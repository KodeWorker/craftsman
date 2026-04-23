import itertools
import json
import os
import random
import shutil
import threading
import time
from enum import Enum
from pathlib import Path

import requests
from colorama import Back, Fore, Style
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import is_done
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import choice
from prompt_toolkit.styles import Style as PTStyle

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger

_AT_FILE_STYLE_CLASS = "class:at-file"  # `@` file completion style class name
_AT_FILE_STYLE = "fg:ansimagenta bold"  # `@` file completion style


class ChatCompleter(Completer):

    def __init__(
        self,
        slash_commands: list = None,
        support_formats: list = None,
        rebuild_interval_sec: int = 15,
    ):
        self.slash_commands = slash_commands or []
        self.support_formats = support_formats or []
        self._file_cache: list[str] = []
        self._cache_time: float = 0
        self._rebuild_interval_sec = rebuild_interval_sec

    def _get_files(self) -> list[str]:
        now = time.monotonic()
        if now - self._cache_time > self._rebuild_interval_sec:
            self._file_cache = [
                os.path.relpath(os.path.join(root, file))
                for root, _, files in os.walk(Path.cwd())
                for file in files
            ]
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
                    if file_path.endswith(tuple(self.support_formats)):
                        yield Completion(
                            "@" + file_path,
                            start_position=-len(word),
                            style=_AT_FILE_STYLE,
                        )
                    else:
                        yield Completion(file_path, start_position=-len(word))


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


class InputMode(Enum):
    MESSAGE = 1
    COMMAND = 2
    EXIT = 3


class Client:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.entry_point = f"http://{self.host}:{self.port}"
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.config = get_config()
        self.slash_commands = [
            cmd["name"] for cmd in self.config.get("commands", [])
        ]
        self.support_formats = self.config.get("provider", {}).get(
            "capabilities", {}
        ).get("vision", {}).get("formats", []) + self.config.get(
            "provider", {}
        ).get(
            "capabilities", {}
        ).get(
            "audio", {}
        ).get(
            "formats", []
        )
        self.rebuild_interval_sec = self.config.get("chat", {}).get(
            "rebuild_completer_interval_sec", 15
        )
        self.retry_interval_sec = self.config.get("chat", {}).get(
            "retry_interval_sec", 3
        )
        self.prompt_history_path = (
            Path(os.path.expanduser(get_config()["workspace"]["root"]))
            / "prompt_history.txt"
        )
        self.project_system_prompt = (
            Path.cwd() / ".craftsman" / "system_prompt.md"
        )
        self.root_system_prompt = (
            Path(os.path.expanduser(get_config()["workspace"]["root"]))
            / "system_prompt.md"
        )
        self.banner = "Welcome to Craftsman!"
        self.footer_pool = self.config.get("chat", {}).get("footer", [])
        self.footer = self.footer_pool[0] if self.footer_pool else ""
        self.ctx_used = 0
        self.upload_tokens = 0
        self.download_tokens = 0
        self.cost = 0.0
        self.request_session = requests.Session()

        self.input_style = PTStyle.from_dict(
            {
                "prompt": "fg:ansigreen bold",
                "at-file": _AT_FILE_STYLE,
            }
        )

    def __jwt_token(self) -> str | None:
        username = Auth.get_password("USERNAME")
        password = Auth.get_password("PASSWORD")
        if not username or not password:
            print(
                Fore.RED
                + "Username or password not set in secrets. "
                + "Proceeding without authentication token."
                + Style.RESET_ALL
            )
            self.logger.error("Username or password not set in secrets.")
            return None

        response = self.request_session.post(
            f"{self.entry_point}/users/login",
            json={"username": username, "password": password},
        )
        if response.status_code == 200:
            self.logger.info("Successfully obtained JWT token.")
            return response.json().get("token")
        else:
            print(
                Fore.RED
                + "Failed to obtain authentication token. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error("Failed to obtain JWT token.")
            return None

    # wire requests through this method to handle 401
    # and retry with JWT token if needed
    def __request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = getattr(self.request_session, method)(url, **kwargs)
        if resp.status_code == 401:
            token = self.__jwt_token()
            if not token:
                return resp
            self.request_session.headers.update(
                {"Authorization": f"Bearer {token}"}
            )
            resp = getattr(self.request_session, method)(url, **kwargs)
        return resp

    def __update_banner(
        self,
        model: str = "",
        session: str = "",
        ctx_used: int = 0,
        ctx_total: int = 0,
        upload_tokens: int = 0,
        download_tokens: int = 0,
        cost: float = 0.0,
        sandbox: bool = False,
    ):
        ctx_used_display = (
            f"{ctx_used/1000:.1f}K" if ctx_used >= 1000 else str(ctx_used)
        )
        ctx_total_display = (
            f"{ctx_total/1000:.1f}K" if ctx_total >= 1000 else str(ctx_total)
        )
        upload_tokens_display = (
            f"{upload_tokens/1000:.1f}K"
            if upload_tokens >= 1000
            else str(upload_tokens)
        )
        download_tokens_display = (
            f"{download_tokens/1000:.1f}K"
            if download_tokens >= 1000
            else str(download_tokens)
        )
        self.banner = (
            f"model: {model} | session: {session} "
            f"| ctx: {ctx_used_display}/{ctx_total_display} "
            f"| {upload_tokens_display}↑ {download_tokens_display}↓ "
            f"| (${cost:.4f}) "
            f"| sandbox: {sandbox}"
        )

    @staticmethod
    def __spin(spinner_stop, message="Thinking..."):
        for frame in itertools.cycle(
            ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        ):
            if spinner_stop.is_set():
                break
            print(
                f"\r{Style.DIM}{frame} {message} {Style.RESET_ALL}",
                end="",
                flush=True,
            )
            time.sleep(0.08)
        print("\r  \r", end="", flush=True)

    def __read_system_prompt(self):
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
                        Fore.LIGHTMAGENTA_EX
                        + f"  {cmd['name']} - {cmd['description']}"
                        + Style.RESET_ALL
                    )
            elif user_input.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                response = self.__request(
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
                response = self.__request(
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
                    print(Back.MAGENTA + Fore.WHITE + msg + Style.RESET_ALL)
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
                response = self.__request(
                    "post",
                    f"{self.entry_point}/sessions/{session_id}/compact",
                    json={
                        "summary_limit": limit,
                        "keep_turns": keep_turns,
                    },
                )
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
                    self.__update_banner(
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
            else:
                return InputMode.MESSAGE
            return InputMode.COMMAND
        return InputMode.MESSAGE

    def chat(self, session_id: str = None):
        self.logger.info(f"Connecting to server at {self.entry_point}...")

        # health check loop to wait for server to be ready
        while True:
            try:
                response = self.__request("get", f"{self.entry_point}/health")
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

        # fetch JWT token and set in header for subsequent requests
        token = self.__jwt_token()
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

        if not session_id:
            response = self.__request("post", f"{self.entry_point}/sessions/")
            session_id = response.json().get("session_id", "")
        else:
            response = self.__request(
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
            response = self.__request(
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
        completer = ChatCompleter(
            slash_commands=self.slash_commands,
            support_formats=self.support_formats,
            rebuild_interval_sec=self.rebuild_interval_sec,
        )

        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            event.current_buffer.validate_and_handle()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        while True:
            terminal_width = shutil.get_terminal_size(
                fallback=(80, 24)
            ).columns

            hint = "Enter your message (or '/help' for commands)"
            hint = f"{Style.DIM}{hint}{Style.RESET_ALL}"
            hint = ANSI(hint)

            separator = "_" * terminal_width
            print(Style.BRIGHT + Fore.CYAN + separator + Style.RESET_ALL)
            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)

            user_input = prompt(
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

            if self.footer_pool:
                self.footer = random.choice(self.footer_pool)
            mode = self.__handle_slash_command(session_id, user_input)
            if mode == InputMode.EXIT:
                break
            elif mode == InputMode.COMMAND:
                continue

            message = {"role": "user", "content": user_input}
            response = self.__request(
                "post",
                f"{self.entry_point}/sessions/{session_id}/completion",
                json={"message": message},
                stream=True,
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
                continue

            in_reasoning = False
            first_chunk = True
            printed_label = False
            spinner_stop = threading.Event()
            spinner_thread = threading.Thread(
                target=self.__spin,
                args=(spinner_stop, "Thinking..."),
                daemon=True,
            )
            spinner_thread.start()
            try:
                # process streaming response chunks
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    kind = chunk["kind"]
                    if kind == "meta":
                        if first_chunk:
                            print()
                            spinner_stop.set()
                            spinner_thread.join()
                            first_chunk = False
                        print()
                        self.__update_banner(
                            model=chunk.get("model", ""),
                            session=session_id[:8],
                            ctx_used=self.ctx_used + chunk.get("ctx_used", 0),
                            ctx_total=chunk.get("ctx_total", 0),
                            upload_tokens=self.upload_tokens
                            + chunk.get("prompt_tokens", 0),
                            download_tokens=self.download_tokens
                            + chunk.get("completion_tokens", 0),
                            cost=self.cost + chunk.get("cost", 0),
                        )
                        continue
                    text = chunk["text"]
                    if first_chunk:
                        print()
                        spinner_stop.set()
                        spinner_thread.join()
                        first_chunk = False
                    if kind == "reasoning":
                        if not in_reasoning:
                            print(
                                Style.DIM + "reasoning:\n" + Style.RESET_ALL,
                                end="",
                                flush=True,
                            )
                            in_reasoning = True
                        print(
                            Style.DIM + text + Style.RESET_ALL,
                            end="",
                            flush=True,
                        )
                    else:
                        if in_reasoning:
                            print()
                            in_reasoning = False
                        if not printed_label:
                            print(
                                Fore.MAGENTA
                                + "assistant:\n"
                                + Style.RESET_ALL,
                                end="",
                                flush=True,
                            )
                            printed_label = True
                        print(text, end="", flush=True)
            except KeyboardInterrupt:
                response.close()
                spinner_stop.set()
                print(Fore.RED + "\n[cancelled]" + Style.RESET_ALL)

            # force stop spinner in case no chunks received
            if not spinner_stop.is_set():
                spinner_stop.set()
                spinner_thread.join()

    def run(self, prompt: str):
        self.logger.info(f"Connecting to server at {self.entry_point}...")

        # health check loop to wait for server to be ready
        while True:
            try:
                response = self.__request("get", f"{self.entry_point}/health")
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

        # fetch JWT token and set in header for subsequent requests
        token = self.__jwt_token()
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

        # Create a new session for this subagent task
        response = self.__request("post", f"{self.entry_point}/sessions/")
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
            response = self.__request(
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
            target=self.__spin,
            args=(spinner_stop, "Running subagent..."),
            daemon=True,
        )
        spinner_thread.start()

        response = self.__request(
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

    def get_sessions(self, project_id: str = None, limit: int = 5) -> list:
        response = self.__request(
            "get",
            f"{self.entry_point}/sessions/",
            params={"project_id": project_id, "limit": limit},
        )
        if response.status_code == 200:
            return response.json().get("sessions", [])
        else:
            print(
                Fore.RED
                + "Error retrieving sessions. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Error retrieving sessions: "
                f"{response.status_code} - {response.text}"
            )
            return []

    def list_sessions(self, project_id: str = None, limit: int = 5) -> list:
        sessions = self.get_sessions(project_id=project_id, limit=limit)
        session_infos = []
        terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns
        for session in sessions:
            session_id = session.get("session_id", "")[:8]
            title = session.get("title", "")
            last_input = session.get("last_input", "")
            last_input_at = session.get("last_input_at", "")
            display_input = (
                last_input[: terminal_width - 3] + "..."
                if len(last_input) > terminal_width
                else last_input
            )

            session_info = (
                f"{Fore.CYAN}{session_id[:8]} | "
                f"{title} | {last_input_at}{Style.RESET_ALL}\n"
                f"{display_input}"
            )
            session_infos.append(session_info)
        return session_infos

    def find_session_id(self, session: str) -> str:
        response = self.__request(
            "get",
            f"{self.entry_point}/sessions/resolve",
            params={"session": session},
        )
        if response.status_code == 200:
            session_id = response.json().get("session_id", None)
            if not session_id:
                print(
                    Fore.RED
                    + f"Session '{session}' not found."
                    + Style.RESET_ALL
                )
                self.logger.error(f"Session '{session}' not found.")
                return None
            return session_id
        else:
            print(
                Fore.RED
                + f"Error retrieving session ID for '{session}'. "
                + "Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Error retrieving session ID: "
                f"{response.status_code} - {response.text}"
            )
            return None

    def delete_session(self, session: str = None):
        if not session:
            print(
                Fore.RED
                + "No session ID or prefix or title provided."
                + Style.RESET_ALL
            )
            self.logger.error("No session ID or prefix or title provided.")
            return

        session_id = self.find_session_id(session)
        if not session_id:
            print(
                Fore.RED + f"Session '{session}' not found." + Style.RESET_ALL
            )
            self.logger.error(f"Session '{session}' not found.")
            return

        response = self.__request(
            "delete",
            f"{self.entry_point}/sessions/{session_id}",
        )
        if response.status_code == 200:
            status = response.json().get("status", "")
            self.logger.info(status)
        else:
            print(
                Fore.RED
                + f"Error deleting session '{session}'. Please check logs."
                + Style.RESET_ALL
            )
            self.logger.error(
                "Error deleting session: "
                f"{response.status_code} - {response.text}"
            )

    def pick_session(self, project_id: str = None, limit: int = 5) -> str:
        sessions = self.get_sessions(project_id=project_id, limit=limit)
        if not sessions:
            self.logger.info(
                "No existing sessions found. Starting a new session."
            )
            return None

        options = [
            (
                session["session_id"],
                f"{session['session_id'][:8]} | {session['title']} | "
                f"{session['last_input_at']} - {session['last_input']}",
            )
            for session in sessions
        ]
        result = choice(
            message="Please choose a session:",
            options=options,
            default=None,
        )
        return result
