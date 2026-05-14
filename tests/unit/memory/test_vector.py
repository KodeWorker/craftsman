"""Tests for VectorDB.  Skipped when sqlite-vec is not installed."""

import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec", reason="sqlite-vec not installed"
)

from craftsman.memory.vector import VectorDB  # noqa: E402

# Deterministic 4-dim embed: returns a fixed vector per text using character
# sum — enough to distinguish different strings in tests.
_DIM = 4


def _embed(text: str) -> list[float]:
    base = [float(ord(c) % 10) / 10.0 for c in text[:_DIM]]
    base += [0.0] * (_DIM - len(base))
    return base


@pytest.fixture
def vdb():
    return VectorDB(db_path=":memory:", embed_fn=_embed, dimensions=_DIM)


# --- availability ---


def test_vdb_available(vdb):
    assert vdb._available is True


def test_vdb_unavailable_without_embed_fn():
    db = VectorDB(db_path=":memory:", embed_fn=None, dimensions=_DIM)
    assert db._available is False


# --- tools ---


def test_store_and_search_tool(vdb):
    vdb.store_tool("bash:ls", "List directory contents")
    vdb.store_tool("bash:grep", "Search file contents with regex")
    results = vdb.search_tools("list", top_k=5)
    assert len(results) >= 1
    names = [r["name"] for r in results]
    assert "bash:ls" in names or "bash:grep" in names  # at least one hit


def test_search_tools_empty_db(vdb):
    assert vdb.search_tools("anything") == []


def test_store_tool_idempotent(vdb):
    vdb.store_tool("bash:ls", "List directory contents")
    vdb.store_tool("bash:ls", "List directory contents updated")
    results = vdb.search_tools("list", top_k=5)
    assert sum(1 for r in results if r["name"] == "bash:ls") == 1


def test_store_tool_embed_failure(mocker):
    def bad_embed(text):
        raise RuntimeError("no model")

    db = VectorDB(db_path=":memory:", embed_fn=bad_embed, dimensions=_DIM)
    db.store_tool("bash:ls", "List directory")  # must not raise
    assert db.search_tools("list") == []


def test_seed_from_registry(vdb, mocker):
    mock_db = mocker.MagicMock()
    mock_db.list_tools.return_value = [
        {"name": "bash:ls", "description": "List directory contents"},
        {"name": "bash:grep", "description": "Search file contents"},
    ]
    vdb.seed_from_registry(mock_db)
    results = vdb.search_tools("directory", top_k=5)
    assert len(results) >= 1


# --- chunks ---


def test_store_and_search_chunk(vdb):
    vdb.store_chunk("s1:foo", "remember to use pytest", "s1")
    results = vdb.search_chunks("pytest", top_k=3)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "s1:foo"
    assert results[0]["session_id"] == "s1"


def test_search_chunks_session_filter(vdb):
    vdb.store_chunk("s1:k", "hello from session one", "s1")
    vdb.store_chunk("s2:k", "hello from session two", "s2")
    results = vdb.search_chunks("hello", top_k=5, session_id="s1")
    assert all(r["session_id"] == "s1" for r in results)


def test_remove_chunk(vdb):
    vdb.store_chunk("s1:x", "some content", "s1")
    vdb.remove_chunk("s1:x")
    results = vdb.search_chunks("content", top_k=5)
    assert not any(r["chunk_id"] == "s1:x" for r in results)


def test_remove_nonexistent_chunk_is_noop(vdb):
    vdb.remove_chunk("ghost:key")  # must not raise


# --- no-op when unavailable ---


def test_noop_methods_when_unavailable():
    db = VectorDB()
    assert db._available is False
    db.store_tool("t", "desc")
    assert db.search_tools("t") == []
    db.store_chunk("id", "content", "s")
    assert db.search_chunks("content") == []
    db.remove_chunk("id")
    db.seed_from_registry(None)
