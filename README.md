# craftsman

# Overview

# Dependencies
- click
- keyring
- fastapi
- litellm

# Configuration
1. Setup our own LLM service in [docs/setup/llama.cpp.md](docs/setup/llama.cpp.md)
2. Configure `craftsman` in [docs/configuration.md](docs/configuration.md)

# Uage

```shell
# Initialize the craftsman environment
uv run craftsman init
# Start the craftsman agent server
uv run craftsman server [--port]
# Connect to a running craftsman server as a client
uv run craftsman client [--host] [--port]
# Start both server and client in one terminal
uv run craftsman dev

# Show available authentication providers and status
uv run craftsman auth list
# Set authentication credentials for a provider
uv run craftsman auth set <provider>
# Get authentication credentials for a provider
uv run craftsman auth get <provider>
# Clear all authentication credentials
uv run craftsman auth clear
# Clear authentication credentials for a specific provider
uv run craftsman auth clear <provider>
```

# Documentation
