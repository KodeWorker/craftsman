import json

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from craftsman.logger import CraftsmanLogger
from craftsman.provider import Provider


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.app = FastAPI()
        self.provider = Provider()

        self.app.get("/health")(self.health_check)
        self.app.post("/completion")(self.handle_completion)

    async def health_check(self):
        return {"status": "ok"}

    async def handle_completion(self, request: Request):
        body = await request.json()
        messages = body.get("messages", [])
        if not messages:
            return {"error": "No messages provided."}

        self.logger.info(
            f"Received completion request with {len(messages)} messages."
        )

        async def stream():
            async for kind, text in self.provider.completion(messages):
                if kind == "meta":
                    yield json.dumps({"kind": "meta", **text}) + "\n"
                else:
                    yield json.dumps({"kind": kind, "text": text}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    def start(self):
        self.logger.info(f"Starting server on port {self.port}...")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port)
