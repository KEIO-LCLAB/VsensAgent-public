"""
test_phase3.py — Phase 3 integration test (Heartbeat / Proactive Perception)

Run from VsensPython/:
    python test_phase3.py

All tests are pure-Python unit tests that do NOT require a running server,
LLM API key, or WebSocket connection.  The checklists that require a live
server are documented at the bottom under "Manual / Live Tests".
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# P3-T1 — SceneDiff unit tests
# ---------------------------------------------------------------------------

from core.perception.scene_diff import compute_diff, as_text


class TestSceneDiff(unittest.TestCase):

    def _make_optical(self, name: str, value: int) -> dict:
        return {
            "position": [1, 1, 1],
            "size": [0.1, 0.1, 0.1],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
            "properties": ["sensor", "movable"],
            "attachTo": "Wall_A",
            "sensor": {"sensorType": "OPTICAL", "value": value},
        }

    def _make_distance(self, name: str, value: float) -> dict:
        return {
            "position": [2, 1, 1],
            "properties": ["sensor"],
            "sensor": {"sensorType": "DISTANCE", "value": value, "validDistance": 5.0},
        }

    def _make_stateful(self, state: str) -> dict:
        return {
            "position": [0, 0, 0],
            "properties": ["with_state"],
            "state": state,
            "availableStates": ["open", "closed"],
        }

    def _make_user(self, position: list) -> dict:
        return {"position": position, "properties": []}

    # --- OPTICAL binary change ---

    def test_optical_binary_change(self):
        old = {"OPTICAL-01": self._make_optical("OPTICAL-01", 0)}
        new = {"OPTICAL-01": self._make_optical("OPTICAL-01", 1)}
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        c = changes[0]
        self.assertEqual(c["object"], "OPTICAL-01")
        self.assertEqual(c["field"], "sensor.value")
        self.assertTrue(c["is_binary"])
        self.assertEqual(c["old"], 0)
        self.assertEqual(c["new"], 1)

    # --- No change on identical snapshots ---

    def test_identical_snapshots_returns_empty(self):
        snap = {"OPTICAL-01": self._make_optical("OPTICAL-01", 0)}
        changes = compute_diff(snap, copy.deepcopy(snap))
        self.assertEqual(changes, [])

    # --- State change ---

    def test_state_change(self):
        old = {"Window_A": self._make_stateful("open")}
        new = {"Window_A": self._make_stateful("closed")}
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        c = changes[0]
        self.assertEqual(c["field"], "state")
        self.assertEqual(c["old"], "open")
        self.assertEqual(c["new"], "closed")

    # --- Both sensor and state change in one diff ---

    def test_sensor_and_state_change(self):
        old = {
            "OPTICAL-01": self._make_optical("OPTICAL-01", 0),
            "Window_A":   self._make_stateful("open"),
        }
        new = {
            "OPTICAL-01": self._make_optical("OPTICAL-01", 1),
            "Window_A":   self._make_stateful("closed"),
        }
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 2)

    # --- Object added / removed ---

    def test_object_added(self):
        old = {}
        new = {"Box_1": self._make_stateful("open")}
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "object_added")

    def test_object_removed(self):
        old = {"Box_1": self._make_stateful("open")}
        new = {}
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "object_removed")

    # --- User proximity ---

    def test_user_position_delta(self):
        old = {"user": self._make_user([0, 0, 0])}
        new = {"user": self._make_user([0, 0, 0.5])}   # 0.5 m delta
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        c = changes[0]
        self.assertEqual(c["field"], "position")
        self.assertAlmostEqual(c["delta_m"], 0.5, places=2)

    # --- Continuous sensor threshold ---

    def test_continuous_sensor_below_threshold_no_change(self):
        old = {"DIST-01": self._make_distance("DIST-01", 2.0)}
        new = {"DIST-01": self._make_distance("DIST-01", 2.05)}  # 0.05 < 0.10 abs
        changes = compute_diff(old, new)
        # Should produce no changes (below both abs and rel thresholds)
        self.assertEqual(changes, [])

    def test_continuous_sensor_above_abs_threshold(self):
        old = {"DIST-01": self._make_distance("DIST-01", 2.0)}
        new = {"DIST-01": self._make_distance("DIST-01", 2.5)}   # 0.5 > 0.10
        changes = compute_diff(old, new)
        self.assertEqual(len(changes), 1)
        self.assertFalse(changes[0]["is_binary"])

    # --- as_text helper ---

    def test_as_text_formats_correctly(self):
        changes = [
            {"object": "OPTICAL-01", "field": "sensor.value", "old": 0, "new": 1,
             "delta": 1.0, "is_binary": True},
            {"object": "Window_A", "field": "state", "old": "open", "new": "closed"},
        ]
        text = as_text(changes)
        self.assertIn("OPTICAL-01", text)
        self.assertIn("0→1", text)
        self.assertIn("Window_A", text)
        self.assertIn("open→closed", text)

    def test_as_text_empty_returns_no_changes(self):
        self.assertEqual(as_text([]), "[no changes]")


# ---------------------------------------------------------------------------
# P3-T2 — EventClassifier unit tests
# ---------------------------------------------------------------------------

from core.perception.event_classifier import (
    classify,
    ATTENTION_THRESHOLD,
    SENSOR_TRIGGER, SENSOR_ANOMALY, STATE_CHANGE, USER_PROXIMITY,
    OBJECT_ADDED, OBJECT_REMOVED, NO_OP,
)


class TestEventClassifier(unittest.TestCase):

    def test_optical_trigger_severity(self):
        changes = [{
            "object": "OPTICAL-01", "field": "sensor.value",
            "old": 0, "new": 1, "delta": 1.0, "is_binary": True,
        }]
        events = classify(changes)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], SENSOR_TRIGGER)
        self.assertGreaterEqual(events[0]["severity"], ATTENTION_THRESHOLD)

    def test_user_proximity_below_threshold(self):
        changes = [{
            "object": "user", "field": "position",
            "old": [0, 0, 0], "new": [0, 0, 0.3], "delta_m": 0.3,
        }]
        events = classify(changes)
        # 0.3m < 0.5m threshold — should be NO_OP
        non_noop = [e for e in events if e["event_type"] != NO_OP]
        self.assertEqual(len(non_noop), 0)

    def test_user_proximity_above_threshold(self):
        changes = [{
            "object": "user", "field": "position",
            "old": [0, 0, 0], "new": [0, 0, 0.6], "delta_m": 0.6,
        }]
        events = classify(changes)
        ue = [e for e in events if e["event_type"] == USER_PROXIMITY]
        self.assertEqual(len(ue), 1)
        self.assertLess(ue[0]["severity"], ATTENTION_THRESHOLD)  # informational only

    def test_state_change_above_threshold(self):
        changes = [{"object": "Door_A", "field": "state", "old": "open", "new": "closed"}]
        events = classify(changes)
        sc = [e for e in events if e["event_type"] == STATE_CHANGE]
        self.assertEqual(len(sc), 1)
        self.assertGreaterEqual(sc[0]["severity"], ATTENTION_THRESHOLD)

    def test_continuous_anomaly_upgrade(self):
        # A 100% relative jump should be upgraded to SENSOR_ANOMALY
        changes = [{
            "object": "DIST-01", "field": "sensor.value",
            "old": 2.0, "new": 4.5, "delta": 2.5, "is_binary": False,
        }]
        events = classify(changes)
        self.assertEqual(events[0]["event_type"], SENSOR_ANOMALY)

    def test_empty_changes_returns_noop(self):
        events = classify([])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], NO_OP)
        self.assertEqual(events[0]["severity"], 0.0)

    def test_mixed_events_sensor_and_user(self):
        """OPTICAL 0→1 + user moved 0.3m → only SENSOR_TRIGGER is significant."""
        changes = [
            {"object": "OPTICAL-01", "field": "sensor.value",
             "old": 0, "new": 1, "delta": 1.0, "is_binary": True},
            {"object": "user", "field": "position",
             "old": [0, 0, 0], "new": [0, 0, 0.3], "delta_m": 0.3},
        ]
        events = classify(changes)
        significant = [e for e in events if e["severity"] >= ATTENTION_THRESHOLD]
        self.assertEqual(len(significant), 1)
        self.assertEqual(significant[0]["event_type"], SENSOR_TRIGGER)


# ---------------------------------------------------------------------------
# P3-T3 — HeartbeatHandler unit tests (mocked LLM)
# ---------------------------------------------------------------------------

from core.perception.heartbeat_handler import HeartbeatHandler
from core.memory.working_memory import WorkingMemory


class TestWorkingMemory(unittest.TestCase):
    def test_update_scene_replaces_full_snapshot_and_removes_missing_objects(self):
        wm = WorkingMemory()
        wm.replace_scene({
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "IMU-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        })

        wm.update_scene({
            "Door_A": {"properties": ["with_state"], "state": "closed"},
        })

        self.assertIn("IMU-01", wm.last_scene)
        self.assertNotIn("IMU-01", wm.scene)

    def test_update_scene_replaces_json_string_snapshot(self):
        wm = WorkingMemory()
        wm.replace_scene({
            "IMU-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        })

        wm.update_scene(json.dumps({
            "DISTANCE-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        }))

        self.assertNotIn("IMU-01", wm.scene)
        self.assertIn("DISTANCE-01", wm.scene)


class TestHeartbeatHandler(unittest.IsolatedAsyncioTestCase):

    def _make_optical_obj(self, value):
        return {
            "position": [1, 1, 1],
            "properties": ["sensor"],
            "sensor": {"sensorType": "OPTICAL", "value": value},
        }

    def _build_handler(self, llm_reply: str = "I noticed a presence detected."):
        wm = WorkingMemory()
        # Prime last_scene with value=0
        wm.last_scene = {"OPTICAL-01": self._make_optical_obj(0)}
        wm.scene     = {"OPTICAL-01": self._make_optical_obj(0)}

        mock_agent = MagicMock()
        mock_agent.send_message.return_value = llm_reply

        mock_broadcaster = AsyncMock()
        mock_broadcaster.set_state = AsyncMock()

        mock_broadcast_fn = AsyncMock()

        mock_memory_manager = MagicMock()
        mock_memory_manager.store_interaction.return_value = None

        handler = HeartbeatHandler(
            working_memory=wm,
            memory_manager=mock_memory_manager,
            agent=mock_agent,
            broadcaster=mock_broadcaster,
            broadcast_fn=mock_broadcast_fn,
        )
        return handler, wm, mock_agent, mock_broadcast_fn

    def _build_history_tracking_handler(self, llm_reply: str = "I noticed a presence detected."):
        handler, wm, _, mock_broadcast_fn = self._build_handler(llm_reply=llm_reply)

        class HistoryTrackingAgent:
            def __init__(self, reply):
                self.reply = reply
                self.calls = []

            def send_message(self, user_input, persist=True):
                self.calls.append({"user_input": user_input, "persist": persist})
                return self.reply

        agent = HistoryTrackingAgent(llm_reply)
        handler.agent = agent
        return handler, wm, agent, mock_broadcast_fn

    async def test_significant_event_returns_push(self):
        """OPTICAL 0→1 should return a non-None agent_push dict."""
        handler, wm, mock_agent, _ = self._build_handler()
        new_snap = {"OPTICAL-01": self._make_optical_obj(1)}
        result = await handler.handle(new_snap)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "agent_push")
        self.assertEqual(result["trigger"], SENSOR_TRIGGER)
        self.assertIn("presence", result["reply"].lower())

    async def test_heartbeat_llm_call_does_not_persist_full_scene_history(self):
        handler, wm, agent, _ = self._build_history_tracking_handler()
        new_snap = {"OPTICAL-01": self._make_optical_obj(1)}

        result = await handler.handle(new_snap)

        self.assertIsNotNone(result)
        self.assertEqual(agent.calls[0]["persist"], False)

    async def test_agent_touch_window_covers_delayed_scene_effects(self):
        handler, _, _, _ = self._build_handler()

        self.assertGreaterEqual(handler._agent_action_suppression_s(), 60.0)

    async def test_no_op_returns_none(self):
        """Heartbeat with identical scene should return None (no LLM call)."""
        handler, wm, mock_agent, _ = self._build_handler()
        same_snap = {"OPTICAL-01": self._make_optical_obj(0)}
        result = await handler.handle(same_snap)
        self.assertIsNone(result)
        mock_agent.send_message.assert_not_called()

    async def test_empty_llm_response_suppresses_push(self):
        """If LLM returns empty string, no agent_push should be sent."""
        handler, wm, mock_agent, _ = self._build_handler(llm_reply="")
        new_snap = {"OPTICAL-01": self._make_optical_obj(1)}
        result = await handler.handle(new_snap)
        self.assertIsNone(result)

    async def test_working_memory_updated_on_every_heartbeat(self):
        """Scene should always be updated, even for no-op heartbeats."""
        handler, wm, mock_agent, _ = self._build_handler()
        new_snap = {"OPTICAL-01": self._make_optical_obj(0), "NewBox": {"position": [5,0,0]}}
        await handler.handle(new_snap)
        self.assertIn("NewBox", wm.scene)

    async def test_deleted_sensor_does_not_remain_in_heartbeat_scene_context(self):
        handler, wm, mock_agent, _ = self._build_handler()
        wm.scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "IMU-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        }
        wm.last_scene = copy.deepcopy(wm.scene)

        result = await handler.handle({
            "Door_A": {"properties": ["with_state"], "state": "closed"},
        })

        self.assertIsNotNone(result)
        self.assertNotIn("IMU-01", wm.scene)
        prompt = mock_agent.send_message.call_args.args[0]
        current_scene = prompt.split("Current scene:\n", 1)[1]
        self.assertNotIn("IMU-01", current_scene)

    async def test_agent_touch_suppresses_object_added_loop(self):
        """
        If the agent adds/modifies an object, the next heartbeat showing that
        object as OBJECT_ADDED must be suppressed (no LLM wakeup).
        """
        handler, wm, mock_agent, _ = self._build_handler()
        # Simulate agent having just added "Sensor_New" via a control action
        handler._agent_touched["Sensor_New"] = time.monotonic() + 30.0

        # Next heartbeat: scene now contains the new sensor (OBJECT_ADDED diff)
        wm.last_scene = {"OPTICAL-01": self._make_optical_obj(0)}
        new_snap = {
            "OPTICAL-01": self._make_optical_obj(0),
            "Sensor_New":  self._make_optical_obj(0),  # agent just placed this
        }
        result = await handler.handle(new_snap)
        # Should be suppressed — LLM must NOT be called
        self.assertIsNone(result)
        mock_agent.send_message.assert_not_called()

    async def test_agent_touch_suppresses_removed_sensor_loop(self):
        handler, wm, mock_agent, _ = self._build_handler()
        wm.scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "IMU-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        }
        wm.last_scene = copy.deepcopy(wm.scene)

        handler.mark_agent_touched(
            ["IMU-01"],
            actions=[{"target": "IMU-01", "action": "remove_sensor", "parameters": {}}],
        )

        result = await handler.handle({
            "Door_A": {"properties": ["with_state"], "state": "closed"},
        })

        self.assertIsNone(result)
        self.assertNotIn("IMU-01", wm.scene)
        mock_agent.send_message.assert_not_called()

    async def test_agent_touch_suppresses_auto_named_sensor_added_loop(self):
        handler, wm, mock_agent, _ = self._build_handler()
        handler.mark_agent_touched(
            [],
            actions=[{"target": "", "action": "set_sensor", "parameters": {"sensor_type": "DISTANCE"}}],
        )

        result = await handler.handle({
            "OPTICAL-01": self._make_optical_obj(0),
            "DISTANCE-01": {
                "position": [1, 1, 1],
                "properties": ["sensor"],
                "sensor": {"sensorType": "DISTANCE", "value": 2.0},
            },
        })

        self.assertIsNone(result)
        self.assertIn("DISTANCE-01", wm.scene)
        mock_agent.send_message.assert_not_called()

    async def test_agent_touch_suppresses_state_change_loop(self):
        """
        If the agent changed an object's state, the resulting STATE_CHANGE
        in the next heartbeat must be suppressed.
        """
        handler, wm, mock_agent, _ = self._build_handler()
        wm.last_scene = {"Door_A": {"state": "closed", "properties": ["with_state"]}}
        wm.scene      = {"Door_A": {"state": "closed", "properties": ["with_state"]}}

        # Simulate agent having just issued set_state on Door_A
        handler._agent_touched["Door_A"] = time.monotonic() + 30.0

        new_snap = {"Door_A": {"state": "open", "properties": ["with_state"]}}
        result = await handler.handle(new_snap)
        self.assertIsNone(result)
        mock_agent.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# P3-T5 — AgentCore diff prompt test (mocked)
# ---------------------------------------------------------------------------

from core.agent_core import AgentCore


class TestAgentCoreDiffPrompt(unittest.TestCase):

    def _make_mini_agent_core(self):
        """Build a minimal AgentCore with mocked subsystems."""
        mock_agent = MagicMock()
        mock_agent.client = MagicMock()
        mock_agent.send_message.return_value = "All good."
        mock_agent.reset_conversation.return_value = None

        mock_broadcaster = MagicMock()
        mock_broadcaster.set_state = AsyncMock()
        mock_broadcaster.reset = AsyncMock()

        mock_episodic = MagicMock()
        mock_episodic.store.return_value = None
        mock_episodic.retrieve.return_value = []
        mock_episodic.count.return_value = 0

        mock_semantic = MagicMock()
        mock_semantic.get.return_value = None
        mock_semantic.as_text.return_value = ""

        core = AgentCore(
            agent=mock_agent,
            broadcaster=mock_broadcaster,
            episodic=mock_episodic,
            semantic=mock_semantic,
        )
        return core

    def test_first_call_sends_full_scene(self):
        """When last_scene is empty, prompt should contain full scene JSON."""
        core = self._make_mini_agent_core()
        scene = {"Window_A": {"position": [1, 2, 3], "state": "open",
                               "properties": ["with_state"]}}
        core.memory.scene = scene
        core.memory_manager.build_context = MagicMock(return_value="")
        core.memory.last_scene = {}

        prompt = core._build_prompt("check the window")
        self.assertIn("Window_A", prompt)
        self.assertIn("Current scene", prompt)

    def test_second_call_includes_current_scene_and_diff(self):
        """After a scene update, prompt should contain current scene plus diff text."""
        core = self._make_mini_agent_core()

        # Simulate first scene
        first_scene = {"Window_A": {"properties": ["with_state"], "state": "open"}}
        core.memory.replace_scene(first_scene)

        # Simulate second scene (state changed)
        second_scene = {"Window_A": {"properties": ["with_state"], "state": "closed"}}
        core.memory.update_scene(second_scene)

        core.memory_manager.get_filtered_scene = MagicMock(return_value=second_scene)
        core.memory_manager.build_context = MagicMock(return_value="")

        prompt = core._build_prompt("what changed?")
        self.assertIn("Current scene", prompt)
        self.assertIn("Window_A", prompt)
        self.assertIn('"state": "closed"', prompt)
        self.assertIn("Scene changes", prompt)
        self.assertIn("open→closed", prompt)

    def test_removed_sensor_is_reported_as_diff_without_stale_scene(self):
        core = self._make_mini_agent_core()
        first_scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "IMU-01": {"properties": ["sensor"], "attachTo": "Door_A"},
        }
        second_scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
        }
        core.memory.replace_scene(first_scene)
        core.memory.update_scene(second_scene)

        core.memory_manager.build_context = MagicMock(return_value="")
        prompt = core._build_prompt("what changed?")

        self.assertIn("IMU-01: removed from scene.", prompt)
        self.assertNotIn("unchanged", prompt.lower())
        self.assertNotIn('"attachTo": "Door_A"', prompt)

    def test_unchanged_scene_prompt(self):
        """Identical consecutive scenes → '[Scene unchanged]' in prompt."""
        core = self._make_mini_agent_core()
        scene = {"Window_A": {"properties": ["with_state"], "state": "open"}}
        core.memory.replace_scene(scene)
        core.memory.update_scene(copy.deepcopy(scene))

        core.memory_manager.build_context = MagicMock(return_value="")
        prompt = core._build_prompt("any updates?")
        self.assertIn("unchanged", prompt.lower())

    def test_reset_clears_last_scene(self):
        """After reset(), last_scene should be empty so next call sends full scene."""
        core = self._make_mini_agent_core()
        core.memory.replace_scene({"A": {"state": "x", "properties": []}})
        core.reset()
        self.assertEqual(core.memory.last_scene, {})


# ---------------------------------------------------------------------------
# MANUAL / LIVE TEST CHECKLIST (requires running server)
# ---------------------------------------------------------------------------
#
# Start the server: python main.py
# Then connect a WebSocket client and run these checks manually:
#
# □ scene_heartbeat with no changes   → server sends nothing back
# □ scene_heartbeat with OPTICAL 0→1  → server broadcasts agent_push to all clients
# □ agent_status "thinking" visible in monitor_gui during heartbeat-triggered LLM call
# □ Second text_chat prompt contains "[Scene changes since ...]" not full JSON
#   (verify by enabling prompt logging in vsens_openai.py or monitor_gui)
# □ Token count for second text_chat is lower than first (check monitor_gui)
# □ All Phase 1 and Phase 2 functionality still works
#
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 3 — Heartbeat / Proactive Perception — Unit Tests")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestSceneDiff))
    suite.addTests(loader.loadTestsFromTestCase(TestEventClassifier))
    suite.addTests(loader.loadTestsFromTestCase(TestHeartbeatHandler))
    suite.addTests(loader.loadTestsFromTestCase(TestAgentCoreDiffPrompt))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
