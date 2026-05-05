import json
import re
from datetime import datetime, timedelta, timezone

from croniter import croniter

from craftsman.memory.structure import StructureDB

_RELATIVE_RE = re.compile(
    r"^\+(\d+)(s|sec|m|min|h|hr|d|day)s?$", re.IGNORECASE
)
_UNITS = {
    "s": 1,
    "sec": 1,
    "m": 60,
    "min": 60,
    "h": 3600,
    "hr": 3600,
    "d": 86400,
    "day": 86400,
}


def _to_utc_sqlite(run_at: str) -> str:
    m = _RELATIVE_RE.match(run_at.strip())
    if m:
        seconds = int(m.group(1)) * _UNITS[m.group(2).lower()]
        dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    else:
        dt = datetime.fromisoformat(run_at)
        if dt.tzinfo is None:
            dt = dt.astimezone()  # treat naive as machine local
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def schedule_at(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    run_at = args.get("run_at", "").strip()
    tool_call = args.get("tool_call")
    if not run_at:
        return {"error": "run_at is required"}
    if not tool_call:
        return {"error": "tool_call is required"}
    try:
        run_at_utc = _to_utc_sqlite(run_at)
    except ValueError:
        return {"error": f"Invalid run_at: {run_at!r}"}
    row = db.get_session(session_id) if session_id else None
    user_id = row["user_id"] if row else None
    job_id = db.schedule_job(
        tool_call=json.dumps(tool_call), run_at=run_at_utc, user_id=user_id
    )
    return {"job_id": job_id, "run_at": run_at_utc}


async def schedule_list(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    row = db.get_session(session_id) if session_id else None
    user_id = row["user_id"] if row else None
    jobs = db.list_scheduled_jobs(user_id=user_id)
    return {"jobs": [dict(j) for j in jobs]}


async def schedule_cancel(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    job_id = args.get("job_id", "").strip()
    if not job_id:
        return {"error": "job_id is required"}
    cancelled = db.cancel_scheduled_job(job_id)
    if not cancelled:
        return {"error": f"Job not found or already completed: {job_id}"}
    return {"status": "cancelled", "job_id": job_id}


async def cron_create(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    expression = args.get("expression", "").strip()
    tool_call = args.get("tool_call")
    if not expression:
        return {"error": "expression is required"}
    if not tool_call:
        return {"error": "tool_call is required"}
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
    row = db.get_session(session_id) if session_id else None
    user_id = row["user_id"] if row else None
    jobs = db.list_cron_jobs(user_id=user_id)
    return {"jobs": [dict(j) for j in jobs]}


async def cron_remove(
    args: dict, db: StructureDB, session_id: str | None
) -> dict:
    cron_id = args.get("cron_id", "").strip()
    if not cron_id:
        return {"error": "cron_id is required"}
    db.delete_cron_job(cron_id)
    return {"status": "removed", "cron_id": cron_id}
