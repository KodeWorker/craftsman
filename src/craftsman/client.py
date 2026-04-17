import itertools
import json
import os
import threading
import time
from pathlib import Path

import requests
from colorama import Fore, Style
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory

from craftsman.logger import CraftsmanLogger

PROMPT_HISTORY_PATH = Path.home() / ".craftsman" / "database" / "craftsman.db"


class Client:
    SLASH_COMMANDS = ["/exit", "/help", "/clear"]

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
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
            f"({cost:.4f}$) "
            f"| sandbox: {sandbox}"
        )

    def connect(self):
        entry_point = f"http://{self.host}:{self.port}"
        self.logger.info(f"Connecting to server at {entry_point}...")

        response = requests.get(f"{entry_point}/chat/session_id")
        session_id = response.json().get("session_id", "")

        while True:
            try:
                response = requests.get(f"{entry_point}/health")
                if response.status_code == 200:
                    self.logger.info("Successfully connected to the server.")
                    break
            except requests.exceptions.ConnectionError:
                self.logger.warning(
                    "Connection failed. Retrying in 2 seconds..."
                )
                time.sleep(2)

        history = FileHistory(str(PROMPT_HISTORY_PATH))

        while True:
            saperator = "_" * os.get_terminal_size().columns
            print(Style.BRIGHT + saperator + Style.RESET_ALL)
            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)
            user_input = prompt(
                "Enter your message (or '/help' for commands): ",
                multiline=False,
                history=history,
            )
            print(Fore.GREEN + "user:" + Style.RESET_ALL)
            if (
                user_input.lower().startswith("/")
                and user_input.lower() in self.SLASH_COMMANDS
            ):
                if user_input.lower() == "/exit":
                    print(Fore.RED + user_input + Style.RESET_ALL)
                    self.logger.info("Exiting client.")
                    break
                elif user_input.lower() == "/help":
                    print(Fore.RED + user_input + Style.RESET_ALL)
                    print(
                        Style.BRIGHT + "Available commands:" + Style.RESET_ALL
                    )
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
                elif user_input.lower() == "/clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    response = requests.post(f"{entry_point}/chat/clear")
                    if response.status_code == 200:
                        self.logger.info("Session cleared.")
                    else:
                        self.logger.error(
                            "Error clearing session: "
                            f"{response.status_code} - {response.text}"
                        )
                else:
                    print(user_input)
                continue
            else:
                print(user_input)

            message = {"role": "user", "content": user_input}
            response = requests.post(
                f"{entry_point}/chat/completion",
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

            def _spin():
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

            spinner_thread = threading.Thread(target=_spin, daemon=True)
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
