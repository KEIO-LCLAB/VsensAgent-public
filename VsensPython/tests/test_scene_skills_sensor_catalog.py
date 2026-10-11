import unittest
from pathlib import Path

from core.memory.semantic_memory import SemanticMemory
from core.skills import scene_skills
from core.skills.skill_registry import SkillRegistry


class TestSceneSkillsSensorCatalog(unittest.TestCase):
    def test_load_valid_sensor_types_reads_knowledge_file(self):
        project_root = Path(__file__).resolve().parents[1]
        knowledge = SemanticMemory(
            knowledge_dir=str(project_root / "data" / "memory" / "knowledge")
        )
        sensor_knowledge = knowledge.get("sensors") or {}
        expected_types = tuple((sensor_knowledge.get("sensors") or {}).keys())

        loaded_types = scene_skills._load_valid_sensor_types()

        self.assertEqual(loaded_types, expected_types)

    def test_valid_sensor_types_match_knowledge_file(self):
        project_root = Path(__file__).resolve().parents[1]
        knowledge = SemanticMemory(
            knowledge_dir=str(project_root / "data" / "memory" / "knowledge")
        )
        sensor_knowledge = knowledge.get("sensors") or {}
        expected_types = tuple((sensor_knowledge.get("sensors") or {}).keys())

        self.assertEqual(scene_skills._VALID_SENSOR_TYPES, expected_types)

    def test_dispatch_rejects_sensor_type_outside_catalog(self):
        result = SkillRegistry.dispatch(
            action="set_sensor",
            target="THERMAL-01",
            parameters={
                "sensor_type": "THERMAL",
                "position": [0, 0, 0],
                "rotation": [0, 0, 0],
            },
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("sensor_type must be one of", result["message"])

    def test_dispatch_accepts_avatar_joint_attachment_mode(self):
        result = SkillRegistry.dispatch(
            action="set_sensor",
            target="imu_left_wrist",
            parameters={
                "sensor_type": "IMU",
                "attach_mode": "avatar_joint",
                "avatar_id": "avatar_main",
                "joint_name": "left_wrist",
                "local_position": [0.0, 0.0, 0.0],
                "local_rotation": [0.0, 0.0, 0.0],
            },
        )

        self.assertEqual(result["action"], "set_sensor")
        self.assertEqual(result["parameters"]["attach_mode"], "avatar_joint")
        self.assertEqual(result["parameters"]["avatar_id"], "avatar_main")
        self.assertEqual(result["parameters"]["joint_name"], "left_wrist")

    def test_dispatch_defaults_visualization_on_and_graph_off(self):
        result = SkillRegistry.dispatch(
            action="set_sensor",
            target="imu_default_flags",
            parameters={
                "sensor_type": "IMU",
            },
        )

        self.assertEqual(result["action"], "set_sensor")
        self.assertEqual(result["parameters"]["show_visualization"], "true")
        self.assertEqual(result["parameters"]["show_data_graph"], "false")

    def test_dispatch_accepts_remove_sensor(self):
        result = SkillRegistry.dispatch(
            action="remove_sensor",
            target="IMU-01",
            parameters={},
        )

        self.assertEqual(result["action"], "remove_sensor")
        self.assertEqual(result["target"], "IMU-01")
        self.assertEqual(result["parameters"], {})

    def test_dispatch_rejects_remove_sensor_without_target(self):
        result = SkillRegistry.dispatch(
            action="remove_sensor",
            target="",
            parameters={},
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("remove_sensor requires target", result["message"])

    def test_dispatch_rejects_update_sensor_without_target(self):
        result = SkillRegistry.dispatch(
            action="set_sensor",
            target="",
            parameters={
                "sensor_type": "IMU",
                "operation": "update",
            },
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("operation=update requires target", result["message"])

    def test_dispatch_rejects_avatar_joint_attachment_without_avatar_id_or_joint_name(self):
        result = SkillRegistry.dispatch(
            action="set_sensor",
            target="imu_left_wrist",
            parameters={
                "sensor_type": "IMU",
                "attach_mode": "avatar_joint",
            },
        )

        self.assertEqual(result["status"], "skill_validation_error")
        self.assertIn("avatar_joint", result["message"])
