import json

import pytest

from craftsman.memory.librarian import Librarian
from craftsman.memory.structure import StructureDB
from craftsman.tools.meta_tools import (
    tool_describe,
    tool_find,
    tool_list,
    tool_revoke,
)

SESSION = "test-session"


@pytest.fixture
def db(tmp_path):
    return StructureDB(path=tmp_path / "test.db")


@pytest.fixture
def librarian():
    lib = Librarian.__new__(Librarian)
    lib.cache = {}
    return lib


@pytest.fixture
def seeded_db(db):
    db.register_tool(
        "bash:ls",
        "List directory contents",
        "bash",
        json.dumps({}),
        audited=False,
    )
    db.register_tool(
        "bash:grep",
        "Search file contents",
        "bash",
        json.dumps({}),
        audited=False,
    )
    db.register_tool(
        "tool:revoke",
        "Revoke a tool for this session",
        "meta",
        json.dumps({}),
        audited=False,
    )
    return db


# --- tool:list ---


async def test_tool_list_returns_all(seeded_db, librarian):
    result = await tool_list({}, seeded_db, librarian, SESSION)
    assert len(result["tools"]) == 3


async def test_tool_list_filters_by_category(seeded_db, librarian):
    result = await tool_list(
        {"category": "bash"}, seeded_db, librarian, SESSION
    )
    assert len(result["tools"]) == 2
    assert all(t["category"] == "bash" for t in result["tools"])


async def test_tool_list_excludes_revoked(seeded_db, librarian):
    librarian.revoke_tool(SESSION, "bash:ls")
    result = await tool_list({}, seeded_db, librarian, SESSION)
    names = [t["name"] for t in result["tools"]]
    assert "bash:ls" not in names
    assert "bash:grep" in names


async def test_tool_list_revoke_session_isolated(seeded_db, librarian):
    librarian.revoke_tool("session-A", "bash:ls")
    result = await tool_list({}, seeded_db, librarian, "session-B")
    names = [t["name"] for t in result["tools"]]
    assert "bash:ls" in names


# --- tool:describe ---


async def test_tool_describe_returns_schema(seeded_db, librarian):
    result = await tool_describe(
        {"name": "bash:ls"}, seeded_db, librarian, SESSION
    )
    assert result["name"] == "bash:ls"
    assert "parameters" in result
    assert result["category"] == "bash"


async def test_tool_describe_revoked_returns_error(seeded_db, librarian):
    librarian.revoke_tool(SESSION, "bash:ls")
    result = await tool_describe(
        {"name": "bash:ls"}, seeded_db, librarian, SESSION
    )
    assert "error" in result


async def test_tool_describe_not_found(seeded_db, librarian):
    result = await tool_describe(
        {"name": "fake:tool"}, seeded_db, librarian, SESSION
    )
    assert "error" in result


async def test_tool_describe_missing_name(seeded_db, librarian):
    result = await tool_describe({}, seeded_db, librarian, SESSION)
    assert "error" in result


# --- tool:find ---


async def test_tool_find_returns_injected_tool(seeded_db, librarian):
    result = await tool_find(
        {"keyword": "List directory"}, seeded_db, librarian, SESSION
    )
    assert "injected_tool" in result
    assert result["injected_tool"]["name"] == "bash:ls"


async def test_tool_find_no_match(seeded_db, librarian):
    result = await tool_find(
        {"keyword": "xyznotfound"}, seeded_db, librarian, SESSION
    )
    assert "error" in result


async def test_tool_find_missing_keyword(seeded_db, librarian):
    result = await tool_find({}, seeded_db, librarian, SESSION)
    assert "error" in result


async def test_tool_find_skips_revoked(seeded_db, librarian):
    librarian.revoke_tool(SESSION, "bash:ls")
    result = await tool_find(
        {"keyword": "List directory"}, seeded_db, librarian, SESSION
    )
    assert "error" in result


# --- tool:revoke ---


async def test_tool_revoke_prevents_list(seeded_db, librarian):
    await tool_revoke({"name": "bash:ls"}, seeded_db, librarian, SESSION)
    result = await tool_list({}, seeded_db, librarian, SESSION)
    names = [t["name"] for t in result["tools"]]
    assert "bash:ls" not in names


async def test_tool_revoke_self_guard(seeded_db, librarian):
    result = await tool_revoke(
        {"name": "tool:revoke"}, seeded_db, librarian, SESSION
    )
    assert "error" in result


async def test_tool_revoke_idempotent(seeded_db, librarian):
    await tool_revoke({"name": "bash:ls"}, seeded_db, librarian, SESSION)
    result = await tool_revoke(
        {"name": "bash:ls"}, seeded_db, librarian, SESSION
    )
    assert result["status"] == "revoked"


async def test_tool_revoke_missing_name(seeded_db, librarian):
    result = await tool_revoke({}, seeded_db, librarian, SESSION)
    assert "error" in result
