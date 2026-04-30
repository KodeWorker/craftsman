from craftsman.tools.bash_tools import (
    bash_cat,
    bash_df,
    bash_find,
    bash_grep,
    bash_head,
    bash_ls,
    bash_ps,
    bash_run,
    bash_stat,
    bash_tail,
)


async def test_ls_lists_files(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("y")
    result = await bash_ls({"path": str(tmp_path)})
    assert "error" not in result
    assert "a.txt" in result["output"]
    assert "b.txt" in result["output"]


async def test_ls_bad_path_returns_error():
    result = await bash_ls({"path": "/nonexistent_craftsman_test_path"})
    assert "error" in result


async def test_cat_reads_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")
    result = await bash_cat({"file": str(f)})
    assert "error" not in result
    assert "line1" in result["output"]
    assert result["truncated"] is False


async def test_cat_truncates_to_tail(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(50)))
    result = await bash_cat({"file": str(f), "max_lines": 10})
    assert result["truncated"] is True
    assert "omitted" in result["output"]
    assert "line49" in result["output"]  # last line shown


async def test_cat_line_range(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("a\nb\nc\nd\ne\n")
    result = await bash_cat({"file": str(f), "line_start": 2, "line_end": 4})
    assert "b" in result["output"]
    assert "a" not in result["output"]
    assert "e" not in result["output"]


async def test_grep_finds_pattern(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    pass\ndef bar():\n    return 1\n")
    result = await bash_grep({"pattern": "def", "path": str(f)})
    assert "error" not in result
    assert "foo" in result["output"]
    assert "bar" in result["output"]


async def test_grep_no_match_is_not_error(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world\n")
    result = await bash_grep({"pattern": "xyz_no_match", "path": str(f)})
    assert "error" not in result


async def test_grep_bad_path_returns_error():
    result = await bash_grep(
        {"pattern": "foo", "path": "/nonexistent_craftsman_test"}
    )
    assert "error" in result


async def test_grep_truncates_to_tail(tmp_path):
    f = tmp_path / "big.txt"
    lines = "\n".join(f"match line {i}" for i in range(50))
    f.write_text(lines)
    result = await bash_grep(
        {"pattern": "match", "path": str(f), "max_lines": 10}
    )
    assert result["truncated"] is True
    assert "omitted" in result["output"]


async def test_find_locates_files(tmp_path):
    (tmp_path / "foo.py").write_text("")
    (tmp_path / "bar.txt").write_text("")
    result = await bash_find(
        {"path": str(tmp_path), "name_pattern": "*.py", "type": "f"}
    )
    assert "error" not in result
    assert "foo.py" in result["output"]
    assert "bar.txt" not in result["output"]


async def test_head_returns_first_lines(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(f"line{i}" for i in range(20)))
    result = await bash_head({"file": str(f), "n_lines": 3})
    assert "error" not in result
    assert "line0" in result["output"]


async def test_tail_returns_last_lines(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(f"line{i}" for i in range(20)))
    result = await bash_tail({"file": str(f), "n_lines": 3})
    assert "error" not in result
    assert "line19" in result["output"]
    assert "line0" not in result["output"]


async def test_stat_returns_metadata(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = await bash_stat({"file": str(f)})
    assert "error" not in result
    assert result["size_bytes"] == 5
    assert "mode" in result
    assert "mtime" in result


async def test_stat_bad_path_raises():
    result = await bash_stat({"file": "/nonexistent_craftsman_test"})
    assert "error" in result


async def test_ps_returns_output():
    result = await bash_ps({})
    assert "error" not in result
    assert "output" in result


async def test_ps_name_filter(tmp_path):
    result = await bash_ps({"name_filter": "python"})
    assert "error" not in result


async def test_df_returns_output():
    result = await bash_df({"path": "/"})
    assert "error" not in result
    assert "output" in result


async def test_run_executes_command():
    result = await bash_run({"cmd": "echo hello"})
    assert "error" not in result
    assert "hello" in result["output"]


async def test_run_captures_nonzero_exit():
    result = await bash_run({"cmd": "false"})
    assert "error" not in result or result.get("output") == ""


async def test_run_truncates_output():
    result = await bash_run({"cmd": "seq 1 300", "max_lines": 10})
    lines = result["output"].splitlines()
    assert result["truncated"] is True
    assert len(lines) <= 11  # 10 lines + truncation marker


async def test_run_empty_cmd_returns_error():
    result = await bash_run({"cmd": ""})
    assert "error" in result


async def test_run_invalid_shlex_returns_error():
    result = await bash_run({"cmd": "echo 'unterminated"})
    assert "error" in result


async def test_run_uses_shlex_not_shell(tmp_path):
    f = tmp_path / "safe file.txt"
    f.write_text("ok")
    result = await bash_run({"cmd": f"cat {str(f)!r}"})
    assert "error" not in result
    assert "ok" in result["output"]
