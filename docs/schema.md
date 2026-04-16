# Schema

## Structure Database (SQLite)

Single file at `~/.craftsman/database/craftsman.db`.

```sql
-- Projects: groups of related sessions
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,  -- UUID
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sessions: individual conversations
CREATE TABLE sessions (
  id         TEXT PRIMARY KEY,  -- UUID
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  title      TEXT,
  metadata   TEXT,  -- JSON string
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at   TEXT
);

-- Messages: full history for session continuation/resume
CREATE TABLE messages (
  id         TEXT PRIMARY KEY,  -- UUID
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
  content    TEXT NOT NULL,
  tokens     INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Global facts: distilled keynotes promoted from Project layer
CREATE TABLE global_facts (
  id                TEXT PRIMARY KEY,  -- UUID
  content           TEXT NOT NULL,
  source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  source_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  promoted_at       TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at        TEXT
);

-- Artifacts: references to files stored in ~/.craftsman/workspace/
CREATE TABLE artifacts (
  id         TEXT PRIMARY KEY,  -- UUID
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  filepath   TEXT NOT NULL,  -- relative to ~/.craftsman/workspace/
  filename   TEXT NOT NULL,
  mime_type  TEXT,
  size_bytes INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

```sql
-- Tool registry: named tools with JSON schemas
CREATE TABLE tools (
  name        TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  category    TEXT NOT NULL,  -- meta, bash, text, web, memory, schedule
  schema      TEXT NOT NULL,  -- JSON schema
  call_count  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- sqlite-vec virtual table for tool:find semantic search
CREATE VIRTUAL TABLE tools_vec USING vec0(
  name        TEXT PRIMARY KEY,
  embedding   FLOAT[1536]
);

-- Tool macros: composed pipelines from tool:compose
CREATE TABLE tool_macros (
  name       TEXT PRIMARY KEY,
  steps      TEXT NOT NULL,   -- JSON array of {tool, args}
  scope      TEXT NOT NULL DEFAULT 'session' CHECK (scope IN ('session', 'global')),
  session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,  -- null if global
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Scheduled jobs: one-shot deferred tool calls
CREATE TABLE scheduled_jobs (
  id          TEXT PRIMARY KEY,  -- UUID
  tool_call   TEXT NOT NULL,     -- JSON {tool, args}
  run_at      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
  result      TEXT,              -- JSON result or error
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cron jobs: recurring tool calls
CREATE TABLE cron_jobs (
  id         TEXT PRIMARY KEY,  -- UUID
  expression TEXT NOT NULL,     -- standard cron expression
  tool_call  TEXT NOT NULL,     -- JSON {tool, args}
  active     INTEGER NOT NULL DEFAULT 1,
  last_run   TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

## Session State (In-Process)

No persistence layer. Python dict keyed by session ID, lives in the server process.

| Key                          | Type  | Description                             |
|------------------------------|-------|-----------------------------------------|
| `session:{id}:scratchpad`    | dict  | Agent scratchpad key/value state        |
| `session:{id}:state`         | dict  | Agent runtime state                     |
| `session:{id}:context`       | list  | Recent message window (sliding context) |
| `tasks`                      | list  | Plan/TODO jobs and scheduled jobs       |

## Vector Store (sqlite-vec)

Collections managed by LightRAG. File-based, no daemon.

| Collection    | Description                                       | Key Fields                                            |
|---------------|---------------------------------------------------|-------------------------------------------------------|
| `entities`    | Entity embeddings extracted from sessions         | `name`, `type`, `description`, `layer`, `session_id` |
| `relations`   | Relationship embeddings between entities          | `source`, `target`, `description`, `weight`           |
| `text_chunks` | Source chunk embeddings for retrieval context     | `content`, `session_id`, `project_id`, `layer`        |

## Knowledge Graph (Kuzu)

Embedded graph DB, no daemon. Managed by LightRAG. Nodes and relationships created during live extraction, pruned by the nightly batch job.

```cypher
// Node types
(:Entity {
  id          : STRING,
  name        : STRING,
  type        : STRING,   // e.g. person, concept, tool, fact
  description : STRING,
  layer       : STRING,   // session | project | global
  created_at  : TIMESTAMP,
  expires_at  : TIMESTAMP  // null = no TTL
})

(:Chunk {
  id         : STRING,
  content    : STRING,
  session_id : STRING,
  tokens     : INT64,
  created_at : TIMESTAMP
})

// Relationship types
(:Entity)-[:RELATED_TO {
  description : STRING,
  weight      : DOUBLE,
  created_at  : TIMESTAMP
}]->(:Entity)

(:Entity)-[:MENTIONED_IN]->(:Chunk)
```
