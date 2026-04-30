import json
import time

from fastapi import APIRouter, Depends, Request

from craftsman.memory.librarian import Librarian
from craftsman.router.deps import get_current_user
from craftsman.tools.constants import DB_DISPATCH as _DB_DISPATCH
from craftsman.tools.constants import LIB_DISPATCH as _LIB_DISPATCH
from craftsman.tools.registry import seed_registry


class ToolsRouter:
    def __init__(self, librarian: Librarian):
        self.librarian = librarian
        self.router = APIRouter(prefix="/tools", tags=["tools"])
        self.router.post("/seed")(self.seed)
        self.router.post("/invoke")(self.invoke)

    async def seed(self, user_id: str = Depends(get_current_user)) -> dict:
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
