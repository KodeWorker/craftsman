import json

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.app = FastAPI()
        self.provider = Provider()
        self.librarian = Librarian()

        self.app.get("/health")(self.health_check)
        self.app.get("/chat/system")(self.get_system_prompt)
        self.app.get("/sessions/list")(self.list_sessions)
        self.app.get("/sessions/id")(self.get_session_id)
        self.app.post("/chat/system")(self.set_system_prompt)
        self.app.post("/chat/completion")(self.handle_completion)
        self.app.post("/chat/clear")(self.clear_session)
        self.app.post("/subagent/run")(self.run_subagent)
        self.app.post("/sessions/create")(self.create_session)
        self.app.post("/sessions/delete")(self.delete_session)
        self.app.post("/sessions/resume")(self.resume_session)

    async def health_check(self):
        return {"status": "ok"}

    async def get_system_prompt(self, session_id: str):
        context = self.librarian.get_context(session_id)
        system_prompt = "".join(
            m["content"] for m in context if m.get("role") == "system"
        )
        return {"system_prompt": system_prompt}

    async def list_sessions(self, project_id: str = None, limit: int = None):
        sessions = self.librarian.structure_db.list_sessions(project_id, limit)
        response = []
        for session in sessions:
            response.append(
                {
                    "session_id": session["id"],
                    "title": session["title"] or "",
                    "last_input": session["last_input"] or "",
                    "last_input_at": session["last_input_at"] or "",
                }
            )
        return {"sessions": response}

    async def get_session_id(self, session: str = None):
        row = (
            self.librarian.structure_db.resolve_session(session)
            if session
            else None
        )
        session_id = row["id"] if row else None
        return {"session_id": session_id}

    async def set_system_prompt(self, request: Request):
        body = await request.json()
        system_prompt = body.get("system_prompt", "")
        session_id = body.get("session_id", None)
        if not system_prompt:
            return {"error": "No system prompt provided."}
        if not session_id:
            return {"error": "No session ID provided."}
        self.librarian.clear_system_prompt(
            session_id
        )  # remove existing system prompts
        self.librarian.push_context(
            session_id, {"role": "system", "content": system_prompt}
        )
        return {"status": "system prompt set"}

    async def handle_completion(self, request: Request):
        body = await request.json()
        message = body.get("message", dict())
        session_id = body.get("session_id", None)
        if not message:
            return {"error": "No messages provided."}
        if not session_id:
            return {"error": "No session ID provided."}

        self.librarian.push_context(session_id, message)
        context = self.librarian.get_context(session_id)

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
                session_id, {"role": "assistant", "content": content}
            )
            # Store messages and token usage in the structure DB
            message["tokens"] = up_tokens
            self.librarian.store_message(session_id, message)
            # Store reasoning and token usage
            self.librarian.store_message(
                session_id,
                {
                    "role": "reasoning",
                    "content": reasoning,
                    "tokens": reason_tokens,
                },
            )
            # Store assistant response with token usage
            self.librarian.store_message(
                session_id,
                {
                    "role": "assistant",
                    "content": content,
                    "tokens": down_tokens - reason_tokens,
                },
            )

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def clear_session(self, request: Request):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            return {"error": "No session ID provided."}
        self.librarian.clear_session(session_id)
        return {"status": "session cleared"}

    async def delete_session(self, request: Request):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            return {"error": "No session ID provided."}
        self.librarian.structure_db.delete_session(session_id)
        return {"status": f"session '{session_id}' deleted"}

    async def run_subagent(self, request: Request):
        body = await request.json()
        message = body.get("message", dict())
        session_id = body.get("session_id", None)
        if not message:
            return {"error": "No messages provided."}
        if not session_id:
            return {"error": "No session ID provided."}
        try:
            self.librarian.push_context(session_id, message)
            context = self.librarian.get_context(session_id)

            result = []
            up_tokens = 0
            down_tokens = 0
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

    async def create_session(self):
        session_id = self.librarian.structure_db.create_session()
        return {"session_id": session_id}

    async def resume_session(self, request: Request):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            return {"error": "No session ID provided."}
        messages, meta = self.librarian.retrieve_messages(session_id)
        for message in messages:
            self.librarian.push_context(session_id, message)
        return {
            "status": (
                f"session '{session_id}' resumed "
                f"with {len(messages)} messages"
            ),
            "meta": meta,
            "messages": messages,
        }

    def start(self):
        self.logger.info(f"Starting server on port {self.port}...")
        uvicorn.run(self.app, host="0.0.0.0", port=self.port)
