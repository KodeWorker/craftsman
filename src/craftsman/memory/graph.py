from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import networkx as nx

    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False

_DEFAULT_PATH = os.path.expanduser("~/.craftsman/database/graph.gml")


class GraphDB:
    """NetworkX DiGraph persisted to GML.

    All methods are no-ops when networkx is unavailable, so callers can always
    invoke them unconditionally.

    Node IDs are the entity/chunk names (strings). GML round-trip relies on
    networkx storing the original string key as a ``label`` attribute and
    reading back with ``label='label'``.
    """

    def __init__(self, gml_path: str | Path | None = None):
        self._gml_path = Path(gml_path) if gml_path else Path(_DEFAULT_PATH)
        self._available = _NX_AVAILABLE
        self.graph = self._load() if _NX_AVAILABLE else None

    # --- init ---

    def _load(self):
        if self._gml_path.exists():
            try:
                return nx.read_gml(str(self._gml_path), label="label")
            except Exception:
                pass
        return nx.DiGraph()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- nodes ---

    def add_entity(
        self,
        name: str,
        entity_type: str,
        description: str,
        layer: str = "session",
        session_id: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        if not self._available:
            return
        attrs = {
            "label": name,
            "node_type": "entity",
            "entity_type": entity_type,
            "description": description,
            "layer": layer,
            "session_id": session_id or "",
            "created_at": self._now(),
            "expires_at": expires_at or "",
        }
        if self.graph.has_node(name):
            self.graph.nodes[name].update(attrs)
        else:
            self.graph.add_node(name, **attrs)

    def add_chunk(
        self,
        chunk_id: str,
        content: str,
        session_id: str,
        tokens: int = 0,
    ) -> None:
        if not self._available:
            return
        self.graph.add_node(
            chunk_id,
            label=chunk_id,
            node_type="chunk",
            content=content,
            session_id=session_id,
            tokens=tokens,
            created_at=self._now(),
        )

    def get_entity(self, name: str) -> dict | None:
        if not self._available or not self.graph.has_node(name):
            return None
        return dict(self.graph.nodes[name])

    # --- edges ---

    def add_relation(
        self,
        source: str,
        target: str,
        description: str = "",
        weight: float = 1.0,
    ) -> None:
        if not self._available:
            return
        self.graph.add_edge(
            source,
            target,
            edge_type="RELATED_TO",
            description=description,
            weight=weight,
            created_at=self._now(),
        )

    def add_mention(self, entity_name: str, chunk_id: str) -> None:
        if not self._available:
            return
        self.graph.add_edge(entity_name, chunk_id, edge_type="MENTIONED_IN")

    # --- queries ---

    def query_neighbors(self, name: str, depth: int = 1) -> list[dict]:
        """BFS up to ``depth`` hops; returns entity node dicts (not chunks)."""
        if not self._available or not self.graph.has_node(name):
            return []
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(name, 0)]
        results: list[dict] = []
        while queue:
            node, d = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            attrs = self.graph.nodes[node]
            if node != name and attrs.get("node_type") == "entity":
                results.append({"name": node, **attrs})
            if d < depth:
                for nb in list(self.graph.successors(node)) + list(
                    self.graph.predecessors(node)
                ):
                    if nb not in visited:
                        queue.append((nb, d + 1))
        return results

    # --- persistence ---

    def save(self) -> None:
        if not self._available:
            return
        try:
            self._gml_path.parent.mkdir(parents=True, exist_ok=True)
            nx.write_gml(self.graph, str(self._gml_path))
        except Exception:
            pass

    def close(self) -> None:
        self.save()
