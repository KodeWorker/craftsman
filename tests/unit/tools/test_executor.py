from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from craftsman.memory.structure import StructureDB
from craftsman.tools.executor import _DISPATCH, ToolExecutor
from craftsman.tools.registry import seed_registry


@pytest.fixture
def db():
    db = StructureDB(path=Path(":memory:"))
    seed_registry(db)
    yield db
    db.close()


async def test_unknown_tool_returns_error(db):
    executor = ToolExecutor(db)
    result = await executor.execute("unknown:tool", {})
    assert "error" in result


async def test_audited_tool_logs_invocation(db):
    executor = ToolExecutor(db)
    mock_fn = AsyncMock(return_value={"output": "ok", "truncated": False})
    with patch.dict(_DISPATCH, {"bash:ls": mock_fn}):
        await executor.execute("bash:ls", {"path": "/tmp"})
    rows = db.conn.execute("SELECT * FROM tool_invocations").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "bash:ls"
    assert rows[0]["is_error"] == 0


async def test_non_audited_tool_no_log(db):
    executor = ToolExecutor(db)
    mock_fn = AsyncMock(
        return_value={"lines": [], "total_lines": 0, "truncated": False}
    )
    with patch.dict(_DISPATCH, {"text:read": mock_fn}):
        await executor.execute("text:read", {"file": "/tmp/x"})
    rows = db.conn.execute("SELECT * FROM tool_invocations").fetchall()
    assert len(rows) == 0


async def test_exception_logs_is_error(db):
    executor = ToolExecutor(db)
    mock_fn = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.dict(_DISPATCH, {"bash:ls": mock_fn}):
        result = await executor.execute("bash:ls", {"path": "/tmp"})
    assert "error" in result
    rows = db.conn.execute("SELECT * FROM tool_invocations").fetchall()
    assert len(rows) == 1
    assert rows[0]["is_error"] == 1


async def test_error_result_logs_is_error(db):
    executor = ToolExecutor(db)
    mock_fn = AsyncMock(return_value={"error": "not found"})
    with patch.dict(_DISPATCH, {"bash:ls": mock_fn}):
        await executor.execute("bash:ls", {"path": "/bad"})
    rows = db.conn.execute("SELECT * FROM tool_invocations").fetchall()
    assert rows[0]["is_error"] == 1


async def test_increments_call_count(db):
    executor = ToolExecutor(db)
    mock_fn = AsyncMock(return_value={"output": "ok", "truncated": False})
    with patch.dict(_DISPATCH, {"bash:grep": mock_fn}):
        await executor.execute("bash:grep", {"pattern": "x", "path": "/tmp"})
    row = db.get_tool("bash:grep")
    assert row["call_count"] == 1


async def test_session_id_stored_in_invocation(db):
    executor = ToolExecutor(db)
    session_id = db.create_session()
    mock_fn = AsyncMock(return_value={"output": "ok", "truncated": False})
    with patch.dict(_DISPATCH, {"bash:ls": mock_fn}):
        await executor.execute(
            "bash:ls", {"path": "/tmp"}, session_id=session_id
        )
    row = db.conn.execute("SELECT * FROM tool_invocations").fetchone()
    assert row["session_id"] == session_id
