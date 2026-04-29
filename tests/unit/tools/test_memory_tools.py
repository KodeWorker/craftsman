import pytest

from craftsman.memory.librarian import Librarian
from craftsman.tools.memory_tools import (
    memory_forget,
    memory_retrieve,
    memory_store,
)


@pytest.fixture
def librarian():
    return Librarian.__new__(Librarian)


@pytest.fixture(autouse=True)
def _init_librarian(librarian):
    librarian.cache = {}


SESSION = "test-session"


async def test_store_and_retrieve_key(librarian):
    await memory_store({"key": "x", "value": 42}, librarian, SESSION)
    result = await memory_retrieve({"key": "x"}, librarian, SESSION)
    assert result == {"key": "x", "value": 42}


async def test_retrieve_all_scratchpad(librarian):
    await memory_store({"key": "a", "value": 1}, librarian, SESSION)
    await memory_store({"key": "b", "value": 2}, librarian, SESSION)
    result = await memory_retrieve({}, librarian, SESSION)
    assert result["scratchpad"] == {"a": 1, "b": 2}


async def test_retrieve_missing_key_error(librarian):
    result = await memory_retrieve({"key": "missing"}, librarian, SESSION)
    assert "error" in result


async def test_forget_removes_key(librarian):
    await memory_store({"key": "del", "value": "bye"}, librarian, SESSION)
    result = await memory_forget({"key": "del"}, librarian, SESSION)
    assert result["status"] == "forgotten"
    check = await memory_retrieve({"key": "del"}, librarian, SESSION)
    assert "error" in check


async def test_forget_missing_key_error(librarian):
    result = await memory_forget({"key": "nope"}, librarian, SESSION)
    assert "error" in result


async def test_sessions_isolated(librarian):
    await memory_store({"key": "k", "value": "s1"}, librarian, "session-1")
    result = await memory_retrieve({"key": "k"}, librarian, "session-2")
    assert "error" in result
