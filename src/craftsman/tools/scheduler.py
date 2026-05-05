import asyncio
import json
import logging

import httpx

from craftsman.tools.constants import REMOTE_TOOLS
from craftsman.tools.executor import _LOCAL_DISPATCH
from craftsman.tools.registry import register_agent_runner

_log = logging.getLogger(__name__)

POLL_INTERVAL = 30


class JobDispatcher:
    """Client-side dispatcher — tools run on the user's machine.

    Polls /jobs/due on the server; executes local tools directly,
    remote tools via /tools/invoke.
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
        register_agent_runner(self.base_url, self.token)
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

    # ── Job execution ────────────────────────────────────────────────────

    async def _run_job(self, tool_call: dict) -> dict:
        name = tool_call["name"]
        args = tool_call.get("args", {})
        try:
            return await self._execute(name, args, session_id="")
        except Exception as e:
            return {"error": str(e)}

    # ── Scheduler tick ───────────────────────────────────────────────────

    async def _tick(self) -> None:
        resp = await self._http.get(
            f"{self.base_url}/jobs/due", headers=self._headers
        )
        if resp.status_code == 401:
            _log.error(
                "Dispatcher token expired"
                " — restart the client to re-authenticate."
            )
            return
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
