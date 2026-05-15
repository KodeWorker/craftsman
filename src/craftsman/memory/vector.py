from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable

from craftsman.configure import get_config

try:
    import sqlite_vec

    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False


class VectorDB:
    """sqlite-vec backed vector store for tools and memory chunks.

    All methods are no-ops when sqlite-vec is unavailable or embed_fn is None,
    so callers can always call them unconditionally and rely on the graceful
    degradation path (LIKE-based fallback in tool:find etc.).

    Uses the same craftsman.db file as StructureDB; loads the sqlite-vec
    extension on a separate connection.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        embed_fn: Callable[[str], list[float]] | None = None,
        dimensions: int = 384,
    ):
        if db_path is None:
            config = get_config()
            db_dir = Path(
                os.path.expanduser(
                    config.get("workspace", {}).get(
                        "database", "~/.craftsman/database"
                    )
                )
            )
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "craftsman.db"
        self._embed_fn = embed_fn
        self._dimensions = dimensions
        self._available = _SQLITE_VEC_AVAILABLE and embed_fn is not None
        if not self._available:
            return
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS tools_vec USING vec0(
                name      TEXT PRIMARY KEY,
                embedding FLOAT[{self._dimensions}]
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                chunk_id  TEXT PRIMARY KEY,
                embedding FLOAT[{self._dimensions}]
            );
            CREATE TABLE IF NOT EXISTS chunks_meta (
                chunk_id   TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                content    TEXT NOT NULL
            );
        """
        )
        self._conn.commit()

    def _serialize(self, embedding: list[float]) -> bytes:
        return sqlite_vec.serialize_float32(embedding)

    def _embed(self, text: str) -> list[float] | None:
        try:
            return self._embed_fn(text)
        except Exception:
            return None

    # --- tools ---

    def store_tool(self, name: str, description: str) -> None:
        if not self._available:
            return
        emb = self._embed(f"{name}: {description}")
        if emb is None:
            return
        # vec0 TEXT primary keys don't support OR REPLACE — delete first
        self._conn.execute("DELETE FROM tools_vec WHERE name = ?", [name])
        self._conn.execute(
            "INSERT INTO tools_vec(name, embedding) VALUES (?, ?)",
            [name, self._serialize(emb)],
        )
        self._conn.commit()

    def search_tools(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._available:
            return []
        emb = self._embed(query)
        if emb is None:
            return []
        rows = self._conn.execute(
            """
            SELECT name, distance
            FROM tools_vec
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            [self._serialize(emb), top_k],
        ).fetchall()
        return [
            {"name": row["name"], "distance": row["distance"]} for row in rows
        ]

    def seed_from_registry(self, db) -> None:
        """Idempotent: embed all tools in StructureDB into tools_vec."""
        if not self._available:
            return
        for row in db.list_tools():
            self.store_tool(row["name"], row["description"])

    # --- memory chunks ---

    def store_chunk(
        self, chunk_id: str, content: str, session_id: str
    ) -> None:
        if not self._available:
            return
        emb = self._embed(content)
        if emb is None:
            return
        # vec0 TEXT primary keys don't support OR REPLACE — delete first
        self._conn.execute(
            "DELETE FROM chunks_vec WHERE chunk_id = ?", [chunk_id]
        )
        self._conn.execute(
            "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
            [chunk_id, self._serialize(emb)],
        )
        self._conn.execute(
            """INSERT INTO chunks_meta(chunk_id, session_id, content)
               VALUES (?, ?, ?)
               ON CONFLICT(chunk_id) DO UPDATE
               SET content = excluded.content""",
            [chunk_id, session_id, content],
        )
        self._conn.commit()

    def search_chunks(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
    ) -> list[dict]:
        if not self._available:
            return []
        emb = self._embed(query)
        if emb is None:
            return []
        rows = self._conn.execute(
            """
            SELECT chunk_id, distance
            FROM chunks_vec
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            [self._serialize(emb), top_k],
        ).fetchall()
        results = []
        for row in rows:
            meta = self._conn.execute(
                "SELECT content, session_id FROM chunks_meta"
                " WHERE chunk_id = ?",
                [row["chunk_id"]],
            ).fetchone()
            if meta is None:
                continue
            if session_id and meta["session_id"] != session_id:
                continue
            results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "content": meta["content"],
                    "session_id": meta["session_id"],
                    "distance": row["distance"],
                }
            )
        return results

    def remove_chunk(self, chunk_id: str) -> None:
        if not self._available:
            return
        self._conn.execute(
            "DELETE FROM chunks_vec WHERE chunk_id = ?", [chunk_id]
        )
        self._conn.execute(
            "DELETE FROM chunks_meta WHERE chunk_id = ?", [chunk_id]
        )
        self._conn.commit()
