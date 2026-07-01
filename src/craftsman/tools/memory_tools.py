from __future__ import annotations

from datetime import datetime, timedelta, timezone

from craftsman.memory.librarian import Librarian
from craftsman.memory.structure import StructureDB


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


_MAX_FACT_CHARS = 4000
_DEFAULT_PRUNE_DAYS = 7


async def memory_promote(
    args: dict,
    db: StructureDB,
    librarian: Librarian,
    session_id: str | None,
) -> dict:
    """Promote ended sessions into the project memory layer.

    For each ended session that has no global_facts entry yet:
      1. Re-ingests messages through LightRAG (entity extraction / KG update).
      2. Promotes GraphDB nodes for that session from layer=session to
         layer=project.
      3. Writes a global_facts row whose content is the last few assistant
         responses (the natural distillation of the conversation).

    Also prunes GraphDB nodes that remain in layer=session after
    `prune_days` days.
    """
    prune_days: int = int(args.get("prune_days", _DEFAULT_PRUNE_DAYS))
    max_chars: int = int(args.get("max_chars", _MAX_FACT_CHARS))

    # sessions already promoted
    already_promoted: set[str] = {
        row["source_session_id"]
        for row in db.get_global_facts(include_expired=True)
        if row["source_session_id"]
    }

    ended_sessions = db.conn.execute(
        "SELECT id, project_id FROM sessions WHERE ended_at IS NOT NULL"
    ).fetchall()

    promoted_ids: list[str] = []
    for sess in ended_sessions:
        sess_id: str = sess["id"]
        project_id: str | None = sess["project_id"]

        if sess_id in already_promoted:
            continue

        messages = db.get_messages(sess_id)
        if not messages:
            continue

        # build ingest text (user + assistant, capped)
        ingest_parts: list[str] = []
        total = 0
        for m in messages:
            if m["role"] not in ("user", "assistant"):
                continue
            chunk = f"[{m['role']}] {m['content']}"
            if total + len(chunk) > max_chars:
                break
            ingest_parts.append(chunk)
            total += len(chunk)

        if ingest_parts:
            await librarian.ingest_message(
                sess_id, "\n".join(ingest_parts), project_id=project_id
            )

        # promote GraphDB nodes for this session
        gdb = librarian.graph_db
        if gdb._available:
            for node, attrs in gdb.graph.nodes(data=True):
                if (
                    attrs.get("session_id") == sess_id
                    and attrs.get("layer") == "session"
                ):
                    gdb.graph.nodes[node]["layer"] = "project"
                    if project_id:
                        gdb.graph.nodes[node]["project_id"] = project_id

        # global_facts: last 3 assistant responses as the distilled keynote
        assistant_texts = [
            m["content"] for m in messages if m["role"] == "assistant"
        ][-3:]
        fact_content = "\n---\n".join(assistant_texts)[:max_chars]

        if fact_content:
            db.add_global_fact(
                content=fact_content,
                source_session_id=sess_id,
                source_project_id=project_id,
            )
            promoted_ids.append(sess_id)

    # prune stale session-layer nodes from the graph
    pruned = 0
    gdb = librarian.graph_db
    if gdb._available and prune_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=prune_days)
        to_remove: list[str] = []
        for node, attrs in list(gdb.graph.nodes(data=True)):
            if attrs.get("layer") != "session":
                continue
            raw = attrs.get("created_at", "")
            if not raw:
                continue
            try:
                created = datetime.fromisoformat(raw)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff:
                    to_remove.append(node)
            except ValueError:
                pass
        for node in to_remove:
            gdb.graph.remove_node(node)
        pruned = len(to_remove)

    if promoted_ids or pruned:
        gdb.save()

    return {
        "promoted_sessions": len(promoted_ids),
        "session_ids": promoted_ids,
        "pruned_graph_nodes": pruned,
    }
