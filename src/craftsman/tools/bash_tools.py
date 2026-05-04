import asyncio
import datetime
import fnmatch
import locale
import os
import pathlib
import re
import shlex
import shutil
import stat as _stat
import sys

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
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    enc = locale.getpreferredencoding(False) or "utf-8"
    if proc.returncode not in ok_codes:
        err = stderr.decode(enc, errors="replace").strip()
        return {"error": err or f"exit code {proc.returncode}"}
    lines = stdout.decode(enc, errors="replace").splitlines()
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


def _human_size(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}P"


async def bash_ls(args: dict) -> dict:
    path = args.get("path", ".")
    if not path:
        path = "."
    recursive = args.get("recursive", False)
    root = pathlib.Path(path)
    if not root.exists():
        return {"error": f"no such file or directory: {path}"}
    if root.is_file():
        entries = [root]
    else:
        try:
            entries = list(root.rglob("*") if recursive else root.iterdir())
        except OSError as e:
            return {"error": str(e)}
    lines = []
    for entry in sorted(entries, key=lambda p: (p.is_file(), p.name.lower())):
        try:
            st = entry.stat()
            mode = _stat.filemode(st.st_mode)
            mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime(
                "%b %d %H:%M"
            )
            size = f"{_human_size(st.st_size):>7}"
            name = str(entry.relative_to(root)) if recursive else entry.name
            lines.append(f"{mode} {size} {mtime}  {name}")
        except OSError:
            lines.append(f"{'??????????':10} {'?':>7} {'?':12}  {entry.name}")
    return {
        "output": "\n".join(lines) if lines else "(empty)",
        "truncated": False,
    }


async def bash_cat(args: dict) -> dict:
    file = args["file"]
    max_lines = args.get("max_lines", _cat_max_lines())
    line_start = args.get("line_start")
    line_end = args.get("line_end")
    try:
        with open(file, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": str(e)}
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
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return {"error": f"invalid pattern: {e}"}

    matches: list[str] = []
    root = pathlib.Path(path)

    def search_file(fp: pathlib.Path) -> None:
        try:
            with open(fp, "r", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if rx.search(line):
                        matches.append(f"{fp}:{lineno}:{line.rstrip()}")
        except OSError:
            pass

    if root.is_file():
        search_file(root)
    elif root.is_dir():
        for entry in root.rglob("*") if recursive else root.glob("*"):
            if entry.is_file():
                search_file(entry)
    else:
        return {"error": f"no such file or directory: {path}"}

    truncated = len(matches) > max_lines
    if truncated:
        omitted = len(matches) - max_lines
        matches = matches[:max_lines]
        matches.append(f"[... {omitted} more matches omitted ...]")
    return {
        "output": "\n".join(matches) if matches else "(no matches)",
        "truncated": truncated,
    }


async def bash_find(args: dict) -> dict:
    path = args["path"]
    name_pattern = args.get("name_pattern")
    type_ = args.get("type")
    max_results = args.get("max_results", 50)
    root = pathlib.Path(path)
    if not root.exists():
        return {"error": f"no such file or directory: {path}"}
    results: list[str] = []
    for entry in root.rglob("*"):
        if type_ == "f" and not entry.is_file():
            continue
        if type_ == "d" and not entry.is_dir():
            continue
        if name_pattern and not fnmatch.fnmatch(entry.name, name_pattern):
            continue
        results.append(str(entry))
        if len(results) >= max_results:
            break
    return {
        "output": "\n".join(results) if results else "(no results)",
        "truncated": len(results) >= max_results,
    }


async def bash_head(args: dict) -> dict:
    file = args["file"]
    n = args.get("n_lines", 20)
    try:
        with open(file, "r", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= n:
                    break
                lines.append(line)
    except OSError as e:
        return {"error": str(e)}
    return {"output": "".join(lines).rstrip("\n"), "truncated": False}


async def bash_tail(args: dict) -> dict:
    file = args["file"]
    n = args.get("n_lines", 20)
    try:
        with open(file, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": str(e)}
    return {"output": "".join(lines[-n:]).rstrip("\n"), "truncated": False}


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
    if sys.platform == "win32":
        cmd = ["tasklist", "/FO", "LIST"]
    else:
        cmd = ["ps", "aux"]
    result = await _run(cmd)
    if "error" in result or not name_filter:
        return result
    lines = result["output"].splitlines()
    if sys.platform == "win32":
        matched = [ln for ln in lines if name_filter.lower() in ln.lower()]
    else:
        matched = lines[:1] + [
            ln for ln in lines[1:] if name_filter.lower() in ln.lower()
        ]
    return {"output": "\n".join(matched), "truncated": False}


async def bash_df(args: dict) -> dict:
    path = args.get("path", "/")
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        return {"error": str(e)}
    pct = 100 * usage.used / usage.total if usage.total else 0
    output = (
        f"{'Path':<20} {'Total':>10} {'Used':>10} {'Free':>10} {'Use%':>6}\n"
        f"{path:<20} {_human_size(usage.total):>10}"
        f" {_human_size(usage.used):>10}"
        f" {_human_size(usage.free):>10} {pct:>5.1f}%"
    )
    return {"output": output, "truncated": False}


async def bash_du(args: dict) -> dict:
    path = args["path"]
    max_depth = args.get("max_depth", 1)
    root = pathlib.Path(path)
    if not root.exists():
        return {"error": f"no such file or directory: {path}"}

    sizes: dict[pathlib.Path, int] = {}

    def _compute(p: pathlib.Path, depth: int) -> int:
        total = 0
        try:
            for entry in p.iterdir():
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file():
                        total += entry.stat().st_size
                    elif entry.is_dir():
                        sub = _compute(entry, depth + 1)
                        total += sub
                        if depth < max_depth:
                            sizes[entry] = sub
                except OSError:
                    pass
        except OSError:
            pass
        return total

    root_total = _compute(root, 0)
    sizes[root] = root_total

    lines = [
        f"{_human_size(sz):>8}\t{p}"
        for p, sz in sorted(sizes.items(), key=lambda x: str(x[0]))
    ]
    return {"output": "\n".join(lines), "truncated": False}


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


async def powershell_run(args: dict) -> dict:
    cmd_str = args.get("cmd", "").strip()
    if not cmd_str:
        return {"error": "cmd is required"}
    max_lines = args.get("max_lines", _run_max_lines())
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        cmd_str,
    ]
    return await _run(cmd, max_lines, ok_codes=tuple(range(256)))
