import json
import time

from craftsman.memory.structure import StructureDB
from craftsman.tools.bash_tools import (
    bash_cat,
    bash_df,
    bash_du,
    bash_find,
    bash_grep,
    bash_head,
    bash_ls,
    bash_ps,
    bash_stat,
    bash_tail,
)
from craftsman.tools.text_tools import (
    commit_tmp,
    discard_tmp,
    text_delete,
    text_insert,
    text_read,
    text_replace,
    text_search,
)

_DISPATCH = {
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
    "text:read": text_read,
    "text:search": text_search,
    "text:replace": text_replace,
    "text:insert": text_insert,
    "text:delete": text_delete,
}


class ToolExecutor:
    def __init__(self, db: StructureDB):
        self.db = db

    async def execute(
        self, name: str, args: dict, session_id: str | None = None
    ) -> dict:
        fn = _DISPATCH.get(name)
        if fn is None:
            return {"error": f"Unknown tool: {name}"}

        start = time.monotonic()
        is_error = False
        try:
            result = await fn(args)
            if "error" in result:
                is_error = True
        except Exception as e:
            result = {"error": str(e)}
            is_error = True

        duration_ms = int((time.monotonic() - start) * 1000)

        try:
            self.db.increment_tool_call_count(name)
        except Exception:
            pass

        try:
            tool_row = self.db.get_tool(name)
            if tool_row and tool_row["audited"]:
                self.db.log_tool_invocation(
                    session_id=session_id,
                    tool_name=name,
                    args=json.dumps(args),
                    result=json.dumps(result),
                    duration_ms=duration_ms,
                    is_error=is_error,
                )
        except Exception:
            pass

        return result

    async def commit_pending(self, file: str, tmp: str) -> dict:
        try:
            bak = commit_tmp(file, tmp)
            return {"status": "committed", "backup": bak}
        except Exception as e:
            return {"error": str(e)}

    async def discard_pending(self, tmp: str) -> dict:
        discard_tmp(tmp)
        return {"status": "discarded"}
