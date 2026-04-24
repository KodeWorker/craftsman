import fnmatch
import mimetypes
import re
from pathlib import Path

from colorama import Fore, Style
from prompt_toolkit.shortcuts import choice

from craftsman.client.base import BaseClient


class ArtifactsClient(BaseClient):

    def __init__(self, host: str, port: int):
        super().__init__(host, port)
        self.support_image_formats = (
            self.config.get("provider", {})
            .get("capabilities", {})
            .get("vision", {})
            .get("formats", [])
        )
        self.support_audio_formats = (
            self.config.get("provider", {})
            .get("capabilities", {})
            .get("audio", {})
            .get("formats", [])
        )
        self.completer_ignores = (
            self.config.get("chat", {}).get("completer", {}).get("ignores", [])
        )

    def list_artifacts(self) -> list:
        response = self._request("get", f"{self.entry_point}/artifacts/")
        if response.status_code != 200:
            self.logger.error(
                f"Error listing artifacts: "
                f"{response.status_code} - {response.text}"
            )
            return []
        artifacts = response.json().get("artifacts", [])
        infos = []
        for artifact in artifacts:
            artifact_id = artifact.get("id", "")[:8]
            filename = artifact.get("filename", "")
            mime_type = artifact.get("mime_type", "")
            size_bytes = artifact.get("size_bytes", 0)
            created_at = artifact.get("created_at", "")
            infos.append(
                f"{artifact_id} | {filename} | {mime_type} | "
                f"{size_bytes} bytes | {created_at}"
            )
        return infos

    def pick_artifact(self) -> str | None:
        response = self._request("get", f"{self.entry_point}/artifacts/")
        if response.status_code != 200:
            self.logger.error(
                f"Error listing artifacts: "
                f"{response.status_code} - {response.text}"
            )
            return None
        artifacts = response.json().get("artifacts", [])
        if not artifacts:
            self.logger.info("No artifacts available to pick.")
            return None

        options = [
            (artifact["id"], f"{artifact['id'][:8]} | {artifact['filename']}")
            for artifact in artifacts
        ]

        result = choice(
            message="Please choose an artifact:",
            options=options,
            default=None,
        )
        return result

    def delete_artifact(self, artifact: str | None = None) -> bool:
        if not artifact:
            artifact = self.pick_artifact()
        if not artifact:
            return False

        response = self._request(
            "delete", f"{self.entry_point}/artifacts/{artifact}"
        )
        if response.status_code == 200:
            self.logger.info(f"Artifact '{artifact}' deleted.")
            return True
        self.logger.error(
            f"Error deleting artifact '{artifact}': "
            f"{response.status_code} - {response.text}"
        )
        return False

    def upload_artifacts(self, user_input: str, session_id: str) -> str | None:
        # find all @file_path patterns in user input
        pattern = r"@([\w./\\~:-]+)"
        matches = re.findall(pattern, user_input)
        for file_path in matches:
            # skip if user_input already contains @image: or @audio:
            # pattern to avoid duplicate uploads
            if re.match(r"^(image|audio):[0-9a-f-]+$", file_path):
                continue
            # check if file_path matches any ignore patterns
            if any(
                fnmatch.fnmatch(file_path, pat)
                for pat in self.completer_ignores
            ):
                continue

            # early check file extension before uploading
            # to save time and bandwidth
            extension = Path(file_path).expanduser().suffix[1:].lower()
            if (
                extension not in self.support_image_formats
                and extension not in self.support_audio_formats
            ):
                # email case (e.g. xxx@yyy.zzz -> @yyy.zzz)
                # also matches the pattern, so we should ignore
                continue

            full_path = Path(file_path).expanduser()
            if not full_path.is_file():
                # file not found - print warning and skip
                print(
                    Fore.YELLOW
                    + f"File '{file_path}' not found."
                    + Style.RESET_ALL
                )
                self.logger.warning(f"File '{file_path}' not found.")
                continue

            size_mb = full_path.stat().st_size / (1024 * 1024)
            type_desc, limit_mb = "", 0
            if extension in self.support_image_formats:
                type_desc = "image"
                limit_mb = (
                    self.config.get("provider", {})
                    .get("capabilities", {})
                    .get("vision", {})
                    .get("max_size_mb", 10)
                )
            elif extension in self.support_audio_formats:
                type_desc = "audio"
                limit_mb = (
                    self.config.get("provider", {})
                    .get("capabilities", {})
                    .get("audio", {})
                    .get("max_size_mb", 25)
                )

            if size_mb > limit_mb:
                print(
                    Fore.RED
                    + f"File '{file_path}' is too large ({size_mb:.1f}MB). "
                    + f"Max allowed size for {type_desc} "
                    + f"files is {limit_mb}MB. "
                    + Style.RESET_ALL
                )
                self.logger.error(
                    f"File '{file_path}' is too large ({size_mb:.1f}MB). "
                    f"Max allowed size for {type_desc} files is {limit_mb}MB."
                )
                return None

            mime_type, _ = mimetypes.guess_type(str(full_path))
            with open(full_path, "rb") as f:
                files = {
                    "file": (
                        full_path.name,
                        f,
                        mime_type or "application/octet-stream",
                    )
                }
                response = self._request(
                    "post",
                    f"{self.entry_point}/artifacts/",
                    files=files,
                    data={"session_id": session_id},
                )
            if response.status_code == 200:
                artifact_id = response.json().get("artifact_id", "")
                user_input = user_input.replace(
                    f"@{file_path}",
                    f"@{type_desc}:{artifact_id}",
                )
                self.logger.info(
                    f"Uploaded file '{file_path}' as artifact '{artifact_id}'."
                )
            else:
                print(
                    Fore.RED
                    + f"Error uploading file '{file_path}'. Please check logs."
                    + Style.RESET_ALL
                )
                self.logger.error(
                    f"Error uploading file '{file_path}': "
                    f"{response.status_code} - {response.text}"
                )
                return None
        return user_input
