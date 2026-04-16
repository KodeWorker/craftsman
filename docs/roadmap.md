# Roadmap

## Phase 1: Fundation

### Major Components
- CLI tools
- agent chat TUI (debug mode)
- llm router
- agent memory
- agent tools
- sandbox
- evaluate suite (w, w/o LLM)

## Memory Hierarchy

### Layers
| Layer   | Scope                      | Store      | Lifecycle |
|---------|----------------------------|------------|-----------|
| Session | single conversation        | In-process dict | discarded after session ends; scratchpad promotes to Project |
| Project | group of related sessions  | SQLite     | session history retained for continuation/resume |
| Global  | distilled fact keynotes    | SQLite     | long-lived; promoted from Project layer |

### Within Session
1. In-process dict: scratchpad and agent state (no daemon)
2. SQLite: session records written for continuation/resume

### Out of Session
1. End of session: scratchpad promotes to Project layer in SQLite
2. Nightly update: promote or prune Project → Global
3. TTL expiry: stale KG nodes pruned; Session layer discarded

### Knowledge Graph (Universal)
- Kuzu (embedded) + LightRAG spans all layers — not session-scoped
- No daemon required; Kuzu runs in-process like SQLite
- Live: entities and relationships extracted during active sessions
- Offline: nightly batch — promote, merge, prune via TTL

### Memory Flow

```mermaid
flowchart TD
    U([User]) --> AG[Agent]

    subgraph LIVE["① Within Session"]
        AG -->|scratchpad / state| MEM[(In-process\nDict)]
        AG -->|log messages| MSG[(SQLite\nMessages)]
        AG -->|entity extraction| LR[LightRAG]
        LR -->|nodes + edges| KZ[(Kuzu\nembedded)]
        LR -->|embeddings| VEC[(sqlite-vec)]
    end

    subgraph EOS["② End of Session"]
        MEM -->|promote scratchpad| PROJ[(SQLite\nProject Layer)]
        MSG -->|retain for continuation| PROJ
        MEM -->|discard state| NIL([discarded])
    end

    subgraph NIGHT["③ Nightly Batch"]
        PROJ -->|promote keynotes| GF[(SQLite\nGlobal Facts)]
        PROJ -->|promote KG nodes\nlayer = global| KZ
        KZ -->|prune stale nodes via TTL| KZ
    end

    subgraph READ["Retrieval"]
        Q([Query]) --> LR2[LightRAG\nhybrid search]
        LR2 <-->|graph traversal| KZ
        LR2 <-->|semantic search| VEC
        Q <-->|context window| MEM
        Q <-->|session history| MSG
    end
```

## Services:
- SQLite (Structured DB — `~/.craftsman/craftsman.db`)
- sqlite-vec (Vector DB — SQLite extension, same file as structured DB)
- Kuzu (Knowledge Graph — embedded, no daemon)
- LightRAG (KG orchestration: entity extraction, graph+vector hybrid retrieval)
- Local filesystem (artifact storage — `~/.craftsman/workspace/`)
- craftsman server (always on, bg worker)
- craftsman client (worker, mount workspace)
