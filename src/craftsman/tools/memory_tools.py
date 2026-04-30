# TODO(p7): upgrade memory_store/retrieve/forget to use vector DB and
# knowledge graph via librarian once Phase 7 memory is implemented.
from craftsman.memory.librarian import Librarian


async def memory_store(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args["key"]
    value = args["value"]
    librarian.set_scratchpad(session_id or "", key, value)
    return {"status": "stored", "key": key}


async def memory_retrieve(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args.get("key")
    scratchpad = librarian.get_scratchpad(session_id or "")
    if key is not None:
        if key not in scratchpad:
            return {"error": f"Key not found: {key}"}
        return {"key": key, "value": scratchpad[key]}
    return {"scratchpad": dict(scratchpad)}


async def memory_forget(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args["key"]
    scratchpad = librarian.get_scratchpad(session_id or "")
    if key not in scratchpad:
        return {"error": f"Key not found: {key}"}
    del scratchpad[key]
    return {"status": "forgotten", "key": key}
