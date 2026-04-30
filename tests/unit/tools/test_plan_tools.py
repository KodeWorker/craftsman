import pytest

from craftsman.memory.structure import StructureDB
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


@pytest.fixture
def db(tmp_path):
    return StructureDB(path=tmp_path / "test.db")


@pytest.fixture
def session_id(db):
    user = db.create_user("u", "hash")
    return db.create_session(user_id=user["id"], title="t")


async def _make_plan(db, session_id):
    r = await plan_create({"goal": "test goal"}, db, session_id)
    return r["plan_id"]


async def _make_task(db, session_id, plan_id):
    r = await task_create(
        {"plan_id": plan_id, "description": "do thing", "criteria": "done"},
        db,
        session_id,
    )
    return r["task_id"]


# --- plan ---


async def test_plan_create(db, session_id):
    result = await plan_create({"goal": "g", "context": "c"}, db, session_id)
    assert "plan_id" in result
    assert result["goal"] == "g"


async def test_plan_create_attaches_session(db, session_id):
    result = await plan_create({"goal": "g"}, db, session_id)
    row = db.get_plan(result["plan_id"])
    assert row["session_id"] == session_id


async def test_plan_done(db, session_id):
    plan_id = await _make_plan(db, session_id)
    result = await plan_done({"plan_id": plan_id}, db, session_id)
    assert result["status"] == "done"


async def test_plan_done_not_found(db, session_id):
    result = await plan_done({"plan_id": "bad-id"}, db, session_id)
    assert "error" in result


# --- task state machine ---


async def test_full_happy_path(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)

    r = await task_start({"task_id": task_id}, db, session_id)
    assert r["status"] == "in_progress"

    r = await task_verify(
        {"task_id": task_id, "output": "looks good"}, db, session_id
    )
    assert r["status"] == "verifying"

    r = await task_done({"task_id": task_id}, db, session_id)
    assert r["status"] == "done"


async def test_invalid_transition_start_twice(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    await task_start({"task_id": task_id}, db, session_id)
    result = await task_start({"task_id": task_id}, db, session_id)
    assert "error" in result
    assert "Invalid transition" in result["error"]


async def test_invalid_transition_skip_verify(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    await task_start({"task_id": task_id}, db, session_id)
    result = await task_done({"task_id": task_id}, db, session_id)
    assert "error" in result


async def test_invalid_transition_done_before_start(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    result = await task_done({"task_id": task_id}, db, session_id)
    assert "error" in result


async def test_fail_from_in_progress(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    await task_start({"task_id": task_id}, db, session_id)
    result = await task_fail(
        {"task_id": task_id, "reason": "broke"}, db, session_id
    )
    assert result["status"] == "failed"


async def test_fail_from_verifying(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    await task_start({"task_id": task_id}, db, session_id)
    await task_verify({"task_id": task_id}, db, session_id)
    result = await task_fail(
        {"task_id": task_id, "reason": "criteria not met"}, db, session_id
    )
    assert result["status"] == "failed"


async def test_fail_from_pending_invalid(db, session_id):
    plan_id = await _make_plan(db, session_id)
    task_id = await _make_task(db, session_id, plan_id)
    result = await task_fail(
        {"task_id": task_id, "reason": "x"}, db, session_id
    )
    assert "error" in result


async def test_task_not_found(db, session_id):
    result = await task_start({"task_id": "bad-id"}, db, session_id)
    assert "error" in result


async def test_task_list(db, session_id):
    plan_id = await _make_plan(db, session_id)
    await _make_task(db, session_id, plan_id)
    await _make_task(db, session_id, plan_id)
    result = await task_list({"plan_id": plan_id}, db, session_id)
    assert len(result["tasks"]) == 2


async def test_task_list_plan_not_found(db, session_id):
    result = await task_list({"plan_id": "bad"}, db, session_id)
    assert "error" in result
