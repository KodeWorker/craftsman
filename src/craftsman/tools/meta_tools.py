import json

from craftsman.memory.librarian import Librarian
from craftsman.memory.structure import StructureDB

_SELF_GUARD = "tool:revoke"


async def tool_list(
    args: dict, db: StructureDB, librarian: Librarian, session_id: str
) -> dict:
    category = args.get("category")
    revoked = librarian.get_revoked_tools(session_id)
    rows = db.list_tools(category=category)
    tools = [
        {
            "name": r["name"],
            "description": r["description"],
            "category": r["category"],
        }
        for r in rows
        if r["name"] not in revoked
    ]
    return {"tools": tools}


async def tool_describe(
    args: dict, db: StructureDB, librarian: Librarian, session_id: str
) -> dict:
    name = args.get("name", "").strip()
    if not name:
        return {"error": "name required"}
    revoked = librarian.get_revoked_tools(session_id)
    if name in revoked:
        return {"error": f"Tool '{name}' is revoked"}
    row = db.get_tool(name)
    if not row:
        return {"error": f"Tool not found: {name}"}
    return {
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "audited": bool(row["audited"]),
        "parameters": json.loads(row["schema"]),
    }


async def tool_find(
    args: dict, db: StructureDB, librarian: Librarian, session_id: str
) -> dict:
    keyword = args.get("keyword", "").strip()
    if not keyword:
        return {"error": "keyword required"}
    revoked = librarian.get_revoked_tools(session_id)
    rows = db.search_tools(keyword)
    matches = [r for r in rows if r["name"] not in revoked]
    if not matches:
        return {"error": f"No tools matching '{keyword}'"}
    best = matches[0]
    return {
        "injected_tool": {
            "name": best["name"],
            "description": best["description"],
            "category": best["category"],
            "parameters": json.loads(best["schema"]),
        }
    }


async def tool_revoke(
    args: dict, db: StructureDB, librarian: Librarian, session_id: str
) -> dict:
    name = args.get("name", "").strip()
    if not name:
        return {"error": "name required"}
    if name == _SELF_GUARD:
        return {"error": "tool:revoke cannot revoke itself"}
    librarian.revoke_tool(session_id, name)
    return {"status": "revoked", "name": name}
