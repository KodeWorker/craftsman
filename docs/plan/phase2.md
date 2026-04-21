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
    vision:
      enabled: false
      formats: [image/jpeg, image/png, image/webp, image/gif]
    audio:
      enabled: false
      formats: [wav, mp3]
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

- Image content → requires `capabilities.vision.enabled: true`; MIME type must be in `capabilities.vision.formats`
- Audio content → requires `capabilities.audio.enabled: true`; format must be in `capabilities.audio.formats`

## Dependencies

| Package | Side | Purpose |
|---------|------|---------|
| `python-multipart` | server | FastAPI requires this to parse `multipart/form-data`; add to `pyproject.toml` |
| `base64` | client | stdlib — encodes file bytes for inline content parts |
| `mimetypes` | client | stdlib — resolves MIME type from file extension |
| `requests` | client | already in use; sends multipart upload via `files=` param |

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
- [ ] *(low priority)* Drag-and-drop support — hook `Buffer.on_text_insert`,
      detect bracketed-paste paths (`file://`, `/`, `~/`), normalise and
      convert to `@filepath` syntax automatically
- [ ] *(low priority)* Voice input keybinding — push-to-talk key records audio
      and feeds it into the prompt via the existing audio artifact upload flow

#### Why `@` for inline file references
`@` is visually distinct, not a valid filename-start character on Linux/Mac (so
parsing is unambiguous), and an established convention in chat UIs (GitHub, Slack)
for pointing at something. It also allows the completer to trigger selectively
on `@`-prefixed input rather than every word.

#### Drag-and-drop file input (low priority)

Terminal emulators paste the file path as text (via bracketed paste) when a
file is dragged into the window. prompt_toolkit has no native drop API, but we
can intercept the paste via `Buffer.on_text_insert` and auto-convert a detected
path to `@filepath` syntax.

Normalisation needed before converting:
- Strip `file://` prefix (some terminals use `file:///path`)
- Strip surrounding quotes (paths with spaces are often quoted)
- Strip trailing newline that some emulators append

Works on all modern terminals (xterm, iTerm2, Kitty, GNOME Terminal) that
support bracketed paste. No new packages required.

```python
from prompt_toolkit.filters import is_done
from prompt_toolkit.buffer import Buffer

def _on_text_inserted(buf):
text = buf.text
# detect pasted file path (absolute, ~/, or file:// prefix)
if text.startswith(("file://", "/", "~/")):
      path = text.replace("file://", "")
      buf.set_document(
            buf.document.insert_after(f"@{path.strip()}")
      )
```

#### Voice input keybinding (low priority)

A push-to-talk key binding records audio and injects it into the prompt via the
same audio artifact upload flow. Requires `capabilities.audio.enabled: true` —
no STT fallback; the model handles audio natively.

Dependencies (both wrap PortAudio — a C system library):
- `sounddevice` — preferred; cleaner API, NumPy-based
- `pyaudio` — alternative if `sounddevice` is unavailable

Deferred until `@filepath` audio input is proven out. At that point the upload
infrastructure is already in place and voice capture is just another input path.
