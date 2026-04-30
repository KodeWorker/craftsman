from craftsman.tools.memory_tools import (
    memory_forget,
    memory_retrieve,
    memory_store,
)
from craftsman.tools.meta_tools import (
    tool_describe,
    tool_find,
    tool_list,
    tool_revoke,
)
from craftsman.tools.plan_tools import (
    plan_create,
    plan_done,
    task_create,
    task_done,
    task_fail,
    task_list,
    task_start,
    task_verify,
)
from craftsman.tools.schedule_tools import (
    cron_create,
    cron_list,
    cron_remove,
    schedule_at,
    schedule_cancel,
    schedule_list,
)

# (args, db, session_id)
DB_DISPATCH: dict = {
    "plan:create": plan_create,
    "plan:done": plan_done,
    "task:create": task_create,
    "task:start": task_start,
    "task:verify": task_verify,
    "task:done": task_done,
    "task:fail": task_fail,
    "task:list": task_list,
    "schedule:at": schedule_at,
    "schedule:list": schedule_list,
    "schedule:cancel": schedule_cancel,
    "cron:create": cron_create,
    "cron:list": cron_list,
    "cron:remove": cron_remove,
}

# (args, librarian, session_id)
LIB_DISPATCH: dict = {
    "memory:store": memory_store,
    "memory:retrieve": memory_retrieve,
    "memory:forget": memory_forget,
}

# (args, db, librarian, session_id)
META_DISPATCH: dict = {
    "tool:list": tool_list,
    "tool:describe": tool_describe,
    "tool:find": tool_find,
    "tool:revoke": tool_revoke,
}

REMOTE_TOOLS: set[str] = (
    set(DB_DISPATCH) | set(LIB_DISPATCH) | set(META_DISPATCH)
)
