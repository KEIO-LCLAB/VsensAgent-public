"""
core/perception/heartbeat_handler.py

HeartbeatHandler — processes incoming scene_heartbeat snapshots end-to-end:
  diff → classify → cooldown gate → attention gate → wake LLM → agent_push

Design notes
------------
- Heartbeat handling is intentionally NOT wrapped in the server's
  ``_active_task`` — it must not block the interrupt path.
- No reply is sent to the requesting client for no-op heartbeats (returns None).
- agent_push can optionally include an audio_path when tts_enabled=True in config.
- Per-object cooldown prevents rapid sensor oscillation from spamming the LLM.
"""
from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Callable, Awaitable

from core.perception.scene_diff import compute_diff
from core.perception.event_classifier import (
    classify,
    ATTENTION_THRESHOLD,
    NO_OP,
    OBJECT_ADDED,
)
from core.perception.perception_config import cfg as _default_cfg
from core.skills.control_parser import ControlParser
from core.skills.skill_registry import SkillRegistry
from core.agent_status import AgentStatusBroadcaster, THINKING, IDLE

logger = logging.getLogger(__name__)

_AUDIO_OUT_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "VsensAgent" / "AudioRecordings" / "Response"
)


class HeartbeatHandler:
    """
    Processes one scene_heartbeat per call.

    Parameters
    ----------
    working_memory  : WorkingMemory instance owned by AgentCore
    memory_manager  : MemoryManager (used to store heartbeat-triggered episodes)
    agent           : VsensOpenAI (LLM + optional TTS)
    broadcaster     : AgentStatusBroadcaster
    broadcast_fn    : async callable that pushes a dict to all WS clients
    perception_cfg  : PerceptionConfig singleton (defaults to module-level cfg)
    """

    def __init__(
        self,
        working_memory,
        memory_manager,
        agent,
        broadcaster: AgentStatusBroadcaster,
        broadcast_fn: Callable[[dict], Awaitable[None]],
        perception_cfg=None,
    ):
        self.working_memory = working_memory
        self.memory_manager = memory_manager
        self.agent = agent
        self.broadcaster = broadcaster
        self.broadcast_fn = broadcast_fn
        self._cfg = perception_cfg if perception_cfg is not None else _default_cfg

        # Per-object cooldown: object_name → last trigger timestamp (monotonic)
        self._last_trigger: dict[str, float] = {}

        # Agent-touch suppression: object_name → expiry timestamp (monotonic)
        # Objects the agent itself modified; their scene changes are suppressed
        # for one cooldown window to prevent agent-action → OBJECT_ADDED loops.
        self._agent_touched: dict[str, float] = {}
        self._agent_added_sensor_prefixes: dict[str, float] = {}

    # ------------------------------------------------------------------
    # External touch registration
    # ------------------------------------------------------------------

    def mark_agent_touched(self, targets: list[str], actions: list[dict] | None = None) -> None:
        """
        Register objects modified by the agent *outside* of a heartbeat-
        triggered action (e.g. from a user text_chat or voice command).
        Suppresses the resulting STATE_CHANGE / OBJECT_ADDED / OBJECT_MOVED
        heartbeat events for one cooldown window, preventing the agent from
        reacting to its own user-commanded actions.
        """
        if not self._cfg.cooldown.enabled:
            return
        expiry = time.monotonic() + self._agent_action_suppression_s()
        for tgt in targets:
            if tgt:
                self._agent_touched[tgt] = expiry
                logger.debug(
                    "[Heartbeat] Marked '%s' as agent-touched (external, suppressed for %.0fs).",
                    tgt, self._cfg.cooldown.per_object_s,
                )
        for action in actions or []:
            self._mark_agent_action_touched(action, expiry, source="external")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle(self, scene_snapshot) -> dict | None:
        """
        Process one heartbeat.

        Returns
        -------
        ``agent_push`` dict if a significant event triggered an LLM response;
        ``None`` for no-op heartbeats (server sends nothing back to client).
        """
        # 0. Coerce snapshot to dict first — Unity double-serialises scene_snapshot
        #    as a JSON string inside the outer JSON payload.  compute_diff requires a
        #    plain dict; passing a string causes character-level OBJECT_ADDED events
        #    on the first heartbeat and an AttributeError crash on every subsequent one.
        from core.memory.working_memory import WorkingMemory as _WM
        scene_snapshot = _WM._coerce_snapshot(scene_snapshot)
        if not isinstance(scene_snapshot, dict):
            logger.warning(
                "[Heartbeat] scene_snapshot could not be coerced to dict (got %s) — skipping.",
                type(scene_snapshot).__name__,
            )
            return None

        # 1. Diff the incoming full snapshot against current known state.
        changes = compute_diff(self.working_memory.scene, scene_snapshot)

        # 2. Always update working memory — even for no-op heartbeats
        self.working_memory.update_scene(scene_snapshot)

        # 3. Classify changes into typed events
        events = classify(changes)

        # 3b. Suppress events on objects the agent recently modified.
        # This prevents the feedback loop: agent adds sensor → OBJECT_ADDED fires
        # → LLM wakes → agent adds another sensor → …
        _now = time.monotonic()
        self._agent_touched = {obj: exp for obj, exp in self._agent_touched.items() if exp > _now}
        self._agent_added_sensor_prefixes = {
            prefix: exp for prefix, exp in self._agent_added_sensor_prefixes.items() if exp > _now
        }
        if self._agent_touched or self._agent_added_sensor_prefixes:
            _all_events = events[:]  # snapshot before filtering
            events = [e for e in events if not self._is_agent_originated_event(e)]
            _suppressed = len(_all_events) - len(events)
            if _suppressed:
                _suppressed_objs = [
                    e["object"] for e in _all_events if self._is_agent_originated_event(e)
                ]
                logger.debug(
                    "[Heartbeat] Suppressed %d agent-originated event(s) — objects: %s",
                    _suppressed, _suppressed_objs,
                )

        # 4. Record all non-NO_OP events in recent_events for future prompt context
        for ev in events:
            if ev["event_type"] != NO_OP:
                self.working_memory.add_event({
                    "summary": f"{ev['event_type']} on {ev['object']}",
                    "event": ev,
                })

        # 5. Attention gate — only wake the LLM for high-severity events
        significant = [e for e in events if e["severity"] >= ATTENTION_THRESHOLD]
        if not significant:
            logger.debug("[Heartbeat] No significant events — skipping LLM.")
            return None

        # 6. Cooldown gate — filter out objects still within the cooldown window
        if self._cfg.cooldown.enabled:
            now = time.monotonic()
            cooldown_s = self._cfg.cooldown.per_object_s
            significant = [
                e for e in significant
                if (now - self._last_trigger.get(e["object"], 0.0)) >= cooldown_s
            ]
            if not significant:
                logger.debug(
                    "[Heartbeat] All significant events are within cooldown window — skipping."
                )
                return None

        # 7. Mark trigger time for each significant object
        now = time.monotonic()
        for ev in significant:
            self._last_trigger[ev["object"]] = now

        # 8. Build a readable event summary for the LLM prompt
        event_summary = self._format_events(significant)
        logger.info("[Heartbeat] Triggering LLM for: %s", event_summary)

        # 9. Call LLM with event context
        await self.broadcaster.set_state(THINKING, detail="Reacting to scene event")

        prompt = (
            "[Scene event detected — you are proactively observing the environment]\n"
            f"{event_summary}\n\n"
            f"Current scene:\n{json.dumps(self.working_memory.scene, indent=2)}\n\n"
            "Briefly comment or take action if appropriate. "
            "If no action or comment is warranted, output an empty string."
        )

        try:
            try:
                reply_text = self.agent.send_message(prompt, persist=False)
            except TypeError:
                reply_text = self.agent.send_message(prompt)
        except Exception as exc:
            logger.error("[Heartbeat] LLM call failed: %s", exc)
            await self.broadcaster.set_state(IDLE)
            return None

        # 10. Parse LLM reply
        spoken_text, actions = ControlParser.extract(reply_text)
        control_output: list[dict] = []
        _touch_expiry = time.monotonic() + self._agent_action_suppression_s()
        for action_item in actions:
            tgt = action_item.get("target", "")
            result = SkillRegistry.dispatch(
                action=action_item.get("action", ""),
                target=tgt,
                parameters=action_item.get("parameters", {}),
            )
            control_output.append(result)
            # Record every target the agent touches so the next heartbeat diff
            # does not re-trigger the LLM on changes the agent itself caused.
            self._mark_agent_action_touched(action_item, _touch_expiry, source="heartbeat")

        # 11. If the LLM decided nothing needed saying, suppress the push
        if not spoken_text.strip() and not control_output:
            logger.debug("[Heartbeat] LLM produced empty response — suppressing push.")
            await self.broadcaster.set_state(IDLE)
            return None

        # 12. Optional TTS — generate audio if enabled in config
        audio_path: str | None = None
        if self._cfg.agent_push.tts_enabled and spoken_text.strip():
            try:
                audio_path = self._generate_tts(spoken_text.strip())
            except Exception as exc:
                logger.warning("[Heartbeat] TTS generation failed: %s", exc)
                # Non-fatal — push is still sent as text only

        await self.broadcaster.set_state(IDLE)

        # 13. Store the event-triggered interaction in episodic memory
        try:
            self.memory_manager.store_interaction(
                session_id=self.working_memory.session_id,
                user_input=f"[heartbeat] {event_summary}",
                agent_reply=spoken_text.strip(),
                scene_snapshot=self.working_memory.scene,
                control_actions=control_output,
            )
        except Exception as exc:
            logger.warning("[Heartbeat] Failed to store episode: %s", exc)

        triggered_by = [
            f"{ev['event_type']}:{ev['object']} (severity {ev['severity']:.1f})"
            for ev in significant
        ]
        push: dict = {
            "type":         "agent_push",
            "trigger":      significant[0]["event_type"],
            "reply":        spoken_text.strip(),
            "triggered_by": triggered_by,
            "control":      {"actions": control_output},
        }
        if audio_path is not None:
            push["audio_path"] = audio_path

        return push

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _agent_action_suppression_s(self) -> float:
        return max(float(self._cfg.cooldown.per_object_s), 60.0)

    def _mark_agent_action_touched(self, action_item: dict, expiry: float, *, source: str) -> None:
        action = (action_item or {}).get("action", "")
        target = (action_item or {}).get("target", "")
        if target:
            self._agent_touched[target] = expiry
            logger.debug(
                "[Heartbeat] Marked '%s' as agent-touched (%s, suppressed for %.0fs).",
                target,
                source,
                self._cfg.cooldown.per_object_s,
            )

        if action != "set_sensor":
            return

        params = (action_item or {}).get("parameters") or {}
        sensor_type = str(params.get("sensor_type") or "").strip().upper()
        if not sensor_type:
            return

        self._agent_added_sensor_prefixes[sensor_type] = expiry
        logger.debug(
            "[Heartbeat] Marked sensor prefix '%s' as agent-created (%s, suppressed for %.0fs).",
            sensor_type,
            source,
            self._cfg.cooldown.per_object_s,
        )

    def _is_agent_originated_event(self, event: dict) -> bool:
        obj = event.get("object", "")
        if obj in self._agent_touched:
            return True

        if event.get("event_type") != OBJECT_ADDED:
            return False

        obj_upper = str(obj).upper()
        return any(
            obj_upper == prefix or obj_upper.startswith(f"{prefix}-")
            for prefix in self._agent_added_sensor_prefixes
        )

    def _generate_tts(self, text: str) -> str:
        """Generate TTS audio via OpenAI and return the absolute path."""
        _AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(_AUDIO_OUT_DIR / f"push_audio_{stamp}.mp3")
        # Honour the configured voice; fall back to agent default if the method
        # doesn't accept a voice parameter.
        try:
            self.agent.speak_text(
                text,
                output_path=out_path,
                voice=self._cfg.agent_push.tts_voice,
            )
        except TypeError:
            # VsensOpenAI.speak_text may not accept 'voice' yet — call without it
            self.agent.speak_text(text, output_path=out_path)
        return out_path

    @staticmethod
    def _format_events(events: list[dict]) -> str:
        """
        Build a compact human-readable event summary for the LLM prompt.

        Example output:
            "Event: SENSOR_TRIGGER on OPTICAL-01 (value 0→1).
             Event: STATE_CHANGE on Window_A (state open→closed)."
        """
        lines: list[str] = []
        for ev in events:
            obj  = ev["object"]
            et   = ev["event_type"]
            data = ev.get("data", {})
            f    = data.get("field", "")

            if f == "sensor.value":
                detail = f"value {data.get('old')}→{data.get('new')}"
            elif f == "state":
                detail = f"state {data.get('old')}→{data.get('new')}"
            elif f == "position":
                detail = f"moved {data.get('delta_m', 0):.2f}m"
            else:
                detail = data.get("change_type", "")

            lines.append(f"Event: {et} on {obj} ({detail}).")

        return "\n".join(lines)
