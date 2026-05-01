import json
from datetime import datetime, timezone

from croniter import croniter

from craftsman.memory.structure import StructureDB


def _to_utc_iso(run_at: str) -> str:
    dt = datetime.fromisoformat(run_at)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # treat naive as machine local
    return dt.astimezone(timezone.utc).isoformat()


async def schedule_at(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    run_at = args["run_at"]
    tool_call = args["tool_call"]
    try:
        run_at_utc = _to_utc_iso(run_at)
    except ValueError:
        return {"error": f"Invalid ISO 8601 datetime: {run_at!r}"}
    row = db.get_session(session_id) if session_id else None
    user_id = row["user_id"] if row else None
    job_id = db.schedule_job(
        tool_call=json.dumps(tool_call), run_at=run_at_utc, user_id=user_id
    )
    return {"job_id": job_id, "run_at": run_at_utc}


async def schedule_list(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    jobs = db.list_scheduled_jobs()
    return {"jobs": [dict(j) for j in jobs]}


async def schedule_cancel(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    job_id = args["job_id"]
    cancelled = db.cancel_scheduled_job(job_id)
    if not cancelled:
        return {"error": f"Job not found or already completed: {job_id}"}
    return {"status": "cancelled", "job_id": job_id}


async def cron_create(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    expression = args["expression"]
    tool_call = args["tool_call"]
    if not croniter.is_valid(expression):
        return {"error": f"Invalid cron expression: {expression!r}"}
    row = db.get_session(session_id) if session_id else None
    user_id = row["user_id"] if row else None
    cron_id = db.create_cron_job(
        expression=expression, tool_call=json.dumps(tool_call), user_id=user_id
    )
    return {"cron_id": cron_id, "expression": expression}


async def cron_list(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    jobs = db.list_cron_jobs()
    return {"jobs": [dict(j) for j in jobs]}


async def cron_remove(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    cron_id = args["cron_id"]
    db.delete_cron_job(cron_id)
    return {"status": "removed", "cron_id": cron_id}
