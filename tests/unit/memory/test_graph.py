"""Tests for GraphDB.  Skipped when networkx is not installed."""

import pytest

nx = pytest.importorskip("networkx", reason="networkx not installed")

from craftsman.memory.graph import GraphDB  # noqa: E402


@pytest.fixture
def gdb(tmp_path):
    return GraphDB(gml_path=tmp_path / "test.gml")


# --- availability ---


def test_gdb_available(gdb):
    assert gdb._available is True
    assert gdb.graph is not None


# --- add / get entity ---


def test_add_and_get_entity(gdb):
    gdb.add_entity("Alice", "person", "A software engineer", layer="session")
    e = gdb.get_entity("Alice")
    assert e is not None
    assert e["entity_type"] == "person"
    assert e["layer"] == "session"


def test_add_entity_updates_existing(gdb):
    gdb.add_entity("Bob", "person", "Original", layer="session")
    gdb.add_entity("Bob", "person", "Updated", layer="project")
    e = gdb.get_entity("Bob")
    assert e["description"] == "Updated"
    assert e["layer"] == "project"


def test_get_entity_missing_returns_none(gdb):
    assert gdb.get_entity("ghost") is None


# --- add chunk ---


def test_add_chunk(gdb):
    gdb.add_chunk("c1", "hello world", "s1", tokens=5)
    assert gdb.graph.has_node("c1")
    assert gdb.graph.nodes["c1"]["node_type"] == "chunk"


# --- relations ---


def test_add_relation(gdb):
    gdb.add_entity("Alice", "person", "", layer="session")
    gdb.add_entity("craftsman", "project", "", layer="project")
    gdb.add_relation("Alice", "craftsman", description="works on")
    assert gdb.graph.has_edge("Alice", "craftsman")
    assert gdb.graph["Alice"]["craftsman"]["edge_type"] == "RELATED_TO"


def test_add_mention(gdb):
    gdb.add_entity("Alice", "person", "", layer="session")
    gdb.add_chunk("c1", "alice said hello", "s1")
    gdb.add_mention("Alice", "c1")
    assert gdb.graph.has_edge("Alice", "c1")
    assert gdb.graph["Alice"]["c1"]["edge_type"] == "MENTIONED_IN"


# --- query_neighbors ---


def test_query_neighbors_depth1(gdb):
    gdb.add_entity("A", "concept", "root", layer="session")
    gdb.add_entity("B", "concept", "neighbor", layer="session")
    gdb.add_entity("C", "concept", "far", layer="session")
    gdb.add_relation("A", "B")
    gdb.add_relation("B", "C")

    neighbors = gdb.query_neighbors("A", depth=1)
    names = [n["name"] for n in neighbors]
    assert "B" in names
    assert "C" not in names


def test_query_neighbors_depth2(gdb):
    gdb.add_entity("A", "concept", "", layer="session")
    gdb.add_entity("B", "concept", "", layer="session")
    gdb.add_entity("C", "concept", "", layer="session")
    gdb.add_relation("A", "B")
    gdb.add_relation("B", "C")

    neighbors = gdb.query_neighbors("A", depth=2)
    names = [n["name"] for n in neighbors]
    assert "B" in names
    assert "C" in names


def test_query_neighbors_missing_node(gdb):
    assert gdb.query_neighbors("ghost") == []


# --- GML round-trip ---


def test_save_and_reload(tmp_path):
    path = tmp_path / "graph.gml"
    g1 = GraphDB(gml_path=path)
    g1.add_entity("Alice", "person", "A dev", layer="session")
    g1.add_entity("craftsman", "project", "The agent", layer="project")
    g1.add_relation("Alice", "craftsman", description="works on")
    g1.save()

    g2 = GraphDB(gml_path=path)
    e = g2.get_entity("Alice")
    assert e is not None
    assert e["entity_type"] == "person"
    assert g2.graph.has_edge("Alice", "craftsman")


def test_close_alias_for_save(tmp_path):
    path = tmp_path / "graph.gml"
    g = GraphDB(gml_path=path)
    g.add_entity("X", "concept", "", layer="session")
    g.close()
    assert path.exists()


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "graph.gml"
    g = GraphDB(gml_path=path)
    g.add_entity("Y", "concept", "", layer="session")
    g.save()
    assert path.exists()


# --- no-op when unavailable ---


def test_noop_when_unavailable(mocker):
    mocker.patch("craftsman.memory.graph._NX_AVAILABLE", False)
    g = GraphDB(gml_path=":memory:")
    g.add_entity("X", "concept", "", layer="session")
    assert g.get_entity("X") is None
    assert g.query_neighbors("X") == []
    g.save()  # must not raise
