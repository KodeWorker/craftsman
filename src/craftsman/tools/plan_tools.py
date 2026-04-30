from craftsman.memory.structure import StructureDB

_TRANSITIONS = {
    "task:start": (("pending",), "in_progress"),
    "task:verify": (("in_progress",), "verifying"),
    "task:done": (("verifying",), "done"),
    "task:fail": (("in_progress", "verifying"), "failed"),
}


def _transition(
    db: StructureDB,
    task_id: str,
    op: str,
    output: str = None,
    fail_reason: str = None,
) -> dict:
    task = db.get_task(task_id)
    if task is None:
        return {"error": f"Task not found: {task_id}"}
    current = task["status"]
    from_states, to_state = _TRANSITIONS[op]
    if current not in from_states:
        expected = "/".join(from_states)
        return {
            "error": f"Invalid transition: {current} -> {to_state}"
            f" (expected status: {expected})"
        }
    db.update_task_status(
        task_id, to_state, output=output, fail_reason=fail_reason
    )
    return {"status": to_state, "task_id": task_id}


async def plan_create(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    goal = args["goal"]
    context = args.get("context", "")
    plan_id = db.create_plan(session_id=session_id, goal=goal, context=context)
    return {"plan_id": plan_id, "goal": goal}


async def plan_done(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    plan_id = args["plan_id"]
    if db.get_plan(plan_id) is None:
        return {"error": f"Plan not found: {plan_id}"}
    db.complete_plan(plan_id)
    return {"status": "done", "plan_id": plan_id}


async def task_create(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    plan_id = args["plan_id"]
    if db.get_plan(plan_id) is None:
        return {"error": f"Plan not found: {plan_id}"}
    task_id = db.create_task(
        plan_id=plan_id,
        description=args["description"],
        criteria=args.get("criteria", ""),
    )
    return {"task_id": task_id, "plan_id": plan_id}


async def task_start(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    return _transition(db, args["task_id"], "task:start")


async def task_verify(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    return _transition(
        db, args["task_id"], "task:verify", output=args.get("output")
    )


async def task_done(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    return _transition(db, args["task_id"], "task:done")


async def task_fail(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    return _transition(
        db, args["task_id"], "task:fail", fail_reason=args.get("reason")
    )


async def task_list(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    plan_id = args["plan_id"]
    if db.get_plan(plan_id) is None:
        return {"error": f"Plan not found: {plan_id}"}
    tasks = db.list_tasks(plan_id)
    return {"tasks": [dict(t) for t in tasks]}
