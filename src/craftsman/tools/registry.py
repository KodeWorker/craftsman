# flake8: noqa: E501
import json

from craftsman.configure import get_config
from craftsman.memory.structure import StructureDB

# Read configurable defaults once at import so the LLM sees the same limits
# that the runtime will enforce.
_cfg = get_config().get("tools", {})
_CAT_MAX_LINES: int = _cfg.get("bash", {}).get("cat", {}).get("max_lines", 200)
_READ_MAX_LINES: int = (
    _cfg.get("text", {}).get("read", {}).get("max_lines", 200)
)
_SEARCH_CTX_LINES: int = (
    _cfg.get("text", {}).get("search", {}).get("context_lines", 2)
)

# Each entry: name, description, category, audited, parameters dict.
# `schema` stored in DB is json.dumps(parameters).
# audited=True  → write/action tools; every invocation logged to tool_invocations
# audited=False → read-only tools; only call_count incremented
_TOOLS: list[dict] = [
    # ── meta ────────────────────────────────────────────────────────────
    {
        "name": "tool:list",
        "description": "List all registered tools, optionally filtered by category",
        "category": "meta",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Filter by category: meta, bash, text, memory,"
                        " schedule, plan"
                    ),
                }
            },
            "required": [],
        },
    },
    {
        "name": "tool:describe",
        "description": "Return the full JSON schema for a named tool",
        "category": "meta",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name, e.g. bash:grep",
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "tool:find",
        "description": (
            "Search tools by intent and inject the best match into the"
            " active tool list for the next turn"
        ),
        "category": "meta",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Natural language description of what you need",
                }
            },
            "required": ["intent"],
        },
    },
    {
        "name": "tool:revoke",
        "description": (
            "Remove a tool from the active set for this session."
            " Append-only: cannot be undone without starting a new session"
        ),
        "category": "meta",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name to revoke",
                }
            },
            "required": ["name"],
        },
    },
    # ── bash ─────────────────────────────────────────────────────────────
    {
        "name": "bash:ls",
        "description": "List directory contents",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "recursive": {
                    "type": "boolean",
                    "description": "List subdirectories recursively",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "bash:cat",
        "description": "Read a file with optional line range",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "line_start": {
                    "type": "integer",
                    "description": "First line (1-based)",
                },
                "line_end": {
                    "type": "integer",
                    "description": "Last line (inclusive)",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines to return",
                    "default": _CAT_MAX_LINES,
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "bash:grep",
        "description": "Search for a pattern in files",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex or literal pattern",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search subdirectories recursively",
                    "default": False,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum matching lines to return",
                    "default": 100,
                },
            },
            "required": ["pattern", "path"],
        },
    },
    {
        "name": "bash:find",
        "description": "Locate files by name or extension",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Root directory to search",
                },
                "name_pattern": {
                    "type": "string",
                    "description": "Shell glob pattern for filename, e.g. *.py",
                },
                "type": {
                    "type": "string",
                    "description": "f = files only, d = directories only",
                    "enum": ["f", "d"],
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 50,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "bash:head",
        "description": "Read the first N lines of a file",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "n_lines": {
                    "type": "integer",
                    "description": "Number of lines to read",
                    "default": 20,
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "bash:tail",
        "description": "Read the last N lines of a file",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "n_lines": {
                    "type": "integer",
                    "description": "Number of lines to read",
                    "default": 20,
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "bash:stat",
        "description": "Read file timestamps, size, and permissions without reading content",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "File or directory path",
                }
            },
            "required": ["file"],
        },
    },
    {
        "name": "bash:ps",
        "description": "List running processes",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "name_filter": {
                    "type": "string",
                    "description": "Filter by process name substring",
                }
            },
            "required": [],
        },
    },
    {
        "name": "bash:df",
        "description": "Show filesystem disk usage",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to check (defaults to /)",
                    "default": "/",
                }
            },
            "required": [],
        },
    },
    {
        "name": "bash:du",
        "description": "Show disk usage for a directory",
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum directory depth to summarise",
                    "default": 1,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "bash:run",
        "description": (
            "Run an arbitrary shell command (tokenised via shlex, "
            "never shell=True); use named bash:* tools first"
        ),
        "category": "bash",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Command string to execute",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum output lines to return",
                },
            },
            "required": ["cmd"],
        },
    },
    # ── text ─────────────────────────────────────────────────────────────
    {
        "name": "text:read",
        "description": (
            "Read a file with line numbers; page with line_start/line_end"
        ),
        "category": "text",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "line_start": {
                    "type": "integer",
                    "description": "First line (1-based)",
                },
                "line_end": {
                    "type": "integer",
                    "description": "Last line (inclusive)",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum lines per page",
                    "default": _READ_MAX_LINES,
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "text:search",
        "description": "Regex or literal search within a file; returns matching lines with context",
        "category": "text",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "pattern": {
                    "type": "string",
                    "description": "Regex or literal pattern",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Lines of context around each match",
                    "default": _SEARCH_CTX_LINES,
                },
            },
            "required": ["file", "pattern"],
        },
    },
    {
        "name": "text:replace",
        "description": (
            "Replace a string in a file atomically."
            " Creates a .bak before writing"
        ),
        "category": "text",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "old_string": {
                    "type": "string",
                    "description": "Exact string to replace (must be unique in file)",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement string",
                },
            },
            "required": ["file", "old_string", "new_string"],
        },
    },
    {
        "name": "text:insert",
        "description": (
            "Insert lines at a specific line number."
            " Use line_num=1 on a non-existent file to create it."
            " Creates a .bak before writing to existing files"
        ),
        "category": "text",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "line_num": {
                    "type": "integer",
                    "description": "Line number to insert before (1-based)",
                },
                "lines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lines to insert",
                },
            },
            "required": ["file", "line_num", "lines"],
        },
    },
    {
        "name": "text:delete",
        "description": (
            "Delete a range of lines from a file."
            " Creates a .bak before writing"
        ),
        "category": "text",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path"},
                "line_start": {
                    "type": "integer",
                    "description": "First line to delete (1-based)",
                },
                "line_end": {
                    "type": "integer",
                    "description": "Last line to delete (inclusive)",
                },
            },
            "required": ["file", "line_start", "line_end"],
        },
    },
    # ── memory ───────────────────────────────────────────────────────────
    {
        "name": "memory:store",
        "description": "Write a key-value fact to the session scratchpad",
        "category": "memory",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Scratchpad key"},
                "value": {"type": "string", "description": "Value to store"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "memory:retrieve",
        "description": (
            "Read facts from the session scratchpad."
            " Omit key to return all stored facts"
        ),
        "category": "memory",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Specific key to retrieve; omit for all",
                }
            },
            "required": [],
        },
    },
    {
        "name": "memory:forget",
        "description": "Remove a key from the session scratchpad",
        "category": "memory",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Scratchpad key to remove",
                }
            },
            "required": ["key"],
        },
    },
    # ── schedule ─────────────────────────────────────────────────────────
    {
        "name": "schedule:at",
        "description": "Run a tool call once at a specific datetime (ISO 8601)",
        "category": "schedule",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "run_at": {
                    "type": "string",
                    "description": "ISO 8601 datetime, e.g. 2026-05-01T09:00:00",
                },
                "tool_call": {
                    "type": "object",
                    "description": "Tool call to invoke: {name, args}",
                },
            },
            "required": ["run_at", "tool_call"],
        },
    },
    {
        "name": "schedule:list",
        "description": "List pending one-shot scheduled jobs",
        "category": "schedule",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "schedule:cancel",
        "description": "Cancel a pending scheduled job",
        "category": "schedule",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Scheduled job ID"}
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "cron:create",
        "description": "Schedule a recurring tool call with a cron expression",
        "category": "schedule",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Standard cron expression, e.g. 0 3 * * *",
                },
                "tool_call": {
                    "type": "object",
                    "description": "Tool call to invoke: {name, args}",
                },
            },
            "required": ["expression", "tool_call"],
        },
    },
    {
        "name": "cron:list",
        "description": "List active cron jobs",
        "category": "schedule",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "cron:remove",
        "description": "Delete a recurring cron job",
        "category": "schedule",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "cron_id": {"type": "string", "description": "Cron job ID"}
            },
            "required": ["cron_id"],
        },
    },
    # ── agent ────────────────────────────────────────────────────────────
    {
        "name": "agent:run",
        "description": (
            "Run a multi-step agentic sub-task driven by a prompt."
            " The agent has access to all registered tools and will"
            " iterate until it reaches a conclusion or hits the loop cap"
        ),
        "category": "agent",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Goal or instruction for the sub-agent",
                }
            },
            "required": ["prompt"],
        },
    },
    # ── plan ─────────────────────────────────────────────────────────────
    {
        "name": "plan:create",
        "description": "Create a plan with a goal; call after research, not before",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What you intend to achieve",
                },
                "context": {
                    "type": "string",
                    "description": "Background and constraints gathered so far",
                },
            },
            "required": ["goal"],
        },
    },
    {
        "name": "plan:done",
        "description": "Close a completed plan",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID"}
            },
            "required": ["plan_id"],
        },
    },
    {
        "name": "task:create",
        "description": "Add a task with acceptance criteria to a plan",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Parent plan ID"},
                "description": {
                    "type": "string",
                    "description": "What needs to be done",
                },
                "criteria": {
                    "type": "string",
                    "description": "Acceptance criteria for task:verify",
                },
            },
            "required": ["plan_id", "description"],
        },
    },
    {
        "name": "task:start",
        "description": "Transition task pending → in_progress",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task:verify",
        "description": (
            "Record task output and transition in_progress → verifying"
        ),
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "output": {
                    "type": "string",
                    "description": "Output or evidence to check against criteria",
                },
            },
            "required": ["task_id", "output"],
        },
    },
    {
        "name": "task:done",
        "description": "Transition task verifying → done",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task:fail",
        "description": "Transition task to failed with a reason",
        "category": "plan",
        "audited": True,
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "reason": {
                    "type": "string",
                    "description": "Why the task failed",
                },
            },
            "required": ["task_id", "reason"],
        },
    },
    {
        "name": "task:list",
        "description": "List all tasks for a plan with their current status",
        "category": "plan",
        "audited": False,
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID"}
            },
            "required": ["plan_id"],
        },
    },
]


def _enabled_tools() -> list[dict]:
    cfg = get_config().get("tools", {})
    explicitly_disabled: set[str] = set(cfg.get("disabled", []))
    result = []
    for t in _TOOLS:
        cat_cfg = cfg.get(t["category"], {})
        if not cat_cfg.get("enabled", True):
            continue
        if t["name"] in explicitly_disabled:
            continue
        result.append(t)
    return result


def seed_registry(db: StructureDB) -> None:
    for t in _enabled_tools():
        db.register_tool(
            name=t["name"],
            description=t["description"],
            category=t["category"],
            schema=json.dumps(t["parameters"]),
            audited=t["audited"],
        )
