from __future__ import annotations

from typing import Any


def _normalize_control(control_actions: list[dict] | None) -> dict[str, list[dict]]:
    return {"actions": control_actions or []}


def build_conversation_reply(
    *,
    reply: str,
    turn_id: str | None = None,
    transcription: str | None = None,
    audio_path: str | None = None,
    control: list[dict] | None = None,
    status: str = "success",
    legacy_type: str = "agent_ready",
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": "conversation.reply",
        "status": status,
        "transcription": transcription,
        "reply": reply,
        "audio_path": audio_path,
        "control": _normalize_control(control),
        "legacy_type": legacy_type,
    }
    if turn_id:
        message["turn_id"] = turn_id
    return message


def build_clarification_request(
    *,
    question_id: str,
    prompt: str,
    options: list[dict],
    selection_mode: str = "single",
    reply: str | None = None,
    transcription: str | None = None,
    audio_path: str | None = None,
    control: list[dict] | None = None,
    status: str = "success",
) -> dict[str, Any]:
    return {
        "type": "clarification.request",
        "status": status,
        "question_id": question_id,
        "prompt": prompt,
        "selection_mode": selection_mode,
        "options": options,
        "reply": reply or prompt,
        "transcription": transcription,
        "audio_path": audio_path,
        "control": _normalize_control(control),
    }


def build_proposal_ready(
    *,
    proposal_id: str,
    title: str,
    options: list[dict],
    summary: str = "",
    reply: str | None = None,
    transcription: str | None = None,
    audio_path: str | None = None,
    control: list[dict] | None = None,
    status: str = "success",
) -> dict[str, Any]:
    return {
        "type": "proposal.ready",
        "status": status,
        "proposal_id": proposal_id,
        "title": title,
        "summary": summary,
        "options": options,
        "reply": reply or summary or title,
        "transcription": transcription,
        "audio_path": audio_path,
        "control": _normalize_control(control),
    }


def _build_job_message(
    *,
    message_type: str,
    job_id: str,
    job_kind: str,
    status: str,
    payload: dict | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "type": message_type,
        "job_id": job_id,
        "job_kind": job_kind,
        "status": status,
        "payload": payload or {},
    }
    if reason:
        message["reason"] = reason
    return message


def build_job_started(
    *,
    job_id: str,
    job_kind: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    return _build_job_message(
        message_type="job.started",
        job_id=job_id,
        job_kind=job_kind,
        status="running",
        payload=payload,
    )


def build_job_completed(
    *,
    job_id: str,
    job_kind: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    return _build_job_message(
        message_type="job.completed",
        job_id=job_id,
        job_kind=job_kind,
        status="completed",
        payload=payload,
    )


def build_job_status(
    *,
    job_id: str,
    job_kind: str,
    status: str,
    payload: dict | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return _build_job_message(
        message_type="job.status",
        job_id=job_id,
        job_kind=job_kind,
        status=status,
        payload=payload,
        reason=reason,
    )


def build_job_cancelled(
    *,
    job_id: str,
    job_kind: str,
    payload: dict | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    return _build_job_message(
        message_type="job.cancelled",
        job_id=job_id,
        job_kind=job_kind,
        status="cancelled",
        payload=payload,
        reason=reason,
    )


def build_delegated_task_result(
    *,
    job_id: str,
    task_type: str,
    status: str,
    reply: str,
    questions_for_agent: list[str] | None = None,
    artifacts: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "type": "task.result",
        "status": status,
        "job_id": job_id,
        "job_kind": "delegated_task",
        "task_type": task_type,
        "reply": reply,
        "questions_for_agent": questions_for_agent or [],
        "artifacts": artifacts or [],
    }


def build_delegated_task_artifacts_snapshot(
    *,
    job_id: str,
    task_type: str,
    artifacts: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "type": "task.artifacts_snapshot",
        "job_id": job_id,
        "job_kind": "delegated_task",
        "task_type": task_type,
        "artifacts": artifacts or [],
    }
