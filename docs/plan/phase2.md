# Phase 2: Multimodal Input

## Goals

Add image and audio input support via upload API. Keep context cheap by replacing
raw media with captions/transcripts at ingest time. Original files retained as artifacts.

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
       → server generates caption (image) or transcript (audio)
       → server records artifact in SQLite (filepath, mime_type, session_id, size_bytes)
       → server records caption generation cost
       → returns { artifact_id, caption }
client → POST /chat/completion with caption text + artifact_id ref in message
```

### Context Strategy

Raw media is never stored in context. At upload time:
- Image → `[image: <caption>]` via vision model
- Audio → `[audio: <transcript>]` via STT (Whisper or equivalent)

Original file stored in `~/.craftsman/workspace/`, referenced by `artifact_id`.
Retrievable on demand; context stays text-only and cheap.

### Cost Tracking

Caption/transcript generation is a separate model call with its own token cost.
Track separately from chat completion cost:

- Add `caption_cost` field to artifact record (or a dedicated `artifact_costs` table)
- Surface in banner or session cost summary

## Checklist

### Infrastructure
- [ ] `POST /artifacts/upload` — multipart upload, save to workspace, return artifact_id
- [ ] Caption pipeline — vision model call at upload time, store caption
- [ ] Transcript pipeline — STT call at upload time, store transcript
- [ ] Cost tracking for caption/transcript generation
- [ ] `GET /artifacts/{id}` — retrieve artifact metadata

### Provider
- [ ] `craftsman.yaml` capability flags (`vision`, `audio`)
- [ ] Guard in `completion()` — reject multimodal messages if capability not declared

### Client
- [ ] `/upload <filepath>` slash command — upload file, inject caption into next message
- [ ] Display artifact_id ref alongside caption in chat
