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

### Message Storage

Base64 content is **not** persisted to the `messages` table — storing raw media
in SQLite would bloat the DB fast (a single image can be several MB as base64).

Instead, the message stored in SQLite replaces the multimodal content part with
an artifact reference:

```
[image: artifact_id=<uuid>]
[audio: artifact_id=<uuid>]
```

On resume, the client re-fetches and re-encodes the artifact from disk before
sending the message back into context.

### Capability Guard

`completion()` rejects messages containing multimodal content parts if the
corresponding capability flag is not declared in `craftsman.yaml`:

- Image content → requires `capabilities.vision: true`
- Audio content → requires `capabilities.audio: true`

## Checklist

### Infrastructure
- [ ] `POST /artifacts/upload` — multipart upload, save to workspace, return artifact_id
- [ ] `GET /artifacts/{id}` — retrieve artifact metadata
- [ ] Strip base64 from message before `store_message`; replace with `[image/audio: artifact_id=<uuid>]`
- [ ] On `resume_session`: re-encode artifact from disk when restoring messages with artifact refs

### Provider
- [ ] `craftsman.yaml` capability flags (`vision`, `audio`)
- [ ] Guard in `completion()` — raise if multimodal content present but capability not declared

### Client
- [ ] `@filepath` inline syntax — user types `describe @image.jpg` in chat or
      `craftsman run "describe @image.jpg"`; client detects `@`-prefixed tokens,
      uploads the file, and replaces the token with the base64 multimodal content part
- [ ] Update `ChatCompleter` to trigger file completion only on `@`-prefixed words
      (current completer completes every word, which is too eager)
- [ ] Display artifact_id ref in chat alongside the message

#### Why `@` for inline file references
`@` is visually distinct, not a valid filename-start character on Linux/Mac (so
parsing is unambiguous), and an established convention in chat UIs (GitHub, Slack)
for pointing at something. It also allows the completer to trigger selectively
on `@`-prefixed input rather than every word.
