from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from craftsman.memory.graph import GraphDB

logger = logging.getLogger(__name__)

try:
    from lightrag import LightRAG, QueryParam
    from lightrag.utils import EmbeddingFunc

    _LIGHTRAG_AVAILABLE = True
except ImportError:
    _LIGHTRAG_AVAILABLE = False

try:
    import networkx as nx

    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False


class LightRAGAdapter:
    """Thin wrapper around LightRAG providing insert/query and GraphDB sync.

    Gracefully degrades to no-ops when lightrag-hku is not installed.
    """

    def __init__(
        self,
        working_dir: str,
        llm_func: Callable,
        embed_func: Callable,
        graph_db: GraphDB,
        embedding_dim: int = 384,
        max_token_size: int = 8192,
    ):
        self._working_dir = working_dir
        self._graph_db = graph_db
        self._available = _LIGHTRAG_AVAILABLE
        if not self._available:
            logger.warning(
                "lightrag-hku not installed; LightRAG features disabled."
            )
            return
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        try:
            self._rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=llm_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=embedding_dim,
                    max_token_size=max_token_size,
                    func=embed_func,
                ),
            )
        except Exception as exc:
            logger.warning(f"LightRAG init failed: {exc}")
            self._available = False

    async def insert(self, text: str, session_id: str = "") -> None:
        if not self._available or not text.strip():
            return
        try:
            await self._rag.ainsert(text)
            self._sync_graph(session_id)
            self._graph_db.save()
        except Exception as exc:
            logger.warning(f"LightRAG insert failed: {exc}")

    async def query(self, query: str, mode: str = "hybrid") -> str:
        if not self._available or not query.strip():
            return ""
        try:
            return await self._rag.aquery(query, param=QueryParam(mode=mode))
        except Exception as exc:
            logger.warning(f"LightRAG query failed: {exc}")
            return ""

    def close(self) -> None:
        if self._available and hasattr(self, "_rag"):
            try:
                if hasattr(self._rag, "close"):
                    self._rag.close()
            except Exception:
                pass

    def _sync_graph(self, session_id: str) -> None:
        """Read LightRAG's GraphML output and merge into our GraphDB."""
        if not _NX_AVAILABLE:
            return
        graphml = (
            Path(self._working_dir) / "graph_chunk_entity_relation.graphml"
        )
        if not graphml.exists():
            return
        try:
            g = nx.read_graphml(str(graphml))
            for node_id, attrs in g.nodes(data=True):
                name = str(node_id)
                self._graph_db.add_entity(
                    name=name,
                    entity_type=attrs.get("entity_type", "unknown"),
                    description=attrs.get("description", ""),
                    layer="session",
                    session_id=session_id,
                )
            for src, dst, attrs in g.edges(data=True):
                self._graph_db.add_relation(
                    str(src),
                    str(dst),
                    description=attrs.get("description", ""),
                    weight=float(attrs.get("weight", 1.0)),
                )
        except Exception as exc:
            logger.warning(f"GraphDB sync failed: {exc}")
