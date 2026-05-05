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
        user_id: str = Depends(get_current_user),
    ) -> dict:
        import uuid

        artifact_id = str(uuid.uuid4())
        suffix = Path(file.filename).suffix
        dest = self.artifacts_dir / f"{artifact_id}{suffix}"
        try:
            async with aiofiles.open(dest, "wb") as out:
                while chunk := await file.read(65536):
                    await out.write(chunk)
        except Exception as e:
            self.logger.error(f"Failed to write artifact {artifact_id}: {e}")
            raise HTTPException(status_code=500, detail="Upload failed.")

        size = dest.stat().st_size
        self.librarian.structure_db.add_artifact(
            artifact_id=artifact_id,
            filepath=str(dest),
            filename=file.filename,
            user_id=user_id,
            session_id=session_id,
            mime_type=file.content_type,
            size_bytes=size,
        )
        self.logger.info(
            f"Artifact {artifact_id} uploaded: {file.filename} ({size} bytes)"
        )
        return {"artifact_id": artifact_id}

    async def list_artifacts(
        self,
        session_id: str = None,
        project_id: str = None,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        if session_id:
            session = self.librarian.structure_db.get_session(session_id)
            if not session or session["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden.")
        if project_id:
            project = self.librarian.structure_db.get_project(project_id)
            if not project or project["user_id"] != user_id:
                raise HTTPException(status_code=403, detail="Forbidden.")
        artifacts = self.librarian.structure_db.get_artifacts(
            user_id=user_id, session_id=session_id, project_id=project_id
        )
        return {"artifacts": [dict(artifact) for artifact in artifacts]}

    def __resolve(self, artifact_id: str):
        full_id = self.librarian.structure_db.resolve_artifact_id(artifact_id)
        if not full_id:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        artifact = self.librarian.structure_db.get_artifact(full_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found.")
        return full_id, artifact

    async def get_artifact(
        self, artifact_id: str, user_id: str = Depends(get_current_user)
    ) -> dict | None:
        _, artifact = self.__resolve(artifact_id)
        if artifact["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Forbidden.")
        return {"artifact": dict(artifact)}

    async def delete_artifact(
        self, artifact_id: str, user_id: str = Depends(get_current_user)
    ) -> dict:
        full_id, artifact = self.__resolve(artifact_id)
        if artifact["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Forbidden.")
        self.librarian.structure_db.delete_artifact(full_id)
        if artifact["filepath"] and os.path.exists(artifact["filepath"]):
            try:
                os.remove(artifact["filepath"])
            except Exception as e:
                self.logger.error(
                    f"Failed to delete artifact file"
                    f" {artifact['filepath']}: {e}"
                )
        self.logger.info(f"Artifact {full_id} deleted.")
        return {"status": "Artifact deleted successfully."}
