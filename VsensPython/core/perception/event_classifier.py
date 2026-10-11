"""
core/perception/event_classifier.py

EventClassifier — map a list of SceneDiff change dicts to named event types
and severity scores, so HeartbeatHandler can decide whether to wake the LLM.

Severity scale
--------------
0.0  trivial / no event
0.4  informational (recorded in recent_events, but LLM not woken)
0.5  threshold that wakes the LLM  (ATTENTION_THRESHOLD)
0.6  notable  (STATE_CHANGE)
0.7  significant  (SENSOR_ANOMALY)
0.8  high-priority  (SENSOR_TRIGGER)

Tunables are grouped at the top of this file so they can be adjusted without
touching the classification logic.
"""
from __future__ import annotations

from typing import Any

# -----------------------------------------------------------------------
# Event type constants
# -----------------------------------------------------------------------

NO_OP          = "NO_OP"           # no meaningful change
SENSOR_TRIGGER = "SENSOR_TRIGGER"  # binary sensor toggled (OPTICAL 0↔1)
SENSOR_ANOMALY = "SENSOR_ANOMALY"  # continuous sensor jumped > 50% in one frame
STATE_CHANGE   = "STATE_CHANGE"    # scene object changed its state string
USER_PROXIMITY = "USER_PROXIMITY"  # user moved > threshold in one heartbeat
OBJECT_ADDED   = "OBJECT_ADDED"    # new object appeared in scene
OBJECT_REMOVED = "OBJECT_REMOVED"  # object disappeared from scene

# -----------------------------------------------------------------------
# Configurable severity table — edit here, not inside the logic below
# -----------------------------------------------------------------------

DEFAULT_SEVERITY: dict[str, float] = {
    SENSOR_TRIGGER: 0.8,
    SENSOR_ANOMALY: 0.7,
    STATE_CHANGE:   0.6,
    OBJECT_ADDED:   0.5,
    OBJECT_REMOVED: 0.5,
    USER_PROXIMITY: 0.4,   # informational — below ATTENTION_THRESHOLD
    NO_OP:          0.0,
}

# Minimum severity required to wake the LLM
ATTENTION_THRESHOLD: float = 0.5

# User movement threshold (metres per heartbeat) to raise USER_PROXIMITY
USER_PROXIMITY_THRESHOLD_M: float = 0.5

# Relative jump threshold to upgrade a continuous sensor change to SENSOR_ANOMALY
# (e.g. 0.50 means a 50% jump from the previous value)
SENSOR_ANOMALY_REL_THRESHOLD: float = 0.50


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def classify(
    changes: list[dict],
    severity_table: dict[str, float] | None = None,
) -> list[dict]:
    """
    Classify a list of SceneDiff change dicts into event dicts.

    Parameters
    ----------
    changes : output of ``scene_diff.compute_diff``
    severity_table : optional override for DEFAULT_SEVERITY (useful in tests)

    Returns
    -------
    list of dicts:
        {
          "event_type": str,    # one of the event-type constants above
          "object":     str,    # name of the scene object involved
          "data":       dict,   # the original change dict from SceneDiff
          "severity":   float,  # from the severity table
        }

    Always returns at least one element.  If no meaningful events were found
    the list contains a single NO_OP entry with severity 0.0.
    """
    sev = severity_table if severity_table is not None else DEFAULT_SEVERITY
    events: list[dict] = []

    for change in changes:
        obj = change.get("object", "unknown")
        event_type = _classify_one(change)

        if event_type == NO_OP:
            continue

        # Upgrade SENSOR_TRIGGER → SENSOR_ANOMALY for large continuous jumps
        if event_type == SENSOR_TRIGGER and not change.get("is_binary", False):
            old_v = change.get("old", 0)
            delta = change.get("delta", 0.0)
            try:
                rel = float(delta) / (abs(float(old_v)) + 1e-9)
                if rel >= SENSOR_ANOMALY_REL_THRESHOLD:
                    event_type = SENSOR_ANOMALY
            except (TypeError, ValueError):
                pass

        events.append({
            "event_type": event_type,
            "object":     obj,
            "data":       change,
            "severity":   sev.get(event_type, 0.0),
        })

    if not events:
        events.append({
            "event_type": NO_OP,
            "object":     "",
            "data":       {},
            "severity":   0.0,
        })

    return events


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

def _classify_one(change: dict) -> str:
    """Return the event type for a single SceneDiff change dict."""
    ct = change.get("change_type")
    if ct == "object_added":
        return OBJECT_ADDED
    if ct == "object_removed":
        return OBJECT_REMOVED

    field = change.get("field")
    if field == "sensor.value":
        # classify() will upgrade to SENSOR_ANOMALY if the jump is large enough
        return SENSOR_TRIGGER

    if field == "state":
        return STATE_CHANGE

    if field == "position" and change.get("object", "").lower() == "user":
        delta_m = change.get("delta_m", 0.0)
        if delta_m >= USER_PROXIMITY_THRESHOLD_M:
            return USER_PROXIMITY
        return NO_OP  # sub-threshold user movement is noise

    return NO_OP
