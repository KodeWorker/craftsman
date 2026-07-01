from __future__ import annotations

import logging

from craftsman.memory.graph import GraphDB
from craftsman.memory.structure import StructureDB
from craftsman.memory.vector import VectorDB

logger = logging.getLogger(__name__)


class Librarian:

    def __init__(
        self,
        vector_db: VectorDB | None = None,
        graph_db: GraphDB | None = None,
        lightrag_adapter=None,
    ):
        self.structure_db = StructureDB()
        self.vector_db = vector_db if vector_db is not None else VectorDB()
        self.graph_db = graph_db if graph_db is not None else GraphDB()
        self._lightrag = lightrag_adapter
        self.cache: dict = (
            {}
        )  # keyed: "session:{id}:scratchpad|state|context", "tasks"

    # --- cache helpers ---

    def _key(self, session_id: str, slot: str) -> str:
        return f"session:{session_id}:{slot}"

    def get_scratchpad(self, session_id: str) -> dict:
        return self.cache.setdefault(self._key(session_id, "scratchpad"), {})

    def set_scratchpad(self, session_id: str, key: str, value) -> None:
        self.get_scratchpad(session_id)[key] = value

    def get_state(self, session_id: str) -> dict:
        return self.cache.setdefault(self._key(session_id, "state"), {})

    def set_state(self, session_id: str, key: str, value) -> None:
        self.get_state(session_id)[key] = value

    def get_context(self, session_id: str) -> list:
        return self.cache.setdefault(self._key(session_id, "context"), [])

    def push_context(self, session_id: str, message: dict) -> None:
        self.get_context(session_id).append(message)

    def clear_context(self, session_id: str) -> None:
        self.cache[self._key(session_id, "context")] = []

    def clear_system_prompt(self, session_id: str) -> None:
        key = self._key(session_id, "context")
        self.cache[key] = [
            m for m in self.cache.get(key, []) if m.get("role") != "system"
        ]

    def get_tasks(self) -> list:
        return self.cache.setdefault("tasks", [])

    def add_task(self, task: dict) -> None:
        self.get_tasks().append(task)

    def revoke_tool(self, session_id: str, name: str) -> None:
        revoked = self.cache.setdefault(self._key(session_id, "revoked"), [])
        if name not in revoked:
            revoked.append(name)

    def get_revoked_tools(self, session_id: str) -> set:
        return set(self.cache.get(self._key(session_id, "revoked"), []))

    def clear_session(self, session_id: str) -> None:
        for slot in ("scratchpad", "state", "context", "revoked"):
            self.cache.pop(self._key(session_id, slot), None)

    # --- persistence ---

    def store_message(self, session_id: str, message: dict) -> str:
        return self.structure_db.add_message(
            session_id=session_id,
            role=message["role"],
            content=message["content"],
            tokens=message.get("tokens", 0),
        )

    def retrieve_messages(
        self, session_id: str, limit: int = 0
    ) -> tuple[list[dict], tuple[int, int, int]]:
        rows = self.structure_db.get_messages(session_id)
        if limit > 0:
            rows = rows[-limit:]

        messages = [dict(r) for r in rows]

        ctx_used = sum(m.get("tokens", 0) for m in messages)
        upload_tokens = sum(
            m.get("tokens", 0) for m in messages if m.get("role") == "user"
        )
        download_tokens = sum(
            m.get("tokens", 0)
            for m in messages
            if m.get("role") == "assistant"
        )

        return messages, {
            "ctx_used": ctx_used,
            "upload_tokens": upload_tokens,
            "download_tokens": download_tokens,
        }

    # --- RAG: ingest + retrieve ---

    async def ingest_message(
        self,
        session_id: str,
        text: str,
        project_id: str | None = None,
    ) -> None:
        """Fire-and-forget: extract entities from text into LightRAG + GraphDB.

        Must never raise — ingest failure must not affect the chat response.
        """
        if self._lightrag is None or not text.strip():
            return
        try:
            await self._lightrag.insert(text, session_id=session_id)
        except Exception as exc:
            logger.warning(f"ingest_message failed: {exc}")

    async def retrieve_context(
        self, query: str, session_id: str, top_k: int = 5
    ) -> str:
        """Return a formatted retrieval block to inject before the LLM call.

        Returns ``""`` when nothing is available (LightRAG disabled, query
        empty, or retrieval returns nothing useful).
        """
        if self._lightrag is None or not query.strip():
            return ""
        try:
            result = await self._lightrag.query(query, mode="hybrid")
            if result and result.strip():
                return f"[Retrieved context]\n{result}"
        except Exception as exc:
            logger.warning(f"retrieve_context failed: {exc}")
        return ""

    def close_session_memory(self, session_id: str) -> None:
        """Flush the knowledge graph to disk. Called at session end/compact."""
        self.graph_db.save()

    def close(self) -> None:
        """Flush and release all memory resources at server shutdown."""
        self.graph_db.save()
        self.vector_db.close()
        if self._lightrag is not None:
            self._lightrag.close()
