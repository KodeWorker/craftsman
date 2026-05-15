from craftsman.memory.librarian import Librarian


def _vdb(librarian: Librarian):
    """Return the VectorDB if available, else None."""
    vdb = getattr(librarian, "vector_db", None)
    return vdb if getattr(vdb, "_available", False) else None


async def memory_store(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args["key"]
    value = args["value"]
    sid = session_id or ""
    librarian.set_scratchpad(sid, key, value)

    vdb = _vdb(librarian)
    if vdb is not None:
        vdb.store_chunk(
            chunk_id=f"{sid}:{key}",
            content=str(value),
            session_id=sid,
        )

    return {"status": "stored", "key": key}


async def memory_retrieve(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args.get("key")
    sid = session_id or ""
    scratchpad = librarian.get_scratchpad(sid)

    if key is not None:
        if key in scratchpad:
            return {"key": key, "value": scratchpad[key]}

        # Fall back to vector search for semantically similar stored facts
        vdb = _vdb(librarian)
        if vdb is not None:
            results = vdb.search_chunks(key, top_k=1, session_id=sid)
            if results:
                return {"key": key, "value": results[0]["content"]}

        # Fall back to knowledge graph retrieval via LightRAG
        kg_result = await librarian.retrieve_context(key, sid)
        if kg_result:
            return {"key": key, "value": kg_result}

        return {"error": f"Key not found: {key}"}

    return {"scratchpad": dict(scratchpad)}


async def memory_forget(
    args: dict, librarian: Librarian, session_id: str | None
) -> dict:
    key = args["key"]
    sid = session_id or ""
    scratchpad = librarian.get_scratchpad(sid)
    if key not in scratchpad:
        return {"error": f"Key not found: {key}"}
    del scratchpad[key]

    vdb = _vdb(librarian)
    if vdb is not None:
        vdb.remove_chunk(f"{sid}:{key}")

    return {"status": "forgotten", "key": key}
