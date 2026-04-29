from craftsman.tools.text_tools import (
    commit_tmp,
    discard_tmp,
    text_delete,
    text_insert,
    text_read,
    text_replace,
    text_search,
)


async def test_read_returns_line_numbers(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("alpha\nbeta\ngamma\n")
    result = await text_read({"file": str(f)})
    assert result["lines"][0] == {"n": 1, "text": "alpha"}
    assert result["lines"][1] == {"n": 2, "text": "beta"}
    assert result["lines"][2] == {"n": 3, "text": "gamma"}
    assert result["total_lines"] == 3
    assert result["truncated"] is False


async def test_read_line_range(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = await text_read({"file": str(f), "line_start": 2, "line_end": 4})
    assert len(result["lines"]) == 3
    assert result["lines"][0] == {"n": 2, "text": "b"}
    assert result["lines"][2] == {"n": 4, "text": "d"}


async def test_read_truncates_to_tail(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(f"line{i}" for i in range(50)) + "\n")
    result = await text_read({"file": str(f), "max_lines": 10})
    assert result["truncated"] is True
    assert result["omitted"] == 40
    assert len(result["lines"]) == 10
    assert result["lines"][-1]["text"] == "line49"
    assert result["lines"][0]["n"] == 41


async def test_search_finds_matches(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("foo\nbar\nbaz\nfoo again\n")
    result = await text_search({"file": str(f), "pattern": "foo"})
    assert result["total_matches"] == 2
    match_lines = [m["line"] for m in result["matches"]]
    assert 1 in match_lines
    assert 4 in match_lines


async def test_search_context_lines(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = await text_search(
        {"file": str(f), "pattern": "c", "context_lines": 1}
    )
    ctx = result["matches"][0]["context"]
    texts = [e["text"] for e in ctx]
    assert "b" in texts
    assert "c" in texts
    assert "d" in texts


async def test_search_no_match(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world\n")
    result = await text_search({"file": str(f), "pattern": "xyz"})
    assert result["total_matches"] == 0


# --- text:replace ---


async def test_replace_returns_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    assert result["status"] == "pending"
    assert result["tmp"].endswith(".tmp")
    assert result["file"] == str(f)
    assert f.read_text() == "hello world"  # unchanged until commit


async def test_replace_tmp_in_craftsman_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    assert (tmp_path / ".craftsman" / "test.txt.tmp").exists()
    discard_tmp(result["tmp"])


async def test_replace_commit_applies_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    commit_tmp(result["file"], result["tmp"])
    assert f.read_text() == "hello there"


async def test_replace_commit_creates_bak_in_craftsman_dir(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    commit_tmp(result["file"], result["tmp"])
    bak = tmp_path / ".craftsman" / "test.txt.bak"
    assert bak.exists()
    assert bak.read_text() == "hello world"


async def test_replace_commit_removes_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    commit_tmp(result["file"], result["tmp"])
    assert not (tmp_path / ".craftsman" / "test.txt.tmp").exists()


async def test_replace_discard_removes_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "world", "new_string": "there"}
    )
    discard_tmp(result["tmp"])
    assert f.read_text() == "hello world"
    assert not (tmp_path / ".craftsman" / "test.txt.tmp").exists()


async def test_replace_not_found_error(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = await text_replace(
        {"file": str(f), "old_string": "xyz", "new_string": "abc"}
    )
    assert "error" in result
    assert f.read_text() == "hello world"


async def test_replace_ambiguous_error(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("foo foo")
    result = await text_replace(
        {"file": str(f), "old_string": "foo", "new_string": "bar"}
    )
    assert "error" in result
    assert f.read_text() == "foo foo"


# --- text:insert ---


async def test_insert_returns_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\n")
    result = await text_insert(
        {"file": str(f), "line_num": 2, "lines": ["x", "y"]}
    )
    assert result["status"] == "pending"
    assert result["lines_inserted"] == 2
    assert f.read_text() == "a\nb\nc\n"  # unchanged until commit


async def test_insert_commit_applies_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\n")
    result = await text_insert(
        {"file": str(f), "line_num": 2, "lines": ["x", "y"]}
    )
    commit_tmp(result["file"], result["tmp"])
    assert f.read_text() == "a\nx\ny\nb\nc\n"


async def test_insert_commit_creates_bak_in_craftsman_dir(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\n")
    result = await text_insert({"file": str(f), "line_num": 1, "lines": ["z"]})
    commit_tmp(result["file"], result["tmp"])
    assert (tmp_path / ".craftsman" / "test.txt.bak").exists()


# --- text:delete ---


async def test_delete_returns_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\nd\n")
    result = await text_delete(
        {"file": str(f), "line_start": 2, "line_end": 3}
    )
    assert result["status"] == "pending"
    assert result["lines_deleted"] == 2
    assert f.read_text() == "a\nb\nc\nd\n"  # unchanged until commit


async def test_delete_commit_applies_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\nd\n")
    result = await text_delete(
        {"file": str(f), "line_start": 2, "line_end": 3}
    )
    commit_tmp(result["file"], result["tmp"])
    assert f.read_text() == "a\nd\n"


async def test_delete_commit_creates_bak_in_craftsman_dir(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\n")
    result = await text_delete(
        {"file": str(f), "line_start": 1, "line_end": 1}
    )
    commit_tmp(result["file"], result["tmp"])
    assert (tmp_path / ".craftsman" / "test.txt.bak").exists()


async def test_delete_invalid_range(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\n")
    result = await text_delete(
        {"file": str(f), "line_start": 2, "line_end": 10}
    )
    assert "error" in result
    assert f.read_text() == "a\nb\nc\n"
