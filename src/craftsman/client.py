import itertools
import json
import os
import shutil
import threading
import time
from enum import Enum
from pathlib import Path

import requests
from colorama import Back, Fore, Style
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import choice

from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger


class ChatCompleter(Completer):

    def __init__(self, slash_commands: list = None):
        self.slash_commands = slash_commands or []

    def get_completions(self, document, complete_event):
        full_text = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)
        # slash command completion — only at start of input
        if full_text.lstrip() == full_text and full_text.startswith("/"):
            for cmd in self.slash_commands:
                if cmd.startswith(full_text.lower()):
                    yield Completion(cmd, start_position=-len(full_text))
        # project file completion — match current word anywhere in input
        if word:
            for root, dirs, files in os.walk(Path.cwd()):
                for file in files:
                    file_path = os.path.relpath(os.path.join(root, file))
                    if file_path.startswith(word):
                        yield Completion(file_path, start_position=-len(word))


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
        self.ctx_used = 0
        self.upload_tokens = 0
        self.download_tokens = 0
        self.cost = 0.0

    def update_banner(
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
    def _spin(spinner_stop, message="Thinking..."):
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

    def read_system_prompt(self):
        if self.project_system_prompt.exists():
            with open(self.project_system_prompt, "r") as f:
                return f.read().strip()
        elif self.root_system_prompt.exists():
            with open(self.root_system_prompt, "r") as f:
                return f.read().strip()
        return ""

    def handle_slash_command(
        self,
        session_id: str,
        user_input: str,
    ) -> InputMode:
        if (
            user_input.lower().startswith("/")
            and user_input.lower() in self.slash_commands
        ):
            print(Fore.RED + user_input + Style.RESET_ALL)
            if user_input.lower() == "/exit":
                self.logger.info("Exiting client.")
                return InputMode.EXIT
            elif user_input.lower() == "/help":
                for cmd in self.config.get("commands", []):
                    print(
                        Style.BRIGHT
                        + f"  {cmd['name']} - {cmd['description']}"
                        + Style.RESET_ALL
                    )
            elif user_input.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                response = requests.post(
                    f"{self.entry_point}/sessions/clear",
                    json={"session_id": session_id},
                )
                if response.status_code == 200:
                    self.logger.info("Session cleared.")
                else:
                    self.logger.error(
                        "Error clearing session: "
                        f"{response.status_code} - {response.text}"
                    )
            elif user_input.lower() == "/system":
                response = requests.get(
                    f"{self.entry_point}/sessions/system",
                    params={"session_id": session_id},
                )
                if response.status_code == 200:
                    system_prompt = response.json().get("system_prompt", None)
                    print(
                        Style.BRIGHT
                        + "Current system prompt:"
                        + Style.RESET_ALL
                    )
                    print(
                        system_prompt
                        if system_prompt
                        else "No system prompt set."
                    )
                else:
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
                response = requests.post(
                    f"{self.entry_point}/sessions/compact",
                    json={
                        "session_id": session_id,
                        "summary_limit": limit,
                        "keep_turns": keep_turns,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "")
                    print(Fore.RED + status + Style.RESET_ALL)
                    self.logger.info(status)
                    self.ctx_used = data.get("meta", {}).get("ctx_used", 0)
                    self.upload_tokens += data.get("meta", {}).get(
                        "prompt_tokens", 0
                    )
                    self.download_tokens += data.get("meta", {}).get(
                        "completion_tokens", 0
                    )
                    self.cost += data.get("meta", {}).get("cost", 0.0)
                    self.update_banner(
                        session=session_id[:8],
                        ctx_used=self.ctx_used,
                        upload_tokens=self.upload_tokens,
                        download_tokens=self.download_tokens,
                        cost=self.cost,
                    )
                else:
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
                response = requests.get(f"{self.entry_point}/health")
                if response.status_code == 200:
                    self.logger.info("Successfully connected to the server.")
                    break
            except requests.exceptions.ConnectionError:
                self.logger.warning(
                    "Connection failed. Retrying in 2 seconds..."
                )
                time.sleep(2)

        if not session_id:
            response = requests.post(f"{self.entry_point}/sessions/create")
            session_id = response.json().get("session_id", "")
        else:
            response = requests.post(
                f"{self.entry_point}/sessions/resume",
                json={"session_id": session_id},
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
                self.logger.error(
                    "Error resuming session: "
                    f"{response.status_code} - {response.text}"
                )
                return

        # set system prompt if exists
        system_prompt = self.read_system_prompt()
        if system_prompt:
            response = requests.post(
                f"{self.entry_point}/sessions/system",
                json={
                    "system_prompt": system_prompt,
                    "session_id": session_id,
                },
            )
            if response.status_code == 200:
                self.logger.info("System prompt set successfully.")
            else:
                self.logger.error(
                    "Error setting system prompt: "
                    f"{response.status_code} - {response.text}"
                )

        history = FileHistory(str(self.prompt_history_path))
        completer = ChatCompleter(slash_commands=self.slash_commands)

        while True:
            terminal_width = shutil.get_terminal_size(
                fallback=(80, 24)
            ).columns

            hint = "Enter your message (or '/help' for commands)"
            hint = hint + " " * (terminal_width - len(hint) - 1)
            hint = f"{Fore.BLACK}{Back.WHITE}{hint}{Style.RESET_ALL}"
            hint = ANSI(hint)

            separator = "_" * terminal_width
            print(Style.BRIGHT + separator + Style.RESET_ALL)
            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)
            user_input = prompt(
                placeholder=hint,
                multiline=False,
                history=history,
                completer=completer,
            )
            print(Fore.GREEN + "user:" + Style.RESET_ALL)

            mode = self.handle_slash_command(session_id, user_input)
            if mode == InputMode.EXIT:
                break
            elif mode == InputMode.COMMAND:
                continue
            else:
                print(user_input)

            message = {"role": "user", "content": user_input}
            response = requests.post(
                f"{self.entry_point}/sessions/completion",
                json={"message": message, "session_id": session_id},
                stream=True,
            )
            if response.status_code != 200:
                self.logger.error(
                    "Error from server: "
                    f"{response.status_code} - {response.text}"
                )
                continue

            in_reasoning = False
            first_chunk = True
            spinner_stop = threading.Event()
            spinner_thread = threading.Thread(
                target=self._spin,
                args=(spinner_stop, "Thinking..."),
                daemon=True,
            )
            spinner_thread.start()

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
                    self.update_banner(
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
                        Style.DIM + text + Style.RESET_ALL, end="", flush=True
                    )
                else:
                    if in_reasoning:
                        print()
                        in_reasoning = False
                        print(
                            Fore.MAGENTA + "assistant:\n" + Style.RESET_ALL,
                            end="",
                            flush=True,
                        )
                    print(text, end="", flush=True)
            # force stop spinner in case no chunks received
            if not spinner_stop.is_set():
                spinner_stop.set()
                spinner_thread.join()

    def run(self, prompt: str):
        self.logger.info(f"Connecting to server at {self.entry_point}...")

        # Check server health
        response = requests.get(f"{self.entry_point}/health")
        if response.status_code == 200:
            self.logger.info("Successfully connected to the server.")
        else:
            self.logger.error(
                "Failed to connect to the server: "
                f"{response.status_code} - {response.text}"
            )
            return

        # Create a new session for this subagent task
        response = requests.post(f"{self.entry_point}/sessions/create")
        if response.status_code == 200:
            session_id = response.json().get("session_id", "")
            self.logger.info(f"Created new session with ID: {session_id}")
        else:
            self.logger.error(
                "Failed to create session: "
                f"{response.status_code} - {response.text}"
            )
            return

        system_prompt = self.read_system_prompt()
        if system_prompt:
            response = requests.post(
                f"{self.entry_point}/sessions/system",
                json={
                    "system_prompt": system_prompt,
                    "session_id": session_id,
                },
            )
            if response.status_code == 200:
                self.logger.info("System prompt set successfully.")
            else:
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

        response = requests.post(
            f"{self.entry_point}/subagent/run",
            json={"message": message, "session_id": session_id},
        )
        if response.status_code != 200:
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
        response = requests.get(
            f"{self.entry_point}/sessions/list",
            params={"project_id": project_id, "limit": limit},
        )
        if response.status_code == 200:
            return response.json().get("sessions", [])
        else:
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
        response = requests.get(
            f"{self.entry_point}/sessions/id", params={"session": session}
        )
        if response.status_code == 200:
            session_id = response.json().get("session_id", None)
            if not session_id:
                self.logger.error(f"Session '{session}' not found.")
                return None
            return session_id
        else:
            self.logger.error(
                "Error retrieving session ID: "
                f"{response.status_code} - {response.text}"
            )
            return None

    def delete_session(self, session: str = None):
        if not session:
            self.logger.error("No session ID or prefix or title provided.")
            return

        session_id = self.find_session_id(session)
        if not session_id:
            self.logger.error(f"Session '{session}' not found.")
            return

        response = requests.post(
            f"{self.entry_point}/sessions/delete",
            json={"session_id": session_id},
        )
        if response.status_code == 200:
            status = response.json().get("status", "")
            self.logger.info(status)
        else:
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
