from __future__ import annotations

import json
import shutil
from pathlib import Path


class DelegatedTaskWorkspaceManager:
    def __init__(self, *, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self, *, job_id: str, task_payload: dict, scene_context: dict) -> Path:
        workspace = self.root / job_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "artifacts").mkdir(exist_ok=True)
        (workspace / "logs").mkdir(exist_ok=True)
        (workspace / "context").mkdir(exist_ok=True)
        (workspace / "inputs").mkdir(exist_ok=True)
        (workspace / "task.json").write_text(
            json.dumps(task_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (workspace / "context" / "scene_context.json").write_text(
            json.dumps(scene_context or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        inputs_root = workspace / "inputs" / "recordings"
        inputs_root.mkdir(parents=True, exist_ok=True)
        for recording_path in task_payload.get("recording_paths") or []:
            source = Path(recording_path)
            if not source.exists():
                continue
            target = inputs_root / source.name
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        return workspace
