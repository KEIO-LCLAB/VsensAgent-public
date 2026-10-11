import unittest
from unittest.mock import patch

import core.skills.scene_skills  # noqa: F401
from core.skills.skill_registry import SkillRegistry


class TestSceneSkillsAvatar(unittest.TestCase):
    def test_spawn_avatar_defaults_to_main_avatar(self):
        result = SkillRegistry.dispatch(
            action="spawn_avatar",
            target="",
            parameters={
                "prefab_key": "smplx_male",
                "position": [1.0, 0.0, 2.0],
                "rotation": [0.0, 90.0, 0.0],
            },
        )

        self.assertEqual(result["action"], "spawn_avatar")
        self.assertEqual(result["target"], "avatar_main")
        self.assertEqual(result["parameters"]["prefab_key"], "smplx_male")

    def test_load_avatar_motion_prepares_motion_when_description_is_provided(self):
        prepared_motion = {
            "motion_id": "motion_walk_sink",
            "motion_name": "walk_to_sink",
            "motion_json": "{\"model\":\"smplx\",\"gender\":\"male\",\"fps\":120.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
            "source_text": "walk to the sink",
        }

        with patch("core.skills.scene_skills._get_motion_preparation_service") as service_factory:
            service_factory.return_value.prepare_motion.return_value = prepared_motion

            result = SkillRegistry.dispatch(
                action="load_avatar_motion",
                target="",
                parameters={
                    "motion_description": "walk to the sink",
                    "motion_name": "walk_to_sink",
                },
            )

        self.assertEqual(result["action"], "load_avatar_motion")
        self.assertEqual(result["target"], "avatar_main")
        self.assertEqual(result["parameters"]["motion_id"], "motion_walk_sink")
        self.assertEqual(result["parameters"]["motion_name"], "walk_to_sink")
        self.assertEqual(result["parameters"]["motion_json"], prepared_motion["motion_json"])
        self.assertNotIn("motion_description", result["parameters"])
