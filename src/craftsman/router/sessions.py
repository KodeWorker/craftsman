import asyncio
import base64
import json
import re

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.provider import Provider
from craftsman.router.deps import get_current_user

_AUDIO_FMT = {"mpeg": "mp3", "x-wav": "wav", "wave": "wav"}


class SessionsRouter:
    def __init__(
        self, provider: Provider, librarian: Librarian, active_sessions: set
    ):
        self.provider = provider
        self.librarian = librarian
        self.active_sessions = active_sessions
        self.logger = CraftsmanLogger().get_logger(__name__)

        self.router = APIRouter(prefix="/sessions", tags=["sessions"])
        self.router.get("/")(self.list_sessions)
        self.router.get("/resolve")(self.resolve_session)
        self.router.get("/{session_id}/system")(self.get_system_prompt)
        self.router.post("/")(self.create_session)
        self.router.put("/{session_id}/system")(self.set_system_prompt)
        self.router.post("/{session_id}/completion")(self.handle_completion)
        self.router.post("/{session_id}/resume")(self.resume_session)
        self.router.post("/{session_id}/clear")(self.clear_session)
        self.router.post("/{session_id}/compact")(self.compact_session)
        self.router.delete("/{session_id}")(self.delete_session)

    def __check_owner(self, session_id: str, user_id: str):
        session = self.librarian.structure_db.get_session(session_id)
        if not session or session["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Forbidden.")

    async def list_sessions(
        self,
        project_id: str = None,
        user_id: str = Depends(get_current_user),
        limit: int = None,
    ) -> dict:
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

    async def resolve_session(
        self, session: str = None, _: str = Depends(get_current_user)
    ) -> dict:
        row = (
            self.librarian.structure_db.resolve_session(session)
            if session
            else None
        )
        session_id = row["id"] if row else None
        return {"session_id": session_id}

    async def get_system_prompt(
        self, session_id: str, user_id: str = Depends(get_current_user)
    ) -> dict:
        self.__check_owner(session_id, user_id)
        context = self.librarian.get_context(session_id)
        system_prompt = "".join(
            m["content"] for m in context if m.get("role") == "system"
        )
        return {"system_prompt": system_prompt}

    async def handle_completion(
        self,
        session_id: str,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> StreamingResponse:
        body = await request.json()
        message = body.get("message", {})
        if not message:
            raise HTTPException(
                status_code=400, detail="No messages provided."
            )
        self.__check_owner(session_id, user_id)

        original_content = message.get("content", "")
        message = await self.multimodalize_message(message)

        self.librarian.push_context(session_id, message)
        context = self.librarian.get_context(session_id)

        async def stream():
            content = []
            reasoning = []
            up_tokens = 0
            down_tokens = 0
            reason_tokens = 0
            cancel_event = asyncio.Event()
            cancelled = False
            try:
                async for kind, text in self.provider.completion(
                    context, cancel_event=cancel_event
                ):
                    if await request.is_disconnected():
                        cancel_event.set()
                        cancelled = True
                        break
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
            if cancelled:
                self.logger.info(
                    f"Client disconnected mid-stream for session {session_id}"
                )
                return
            content = "".join(content)
            reasoning = "".join(reasoning)
            self.librarian.push_context(
                session_id, {"role": "assistant", "content": content}
            )
            # Store messages and token usage in the structure DB
            self.librarian.store_message(
                session_id,
                {**message, "content": original_content, "tokens": up_tokens},
            )
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
        self,
        session_id: str,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        body = await request.json()
        system_prompt = body.get("system_prompt", "")
        if not system_prompt:
            raise HTTPException(
                status_code=400, detail="No system prompt provided."
            )
        self.__check_owner(session_id, user_id)
        self.librarian.clear_system_prompt(session_id)
        self.librarian.push_context(
            session_id, {"role": "system", "content": system_prompt}
        )
        return {"status": "system prompt set"}

    async def create_session(
        self, user_id: str = Depends(get_current_user)
    ) -> dict:
        session_id = self.librarian.structure_db.create_session(
            user_id=user_id
        )
        if session_id in self.active_sessions:
            self.logger.warning(
                f"Session ID collision: {session_id} already active. "
            )
        self.active_sessions.add(session_id)
        return {"session_id": session_id}

    async def delete_session(
        self,
        session_id: str,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        self.__check_owner(session_id, user_id)
        self.active_sessions.discard(session_id)
        self.librarian.structure_db.delete_session(session_id)
        return {"status": f"session '{session_id}' deleted"}

    async def resume_session(
        self,
        session_id: str,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        self.__check_owner(session_id, user_id)
        messages, meta = self.librarian.retrieve_messages(session_id)
        if session_id in self.active_sessions:
            self.logger.warning(
                f"Session ID collision: {session_id} already active. "
            )
        self.active_sessions.add(session_id)
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

    async def clear_session(
        self,
        session_id: str,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        self.__check_owner(session_id, user_id)
        self.active_sessions.discard(session_id)
        self.librarian.clear_session(session_id)
        return {"status": "session cleared"}

    async def compact_session(
        self,
        session_id: str,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        self.__check_owner(session_id, user_id)
        body = await request.json()
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
            ctx_size=summary_limit,
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

    async def multimodalize_message(self, message: dict) -> dict:
        content = message.get("content", "")
        if not isinstance(content, str):
            return message
        pattern = r"@(image|audio):([0-9a-f-]+)"
        if not re.search(pattern, content):
            return message
        caps = get_config().get("provider", {}).get("capabilities", {})
        parts = []
        last = 0
        for m in re.finditer(pattern, content):
            if m.start() > last:
                parts.append(
                    {"type": "text", "text": content[last : m.start()]}
                )
            media_type, uuid = m.group(1), m.group(2)
            artifact = self.librarian.structure_db.get_artifact(uuid)
            if not artifact:
                self.logger.warning(
                    f"Message references missing artifact {uuid}"
                )
                last = m.end()
                continue
            mime = artifact["mime_type"]
            fmt = _AUDIO_FMT.get(mime.split("/")[-1], mime.split("/")[-1])
            async with aiofiles.open(artifact["filepath"], "rb") as f:
                data = base64.b64encode(await f.read()).decode("utf-8")
            if media_type == "image":
                vision = caps.get("vision", {})
                if not vision.get("enabled", False):
                    raise HTTPException(
                        status_code=400,
                        detail="Vision capability is not enabled.",
                    )
                img_fmt = mime.split("/")[-1]
                allowed = vision.get("formats") or []
                if allowed and img_fmt not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image format '{img_fmt}' is not supported.",
                    )
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )
            elif media_type == "audio":
                audio_cap = caps.get("audio", {})
                if not audio_cap.get("enabled", False):
                    raise HTTPException(
                        status_code=400,
                        detail="Audio capability is not enabled.",
                    )
                allowed = audio_cap.get("formats") or []
                if allowed and fmt not in allowed:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Audio format '{fmt}' is not supported.",
                    )
                parts.append(
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data, "format": fmt},
                    }
                )
            last = m.end()
        if last < len(content):
            parts.append({"type": "text", "text": content[last:]})
        if not parts:
            return message
        return {"role": message["role"], "content": parts}
