# Phase 7: Memory — Vector Search, Knowledge Graph, LightRAG

Upgrade the memory layer from a scratchpad + SQLite LIKE baseline to a
full retrieval-augmented generation (RAG) architecture: sqlite-vec for
semantic tool search, LightRAG + NetworkX for entity extraction and
knowledge graph persistence, and automatic injection of long-term context
into every LLM call.

---

## Architecture

```
User message
     │
     ▼
router/sessions.py ──► librarian.store_message()  ──► SQLite messages
     │
     │  asyncio.create_task (non-blocking)
     ▼
librarian.ingest_message(text, session_id, project_id)       7.4
     │
     └──► LightRAGAdapter.insert(text)                        7.3
               │
               ├──► LLM: entity / relation extraction
               ├──► NetworkX graph (graph.gml)               7.2
               └──► LightRAG built-in vector store
                    (~/.craftsman/database/lightrag/)

Before LLM call:  librarian.retrieve_context(query, session_id)  7.4
     │
     ├──► LightRAGAdapter.query(query, mode="hybrid")
     │         → entity facts + relevant text chunks
     └──► injected as {"role":"system"} block in messages

tool:find query  ──►  VectorDB.search_tools(query)           7.1
                          (sqlite-vec tools_vec table)
```

**Two independent vector backends:**
- `sqlite-vec` (`VectorDB`) — tools registry embedding; powers semantic `tool:find`
- LightRAG built-in nano-vectordb — conversation chunks + extracted entities;
  powers `retrieve_context`

---

## Dependency Chain

```
7.1 (VectorDB / sqlite-vec)      7.2 (GraphDB / NetworkX)
       │                                  │
       └──────────────┬───────────────────┘
                      ▼
              7.3 (LightRAGAdapter)
                      │
                      ▼
              7.4 (Librarian: ingest + retrieve)
                      │
                      ▼
              7.5 (session hooks + tool:find + memory tools)
```

7.1 and 7.2 are independent of each other and can be implemented in parallel.

---

## 7.1 — VectorDB: sqlite-vec Tools Embedding

Implement `VectorDB` backed by sqlite-vec to embed and semantically search
the tool registry. This sub-phase is the `tool:find` upgrade only — conversation
chunks are handled by LightRAG in 7.3.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/memory/vector.py` | Full `VectorDB` implementation (replaces stub) |
| `pyproject.toml` | Add `sqlite-vec>=0.1` |

### Design notes

**`VectorDB.__init__(db_path: str, embed_func: Callable)`**
- Load sqlite-vec extension: `conn.enable_load_extension(True)` + `sqlite_vec.load(conn)`
- Create `tools_vec` virtual table if not exists:
  ```sql
  CREATE VIRTUAL TABLE IF NOT EXISTS tools_vec
  USING vec0(name TEXT, embedding FLOAT[384])
  ```
- Dimension 384 matches `all-MiniLM-L6-v2` (the default embed model)

**`embed_func`** — injected at construction; in practice this is a thin
wrapper around `litellm.embedding()` so the same LLM config is reused.

**`store_tool(name: str, description: str)`**
- Embed `name + ": " + description` → 384-dim float list
- `INSERT OR REPLACE INTO tools_vec(name, embedding) VALUES (?, ?)`

**`search_tools(query: str, top_k: int = 5) -> list[dict]`**
- Embed query → cosine search via sqlite-vec `knn_search`:
  ```sql
  SELECT name, distance
  FROM tools_vec
  WHERE embedding MATCH ?
  ORDER BY distance
  LIMIT ?
  ```
- Returns `[{"name": ..., "distance": ...}, ...]`

**Startup seeding** — `server.py` lifespan calls `vector_db.seed_from_registry(db)`
(new method) that iterates `StructureDB.list_tools()` and calls `store_tool`
for any name not already in `tools_vec`. Idempotent.

### Checklist

- [ ] `src/craftsman/memory/vector.py` — `VectorDB` class with `__init__`,
      `store_tool`, `search_tools`, `seed_from_registry`
- [ ] `pyproject.toml` — `sqlite-vec>=0.1`
- [ ] `tests/unit/memory/test_vector.py` — store 5 tools, semantic search
      returns correct top-1; idempotent re-seed; missing query returns empty list

### Verify

```bash
uv run pytest tests/unit/memory/test_vector.py
# Manual:
uv run python -c "
from craftsman.memory.vector import VectorDB
vdb = VectorDB(':memory:')
vdb.store_tool('bash:grep', 'Search file contents with regex patterns')
vdb.store_tool('text:read', 'Read a file and return its lines')
print(vdb.search_tools('find text in files'))
"
```

---

## 7.2 — GraphDB: NetworkX File-Backed Knowledge Graph

Implement `GraphDB` as a thin wrapper around a NetworkX `DiGraph` that
persists to `~/.craftsman/database/graph.gml`.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/memory/graph.py` | Full `GraphDB` implementation (replaces stub) |
| `pyproject.toml` | Add `networkx>=3.0` |

### Design notes

**`GraphDB.__init__(gml_path: str)`**
- If `gml_path` exists: `nx.read_gml(gml_path)` → `self.graph`
- Else: `self.graph = nx.DiGraph()`

**Node schema (Entity)**
```python
{
  "node_type": "entity",
  "name": str,
  "entity_type": str,          # person, project, concept, tool, …
  "description": str,
  "layer": str,                # "session" | "project" | "global"
  "session_id": str | None,
  "created_at": str,           # ISO 8601
  "expires_at": str | None,    # ISO 8601; None = never expires
}
```

**Node schema (Chunk)**
```python
{
  "node_type": "chunk",
  "chunk_id": str,
  "content": str,
  "session_id": str,
  "tokens": int,
  "created_at": str,
}
```

**Edge types**
- `RELATED_TO` (Entity → Entity): `{description, weight, created_at}`
- `MENTIONED_IN` (Entity → Chunk): `{}`

**Methods**
- `add_entity(name, entity_type, description, layer, session_id, expires_at=None)`
  — `nx.DiGraph.add_node(name, **attrs)`; update if already exists
- `add_chunk(chunk_id, content, session_id, tokens)`
- `add_relation(source, target, description, weight=1.0)`
  — `add_edge(source, target, type="RELATED_TO", ...)`
- `add_mention(entity_name, chunk_id)`
  — `add_edge(entity_name, chunk_id, type="MENTIONED_IN")`
- `get_entity(name) -> dict | None`
- `query_neighbors(name, depth=1) -> list[dict]`
  — BFS up to `depth` hops; returns list of entity node dicts
- `save()` — `nx.write_gml(self.graph, self.gml_path)`
- `close()` — alias for `save()`

### Checklist

- [ ] `src/craftsman/memory/graph.py` — `GraphDB` class with all methods above
- [ ] `pyproject.toml` — `networkx>=3.0`
- [ ] `tests/unit/memory/test_graph.py` — add/get entity, add relation, query
      neighbors depth-1 and depth-2, GML round-trip (save + reload), missing node
      returns None

### Verify

```bash
uv run pytest tests/unit/memory/test_graph.py
# Manual:
uv run python -c "
import tempfile, os
from craftsman.memory.graph import GraphDB
with tempfile.NamedTemporaryFile(suffix='.gml', delete=False) as f:
    path = f.name
gdb = GraphDB(path)
gdb.add_entity('Alice', 'person', 'A software engineer', 'session', 's1')
gdb.add_entity('craftsman', 'project', 'The agent framework', 'project', None)
gdb.add_relation('Alice', 'craftsman', 'works on')
print(gdb.query_neighbors('Alice'))
gdb.save()
gdb2 = GraphDB(path)
print(gdb2.get_entity('Alice'))
os.unlink(path)
"
```

---

## 7.3 — LightRAG Adapter

Thin adapter that wires `lightrag-hku` to our `GraphDB` and provides
`insert` / `query` interfaces consumed by the `Librarian`.

LightRAG manages its own vector store in
`~/.craftsman/database/lightrag/`; `GraphDB` wraps the result graph.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/memory/lightrag_adapter.py` | New file — `LightRAGAdapter` |
| `pyproject.toml` | Add `lightrag-hku>=1.0` |

### Design notes

**Initialization**

```python
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc

class LightRAGAdapter:
    def __init__(self, working_dir: str, llm_func, embed_func, graph_db: GraphDB):
        self._rag = LightRAG(
            working_dir=working_dir,    # ~/.craftsman/database/lightrag/
            llm_model_func=llm_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=384,
                max_token_size=512,
                func=embed_func,
            ),
        )
        self._graph_db = graph_db
```

**`async insert(text: str, session_id: str)`**
- `await self._rag.ainsert(text)`
- LightRAG extracts entities/relations via LLM, stores in its internal
  vector store and internal NetworkX graph
- After insert, sync extracted nodes back to our `GraphDB`:
  walk `self._rag.chunk_entity_relation_graph` and call
  `graph_db.add_entity` / `graph_db.add_relation` for new nodes/edges;
  tag each with `session_id` and `layer="session"`
- Sync is best-effort: wrapped in `try/except` — insert failure must
  never block the main chat response

**`async query(query: str, mode="hybrid") -> str`**
- `return await self._rag.aquery(query, param=QueryParam(mode=mode))`
- Returns a free-text context summary

**LLM / embed function factories** — `server.py` builds these from the
configured provider using `litellm`:
```python
async def _llm_func(prompt, **kwargs):
    return await litellm.acompletion(model=..., messages=[{"role":"user","content":prompt}], ...)

async def _embed_func(texts):
    resp = await litellm.aembedding(model=..., input=texts)
    return [d["embedding"] for d in resp.data]
```

### Checklist

- [ ] `src/craftsman/memory/lightrag_adapter.py` — `LightRAGAdapter` class
- [ ] `pyproject.toml` — `lightrag-hku>=1.0`
- [ ] `src/craftsman/server.py` — build `llm_func` + `embed_func` from provider
      config; pass to `LightRAGAdapter.__init__`; store on `Librarian`
- [ ] `tests/unit/memory/test_lightrag_adapter.py` — mock `LightRAG.ainsert` /
      `aquery`; verify `insert` calls `ainsert` and syncs to `GraphDB`;
      verify `query` delegates to `aquery`

### Verify

```bash
uv run pytest tests/unit/memory/test_lightrag_adapter.py
# Integration (requires live LLM key):
uv run craftsman dev
# In chat: "Remember that the project uses SQLite"
# Then: "What database does this project use?" — verify RAG context injected
```

---

## 7.4 — Librarian: ingest_message + retrieve_context

Wire `LightRAGAdapter` and `VectorDB` into `Librarian` with two new public
methods and a session-close flush.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/memory/librarian.py` | Add `ingest_message`, `retrieve_context`, `close_session_memory` |

### Design notes

**`Librarian.__init__` changes**
- Accept `lightrag_adapter: LightRAGAdapter | None = None` — `None` when
  LightRAG is disabled or unavailable (graceful degradation)
- `self.vector_db` already instantiated; now receives real `VectorDB`
- `self.graph_db` already instantiated; now receives real `GraphDB`

**`async ingest_message(session_id: str, text: str, project_id: str | None = None)`**
- Guard: if `self._lightrag is None` or `text` is empty → return immediately
- `await self._lightrag.insert(text, session_id)` — entity extraction +
  vector storage; errors caught and logged, never raised
- No return value; caller uses `asyncio.create_task(...)` to fire-and-forget

**`async retrieve_context(query: str, session_id: str, top_k: int = 5) -> str`**
- Guard: if `self._lightrag is None` → return `""`
- `result = await self._lightrag.query(query, mode="hybrid")`
- If `result` is non-empty: return `f"[Retrieved context]\n{result}"`
- Else return `""`

**`close_session_memory(session_id: str)`**
- `self.graph_db.save()` — flush NetworkX graph to GML
- Then `self.clear_session(session_id)` (already exists)

### Checklist

- [ ] `librarian.py` — `ingest_message`, `retrieve_context`, `close_session_memory`
- [ ] `librarian.py` — `__init__` accepts `lightrag_adapter` kwarg;
      falls back to `None` if not passed (keeps existing tests green)
- [ ] `tests/unit/memory/test_librarian.py` — extend with: ingest with None
      adapter is no-op; retrieve with None adapter returns ""; close_session_memory
      calls graph_db.save(); graceful error handling in ingest

### Verify

```bash
uv run pytest tests/unit/memory/test_librarian.py
```

---

## 7.5 — Session Hooks, tool:find Upgrade, Memory Tools Upgrade

Wire ingestion + retrieval into the session router; upgrade `tool:find`
from SQLite LIKE to vector semantic search; upgrade `memory:store/retrieve`
to persist facts in the vector store.

### Files

| Path | Change |
|------|--------|
| `src/craftsman/router/sessions.py` | 3 hook points: ingest after store, inject before LLM, close at session end |
| `src/craftsman/tools/meta_tools.py` | `tool:find` → `vector_db.search_tools` |
| `src/craftsman/tools/memory_tools.py` | `memory:store/retrieve/forget` → vector-backed |
| `src/craftsman/server.py` | Build and inject `LightRAGAdapter` + `VectorDB` into `Librarian` |
| `docs/schema.md` | Document `tools_vec` virtual table |

### Design notes

**`sessions.py` — ingest hook** (after each `store_message` call for user
and assistant messages):
```python
asyncio.create_task(
    self.librarian.ingest_message(session_id, message["content"], project_id)
)
```

**`sessions.py` — retrieval injection** (inside `_stream_completion`, before
building `tool_schemas`):
```python
user_text = next(
    (m["content"] for m in reversed(context) if m["role"] == "user"), ""
)
if user_text:
    retrieval = await self.librarian.retrieve_context(user_text, session_id)
    if retrieval:
        context = [context[0], {"role": "system", "content": retrieval}] + context[1:]
```
Insert after the first system prompt (index 0) so it has lower priority than
the main system prompt but higher than history.

**`sessions.py` — session close hook** (`compact_session` and
`delete_session` paths):
```python
self.librarian.close_session_memory(session_id)
```

**`meta_tools.py` — `tool:find` upgrade**
```python
# Before (7.5):
results = db.search_tools(keyword)

# After (7.5):
results = await librarian.vector_db.search_tools(keyword, top_k=5)
# Then fetch full schemas: [db.get_tool(r["name"]) for r in results]
```
`tool:find` signature becomes `async`; executor dispatch updated accordingly.

**`memory_tools.py` — upgrades**
- `memory:store` — store to scratchpad (existing) **and** call
  `vector_db.store_chunk(key, value, session_id, project_id, layer="session")`
  so the fact is semantically retrievable
- `memory:retrieve` — first check scratchpad; if missing, call
  `vector_db.search_chunks(key, top_k=1)` and return best match value
- `memory:forget` — remove from scratchpad (existing) + mark chunk expired
  in `text_chunks_vec` (delete by `chunk_id`)

For `memory_tools` to call `vector_db`, the `executor.py` dispatch must
pass `librarian` — it already does.

### Checklist

- [ ] `router/sessions.py` — ingest hook (user + assistant messages)
- [ ] `router/sessions.py` — retrieval injection before LLM call
- [ ] `router/sessions.py` — `close_session_memory` at compact/delete
- [ ] `tools/meta_tools.py` — `tool:find` uses `vector_db.search_tools`;
      falls back to `db.search_tools` if `vector_db` unavailable
- [ ] `tools/memory_tools.py` — `memory:store` writes to vector; `memory:retrieve`
      falls back to vector; `memory:forget` removes from vector
- [ ] `server.py` — build `VectorDB(db_path, embed_func)` and
      `LightRAGAdapter(working_dir, llm_func, embed_func, graph_db)`;
      pass both to `Librarian`; call `vector_db.seed_from_registry(db)` in lifespan
- [ ] `docs/schema.md` — add `tools_vec` virtual table entry
- [ ] `tests/unit/tools/test_meta_tools.py` — `tool:find` returns semantic match
      (not just substring); vector unavailable falls back gracefully
- [ ] `tests/unit/tools/test_memory_tools.py` — store persists to vector;
      retrieve hits vector on cache miss; forget removes from vector
- [ ] `tests/unit/test_sessions_memory.py` — ingest fires as task; retrieval
      block inserted when non-empty; close_session_memory called on compact

### Verify

```bash
uv run pytest tests/unit/
# Semantic tool:find:
# craftsman chat → "find a tool for searching file contents"
# Expected: bash:grep returned (not requiring keyword "grep")
#
# Cross-session retrieval:
# Session A: "Remember I use pytest for all tests"
# Session B (new): "How should I run tests?" — verify "pytest" surfaces
```

---

## Graceful Degradation

All Phase 7 features are **opt-in via availability**, not config flags.
If `sqlite-vec` fails to load or `lightrag-hku` is not installed:

| Component | Fallback |
|-----------|---------|
| `VectorDB` init fails | `tool:find` falls back to SQLite LIKE; `memory:store` skips vector write |
| `LightRAGAdapter` init fails | `ingest_message` and `retrieve_context` are no-ops; `Librarian` logs a warning |
| `GraphDB` save fails | Error logged; chat response unaffected |

The fallback in each case is the Phase 5/6 behaviour — existing unit tests
must continue to pass without `sqlite-vec` or `lightrag-hku` installed.

---

## Dependencies Added

| Package | Purpose | Sub-phase |
|---------|---------|-----------|
| `sqlite-vec>=0.1` | Vector similarity search in SQLite | 7.1 |
| `networkx>=3.0` | In-memory knowledge graph | 7.2 |
| `lightrag-hku>=1.0` | Entity extraction + hybrid RAG orchestration | 7.3 |
