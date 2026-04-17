# Phase 1: Basic Chat

## Goals

Stand up a working local chat loop: CLI starts a server and client,
user types messages, server calls the LLM and streams the response back.

## Checklist

### Infrastructure
- [x] FastAPI server with `/health` and `/completion` endpoints
- [x] Server streams responses via `StreamingResponse` (ndjson)
- [x] Client health-check retry loop before entering chat
- [x] `craftsman dev` starts server in subprocess, then connects client
- [x] `craftsman server` / `craftsman client` as separate commands

### Provider
- [x] litellm `acompletion` with streaming
- [x] Thinking/reasoning support (`think.enabled`, `think.budget` in config)
- [x] `model_response_parser` — handles `reasoning_content` field and `<think>` tags
- [x] `drop_params=True` for model compatibility (e.g. Gemma on llama.cpp)
- [x] Debug gate — reasoning only forwarded when `provider.debug: true`
- [x] Debug logging removed from provider

### Client UI
- [x] Streaming print — tokens printed as they arrive
- [x] Reasoning shown in dim style, assistant in magenta
- [x] Conversation history maintained across turns
- [x] Slash commands: `/exit`, `/help`, `/clear`
- [x] Banner with separator that adapts to terminal width

### Auth & Config
- [x] Keyring-backed auth (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_SSL_CRT`)
- [x] `craftsman.yaml` config (`provider`, `logging`, `workspace` sections)

## Remaining

- [x] Server returns token usage — wire `ctx_used`, `upload_tokens`, `download_tokens` into banner
- [x] `craftsman dev` race condition — client retries until server is healthy
