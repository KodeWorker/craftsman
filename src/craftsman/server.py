import uvicorn
from fastapi import FastAPI, HTTPException, Request

from craftsman.crypto import Crypto
from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider
from craftsman.router.sessions import SessionsRouter


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.provider = Provider()
        self.librarian = Librarian()
        self.crypto = Crypto()
        self.active_sessions = set()

        self.app = FastAPI()
        self.app.get("/health")(self.health_check)
        self.app.post("/subagent/run")(self.run_subagent)
        self.app.post("/users/login")(self.login_user)

        self.sessions_router = SessionsRouter(
            self.provider, self.librarian, self.active_sessions
        )
        self.app.include_router(self.sessions_router.router)

    async def health_check(self):
        return {"status": "ok"}

    async def run_subagent(self, request: Request):
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

    async def login_user(self, request: Request):
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        if not username or not password:
            raise HTTPException(
                status_code=400, detail="Username and password are required."
            )
        user = self.librarian.structure_db.get_user(username)
        if user:
            user = dict(user)
            username = user["username"]
            password_hash = user["password_hash"]

            if self.crypto.verify_password(password, password_hash):
                token = self.crypto.create_token(username)
                self.logger.info(f"User '{username}' logged in successfully.")
                return {"token": token}
            else:
                self.logger.warning(
                    f"Failed login attempt for user '{username}': "
                    f"Incorrect password."
                )
                raise HTTPException(
                    status_code=401, detail="Invalid username or password."
                )
        else:
            self.logger.warning(
                f"Failed login attempt: User '{username}' not found."
            )
            raise HTTPException(
                status_code=401, detail="Invalid username or password."
            )

    def start(self):
        self.logger.info(f"Starting server on port {self.port}...")
        uvicorn.run(self.app, host="127.0.0.1", port=self.port)
