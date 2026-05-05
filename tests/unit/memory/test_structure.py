import uuid
from pathlib import Path

import pytest

from craftsman.memory.structure import StructureDB


@pytest.fixture
def db():
    instance = StructureDB(path=Path(":memory:"))
    yield instance
    instance.close()


@pytest.fixture
def uid(db):
    return db.create_user("testuser", "hashedpw")["id"]


@pytest.fixture
def sid(db):
    return db.create_session()


# --- users ---


def test_create_user_returns_id_and_username(db):
    row = db.create_user("alice", "hash")
    assert row["username"] == "alice"
    uuid.UUID(row["id"])


def test_get_user_found(db):
    db.create_user("alice", "hash")
    assert db.get_user("alice")["username"] == "alice"


def test_get_user_not_found(db):
    assert db.get_user("ghost") is None


def test_list_users(db):
    db.create_user("alice", "h1")
    db.create_user("bob", "h2")
    names = [r["username"] for r in db.list_users()]
    assert "alice" in names and "bob" in names


def test_delete_user(db):
    db.create_user("alice", "hash")
    db.delete_user("alice")
    assert db.get_user("alice") is None


def test_create_session_stores_user_id(db, uid):
    sid = db.create_session(user_id=uid)
    assert db.get_session(sid)["user_id"] == uid


def test_list_sessions_filtered_by_user_id(db, uid):
    s1 = db.create_session(user_id=uid)
    s2 = db.create_session(user_id=uid)
    other_uid = db.create_user("other", "h")["id"]
    s3 = db.create_session(user_id=other_uid)
    db.add_message(s1, "user", "hi")
    db.add_message(s2, "user", "hey")
    db.add_message(s3, "user", "yo")
    ids = [r["id"] for r in db.list_sessions(user_id=uid)]
    assert s1 in ids and s2 in ids and s3 not in ids


# --- sessions ---


def test_create_session_returns_uuid_string(db):
    sid = db.create_session()
    uuid.UUID(sid)  # raises if not valid UUID


def test_get_session_returns_row(db, sid):
    assert db.get_session(sid)["id"] == sid


def test_get_session_unknown_returns_none(db):
    assert db.get_session("nonexistent") is None


def test_delete_session_removes_row(db, sid):
    db.delete_session(sid)
    assert db.get_session(sid) is None


def test_delete_session_cascades_messages(db, sid):
    db.add_message(sid, "user", "hello")
    db.delete_session(sid)
    rows = db.conn.execute(
        "SELECT * FROM messages WHERE session_id = ?", (sid,)
    ).fetchall()
    assert rows == []


def test_end_session_sets_ended_at(db, sid):
    db.end_session(sid)
    assert db.get_session(sid)["ended_at"] is not None


def test_resolve_session_by_exact_id(db, sid):
    assert db.resolve_session(sid)["id"] == sid


def test_resolve_session_by_prefix(db, sid):
    assert db.resolve_session(sid[:8])["id"] == sid


def test_resolve_session_by_title(db):
    sid = db.create_session(title="mytitle")
    assert db.resolve_session("mytitle")["id"] == sid


def test_resolve_session_ambiguous_prefix_returns_none(db):
    db.conn.execute(
        "INSERT INTO sessions (id, created_at) VALUES (?, datetime('now'))",
        ("abcd1111-0000-0000-0000-000000000001",),
    )
    db.conn.execute(
        "INSERT INTO sessions (id, created_at) VALUES (?, datetime('now'))",
        ("abcd2222-0000-0000-0000-000000000002",),
    )
    db.conn.commit()
    assert db.resolve_session("abcd") is None


def test_list_sessions_empty_without_user_messages(db, sid):
    assert db.list_sessions() == []


def test_list_sessions_returns_sessions_with_user_messages(db):
    s1 = db.create_session()
    s2 = db.create_session()
    db.add_message(s1, "user", "hi")
    db.add_message(s2, "user", "hey")
    ids = [r["id"] for r in db.list_sessions()]
    assert s1 in ids and s2 in ids


def test_list_sessions_limit(db):
    for _ in range(3):
        s = db.create_session()
        db.add_message(s, "user", "x")
    assert len(db.list_sessions(limit=2)) == 2


# --- messages ---


def test_add_message_returns_uuid(db, sid):
    mid = db.add_message(sid, "user", "hello")
    uuid.UUID(mid)


def test_get_messages_returns_in_order(db, sid):
    db.add_message(sid, "user", "one")
    db.add_message(sid, "assistant", "two")
    db.add_message(sid, "user", "three")
    contents = [dict(m)["content"] for m in db.get_messages(sid)]
    assert contents == ["one", "two", "three"]


def test_get_messages_no_summary_returns_all(db, sid):
    db.add_message(sid, "user", "a")
    db.add_message(sid, "assistant", "b")
    assert len(db.get_messages(sid)) == 2


def test_get_messages_with_summary_returns_from_checkpoint(db, sid):
    db.conn.execute(
        "INSERT INTO messages "
        "(id, session_id, role, content, tokens, created_at)"
        " VALUES (?, ?, 'user', 'before', 5, '2020-01-01 00:00:00')",
        (str(uuid.uuid4()), sid),
    )
    db.conn.execute(
        "INSERT INTO messages "
        "(id, session_id, role, content, tokens, created_at)"
        " VALUES (?, ?, 'summary', 'the summary', 10, '2020-01-01 00:00:01')",
        (str(uuid.uuid4()), sid),
    )
    post_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO messages "
        "(id, session_id, role, content, tokens, created_at)"
        " VALUES (?, ?, 'user', 'after', 5, '2020-01-01 00:00:02')",
        (post_id, sid),
    )
    db.conn.commit()
    messages = db.get_messages(sid)
    contents = [dict(m)["content"] for m in messages]
    assert "before" not in contents
    assert "the summary" in contents
    assert "after" in contents


def test_get_messages_summary_itself_included(db, sid):
    db.conn.execute(
        "INSERT INTO messages "
        "(id, session_id, role, content, tokens, created_at)"
        " VALUES (?, ?, 'summary', 'compact', 10, '2020-01-01 00:00:01')",
        (str(uuid.uuid4()), sid),
    )
    db.conn.commit()
    contents = [dict(m)["content"] for m in db.get_messages(sid)]
    assert "compact" in contents


# --- projects ---


def test_create_and_get_project(db):
    pid = db.create_project("myproj")
    assert db.get_project(pid)["name"] == "myproj"


def test_delete_project(db):
    pid = db.create_project("todelete")
    db.delete_project(pid)
    assert db.get_project(pid) is None


def test_list_projects_count(db):
    db.create_project("p1")
    db.create_project("p2")
    assert len(db.list_projects()) == 2


# --- plans and tasks ---


def test_create_plan_and_get(db, sid):
    pid = db.create_plan("my goal", sid)
    row = db.get_plan(pid)
    assert row["goal"] == "my goal"
    assert row["status"] == "active"


def test_complete_plan(db, sid):
    pid = db.create_plan("goal", sid)
    db.complete_plan(pid)
    row = db.get_plan(pid)
    assert row["status"] == "done"
    assert row["ended_at"] is not None


def test_create_task_and_list(db, sid):
    pid = db.create_plan("goal", sid)
    db.create_task(pid, "do something")
    tasks = db.list_tasks(pid)
    assert len(tasks) == 1
    assert tasks[0]["description"] == "do something"


def test_update_task_status(db, sid):
    pid = db.create_plan("goal", sid)
    tid = db.create_task(pid, "task")
    db.update_task_status(tid, "done", output="ok")
    row = db.get_task(tid)
    assert row["status"] == "done"
    assert row["output"] == "ok"


# --- global_facts ---


def test_add_and_get_global_facts(db):
    db.add_global_fact("fact one")
    facts = db.get_global_facts()
    assert any(f["content"] == "fact one" for f in facts)


def test_delete_global_fact(db):
    fid = db.add_global_fact("to delete")
    db.delete_global_fact(fid)
    assert all(f["content"] != "to delete" for f in db.get_global_facts())


# --- artifacts ---


@pytest.fixture
def aid(db, uid, sid):
    return db.add_artifact(
        filepath="/tmp/test.jpg",
        filename="test.jpg",
        user_id=uid,
        session_id=sid,
        mime_type="image/jpeg",
        size_bytes=1024,
    )


def test_add_artifact_returns_uuid(db):
    result = db.add_artifact(filepath="", filename="file.jpg")
    uuid.UUID(result)


def test_add_artifact_stores_fields(db, uid, sid):
    aid = db.add_artifact(
        filepath="/tmp/x.jpg",
        filename="x.jpg",
        user_id=uid,
        session_id=sid,
        mime_type="image/jpeg",
        size_bytes=512,
    )
    row = db.get_artifact(aid)
    assert row["filename"] == "x.jpg"
    assert row["mime_type"] == "image/jpeg"
    assert row["size_bytes"] == 512
    assert row["user_id"] == uid


def test_update_artifact_updates_filepath_and_size(db, aid):
    db.update_artifact(aid, filepath="/new/path.jpg", size_bytes=9999)
    row = db.get_artifact(aid)
    assert row["filepath"] == "/new/path.jpg"
    assert row["size_bytes"] == 9999


def test_resolve_artifact_id_by_prefix(db, aid):
    assert db.resolve_artifact_id(aid[:8]) == aid


def test_resolve_artifact_id_exact_full_id(db, aid):
    assert db.resolve_artifact_id(aid) == aid


def test_resolve_artifact_id_ambiguous_returns_none(db):
    db.conn.execute(
        "INSERT INTO artifacts (id, filepath, filename, created_at)"
        " VALUES (?, '', 'a.jpg', datetime('now'))",
        ("abcd1111-0000-0000-0000-000000000001",),
    )
    db.conn.execute(
        "INSERT INTO artifacts (id, filepath, filename, created_at)"
        " VALUES (?, '', 'b.jpg', datetime('now'))",
        ("abcd2222-0000-0000-0000-000000000002",),
    )
    db.conn.commit()
    assert db.resolve_artifact_id("abcd") is None


def test_resolve_artifact_id_no_match_returns_none(db):
    assert db.resolve_artifact_id("nonexistent") is None


def test_get_artifact_returns_row(db, aid):
    assert db.get_artifact(aid)["id"] == aid


def test_get_artifact_unknown_returns_none(db):
    assert db.get_artifact("no-such-id") is None


def test_get_artifacts_by_user_id(db, uid):
    other_uid = db.create_user("other", "h")["id"]
    a1 = db.add_artifact(filepath="", filename="a.jpg", user_id=uid)
    a2 = db.add_artifact(filepath="", filename="b.jpg", user_id=other_uid)
    ids = [r["id"] for r in db.get_artifacts(user_id=uid)]
    assert a1 in ids and a2 not in ids


def test_get_artifacts_by_session_id(db, sid):
    other_sid = db.create_session()
    a1 = db.add_artifact(filepath="", filename="a.jpg", session_id=sid)
    a2 = db.add_artifact(filepath="", filename="b.jpg", session_id=other_sid)
    ids = [r["id"] for r in db.get_artifacts(session_id=sid)]
    assert a1 in ids and a2 not in ids


def test_get_artifacts_by_project_id(db):
    pid = db.create_project("proj")
    other_pid = db.create_project("other")
    a1 = db.add_artifact(filepath="", filename="a.jpg", project_id=pid)
    a2 = db.add_artifact(filepath="", filename="b.jpg", project_id=other_pid)
    ids = [r["id"] for r in db.get_artifacts(project_id=pid)]
    assert a1 in ids and a2 not in ids


def test_get_artifacts_no_filter_returns_all(db):
    db.add_artifact(filepath="", filename="a.jpg")
    db.add_artifact(filepath="", filename="b.jpg")
    assert len(db.get_artifacts()) == 2


def test_delete_artifact_removes_row(db, aid):
    db.delete_artifact(aid)
    assert db.get_artifact(aid) is None


# --- get_user_tokens ---


def test_get_user_tokens_no_messages(db, uid):
    db.create_session(user_id=uid)
    result = db.get_user_tokens(uid)
    assert result == {"upload_tokens": 0, "download_tokens": 0}


def test_get_user_tokens_sums_user_as_upload(db, uid):
    sid = db.create_session(user_id=uid)
    db.add_message(sid, "user", "hi", tokens=10)
    db.add_message(sid, "user", "hey", tokens=5)
    result = db.get_user_tokens(uid)
    assert result["upload_tokens"] == 15


def test_get_user_tokens_sums_assistant_and_reasoning_as_download(db, uid):
    sid = db.create_session(user_id=uid)
    db.add_message(sid, "assistant", "reply", tokens=8)
    db.add_message(sid, "reasoning", "thought", tokens=3)
    result = db.get_user_tokens(uid)
    assert result["download_tokens"] == 11


def test_get_user_tokens_ignores_tool_and_summary(db, uid):
    sid = db.create_session(user_id=uid)
    db.add_message(sid, "tool", "result", tokens=20)
    db.add_message(sid, "summary", "compact", tokens=30)
    result = db.get_user_tokens(uid)
    assert result["upload_tokens"] == 0
    assert result["download_tokens"] == 0


def test_get_user_tokens_excludes_other_users(db, uid):
    other_uid = db.create_user("other", "h")["id"]
    sid = db.create_session(user_id=uid)
    other_sid = db.create_session(user_id=other_uid)
    db.add_message(sid, "user", "mine", tokens=10)
    db.add_message(other_sid, "user", "theirs", tokens=50)
    result = db.get_user_tokens(uid)
    assert result["upload_tokens"] == 10
