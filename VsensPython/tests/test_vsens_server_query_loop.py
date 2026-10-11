import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.jobs.job_manager import JobManager
from vsens_server import VsensWebSocketServer


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


class _LoopbackQueryWebSocket(_FakeWebSocket):
    def __init__(self, server):
        super().__init__()
        self.server = server

    async def send(self, payload):
        message = json.loads(payload)
        self.sent.append(message)
        if message.get("type") == "scene.query_summary":
            asyncio.create_task(self.server.process_message(json.dumps({
                "type": "scene.query_response",
                "request_id": message["request_id"],
                "method": "scene.query_summary",
                "scene_version": 7,
                "counts": {"objects": 3},
            }), self))


class _LoopbackSceneActionWebSocket(_FakeWebSocket):
    def __init__(self, server):
        super().__init__()
        self.server = server

    async def send(self, payload):
        message = json.loads(payload)
        self.sent.append(message)
        if message.get("type") == "scene.execute_actions":
            asyncio.create_task(self.server.process_message(json.dumps({
                "type": "scene.execute_actions_response",
                "request_id": message["request_id"],
                "status": "success",
                "scene_version_before": 4,
                "scene_version_after": 5,
                "applied_actions": len(message.get("actions") or []),
                "errors": [],
            }), self))


class _SessionHarness:
    def __init__(self):
        self.agent_core = MagicMock()
        self.agent_core.handle_text = AsyncMock(
            return_value={"type": "conversation.reply", "reply": "ok"}
        )
        self.job_manager = JobManager()
        self._active_task = None
        self._pending_queries = {}
        self._query_timeout_s = 5.0


class TestVsensWebSocketServerQueryLoop(unittest.IsolatedAsyncioTestCase):
    def _make_server(self):
        server = VsensWebSocketServer.__new__(VsensWebSocketServer)
        server.agent_core = MagicMock()
        server.agent_core.handle_text = AsyncMock(
            return_value={"type": "conversation.reply", "reply": "ok"}
        )
        server.job_manager = JobManager()
        server._active_task = None
        server._pending_queries = {}
        server.handlers = {}
        return server

    def _make_session(self):
        return _SessionHarness()

    async def test_query_response_resolves_pending_future(self):
        server = self._make_server()
        future = asyncio.get_running_loop().create_future()
        server._pending_queries = {"qry_1": future}

        await server._handle_scene_request_response({
            "type": "scene.query_response",
            "request_id": "qry_1",
            "method": "scene.query_summary",
        })

        self.assertTrue(future.done())
        self.assertEqual(future.result()["request_id"], "qry_1")

    async def test_execute_scene_query_sends_payload_and_waits_for_result(self):
        server = self._make_server()
        websocket = _FakeWebSocket()

        async def fulfill():
            while "qry_1" not in server._pending_queries:
                await asyncio.sleep(0)
            server._pending_queries["qry_1"].set_result({
                "type": "scene.query_response",
                "request_id": "qry_1",
                "method": "scene.query_summary",
            })

        waiter = asyncio.create_task(fulfill())
        result = await server._execute_scene_query(
            websocket,
            {"type": "scene.query_summary", "request_id": "qry_1"},
        )
        await waiter

        self.assertEqual(websocket.sent[0]["type"], "scene.query_summary")
        self.assertEqual(result["request_id"], "qry_1")

    async def test_execute_scene_query_handles_execute_actions_response(self):
        server = self._make_server()
        websocket = _LoopbackSceneActionWebSocket(server)

        result = await server._execute_scene_query(
            websocket,
            {
                "type": "scene.execute_actions",
                "request_id": "exec_1",
                "actions": [
                    {
                        "target_id": "avatar_main",
                        "action_type": "spawn_avatar",
                        "parameters": {"prefab_key": "smplx_male"},
                    }
                ],
            },
        )

        self.assertEqual(websocket.sent[0]["type"], "scene.execute_actions")
        self.assertEqual(result["type"], "scene.execute_actions_response")
        self.assertEqual(result["request_id"], "exec_1")

    async def test_process_message_with_websocket_sends_reply_from_background_task(self):
        server = self._make_server()
        websocket = _FakeWebSocket()

        async def fake_handle_text(message, scene_snapshot, query_executor=None):
            self.assertEqual(message, "Help me inspect the scene")
            self.assertEqual(scene_snapshot, {"room": "kitchen"})
            self.assertIsNotNone(query_executor)
            return {"type": "conversation.reply", "reply": "ok"}

        server.agent_core.handle_text = AsyncMock(side_effect=fake_handle_text)
        server.handlers = {
            "conversation.ask": server._handle_text_chat,
        }

        result = await server.process_message(json.dumps({
            "type": "conversation.ask",
            "message": "Help me inspect the scene",
            "scene_snapshot": {"room": "kitchen"},
        }), websocket)

        self.assertIsNone(result)
        await asyncio.sleep(0)
        self.assertEqual(websocket.sent[-1]["type"], "conversation.reply")

    async def test_background_turn_can_query_and_resume_before_replying(self):
        server = self._make_server()
        websocket = _LoopbackQueryWebSocket(server)

        async def fake_handle_text(message, scene_snapshot, query_executor=None):
            self.assertEqual(message, "Inspect the scene first")
            self.assertEqual(scene_snapshot, {"room": "kitchen"})
            query_result = await query_executor({
                "type": "scene.query_summary",
                "request_id": "qry_test_turn",
            })
            return {
                "type": "conversation.reply",
                "reply": f"Scene version {query_result['scene_version']}",
            }

        server.agent_core.handle_text = AsyncMock(side_effect=fake_handle_text)
        server.handlers = {
            "conversation.ask": server._handle_text_chat,
        }

        result = await server.process_message(json.dumps({
            "type": "conversation.ask",
            "message": "Inspect the scene first",
            "scene_snapshot": {"room": "kitchen"},
        }), websocket)

        self.assertIsNone(result)
        await server._active_task

        self.assertEqual(websocket.sent[0]["type"], "scene.query_summary")
        self.assertEqual(websocket.sent[-1]["type"], "conversation.reply")
        self.assertEqual(websocket.sent[-1]["reply"], "Scene version 7")

    async def test_execute_scene_query_isolated_per_session_pending_map(self):
        server = self._make_server()
        session_a = self._make_session()
        session_b = self._make_session()
        websocket_a = _FakeWebSocket()
        websocket_b = _FakeWebSocket()

        async def fulfill_session_b():
            while "qry_b" not in session_b._pending_queries:
                await asyncio.sleep(0)
            session_b._pending_queries["qry_b"].set_result({
                "type": "scene.query_response",
                "request_id": "qry_b",
                "method": "scene.query_summary",
                "scene_version": 22,
            })

        waiter = asyncio.create_task(fulfill_session_b())
        result = await server._execute_scene_query(
            session_b,
            websocket_b,
            {"type": "scene.query_summary", "request_id": "qry_b"},
        )
        await waiter

        self.assertEqual(result["scene_version"], 22)
        self.assertNotIn("qry_b", session_a._pending_queries)
        self.assertEqual(websocket_b.sent[0]["request_id"], "qry_b")
        self.assertEqual(websocket_a.sent, [])

    async def test_scene_response_only_resolves_matching_session_future(self):
        server = self._make_server()
        session_a = self._make_session()
        session_b = self._make_session()
        future_a = asyncio.get_running_loop().create_future()
        future_b = asyncio.get_running_loop().create_future()
        session_a._pending_queries = {"qry_shared": future_a}
        session_b._pending_queries = {"qry_shared": future_b}

        await server._handle_scene_request_response(
            session_b,
            {
                "type": "scene.query_response",
                "request_id": "qry_shared",
                "method": "scene.query_summary",
                "scene_version": 9,
            },
        )

        self.assertFalse(future_a.done())
        self.assertTrue(future_b.done())
        self.assertEqual(future_b.result()["scene_version"], 9)
