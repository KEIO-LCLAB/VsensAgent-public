import unittest

from core.protocol.messages import (
    build_clarification_request,
    build_conversation_reply,
    build_delegated_task_artifacts_snapshot,
    build_delegated_task_result,
    build_job_cancelled,
    build_job_completed,
    build_job_started,
    build_job_status,
    build_proposal_ready,
)


class TestProtocolMessages(unittest.TestCase):
    def test_conversation_reply_shape(self):
        msg = build_conversation_reply(turn_id="turn_1", reply="hello")

        self.assertEqual(msg["type"], "conversation.reply")
        self.assertEqual(msg["turn_id"], "turn_1")
        self.assertEqual(msg["reply"], "hello")
        self.assertEqual(msg["status"], "success")
        self.assertEqual(msg["control"]["actions"], [])

    def test_clarification_request_shape(self):
        msg = build_clarification_request(
            question_id="q_1",
            prompt="Which appliance do you mean?",
            options=[{"id": "coffee", "label": "Coffee maker"}],
            selection_mode="single",
        )

        self.assertEqual(msg["type"], "clarification.request")
        self.assertEqual(msg["question_id"], "q_1")
        self.assertEqual(msg["prompt"], "Which appliance do you mean?")
        self.assertEqual(msg["selection_mode"], "single")
        self.assertEqual(msg["options"][0]["id"], "coffee")

    def test_proposal_ready_shape(self):
        msg = build_proposal_ready(
            proposal_id="prop_1",
            title="Wall placement options",
            options=[{"id": "cand_1", "label": "East wall"}],
            summary="I found two strong candidates.",
        )

        self.assertEqual(msg["type"], "proposal.ready")
        self.assertEqual(msg["proposal_id"], "prop_1")
        self.assertEqual(msg["title"], "Wall placement options")
        self.assertEqual(msg["summary"], "I found two strong candidates.")
        self.assertEqual(msg["options"][0]["id"], "cand_1")

    def test_job_started_shape(self):
        msg = build_job_started(
            job_id="job_1",
            job_kind="simulation.run",
            payload={"duration_s": 30},
        )

        self.assertEqual(msg["type"], "job.started")
        self.assertEqual(msg["job_id"], "job_1")
        self.assertEqual(msg["job_kind"], "simulation.run")
        self.assertEqual(msg["status"], "running")
        self.assertEqual(msg["payload"], {"duration_s": 30})

    def test_job_status_shape(self):
        msg = build_job_status(
            job_id="job_1",
            job_kind="simulation.run",
            status="running",
            payload={"duration_s": 30},
        )

        self.assertEqual(msg["type"], "job.status")
        self.assertEqual(msg["job_id"], "job_1")
        self.assertEqual(msg["job_kind"], "simulation.run")
        self.assertEqual(msg["status"], "running")

    def test_job_completed_shape(self):
        msg = build_job_completed(
            job_id="job_1",
            job_kind="data_analysis",
            payload={"summary": "done"},
        )

        self.assertEqual(msg["type"], "job.completed")
        self.assertEqual(msg["job_id"], "job_1")
        self.assertEqual(msg["status"], "completed")
        self.assertEqual(msg["payload"]["summary"], "done")

    def test_job_cancelled_shape(self):
        msg = build_job_cancelled(
            job_id="job_1",
            job_kind="simulation.run",
            payload={"duration_s": 30},
            reason="User requested stop",
        )

        self.assertEqual(msg["type"], "job.cancelled")
        self.assertEqual(msg["job_id"], "job_1")
        self.assertEqual(msg["status"], "cancelled")
        self.assertEqual(msg["reason"], "User requested stop")

    def test_delegated_task_result_shape(self):
        msg = build_delegated_task_result(
            job_id="job_1",
            task_type="analysis",
            status="completed",
            reply="analysis done",
            artifacts=[{"path": "artifacts/chart.png", "kind": "image"}],
            questions_for_agent=[],
        )

        self.assertEqual(msg["type"], "task.result")
        self.assertEqual(msg["job_kind"], "delegated_task")
        self.assertEqual(msg["task_type"], "analysis")
        self.assertEqual(msg["status"], "completed")
        self.assertEqual(msg["artifacts"][0]["kind"], "image")

    def test_delegated_task_artifacts_snapshot_shape(self):
        msg = build_delegated_task_artifacts_snapshot(
            job_id="job_1",
            task_type="analysis",
            artifacts=[
                {
                    "file_name": "chart.png",
                    "kind": "image",
                    "label": "Comparison chart",
                    "server_path": "/tmp/task/job_1/artifacts/chart.png",
                    "content_base64": "ZmFrZQ==",
                }
            ],
        )

        self.assertEqual(msg["type"], "task.artifacts_snapshot")
        self.assertEqual(msg["job_kind"], "delegated_task")
        self.assertEqual(msg["job_id"], "job_1")
        self.assertEqual(msg["artifacts"][0]["file_name"], "chart.png")
