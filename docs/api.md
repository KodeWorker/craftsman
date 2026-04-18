# API

## GET /health

```json
{ "status": "ok" }
```

## GET /chat/session_id

```json
{ "session_id": "<uuid>" }
```

## POST /chat/completion

Request:
```json
{ "message": { "role": "user", "content": "..." } }
```

Response: NDJSON stream.

```json
{ "kind": "content", "text": "..." }
{ "kind": "meta", "prompt_tokens": 0, "completion_tokens": 0 }
```

## POST /chat/clear

Clears in-process context window for the current session.

```json
{ "status": "session cleared" }
```

## POST /subagent/run

Runs a one-shot agent in an ephemeral session. Session is created, used, and discarded after completion.

Request:
```json
{ "message": { "role": "user", "content": "..." } }
```

Response:
```json
{
  "meta": { "prompt_tokens": 0, "completion_tokens": 0, "cost": 0},
  "content": "..."
}
```
