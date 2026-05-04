import re
from datetime import datetime, timedelta, timezone

import pytest

from craftsman.memory.structure import StructureDB
from craftsman.tools.schedule_tools import (
    cron_create,
    cron_list,
    cron_remove,
    schedule_at,
    schedule_cancel,
    schedule_list,
)

SESSION = "sess-sched"


@pytest.fixture
def db(tmp_path):
    return StructureDB(path=tmp_path / "test.db")


def _future_iso(minutes: int = 60) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=minutes)
    ).isoformat()


# --- schedule:at ---


async def test_schedule_at_valid(db):
    result = await schedule_at(
        {
            "run_at": _future_iso(),
            "tool_call": {"name": "bash:ls", "args": {}},
        },
        db,
        SESSION,
    )
    assert "job_id" in result
    assert "error" not in result


async def test_schedule_at_normalizes_to_utc(db):
    naive = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    result = await schedule_at(
        {"run_at": naive, "tool_call": {"name": "bash:ls", "args": {}}},
        db,
        SESSION,
    )
    assert "job_id" in result
    # stored as SQLite-compatible UTC: YYYY-MM-DD HH:MM:SS
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result["run_at"])


async def test_schedule_at_invalid_datetime(db):
    result = await schedule_at(
        {"run_at": "not-a-date", "tool_call": {}}, db, SESSION
    )
    assert "error" in result


async def test_schedule_at_relative_minutes(db):
    result = await schedule_at(
        {"run_at": "+2m", "tool_call": {"name": "bash:ls", "args": {}}},
        db,
        SESSION,
    )
    assert "job_id" in result
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result["run_at"])


async def test_schedule_at_relative_seconds(db):
    result = await schedule_at(
        {"run_at": "+30s", "tool_call": {"name": "bash:ls", "args": {}}},
        db,
        SESSION,
    )
    assert "job_id" in result


async def test_schedule_at_relative_hours(db):
    result = await schedule_at(
        {"run_at": "+1h", "tool_call": {"name": "bash:ls", "args": {}}},
        db,
        SESSION,
    )
    assert "job_id" in result


async def test_schedule_at_relative_days(db):
    result = await schedule_at(
        {"run_at": "+1d", "tool_call": {"name": "bash:ls", "args": {}}},
        db,
        SESSION,
    )
    assert "job_id" in result


# --- schedule:list / cancel ---


async def test_schedule_list(db):
    await schedule_at(
        {
            "run_at": _future_iso(),
            "tool_call": {"name": "bash:ls", "args": {}},
        },
        db,
        SESSION,
    )
    result = await schedule_list({}, db, SESSION)
    assert len(result["jobs"]) == 1


async def test_schedule_cancel(db):
    r = await schedule_at(
        {
            "run_at": _future_iso(),
            "tool_call": {"name": "bash:ls", "args": {}},
        },
        db,
        SESSION,
    )
    cancel = await schedule_cancel({"job_id": r["job_id"]}, db, SESSION)
    assert cancel["status"] == "cancelled"
    jobs = await schedule_list({}, db, SESSION)
    assert len(jobs["jobs"]) == 0


async def test_schedule_cancel_not_found(db):
    result = await schedule_cancel({"job_id": "bad-id"}, db, SESSION)
    assert "error" in result


# --- cron:create ---


async def test_cron_create_valid(db):
    result = await cron_create(
        {
            "expression": "0 3 * * *",
            "tool_call": {"name": "bash:ls", "args": {}},
        },
        db,
        SESSION,
    )
    assert "cron_id" in result
    assert "error" not in result


async def test_cron_create_invalid_expression(db):
    result = await cron_create(
        {"expression": "not a cron", "tool_call": {}}, db, SESSION
    )
    assert "error" in result


# --- cron:list / remove ---


async def test_cron_list(db):
    await cron_create(
        {"expression": "*/5 * * * *", "tool_call": {"name": "bash:ls"}},
        db,
        SESSION,
    )
    result = await cron_list({}, db, SESSION)
    assert len(result["jobs"]) == 1


async def test_cron_remove(db):
    r = await cron_create(
        {"expression": "0 0 * * *", "tool_call": {"name": "bash:ls"}},
        db,
        SESSION,
    )
    remove = await cron_remove({"cron_id": r["cron_id"]}, db, SESSION)
    assert remove["status"] == "removed"
    jobs = await cron_list({}, db, SESSION)
    assert len(jobs["jobs"]) == 0
