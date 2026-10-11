"""
core/memory/working_memory.py
In-process short-term state for the agent.  Replaces the raw scene_snapshot
dict that was passed around per call in the original interactionManager.
"""
import json
import uuid
import copy
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    Holds the canonical scene state, active plan reference, and a short
    recent-events list for the current session.

    Attributes
    ----------
    scene       : full latest scene snapshot, keyed by object name
    last_scene  : snapshot from the previous update (for diff in Phase 3)
    active_plan : current multi-step plan dict, or None
    recent_events: last N classified events (list of dicts, capped at 10)
    session_id  : UUID generated once at startup, stable for the process lifetime
    """

    MAX_EVENTS = 10

    def __init__(self):
        self.session_id: str = str(uuid.uuid4())
        self.scene: dict = {}
        self.last_scene: dict = {}
        self.active_plan: Optional[dict] = None
        self.recent_events: list[dict] = []

    # ------------------------------------------------------------------
    # Scene state
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_snapshot(snapshot) -> dict:
        """
        Ensure *snapshot* is a plain dict.

        Unity occasionally serialises scene_snapshot as a JSON string inside
        the outer JSON payload (double-serialisation).  When that happens
        ``json.loads`` is called to recover the real dict.  A non-dict,
        non-string value is returned as-is and will fail naturally later so
        the caller sees a clear error instead of a cryptic one.
        """
        if isinstance(snapshot, str):
            try:
                parsed = json.loads(snapshot)
                if isinstance(parsed, dict):
                    logger.debug(
                        "[WorkingMemory] scene_snapshot is double-serialised (JSON string). "
                        "Unwrapped automatically — this is the accepted Unity convention."
                    )
                    return parsed
            except json.JSONDecodeError:
                pass  # will fail in update() with a clear type error
        return snapshot

    def update_scene(self, new_snapshot) -> None:
        """
        Persist the current scene as last_scene, then replace it with
        new_snapshot.  Passing an empty dict is a no-op (guards against
        Unity sending {} when no snapshot is available).

        Accepts either a dict or a JSON-encoded string (the latter can
        happen when Unity double-serialises the payload).
        """
        new_snapshot = self._coerce_snapshot(new_snapshot)
        if not new_snapshot:
            return
        if not isinstance(new_snapshot, dict):
            raise TypeError(
                f"scene_snapshot must be a dict or JSON object string, got {type(new_snapshot).__name__}"
            )
        self.last_scene = copy.deepcopy(self.scene)
        self.scene = copy.deepcopy(new_snapshot)

    def replace_scene(self, snapshot) -> None:
        """Fully replace the scene (used on reset or first call).

        Accepts either a dict or a JSON-encoded string.
        """
        snapshot = self._coerce_snapshot(snapshot)
        self.last_scene = copy.deepcopy(self.scene)
        self.scene = copy.deepcopy(snapshot)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def add_event(self, event: dict) -> None:
        """Append an event and trim to MAX_EVENTS most recent."""
        self.recent_events.append(event)
        if len(self.recent_events) > self.MAX_EVENTS:
            self.recent_events = self.recent_events[-self.MAX_EVENTS:]

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def set_plan(self, plan: dict) -> None:
        self.active_plan = plan

    def clear_plan(self) -> None:
        self.active_plan = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"WorkingMemory(session={self.session_id[:8]}…, "
            f"scene_objects={len(self.scene)}, "
            f"plan={'yes' if self.active_plan else 'none'}, "
            f"events={len(self.recent_events)})"
        )
