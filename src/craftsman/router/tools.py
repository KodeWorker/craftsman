import json
import time

from fastapi import APIRouter, Depends, Request

from craftsman.memory.librarian import Librarian
from craftsman.router.deps import get_current_user
from craftsman.tools.memory_tools import (
    memory_forget,
    memory_retrieve,
    memory_store,
)
from craftsman.tools.plan_tools import (
    plan_create,
    plan_done,
    task_create,
    task_done,
    task_fail,
    task_list,
    task_start,
    task_verify,
)
from craftsman.tools.registry import seed_registry
from craftsman.tools.schedule_tools import (
    cron_create,
    cron_list,
    cron_remove,
    schedule_at,
    schedule_cancel,
    schedule_list,
)

# (args, db, session_id)
_DB_DISPATCH = {
    "plan:create": plan_create,
    "plan:done": plan_done,
    "task:create": task_create,
    "task:start": task_start,
    "task:verify": task_verify,
    "task:done": task_done,
    "task:fail": task_fail,
    "task:list": task_list,
    "schedule:at": schedule_at,
    "schedule:list": schedule_list,
    "schedule:cancel": schedule_cancel,
    "cron:create": cron_create,
    "cron:list": cron_list,
    "cron:remove": cron_remove,
}

# (args, librarian, session_id)
_LIB_DISPATCH = {
    "memory:store": memory_store,
    "memory:retrieve": memory_retrieve,
    "memory:forget": memory_forget,
}

REMOTE_TOOLS = _DB_DISPATCH.keys() | _LIB_DISPATCH.keys()


class ToolsRouter:
    def __init__(self, librarian: Librarian):
        self.librarian = librarian
        self.router = APIRouter(prefix="/tools", tags=["tools"])
        self.router.post("/seed")(self.seed)
        self.router.post("/invoke")(self.invoke)

    async def seed(self) -> dict:
        seed_registry(self.librarian.structure_db)
        return {"status": "ok"}

    async def invoke(
        self,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        body = await request.json()
        name = body.get("name", "")
        args = body.get("args", {})
        session_id = body.get("session_id")

        db = self.librarian.structure_db

        start = time.monotonic()
        is_error = False
        if name in _DB_DISPATCH:
            result = await _DB_DISPATCH[name](args, db, session_id)
        elif name in _LIB_DISPATCH:
            result = await _LIB_DISPATCH[name](
                args, self.librarian, session_id
            )
        else:
            return {"error": f"Unknown remote tool: {name}"}

        if "error" in result:
            is_error = True
        duration_ms = int((time.monotonic() - start) * 1000)

        try:
            db.increment_tool_call_count(name)
            tool_row = db.get_tool(name)
            if tool_row and tool_row["audited"]:
                db.log_tool_invocation(
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
