# Schema

## Structure Database (PostgreSQL)

```sql
-- Projects: groups of related sessions
CREATE TABLE projects (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sessions: individual conversations
CREATE TABLE sessions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  title      TEXT,
  metadata   JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at   TIMESTAMPTZ
);

-- Messages: full history for session continuation/resume
CREATE TABLE messages (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
  content    TEXT NOT NULL,
  tokens     INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Global facts: distilled keynotes promoted from Project layer
CREATE TABLE global_facts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content           TEXT NOT NULL,
  source_session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
  source_project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  promoted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at        TIMESTAMPTZ
);

-- Artifacts: references to files stored in SeaweedFS
CREATE TABLE artifacts (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  fid        TEXT NOT NULL,  -- SeaweedFS file ID
  filename   TEXT NOT NULL,
  mime_type  TEXT,
  size_bytes BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Vector Database (Qdrant)

Collections are managed by LightRAG.

| Collection    | Description                                          | Key Payload Fields                                      |
|---------------|------------------------------------------------------|---------------------------------------------------------|
| `entities`    | Entity embeddings extracted from sessions            | `name`, `type`, `description`, `layer`, `session_id`   |
| `relations`   | Relationship embeddings between entities             | `source`, `target`, `description`, `weight`             |
| `text_chunks` | Source chunk embeddings for retrieval context        | `content`, `session_id`, `project_id`, `layer`          |

## Knowledge Graph (Neo4j)

Managed by LightRAG. Nodes and relationships are created during live extraction and pruned by the nightly batch job.

```cypher
// Node types
(:Entity {
  id          : STRING,
  name        : STRING,
  type        : STRING,   // e.g. person, concept, tool, fact
  description : STRING,
  layer       : STRING,   // session | project | global
  created_at  : DATETIME,
  expires_at  : DATETIME  // null = no TTL
})

(:Chunk {
  id         : STRING,
  content    : STRING,
  session_id : STRING,
  tokens     : INTEGER,
  created_at : DATETIME
})

// Relationship types
(:Entity)-[:RELATED_TO {
  description : STRING,
  weight      : FLOAT,
  created_at  : DATETIME
}]->(:Entity)

(:Entity)-[:MENTIONED_IN]->(:Chunk)
```

## Cache (Redis)

| Key pattern                    | Type   | Description                              |
|--------------------------------|--------|------------------------------------------|
| `session:{id}:scratchpad`      | Hash   | Agent scratchpad key/value state         |
| `session:{id}:state`           | Hash   | Agent runtime state                      |
| `session:{id}:context`         | List   | Recent message window (sliding context)  |
| `tasks`                        | Stream | Plan/TODO jobs and cron/scheduled jobs   |
