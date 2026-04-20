# Phase 2: Multimodal Input

## Goals

Add image and audio input support. Inject media inline as base64 into the message
content so the model sees the actual file. Original files retained as artifacts.

## Design

### Capability Declaration

LiteLLM's `supports_vision` / `supports_audio_input` does not work for self-hosted
models (llama.cpp, etc.) — registry-based, unaware of loaded weights.

Declare capabilities explicitly in `craftsman.yaml`:

```yaml
provider:
  capabilities:
    vision: false
    audio: false
```

### Upload Flow

```
client → POST /artifacts/upload (multipart)
       → server saves file to ~/.craftsman/workspace/
       → server records artifact in SQLite (filepath, mime_type, session_id, size_bytes)
       → returns { artifact_id }
client → POST /sessions/completion with base64-encoded media inline in message content
```

### Context Strategy

Media is base64-encoded and injected inline into the message as a multimodal
content part. The model receives the actual image or audio directly.

- Image → `{ type: "image_url", image_url: { url: "data:<mime>;base64,<data>" } }`
- Audio → `{ type: "input_audio", input_audio: { data: "<base64>", format: "<fmt>" } }`

Original file stored in `~/.craftsman/workspace/`, referenced by `artifact_id`.

No pre-captioning or STT pipeline — the main model handles vision and audio natively.

### Capability Guard

`completion()` rejects messages containing multimodal content parts if the
corresponding capability flag is not declared in `craftsman.yaml`:

- Image content → requires `capabilities.vision: true`
- Audio content → requires `capabilities.audio: true`

## Checklist

### Infrastructure
- [ ] `POST /artifacts/upload` — multipart upload, save to workspace, return artifact_id
- [ ] `GET /artifacts/{id}` — retrieve artifact metadata

### Provider
- [ ] `craftsman.yaml` capability flags (`vision`, `audio`)
- [ ] Guard in `completion()` — raise if multimodal content present but capability not declared

### Client
- [ ] `/upload <filepath>` slash command — upload file, base64-encode, inject inline into next message
- [ ] Display artifact_id ref in chat alongside the message
