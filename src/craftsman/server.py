import os
from contextlib import asynccontextmanager

import litellm
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request

from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger
from craftsman.memory.graph import GraphDB
from craftsman.memory.librarian import Librarian
from craftsman.memory.lightrag_adapter import LightRAGAdapter
from craftsman.memory.vector import VectorDB
from craftsman.provider import Provider
from craftsman.router.artifacts import ArtifactsRouter
from craftsman.router.deps import _crypto, get_current_user
from craftsman.router.jobs import JobsRouter
from craftsman.router.sessions import SessionsRouter
from craftsman.router.tools import ToolsRouter


def _build_memory(provider: Provider):
    """Construct VectorDB, GraphDB, and LightRAGAdapter from config.

    All components degrade gracefully: if a dependency is missing or a call
    fails, the relevant object is returned in its disabled state (no-op).
    """
    config = get_config()
    mem_cfg = config.get("memory", {})
    provider_cfg = config.get("provider", {})
    workspace_cfg = config.get("workspace", {})

    embed_dim: int = mem_cfg.get("embedding_dim", 384)
    embed_model: str = mem_cfg.get("embed_model", "").strip()
    lightrag_enabled: bool = mem_cfg.get("lightrag", {}).get("enabled", True)

    db_dir: str = os.path.expanduser(
        workspace_cfg.get("database", "~/.craftsman/database")
    )

    # --- sync embed_fn for VectorDB tools seeding (called at /tools/seed) ---
    def embed_fn(text: str) -> list[float]:
        api_base = provider.api_base
        api_key = provider.api_key
        if not api_base or not api_key:
            raise RuntimeError("Provider not configured yet")
        resp = litellm.embedding(
            model=embed_model,
            input=[text],
            api_base=api_base,
            api_key=api_key,
            num_retries=0,
        )
        return resp.data[0]["embedding"]

    try:
        vector_db = VectorDB(
            embed_fn=embed_fn if embed_model else None,
            dimensions=embed_dim,
        )
    except Exception as exc:
        CraftsmanLogger().get_logger(__name__).warning(
            f"VectorDB init failed (vector search disabled): {exc}"
        )
        vector_db = VectorDB()

    graph_db = GraphDB()

    lightrag_adapter = None
    if lightrag_enabled:
        # async llm_func for LightRAG entity extraction
        async def llm_func(
            prompt, system_prompt=None, history_messages=None, **kwargs
        ):
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if history_messages:
                messages.extend(history_messages)
            messages.append({"role": "user", "content": prompt})
            api_base = provider.api_base
            api_key = provider.api_key
            if not api_base or not api_key:
                return ""
            try:
                resp = await litellm.acompletion(
                    model=provider_cfg.get("model", ""),
                    api_base=api_base,
                    api_key=api_key,
                    messages=messages,
                    max_tokens=kwargs.get("max_tokens", 1024),
                    stream=False,
                )
                return resp.choices[0].message.content or ""
            except Exception:
                return ""

        # async embed_func for LightRAG vector store
        async def async_embed_func(texts: list[str]) -> list[list[float]]:
            api_base = provider.api_base
            api_key = provider.api_key
            if not api_base or not api_key:
                return [[0.0] * embed_dim] * len(texts)
            try:
                resp = await litellm.aembedding(
                    model=embed_model,
                    input=texts,
                    api_base=api_base,
                    api_key=api_key,
                    num_retries=0,
                )
                return [d["embedding"] for d in resp.data]
            except Exception:
                return [[0.0] * embed_dim] * len(texts)

        lightrag_dir = os.path.join(db_dir, "lightrag")
        try:
            lightrag_adapter = LightRAGAdapter(
                working_dir=lightrag_dir,
                llm_func=llm_func,
                embed_func=async_embed_func,
                graph_db=graph_db,
                embedding_dim=embed_dim,
            )
        except Exception as exc:
            CraftsmanLogger().get_logger(__name__).warning(
                f"LightRAGAdapter init failed (KG retrieval disabled): {exc}"
            )

    return vector_db, graph_db, lightrag_adapter


class Server:
    def __init__(self, port: int):
        self.port = port
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.provider = Provider()

        vector_db, graph_db, lightrag_adapter = _build_memory(self.provider)
        self.librarian = Librarian(
            vector_db=vector_db,
            graph_db=graph_db,
            lightrag_adapter=lightrag_adapter,
        )
        self.active_sessions = set()

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield
            self.librarian.close()
            self.logger.info("Memory flushed on shutdown.")

        self.app = FastAPI(lifespan=lifespan)
        self.app.get("/health")(self.health_check)
        self.app.post("/reset")(self.reset_provider)
        self.app.post("/subagent/run")(self.run_subagent)
        self.app.post("/users/login")(self.login_user)
        self.app.get("/users/cost")(self.get_user_cost)

        self.sessions_router = SessionsRouter(
            self.provider, self.librarian, self.active_sessions
        )
        self.artifacts_router = ArtifactsRouter(self.librarian)
        self.tools_router = ToolsRouter(self.librarian)
        self.jobs_router = JobsRouter(self.librarian)
        self.app.include_router(self.sessions_router.router)
        self.app.include_router(self.artifacts_router.router)
        self.app.include_router(self.tools_router.router)
        self.app.include_router(self.jobs_router.router)

    async def health_check(self) -> dict:
        return {"status": "ok"}

    async def reset_provider(
        self,
        request: Request,
        _: str = Depends(get_current_user),
    ) -> dict:
        body = await request.json()
        api_base = body.get("api_base", None)
        api_key = body.get("api_key", None)
        model = body.get("model", None)
        self.provider.reset(api_base=api_base, api_key=api_key, model=model)
        return {"status": "provider reset"}

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
            self.active_sessions.discard(session_id)

    async def get_user_cost(
        self, user_id: str = Depends(get_current_user)
    ) -> dict:
        tokens = self.librarian.structure_db.get_user_tokens(user_id)
        cost = self.provider.cost(
            tokens["upload_tokens"], tokens["download_tokens"]
        )
        return {**tokens, "cost": cost}

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

    def start(self):
        host = os.environ.get("CRAFTSMAN_HOST", "127.0.0.1")
        self.logger.info(f"Starting server on {host}:{self.port}...")
        uvicorn.run(self.app, host=host, port=self.port)
