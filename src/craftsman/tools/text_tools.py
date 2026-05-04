import os
import re
import shutil

from craftsman.configure import get_config


def _read_max_lines() -> int:
    return (
        get_config()
        .get("tools", {})
        .get("text", {})
        .get("read", {})
        .get("max_lines", 200)
    )


def _search_context_lines() -> int:
    return (
        get_config()
        .get("tools", {})
        .get("text", {})
        .get("search", {})
        .get("context_lines", 2)
    )


async def text_read(args: dict) -> dict:
    file = args["file"]
    line_start = args.get("line_start", 1)
    line_end = args.get("line_end")
    max_lines = args.get("max_lines", _read_max_lines())
    with open(file, "r", errors="replace") as f:
        all_lines = f.readlines()
    total = len(all_lines)
    start_idx = max(0, (line_start or 1) - 1)
    end_idx = line_end if line_end is not None else total
    selected = all_lines[start_idx:end_idx]
    total_selected = len(selected)
    truncated = total_selected > max_lines
    omitted = 0
    if truncated:
        omitted = total_selected - max_lines
        selected = selected[-max_lines:]
        first_n = end_idx - max_lines + 1  # 1-based line number of first shown
    else:
        first_n = start_idx + 1
    lines_out = [
        {"n": first_n + i, "text": l.rstrip("\n")}
        for i, l in enumerate(selected)
    ]
    return {
        "lines": lines_out,
        "total_lines": total,
        "truncated": truncated,
        **({"omitted": omitted} if truncated else {}),
    }


async def text_search(args: dict) -> dict:
    file = args["file"]
    pattern = args["pattern"]
    context_lines = args.get("context_lines", _search_context_lines())
    with open(file, "r", errors="replace") as f:
        lines = f.readlines()
    matches = []
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            ctx = [
                {"n": j + 1, "text": lines[j].rstrip("\n"), "match": j == i}
                for j in range(start, end)
            ]
            matches.append({"line": i + 1, "context": ctx})
    return {"matches": matches, "total_matches": len(matches)}


def _craftsman_path(file: str, suffix: str) -> str:
    cwd = os.getcwd()
    abs_file = os.path.abspath(file)
    try:
        rel = os.path.relpath(abs_file, cwd)
    except ValueError:
        rel = abs_file.lstrip(os.sep)
    path = os.path.join(cwd, ".craftsman", rel + suffix)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _write_tmp(file: str, content: str) -> str:
    tmp = _craftsman_path(file, ".tmp")
    with open(tmp, "w") as f:
        f.write(content)
    return tmp


def _write_tmp_lines(file: str, lines: list[str]) -> str:
    tmp = _craftsman_path(file, ".tmp")
    with open(tmp, "w") as f:
        f.writelines(lines)
    return tmp


def commit_tmp(file: str, tmp: str) -> str | None:
    parent = os.path.dirname(os.path.abspath(file))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.exists(file):
        bak = _craftsman_path(file, ".bak")
        shutil.copy2(file, bak)
    else:
        bak = None
    os.replace(tmp, file)
    return bak


def discard_tmp(tmp: str) -> None:
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass


async def text_replace(args: dict) -> dict:
    file = args["file"]
    old = args["old_string"]
    new = args["new_string"]
    with open(file, "r", errors="replace") as f:
        content = f.read()

    # Exact match
    count = content.count(old)
    if count > 1:
        return {"error": f"String found {count} times — must be unique"}
    if count == 1:
        tmp = _write_tmp(file, content.replace(old, new, 1))
        return {"status": "pending", "tmp": tmp, "file": file}

    # Fallback: line-by-line match ignoring trailing whitespace
    file_lines = content.splitlines(keepends=True)
    old_lines = [ln.rstrip() for ln in old.splitlines()]
    n = len(old_lines)
    if n == 0:
        return {"error": f"String not found in {file}"}

    found = -1
    for i in range(len(file_lines) - n + 1):
        chunk = [file_lines[i + j].rstrip() for j in range(n)]
        if chunk == old_lines:
            if found != -1:
                return {
                    "error": "String found multiple times — must be unique"
                }
            found = i

    if found == -1:
        return {"error": f"String not found in {file}"}

    prefix = "".join(file_lines[:found])
    suffix = "".join(file_lines[found + n :])
    insertion = new if new.endswith("\n") or not suffix else new + "\n"
    tmp = _write_tmp(file, prefix + insertion + suffix)
    return {"status": "pending", "tmp": tmp, "file": file}


async def text_insert(args: dict) -> dict:
    file = args["file"]
    line_num = args["line_num"]
    new_lines = args["lines"]
    to_insert = [ln if ln.endswith("\n") else ln + "\n" for ln in new_lines]
    if not os.path.exists(file):
        if line_num != 1:
            return {
                "error": (
                    f"{file} does not exist; use line_num=1 to create it"
                )
            }
        tmp = _write_tmp_lines(file, to_insert)
    else:
        with open(file, "r", errors="replace") as f:
            lines = f.readlines()
        if line_num < 1 or line_num > len(lines) + 1:
            return {
                "error": (
                    f"line_num={line_num} out of range"
                    f" for file with {len(lines)} lines"
                )
            }
        lines[line_num - 1 : line_num - 1] = to_insert
        tmp = _write_tmp_lines(file, lines)
    return {
        "status": "pending",
        "tmp": tmp,
        "file": file,
        "lines_inserted": len(new_lines),
    }


async def text_delete(args: dict) -> dict:
    file = args["file"]
    line_start = args["line_start"]
    line_end = args["line_end"]
    with open(file, "r", errors="replace") as f:
        lines = f.readlines()
    if line_start < 1 or line_end > len(lines) or line_start > line_end:
        return {
            "error": (
                f"Invalid range {line_start}-{line_end}"
                f" for file with {len(lines)} lines"
            )
        }
    new_lines = lines[: line_start - 1] + lines[line_end:]
    tmp = _write_tmp_lines(file, new_lines)
    return {
        "status": "pending",
        "tmp": tmp,
        "file": file,
        "lines_deleted": line_end - line_start + 1,
    }
