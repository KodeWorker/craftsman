# API

## GET /health

```json
{ "status": "ok" }
```

## GET /sessions/list

Query params: `project_id` (optional), `limit` (optional)

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

## GET /sessions/id

Query params: `session` — id, prefix, or title

```json
{ "session_id": "<uuid>" }
```

## GET /sessions/system

Query params: `session_id` (required)

```json
{ "system_prompt": "..." }
```

## POST /sessions/create

```json
{ "session_id": "<uuid>" }
```

## POST /sessions/resume

Request:
```json
{ "session_id": "<uuid>" }
```

Response:
```json
{
  "status": "session '<uuid>' resumed with N messages",
  "meta": { "ctx_used": 0, "upload_tokens": 0, "download_tokens": 0, "cost": 0.0 },
  "messages": [{ "role": "...", "content": "..." }]
}
```

## POST /sessions/delete

Request:
```json
{ "session_id": "<uuid>" }
```

Response:
```json
{ "status": "session '<uuid>' deleted" }
```

## POST /sessions/clear

Request:
```json
{ "session_id": "<uuid>" }
```

Response:
```json
{ "status": "session cleared" }
```

## POST /sessions/system

Request:
```json
{ "session_id": "<uuid>", "system_prompt": "..." }
```

Response:
```json
{ "status": "system prompt set" }
```

## POST /sessions/completion

Request:
```json
{ "session_id": "<uuid>", "message": { "role": "user", "content": "..." } }
```

Response: NDJSON stream.

```json
{ "kind": "content", "text": "..." }
{ "kind": "reasoning", "text": "..." }
{ "kind": "meta", "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0 }
```

## POST /sessions/compact

Request:
```json
{ "session_id": "<uuid>", "summary_limit": 1000 , "keep_turns": 5}
```

Response:
```json
{
  "status": "session '<uuid>' compacted with summary",
  "meta": { "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0 }
}
```

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
