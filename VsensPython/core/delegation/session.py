from __future__ import annotations

import json
import uuid
from pathlib import Path


class DelegatedSubagentSessionManager:
    _SESSION_FILE_NAME = "subagent_session.json"

    def create_session(self, *, workspace: Path, job_id: str, task_payload: dict) -> dict:
        workspace = Path(workspace)
        state = {
            "session_id": f"subagent_{uuid.uuid4().hex[:12]}",
            "job_id": job_id,
            "task_payload": dict(task_payload or {}),
            "status": "running",
            "pending_question_id": None,
            "pending_questions": [],
            "history": [],
        }
        self._write(workspace=workspace, state=state)
        return state

    def load_session(self, *, workspace: Path) -> dict:
        workspace = Path(workspace)
        path = workspace / self._SESSION_FILE_NAME
        return json.loads(path.read_text(encoding="utf-8"))

    def append_history(self, *, workspace: Path, role: str, content: str) -> dict:
        state = self.load_session(workspace=workspace)
        state.setdefault("history", []).append({"role": role, "content": content})
        self._write(workspace=workspace, state=state)
        return state

    def mark_waiting_on_user(self, *, workspace: Path, question_id: str, questions: list[str]) -> dict:
        state = self.load_session(workspace=workspace)
        state["status"] = "waiting_on_user"
        state["pending_question_id"] = question_id
        state["pending_questions"] = list(questions or [])
        self._write(workspace=workspace, state=state)
        return state

    def record_user_reply(self, *, workspace: Path, reply_text: str) -> dict:
        state = self.load_session(workspace=workspace)
        state.setdefault("history", []).append({"role": "user", "content": reply_text})
        state["status"] = "running"
        state["pending_question_id"] = None
        state["pending_questions"] = []
        self._write(workspace=workspace, state=state)
        return state

    def mark_completed(self, *, workspace: Path) -> dict:
        state = self.load_session(workspace=workspace)
        state["status"] = "completed"
        self._write(workspace=workspace, state=state)
        return state

    def mark_failed(self, *, workspace: Path, error: str) -> dict:
        state = self.load_session(workspace=workspace)
        state["status"] = "failed"
        state["error"] = error
        self._write(workspace=workspace, state=state)
        return state

    def ensure_session(self, *, workspace: Path, job_id: str, task_payload: dict) -> dict:
        path = Path(workspace) / self._SESSION_FILE_NAME
        if path.exists():
            return self.load_session(workspace=workspace)
        return self.create_session(workspace=workspace, job_id=job_id, task_payload=task_payload)

    def _write(self, *, workspace: Path, state: dict) -> None:
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / self._SESSION_FILE_NAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
