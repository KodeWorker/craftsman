import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider
from craftsman.router.deps import get_current_user


class SessionsRouter:
    def __init__(
        self, provider: Provider, librarian: Librarian, active_sessions: set
    ):
        self.provider = provider
        self.librarian = librarian
        self.active_sessions = active_sessions
        self.logger = CraftsmanLogger().get_logger(__name__)

        self.router = APIRouter(prefix="/sessions", tags=["sessions"])
        self.router.get("/system")(self.get_system_prompt)
        self.router.get("/list")(self.list_sessions)
        self.router.get("/id")(self.get_session_id)
        self.router.post("/completion")(self.handle_completion)
        self.router.post("/system")(self.set_system_prompt)
        self.router.post("/create")(self.create_session)
        self.router.post("/delete")(self.delete_session)
        self.router.post("/resume")(self.resume_session)
        self.router.post("/clear")(self.clear_session)
        self.router.post("/compact")(self.compact_session)

    async def get_system_prompt(
        self, session_id: str, _: str = Depends(get_current_user)
    ):
        context = self.librarian.get_context(session_id)
        system_prompt = "".join(
            m["content"] for m in context if m.get("role") == "system"
        )
        return {"system_prompt": system_prompt}

    async def list_sessions(
        self,
        project_id: str = None,
        user_id: str = Depends(get_current_user),
        limit: int = None,
    ):
        sessions = self.librarian.structure_db.list_sessions(
            project_id, user_id, limit
        )
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

    async def get_session_id(
        self, session: str = None, _: str = Depends(get_current_user)
    ):
        row = (
            self.librarian.structure_db.resolve_session(session)
            if session
            else None
        )
        session_id = row["id"] if row else None
        return {"session_id": session_id}

    async def handle_completion(
        self, request: Request, _: str = Depends(get_current_user)
    ):
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

        self.librarian.push_context(session_id, message)
        context = self.librarian.get_context(session_id)

        async def stream():
            content = []
            reasoning = []
            up_tokens = 0
            down_tokens = 0
            reason_tokens = 0
            try:
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
            except Exception as e:
                self.logger.error(f"Error in streaming response: {e}")
                yield json.dumps({"kind": "error", "text": str(e)}) + "\n"
                return
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

    async def set_system_prompt(
        self, request: Request, _: str = Depends(get_current_user)
    ):
        body = await request.json()
        system_prompt = body.get("system_prompt", "")
        session_id = body.get("session_id", None)
        if not system_prompt:
            raise HTTPException(
                status_code=400, detail="No system prompt provided."
            )
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        self.librarian.clear_system_prompt(
            session_id
        )  # remove existing system prompts
        self.librarian.push_context(
            session_id, {"role": "system", "content": system_prompt}
        )
        return {"status": "system prompt set"}

    async def create_session(self, user_id: str = Depends(get_current_user)):
        session_id = self.librarian.structure_db.create_session(
            user_id=user_id
        )
        if session_id in self.active_sessions:
            self.logger.warning(
                f"Session ID collision: {session_id} already active. "
            )
        self.active_sessions.add(session_id)  # add to active sessions
        return {"session_id": session_id}

    async def clear_session(
        self, request: Request, _: str = Depends(get_current_user)
    ):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        self.active_sessions.discard(
            session_id
        )  # remove from active sessions if present
        self.librarian.clear_session(session_id)
        return {"status": "session cleared"}

    async def delete_session(
        self, request: Request, _: str = Depends(get_current_user)
    ):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        self.active_sessions.discard(
            session_id
        )  # remove from active sessions if present
        self.librarian.structure_db.delete_session(session_id)
        return {"status": f"session '{session_id}' deleted"}

    async def resume_session(
        self, request: Request, _: str = Depends(get_current_user)
    ):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        messages, meta = self.librarian.retrieve_messages(session_id)
        if session_id in self.active_sessions:
            self.logger.warning(
                f"Session ID collision: {session_id} already active. "
            )
        self.active_sessions.add(session_id)  # add to active sessions
        meta["cost"] = self.provider.cost(
            meta.get("upload_tokens", 0), meta.get("download_tokens", 0)
        )
        for message in messages:
            msg = dict(message)
            if msg.get("role") == "summary":
                msg["role"] = "user"
                msg["content"] = f"[Conversation summary: {msg['content']}]"
            self.librarian.push_context(session_id, msg)
        return {
            "status": (
                f"session '{session_id}' resumed "
                f"with {len(messages)} messages"
            ),
            "meta": meta,
            "messages": [dict(m) for m in messages],
        }

    async def compact_session(
        self, request: Request, _: str = Depends(get_current_user)
    ):
        body = await request.json()
        session_id = body.get("session_id", None)
        if not session_id:
            raise HTTPException(
                status_code=400, detail="No session ID provided."
            )
        summary_limit = body.get("summary_limit", 1000)
        keep_turns = body.get("keep_turns", 5)

        context = self.librarian.get_context(session_id)
        system_msgs = [m for m in context if m.get("role") == "system"]
        convo = [m for m in context if m.get("role") != "system"]

        if len(convo) <= keep_turns * 2:
            return {"status": "nothing to compact"}

        head = convo[: -keep_turns * 2]
        tail = convo[-keep_turns * 2 :]

        message = {
            "role": "user",
            "content": (
                f"Summarize our conversation so far in under "
                f"{summary_limit} tokens. Capture all key decisions, "
                "goals, facts, code changes, and context needed to "
                "continue this work without the original messages. "
                "Nothing load-bearing should be omitted."
            ),
        }

        result = []
        up_tokens = 0
        down_tokens = 0
        cost = 0.0
        async for kind, text in self.provider.completion(
            system_msgs + head + [message],
            max_tokens=summary_limit,
        ):
            if kind == "meta":
                up_tokens = text.get("prompt_tokens", 0)
                down_tokens = text.get("completion_tokens", 0)
                cost = text.get("cost", 0.0)
            elif kind == "content":
                result.append(text)

        summary = "".join(result)

        self.librarian.clear_context(session_id)
        for msg in system_msgs:
            self.librarian.push_context(session_id, msg)
        self.librarian.push_context(
            session_id,
            {"role": "user", "content": f"[Conversation summary: {summary}]"},
        )
        for msg in tail:
            self.librarian.push_context(session_id, msg)

        self.librarian.store_message(
            session_id,
            {
                "role": "summary",
                "content": summary,
                "tokens": up_tokens + down_tokens,
            },
        )

        return {
            "status": f"session '{session_id}' compacted with summary",
            "meta": {
                "prompt_tokens": up_tokens,
                "completion_tokens": down_tokens,
                "cost": cost,
            },
        }
