import itertools
import json
import os
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

from craftsman.logger import CraftsmanLogger

PROMPT_HISTORY_PATH = Path.home() / ".craftsman" / "database" / "craftsman.db"
PROJECT_SYSTEM_PROMPT = Path.cwd() / ".craftsman" / "system_prompt.md"
ROOT_SYSTEM_PROMPT = Path.home() / ".craftsman" / "system_prompt.md"
SLASH_COMMANDS = ["/exit", "/help", "/clear", "/system"]


class ChatCompleter(Completer):

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        # slash command completion
        for cmd in SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))
        # project file completion
        for root, dirs, files in os.walk(Path.cwd()):
            for file in files:
                file_path = os.path.relpath(os.path.join(root, file))
                if file_path.startswith(text):
                    yield Completion(file_path, start_position=-len(text))


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
        self.banner = "Welcome to Craftsman!"

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
    def _spin(spinner_stop):
        for frame in itertools.cycle(
            ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        ):
            if spinner_stop.is_set():
                break
            print(
                f"\r{Style.DIM}{frame} Thinking...{Style.RESET_ALL}",
                end="",
                flush=True,
            )
            time.sleep(0.08)
        print("\r  \r", end="", flush=True)

    def read_system_prompt(self):
        if PROJECT_SYSTEM_PROMPT.exists():
            with open(PROJECT_SYSTEM_PROMPT, "r") as f:
                return f.read().strip()
        elif ROOT_SYSTEM_PROMPT.exists():
            with open(ROOT_SYSTEM_PROMPT, "r") as f:
                return f.read().strip()
        return ""

    def handle_slash_command(self, user_input: str) -> InputMode:
        if (
            user_input.lower().startswith("/")
            and user_input.lower() in SLASH_COMMANDS
        ):
            if user_input.lower() == "/exit":
                print(Fore.RED + user_input + Style.RESET_ALL)
                self.logger.info("Exiting client.")
                return InputMode.EXIT
            elif user_input.lower() == "/help":
                print(Fore.RED + user_input + Style.RESET_ALL)
                print(Style.BRIGHT + "Available commands:" + Style.RESET_ALL)
                print(
                    Style.BRIGHT
                    + "  /help - Show this help message"
                    + Style.RESET_ALL
                )
                print(
                    Style.BRIGHT
                    + "  /clear - Clear the session"
                    + Style.RESET_ALL
                )
                print(
                    Style.BRIGHT
                    + "  /exit - Exit the client"
                    + Style.RESET_ALL
                )
                print(
                    Style.BRIGHT
                    + "  /system - View system prompt"
                    + Style.RESET_ALL
                )
            elif user_input.lower() == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                response = requests.post(f"{self.entry_point}/chat/clear")
                if response.status_code == 200:
                    self.logger.info("Session cleared.")
                else:
                    self.logger.error(
                        "Error clearing session: "
                        f"{response.status_code} - {response.text}"
                    )
            elif user_input.lower() == "/system":
                response = requests.get(f"{self.entry_point}/chat/system")
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
            else:
                return InputMode.MESSAGE
            return InputMode.COMMAND
        return InputMode.MESSAGE

    def chat(self):
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

        # get session id
        response = requests.get(f"{self.entry_point}/chat/session_id")
        session_id = response.json().get("session_id", "")

        # set system prompt if exists
        system_prompt = self.read_system_prompt()
        if system_prompt:
            response = requests.post(
                f"{self.entry_point}/chat/system",
                json={"system_prompt": system_prompt},
            )
            if response.status_code == 200:
                self.logger.info("System prompt set successfully.")
            else:
                self.logger.error(
                    "Error setting system prompt: "
                    f"{response.status_code} - {response.text}"
                )

        history = FileHistory(str(PROMPT_HISTORY_PATH))
        completer = ChatCompleter()

        while True:
            terminal_width = os.get_terminal_size().columns

            hint = "Enter your message (or '/help' for commands)"
            hint = hint + " " * (terminal_width - len(hint) - 1)
            hint = f"{Fore.BLACK}{Back.WHITE}{hint}{Style.RESET_ALL}"
            hint = ANSI(hint)

            saperator = "_" * terminal_width
            print(Style.BRIGHT + saperator + Style.RESET_ALL)
            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)
            user_input = prompt(
                placeholder=hint,
                multiline=False,
                history=history,
                completer=completer,
            )
            print(Fore.GREEN + "user:" + Style.RESET_ALL)

            mode = self.handle_slash_command(user_input)
            if mode == InputMode.EXIT:
                break
            elif mode == InputMode.COMMAND:
                continue
            else:
                print(user_input)

            message = {"role": "user", "content": user_input}
            response = requests.post(
                f"{self.entry_point}/chat/completion",
                json={"message": message},
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
                target=self._spin, args=(spinner_stop,), daemon=True
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
                        ctx_used=chunk.get("ctx_used", 0),
                        ctx_total=chunk.get("ctx_total", 0),
                        upload_tokens=chunk.get("prompt_tokens", 0),
                        download_tokens=chunk.get("completion_tokens", 0),
                        cost=chunk.get("cost", 0),
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

    def run(self, prompt: str):
        self.logger.info(f"Connecting to server at {self.entry_point}...")
        system_prompt = self.read_system_prompt()
        if system_prompt:
            response = requests.post(
                f"{self.entry_point}/chat/system",
                json={"system_prompt": system_prompt},
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
            target=self._spin, args=(spinner_stop,), daemon=True
        )
        spinner_thread.start()

        response = requests.post(
            f"{self.entry_point}/subagent/run",
            json={"message": message},
            stream=True,
        )
        if response.status_code != 200:
            self.logger.error(
                "Error from server: "
                f"{response.status_code} - {response.text}"
            )
            return

        content = []
        up_tokens = 0
        down_tokens = 0
        cost = 0.0
        content = response.json().get("content", "")
        up_tokens = response.json().get("meta", {}).get("prompt_tokens", 0)
        down_tokens = (
            response.json().get("meta", {}).get("completion_tokens", 0)
        )
        cost = response.json().get("meta", {}).get("cost", 0.0)
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

    def list_sessions(self, project_id: str = None, limit: int = 5):
        response = requests.get(
            f"{self.entry_point}/chat/sessions",
            params={"project_id": project_id, "limit": limit},
        )

        if response.status_code == 200:
            sessions = response.json().get("sessions", [])

            terminal_width = os.get_terminal_size().columns
            for session in sessions:
                session_id = session.get("session_id", "(Unknown ID)")
                title = session.get("title", "(Untitled Session)")
                last_input_at = session.get("last_input_at", "N/A")
                last_input = session.get("last_input", "(No messages)")
                display_input = (
                    last_input[: terminal_width - 3] + "..."
                    if len(last_input) > terminal_width
                    else last_input
                )

                info = (
                    f"{Fore.CYAN}{session_id[:8]} | "
                    f"{title} | {last_input_at}{Style.RESET_ALL}\n"
                    f"{display_input}"
                )
                print(info)
        else:
            self.logger.error(
                "Error retrieving sessions: "
                f"{response.status_code} - {response.text}"
            )

    def delete_session(self, session: str = None):
        if not session:
            self.logger.error("No session ID provided.")
            return
        response = requests.post(
            f"{self.entry_point}/sessions/delete", json={"session": session}
        )
        if response.status_code == 200:
            status = response.json().get("status", "")
            self.logger.info(status)
        else:
            self.logger.error(
                "Error deleting session: "
                f"{response.status_code} - {response.text}"
            )
