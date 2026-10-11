import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from vsens_server import SessionTranscriptWriter


class TestSessionTranscriptWriter(unittest.TestCase):
    def test_buffers_events_until_identity_then_writes_jsonl_under_user_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SessionTranscriptWriter(
                base_dir=Path(tmpdir),
                connected_at=datetime.fromisoformat("2026-04-21T10:10:10"),
                client_id="client_123",
            )

            writer.append_lifecycle(
                "connect",
                summary="Client connected",
                payload={"remote_address": "::1"},
            )
            writer.configure_identity(username="alice", us="lab_a")
            writer.append_lifecycle("hello", summary="hello username=alice us=lab_a")

            expected_path = Path(tmpdir) / "lab_a" / "alice" / "20260421_101010_client_123.jsonl"
            self.assertTrue(expected_path.exists())
            events = [
                json.loads(line)
                for line in expected_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual([event["event_kind"] for event in events], ["lifecycle", "lifecycle"])
            self.assertEqual(events[0]["schema_version"], 1)
            self.assertEqual(events[0]["client_id"], "client_123")
            self.assertEqual(events[0]["username"], "anonymous")
            self.assertEqual(events[0]["us"], "anonymous")
            self.assertEqual(events[0]["direction"], "lifecycle")
            self.assertEqual(events[0]["message_type"], None)
            self.assertEqual(events[0]["payload"], {"remote_address": "::1"})
            self.assertEqual(events[1]["username"], "alice")
            self.assertEqual(events[1]["us"], "lab_a")
            self.assertGreaterEqual(events[1]["elapsed_ms"], events[0]["elapsed_ms"])

    def test_records_full_recv_and_send_payloads_as_json_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SessionTranscriptWriter(
                base_dir=Path(tmpdir),
                connected_at=datetime.fromisoformat("2026-04-21T10:10:10"),
                client_id="client_123",
            )
            writer.configure_identity(username="alice", us="lab_a")

            heartbeat_payload = {
                "type": "scene_heartbeat",
                "scene_snapshot": json.dumps({"Door_A": {"state": "open"}}),
            }
            writer.append_raw_message("recv", json.dumps(heartbeat_payload))
            writer.append_message(
                "send",
                {
                    "type": "sensor.recording_snapshot_ack",
                    "saved_files": ["IMU-01_IMU.csv"],
                },
            )
            writer.append_raw_message("recv", "{not valid json")

            events = [
                json.loads(line)
                for line in writer.path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(events[0]["message_type"], "scene_heartbeat")
            self.assertEqual(events[0]["payload"], heartbeat_payload)
            self.assertEqual(
                events[0]["payload"]["scene_snapshot"],
                json.dumps({"Door_A": {"state": "open"}}),
            )
            self.assertEqual(events[1]["direction"], "send")
            self.assertEqual(events[1]["message_type"], "sensor.recording_snapshot_ack")
            self.assertEqual(events[2]["message_type"], None)
            self.assertEqual(events[2]["payload"]["raw"], "{not valid json")
            self.assertIn("parse_error", events[2]["payload"])

