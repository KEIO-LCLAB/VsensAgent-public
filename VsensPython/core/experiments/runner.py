from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from typing import Any


EventCallback = Callable[[dict], Any]
QueryExecutor = Callable[[dict], Awaitable[dict]]
SleepFn = Callable[[float], Awaitable[Any]]
SnapshotWaiter = Callable[[], Awaitable[dict | None]]
AnalysisRunner = Callable[[dict, dict], Awaitable[dict | None]]
ActionPreparer = Callable[[dict], dict]


def validate_experiment_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("experiment plan must be an object")
    goal = str(plan.get("goal") or "").strip()
    if not goal:
        raise ValueError("experiment plan requires goal")
    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("experiment plan requires non-empty phases")
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            raise ValueError(f"phase {index} must be an object")
        label = str(phase.get("label") or "").strip()
        if not label:
            raise ValueError(f"phase {index} requires label")
        try:
            duration_s = float(phase.get("duration_s"))
        except (TypeError, ValueError):
            raise ValueError(f"phase {label} requires numeric duration_s") from None
        if duration_s <= 0:
            raise ValueError(f"phase {label} requires positive duration_s")

    repeat = int(plan.get("repeat", 1))
    if repeat <= 0:
        raise ValueError("experiment repeat must be positive")
    return plan


class ExperimentRunner:
    def __init__(
        self,
        *,
        query_executor: QueryExecutor,
        sleep: SleepFn | None = None,
        wait_for_snapshot: SnapshotWaiter | None = None,
        run_analysis: AnalysisRunner | None = None,
        on_event: EventCallback | None = None,
        action_preparer: ActionPreparer | None = None,
    ):
        self._query_executor = query_executor
        self._sleep = sleep or asyncio.sleep
        self._wait_for_snapshot = wait_for_snapshot
        self._run_analysis = run_analysis
        self._on_event = on_event
        self._action_preparer = action_preparer
        self._scene_version: int | None = None

    async def run(self, plan: dict) -> dict:
        plan = validate_experiment_plan(plan)
        experiment_id = str(plan.get("experiment_id") or f"exp_{uuid.uuid4().hex[:8]}")
        repeat = int(plan.get("repeat") or 1)
        recording = dict(plan.get("recording") or {})
        analysis_plan = dict(plan.get("analysis") or {})
        avatar_required = _avatar_required(plan)
        recording_started = False

        await self._emit({"event": "experiment.started", "experiment_id": experiment_id, "goal": plan["goal"]})
        await self._sync_scene_version()

        completed_phases: list[dict] = []
        try:
            setup_actions = _normalize_actions(plan.get("setup_actions") or [])
            if setup_actions:
                await self._execute_actions(setup_actions)

            first_phase = str(plan["phases"][0]["label"]).strip()
            await self._execute_actions(
                [
                    {
                        "target": "",
                        "action": "start_sensor_recording",
                        "parameters": {
                            "recording_label": recording.get("label") or experiment_id,
                            "goal": plan["goal"],
                            "initial_phase": first_phase,
                            "sensors": recording.get("sensors") or [],
                        },
                    }
                ]
            )
            recording_started = True
            await self._emit({"event": "recording.started", "experiment_id": experiment_id, "phase": first_phase})

            for repeat_index in range(repeat):
                for phase in plan["phases"]:
                    label = str(phase["label"]).strip()
                    duration_s = float(phase["duration_s"])
                    await self._emit(
                        {
                            "event": "phase.started",
                            "experiment_id": experiment_id,
                            "phase": label,
                            "repeat_index": repeat_index,
                            "duration_s": duration_s,
                        }
                    )
                    await self._execute_actions(
                        [
                            {
                                "target": "",
                                "action": "mark_recording_phase",
                                "parameters": {
                                    "phase_label": label,
                                    "note": phase.get("note") or "",
                                },
                            }
                        ]
                    )
                    phase_actions = _phase_actions(phase, requires_avatar=avatar_required and not phase.get("manual_actor"))
                    if phase_actions:
                        await self._execute_actions(phase_actions)
                    await self._sleep(duration_s)
                    completed_phases.append(
                        {
                            "label": label,
                            "repeat_index": repeat_index,
                            "duration_s": duration_s,
                        }
                    )
                    await self._emit(
                        {
                            "event": "phase.completed",
                            "experiment_id": experiment_id,
                            "phase": label,
                            "repeat_index": repeat_index,
                        }
                    )

            await self._execute_actions(
                [
                    {
                        "target": "",
                        "action": "stop_sensor_recording",
                        "parameters": {"upload_snapshot": recording.get("auto_upload", True)},
                    }
                ]
            )
            recording_started = False
            await self._emit({"event": "recording.stopped", "experiment_id": experiment_id})
        except Exception:
            if recording_started:
                await self._safe_stop_recording(recording)
            raise

        snapshot = None
        if self._wait_for_snapshot is not None and recording.get("auto_upload", True):
            snapshot = await self._wait_for_snapshot()
            await self._emit(
                {
                    "event": "recording.snapshot_saved",
                    "experiment_id": experiment_id,
                    "snapshot": snapshot or {},
                }
            )

        analysis = None
        if analysis_plan.get("run_after") and self._run_analysis is not None and snapshot is not None:
            await self._emit({"event": "analysis.started", "experiment_id": experiment_id})
            analysis = await self._run_analysis(snapshot, plan)
            await self._emit(
                {
                    "event": "analysis.completed",
                    "experiment_id": experiment_id,
                    "analysis": analysis or {},
                }
            )

        result = {
            "experiment_id": experiment_id,
            "goal": plan["goal"],
            "phases": completed_phases,
            "snapshot": snapshot,
            "analysis": analysis,
        }
        await self._emit({"event": "experiment.completed", "experiment_id": experiment_id, "result": result})
        return result

    async def _execute_actions(self, actions: list[dict]) -> dict:
        normalized = [self._prepare_action(item) for item in _normalize_actions(actions)]
        request = {
            "type": "scene.execute_actions",
            "request_id": f"exp_{uuid.uuid4().hex}",
            "scene_version": int(self._scene_version if self._scene_version is not None else -1),
            "strict": True,
            "actions": [
                {
                    "target_id": item.get("target") or item.get("target_id") or "",
                    "action_type": item.get("action") or item.get("action_type") or "",
                    "parameters": dict(item.get("parameters") or {}),
                }
                for item in normalized
            ],
        }
        response = await self._query_executor(request)
        _raise_for_failed_action_response(response)
        if isinstance(response, dict) and response.get("scene_version_after") is not None:
            try:
                self._scene_version = int(response["scene_version_after"])
            except (TypeError, ValueError):
                pass
        return response

    async def _safe_stop_recording(self, recording: dict) -> None:
        try:
            await self._execute_actions(
                [
                    {
                        "target": "",
                        "action": "stop_sensor_recording",
                        "parameters": {"upload_snapshot": recording.get("auto_upload", True)},
                    }
                ]
            )
        except Exception:
            pass

    def _prepare_action(self, action: dict) -> dict:
        if self._action_preparer is None:
            return action
        prepared = self._action_preparer(action)
        if not isinstance(prepared, dict):
            raise RuntimeError(f"action preparer returned non-object for {action.get('action')}")
        if prepared.get("status") in {"unknown_skill", "skill_validation_error", "skill_error"}:
            raise RuntimeError(str(prepared.get("message") or prepared))
        return _normalize_actions([prepared])[0]

    async def _sync_scene_version(self) -> None:
        request = {
            "type": "scene.query_summary",
            "request_id": f"exp_{uuid.uuid4().hex}",
        }
        response = await self._query_executor(request)
        if isinstance(response, dict) and response.get("scene_version") is not None:
            self._scene_version = int(response["scene_version"])

    async def _emit(self, event: dict) -> None:
        if self._on_event is None:
            return
        result = self._on_event(event)
        if inspect.isawaitable(result):
            await result


def _normalize_actions(actions: list[dict]) -> list[dict]:
    normalized = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        normalized.append(
            {
                "target": action.get("target") or action.get("target_id") or "",
                "action": action.get("action") or action.get("action_type") or "",
                "parameters": dict(action.get("parameters") or {}),
            }
        )
    return normalized


def _phase_actions(phase: dict, *, requires_avatar: bool = True) -> list[dict]:
    actions = _normalize_actions(phase.get("actions") or [])
    motion_description = str(phase.get("motion_description") or "").strip()
    if requires_avatar and motion_description:
        target = str(phase.get("avatar_id") or "avatar_main").strip() or "avatar_main"
        actions.extend(
            [
                {
                    "target": target,
                    "action": "load_avatar_motion",
                    "parameters": {
                        "motion_description": motion_description,
                        "motion_name": phase.get("motion_name") or phase.get("label"),
                        "duration": float(phase.get("duration_s")),
                    },
                },
                {
                    "target": target,
                    "action": "play_avatar_motion",
                    "parameters": {"speed": 1.0, "loop": False},
                },
            ]
        )
    return actions


def _avatar_required(plan: dict) -> bool:
    actor_mode = str(plan.get("actor_mode") or "").strip().lower()
    if actor_mode == "avatar":
        return True
    if actor_mode == "manual":
        return False
    return bool(plan.get("requires_avatar"))


def _raise_for_failed_action_response(response: dict) -> None:
    if not isinstance(response, dict):
        raise RuntimeError("scene.execute_actions returned a non-object response")
    status = str(response.get("status") or "").strip().lower()
    ok = response.get("ok")
    if status in {"", "success", "ok", "completed"} and ok is not False:
        return

    messages: list[str] = []
    errors = response.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict):
                raw = item.get("message") or item.get("error") or item.get("code")
                if raw:
                    messages.append(str(raw))
            elif item:
                messages.append(str(item))
    if response.get("message"):
        messages.append(str(response["message"]))
    detail = "; ".join(messages) if messages else f"status={response.get('status', '')}"
    raise RuntimeError(f"scene.execute_actions failed: {detail}")
