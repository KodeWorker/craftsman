from pathlib import Path

import pytest

from craftsman.memory.librarian import Librarian
from craftsman.memory.structure import StructureDB


@pytest.fixture
def librarian(mocker):
    mocker.patch("craftsman.memory.librarian.StructureDB")
    mocker.patch("craftsman.memory.librarian.VectorDB")
    mocker.patch("craftsman.memory.librarian.GraphDB")
    return Librarian()


@pytest.fixture
def librarian_with_real_db(mocker):
    mocker.patch("craftsman.memory.librarian.VectorDB")
    mocker.patch("craftsman.memory.librarian.GraphDB")
    mocker.patch("craftsman.memory.librarian.StructureDB")
    lib = Librarian()
    real_db = StructureDB(path=Path(":memory:"))
    lib.structure_db = real_db
    yield lib, real_db
    real_db.close()


# --- cache helpers ---


def test_key_format(librarian):
    assert librarian._key("s1", "context") == "session:s1:context"


def test_get_context_returns_empty_list_initially(librarian):
    assert librarian.get_context("new-id") == []


def test_push_context_appends_in_order(librarian):
    librarian.push_context("s", {"role": "user", "content": "a"})
    librarian.push_context("s", {"role": "assistant", "content": "b"})
    ctx = librarian.get_context("s")
    assert len(ctx) == 2
    assert ctx[0]["content"] == "a"
    assert ctx[1]["content"] == "b"


def test_clear_context_empties_list(librarian):
    librarian.push_context("s", {"role": "user", "content": "x"})
    librarian.clear_context("s")
    assert librarian.get_context("s") == []


def test_clear_system_prompt_removes_system_only(librarian):
    librarian.push_context("s", {"role": "system", "content": "sys"})
    librarian.push_context("s", {"role": "user", "content": "hi"})
    librarian.push_context("s", {"role": "assistant", "content": "hello"})
    librarian.clear_system_prompt("s")
    ctx = librarian.get_context("s")
    assert all(m["role"] != "system" for m in ctx)
    assert len(ctx) == 2


def test_clear_system_prompt_on_empty_cache(librarian):
    librarian.clear_system_prompt("never-seen")  # must not raise


def test_clear_session_removes_all_three_slots(librarian):
    librarian.push_context("s", {"role": "user", "content": "x"})
    librarian.set_scratchpad("s", "k", "v")
    librarian.set_state("s", "k", "v")
    librarian.clear_session("s")
    for slot in ("scratchpad", "state", "context"):
        assert librarian._key("s", slot) not in librarian.cache


def test_clear_session_on_absent_session_is_noop(librarian):
    librarian.clear_session("ghost")  # must not raise


def test_get_scratchpad_returns_same_dict(librarian):
    a = librarian.get_scratchpad("s")
    b = librarian.get_scratchpad("s")
    assert a is b


def test_set_scratchpad_stores_value(librarian):
    librarian.set_scratchpad("s", "mykey", "myval")
    assert librarian.get_scratchpad("s")["mykey"] == "myval"


def test_tasks_list_accumulates(librarian):
    librarian.add_task({"name": "t1"})
    librarian.add_task({"name": "t2"})
    assert len(librarian.get_tasks()) == 2


# --- retrieve_messages / store_message (real DB) ---


def test_store_message_delegates_to_structure_db(librarian_with_real_db):
    lib, real_db = librarian_with_real_db
    sid = real_db.create_session()
    msg = {"role": "user", "content": "hello", "tokens": 5}
    mid = lib.store_message(sid, msg)
    assert mid is not None
    rows = real_db.get_messages(sid)
    assert len(rows) == 1
    assert dict(rows[0])["content"] == "hello"


def test_retrieve_messages_token_stats(librarian_with_real_db):
    lib, real_db = librarian_with_real_db
    sid = real_db.create_session()
    real_db.add_message(sid, "user", "a", tokens=10)
    real_db.add_message(sid, "assistant", "b", tokens=20)
    real_db.add_message(sid, "user", "c", tokens=5)
    _, stats = lib.retrieve_messages(sid)
    assert stats["ctx_used"] == 35
    assert stats["upload_tokens"] == 15
    assert stats["download_tokens"] == 20


def test_retrieve_messages_limit(librarian_with_real_db):
    lib, real_db = librarian_with_real_db
    sid = real_db.create_session()
    for i in range(5):
        real_db.add_message(sid, "user", f"msg{i}", tokens=1)
    messages, _ = lib.retrieve_messages(sid, limit=2)
    assert len(messages) == 2
    assert messages[-1]["content"] == "msg4"


def test_retrieve_messages_empty_session(librarian_with_real_db):
    lib, real_db = librarian_with_real_db
    sid = real_db.create_session()
    messages, stats = lib.retrieve_messages(sid)
    assert messages == []
    assert stats == {"ctx_used": 0, "upload_tokens": 0, "download_tokens": 0}
