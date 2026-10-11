"""
core/skills/scene_skills.py
Registers the four core Unity control actions with the SkillRegistry.

Import this module at startup to trigger all @register side-effects:
    import core.skills.scene_skills  # noqa: F401

Each skill function does lightweight local validation and returns the
action dict that will be forwarded to Unity over the WebSocket.
"""
import logging
import random
from pathlib import Path
from typing import Any

from core.memory.semantic_memory import SemanticMemory
from core.skills.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

_DEFAULT_SENSOR_TYPES = ("OPTICAL", "DISTANCE", "IMU")
_DEFAULT_AVATAR_TARGET = "avatar_main"
_DEFAULT_AVATAR_PREFAB = "smplx_male"
_MOTION_PREPARATION_SERVICE: Any = None


def _load_valid_sensor_types() -> tuple[str, ...]:
    project_root = Path(__file__).resolve().parents[2]
    knowledge_dir = project_root / "data" / "memory" / "knowledge"
    knowledge = SemanticMemory(str(knowledge_dir))
    sensors = knowledge.get("sensors") or {}
    sensor_catalog = sensors.get("sensors") if isinstance(sensors, dict) else None

    if isinstance(sensor_catalog, dict) and sensor_catalog:
        return tuple(sensor_catalog.keys())

    logger.warning(
        "[scene_skills] Falling back to default sensor catalog because sensors.yaml was unavailable."
    )
    return _DEFAULT_SENSOR_TYPES


_VALID_SENSOR_TYPES = _load_valid_sensor_types()


def _get_motion_preparation_service():
    global _MOTION_PREPARATION_SERVICE
    if _MOTION_PREPARATION_SERVICE is None:
        from core.motion import MotionPreparationService

        _MOTION_PREPARATION_SERVICE = MotionPreparationService()
    return _MOTION_PREPARATION_SERVICE


def _normalize_avatar_target(target: str, params: dict) -> str:
    return (target or params.get("avatar_id") or _DEFAULT_AVATAR_TARGET).strip()


# ---------------------------------------------------------------------------
# set_state
# ---------------------------------------------------------------------------
@SkillRegistry.register("set_state")
def skill_set_state(target: str, params: dict) -> dict:
    """Set the state of a stateful object (e.g. door, window)."""
    assert "state" in params, "set_state requires a 'state' parameter"
    return {"target": target, "action": "set_state", "parameters": params}


# ---------------------------------------------------------------------------
# set_transform
# ---------------------------------------------------------------------------
@SkillRegistry.register("set_transform")
def skill_set_transform(target: str, params: dict) -> dict:
    """Move/rotate/scale a movable object."""
    assert any(k in params for k in ("position", "rotation", "scale")), (
        "set_transform requires at least one of 'position', 'rotation', or 'scale'"
    )
    return {"target": target, "action": "set_transform", "parameters": params}


# ---------------------------------------------------------------------------
# highlight
# ---------------------------------------------------------------------------
@SkillRegistry.register("highlight")
def skill_highlight(target: str, params: dict) -> dict:
    """Highlight an object; optional 'color' HTML string in params."""
    return {"target": target, "action": "highlight", "parameters": params}


# ---------------------------------------------------------------------------
# set_sensor
# ---------------------------------------------------------------------------
@SkillRegistry.register("set_sensor")
def skill_set_sensor(target: str, params: dict) -> dict:
    """Place or configure a virtual sensor."""
    normalized = dict(params)
    sensor_type = normalized.get("sensor_type")
    assert sensor_type in _VALID_SENSOR_TYPES, (
        f"sensor_type must be one of {_VALID_SENSOR_TYPES}, got '{sensor_type}'"
    )
    normalized.setdefault("show_visualization", "true")
    normalized.setdefault("show_data_graph", "false")
    operation = (normalized.get("operation") or "create_or_update").strip()
    assert operation in {"create", "update", "create_or_update"}, (
        "set_sensor operation must be one of create, update, or create_or_update"
    )
    normalized["operation"] = operation
    if operation == "update":
        assert (target or "").strip(), "set_sensor operation=update requires target"

    attach_mode = (normalized.get("attach_mode") or "").strip()
    if attach_mode == "avatar_joint":
        assert (normalized.get("avatar_id") or "").strip(), (
            "set_sensor with attach_mode=avatar_joint requires avatar_id"
        )
        assert (normalized.get("joint_name") or "").strip(), (
            "set_sensor with attach_mode=avatar_joint requires joint_name"
        )
    return {"target": target, "action": "set_sensor", "parameters": normalized}


@SkillRegistry.register("remove_sensor")
def skill_remove_sensor(target: str, params: dict) -> dict:
    """Remove an existing virtual sensor by object name."""
    assert (target or "").strip(), "remove_sensor requires target sensor object name"
    return {"target": target, "action": "remove_sensor", "parameters": dict(params)}


@SkillRegistry.register("spawn_avatar")
def skill_spawn_avatar(target: str, params: dict) -> dict:
    avatar_target = _normalize_avatar_target(target, params)
    prefab_key = params.get("prefab_key", _DEFAULT_AVATAR_PREFAB)
    assert prefab_key, "spawn_avatar requires prefab_key"
    normalized = dict(params)
    normalized["prefab_key"] = prefab_key
    return {"target": avatar_target, "action": "spawn_avatar", "parameters": normalized}


@SkillRegistry.register("remove_avatar")
def skill_remove_avatar(target: str, params: dict) -> dict:
    return {
        "target": _normalize_avatar_target(target, params),
        "action": "remove_avatar",
        "parameters": dict(params),
    }


@SkillRegistry.register("set_avatar_transform")
def skill_set_avatar_transform(target: str, params: dict) -> dict:
    assert any(k in params for k in ("position", "rotation", "scale")), (
        "set_avatar_transform requires at least one of 'position', 'rotation', or 'scale'"
    )
    return {
        "target": _normalize_avatar_target(target, params),
        "action": "set_avatar_transform",
        "parameters": dict(params),
    }


@SkillRegistry.register("load_avatar_motion")
def skill_load_avatar_motion(target: str, params: dict) -> dict:
    normalized = dict(params)
    if not normalized.get("motion_json"):
        motion_description = (normalized.get("motion_description") or "").strip()
        assert motion_description, "load_avatar_motion requires motion_json or motion_description"
        prepared = _get_motion_preparation_service().prepare_motion(
            motion_description,
            duration=float(normalized.get("duration", 8.0)),
            seed=int(normalized.get("seed", random.random())),
            cfg_scale=float(normalized.get("cfg_scale", 5.0)),
            motion_name=normalized.get("motion_name"),
        )
        normalized["motion_id"] = prepared["motion_id"]
        normalized["motion_name"] = prepared["motion_name"]
        normalized["motion_json"] = prepared["motion_json"]
        normalized["source_text"] = prepared["source_text"]
        normalized.pop("motion_description", None)

    assert normalized.get("motion_json"), "load_avatar_motion requires motion_json"
    normalized.setdefault("motion_name", "avatar_motion")
    normalized.setdefault("motion_id", normalized["motion_name"])
    return {
        "target": _normalize_avatar_target(target, normalized),
        "action": "load_avatar_motion",
        "parameters": normalized,
    }


@SkillRegistry.register("play_avatar_motion")
def skill_play_avatar_motion(target: str, params: dict) -> dict:
    normalized = dict(params)
    if "speed" in normalized:
        normalized["speed"] = float(normalized["speed"])
    return {
        "target": _normalize_avatar_target(target, normalized),
        "action": "play_avatar_motion",
        "parameters": normalized,
    }


@SkillRegistry.register("pause_avatar_motion")
def skill_pause_avatar_motion(target: str, params: dict) -> dict:
    return {
        "target": _normalize_avatar_target(target, params),
        "action": "pause_avatar_motion",
        "parameters": dict(params),
    }


@SkillRegistry.register("stop_avatar_motion")
def skill_stop_avatar_motion(target: str, params: dict) -> dict:
    return {
        "target": _normalize_avatar_target(target, params),
        "action": "stop_avatar_motion",
        "parameters": dict(params),
    }


@SkillRegistry.register("clear_avatar_motion")
def skill_clear_avatar_motion(target: str, params: dict) -> dict:
    return {
        "target": _normalize_avatar_target(target, params),
        "action": "clear_avatar_motion",
        "parameters": dict(params),
    }


logger.debug("[scene_skills] Registered skills: %s", SkillRegistry.list_skills())


@SkillRegistry.register("delegate_task")
def skill_delegate_task(target: str, params: dict) -> dict:
    """Request a delegated worker task."""
    normalized = dict(params)
    task_type = (normalized.get("task_type") or "").strip()
    assert task_type in {"analysis"}, "delegate_task task_type must currently be 'analysis'"
    goal = (normalized.get("goal") or "").strip()
    assert goal, "delegate_task requires a non-empty goal"

    selector = (normalized.get("selector") or "recent_n").strip()
    assert selector in {"latest", "all", "recent_n", "by_label"}, (
        "delegate_task selector must be one of latest, all, recent_n, by_label"
    )

    if selector == "by_label":
        assert (normalized.get("timestamp_label") or "").strip(), (
            "delegate_task with by_label requires timestamp_label"
        )

    if selector == "recent_n":
        recent_n = normalized.get("recent_n", 3)
        try:
            recent_n = int(recent_n)
        except (TypeError, ValueError):
            raise AssertionError("delegate_task recent_n must be a positive integer")
        assert recent_n > 0, "delegate_task recent_n must be a positive integer"
        normalized["recent_n"] = recent_n

    normalized["task_type"] = task_type
    normalized["goal"] = goal
    normalized["selector"] = selector

    return {
        "target": target,
        "action": "delegate_task",
        "parameters": normalized,
    }
