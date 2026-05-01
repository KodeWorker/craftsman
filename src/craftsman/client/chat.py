import asyncio
import difflib
import json
import os
import re
import shutil
import threading
import time
from enum import Enum
from pathlib import Path

import requests
from colorama import Back, Fore, Style
from prompt_toolkit import PromptSession
from prompt_toolkit.document import Document
from prompt_toolkit.filters import is_done
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PTStyle

from craftsman.auth import Auth
from craftsman.client.artifacts import ArtifactsClient
from craftsman.client.base import _AT_FILE_STYLE
from craftsman.client.completer import AtFileLexer, ChatCompleter
from craftsman.client.sessions import SessionsClient
from craftsman.tools.constants import REMOTE_TOOLS
from craftsman.tools.executor import _LOCAL_DISPATCH
from craftsman.tools.text_tools import commit_tmp, discard_tmp

_PENDING_TOOLS = {"text:replace", "text:insert", "text:delete"}


class InputMode(Enum):
    MESSAGE = 1
    COMMAND = 2
    EXIT = 3


class Client(SessionsClient, ArtifactsClient):

    def __init__(self, host: str, port: int):
        super().__init__(host, port)

        self.slash_commands = [
            cmd["name"] for cmd in self.config.get("commands", [])
        ]
        self.rebuild_interval_sec = self.config.get("chat", {}).get(
            "rebuild_completer_interval_sec", 15
        )
        self.retry_interval_sec = self.config.get("chat", {}).get(
            "retry_interval_sec", 3
        )
        self.prompt_history_path = (
            Path(os.path.expanduser(self.config["workspace"]["root"]))
            / "prompt_history.txt"
        )
        self.project_system_prompt = (
            Path.cwd() / ".craftsman" / "system_prompt.md"
        )
        self.root_system_prompt = (
            Path(os.path.expanduser(self.config["workspace"]["root"]))
            / "system_prompt.md"
        )

        self.ctx_used = 0
        self.upload_tokens = 0
        self.download_tokens = 0
        self.cost = 0.0
        self.input_style = PTStyle.from_dict(
            {
                "prompt": "fg:ansigreen bold",
                "at-file": _AT_FILE_STYLE,
            }
        )

    def __read_system_prompt(self) -> str:
        if self.project_system_prompt.exists():
            with open(self.project_system_prompt, "r") as f:
                return f.read().strip()
        elif self.root_system_prompt.exists():
            with open(self.root_system_prompt, "r") as f:
                return f.read().strip()
        return ""

    def __handle_slash_command(
        self,
        session_id: str,
        user_input: str,
    ) -> InputMode:
        if (
            user_input.lower().startswith("/")
            and user_input.lower() in self.slash_commands
        ):
            print(Fore.LIGHTMAGENTA_EX + user_input + Style.RESET_ALL)
            if user_input.lower() == "/exit":
                self.logger.info("Exiting client.")
                return InputMode.EXIT
            elif user_input.lower() == "/help":
                for cmd in self.config.get("commands", []):
                    print(
                        Fore.CYAN
                        + f"  {cmd['name']} - {cmd['description']}"
                        + Style.RESET_ALL
                    )
            elif user_input.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                response = self._request(
                    "post",
                    f"{self.entry_point}/sessions/{session_id}/clear",
                )
                if response.status_code == 200:
                    self.logger.info("Session cleared.")
                else:
                    print(
                        Fore.RED
                        + "Error clearing session. Please check logs."
                        + Style.RESET_ALL
                    )
                    self.logger.error(
                        "Error clearing session: "
                        f"{response.status_code} - {response.text}"
                    )
            elif user_input.lower() == "/system":
                response = self._request(
                    "get",
                    f"{self.entry_point}/sessions/{session_id}/system",
                )
                if response.status_code == 200:
                    system_prompt = response.json().get("system_prompt", None)
                    print(
                        Fore.LIGHTMAGENTA_EX
                        + "System prompt:"
                        + Style.RESET_ALL
                    )
                    msg = (
                        system_prompt
                        if system_prompt
                        else "(No system prompt set.)"
                    )
                    print(Fore.CYAN + msg + Style.RESET_ALL)
                else:
                    print(
                        Fore.RED
                        + "Error retrieving system prompt. Please check logs."
                        + Style.RESET_ALL
                    )
                    self.logger.error(
                        "Error retrieving system prompt: "
                        f"{response.status_code} - {response.text}"
                    )
            elif user_input.lower() == "/compact":
                limit, keep_turns = next(
                    (
                        (cmd.get("limit", 1000), cmd.get("keep_turns", 5))
                        for cmd in self.config.get("commands", [])
                        if cmd["name"] == "/compact"
                    ),
                    (1000, 5),
                )
                spinner_stop, spinner_thread = self._start_spinner(
                    "Compacting..."
                )
                response = self._request(
                    "post",
                    f"{self.entry_point}/sessions/{session_id}/compact",
                    json={
                        "summary_limit": limit,
                        "keep_turns": keep_turns,
                    },
                )
                spinner_stop.set()
                spinner_thread.join()
                print()
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "")
                    print(Fore.LIGHTMAGENTA_EX + status + Style.RESET_ALL)
                    self.logger.info(status)
                    self.ctx_used = data.get("meta", {}).get("ctx_used", 0)
                    self.upload_tokens += data.get("meta", {}).get(
                        "prompt_tokens", 0
                    )
                    self.download_tokens += data.get("meta", {}).get(
                        "completion_tokens", 0
                    )
                    self.cost += data.get("meta", {}).get("cost", 0.0)
                    self._update_banner(
                        session=session_id[:8],
                        ctx_used=self.ctx_used,
                        upload_tokens=self.upload_tokens,
                        download_tokens=self.download_tokens,
                        cost=self.cost,
                    )
                else:
                    print(
                        Fore.RED
                        + "Error compacting session. Please check logs."
                        + Style.RESET_ALL
                    )
                    self.logger.error(
                        "Error compacting session: "
                        f"{response.status_code} - {response.text}"
                    )
            elif user_input.lower() == "/artifacts":
                response = self._request(
                    "get",
                    f"{self.entry_point}/artifacts/",
                    params={"session_id": session_id},
                )
                if response.status_code == 200:
                    artifacts = response.json().get("artifacts", [])
                    if not artifacts:
                        print(
                            Fore.YELLOW
                            + "No artifacts uploaded in this session."
                            + Style.RESET_ALL
                        )
                        return InputMode.COMMAND
                    print(
                        Fore.LIGHTMAGENTA_EX
                        + "Artifacts uploaded in this session:"
                        + Style.RESET_ALL
                    )
                    for artifact in artifacts:
                        artifact_id = artifact.get("id", "")[:8]
                        filename = artifact.get("filename", "")
                        mime_type = artifact.get("mime_type", "")
                        size_bytes = artifact.get("size_bytes", 0)
                        created_at = artifact.get("created_at", "")
                        print(
                            f"{Fore.CYAN}{artifact_id} | {filename} | "
                            f"{mime_type} | {size_bytes} bytes | "
                            f"{created_at}{Style.RESET_ALL}"
                        )
                else:
                    print(
                        Fore.RED
                        + "Error retrieving artifacts. Please check logs."
                        + Style.RESET_ALL
                    )
                    self.logger.error(
                        "Error retrieving artifacts: "
                        f"{response.status_code} - {response.text}"
                    )
            else:
                return InputMode.MESSAGE
            return InputMode.COMMAND
        return InputMode.MESSAGE

    def _initalize_connection(self) -> bool:
        # health check loop to wait for server to be ready
        while True:
            try:
                response = self._request("get", f"{self.entry_point}/health")
                if response.status_code == 200:
                    self.logger.info("Successfully connected to the server.")
                    break
            except requests.exceptions.ConnectionError:
                print(
                    Fore.YELLOW + "Server not ready yet..." + Style.RESET_ALL
                )
                self.logger.warning(
                    f"Connection failed. "
                    f"Retrying in {self.retry_interval_sec} seconds..."
                )
                time.sleep(self.retry_interval_sec)

        # reset provider state on the server
        response = self._request(
            "post",
            f"{self.entry_point}/reset",
            json={
                "api_base": self.config.get("provider", {}).get(
                    "api_base", None
                ),
                "api_key": Auth.get_password("LLM_API_KEY"),
            },
        )
        if response.status_code == 200:
            self.logger.info("Provider state reset successfully.")
            return True
        else:
            print(
                Fore.RED
                + "Failed to reset provider state. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Failed to reset provider state: "
                f"{response.status_code} - {response.text}"
            )
            return False

    def _start_spinner(self, message: str = "Thinking..."):
        stop = threading.Event()
        thread = threading.Thread(
            target=self._spin, args=(stop, message), daemon=True
        )
        thread.start()
        return stop, thread

    def _call_tool(self, name: str, args: dict, session_id: str) -> dict:
        if name in _LOCAL_DISPATCH:
            try:
                return asyncio.run(_LOCAL_DISPATCH[name](args))
            except Exception as e:
                return {"error": str(e)}
        if name in REMOTE_TOOLS:
            try:
                resp = self._request(
                    "post",
                    f"{self.entry_point}/tools/invoke",
                    json={
                        "name": name,
                        "args": args,
                        "session_id": session_id,
                    },
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"error": str(e)}
        return {"error": f"Unknown tool: {name}"}

    def _confirm_audited(self, name: str, args: dict) -> tuple[bool, str]:
        args_str = json.dumps(args)
        print(Fore.YELLOW + f"[audited] {name} {args_str}" + Style.RESET_ALL)
        try:
            answer = input(
                "[y] run / [n] skip (add reason after 'n'): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return False, "cancelled"
        if answer.lower() == "y":
            return True, ""
        parts = answer.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else "user rejected"
        return False, reason

    def _confirm_pending(self, tool_name: str, result: dict) -> dict:
        file_path = result.get("file", "unknown")
        tmp = result.get("tmp", "")
        try:
            if os.path.exists(file_path):
                with open(file_path, errors="replace") as f:
                    orig = f.readlines()
            else:
                orig = []
            with open(tmp, errors="replace") as f:
                new = f.readlines()
            diff = list(
                difflib.unified_diff(
                    orig, new, fromfile=file_path, tofile=file_path
                )
            )
        except Exception:
            diff = []
        if diff:
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            width = len(str(max(len(orig), len(new), 1)))
            old_n = new_n = 0
            for raw in diff:
                ln = raw.rstrip("\n")
                pad = " " * width
                if ln.startswith("---") or ln.startswith("+++"):
                    print(
                        Style.BRIGHT
                        + f"{pad} {ln}".ljust(cols)
                        + Style.RESET_ALL
                    )
                elif ln.startswith("@@"):
                    m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
                    if m:
                        old_n = int(m.group(1)) - 1
                        new_n = int(m.group(2)) - 1
                    print(
                        Fore.CYAN + f"{pad} {ln}".ljust(cols) + Style.RESET_ALL
                    )
                elif ln.startswith("-"):
                    old_n += 1
                    num = str(old_n).rjust(width)
                    body = f" {ln}".ljust(cols - width)
                    print(
                        Back.LIGHTRED_EX
                        + Fore.BLACK
                        + num
                        + Style.RESET_ALL
                        + Back.RED
                        + body
                        + Style.RESET_ALL
                    )
                elif ln.startswith("+"):
                    new_n += 1
                    num = str(new_n).rjust(width)
                    body = f" {ln}".ljust(cols - width)
                    print(
                        Back.LIGHTGREEN_EX
                        + Fore.BLACK
                        + num
                        + Style.RESET_ALL
                        + Back.GREEN
                        + body
                        + Style.RESET_ALL
                    )
                else:
                    old_n += 1
                    new_n += 1
                    num = str(new_n).rjust(width)
                    body = f" {ln}".ljust(cols - width)
                    print(Style.DIM + num + Style.RESET_ALL + body)
        print(
            Fore.YELLOW
            + f"[pending] {tool_name} → {file_path}"
            + Style.RESET_ALL
        )
        try:
            answer = input(
                "[y] approve / [n] reject (add reason after 'n'): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            discard_tmp(tmp)
            return {"status": "rejected", "reason": "cancelled"}
        if answer.lower() == "y":
            try:
                bak = commit_tmp(file_path, tmp)
                return {
                    "status": "committed",
                    "file": file_path,
                    "backup": bak,
                }
            except Exception as e:
                return {"error": str(e)}
        parts = answer.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        discard_tmp(tmp)
        return {"status": "rejected", "reason": reason or "user rejected"}

    def _do_stream(
        self,
        response,
        session_id: str,
        spinner_stop: threading.Event,
        spinner_thread: threading.Thread,
    ) -> tuple:
        tool_calls: list[dict] = []
        meta: dict = {}
        first_chunk = True
        in_reasoning = False
        printed_label = False

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                kind = chunk.get("kind")

                if first_chunk:
                    print()
                    spinner_stop.set()
                    if spinner_thread.is_alive():
                        spinner_thread.join()
                    first_chunk = False

                if kind == "meta":
                    meta = chunk
                    print()
                    self._update_banner(
                        model=chunk.get("model", ""),
                        session=session_id[:8],
                        ctx_used=self.ctx_used + chunk.get("ctx_used", 0),
                        ctx_total=chunk.get("ctx_total", 0),
                        upload_tokens=self.upload_tokens
                        + chunk.get("prompt_tokens", 0),
                        download_tokens=self.download_tokens
                        + chunk.get("completion_tokens", 0),
                        cost=self.cost + chunk.get("cost", 0.0),
                    )
                elif kind == "tool_call":
                    args_str = json.dumps(chunk.get("args", {}))
                    print(
                        Style.DIM
                        + f"[tool] {chunk['name']} {args_str}"
                        + Style.RESET_ALL
                    )
                    tool_calls.append(chunk)
                elif kind == "reasoning":
                    if not in_reasoning:
                        print(
                            Style.DIM + "reasoning:\n" + Style.RESET_ALL,
                            end="",
                            flush=True,
                        )
                        in_reasoning = True
                    print(
                        Style.DIM + chunk["text"] + Style.RESET_ALL,
                        end="",
                        flush=True,
                    )
                elif kind == "content":
                    if in_reasoning:
                        print()
                        in_reasoning = False
                    if not printed_label:
                        print(
                            Fore.MAGENTA + "assistant:\n" + Style.RESET_ALL,
                            end="",
                            flush=True,
                        )
                        printed_label = True
                    print(chunk["text"], end="", flush=True)
                elif kind == "error":
                    print(
                        Fore.RED
                        + chunk.get("text", "Unknown error")
                        + Style.RESET_ALL
                    )
        except KeyboardInterrupt:
            response.close()
            spinner_stop.set()
            print(Fore.RED + "\n[cancelled]" + Style.RESET_ALL)
            return None, meta

        if not spinner_stop.is_set():
            spinner_stop.set()
            if spinner_thread.is_alive():
                spinner_thread.join()

        return tool_calls, meta

    def _agentic_loop(self, session_id: str, message: dict) -> None:
        tools = self.config.get("chat", {}).get("tools", ["all"])
        max_loops = self.config.get("chat", {}).get("max_tool_loops", 10)

        spinner_stop, spinner_thread = self._start_spinner("Thinking...")
        response = self._request(
            "post",
            f"{self.entry_point}/sessions/{session_id}/completion",
            json={"message": message, "tools": tools},
            stream=True,
        )
        if response.status_code != 200:
            spinner_stop.set()
            spinner_thread.join()
            print(
                Fore.RED
                + "Error from server. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                f"Error from server: {response.status_code} - {response.text}"
            )
            return

        # pass 0 = initial completion; passes 1..max_loops = tool rounds
        for tool_round in range(max_loops + 1):
            tool_calls, meta = self._do_stream(
                response, session_id, spinner_stop, spinner_thread
            )
            if tool_calls is None:
                return

            self.ctx_used += meta.get("ctx_used", 0)
            self.upload_tokens += meta.get("prompt_tokens", 0)
            self.download_tokens += meta.get("completion_tokens", 0)
            self.cost += meta.get("cost", 0.0)

            if not tool_calls:
                return

            if tool_round >= max_loops:
                print(
                    Fore.YELLOW
                    + f"[max tool loops ({max_loops}) reached]"
                    + Style.RESET_ALL
                )
                return

            tool_results = []
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args", {})
                audited = tc.get("audited", False)

                if audited and name not in _PENDING_TOOLS:
                    approved, reason = self._confirm_audited(name, args)
                    if not approved:
                        result: dict = {
                            "status": "rejected",
                            "reason": reason,
                        }
                        tool_results.append(
                            {
                                "tool_call_id": tc["id"],
                                "tool_name": name,
                                "result": result,
                            }
                        )
                        continue

                print(Style.DIM + f"  → executing {name}" + Style.RESET_ALL)
                result = self._call_tool(name, args, session_id)
                if result.get("status") == "pending":
                    result = self._confirm_pending(name, result)
                if result.get("error"):
                    print(
                        Fore.RED
                        + f"  ← error: {result['error']}"
                        + Style.RESET_ALL
                    )
                else:
                    status_str = (
                        result.get("status") or json.dumps(result)[:80]
                    )
                    print(Fore.YELLOW + f"  ← {status_str}" + Style.RESET_ALL)
                tool_results.append(
                    {
                        "tool_call_id": tc["id"],
                        "tool_name": name,
                        "result": result,
                    }
                )

            spinner_stop, spinner_thread = self._start_spinner("Thinking...")
            response = self._request(
                "post",
                f"{self.entry_point}/sessions/{session_id}/tool_result",
                json={"tool_results": tool_results, "tools": tools},
                stream=True,
            )
            if response.status_code != 200:
                spinner_stop.set()
                spinner_thread.join()
                print(
                    Fore.RED
                    + "Error from server. Please check logs."
                    + Style.RESET_ALL
                )
                self.logger.error(
                    f"Error from tool_result: "
                    f"{response.status_code} - {response.text}"
                )
                return

    def _start_dispatcher(self, token: str) -> None:
        import threading

        from craftsman.tools.scheduler import JobDispatcher

        dispatcher = JobDispatcher(self.entry_point, token)

        def _run():
            asyncio.run(dispatcher.run_loop())

        threading.Thread(target=_run, daemon=True).start()
        self.logger.info("Job dispatcher started.")

    def chat(self, session_id: str = None):
        self.logger.info(f"Connecting to server at {self.entry_point}...")

        if not self._initalize_connection():
            return

        # fetch JWT token and set in header for subsequent requests
        token = self._jwt_token()
        if token:
            self.logger.info("Setting JWT token for authentication.")
            self.request_session.headers.update(
                {"Authorization": f"Bearer {token}"}
            )
        else:
            print(
                Fore.RED
                + "Failed to obtain authentication token. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error("Failed to obtain authentication token.")
            return

        self._seed_tools()
        self._start_dispatcher(token)

        if not session_id:
            response = self._request("post", f"{self.entry_point}/sessions/")
            session_id = response.json().get("session_id", "")
        else:
            response = self._request(
                "post",
                f"{self.entry_point}/sessions/{session_id}/resume",
            )
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "")
                messages = data.get("messages", [])
                meta = data.get("meta", {})
                self.logger.info(f"{status}")
                self.ctx_used = meta.get("ctx_used", 0)
                self.upload_tokens = meta.get("upload_tokens", 0)
                self.download_tokens = meta.get("download_tokens", 0)
                self.cost = meta.get("cost", 0.0)
                # display user and assistant messages in the session history
                for message in messages:
                    if message["role"] == "user":
                        print(Fore.GREEN + "user:" + Style.RESET_ALL)
                        print(message["content"])
                    elif message["role"] == "assistant":
                        print(Fore.MAGENTA + "assistant:" + Style.RESET_ALL)
                        print(message["content"])
            else:
                print(
                    Fore.RED
                    + "Failed to resume session. Please check logs."
                    + Style.RESET_ALL
                )
                self.logger.error(
                    "Error resuming session: "
                    f"{response.status_code} - {response.text}"
                )
                return

        # set system prompt if exists
        system_prompt = self.__read_system_prompt()
        if system_prompt:
            response = self._request(
                "put",
                f"{self.entry_point}/sessions/{session_id}/system",
                json={"system_prompt": system_prompt},
            )
            if response.status_code == 200:
                self.logger.info("System prompt set successfully.")
            else:
                print(
                    Fore.RED
                    + "Error setting system prompt. Please check logs."
                    + Style.RESET_ALL
                )
                self.logger.error(
                    "Error setting system prompt: "
                    f"{response.status_code} - {response.text}"
                )

        history = FileHistory(str(self.prompt_history_path))
        if (
            self.config.get("chat", {})
            .get("completer", {})
            .get("enabled", False)
        ):
            completer = ChatCompleter(
                slash_commands=self.slash_commands,
                support_formats=self.support_image_formats
                + self.support_audio_formats,
                rebuild_interval_sec=self.rebuild_interval_sec,
                ignores=self.completer_ignores,
            )
        else:
            completer = None

        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            event.current_buffer.validate_and_handle()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        hint = ANSI(
            f"{Style.DIM}Enter your message (or '/help' for commands)"
            f"{Style.RESET_ALL}"
        )
        prompt_session = PromptSession(
            message=[("class:prompt", "user: ")],
            placeholder=hint,
            multiline=True,
            history=history,
            completer=completer,
            lexer=AtFileLexer(),
            style=self.input_style,
            key_bindings=kb,
            show_frame=~is_done,
            bottom_toolbar=self.footer,
        )

        _dd_active = False
        _dd_prev_before = [""]  # text-before-cursor from the last event

        def _drag_drop_handler(buf):
            nonlocal _dd_active
            if _dd_active:
                return
            doc = buf.document
            current_before = doc.text_before_cursor
            prev_before = _dd_prev_before[0]
            _dd_prev_before[0] = current_before
            # compute what was just inserted at the cursor position
            if not current_before.startswith(prev_before):
                return  # deletion or cursor-only move — skip
            inserted = current_before[len(prev_before) :]
            stripped = inserted.strip().strip("'")
            # require at least 2 chars to avoid false-positive on typing "/"
            if len(stripped) <= 1:
                return
            # Linux/Mac path (e.g. /path/to/file or ~/file)
            if stripped.startswith(("/", "~/")):
                raw = stripped
            # Windows path with drive letter (e.g. C:\path\to\file)
            elif (
                len(stripped) > 2
                and stripped[1] == ":"
                and stripped[2] in ("\\", "/")
            ):
                raw = stripped
            else:
                return
            if not raw:
                return
            _dd_active = True
            try:
                replacement = f"@{raw}"
                new_text = prev_before + replacement + doc.text_after_cursor
                cursor_pos = len(prev_before) + len(replacement)
                buf.set_document(Document(new_text, cursor_pos))
                _dd_prev_before[0] = prev_before + replacement
            finally:
                _dd_active = False

        prompt_session.default_buffer.on_text_changed += _drag_drop_handler

        while True:

            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)

            user_input = prompt_session.prompt()

            self._update_footer()

            mode = self.__handle_slash_command(session_id, user_input)
            if mode == InputMode.EXIT:
                break
            elif mode == InputMode.COMMAND:
                continue

            user_input = self.upload_artifacts(user_input, session_id)
            if user_input is None:
                continue

            message = {"role": "user", "content": user_input}
            self._agentic_loop(session_id, message)

    def run(self, prompt: str):
        self.logger.info(f"Connecting to server at {self.entry_point}...")

        if not self._initalize_connection():
            return

        # fetch JWT token and set in header for subsequent requests
        token = self._jwt_token()
        if token:
            self.logger.info("Setting JWT token for authentication.")
            self.request_session.headers.update(
                {"Authorization": f"Bearer {token}"}
            )
        else:
            print(
                Fore.RED
                + "Failed to obtain authentication token. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error("Failed to obtain authentication token.")
            return

        self._seed_tools()

        # Create a new session for this subagent task
        response = self._request("post", f"{self.entry_point}/sessions/")
        if response.status_code == 200:
            session_id = response.json().get("session_id", "")
            self.logger.info(f"Created new session with ID: {session_id}")
        else:
            print(
                Fore.RED
                + "Failed to create session. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Failed to create session: "
                f"{response.status_code} - {response.text}"
            )
            return

        system_prompt = self.__read_system_prompt()
        if system_prompt:
            response = self._request(
                "put",
                f"{self.entry_point}/sessions/{session_id}/system",
                json={"system_prompt": system_prompt},
            )
            if response.status_code == 200:
                self.logger.info("System prompt set successfully.")
            else:
                print(
                    Fore.RED
                    + "Failed to set system prompt. Please check logs."
                    + Style.RESET_ALL
                )
                self.logger.error(
                    "Error setting system prompt: "
                    f"{response.status_code} - {response.text}"
                )

        message = {"role": "user", "content": prompt}

        spinner_stop = threading.Event()
        spinner_thread = threading.Thread(
            target=self._spin,
            args=(spinner_stop, "Running subagent..."),
            daemon=True,
        )
        spinner_thread.start()

        response = self._request(
            "post",
            f"{self.entry_point}/subagent/run",
            json={"message": message, "session_id": session_id},
        )
        if response.status_code != 200:
            print(
                Fore.RED
                + "Error from server. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Error from server: "
                f"{response.status_code} - {response.text}"
            )
            spinner_stop.set()
            spinner_thread.join()
            return

        data = response.json()
        content = data.get("content", "")
        up_tokens = data.get("meta", {}).get("prompt_tokens", 0)
        down_tokens = data.get("meta", {}).get("completion_tokens", 0)
        cost = data.get("meta", {}).get("cost", 0.0)
        spinner_stop.set()
        spinner_thread.join()
        print()

        print(Fore.GREEN + "assistant:" + Style.RESET_ALL)
        print(content)
        print(
            Fore.CYAN
            + f"Tokens used - Prompt: {up_tokens},"
            + f" Completion: {down_tokens}, Cost: ${cost:.4f}"
            + Style.RESET_ALL
        )
