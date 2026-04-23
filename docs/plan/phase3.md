# Phase 3: Multimodal Input

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
      # SigLIP encoder: token cost is resolution-based, not file-size-based
      # 10MB covers all phone photos (3-8MB); RAW/TIFF should be exported first
      max_size_mb: 10
    audio:
      enabled: false
      formats: [wav, mp3]
      # Gemma 4 audio encoder: 10MB MP3 → ~1085 tokens (duration-based, not
      # file-size-based); 25MB → ~2710 tokens (~2% of 131K context)
      max_size_mb: 25
```

### Upload Flow

```
client → POST /artifacts/upload (multipart)
       → server saves file to ~/.craftsman/workspace/
       → server records artifact in SQLite (filepath, mime_type, session_id, size_bytes)
       → returns { artifact_id }
client → POST /sessions/completion with @image:<uuid> | @audio:<uuid>
       → server resolves artifact_id, reads file from disk, base64-encodes inline
       → server sends assembled multimodal message to model
```

The completion request carries only a small text token — base64 encoding stays
server-side, keeping client→server traffic minimal.

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
@image:<uuid>
@audio:<uuid>
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
| `base64` | server | stdlib — encodes file bytes into inline content parts |
| `mimetypes` | server | stdlib — resolves MIME type from file extension |
| `requests` | client | already in use; sends multipart upload via `files=` param |

## Server Architecture

`server.py` currently registers all routes directly on `self.app`. Adding
`/artifacts/*` introduces a third domain; split into router classes at that
boundary rather than growing `Server` further.

Each router takes `librarian` and `provider` in `__init__` and registers its
own routes:

```
Server
├── SessionsRouter   → /sessions/*  (existing handlers, moved)
└── ArtifactsRouter  → /artifacts/* (new)
```

`/health` and `/subagent/run` remain on `Server` directly — too small to
warrant their own routers.

## Checklist

### Server
- [x] Extract `SessionRouter` — move existing `/sessions/*` handlers out of `Server`
- [x] Add `ArtifactRouter` — new `/artifacts/*` handlers

### Infrastructure
- [x] `POST /artifacts/` — multipart upload, save to workspace, return artifact_id
- [x] `GET /artifacts/` — list artifacts; optional `?session_id=` filter for session-scoped view
- [x] `GET /artifacts/{id}` — retrieve artifact metadata
- [x] `DELETE /artifacts/{id}` — delete artifact record and remove file from workspace
- [x] Strip base64 from message before `store_message`; store original `@image:<uuid>` / `@audio:<uuid>` token
- [ ] `get_artifact` resolves UUID prefix — `LIKE 'prefix%'` so user can type short IDs
- ~~[ ] On `resume_session`: re-encode artifact from disk when restoring messages with artifact refs~~
  — deferred: user re-injects via `/artifacts` + `@image:<uuid>` syntax instead

### Provider
- [ ] `craftsman.yaml` capability flags (`vision`, `audio`)
- [ ] Guard in `completion()` — raise if multimodal content present but capability not declared

### Client
- [ ] `/artifacts` slash command — lists artifacts uploaded in the current session
      (artifact_id, filename, mime type, size); session-scoped only; short UUID prefix shown
      so user can copy and type `@image:<prefix>` to re-inject a past artifact into context
- [ ] `craftsman arti list` CLI — lists all artifacts across sessions
- [ ] `craftsman arti delete <id>` CLI — deletes artifact and removes file
      from `~/.craftsman/workspace/`
- [x] `@filepath` inline syntax — user types `describe @image.jpg` in chat or
      `craftsman run "describe @image.jpg"`; client detects `@`-prefixed tokens,
      uploads the file, and replaces with `@image:<uuid>` / `@audio:<uuid>` token
- [x] Update `ChatCompleter` to trigger file completion only on `@`-prefixed words
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

## Future Phase: Telegram Bot Integration

Wire a Telegram bot into `client.chat` as an alternative input channel.

### Media format considerations

Telegram delivers media in fixed formats regardless of what the sender uploaded:

| Telegram type | Format | Supported |
|---------------|--------|-----------|
| `photo` | JPEG (re-compressed by Telegram) | yes |
| `document` (image) | original format preserved | yes (PNG, WebP, GIF) |
| `audio` | MP3 or M4A | MP3 yes; M4A needs transcoding |
| `voice` | OGG/OPUS | no — llama.cpp rejects OGG |
| `video_note` | MP4 | out of scope |

`voice` is the most common audio input in Telegram and always arrives as
OGG/OPUS. llama.cpp does not accept OGG, so server-side transcoding is required
before storing the artifact.

### Transcoding

```
Telegram voice (OGG/OPUS) → pydub → WAV → artifact upload flow
```

- `pydub` shells out to `ffmpeg`; both must be installed
- Transcoding happens in the artifact ingest path before `store_message`
- No change to the model-facing pipeline — WAV is already a supported format
