import json

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider


class StoreMessageRequest(BaseModel):
    session_id: str
    message: dict


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.app = FastAPI()
        self.provider = Provider()
        self.librarian = Librarian()
        self.session_id = self.librarian.structure_db.create_session()

        self.app.get("/health")(self.health_check)
        self.app.get("/chat/session_id")(self.get_session_id)
        self.app.post("/chat/completion")(self.handle_completion)
        self.app.post("/chat/clear")(self.clear_session)

    async def health_check(self):
        return {"status": "ok"}

    async def get_session_id(self):
        return {"session_id": self.session_id}

    async def handle_completion(self, request: Request):
        body = await request.json()
        message = body.get("message", dict())
        if not message:
            return {"error": "No messages provided."}

        self.librarian.push_context(self.session_id, message)
        context = self.librarian.get_context(self.session_id)

        async def stream():
            content = []
            reasoning = []
            up_tokens = 0
            down_tokens = 0
            reason_tokens = 0
            async for kind, text in self.provider.completion(context):
                if kind == "meta":
                    up_tokens = text.get("prompt_tokens", 0)
                    down_tokens = text.get("completion_tokens", 0)
                    reason_tokens = text.get("reasoning_tokens", 0)
                    yield json.dumps({"kind": "meta", **text}) + "\n"
                else:
                    if kind == "content":
                        content.append(text)
                    elif kind == "reasoning":
                        reasoning.append(text)
                    yield json.dumps({"kind": kind, "text": text}) + "\n"
            content = "".join(content)
            reasoning = "".join(reasoning)
            self.librarian.push_context(
                self.session_id, {"role": "assistant", "content": content}
            )
            # Store messages and token usage in the structure DB
            message["tokens"] = up_tokens
            self.librarian.store_message(self.session_id, message)
            # Store reasoning and token usage
            self.librarian.store_message(
                self.session_id,
                {
                    "role": "reasoning",
                    "content": reasoning,
                    "tokens": reason_tokens,
                },
            )
            # Store assistant response with token usage
            self.librarian.store_message(
                self.session_id,
                {
                    "role": "assistant",
                    "content": content,
                    "tokens": down_tokens - reason_tokens,
                },
            )

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def clear_session(self):
        self.librarian.clear_session(self.session_id)
        return {"status": "session cleared"}

    def start(self):
        self.logger.info(f"Starting server on port {self.port}...")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port)
