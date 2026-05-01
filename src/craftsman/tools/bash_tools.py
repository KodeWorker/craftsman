import asyncio
import datetime
import os
import shlex
import stat as _stat

from craftsman.configure import get_config


def _cat_max_lines() -> int:
    return (
        get_config()
        .get("tools", {})
        .get("bash", {})
        .get("cat", {})
        .get("max_lines", 200)
    )


def _run_max_lines() -> int:
    return (
        get_config()
        .get("tools", {})
        .get("bash", {})
        .get("run", {})
        .get("max_lines", 200)
    )


async def _run(
    cmd: list[str], max_lines: int = 200, ok_codes: tuple = (0,)
) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode not in ok_codes:
        err = stderr.decode(errors="replace").strip()
        return {"error": err or f"exit code {proc.returncode}"}
    lines = stdout.decode(errors="replace").splitlines()
    truncated = len(lines) > max_lines
    if truncated:
        omitted = len(lines) - max_lines
        lines = lines[-max_lines:]
        lines.insert(0, f"[... {omitted} lines omitted ...]")
    return {
        "output": "\n".join(lines),
        "truncated": truncated,
        "exit_code": proc.returncode,
    }


async def bash_ls(args: dict) -> dict:
    path = args["path"]
    recursive = args.get("recursive", False)
    flags = "-laR" if recursive else "-la"
    cmd = shlex.split(f"ls {flags} {shlex.quote(path)}")
    return await _run(cmd)


async def bash_cat(args: dict) -> dict:
    file = args["file"]
    max_lines = args.get("max_lines", _cat_max_lines())
    line_start = args.get("line_start")
    line_end = args.get("line_end")
    with open(file, "r", errors="replace") as f:
        lines = f.readlines()
    start = (line_start - 1) if line_start else 0
    end = line_end if line_end else len(lines)
    lines = lines[start:end]
    truncated = len(lines) > max_lines
    if truncated:
        omitted = len(lines) - max_lines
        lines = lines[-max_lines:]
    output = "".join(lines)
    if truncated:
        output = f"[... {omitted} lines omitted ...]\n" + output
    return {"output": output, "truncated": truncated}


async def bash_grep(args: dict) -> dict:
    pattern = args["pattern"]
    path = args["path"]
    recursive = args.get("recursive", False)
    max_lines = args.get("max_lines", 100)
    flags = "-nr" if recursive else "-n"
    cmd = shlex.split(
        f"grep {flags} {shlex.quote(pattern)} {shlex.quote(path)}"
    )
    # grep exits 1 for no matches — not an error
    return await _run(cmd, max_lines, ok_codes=(0, 1))


async def bash_find(args: dict) -> dict:
    path = args["path"]
    name_pattern = args.get("name_pattern")
    type_ = args.get("type")
    max_results = args.get("max_results", 50)
    cmd = shlex.split(f"find {shlex.quote(path)}")
    if type_:
        cmd.extend(["-type", type_])
    if name_pattern:
        cmd.extend(["-name", name_pattern])
    return await _run(cmd, max_results)


async def bash_head(args: dict) -> dict:
    file = args["file"]
    n = args.get("n_lines", 20)
    cmd = shlex.split(f"head -n{n} {shlex.quote(file)}")
    return await _run(cmd, n + 5)


async def bash_tail(args: dict) -> dict:
    file = args["file"]
    n = args.get("n_lines", 20)
    cmd = shlex.split(f"tail -n{n} {shlex.quote(file)}")
    return await _run(cmd, n + 5)


async def bash_stat(args: dict) -> dict:
    file = args["file"]
    try:
        st = os.stat(file)
    except OSError as e:
        return {"error": str(e)}
    return {
        "file": file,
        "size_bytes": st.st_size,
        "mode": _stat.filemode(st.st_mode),
        "mtime": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
        "atime": datetime.datetime.fromtimestamp(st.st_atime).isoformat(),
        "ctime": datetime.datetime.fromtimestamp(st.st_ctime).isoformat(),
    }


async def bash_ps(args: dict) -> dict:
    name_filter = args.get("name_filter")
    result = await _run(shlex.split("ps aux"))
    if "error" in result or not name_filter:
        return result
    lines = result["output"].splitlines()
    header = lines[:1]
    matched = [ln for ln in lines[1:] if name_filter.lower() in ln.lower()]
    return {"output": "\n".join(header + matched), "truncated": False}


async def bash_df(args: dict) -> dict:
    path = args.get("path", "/")
    cmd = shlex.split(f"df -h {shlex.quote(path)}")
    return await _run(cmd)


async def bash_du(args: dict) -> dict:
    path = args["path"]
    max_depth = args.get("max_depth", 1)
    cmd = shlex.split(f"du -h --max-depth={max_depth} {shlex.quote(path)}")
    return await _run(cmd)


async def bash_run(args: dict) -> dict:
    cmd_str = args.get("cmd", "").strip()
    if not cmd_str:
        return {"error": "cmd is required"}
    max_lines = args.get("max_lines", _run_max_lines())
    try:
        cmd = shlex.split(cmd_str)
    except ValueError as e:
        return {"error": f"invalid command: {e}"}
    return await _run(cmd, max_lines, ok_codes=tuple(range(256)))
