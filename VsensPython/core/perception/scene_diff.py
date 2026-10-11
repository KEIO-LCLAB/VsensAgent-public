"""
core/perception/scene_diff.py

SceneDiff — compare two consecutive scene snapshots and produce a structured
change log used by HeartbeatHandler (P3-T3) and AgentCore._build_prompt (P3-T5).

Change detection rules
----------------------
- Sensor objects  : compare sensor.value
    - Binary (OPTICAL) : any change is flagged.
    - Continuous        : flagged only when abs_delta >= 0.1 OR rel_delta >= 20%.
- State objects   : compare the "state" string field.
- User object     : compare position, compute Euclidean distance in metres.
- Ignored fields  : size, rotation, scale, properties, attachTo,
                    showVisualization, showDataGraph  (noisy / not meaningful).
- Added / removed : tracked as object_added / object_removed change types.
"""
from __future__ import annotations

import math
from typing import Any

# Fields that are intentionally skipped when scanning for changes
_IGNORED_FIELDS = frozenset({
    "size", "rotation", "scale", "properties",
    "attachTo", "showVisualization", "showDataGraph",
})

# Thresholds for continuous sensor change detection
_CONTINUOUS_ABS_THRESHOLD: float = 0.10   # absolute value delta
_CONTINUOUS_REL_THRESHOLD: float = 0.20   # 20% relative change


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

def _get_sensor_value(obj: dict) -> Any:
    """Safely extract sensor.value; returns None if absent."""
    sensor = obj.get("sensor")
    if isinstance(sensor, dict):
        return sensor.get("value")
    return None


def _is_sensor(obj: dict) -> bool:
    props = obj.get("properties", [])
    return "sensor" in props or isinstance(obj.get("sensor"), dict)


def _is_optical(obj: dict) -> bool:
    sensor = obj.get("sensor", {})
    return isinstance(sensor, dict) and sensor.get("sensorType") == "OPTICAL"


def _euclidean(a, b) -> float:
    if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def compute_diff(old: dict, new: dict) -> list[dict]:
    """
    Compare two consecutive scene snapshots and return a list of change dicts.

    Change dict shapes
    ------------------
    Sensor value change (binary):
        {
          "object": str,
          "field": "sensor.value",
          "old": <value>, "new": <value>,
          "delta": float,
          "is_binary": True
        }

    Sensor value change (continuous):
        {
          "object": str,
          "field": "sensor.value",
          "old": float, "new": float,
          "delta": float,
          "is_binary": False
        }

    State change:
        {"object": str, "field": "state", "old": str, "new": str}

    User position change:
        {
          "object": "user",
          "field": "position",
          "old": list, "new": list,
          "delta_m": float
        }

    Object added / removed:
        {"object": str, "change_type": "object_added" | "object_removed"}

    Returns an empty list if the snapshots are identical (within thresholds).
    """
    if not old:
        # No previous state to diff against — treat everything as newly added
        return [{"object": name, "change_type": "object_added"} for name in new]

    changes: list[dict] = []

    old_names = set(old.keys())
    new_names = set(new.keys())

    # --- added / removed ---
    for name in sorted(new_names - old_names):
        changes.append({"object": name, "change_type": "object_added"})
    for name in sorted(old_names - new_names):
        changes.append({"object": name, "change_type": "object_removed"})

    # --- changed objects ---
    for name in sorted(old_names & new_names):
        old_obj = old[name]
        new_obj = new[name]

        # Sensor value
        if _is_sensor(new_obj):
            old_val = _get_sensor_value(old_obj)
            new_val = _get_sensor_value(new_obj)
            if old_val is not None and new_val is not None and old_val != new_val:
                binary = _is_optical(new_obj)
                if binary:
                    changes.append({
                        "object": name,
                        "field": "sensor.value",
                        "old": old_val,
                        "new": new_val,
                        "delta": abs(float(new_val) - float(old_val)),
                        "is_binary": True,
                    })
                else:
                    # Continuous sensor — only flag if delta exceeds thresholds
                    try:
                        old_f, new_f = float(old_val), float(new_val)
                        abs_delta = abs(new_f - old_f)
                        rel_delta = abs_delta / (abs(old_f) + 1e-9)
                        if (abs_delta >= _CONTINUOUS_ABS_THRESHOLD
                                or rel_delta >= _CONTINUOUS_REL_THRESHOLD):
                            changes.append({
                                "object": name,
                                "field": "sensor.value",
                                "old": old_val,
                                "new": new_val,
                                "delta": abs_delta,
                                "is_binary": False,
                            })
                    except (TypeError, ValueError):
                        pass  # non-numeric (e.g. IMU produces list) — skip

        # State change
        old_state = old_obj.get("state")
        new_state = new_obj.get("state")
        if old_state is not None and new_state is not None and old_state != new_state:
            changes.append({
                "object": name,
                "field": "state",
                "old": old_state,
                "new": new_state,
            })

        # User position
        if name.lower() == "user":
            old_pos = old_obj.get("position")
            new_pos = new_obj.get("position")
            if old_pos and new_pos:
                delta_m = _euclidean(old_pos, new_pos)
                if delta_m > 0.0:
                    changes.append({
                        "object": name,
                        "field": "position",
                        "old": old_pos,
                        "new": new_pos,
                        "delta_m": round(delta_m, 3),
                    })

    return changes


def as_text(changes: list[dict]) -> str:
    """
    Convert a list of change dicts to a compact, human-readable string for
    prompt injection.

    Example output:
        "OPTICAL-01: value 0→1. Window_A: state open→closed. User: moved 0.43m."
    """
    if not changes:
        return "[no changes]"

    parts: list[str] = []
    for c in changes:
        obj = c.get("object", "?")
        ct = c.get("change_type")
        field = c.get("field")

        if ct == "object_added":
            parts.append(f"{obj}: added to scene.")
        elif ct == "object_removed":
            parts.append(f"{obj}: removed from scene.")
        elif field == "sensor.value":
            parts.append(f"{obj}: value {c['old']}→{c['new']}.")
        elif field == "state":
            parts.append(f"{obj}: state {c['old']}→{c['new']}.")
        elif field == "position":
            parts.append(f"{obj}: moved {c['delta_m']:.2f}m.")

    return " ".join(parts) if parts else "[no changes]"
