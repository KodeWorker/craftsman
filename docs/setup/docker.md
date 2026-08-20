# Running craftsman with Docker Compose

`docker-compose.yaml` at the repo root wires up three services:

| Service  | Image                      | Role                                            |
|----------|-----------------------------|--------------------------------------------------|
| `llm`    | `ghcr.io/ggml-org/llama.cpp:server` | Local OpenAI-compatible LLM backend       |
| `server` | built from `Dockerfile`    | craftsman API (`craftsman server`)               |
| `client` | built from `Dockerfile`    | interactive chat REPL (`craftsman chat`), run on demand |

`llm` and `server` are meant to stay up (`docker compose up -d`); `client`
is an interactive terminal app, so it's tagged with the `client` profile and
started on demand via `docker compose run` instead.

## 1. Get a model

Same as the bare-metal setup — see [llama.cpp.md](llama.cpp.md#prepare-local-language-model-from-unsloth)
for downloading a `.gguf` from unsloth. Drop it under `./models/`.

## 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:
- `LLM_MODEL_FILE` — filename under `MODELS_DIR` (default `./models`)
- `LLM_API_KEY` — shared secret between llama.cpp and craftsman; generate
  with `openssl rand -hex 32`

## 3. Build and start the always-on services

```bash
docker compose build
docker compose up -d llm server
docker compose logs -f server   # wait for "Starting server on 0.0.0.0:6969..."
```

## 4. One-time craftsman setup

Run these through the `client` service (they need the shared
`$CRAFTSMAN_HOME` volume, not a running server):

```bash
# Creates ~/.craftsman/craftsman.yaml on the shared volume
docker compose run --rm client craftsman init
```

Edit `craftsman_home/.craftsman/craftsman.yaml` (bind-mounted, so it's a
regular file on the host) and point the provider at the `llm` service on the
compose network — not `localhost`:

```yaml
provider:
  api_base: "http://llm:8080"
  model: openai/gemma-4-E4B-it # label only; llama.cpp ignores mismatches
```

Then register a user and save credentials (all prompt interactively):

```bash
docker compose run --rm client craftsman user register
docker compose run --rm client craftsman user login       # USERNAME/PASSWORD, for JWT
docker compose run --rm client craftsman auth set LLM_API_KEY  # same value as .env
```

## 5. Chat

```bash
docker compose run --rm client
```

## Notes

- `server.py` binds `127.0.0.1` by default; the compose file sets
  `CRAFTSMAN_HOST=0.0.0.0` on the `server` service so the `client` container
  can reach it by service name. Leave this unset for non-Docker use.
- No OS keyring is available in the container, so both services set
  `PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring` (an existing
  dependency) — credentials are stored **unencrypted** under
  `$CRAFTSMAN_HOME/.local/share/python_keyring/` on the host. Fine for a
  single-user, self-hosted setup; don't reuse `LLM_API_KEY`/user passwords
  elsewhere, and restrict access to the `craftsman_home` directory.
- `telegram`/`daemon` can run as an additional always-on service the same
  way `server` does — add a service block with `command: telegram` (or
  `daemon`) and the same volume/env, and set `TELEGRAM_BOT_TOKEN` via
  `craftsman auth set` first.
- GPU: swap the `llm` image for `ghcr.io/ggml-org/llama.cpp:server-cuda` and
  uncomment the `deploy.resources` block in `docker-compose.yaml` (requires
  the NVIDIA container toolkit on the host).
