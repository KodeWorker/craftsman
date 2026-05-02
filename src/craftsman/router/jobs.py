import json
import logging
from datetime import datetime, timezone

from croniter import croniter
from fastapi import APIRouter, Depends, Request

from craftsman.memory.librarian import Librarian
from craftsman.router.deps import get_current_user


class JobsRouter:
    def __init__(self, librarian: Librarian):
        self.librarian = librarian
        self.db = librarian.structure_db
        self.logger = logging.getLogger(__name__)
        self.router = APIRouter(prefix="/jobs", tags=["jobs"])
        self.router.get("/due")(self.get_due)
        self.router.post("/scheduled/{job_id}/result")(self.scheduled_result)
        self.router.post("/cron/{cron_id}/result")(self.cron_result)

    async def get_due(self, user_id: str = Depends(get_current_user)) -> dict:
        scheduled = []
        for job in self.db.get_due_jobs(user_id=user_id):
            self.db.update_job_status(job["id"], "running")
            scheduled.append(dict(job))

        now = datetime.now(timezone.utc)
        cron = []
        for job in self.db.list_cron_jobs(active_only=True, user_id=user_id):
            try:
                base_str = job["last_run"] or job["created_at"]
                base_dt = datetime.fromisoformat(base_str).replace(
                    tzinfo=timezone.utc
                )
                c = croniter(job["expression"], base_dt)
                if c.get_next(datetime) <= now:
                    cron.append(dict(job))
            except Exception as e:
                self.logger.warning(f"Skipping cron job {job['id']}: {e}")

        return {"scheduled": scheduled, "cron": cron}

    async def scheduled_result(
        self,
        job_id: str,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        body = await request.json()
        status = body.get("status", "done")
        result = body.get("result")
        self.db.update_job_status(
            job_id, status, json.dumps(result) if result is not None else None
        )
        return {"ok": True}

    async def cron_result(
        self,
        cron_id: str,
        request: Request,
        user_id: str = Depends(get_current_user),
    ) -> dict:
        body = await request.json()
        result = body.get("result")
        self.db.update_cron_last_run(
            cron_id, json.dumps(result) if result is not None else None
        )
        return {"ok": True}
