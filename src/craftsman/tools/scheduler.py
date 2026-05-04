import asyncio
import json
import logging

import httpx

from craftsman.tools.constants import REMOTE_TOOLS
from craftsman.tools.executor import _LOCAL_DISPATCH

_log = logging.getLogger(__name__)

POLL_INTERVAL = 30
MAX_AGENT_LOOPS = 10


class JobDispatcher:
    """Client-side dispatcher — tools run on the user's machine.

    Polls /jobs/due on the server; executes local tools directly,
    remote tools via /tools/invoke; drives agent:run via the HTTP
    streaming completion loop.
    """

    def __init__(self, base_url: str, token: str, on_result=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http: httpx.AsyncClient | None = None
        self._on_result = on_result  # async callable(name, result) | None

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def run_loop(self) -> None:
        async with httpx.AsyncClient(timeout=60.0) as http:
            self._http = http
            while True:
                try:
                    await self._tick()
                except Exception as e:
                    _log.error(f"Dispatcher tick error: {e}")
                await asyncio.sleep(POLL_INTERVAL)

    # ── Tool dispatch ────────────────────────────────────────────────────

    async def _execute(self, name: str, args: dict, session_id: str) -> dict:
        try:
            if name in _LOCAL_DISPATCH:
                return await _LOCAL_DISPATCH[name](args)
            if name in REMOTE_TOOLS:
                resp = await self._http.post(
                    f"{self.base_url}/tools/invoke",
                    json={
                        "name": name,
                        "args": args,
                        "session_id": session_id,
                    },
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json()
            return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Session lifecycle ────────────────────────────────────────────────

    async def _create_session(self) -> str:
        resp = await self._http.post(
            f"{self.base_url}/sessions/", headers=self._headers
        )
        resp.raise_for_status()
        return resp.json()["session_id"]

    # ── Job execution ────────────────────────────────────────────────────

    async def _run_job(self, tool_call: dict) -> dict:
        session_id = await self._create_session()
        name = tool_call["name"]
        args = tool_call.get("args", {})
        try:
            if name == "agent:run":
                return await self._run_agent(args, session_id)
            return await self._execute(name, args, session_id)
        except Exception as e:
            return {"error": str(e)}

    async def _run_agent(self, args: dict, session_id: str) -> dict:
        prompt = args.get("prompt", "").strip()
        if not prompt:
            return {"error": "prompt is required"}

        tools = ["all"]
        content = ""

        async with self._http.stream(
            "POST",
            f"{self.base_url}/sessions/{session_id}/completion",
            json={
                "message": {"role": "user", "content": prompt},
                "tools": tools,
            },
            headers=self._headers,
        ) as resp:
            resp.raise_for_status()
            tool_calls, content = await self._parse_stream(resp)

        for _ in range(MAX_AGENT_LOOPS):
            if not tool_calls:
                break
            tool_results = [
                {
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "result": await self._execute(
                        tc["name"], tc.get("args", {}), session_id
                    ),
                }
                for tc in tool_calls
            ]
            async with self._http.stream(
                "POST",
                f"{self.base_url}/sessions/{session_id}/tool_result",
                json={"tool_results": tool_results, "tools": tools},
                headers=self._headers,
            ) as resp:
                resp.raise_for_status()
                tool_calls, content = await self._parse_stream(resp)

        return {"content": content}

    async def _parse_stream(
        self, resp: httpx.Response
    ) -> tuple[list[dict], str]:
        tool_calls: list[dict] = []
        content_parts: list[str] = []
        async for line in resp.aiter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = chunk.get("kind")
            if kind == "tool_call":
                tool_calls.append(chunk)
            elif kind == "content":
                content_parts.append(chunk.get("text", ""))
        return tool_calls, "".join(content_parts)

    # ── Scheduler tick ───────────────────────────────────────────────────

    async def _tick(self) -> None:
        resp = await self._http.get(
            f"{self.base_url}/jobs/due", headers=self._headers
        )
        if resp.status_code != 200:
            _log.warning(f"GET /jobs/due failed: {resp.status_code}")
            return
        data = resp.json()
        await self._run_scheduled(data.get("scheduled", []))
        await self._run_cron(data.get("cron", []))

    async def _notify(self, name: str, result: dict) -> None:
        if self._on_result:
            try:
                await self._on_result(name, result)
            except Exception as e:
                _log.error(f"on_result callback error: {e}")

    async def _run_scheduled(self, jobs: list[dict]) -> None:
        for job in jobs:
            job_id = job["id"]
            try:
                tc = json.loads(job["tool_call"])
                result = await self._run_job(tc)
                status = "failed" if "error" in result else "done"
                await self._http.post(
                    f"{self.base_url}/jobs/scheduled/{job_id}/result",
                    json={"status": status, "result": result},
                    headers=self._headers,
                )
                _log.info(f"Job {job_id}: {tc['name']} → {status}")
                await self._notify(tc["name"], result)
            except Exception as e:
                _log.error(f"Job {job_id} failed: {e}")
                await self._http.post(
                    f"{self.base_url}/jobs/scheduled/{job_id}/result",
                    json={"status": "failed", "result": {"error": str(e)}},
                    headers=self._headers,
                )
                await self._notify(
                    job.get("tool_call", "?"), {"error": str(e)}
                )

    async def _run_cron(self, jobs: list[dict]) -> None:
        for job in jobs:
            cron_id = job["id"]
            try:
                tc = json.loads(job["tool_call"])
                result = await self._run_job(tc)
                await self._http.post(
                    f"{self.base_url}/jobs/cron/{cron_id}/result",
                    json={"result": result},
                    headers=self._headers,
                )
                outcome = "err" if "error" in result else "ok"
                _log.info(
                    f"Cron {cron_id} ({job['expression']}):"
                    f" {tc['name']} → {outcome}"
                )
                await self._notify(tc["name"], result)
            except Exception as e:
                _log.error(f"Cron {cron_id} error: {e}")
                await self._http.post(
                    f"{self.base_url}/jobs/cron/{cron_id}/result",
                    json={"result": {"error": str(e)}},
                    headers=self._headers,
                )
                await self._notify(
                    job.get("tool_call", "?"), {"error": str(e)}
                )
