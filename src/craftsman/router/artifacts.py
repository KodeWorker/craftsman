from fastapi import APIRouter  # , Depends, HTTPException, Request

from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian

# from craftsman.router.deps import get_current_user


class ArtifactsRouter:
    def __init__(self, librarian: Librarian):
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.librarian = librarian

        self.router = APIRouter(prefix="/artifacts", tags=["artifacts"])
        self.router.post("/")(self.upload_artifact)
        self.router.get("/")(self.list_artifacts)
        self.router.get("/{artifact_id}")(self.get_artifact)
        self.router.delete("/{artifact_id}")(self.delete_artifact)

    async def upload_artifact(self):
        pass

    async def list_artifacts(self):
        pass

    async def get_artifact(self, artifact_id: str):
        pass

    async def delete_artifact(self, artifact_id: str):
        pass
