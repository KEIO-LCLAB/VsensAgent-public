from __future__ import annotations

import uuid

from core.protocol.messages import (
    build_job_cancelled,
    build_job_completed,
    build_job_started,
    build_job_status,
)


class JobManager:
    def __init__(self):
        self._jobs: dict[str, dict] = {}

    def start_job(self, job_kind: str, payload: dict | None = None) -> dict:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "job_kind": job_kind,
            "status": "running",
            "payload": payload or {},
        }
        self._jobs[job_id] = job
        return build_job_started(
            job_id=job_id,
            job_kind=job_kind,
            payload=job["payload"],
        )

    def get_job(self, job_id: str) -> dict:
        job = self._require_job(job_id)
        return build_job_status(
            job_id=job_id,
            job_kind=job["job_kind"],
            status=job["status"],
            payload=job["payload"],
            reason=job.get("reason"),
        )

    def cancel_job(self, job_id: str, reason: str = "") -> dict:
        job = self._require_job(job_id)
        job["status"] = "cancelled"
        if reason:
            job["reason"] = reason
        return build_job_cancelled(
            job_id=job_id,
            job_kind=job["job_kind"],
            payload=job["payload"],
            reason=reason,
        )

    def complete_job(self, job_id: str, payload: dict | None = None) -> dict:
        job = self._require_job(job_id)
        job["status"] = "completed"
        if payload is not None:
            job["payload"] = payload
        return build_job_completed(
            job_id=job_id,
            job_kind=job["job_kind"],
            payload=job["payload"],
        )

    def fail_job(self, job_id: str, reason: str, payload: dict | None = None) -> dict:
        job = self._require_job(job_id)
        job["status"] = "failed"
        job["reason"] = reason
        if payload is not None:
            job["payload"] = payload
        return build_job_status(
            job_id=job_id,
            job_kind=job["job_kind"],
            status="failed",
            payload=job["payload"],
            reason=reason,
        )

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        payload: dict | None = None,
        reason: str | None = None,
    ) -> dict:
        job = self._require_job(job_id)
        job["status"] = status
        if payload is not None:
            job["payload"] = payload
        if reason is not None:
            if reason:
                job["reason"] = reason
            else:
                job.pop("reason", None)
        return build_job_status(
            job_id=job_id,
            job_kind=job["job_kind"],
            status=status,
            payload=job["payload"],
            reason=job.get("reason"),
        )

    def _require_job(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job
