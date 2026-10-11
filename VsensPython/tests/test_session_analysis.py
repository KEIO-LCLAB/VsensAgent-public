import json
import tempfile
import unittest
from pathlib import Path

from core.session_analysis import (
    analyze_session_flow,
    export_analysis_json,
    export_flow_mermaid,
    parse_session_log,
)


def _event(
    *,
    elapsed_ms: int,
    direction: str,
    message_type: str | None,
    payload: dict | None = None,
    event_kind: str = "message",
    summary: str = "",
) -> dict:
    return {
        "schema_version": 1,
        "timestamp": f"2026-04-21T10:10:{10 + elapsed_ms // 1000:02d}.000000",
        "elapsed_ms": elapsed_ms,
        "client_id": "client_123",
        "username": "alice",
        "us": "lab_a",
        "direction": direction,
        "event_kind": event_kind,
        "message_type": message_type,
        "payload": payload,
        "summary": summary,
    }


class TestSessionAnalysis(unittest.TestCase):
    def test_analyzes_message_counts_durations_and_mermaid_without_heartbeats_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.jsonl"
            events = [
                _event(
                    elapsed_ms=0,
                    direction="recv",
                    message_type="client.hello",
                    payload={"type": "client.hello", "username": "alice", "us": "lab_a"},
                ),
                _event(
                    elapsed_ms=100,
                    direction="recv",
                    message_type="scene_heartbeat",
                    payload={"type": "scene_heartbeat", "scene_snapshot": "{\"Door_A\":{}}"},
                ),
                _event(
                    elapsed_ms=200,
                    direction="recv",
                    message_type="conversation.ask",
                    payload={"type": "conversation.ask", "message": "Inspect the scene"},
                ),
                _event(
                    elapsed_ms=300,
                    direction="send",
                    message_type="scene.query_objects",
                    payload={
                        "type": "scene.query_objects",
                        "request_id": "qry_1",
                        "aliases": ["CoffeeMaker"],
                    },
                ),
                _event(
                    elapsed_ms=530,
                    direction="recv",
                    message_type="scene.query_response",
                    payload={
                        "type": "scene.query_response",
                        "request_id": "qry_1",
                        "method": "scene.query_objects",
                    },
                ),
                _event(
                    elapsed_ms=700,
                    direction="send",
                    message_type="job.started",
                    payload={"type": "job.started", "job_id": "job_1", "job_kind": "delegated_task"},
                ),
                _event(
                    elapsed_ms=950,
                    direction="send",
                    message_type="job.completed",
                    payload={"type": "job.completed", "job_id": "job_1", "job_kind": "delegated_task"},
                ),
                _event(
                    elapsed_ms=1000,
                    direction="internal",
                    event_kind="unity_action",
                    message_type="unity.scene_action",
                    payload={
                        "record": {
                            "actionId": "action_1",
                            "actionType": "set_sensor",
                            "targetId": "IMU-01",
                        }
                    },
                ),
                _event(
                    elapsed_ms=1100,
                    direction="send",
                    message_type="conversation.reply",
                    payload={"type": "conversation.reply", "reply": "Done"},
                ),
            ]
            path.write_text(
                "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
                encoding="utf-8",
            )

            parsed = parse_session_log(path)
            analysis = analyze_session_flow(path)
            mermaid = export_flow_mermaid(analysis)
            analysis_json = json.loads(export_analysis_json(analysis))

            self.assertEqual(len(parsed), 9)
            self.assertEqual(len(analysis["events"]), 8)
            self.assertNotIn("scene_heartbeat", [event["message_type"] for event in analysis["events"]])
            self.assertEqual(analysis["message_counts"]["conversation.ask"], 1)
            self.assertEqual(analysis["message_counts"]["scene.query_response"], 1)
            self.assertEqual(analysis["durations"]["requests"]["qry_1"]["duration_ms"], 230)
            self.assertEqual(analysis["durations"]["jobs"]["job_1"]["duration_ms"], 250)
            self.assertEqual(analysis["durations"]["actions"]["action_1"]["duration_ms"], 0)
            self.assertEqual(analysis["durations"]["actions"]["action_1"]["target_id"], "IMU-01")
            self.assertIn("flowchart TD", mermaid)
            self.assertIn("conversation.ask", mermaid)
            self.assertIn("scene.query_objects", mermaid)
            self.assertEqual(analysis_json["session"]["client_id"], "client_123")

    def test_can_include_heartbeats_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.jsonl"
            events = [
                _event(
                    elapsed_ms=0,
                    direction="recv",
                    message_type="scene_heartbeat",
                    payload={"type": "scene_heartbeat"},
                ),
            ]
            path.write_text(json.dumps(events[0]), encoding="utf-8")

            analysis = analyze_session_flow(path, include_heartbeat=True)

            self.assertEqual(len(analysis["events"]), 1)
            self.assertEqual(analysis["events"][0]["message_type"], "scene_heartbeat")
