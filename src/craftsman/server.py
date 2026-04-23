import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider
from craftsman.router.artifacts import ArtifactsRouter
from craftsman.router.deps import _crypto
from craftsman.router.sessions import SessionsRouter


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.provider = Provider()
        self.librarian = Librarian()
        self.active_sessions = set()

        self.app = FastAPI()
        self.app.get("/health")(self.health_check)
        self.app.post("/subagent/run")(self.run_subagent)
        self.app.post("/users/login")(self.login_user)

        self.sessions_router = SessionsRouter(
            self.provider, self.librarian, self.active_sessions
        )
        self.artifacts_router = ArtifactsRouter(self.librarian)
        self.app.include_router(self.sessions_router.router)
        self.app.include_router(self.artifacts_router.router)

    async def health_check(self) -> dict:
        return {"status": "ok"}

    async def run_subagent(self, request: Request) -> dict:
        body = await request.json()
        message = body.get("message", {})
        session_id = body.get("session_id", None)
        if not message:
            raise HTTPException(
                status_code=400, detail="No messages provided."
            )
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        try:
            self.librarian.push_context(session_id, message)
            context = self.librarian.get_context(session_id)

            result = []
            up_tokens = 0
            down_tokens = 0
            cost = 0.0
            async for kind, text in self.provider.completion(context):
                if kind == "meta":
                    up_tokens = text.get("prompt_tokens", 0)
                    down_tokens = text.get("completion_tokens", 0)
                    cost = text.get("cost", 0.0)
                elif kind == "content":
                    result.append(text)

            meta = {
                "prompt_tokens": up_tokens,
                "completion_tokens": down_tokens,
                "cost": cost,
            }
            return {"meta": meta, "content": "".join(result)}

        finally:
            self.librarian.clear_session(session_id)  # discard
            self.active_sessions.discard(
                session_id
            )  # remove from active sessions if present

    async def login_user(self, request: Request) -> dict:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            raise HTTPException(
                status_code=400, detail="Username and password are required."
            )
        user = self.librarian.structure_db.get_user(username)
        dummy = "$2b$12$dummyhashfortimingXXXXXXXXXXXXXXXXXXXXXXX"
        password_hash = dict(user)["password_hash"] if user else dummy
        if not user or not _crypto.verify_password(password, password_hash):
            self.logger.warning(f"Failed login attempt for user '{username}'.")
            raise HTTPException(
                status_code=401, detail="Invalid username or password."
            )
        user = dict(user)
        token = _crypto.create_token(user["id"])
        self.logger.info(f"User '{user['username']}' logged in successfully.")
        return {"token": token}

    def list_artifacts(self, session_id: str = None, project_id: str = None):
        artifacts = self.librarian.structure_db.get_artifacts(
            session_id=session_id, project_id=project_id
        )
        artifacts = [dict(artifact) for artifact in artifacts]
        artifact_infos = []
        for artifact in artifacts:
            artifact_id = artifact.get("id", "")[:8]
            filename = artifact.get("filename", "")
            mime_type = artifact.get("mime_type", "")
            size_bytes = artifact.get("size_bytes", 0)
            created_at = artifact.get("created_at", "")
            artifact_info = (
                f"{artifact_id} | {filename} | {mime_type} | "
                f"{size_bytes} bytes | {created_at}"
            )
            artifact_infos.append(artifact_info)
        return artifact_infos

    def delete_artifact(self, artifact: str) -> bool:
        row = self.librarian.structure_db.get_artifact(artifact)
        if not row:
            self.logger.error(f"Artifact '{artifact}' not found.")
            return False
        filepath = row["filepath"]
        self.librarian.structure_db.delete_artifact(artifact)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                self.logger.error(f"Failed to delete file {filepath}: {e}")
        self.logger.info(f"Artifact '{artifact}' deleted.")
        return True

    def start(self):
        self.logger.info(f"Starting server on port {self.port}...")
        uvicorn.run(self.app, host="127.0.0.1", port=self.port)
