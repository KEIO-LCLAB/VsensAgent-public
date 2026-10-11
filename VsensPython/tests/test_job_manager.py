import unittest

from core.jobs.job_manager import JobManager


class TestJobManager(unittest.TestCase):
    def test_start_job_returns_running_status(self):
        manager = JobManager()

        job = manager.start_job("simulation.run", {"duration_s": 30})

        self.assertEqual(job["type"], "job.started")
        self.assertEqual(job["job_kind"], "simulation.run")
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["payload"], {"duration_s": 30})
        self.assertIn("job_id", job)

    def test_get_job_returns_latest_state(self):
        manager = JobManager()
        started = manager.start_job("dataset.collect", {"episodes": 5})

        job = manager.get_job(started["job_id"])

        self.assertEqual(job["type"], "job.status")
        self.assertEqual(job["job_id"], started["job_id"])
        self.assertEqual(job["status"], "running")

    def test_cancel_job_marks_job_cancelled(self):
        manager = JobManager()
        started = manager.start_job("training.run", {"epochs": 3})

        job = manager.cancel_job(started["job_id"], reason="User requested stop")

        self.assertEqual(job["type"], "job.cancelled")
        self.assertEqual(job["job_id"], started["job_id"])
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["reason"], "User requested stop")

    def test_complete_job_marks_job_completed(self):
        manager = JobManager()
        started = manager.start_job("data_analysis", {"selector": "latest"})

        job = manager.complete_job(started["job_id"], payload={"summary": "done"})

        self.assertEqual(job["type"], "job.completed")
        self.assertEqual(job["job_id"], started["job_id"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["payload"]["summary"], "done")

    def test_fail_job_marks_job_failed(self):
        manager = JobManager()
        started = manager.start_job("data_analysis", {"selector": "latest"})

        job = manager.fail_job(started["job_id"], reason="bad csv")

        self.assertEqual(job["type"], "job.status")
        self.assertEqual(job["job_id"], started["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["reason"], "bad csv")
