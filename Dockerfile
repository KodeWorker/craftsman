# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Install project dependencies first (better layer caching).
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# --no-dev: skip pytest/etc. Browser tools are disabled by default in
# craftsman.yaml, so `playwright install` is intentionally skipped here;
# opt in by extending this image if you enable tools.browser.
RUN uv sync --frozen --no-dev

# Non-root runtime user; HOME holds the workspace (~/.craftsman) and the
# file-based keyring store used by PYTHON_KEYRING_BACKEND (see
# docker-compose.yaml). Persist this directory via a volume or credentials
# and session data are lost on container recreation.
RUN useradd --create-home --uid 1000 craftsman
USER craftsman
ENV HOME=/home/craftsman \
    PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["craftsman"]
CMD ["--help"]
