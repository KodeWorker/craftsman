import httpx

from craftsman.tools.bash_tools import (
    bash_cat,
    bash_df,
    bash_du,
    bash_find,
    bash_grep,
    bash_head,
    bash_ls,
    bash_ps,
    bash_run,
    bash_stat,
    bash_tail,
    powershell_run,
)
from craftsman.tools.constants import REMOTE_TOOLS
from craftsman.tools.text_tools import (
    commit_tmp,
    discard_tmp,
    text_delete,
    text_insert,
    text_read,
    text_replace,
    text_search,
)

_LOCAL_DISPATCH = {
    "bash:ls": bash_ls,
    "bash:cat": bash_cat,
    "bash:grep": bash_grep,
    "bash:find": bash_find,
    "bash:head": bash_head,
    "bash:tail": bash_tail,
    "bash:stat": bash_stat,
    "bash:ps": bash_ps,
    "bash:df": bash_df,
    "bash:du": bash_du,
    "bash:run": bash_run,
    "powershell:run": powershell_run,
    "text:read": text_read,
    "text:search": text_search,
    "text:replace": text_replace,
    "text:insert": text_insert,
    "text:delete": text_delete,
}


class ToolExecutor:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        token: str,
    ):
        self.http = http_client
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def execute(
        self, name: str, args: dict, session_id: str | None = None
    ) -> dict:
        if name in _LOCAL_DISPATCH:
            try:
                return await _LOCAL_DISPATCH[name](args)
            except Exception as e:
                return {"error": str(e)}

        if name in REMOTE_TOOLS:
            return await self._invoke_remote(name, args, session_id)

        return {"error": f"Unknown tool: {name}"}

    async def _invoke_remote(
        self, name: str, args: dict, session_id: str | None
    ) -> dict:
        try:
            resp = await self.http.post(
                f"{self.base_url}/tools/invoke",
                json={"name": name, "args": args, "session_id": session_id},
                headers={"Authorization": f"Bearer {self.token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def commit_pending(self, file: str, tmp: str) -> dict:
        try:
            bak = commit_tmp(file, tmp)
            return {"status": "committed", "backup": bak}
        except Exception as e:
            return {"error": str(e)}

    async def discard_pending(self, tmp: str) -> dict:
        discard_tmp(tmp)
        return {"status": "discarded"}
