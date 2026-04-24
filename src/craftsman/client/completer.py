import fnmatch
import os
import time
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.lexers import Lexer

from craftsman.client.base import _AT_FILE_STYLE, _AT_FILE_STYLE_CLASS


class ChatCompleter(Completer):

    def __init__(
        self,
        slash_commands: list = None,
        rebuild_interval_sec: int = 15,
        ignores: list = None,
    ):
        self.slash_commands = slash_commands or []
        self._file_cache: list[str] = []
        self._cache_time: float = 0
        self._rebuild_interval_sec = rebuild_interval_sec
        ignores = ignores or []
        # patterns ending with "/" are dir filters; strip trailing "/"
        self._dir_ignores = [p.rstrip("/") for p in ignores if p.endswith("/")]
        self._file_ignores = [p for p in ignores if not p.endswith("/")]

    def _get_files(self) -> list[str]:
        now = time.monotonic()
        if now - self._cache_time > self._rebuild_interval_sec:
            result = []
            for root, dirs, files in os.walk(Path.cwd()):
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(
                        fnmatch.fnmatch(d, pat) for pat in self._dir_ignores
                    )
                ]
                result.extend(
                    os.path.relpath(os.path.join(root, f))
                    for f in files
                    if not any(
                        fnmatch.fnmatch(f, pat) for pat in self._file_ignores
                    )
                )
            self._file_cache = result
            self._cache_time = now
        return self._file_cache

    def get_completions(self, document, complete_event):
        full_text = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)
        # slash command completion — only at start of input
        if full_text.lstrip() == full_text and full_text.startswith("/"):
            for cmd in self.slash_commands:
                if cmd.startswith(full_text.lower()):
                    yield Completion(cmd, start_position=-len(full_text))

        # project file completion — triggered by "@" prefix
        if word.startswith("@"):
            file_prefix = word[1:]
            for file_path in self._get_files():
                if file_path.startswith(file_prefix):
                    yield Completion(
                        "@" + file_path,
                        start_position=-len(word),
                        style=_AT_FILE_STYLE,
                    )


class AtFileLexer(Lexer):

    def lex_document(self, document):
        def get_line(lineno):
            line = document.lines[lineno]
            tokens = []
            i = 0
            while i < len(line):
                if line[i] == "@":
                    j = i + 1
                    while j < len(line) and not line[j].isspace():
                        j += 1
                    tokens.append((_AT_FILE_STYLE_CLASS, line[i:j]))
                    i = j
                else:
                    j = i + 1
                    while j < len(line) and line[j] != "@":
                        j += 1
                    tokens.append(("", line[i:j]))
                    i = j
            return tokens

        return get_line
