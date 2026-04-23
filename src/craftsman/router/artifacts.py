import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger
from craftsman.memory.librarian import Librarian
from craftsman.router.deps import get_current_user


class ArtifactsRouter:
    def __init__(self, librarian: Librarian):
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.librarian = librarian
        self.artifacts_dir = Path(
            os.path.expanduser(get_config()["workspace"]["artifacts"])
        )

        self.router = APIRouter(prefix="/artifacts", tags=["artifacts"])
        self.router.post("/")(self.upload_artifact)
        self.router.get("/")(self.list_artifacts)
        self.router.get("/{artifact_id}")(self.get_artifact)
        self.router.delete("/{artifact_id}")(self.delete_artifact)

    async def upload_artifact(
        self,
        file: UploadFile = File(...),
        session_id: str = Form(None),
        _: str = Depends(get_current_user),
    ):
        suffix = Path(file.filename).suffix
        artifact_id = self.librarian.structure_db.add_artifact(
            filepath="",
            filename=file.filename,
            session_id=session_id,
            mime_type=file.content_type,
            size_bytes=0,
        )
        dest = self.artifacts_dir / f"{artifact_id}{suffix}"
        try:
            async with aiofiles.open(dest, "wb") as out:
                while chunk := await file.read(65536):
                    await out.write(chunk)
        except Exception as e:
            self.logger.error(f"Failed to write artifact {artifact_id}: {e}")
            raise HTTPException(status_code=500, detail="Upload failed.")

        size = dest.stat().st_size
        self.librarian.structure_db.update_artifact(
            artifact_id, filepath=str(dest), size_bytes=size
        )
        self.logger.info(
            f"Artifact {artifact_id} uploaded: {file.filename} ({size} bytes)"
        )
        return {"artifact_id": artifact_id}

    async def list_artifacts(self):
        pass

    async def get_artifact(self, artifact_id: str):
        pass

    async def delete_artifact(self, artifact_id: str):
        pass
