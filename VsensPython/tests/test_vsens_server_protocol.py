import asyncio
import json
import shutil
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from datetime import datetime

from core.jobs.job_manager import JobManager
from core.delegation.workspace import DelegatedTaskWorkspaceManager
from core.protocol.user_turns import (
    build_clarification_reply_turn,
    build_proposal_select_turn,
)
from vsens_server import VsensWebSocketServer


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


class TestVsensWebSocketServerProtocol(unittest.IsolatedAsyncioTestCase):
    def _make_server(self):
        tmp_root = Path(__file__).resolve().parent / "_tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        recording_root = tmp_root / f"recording_protocol_test_{uuid.uuid4().hex[:8]}"
        unity_root = tmp_root / f"unity_action_protocol_test_{uuid.uuid4().hex[:8]}"
        workspace_root = tmp_root / f"delegated_workspace_protocol_test_{uuid.uuid4().hex[:8]}"
        recording_root.mkdir(parents=True, exist_ok=True)
        unity_root.mkdir(parents=True, exist_ok=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(recording_root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(unity_root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(workspace_root, ignore_errors=True))
        server = VsensWebSocketServer.__new__(VsensWebSocketServer)
        server.agent_core = MagicMock()
        server.agent_core.handle_text = AsyncMock(
            return_value={"type": "conversation.reply", "reply": "ok"}
        )
        server.job_manager = JobManager()
        server._active_task = None
        server._pending_queries = {}
        server._recording_storage_root = recording_root
        server._unity_action_log_root = unity_root
        server._delegated_task_workspace_manager = DelegatedTaskWorkspaceManager(root=workspace_root)
        server.handlers = {
            "client.hello": server._handle_client_hello,
            "clarification.reply": server._handle_clarification_reply,
            "proposal.select": server._handle_proposal_select,
            "job.start": server._handle_job_start,
            "job.status": server._handle_job_status,
            "job.cancel": server._handle_job_cancel,
            "sensor.recording_snapshot": server._handle_sensor_recording_snapshot,
            "task.start": server._handle_delegated_task_start,
            "unity.scene_action": server._handle_unity_scene_action,
            "object_selection.reply": server._handle_object_selection_reply,
        }
        server._delegated_task_runner = MagicMock()
        return server

    def test_server_configures_websocket_message_size_for_recording_snapshots(self):
        server = VsensWebSocketServer(host="localhost", port=8765)

        self.assertGreaterEqual(server.websocket_max_size_bytes, 8 * 1024 * 1024)

    async def test_start_passes_websocket_message_size_to_serve(self):
        server = self._make_server()
        server.host = "localhost"
        server.port = 8765
        server.websocket_max_size_bytes = 9 * 1024 * 1024
        captured = {}

        class _FakeServeContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _StopFuture:
            def __await__(self):
                raise RuntimeError("stop test server")
                yield

        def fake_serve(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _FakeServeContext()

        with patch("vsens_server.websockets.serve", side_effect=fake_serve), patch(
            "vsens_server.asyncio.Future",
            side_effect=lambda: _StopFuture(),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop test server"):
                await server.start()

        self.assertEqual(captured["kwargs"]["max_size"], server.websocket_max_size_bytes)

    async def test_process_message_routes_client_hello_and_returns_ack(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_1"
        session.connected_at_iso = "2026-04-18T10:00:00"
        session.transcript = MagicMock()
        session.unity_action_log = MagicMock()
        payload = {
            "type": "client.hello",
            "username": "alice",
            "us": "lab_a",
        }

        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "client.hello_ack")
        self.assertEqual(result["client_id"], "client_1")
        self.assertEqual(result["username"], "alice")
        self.assertEqual(result["us"], "lab_a")
        self.assertEqual(session.username, "alice")
        self.assertEqual(session.us, "lab_a")
        session.unity_action_log.configure_identity.assert_called_once_with(username="alice", us="lab_a")

    async def test_process_message_routes_clarification_reply(self):
        server = self._make_server()
        payload = {
            "type": "clarification.reply",
            "question_id": "q_1",
            "selected_ids": ["coffee_maker"],
            "free_text": "Near the sink",
            "scene_snapshot": {"room": "kitchen"},
        }

        result = await server.process_message(json.dumps(payload))

        self.assertEqual(result["type"], "conversation.reply")
        server.agent_core.handle_text.assert_awaited_once_with(
            build_clarification_reply_turn(
                question_id="q_1",
                selected_ids=["coffee_maker"],
                free_text="Near the sink",
            ),
            {"room": "kitchen"},
        )

    async def test_process_message_routes_proposal_select(self):
        server = self._make_server()
        payload = {
            "type": "proposal.select",
            "proposal_id": "prop_1",
            "selected_option_ids": ["cand_1"],
            "note": "Prefer easier wiring",
            "scene_snapshot": {"room": "kitchen"},
        }

        result = await server.process_message(json.dumps(payload))

        self.assertEqual(result["type"], "conversation.reply")
        server.agent_core.handle_text.assert_awaited_once_with(
            build_proposal_select_turn(
                proposal_id="prop_1",
                selected_option_ids=["cand_1"],
                note="Prefer easier wiring",
            ),
            {"room": "kitchen"},
        )

    async def test_object_selection_reply_resolves_pending_waiter(self):
        server = self._make_server()
        session = MagicMock()
        future = asyncio.get_running_loop().create_future()
        session._pending_object_selections = {"sel_1": future}
        session.transcript = MagicMock()

        result = await server._handle_object_selection_reply(
            {
                "type": "object_selection.reply",
                "selection_id": "sel_1",
                "selected_object_id": "obj_stove",
                "selected_alias": "Stove",
                "world_position": [1.0, 0.5, 2.0],
                "cancelled": False,
            },
            session=session,
        )

        self.assertIsNone(result)
        self.assertTrue(future.done())
        self.assertEqual(future.result()["selected_alias"], "Stove")
        self.assertEqual(session._pending_object_selections, {})

    async def test_agent_experiment_reply_requests_confirmation_before_starting_job(self):
        server = self._make_server()
        websocket = _FakeWebSocket()
        session = MagicMock()
        session.client_id = "client_exp"
        session.username = "kba"
        session.us = "0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session._active_task = None
        session._pending_queries = {}
        session._experiment_task = None
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {
            "Stove": {"position": [1.6, 0.5, -0.3], "size": [0.6, 0.9, 0.8]},
            "Sink": {"position": [1.6, 0.9, 1.4], "size": [0.5, 0.2, 0.7]},
        }
        session.agent_core.handle_text = AsyncMock(
            return_value={
                "type": "conversation.reply",
                "reply": "I will run a phased cooking-vs-washing collection.",
                "control": {"actions": []},
                "experiment": {
                    "goal": "distinguish cooking from washing dishes",
                    "requires_avatar": True,
                    "setup_actions": [],
                    "recording": {"sensors": ["DISTANCE-01"], "auto_upload": True},
                    "phases": [
                        {"label": "cooking", "duration_s": 0.01},
                        {"label": "washing_dishes", "duration_s": 0.01},
                    ],
                    "repeat": 1,
                    "analysis": {"run_after": True, "goal": "find a threshold"},
                },
            }
        )
        server._execute_scene_query = AsyncMock(
            side_effect=lambda _session, _websocket, query_request: (
                {
                    "type": "scene.query_response",
                    "request_id": query_request["request_id"],
                    "scene_version": 6,
                }
                if query_request["type"] == "scene.query_summary"
                else {
                    "type": "scene.execute_actions_response",
                    "request_id": query_request["request_id"],
                    "status": "success",
                    "scene_version_after": 6,
                }
            )
        )
        server._wait_for_next_recording_snapshot = AsyncMock(
            return_value={
                "timestamp_label": "kba_0_20260616_160000",
                "saved_directory": "/tmp/recording",
                "saved_files": ["DISTANCE-01_DISTANCE.csv"],
            }
        )
        server._run_experiment_analysis = AsyncMock(
            return_value={"reply": "Candidate threshold is 2.1m."}
        )

        await server._run_handler_and_reply(
            server._handle_text_chat,
            {"type": "conversation.ask", "message": "collect data", "scene_snapshot": {}},
            websocket,
            session,
        )

        self.assertIsNone(session._experiment_task)
        self.assertEqual([message["type"] for message in websocket.sent], [
            "conversation.reply",
            "clarification.request",
        ])
        confirmation = websocket.sent[-1]
        self.assertTrue(confirmation["question_id"].startswith("experiment_confirm:"))
        self.assertIn("distinguish cooking from washing dishes", confirmation["prompt"])
        self.assertIn("cooking", confirmation["prompt"])
        self.assertEqual(confirmation["options"][0]["id"], "run_experiment")
        self.assertEqual(confirmation["options"][1]["id"], "cancel_experiment")
        self.assertIn(confirmation["question_id"], session._pending_experiment_confirmations)
        server._execute_scene_query.assert_not_awaited()

    async def test_experiment_confirmation_reply_starts_background_experiment_job(self):
        server = self._make_server()
        websocket = _FakeWebSocket()
        session = MagicMock()
        session.client_id = "client_exp"
        session.username = "kba"
        session.us = "0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session._active_task = None
        session._pending_queries = {}
        session._experiment_task = None
        session._recording_snapshot_waiters = []
        session._pending_experiment_confirmations = {
            "experiment_confirm:exp_1": {
                "reply": {
                    "type": "conversation.reply",
                    "reply": "I will run a phased cooking-vs-washing collection.",
                    "control": {"actions": []},
                },
                "experiment": {
                    "goal": "distinguish cooking from washing dishes",
                    "requires_avatar": True,
                    "setup_actions": [],
                    "recording": {"sensors": ["DISTANCE-01"], "auto_upload": True},
                    "phases": [
                        {"label": "cooking", "duration_s": 0.01},
                        {"label": "washing_dishes", "duration_s": 0.01},
                    ],
                    "repeat": 1,
                    "analysis": {"run_after": True, "goal": "find a threshold"},
                },
            }
        }
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {
            "Stove": {"position": [1.6, 0.5, -0.3], "size": [0.6, 0.9, 0.8]},
            "Sink": {"position": [1.6, 0.9, 1.4], "size": [0.5, 0.2, 0.7]},
        }
        server._execute_scene_query = AsyncMock(
            side_effect=lambda _session, _websocket, query_request: (
                {
                    "type": "scene.query_response",
                    "request_id": query_request["request_id"],
                    "scene_version": 6,
                }
                if query_request["type"] == "scene.query_summary"
                else {
                    "type": "scene.execute_actions_response",
                    "request_id": query_request["request_id"],
                    "status": "success",
                    "scene_version_after": 6,
                }
            )
        )
        server._wait_for_next_recording_snapshot = AsyncMock(
            return_value={
                "timestamp_label": "kba_0_20260616_160000",
                "saved_directory": "/tmp/recording",
                "saved_files": ["DISTANCE-01_DISTANCE.csv"],
            }
        )
        server._run_experiment_analysis = AsyncMock(
            return_value={"reply": "Candidate threshold is 2.1m."}
        )

        result = await server._handle_clarification_reply(
            {
                "type": "clarification.reply",
                "question_id": "experiment_confirm:exp_1",
                "selected_ids": ["run_experiment"],
            },
            websocket=websocket,
            session=session,
        )

        self.assertIsNone(result)
        self.assertIsNotNone(session._experiment_task)
        await session._experiment_task
        sent_types = [message["type"] for message in websocket.sent]
        self.assertEqual(sent_types[0], "job.started")
        self.assertIn("job.started", sent_types)
        self.assertIn("job.completed", sent_types)
        self.assertEqual(sent_types[-1], "conversation.reply")
        self.assertEqual(websocket.sent[-1]["reply"], "Candidate threshold is 2.1m.")
        sent_actions = [
            action["action_type"]
            for call in server._execute_scene_query.await_args_list
            if call.args[2]["type"] == "scene.execute_actions"
            for action in call.args[2]["actions"]
        ]
        self.assertEqual(sent_actions[0], "start_sensor_recording")
        self.assertIn("mark_recording_phase", sent_actions)
        self.assertEqual(sent_actions[-1], "stop_sensor_recording")
        self.assertEqual(session._pending_experiment_confirmations, {})
        status_details = [call.kwargs.get("detail") for call in session.broadcaster.set_state.await_args_list]
        self.assertIn("Running experiment: distinguish cooking from washing dishes", status_details[0])

    async def test_experiment_job_normalizes_pseudo_avatar_imu_setup_actions(self):
        server = self._make_server()
        websocket = _FakeWebSocket()
        session = MagicMock()
        session.client_id = "client_exp_pseudo"
        session.username = "kba"
        session.us = "0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session._active_task = None
        session._pending_queries = {}
        session._experiment_task = None
        session._recording_snapshot_waiters = []
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {
            "CoffeeMaker": {"position": [1.0, 0.0, 2.0]},
            "Sink": {"position": [2.0, 0.0, 3.0]},
        }
        session._pending_experiment_confirmations = {
            "experiment_confirm:exp_pseudo": {
                "reply": {"type": "conversation.reply", "reply": "Plan ready."},
                "experiment": {
                    "goal": "IMU HAR for coffee vs dishes",
                    "actor_mode": "avatar",
                    "requires_avatar": True,
                    "setup_actions": [
                        {"action": "ensure_avatar", "target": "avatar_main", "parameters": {"prefab_key": "smplx_male"}},
                        {"action": "attach_imu", "target": "IMU-01", "parameters": {"joint_name": "right_wrist"}},
                        {"action": "attach_imu", "target": "IMU-02", "parameters": {"joint_name": "waist"}},
                    ],
                    "recording": {"sensors": ["IMU-01", "IMU-02"], "auto_upload": False},
                    "phases": [
                        {"label": "making_coffee", "duration_s": 0.01, "target_alias": "CoffeeMaker"},
                        {"label": "washing_dishes", "duration_s": 0.01, "target_alias": "Sink"},
                    ],
                    "repeat": 1,
                    "analysis": {"run_after": False},
                },
            }
        }

        async def fake_execute_scene_query(_session, _websocket, query_request):
            if query_request["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_request["request_id"],
                    "avatars": [],
                }
            if query_request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": query_request["request_id"],
                    "scene_version": 10,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": query_request["request_id"],
                "status": "success",
                "scene_version_after": 11,
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        result = await server._handle_clarification_reply(
            {
                "type": "clarification.reply",
                "question_id": "experiment_confirm:exp_pseudo",
                "selected_ids": ["run_experiment"],
            },
            websocket=websocket,
            session=session,
        )

        self.assertIsNone(result)
        await session._experiment_task
        setup_request = next(
            call.args[2]
            for call in server._execute_scene_query.await_args_list
            if call.args[2]["type"] == "scene.execute_actions"
        )
        self.assertEqual(
            [action["action_type"] for action in setup_request["actions"]],
            ["spawn_avatar", "set_sensor", "set_sensor"],
        )
        self.assertNotIn("ensure_avatar", [action["action_type"] for action in setup_request["actions"]])
        self.assertNotIn("attach_imu", [action["action_type"] for action in setup_request["actions"]])
        self.assertEqual(setup_request["actions"][1]["parameters"]["attach_mode"], "avatar_joint")
        self.assertEqual(setup_request["actions"][1]["parameters"]["joint_name"], "right_wrist")
        self.assertEqual(setup_request["actions"][2]["parameters"]["joint_name"], "waist")

    async def test_experiment_confirmation_reply_can_cancel_plan(self):
        server = self._make_server()
        websocket = _FakeWebSocket()
        session = MagicMock()
        session.client_id = "client_exp_cancel"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session._experiment_task = None
        session._pending_experiment_confirmations = {
            "experiment_confirm:exp_1": {
                "reply": {"type": "conversation.reply", "reply": "Plan ready."},
                "experiment": {
                    "goal": "collect door data",
                    "recording": {"auto_upload": False},
                    "phases": [{"label": "open", "duration_s": 1}],
                },
            }
        }

        result = await server._handle_clarification_reply(
            {
                "type": "clarification.reply",
                "question_id": "experiment_confirm:exp_1",
                "selected_ids": ["cancel_experiment"],
            },
            websocket=websocket,
            session=session,
        )

        self.assertIsNone(result)
        self.assertIsNone(session._experiment_task)
        self.assertEqual(session._pending_experiment_confirmations, {})
        self.assertEqual(websocket.sent[-1]["type"], "conversation.reply")
        self.assertIn("cancelled", websocket.sent[-1]["reply"].lower())

    async def test_agent_experiment_job_fails_when_scene_action_fails(self):
        server = self._make_server()
        websocket = _FakeWebSocket()
        session = MagicMock()
        session.client_id = "client_exp_fail"
        session.username = "kba"
        session.us = "0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session._active_task = None
        session._pending_queries = {}
        session._experiment_task = None
        session._recording_snapshot_waiters = []
        session.agent_core = MagicMock()
        session.agent_core.handle_text = AsyncMock(
            return_value={
                "type": "conversation.reply",
                "reply": "I will run the collection.",
                "control": {"actions": []},
                "experiment": {
                    "goal": "collect door data",
                    "recording": {"auto_upload": False},
                    "phases": [{"label": "open", "duration_s": 0.01}],
                },
            }
        )
        call_count = 0

        async def fake_execute_scene_query(_session, _websocket, query_request):
            nonlocal call_count
            if query_request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": query_request["request_id"],
                    "scene_version": 6,
                }
            call_count += 1
            if call_count == 2:
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_request["request_id"],
                    "status": "failed",
                    "errors": [{"message": "phase label rejected"}],
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": query_request["request_id"],
                "status": "success",
                "scene_version_after": 6 + call_count,
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        await server._run_handler_and_reply(
            server._handle_text_chat,
            {"type": "conversation.ask", "message": "collect data", "scene_snapshot": {}},
            websocket,
            session,
        )
        confirmation_id = websocket.sent[-1]["question_id"]
        await server._handle_clarification_reply(
            {
                "type": "clarification.reply",
                "question_id": confirmation_id,
                "selected_ids": ["run_experiment"],
            },
            websocket=websocket,
            session=session,
        )
        await session._experiment_task

        sent_types = [message["type"] for message in websocket.sent]
        self.assertIn("job.status", sent_types)
        self.assertNotIn("job.completed", sent_types)
        failed_messages = [
            message for message in websocket.sent
            if message.get("type") == "job.status" and message.get("status") == "failed"
        ]
        self.assertEqual(len(failed_messages), 1)
        self.assertIn("phase label rejected", failed_messages[0]["reason"])
        failure_replies = [
            message for message in websocket.sent
            if message.get("type") == "conversation.reply"
            and "phase label rejected" in (message.get("reply") or "")
        ]
        self.assertEqual(len(failure_replies), 1)

    async def test_recording_snapshot_ack_marks_experiment_waiter_as_handled(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_snapshot"
        session.username = "kba"
        session.us = "0"
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.add_event = MagicMock()
        session.transcript = MagicMock()
        waiter = asyncio.get_running_loop().create_future()
        session._recording_snapshot_waiters = [waiter]

        result = await server._handle_sensor_recording_snapshot(
            {
                "type": "sensor.recording_snapshot",
                "timestamp_label": "kba_0_20260616_170000",
                "local_export_directory": "/tmp/local",
                "files": [
                    {
                        "file_name": "DISTANCE-01_DISTANCE.csv",
                        "csv_content": "tag,time,phase,distance\nDISTANCE-01,0,cooking,1.0\n",
                    }
                ],
            },
            session=session,
        )

        self.assertEqual(result["type"], "sensor.recording_snapshot_ack")
        self.assertTrue(result["handled_by_experiment"])
        self.assertTrue(waiter.done())
        self.assertEqual(waiter.result()["timestamp_label"], "kba_0_20260616_170000")

    async def test_recording_snapshot_received_before_waiter_is_created_is_buffered_for_experiment(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_snapshot_race"
        session.username = "kba"
        session.us = "0"
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.add_event = MagicMock()
        session.transcript = MagicMock()
        session._recording_snapshot_waiters = []
        session._recent_recording_snapshots = []
        session._experiment_task = asyncio.create_task(asyncio.sleep(60))
        self.addCleanup(session._experiment_task.cancel)

        ack = await server._handle_sensor_recording_snapshot(
            {
                "type": "sensor.recording_snapshot",
                "timestamp_label": "kba_0_20260616_170100",
                "local_export_directory": "/tmp/local",
                "files": [
                    {
                        "file_name": "DISTANCE-01_DISTANCE.csv",
                        "csv_content": "tag,time,phase,distance\nDISTANCE-01,0,cooking,1.0\n",
                    }
                ],
            },
            session=session,
        )

        snapshot = await server._wait_for_next_recording_snapshot(session, timeout_s=0.01)

        self.assertTrue(ack["handled_by_experiment"])
        self.assertEqual(snapshot["timestamp_label"], "kba_0_20260616_170100")

    async def test_process_message_routes_job_start(self):
        server = self._make_server()
        payload = {
            "type": "job.start",
            "job_kind": "simulation.run",
            "payload": {"duration_s": 30},
        }

        result = await server.process_message(json.dumps(payload))

        self.assertEqual(result["type"], "job.started")
        self.assertEqual(result["job_kind"], "simulation.run")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["payload"], {"duration_s": 30})

    async def test_process_message_routes_job_status(self):
        server = self._make_server()
        started = server.job_manager.start_job("simulation.run", {"duration_s": 30})
        payload = {
            "type": "job.status",
            "job_id": started["job_id"],
        }

        result = await server.process_message(json.dumps(payload))

        self.assertEqual(result["type"], "job.status")
        self.assertEqual(result["job_id"], started["job_id"])
        self.assertEqual(result["status"], "running")

    async def test_process_message_routes_job_cancel(self):
        server = self._make_server()
        started = server.job_manager.start_job("training.run", {"epochs": 3})
        payload = {
            "type": "job.cancel",
            "job_id": started["job_id"],
            "reason": "User requested stop",
        }

        result = await server.process_message(json.dumps(payload))

        self.assertEqual(result["type"], "job.cancelled")
        self.assertEqual(result["job_id"], started["job_id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["reason"], "User requested stop")

    async def test_process_message_persists_sensor_recording_snapshot_and_adds_event(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "alice"
        session.us = "lab_a"
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.add_event = MagicMock()

        payload = {
            "type": "sensor.recording_snapshot",
            "timestamp_label": "alice_lab_a_20260421_101010",
            "local_export_directory": "/tmp/unity_export/alice_lab_a_20260421_101010",
            "files": [
                {
                    "file_name": "IMU-01_IMU.csv",
                    "sensor_name": "IMU-01",
                    "csv_content": "tag,time,ax,ay,az\nIMU-01,0.0,1,2,3\n",
                },
                {
                    "file_name": "DISTANCE-01_DISTANCE.csv",
                    "sensor_name": "DISTANCE-01",
                    "csv_content": "tag,time,distance\nDISTANCE-01,0.0,0.5\n",
                },
            ],
        }

        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "sensor.recording_snapshot_ack")
        self.assertEqual(result["saved_file_count"], 2)
        saved_dir = Path(result["saved_directory"])
        self.assertTrue(saved_dir.is_dir())
        self.assertTrue((saved_dir / "IMU-01_IMU.csv").exists())
        self.assertTrue((saved_dir / "DISTANCE-01_DISTANCE.csv").exists())
        session.agent_core.memory.add_event.assert_called_once()
        event = session.agent_core.memory.add_event.call_args.args[0]
        self.assertEqual(event["summary"], f"Recording snapshot saved: alice_lab_a_20260421_101010 at {saved_dir}")
        self.assertEqual(event["recording_snapshot"]["saved_directory"], str(saved_dir))
        self.assertEqual(
            event["recording_snapshot"]["file_names"],
            ["DISTANCE-01_DISTANCE.csv", "IMU-01_IMU.csv"],
        )
        session.transcript.append_event.assert_called_once()
        transcript_event = session.transcript.append_event.call_args.kwargs
        self.assertEqual(transcript_event["event_kind"], "recording")
        self.assertEqual(transcript_event["message_type"], "sensor.recording_snapshot")
        self.assertEqual(transcript_event["payload"]["timestamp_label"], "alice_lab_a_20260421_101010")
        self.assertEqual(transcript_event["payload"]["file_names"], ["DISTANCE-01_DISTANCE.csv", "IMU-01_IMU.csv"])

    async def test_recording_snapshot_with_websocket_sends_ack_then_analysis_reminder(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "alice"
        session.us = "lab_a"
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        websocket = _FakeWebSocket()

        payload = {
            "type": "sensor.recording_snapshot",
            "timestamp_label": "alice_lab_a_20260421_101010",
            "files": [
                {
                    "file_name": "IMU-01_IMU.csv",
                    "sensor_name": "IMU-01",
                    "csv_content": "tag,time,ax,ay,az\nIMU-01,0.0,1,2,3\n",
                },
                {
                    "file_name": "IMU-02_IMU.csv",
                    "sensor_name": "IMU-02",
                    "csv_content": "tag,time,ax,ay,az\nIMU-02,0.0,2,3,4\n",
                },
            ],
        }

        result = await server.process_message(json.dumps(payload), websocket=websocket, session=session)

        self.assertIsNone(result)
        self.assertEqual([message["type"] for message in websocket.sent], ["sensor.recording_snapshot_ack", "conversation.reply"])
        self.assertEqual(websocket.sent[0]["saved_file_count"], 2)
        self.assertIn("2", websocket.sent[1]["reply"])
        self.assertIn("recording", websocket.sent[1]["reply"])
        self.assertIn("analyze", websocket.sent[1]["reply"])
        self.assertIn("compare", websocket.sent[1]["reply"])
        self.assertGreaterEqual(session.transcript.append_message.call_count, 2)

    async def test_process_message_rejects_malformed_sensor_recording_snapshot(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "alice"
        session.us = "lab_a"
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()

        payload = {
            "type": "sensor.recording_snapshot",
            "timestamp_label": "alice_lab_a_20260421_101010",
            "files": [],
        }

        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "error")
        self.assertIn("files", result["message"])

    async def test_malformed_recording_snapshot_with_websocket_does_not_send_reminder(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "alice"
        session.us = "lab_a"
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        websocket = _FakeWebSocket()

        payload = {
            "type": "sensor.recording_snapshot",
            "timestamp_label": "alice_lab_a_20260421_101010",
            "files": [],
        }

        result = await server.process_message(json.dumps(payload), websocket=websocket, session=session)

        self.assertIsNone(result)
        self.assertEqual([message["type"] for message in websocket.sent], ["error"])
        self.assertNotIn("conversation.reply", [message["type"] for message in websocket.sent])

    async def test_avatar_joint_sensor_reply_is_executed_with_scene_api_and_not_legacy_control(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_avatar_sensor"
        session.transcript = MagicMock()
        session._pending_queries = {}
        session._active_task = asyncio.current_task()
        websocket = _FakeWebSocket()
        async def fake_execute_scene_query(_session, _websocket, request):
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "method": "scene.query_summary",
                    "scene_version": 12,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "applied_actions": [0],
                "errors": [],
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        async def fake_handler(_msg, websocket=None, session=None):
            return {
                "type": "conversation.reply",
                "reply": "Attaching IMU-01 to the right wrist.",
                "control": {
                    "actions": [
                        {
                            "target": "IMU-01",
                            "action": "set_sensor",
                            "parameters": {
                                "sensor_type": "IMU",
                                "attach_mode": "avatar_joint",
                                "avatar_id": "avatar_main",
                                "joint_name": "right_wrist",
                            },
                        }
                    ]
                },
            }

        await server._run_handler_and_reply(
            fake_handler,
            {"type": "conversation.ask", "message": "attach"},
            websocket,
            session,
        )

        self.assertEqual(server._execute_scene_query.await_count, 2)
        reliable_request = server._execute_scene_query.await_args_list[1].args[2]
        self.assertEqual(reliable_request["type"], "scene.execute_actions")
        self.assertEqual(reliable_request["strict"], True)
        self.assertEqual(reliable_request["scene_version"], 12)
        self.assertEqual(reliable_request["actions"][0]["target_id"], "IMU-01")
        self.assertEqual(reliable_request["actions"][0]["action_type"], "set_sensor")
        self.assertEqual(
            reliable_request["actions"][0]["parameters"]["attach_mode"],
            "avatar_joint",
        )
        self.assertEqual(websocket.sent[-1]["type"], "conversation.reply")
        self.assertEqual(websocket.sent[-1]["control"]["actions"], [])

    async def test_remove_sensor_reply_is_executed_with_scene_api_and_not_legacy_control(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_remove_sensor"
        session.transcript = MagicMock()
        session._pending_queries = {}
        session._active_task = asyncio.current_task()
        websocket = _FakeWebSocket()

        async def fake_execute_scene_query(_session, _websocket, request):
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "method": "scene.query_summary",
                    "scene_version": 21,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "applied_actions": [0],
                "errors": [],
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        async def fake_handler(_msg, websocket=None, session=None):
            return {
                "type": "conversation.reply",
                "reply": "Removing IMU-03.",
                "control": {
                    "actions": [
                        {
                            "target": "IMU-03",
                            "action": "remove_sensor",
                            "parameters": {},
                        }
                    ]
                },
            }

        await server._run_handler_and_reply(
            fake_handler,
            {"type": "conversation.ask", "message": "remove imu"},
            websocket,
            session,
        )

        self.assertEqual(server._execute_scene_query.await_count, 2)
        reliable_request = server._execute_scene_query.await_args_list[1].args[2]
        self.assertEqual(reliable_request["type"], "scene.execute_actions")
        self.assertEqual(reliable_request["actions"][0]["target_id"], "IMU-03")
        self.assertEqual(reliable_request["actions"][0]["action_type"], "remove_sensor")
        self.assertEqual(websocket.sent[-1]["control"]["actions"], [])

    async def test_stale_turn_drops_reply_and_reliable_actions(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_stale_turn"
        session.transcript = MagicMock()
        session._pending_queries = {}
        session._active_task = asyncio.current_task()
        session._turn_generation = 2
        websocket = _FakeWebSocket()
        server._execute_scene_query = AsyncMock()

        async def fake_handler(_msg, websocket=None, session=None):
            return {
                "type": "conversation.reply",
                "reply": "This stale reply should not be sent.",
                "control": {
                    "actions": [
                        {
                            "target": "IMU-01",
                            "action": "set_sensor",
                            "parameters": {
                                "sensor_type": "IMU",
                                "attach_mode": "avatar_joint",
                                "avatar_id": "avatar_main",
                                "joint_name": "right_wrist",
                            },
                        }
                    ]
                },
            }

        await server._run_handler_and_reply(
            fake_handler,
            {"type": "conversation.ask", "message": "old request", "_turn_generation": 1},
            websocket,
            session,
        )

        server._execute_scene_query.assert_not_awaited()
        self.assertEqual(websocket.sent, [])
        session.transcript.append_event.assert_called()

    async def test_avatar_joint_sensor_reply_executes_whole_action_batch_in_order(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_avatar_sensor_batch"
        session.transcript = MagicMock()
        session._pending_queries = {}
        session._active_task = asyncio.current_task()
        websocket = _FakeWebSocket()

        async def fake_execute_scene_query(_session, _websocket, request):
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "method": "scene.query_summary",
                    "scene_version": 3,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "applied_actions": [0, 1],
                "errors": [],
                "scene_version_after": 5,
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        async def fake_handler(_msg, websocket=None, session=None):
            return {
                "type": "conversation.reply",
                "reply": "Creating avatar and attaching IMU-01.",
                "control": {
                    "actions": [
                        {
                            "target": "avatar_main",
                            "action": "spawn_avatar",
                            "parameters": {
                                "prefab_key": "smplx_male",
                                "avatar_id": "avatar_main",
                                "position": [0, 0, 0],
                                "rotation": [0, 0, 0],
                            },
                        },
                        {
                            "target": "IMU-01",
                            "action": "set_sensor",
                            "parameters": {
                                "sensor_type": "IMU",
                                "attach_mode": "avatar_joint",
                                "avatar_id": "avatar_main",
                                "joint_name": "right_wrist",
                            },
                        },
                    ]
                },
            }

        await server._run_handler_and_reply(
            fake_handler,
            {"type": "conversation.ask", "message": "create avatar and attach imu"},
            websocket,
            session,
        )

        reliable_request = server._execute_scene_query.await_args_list[1].args[2]
        self.assertEqual(reliable_request["scene_version"], 3)
        self.assertEqual(
            [action["action_type"] for action in reliable_request["actions"]],
            ["spawn_avatar", "set_sensor"],
        )
        self.assertEqual(
            [action["target_id"] for action in reliable_request["actions"]],
            ["avatar_main", "IMU-01"],
        )
        self.assertEqual(websocket.sent[-1]["control"]["actions"], [])

    async def test_failed_reliable_avatar_joint_action_is_not_replayed_as_legacy_control(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_avatar_sensor_failed"
        session.transcript = MagicMock()
        session._pending_queries = {}
        session._active_task = asyncio.current_task()
        websocket = _FakeWebSocket()

        async def fake_execute_scene_query(_session, _websocket, request):
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "method": "scene.query_summary",
                    "scene_version": 7,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "failed",
                "applied_actions": [],
                "errors": [{"code": "CONSTRAINT_VIOLATION", "message": "avatar missing"}],
            }

        server._execute_scene_query = AsyncMock(side_effect=fake_execute_scene_query)

        async def fake_handler(_msg, websocket=None, session=None):
            return {
                "type": "conversation.reply",
                "reply": "Attaching IMU-01.",
                "control": {
                    "actions": [
                        {
                            "target": "IMU-01",
                            "action": "set_sensor",
                            "parameters": {
                                "sensor_type": "IMU",
                                "attach_mode": "avatar_joint",
                                "avatar_id": "avatar_main",
                                "joint_name": "right_wrist",
                            },
                        }
                    ]
                },
            }

        await server._run_handler_and_reply(
            fake_handler,
            {"type": "conversation.ask", "message": "attach"},
            websocket,
            session,
        )

        self.assertIn("Unity reported", websocket.sent[-1]["reply"])
        self.assertEqual(websocket.sent[-1]["control"]["actions"], [])

    async def test_process_message_persists_unity_scene_action_log(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "alice"
        session.us = "lab_a"
        session.transcript = MagicMock()
        from vsens_server import UnityActionLogWriter
        session.unity_action_log = UnityActionLogWriter(
            base_dir=server._unity_action_log_root,
            connected_at=datetime.fromisoformat("2026-04-21T10:10:10"),
            client_id=session.client_id,
        )
        session.unity_action_log.configure_identity(username=session.username, us=session.us)

        payload = {
            "type": "unity.scene_action",
            "scene_name": "Room Test",
            "record": {
                "actionId": "action_001",
                "source": "user",
                "actionType": "set_transform",
                "targetId": "DISTANCE-01",
                "timestampUtc": "2026-04-21T10:11:12.123Z",
                "description": "Moved sensor",
                "rawActionJson": None,
                "revertedActionId": None,
                "beforeTransform": {
                    "objectId": "DISTANCE-01",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "afterTransform": {
                    "objectId": "DISTANCE-01",
                    "position": {"x": 1.0, "y": 0.0, "z": 0.0},
                },
            },
        }

        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertIsNone(result)
        expected_path = server._unity_action_log_root / "lab_a" / "alice" / "20260421_101010_client_123.log"
        self.assertTrue(expected_path.exists())
        lines = expected_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("unity.scene_action", lines[0])
        self.assertIn("\"client_id\":\"client_123\"", lines[0])
        self.assertIn("\"scene_name\":\"Room Test\"", lines[0])
        self.assertIn("\"actionType\":\"set_transform\"", lines[0])
        session.transcript.append_event.assert_called_once()
        transcript_event = session.transcript.append_event.call_args.kwargs
        self.assertEqual(transcript_event["event_kind"], "unity_action")
        self.assertEqual(transcript_event["message_type"], "unity.scene_action")
        self.assertEqual(transcript_event["payload"]["client_id"], "client_123")
        self.assertEqual(transcript_event["payload"]["record"]["actionType"], "set_transform")

    async def test_delegated_task_start_requires_goal(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {"CoffeeMaker": {"position": [0, 0, 0]}}

        payload = {
            "type": "task.start",
            "task_type": "analysis",
        }
        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "error")
        self.assertIn("goal", result["message"])

    async def test_delegated_task_start_analysis_defaults_recent_n_and_creates_job(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {"CoffeeMaker": {"position": [0, 0, 0]}}

        base = server._recording_storage_root / "u0" / "welkin"
        (base / "welkin_0_20260421_155804").mkdir(parents=True, exist_ok=True)
        (base / "welkin_0_20260421_160001").mkdir(parents=True, exist_ok=True)
        (base / "welkin_0_20260421_160101").mkdir(parents=True, exist_ok=True)
        (base / "welkin_0_20260421_160201").mkdir(parents=True, exist_ok=True)

        payload = {
            "type": "task.start",
            "task_type": "analysis",
            "goal": "Compare the recent door-opening recordings and find the best placement.",
        }
        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "job.started")
        self.assertEqual(result["job_kind"], "delegated_task")
        self.assertEqual(result["payload"]["task_type"], "analysis")
        self.assertEqual(result["payload"]["recent_n"], 3)
        self.assertEqual(result["recording_count"], 3)
        session.broadcaster.set_state.assert_awaited()
        self.assertEqual(session.broadcaster.set_state.await_args.args[0], "waiting_subagent")

    async def test_process_message_blocks_text_chat_while_waiting_subagent(self):
        server = self._make_server()
        session = MagicMock()
        session._delegated_task_job_id = "job_123"
        session._delegated_task_waiting_for_user = False

        payload = {
            "type": "text_chat",
            "message": "hello while worker runs",
            "scene_snapshot": {},
        }

        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "error")
        self.assertIn("delegated task", result["message"].lower())

    async def test_delegated_task_start_by_label_requires_timestamp(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {}

        payload = {
            "type": "task.start",
            "task_type": "analysis",
            "goal": "Analyze a specific recording.",
            "selector": "by_label",
        }
        result = await server.process_message(json.dumps(payload), websocket=object(), session=session)

        self.assertEqual(result["type"], "error")
        self.assertIn("timestamp_label", result["message"])

    async def test_run_delegated_task_job_pushes_completed_and_result_messages(self):
        server = self._make_server()
        server._send_to_websocket = AsyncMock()
        server._delegated_task_runner.run = AsyncMock(
            return_value={
                "status": "completed",
                "report_text": "The best placement is placement B based on lower noise and clearer transitions.",
                "questions_for_agent": [],
                "artifacts": [{"path": "artifacts/chart.png", "kind": "image", "label": "Comparison chart"}],
                "working_notes": "Used simple statistics.",
            }
        )
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.add_event = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()

        base = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160201"
        base.mkdir(parents=True, exist_ok=True)
        (base / "DISTANCE-01_DISTANCE.csv").write_text(
            "\n".join(
                [
                    "tag,time,d",
                    "DISTANCE-01,0.0,3.6",
                    "DISTANCE-01,0.1,3.6",
                    "DISTANCE-01,0.2,4.9",
                    "DISTANCE-01,0.3,1.0",
                    "DISTANCE-01,0.4,10.0",
                ]
            ),
            encoding="utf-8",
        )

        started = session.job_manager.start_job(
            "delegated_task",
            {
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
                "selector": "latest",
                "recording_count": 1,
                "recording_keys": ["u0/welkin/welkin_0_20260421_160201"],
                "recording_paths": [str(base)],
            },
        )
        artifact_path = server._delegated_task_workspace_manager.root / started["job_id"] / "artifacts" / "chart.png"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(b"fake-png")

        await server._run_delegated_task_job(
            websocket=MagicMock(),
            session=session,
            job_id=started["job_id"],
            job_payload=started["payload"],
        )

        self.assertEqual(server._send_to_websocket.await_count, 3)
        completed = server._send_to_websocket.await_args_list[0].args[1]
        result = server._send_to_websocket.await_args_list[1].args[1]
        snapshot = server._send_to_websocket.await_args_list[2].args[1]
        self.assertEqual(completed["type"], "job.completed")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(result["type"], "task.result")
        self.assertEqual(result["job_kind"], "delegated_task")
        self.assertEqual(result["task_type"], "analysis")
        self.assertEqual(result["artifacts"][0]["kind"], "image")
        self.assertEqual(snapshot["type"], "task.artifacts_snapshot")
        self.assertEqual(snapshot["artifacts"][0]["file_name"], "chart.png")
        self.assertTrue(snapshot["artifacts"][0]["content_base64"])

    async def test_run_delegated_task_job_needs_user_input_sends_waiting_status_and_clarification(self):
        server = self._make_server()
        server._send_to_websocket = AsyncMock()
        server._delegated_task_runner.run = AsyncMock(
            return_value={
                "status": "needs_agent_input",
                "report_text": "",
                "questions_for_agent": ["Which placements should be compared?"],
                "artifacts": [],
                "working_notes": "",
            }
        )
        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {}
        session.agent_core.memory.add_event = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session._pending_delegated_task_questions = {}

        base = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160201"
        base.mkdir(parents=True, exist_ok=True)

        started = session.job_manager.start_job(
            "delegated_task",
            {
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
                "selector": "latest",
                "recording_count": 1,
                "recording_keys": ["u0/welkin/welkin_0_20260421_160201"],
                "recording_paths": [str(base)],
            },
        )

        await server._run_delegated_task_job(
            websocket=MagicMock(),
            session=session,
            job_id=started["job_id"],
            job_payload=started["payload"],
        )

        self.assertEqual(server._send_to_websocket.await_count, 2)
        waiting = server._send_to_websocket.await_args_list[0].args[1]
        clarification = server._send_to_websocket.await_args_list[1].args[1]
        self.assertEqual(waiting["type"], "job.status")
        self.assertEqual(waiting["status"], "waiting_on_user")
        self.assertEqual(clarification["type"], "clarification.request")
        self.assertTrue(clarification["question_id"].startswith(f"delegated_task:{started['job_id']}:"))
        self.assertIn("Which placements should be compared?", clarification["prompt"])
        self.assertEqual(session.broadcaster.set_state.await_args.args[0], "idle")

    async def test_clarification_reply_resumes_pending_delegated_task(self):
        server = self._make_server()
        server._send_to_websocket = AsyncMock()
        first_result = {
            "status": "needs_agent_input",
            "report_text": "",
            "questions_for_agent": ["Which placements should be compared?"],
            "artifacts": [],
            "working_notes": "",
        }
        second_result = {
            "status": "completed",
            "report_text": "Placement B is best after comparing A and B.",
            "questions_for_agent": [],
            "artifacts": [{"path": "artifacts/chart.png", "kind": "image"}],
            "working_notes": "",
        }
        server._delegated_task_runner.run = AsyncMock(side_effect=[first_result, second_result])

        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {}
        session.agent_core.memory.add_event = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session._pending_delegated_task_questions = {}

        base = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160201"
        base.mkdir(parents=True, exist_ok=True)

        started = session.job_manager.start_job(
            "delegated_task",
            {
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
                "selector": "latest",
                "recording_count": 1,
                "recording_keys": ["u0/welkin/welkin_0_20260421_160201"],
                "recording_paths": [str(base)],
            },
        )

        await server._run_delegated_task_job(
            websocket=MagicMock(),
            session=session,
            job_id=started["job_id"],
            job_payload=started["payload"],
        )

        pending_question_id = server._send_to_websocket.await_args_list[1].args[1]["question_id"]
        server._send_to_websocket.reset_mock()

        result = await server._handle_clarification_reply(
            {
                "type": "clarification.reply",
                "question_id": pending_question_id,
                "free_text": "Compare placements A and B.",
                "scene_snapshot": {},
            },
            websocket=MagicMock(),
            session=session,
        )

        self.assertIsNone(result)
        self.assertEqual(server._send_to_websocket.await_count, 3)
        running = server._send_to_websocket.await_args_list[0].args[1]
        completed = server._send_to_websocket.await_args_list[1].args[1]
        task_result = server._send_to_websocket.await_args_list[2].args[1]
        self.assertEqual(running["type"], "job.status")
        self.assertEqual(running["status"], "running")
        self.assertEqual(completed["type"], "job.completed")
        self.assertEqual(task_result["type"], "task.result")
        self.assertIn("Placement B is best", task_result["reply"])
        self.assertEqual(session.broadcaster.set_state.await_args_list[-1].args[0], "idle")

    async def test_agent_interrupt_cancels_active_delegated_task(self):
        server = self._make_server()
        session = MagicMock()
        session.client_id = "client_123"
        session.job_manager = JobManager()
        started = session.job_manager.start_job("delegated_task", {"task_type": "analysis"})
        session._delegated_task_job_id = started["job_id"]
        session._delegated_task_waiting_for_user = False
        session._active_task = None
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.clear_plan = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session.broadcaster.reset = AsyncMock()
        session._delegated_task_future = asyncio.create_task(asyncio.sleep(60))

        try:
            result = await server._handle_agent_interrupt({"type": "agent_interrupt"}, websocket=object(), session=session)
        finally:
            if session._delegated_task_future is not None and not session._delegated_task_future.done():
                session._delegated_task_future.cancel()

        self.assertEqual(result["type"], "interrupt_ack")
        self.assertEqual(session.job_manager.get_job(started["job_id"])["status"], "cancelled")

    async def test_run_delegated_task_job_auto_resolves_recording_scope_question(self):
        server = self._make_server()
        server._send_to_websocket = AsyncMock()
        first_result = {
            "status": "needs_agent_input",
            "report_text": "",
            "questions_for_agent": ["Which recordings should be compared for this analysis?"],
            "artifacts": [],
            "working_notes": "",
        }
        second_result = {
            "status": "completed",
            "report_text": "Placement B is best after comparing the selected recordings.",
            "questions_for_agent": [],
            "artifacts": [],
            "working_notes": "",
        }
        server._delegated_task_runner.run = AsyncMock(side_effect=[first_result, second_result])

        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {}
        session.agent_core.memory.add_event = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session._pending_delegated_task_questions = {}

        base_a = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160201"
        base_b = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160301"
        base_a.mkdir(parents=True, exist_ok=True)
        base_b.mkdir(parents=True, exist_ok=True)

        started = session.job_manager.start_job(
            "delegated_task",
            {
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
                "selector": "recent_n",
                "recent_n": 2,
                "recording_count": 2,
                "recording_keys": [
                    "u0/welkin/welkin_0_20260421_160201",
                    "u0/welkin/welkin_0_20260421_160301",
                ],
                "recording_paths": [str(base_a), str(base_b)],
            },
        )

        await server._run_delegated_task_job(
            websocket=MagicMock(),
            session=session,
            job_id=started["job_id"],
            job_payload=started["payload"],
        )

        self.assertEqual(server._send_to_websocket.await_count, 3)
        running = server._send_to_websocket.await_args_list[0].args[1]
        completed = server._send_to_websocket.await_args_list[1].args[1]
        task_result = server._send_to_websocket.await_args_list[2].args[1]
        self.assertEqual(running["type"], "job.status")
        self.assertEqual(running["status"], "running")
        self.assertEqual(completed["type"], "job.completed")
        self.assertEqual(task_result["type"], "task.result")
        self.assertEqual(session._pending_delegated_task_questions, {})

    async def test_run_delegated_task_job_asks_main_agent_before_user(self):
        server = self._make_server()
        server._send_to_websocket = AsyncMock()
        first_result = {
            "status": "needs_agent_input",
            "report_text": "",
            "questions_for_agent": ["Based on the user goal, which placement comparison should I focus on first?"],
            "artifacts": [],
            "working_notes": "",
        }
        second_result = {
            "status": "completed",
            "report_text": "Focus on comparing placements A and B first.",
            "questions_for_agent": [],
            "artifacts": [],
            "working_notes": "",
        }
        server._delegated_task_runner.run = AsyncMock(side_effect=[first_result, second_result])

        session = MagicMock()
        session.client_id = "client_123"
        session.username = "welkin"
        session.us = "u0"
        session.job_manager = JobManager()
        session.transcript = MagicMock()
        session.agent_core = MagicMock()
        session.agent_core.memory = MagicMock()
        session.agent_core.memory.scene = {}
        session.agent_core.memory.add_event = MagicMock()
        session.broadcaster = MagicMock()
        session.broadcaster.set_state = AsyncMock()
        session.agent_core.handle_text = AsyncMock(
            return_value={
                "type": "conversation.reply",
                "reply": "Compare placements A and B first because they are the most recent door-opening runs.",
                "control": {"actions": []},
            }
        )
        session._pending_delegated_task_questions = {}

        base_a = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160201"
        base_b = server._recording_storage_root / "u0" / "welkin" / "welkin_0_20260421_160301"
        base_a.mkdir(parents=True, exist_ok=True)
        base_b.mkdir(parents=True, exist_ok=True)

        started = session.job_manager.start_job(
            "delegated_task",
            {
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
                "selector": "recent_n",
                "recent_n": 2,
                "recording_count": 2,
                "recording_keys": [
                    "u0/welkin/welkin_0_20260421_160201",
                    "u0/welkin/welkin_0_20260421_160301",
                ],
                "recording_paths": [str(base_a), str(base_b)],
            },
        )

        await server._run_delegated_task_job(
            websocket=MagicMock(),
            session=session,
            job_id=started["job_id"],
            job_payload=started["payload"],
        )

        session.agent_core.handle_text.assert_awaited_once()
        asked_message = session.agent_core.handle_text.await_args.args[0]
        self.assertIn("subagent", asked_message.lower())
        self.assertIn("placement comparison", asked_message.lower())
        self.assertEqual(server._send_to_websocket.await_count, 3)
        self.assertEqual(server._send_to_websocket.await_args_list[0].args[1]["status"], "running")
        self.assertEqual(server._send_to_websocket.await_args_list[1].args[1]["type"], "job.completed")
        self.assertEqual(server._send_to_websocket.await_args_list[2].args[1]["type"], "task.result")
        self.assertEqual(session._pending_delegated_task_questions, {})
