import shutil
import unittest
import uuid
from pathlib import Path


class TestDelegatedSubagentSessionManager(unittest.TestCase):
    def test_create_and_update_session_persists_history_and_pending_question(self):
        from core.delegation.session import DelegatedSubagentSessionManager

        root = Path(__file__).resolve().parent / "_tmp" / f"subagent_session_test_{uuid.uuid4().hex[:8]}"
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        manager = DelegatedSubagentSessionManager()
        workspace = root / "job_001"
        workspace.mkdir(parents=True, exist_ok=True)

        state = manager.create_session(
            workspace=workspace,
            job_id="job_001",
            task_payload={"task_type": "analysis", "goal": "Compare recordings."},
        )
        self.assertEqual(state["job_id"], "job_001")
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["history"], [])

        manager.append_history(
            workspace=workspace,
            role="assistant",
            content="I need to know which placements should be compared.",
        )
        manager.mark_waiting_on_user(
            workspace=workspace,
            question_id="delegated_task:job_001:q1",
            questions=["Which placements should be compared?"],
        )

        loaded = manager.load_session(workspace=workspace)
        self.assertEqual(loaded["history"][0]["role"], "assistant")
        self.assertEqual(loaded["pending_question_id"], "delegated_task:job_001:q1")
        self.assertEqual(loaded["pending_questions"], ["Which placements should be compared?"])

        manager.record_user_reply(
            workspace=workspace,
            reply_text="Compare placements A and B.",
        )
        resumed = manager.load_session(workspace=workspace)
        self.assertEqual(resumed["status"], "running")
        self.assertIsNone(resumed["pending_question_id"])
        self.assertEqual(resumed["history"][-1]["role"], "user")
