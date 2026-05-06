import itertools
import random
import shutil
import time

import requests
from colorama import Fore, Style

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger

_AT_FILE_STYLE_CLASS = "class:at-file"  # `@` file completion style class name
_AT_FILE_STYLE = "fg:ansimagenta bold"  # `@` file completion style


class BaseClient:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.entry_point = f"http://{self.host}:{self.port}"
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.config = get_config()
        self.banner = "Welcome to Craftsman!"
        self.footer_pool = self.config.get("chat", {}).get("footer", [])
        self.footer = self.footer_pool[0] if self.footer_pool else ""
        self.request_session = requests.Session()

    def _jwt_token(self) -> str | None:
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

    def _seed_tools(self) -> None:
        self._request("post", f"{self.entry_point}/tools/seed")

    # wire requests through this method to handle 401
    # and retry with JWT token if needed
    def _request(
        self, method: str, url: str, _reseeding: bool = False, **kwargs
    ) -> requests.Response:
        resp = getattr(self.request_session, method)(url, **kwargs)
        if resp.status_code == 401:
            token = self._jwt_token()
            if not token:
                return resp
            self.request_session.headers.update(
                {"Authorization": f"Bearer {token}"}
            )
            resp = getattr(self.request_session, method)(url, **kwargs)
            # Server restarted — re-seed tools into the fresh DB
            if not _reseeding:
                self._request(
                    "post",
                    f"{self.entry_point}/tools/seed",
                    _reseeding=True,
                )
        return resp

    def _update_banner(
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

        terminal_width = shutil.get_terminal_size(fallback=(80, 24)).columns
        separator = "_" * terminal_width

        self.banner = (
            f"{Style.BRIGHT}{Fore.CYAN}{separator}\n"
            f"model: {model} | session: {session} "
            f"| ctx: {ctx_used_display}/{ctx_total_display} "
            f"| {upload_tokens_display}↑ {download_tokens_display}↓ "
            f"| (${cost:.4f}) "
            f"| sandbox: {sandbox}"
        )

    def _update_footer(self):
        if self.footer_pool:
            self.footer = random.choice(self.footer_pool)

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
