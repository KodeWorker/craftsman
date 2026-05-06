# Searxng Setup

Craftsman's `web:search` tool requires a running searxng instance.
Searxng is a self-hosted, privacy-respecting meta-search engine.

## Install

> **Port conflict:** llama.cpp server also defaults to `8080`. Examples below
> use `8888` to avoid the conflict.

### Dev (quick start)

Create a minimal `settings.yml` — `use_default_settings: true` inherits all
defaults; `server.secret_key` is required (SearXNG refuses to start with the
built-in default).

```yaml
# settings.yml
use_default_settings: true
server:
  secret_key: "craftsman-local-dev"
search:
  formats:
    - html
    - json
```

```bash
docker run -d \
  --name searxng \
  -p 8888:8080 \
  -v /path/to/settings.yml:/etc/searxng/settings.yml:ro \
  searxng/searxng:latest
```

### Docker Compose

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    ports:
      - "8888:8080"
    volumes:
      - /path/to/settings.yml:/etc/searxng/settings.yml:ro
    restart: unless-stopped
```

Verify JSON is working:

```bash
curl "http://localhost:8888/search?q=test&format=json" | python3 -m json.tool
```

## Configure craftsman

In `~/.craftsman/craftsman.yaml`:

```yaml
tools:
  web:
    enabled: true
    searxng_url: "http://localhost:8888"
```

## Which engines searxng uses

Configure engines and categories in searxng's own `settings.yml` —
craftsman passes only the query string and lets searxng decide.
See the [searxng documentation](https://docs.searxng.org/admin/settings/settings_engines.html)
for engine configuration.
