import logging

_log = logging.getLogger(__name__)

POLL_INTERVAL = 30

# Client-side job dispatcher — implemented in 5.8.
# Polls scheduled_jobs and cron_jobs directly from the local StructureDB,
# executes tools via ToolExecutor (local tools run on the client machine,
# server tools go through HTTP), and drives agent:run via the HTTP
# agentic loop. No tool execution happens on the server.
