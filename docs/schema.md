# Schema

## Structure Database (SQLite)

Single file at `~/.craftsman/database/craftsman.db`.

```sql
-- Users: registry of valid users
CREATE TABLE users (
  id            TEXT PRIMARY KEY,  -- UUID
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

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
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  title      TEXT,
  metadata   TEXT,  -- JSON string
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at   TEXT
);

-- Messages: full history for session continuation/resume
CREATE TABLE messages (
  id         TEXT PRIMARY KEY,  -- UUID
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool', 'summary', 'reasoning')),
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

-- Artifacts: references to files stored in ~/.craftsman/artifacts/
CREATE TABLE artifacts (
  id         TEXT PRIMARY KEY,  -- UUID
  user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
  filepath   TEXT NOT NULL,  -- absolute path under ~/.craftsman/artifacts/
  filename   TEXT NOT NULL,
  mime_type  TEXT,
  size_bytes INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

```sql
-- Plans: agent goal + context
CREATE TABLE plans (
  id         TEXT PRIMARY KEY,  -- UUID
  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  goal       TEXT NOT NULL,
  context    TEXT,
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at   TEXT
);

-- Tasks: units of work within a plan; state machine enforced at tool layer
CREATE TABLE tasks (
  id         TEXT PRIMARY KEY,  -- UUID
  plan_id    TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  criteria   TEXT,   -- acceptance criteria for task:verify
  status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'in_progress', 'verifying', 'done', 'failed')),
  output     TEXT,   -- captured output from task:verify
  fail_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tool registry: named tools with JSON schemas
CREATE TABLE tools (
  name        TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  category    TEXT NOT NULL,   -- meta, bash, text, web, memory, schedule, plan
  schema      TEXT NOT NULL,   -- JSON parameters schema (OpenAI function-calling format)
  audited     INTEGER NOT NULL DEFAULT 0,  -- 1 = log every invocation to tool_invocations
  call_count  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Audit log for write/action tool invocations
CREATE TABLE tool_invocations (
  id          TEXT PRIMARY KEY,  -- UUID
  session_id  TEXT REFERENCES sessions(id) ON DELETE SET NULL,
  tool_name   TEXT NOT NULL,
  args        TEXT NOT NULL,     -- JSON
  result      TEXT NOT NULL,     -- JSON
  duration_ms INTEGER NOT NULL,
  is_error    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- sqlite-vec virtual table for tool:find semantic search
CREATE VIRTUAL TABLE tools_vec USING vec0(
  name        TEXT PRIMARY KEY,
  embedding   FLOAT[1536]
);

-- Scheduled jobs: one-shot deferred tool calls
CREATE TABLE scheduled_jobs (
  id          TEXT PRIMARY KEY,  -- UUID
  user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
  tool_call   TEXT NOT NULL,     -- JSON {name, args}
  run_at      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
  result      TEXT,              -- JSON result or error
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cron jobs: recurring tool calls
CREATE TABLE cron_jobs (
  id          TEXT PRIMARY KEY,  -- UUID
  user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
  expression  TEXT NOT NULL,     -- standard cron expression
  tool_call   TEXT NOT NULL,     -- JSON {name, args}
  active      INTEGER NOT NULL DEFAULT 1,
  last_run    TEXT,
  last_result TEXT,              -- JSON result from most recent run
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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

## Knowledge Graph (NetworkX)

In-memory graph, no daemon. Managed by LightRAG (built-in NetworkX backend). Nodes and relationships created during live extraction, pruned by the nightly batch job. Graph serialized to disk at session end.

File: `~/.craftsman/database/graph.gml`

```python
# Entity node attributes
{
    "id":          str,   # UUID
    "name":        str,
    "type":        str,   # e.g. person, concept, tool, fact
    "description": str,
    "layer":       str,   # session | project | global
    "created_at":  str,   # ISO datetime
    "expires_at":  str,   # ISO datetime, None = no TTL
}

# Chunk node attributes
{
    "id":         str,   # UUID
    "content":    str,
    "session_id": str,
    "tokens":     int,
    "created_at": str,   # ISO datetime
}

# Edge: RELATED_TO (Entity -> Entity)
{
    "type":        "RELATED_TO",
    "description": str,
    "weight":      float,
    "created_at":  str,
}

# Edge: MENTIONED_IN (Entity -> Chunk)
{
    "type": "MENTIONED_IN",
}
```
