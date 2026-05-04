# API

All `/sessions/*` and `/artifacts/*` endpoints require `Authorization: Bearer <token>`.

## GET /users/cost

Requires `Authorization: Bearer <token>`. Returns cumulative token usage and cost across all sessions for the authenticated user.

```json
{ "upload_tokens": 0, "download_tokens": 0, "cost": 0.0 }
```

---

## POST /users/login

Request:
```json
{ "username": "...", "password": "..." }
```

Response:
```json
{ "token": "<jwt>" }
```

## GET /health

```json
{ "status": "ok" }
```

---

## Sessions

### GET /sessions/

Query params: `project_id` (optional), `limit` (optional). Returns sessions scoped to the authenticated user.

```json
{
  "sessions": [
    {
      "session_id": "<uuid>",
      "title": "...",
      "last_input": "...",
      "last_input_at": "..."
    }
  ]
}
```

### GET /sessions/resolve

Query params: `session` — id, prefix, or title.

```json
{ "session_id": "<uuid>" }
```

### POST /sessions/

```json
{ "session_id": "<uuid>" }
```

### DELETE /sessions/{id}

```json
{ "status": "session '<uuid>' deleted" }
```

### POST /sessions/{id}/resume

Response:
```json
{
  "status": "session '<uuid>' resumed with N messages",
  "meta": { "ctx_used": 0, "upload_tokens": 0, "download_tokens": 0, "cost": 0.0 },
  "messages": [{ "role": "...", "content": "..." }]
}
```

### POST /sessions/{id}/clear

```json
{ "status": "session cleared" }
```

### GET /sessions/{id}/system

```json
{ "system_prompt": "..." }
```

### PUT /sessions/{id}/system

Request:
```json
{ "system_prompt": "..." }
```

Response:
```json
{ "status": "system prompt set" }
```

### POST /sessions/{id}/completion

Request:
```json
{
  "message": { "role": "user", "content": "..." },
  "tools": ["bash:grep", "bash:ls"]
}
```

`tools` is an optional list of tool names to expose to the LLM. The server
looks up their schemas from the `tools` table. Omit to run without tools.

Response: NDJSON stream.

```json
{ "kind": "content", "text": "..." }
{ "kind": "reasoning", "text": "..." }
{ "kind": "tool_call", "id": "...", "name": "bash:grep", "args": { "pattern": "error", "path": "/tmp" } }
{ "kind": "error", "text": "..." }
{
  "kind": "meta",
  "model": "...",
  "ctx_total": 0,
  "ctx_used": 0,
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "reasoning_tokens": 0,
  "cost": 0.0
}
```

When the LLM returns tool calls the stream emits `tool_call` events and ends
(no `content` in the same response). The client executes the tools and posts
results to `/sessions/{id}/tool_result`.

### POST /sessions/{id}/tool_result

Submits tool execution results from the client. The server stores them as
`role="tool"` messages and calls the LLM again, streaming the next response.

Request:
```json
{
  "tool_results": [
    {
      "tool_call_id": "call_abc123",
      "tool_name": "bash:grep",
      "result": { "lines": ["foo.py:12: error: ..."] }
    }
  ]
}
```

Response: same NDJSON stream as `/completion` — may contain further
`tool_call` events or a final `content` response.

### POST /sessions/{id}/compact

Request:
```json
{ "summary_limit": 1000, "keep_turns": 5 }
```

Response:
```json
{
  "status": "session '<uuid>' compacted with summary",
  "meta": { "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0 }
}
```

---

## Artifacts

### POST /artifacts/

Multipart form upload. Fields: `file` (required), `session_id` (optional).

```json
{ "artifact_id": "<uuid>" }
```

### GET /artifacts/

Query params: `session_id` (optional), `project_id` (optional). Both trigger an ownership check; 403 if the session/project belongs to a different user.

```json
{
  "artifacts": [
    {
      "id": "<uuid>",
      "filename": "...",
      "mime_type": "...",
      "size_bytes": 0,
      "created_at": "..."
    }
  ]
}
```

### GET /artifacts/{id}

`{id}` may be a full UUID or an unambiguous prefix.

```json
{
  "artifact": {
    "id": "<uuid>",
    "filename": "...",
    "mime_type": "...",
    "size_bytes": 0,
    "created_at": "..."
  }
}
```

### DELETE /artifacts/{id}

`{id}` may be a full UUID or an unambiguous prefix. 403 if the artifact belongs to a different user.

```json
{ "status": "Artifact deleted successfully." }
```

---

## POST /tools/seed

Seeds the tool registry from the server's built-in schema list, filtered by
the `tools` section of `craftsman.yaml`. Safe to call on every client
startup (uses INSERT OR REPLACE).

```json
{ "status": "ok" }
```

---

## POST /subagent/run

Request:
```json
{ "session_id": "<uuid>", "message": { "role": "user", "content": "..." } }
```

Response:
```json
{
  "meta": { "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0 },
  "content": "..."
}
```
