# API

All `/sessions/*` and `/artifacts/*` endpoints require `Authorization: Bearer <token>`.

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
{ "message": { "role": "user", "content": "..." } }
```

Response: NDJSON stream.

```json
{ "kind": "content", "text": "..." }
{ "kind": "reasoning", "text": "..." }
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

Query params: `session_id` (optional).

```json
{
  "artifacts": [
    {
      "artifact_id": "<uuid>",
      "filename": "...",
      "mime_type": "...",
      "size_bytes": 0,
      "created_at": "..."
    }
  ]
}
```

### GET /artifacts/{id}

```json
{
  "artifact_id": "<uuid>",
  "filename": "...",
  "mime_type": "...",
  "size_bytes": 0,
  "created_at": "..."
}
```

### DELETE /artifacts/{id}

```json
{ "status": "artifact '<uuid>' deleted" }
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
