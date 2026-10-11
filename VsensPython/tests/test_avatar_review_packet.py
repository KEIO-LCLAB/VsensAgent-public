import unittest


class TestAvatarReviewPacket(unittest.TestCase):
    def test_builds_compact_review_packet(self):
        from core.avatar_review.review_packet import build_avatar_review_packet

        packet = build_avatar_review_packet(
            task_hint="make_coffee",
            target_alias="CoffeeMaker",
            candidate_id="avatar_cand_001",
            avatar_position=[1.9, 0.0, 4.9],
            avatar_rotation=[0.0, 180.0, 0.0],
            motion_name="make_coffee_basic",
            motion_mode="static",
            validation_summary={
                "distance_to_target": 0.82,
                "facing_score": 0.91,
                "collision_free": True,
                "grounded": True,
            },
            artifacts=[
                {"label": "avatar_eye", "file_path": "/tmp/avatar_eye.png"},
                {"label": "user_camera", "file_path": "/tmp/user_camera.png"},
            ],
        )

        self.assertEqual(packet["candidate_id"], "avatar_cand_001")
        self.assertEqual(packet["artifacts"], ["/tmp/avatar_eye.png", "/tmp/user_camera.png"])
        self.assertIn("make_coffee", packet["context_text"])
        self.assertIn("CoffeeMaker", packet["context_text"])
        self.assertIn("avatar_cand_001", packet["context_text"])
        self.assertIn("avatar_eye", packet["context_text"])
        self.assertIn("user_camera", packet["context_text"])
