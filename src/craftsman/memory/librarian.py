from craftsman.memory.graph import GraphDB
from craftsman.memory.structure import StructureDB
from craftsman.memory.vector import VectorDB


class Librarian:

    def __init__(self):
        self.structure_db = StructureDB()
        self.vector_db = VectorDB()
        self.graph_db = GraphDB()
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

    def get_tasks(self) -> list:
        return self.cache.setdefault("tasks", [])

    def add_task(self, task: dict) -> None:
        self.get_tasks().append(task)

    def clear_session(self, session_id: str) -> None:
        for slot in ("scratchpad", "state", "context"):
            self.cache.pop(self._key(session_id, slot), None)

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

        return messages, (ctx_used, upload_tokens, download_tokens)
