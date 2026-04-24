import shutil

from colorama import Fore, Style
from prompt_toolkit.shortcuts import choice

from craftsman.client.base import BaseClient


class SessionsClient(BaseClient):

    def __init__(self, host: str, port: int):
        super().__init__(host, port)

    def get_sessions(self, project_id: str = None, limit: int = 5) -> list:
        response = self._request(
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
        response = self._request(
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

    def delete_session(self, session: str = None) -> bool:
        if not session:
            print(
                Fore.RED
                + "No session ID or prefix or title provided."
                + Style.RESET_ALL
            )
            self.logger.error("No session ID or prefix or title provided.")
            return False

        session_id = self.find_session_id(session)
        if not session_id:
            print(
                Fore.RED + f"Session '{session}' not found." + Style.RESET_ALL
            )
            self.logger.error(f"Session '{session}' not found.")
            return False

        response = self._request(
            "delete",
            f"{self.entry_point}/sessions/{session_id}",
        )
        if response.status_code == 200:
            self.logger.info(response.json().get("status", ""))
            return True
        print(
            Fore.RED
            + f"Error deleting session '{session}'. Please check logs."
            + Style.RESET_ALL
        )
        self.logger.error(
            "Error deleting session: "
            f"{response.status_code} - {response.text}"
        )
        return False

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
