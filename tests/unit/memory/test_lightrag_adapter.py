"""Tests for LightRAGAdapter — always runs; LightRAG itself is mocked."""

import pytest

from craftsman.memory.graph import GraphDB
from craftsman.memory.lightrag_adapter import (
    _LIGHTRAG_AVAILABLE,
    LightRAGAdapter,
)

# --- adapter disabled when lightrag not available ---


def test_adapter_unavailable_when_lightrag_missing(mocker, tmp_path):
    mocker.patch(
        "craftsman.memory.lightrag_adapter._LIGHTRAG_AVAILABLE", False
    )
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=None,
        embed_func=None,
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    assert adapter._available is False


@pytest.mark.asyncio
async def test_insert_noop_when_unavailable(mocker, tmp_path):
    mocker.patch(
        "craftsman.memory.lightrag_adapter._LIGHTRAG_AVAILABLE", False
    )
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=None,
        embed_func=None,
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    await adapter.insert("some text", session_id="s1")  # must not raise


@pytest.mark.asyncio
async def test_query_noop_when_unavailable(mocker, tmp_path):
    mocker.patch(
        "craftsman.memory.lightrag_adapter._LIGHTRAG_AVAILABLE", False
    )
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=None,
        embed_func=None,
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    result = await adapter.query("what happened?")
    assert result == ""


# --- with mocked LightRAG ---


@pytest.fixture
def mock_rag(mocker):
    if not _LIGHTRAG_AVAILABLE:
        pytest.skip("lightrag-hku not installed")
    mock = mocker.MagicMock()
    mock.ainsert = mocker.AsyncMock(return_value=None)
    mock.aquery = mocker.AsyncMock(return_value="Alice works on craftsman.")
    mocker.patch(
        "craftsman.memory.lightrag_adapter.LightRAG", return_value=mock
    )
    mocker.patch("craftsman.memory.lightrag_adapter.EmbeddingFunc")
    return mock


@pytest.mark.asyncio
async def test_insert_calls_ainsert(mock_rag, tmp_path):
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=lambda p, **kw: "",
        embed_func=lambda t: [],
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    await adapter.insert("Alice works on craftsman.", session_id="s1")
    mock_rag.ainsert.assert_awaited_once_with("Alice works on craftsman.")


@pytest.mark.asyncio
async def test_insert_empty_text_skipped(mock_rag, tmp_path):
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=lambda p, **kw: "",
        embed_func=lambda t: [],
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    await adapter.insert("   ", session_id="s1")
    mock_rag.ainsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_returns_rag_result(mock_rag, tmp_path):
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=lambda p, **kw: "",
        embed_func=lambda t: [],
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    result = await adapter.query("who works on craftsman?")
    assert "Alice" in result


@pytest.mark.asyncio
async def test_insert_exception_is_swallowed(mocker, tmp_path):
    if not _LIGHTRAG_AVAILABLE:
        pytest.skip("lightrag-hku not installed")
    mock = mocker.MagicMock()
    mock.ainsert = mocker.AsyncMock(side_effect=RuntimeError("boom"))
    mocker.patch(
        "craftsman.memory.lightrag_adapter.LightRAG", return_value=mock
    )
    mocker.patch("craftsman.memory.lightrag_adapter.EmbeddingFunc")
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=lambda p, **kw: "",
        embed_func=lambda t: [],
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    await adapter.insert("some text")  # must not raise


@pytest.mark.asyncio
async def test_query_exception_returns_empty(mocker, tmp_path):
    if not _LIGHTRAG_AVAILABLE:
        pytest.skip("lightrag-hku not installed")
    mock = mocker.MagicMock()
    mock.aquery = mocker.AsyncMock(side_effect=RuntimeError("boom"))
    mocker.patch(
        "craftsman.memory.lightrag_adapter.LightRAG", return_value=mock
    )
    mocker.patch("craftsman.memory.lightrag_adapter.EmbeddingFunc")
    adapter = LightRAGAdapter(
        working_dir=str(tmp_path / "lr"),
        llm_func=lambda p, **kw: "",
        embed_func=lambda t: [],
        graph_db=GraphDB(gml_path=tmp_path / "g.gml"),
    )
    result = await adapter.query("what happened?")
    assert result == ""
