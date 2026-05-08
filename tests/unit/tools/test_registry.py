import json
from pathlib import Path

import pytest

from craftsman.memory.structure import StructureDB
from craftsman.tools.registry import _TOOLS, _enabled_tools, seed_registry


@pytest.fixture
def db():
    db = StructureDB(path=Path(":memory:"))
    yield db
    db.close()


def test_seed_populates_tools(db):
    seed_registry(db)
    rows = db.list_tools()
    assert len(rows) == len(_enabled_tools())


def test_names_are_unique():
    names = [t["name"] for t in _TOOLS]
    assert len(names) == len(set(names))


def test_all_required_fields():
    for t in _TOOLS:
        assert "name" in t
        assert "description" in t
        assert "category" in t
        assert "audited" in t
        assert "parameters" in t
        assert t["description"].strip()


def test_schemas_are_valid_json(db):
    seed_registry(db)
    for row in db.list_tools():
        parsed = json.loads(row["schema"])
        assert parsed["type"] == "object"
        assert "properties" in parsed
        assert "required" in parsed


def test_idempotent_reseed(db):
    seed_registry(db)
    seed_registry(db)
    rows = db.list_tools()
    assert len(rows) == len(_enabled_tools())


def test_audited_flags():
    by_name = {t["name"]: t for t in _TOOLS}
    # bash tools are all audited
    assert by_name["bash:grep"]["audited"] is True
    assert by_name["bash:ls"]["audited"] is True
    # read-only tools are not audited
    assert by_name["text:read"]["audited"] is False
    assert by_name["tool:list"]["audited"] is False
    assert by_name["memory:retrieve"]["audited"] is False
    # write/action tools are audited
    assert by_name["text:replace"]["audited"] is True
    assert by_name["memory:store"]["audited"] is True
    assert by_name["tool:revoke"]["audited"] is True


def test_audited_stored_in_db(db):
    seed_registry(db)
    row = db.get_tool("bash:grep")
    assert row["audited"] == 1
    row = db.get_tool("text:read")
    assert row["audited"] == 0


def test_categories_are_valid():
    valid = {
        "meta",
        "bash",
        "text",
        "memory",
        "schedule",
        "web",
        "plan",
        "agent",
    }
    for t in _TOOLS:
        assert (
            t["category"] in valid
        ), f"{t['name']} has unknown category {t['category']}"


def test_seed_registry_skips_if_no_enabled_tools(db, mocker):
    mocker.patch("craftsman.tools.registry._enabled_tools", return_value=[])
    seed_registry(db)
    assert db.list_tools() == []
