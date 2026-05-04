import json

import httpx

_MAX_LOOPS = 10


def make_agent_runner(base_url: str, token: str):
    _base = base_url.rstrip("/")
    _headers = {"Authorization": f"Bearer {token}"}

    async def _execute(
        http: httpx.AsyncClient, name: str, args: dict, session_id: str
    ) -> dict:
        from craftsman.tools.constants import REMOTE_TOOLS
        from craftsman.tools.executor import _LOCAL_DISPATCH

        try:
            if name in _LOCAL_DISPATCH:
                return await _LOCAL_DISPATCH[name](args)
            if name in REMOTE_TOOLS:
                resp = await http.post(
                    f"{_base}/tools/invoke",
                    json={
                        "name": name,
                        "args": args,
                        "session_id": session_id,
                    },
                    headers=_headers,
                )
                resp.raise_for_status()
                return resp.json()
            return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            return {"error": str(e)}

    async def _parse_stream(resp) -> tuple[list[dict], str]:
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

    async def agent_run(args: dict) -> dict:
        prompt = args.get("prompt", "").strip()
        if not prompt:
            return {"error": "prompt is required"}

        async with httpx.AsyncClient(timeout=60.0) as http:
            try:
                resp = await http.post(f"{_base}/sessions/", headers=_headers)
                resp.raise_for_status()
                session_id = resp.json()["session_id"]
            except Exception as e:
                return {"error": f"session create failed: {e}"}

            try:
                async with http.stream(
                    "POST",
                    f"{_base}/sessions/{session_id}/completion",
                    json={
                        "message": {"role": "user", "content": prompt},
                        "tools": ["all"],
                    },
                    headers=_headers,
                ) as resp:
                    resp.raise_for_status()
                    tool_calls, content = await _parse_stream(resp)
            except Exception as e:
                return {"error": str(e)}

            for _ in range(_MAX_LOOPS):
                if not tool_calls:
                    break
                tool_results = [
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": tc["name"],
                        "result": await _execute(
                            http,
                            tc["name"],
                            tc.get("args", {}),
                            session_id,
                        ),
                    }
                    for tc in tool_calls
                ]
                try:
                    async with http.stream(
                        "POST",
                        f"{_base}/sessions/{session_id}/tool_result",
                        json={
                            "tool_results": tool_results,
                            "tools": ["all"],
                        },
                        headers=_headers,
                    ) as resp:
                        resp.raise_for_status()
                        tool_calls, content = await _parse_stream(resp)
                except Exception as e:
                    return {"error": str(e)}

        return {"content": content}

    return agent_run
