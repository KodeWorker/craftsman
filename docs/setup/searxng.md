# Searxng Setup

Craftsman's `web:search` tool requires a running searxng instance.
Searxng is a self-hosted, privacy-respecting meta-search engine.

## Install

### Docker (recommended)

```bash
docker run -d \
  --name searxng \
  -p 8080:8080 \
  -e SEARXNG_SECRET=$(openssl rand -hex 32) \
  searxng/searxng:latest
```

### Docker Compose

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    ports:
      - "8080:8080"
    environment:
      SEARXNG_SECRET: your_secret_here
    restart: unless-stopped
```

## Enable JSON output

Searxng disables JSON format by default. Enable it in your searxng config:

```yaml
# settings.yml (searxng config file)
search:
  formats:
    - html
    - json
```

If using Docker, mount your settings file:

```bash
docker run -d \
  --name searxng \
  -p 8080:8080 \
  -v /path/to/settings.yml:/etc/searxng/settings.yml \
  searxng/searxng:latest
```

Verify JSON is working:

```bash
curl "http://localhost:8080/search?q=test&format=json" | python3 -m json.tool
```

## Configure craftsman

In `~/.craftsman/craftsman.yaml`:

```yaml
web:
  searxng_url: "http://localhost:8080"
```

Then enable the web tools category:

```yaml
tools:
  web:
    enabled: true
```

## Which engines searxng uses

Configure engines and categories in searxng's own `settings.yml` —
craftsman passes only the query string and lets searxng decide.
See the [searxng documentation](https://docs.searxng.org/admin/settings/settings_engines.html)
for engine configuration.
