import unittest

import core.skills.scene_skills  # noqa: F401
from core.skills.skill_registry import SkillRegistry


class TestDelegateTaskSkill(unittest.TestCase):
    def test_dispatch_accepts_analysis_task(self):
        result = SkillRegistry.dispatch(
            action="delegate_task",
            target="",
            parameters={
                "task_type": "analysis",
                "goal": "Compare the door-opening recordings and find the best placement.",
            },
        )

        self.assertEqual(result["action"], "delegate_task")
        self.assertEqual(result["parameters"]["task_type"], "analysis")
        self.assertEqual(result["parameters"]["goal"], "Compare the door-opening recordings and find the best placement.")
        self.assertEqual(result["parameters"]["selector"], "recent_n")
        self.assertEqual(result["parameters"]["recent_n"], 3)

    def test_dispatch_requires_goal(self):
        result = SkillRegistry.dispatch(
            action="delegate_task",
            target="",
            parameters={"task_type": "analysis"},
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("goal", result["message"])

    def test_dispatch_rejects_unknown_task_type(self):
        result = SkillRegistry.dispatch(
            action="delegate_task",
            target="",
            parameters={
                "task_type": "unsupported",
                "goal": "Do something unsupported.",
            },
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("task_type", result["message"])
