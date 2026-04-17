import json
import os
import time

import requests
from colorama import Fore, Style
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from craftsman.logger import CraftsmanLogger

ANSI_SEQUENCES["\x1b[1;2R"] = Keys.F24


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
            f"| sandbox: {sandbox}"
        )

    def connect(self):
        entry_point = f"http://{self.host}:{self.port}"
        self.logger.info(f"Connecting to server at {entry_point}...")

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

        bindings = KeyBindings()

        @bindings.add(Keys.F24)  # Alt+Enter = submit
        def _(event):
            event.app.exit(result=event.current_buffer.text)

        history = FileHistory(os.path.expanduser("~/.craftsman/.history"))

        messages = []
        while True:
            saperator = "=" * os.get_terminal_size().columns
            print(Style.BRIGHT + saperator + Style.RESET_ALL)
            print(Style.BRIGHT + Fore.CYAN + self.banner + Style.RESET_ALL)
            user_input = prompt(
                "Enter your message (or '/help' for commands): ",
                multiline=True,
                key_bindings=bindings,
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
                        + "  /clear - Clear the conversation history"
                        + Style.RESET_ALL
                    )
                    print(
                        Style.BRIGHT
                        + "  /exit - Exit the client"
                        + Style.RESET_ALL
                    )
                elif user_input.lower() == "/clear":
                    print(Fore.RED + user_input + Style.RESET_ALL)
                    messages = []
                    self.logger.info("Conversation history cleared.")
                else:
                    print(user_input)
                continue
            else:
                print(user_input)

            messages += [{"role": "user", "content": user_input}]
            response = requests.post(
                f"{entry_point}/completion",
                json={"messages": messages},
                stream=True,
            )
            if response.status_code != 200:
                self.logger.error(
                    "Error from server: "
                    f"{response.status_code} - {response.text}"
                )
                continue

            assistant_content = ""
            in_reasoning = False
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                kind = chunk["kind"]
                if kind == "meta":
                    print()
                    self.update_banner(
                        model=chunk.get("model", ""),
                        ctx_used=chunk.get("total_tokens", 0),
                        ctx_total=chunk.get("ctx_total", 0),
                        upload_tokens=chunk.get("prompt_tokens", 0),
                        download_tokens=chunk.get("completion_tokens", 0),
                    )
                    continue
                text = chunk["text"]
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
                    elif not assistant_content:
                        print(
                            Fore.MAGENTA + "assistant:\n" + Style.RESET_ALL,
                            end="",
                            flush=True,
                        )
                    print(text, end="", flush=True)
                    assistant_content += text
            messages += [{"role": "assistant", "content": assistant_content}]
