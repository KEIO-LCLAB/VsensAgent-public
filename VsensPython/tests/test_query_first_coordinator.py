import unittest


class TestQueryFirstCoordinator(unittest.IsolatedAsyncioTestCase):
    async def test_builds_query_request_with_request_id(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        async def fake_executor(query_request):
            return {
                "type": "scene.query_response",
                "request_id": query_request["request_id"],
                "method": query_request["type"],
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)
        result = await coordinator.execute_query(
            {"method": "scene.query_summary", "params": {"scene_version": 1}}
        )

        self.assertEqual(result["type"], "scene.query_response")
        self.assertEqual(result["method"], "scene.query_summary")
        self.assertTrue(result["request_id"].startswith("qry_"))

    async def test_rejects_unknown_query_method(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        async def fake_executor(_query_request):
            raise AssertionError("executor should not be called for unsupported methods")

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        with self.assertRaises(ValueError):
            await coordinator.execute_query(
                {"method": "scene.delete_everything", "params": {}}
            )

    async def test_accepts_avatar_query_methods(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        seen = []

        async def fake_executor(query_request):
            seen.append(query_request["type"])
            return {
                "type": "scene.query_response",
                "request_id": query_request["request_id"],
                "method": query_request["type"],
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        avatar_result = await coordinator.execute_query(
            {"method": "scene.query_avatars", "params": {}}
        )
        motion_result = await coordinator.execute_query(
            {"method": "scene.query_motions", "params": {}}
        )

        self.assertEqual(avatar_result["method"], "scene.query_avatars")
        self.assertEqual(motion_result["method"], "scene.query_motions")
        self.assertEqual(seen, ["scene.query_avatars", "scene.query_motions"])

    async def test_rejects_legacy_avatar_attachment_points_query(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        async def fake_executor(_query_request):
            raise AssertionError("legacy attachment point query must not be executed")

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)
        legacy_method = "scene.query_avatar" + "_attachment_points"

        with self.assertRaises(ValueError):
            await coordinator.execute_query(
                {"method": legacy_method, "params": {"avatar_id": "avatar_main"}}
            )

    async def test_accepts_avatar_validation_query_methods(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        seen = []

        async def fake_executor(query_request):
            seen.append(query_request["type"])
            return {
                "type": "scene.query_response",
                "request_id": query_request["request_id"],
                "method": query_request["type"],
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        await coordinator.execute_query(
            {"method": "scene.query_avatar_candidates", "params": {"target_alias": "CoffeeMaker"}}
        )
        await coordinator.execute_query(
            {"method": "scene.validate_avatar_placement", "params": {"target_alias": "CoffeeMaker"}}
        )
        await coordinator.execute_query(
            {"method": "scene.capture_validation_views", "params": {"target_alias": "CoffeeMaker"}}
        )

        self.assertEqual(
            seen,
            [
                "scene.query_avatar_candidates",
                "scene.validate_avatar_placement",
                "scene.capture_validation_views",
            ],
        )

    async def test_accepts_scene_execute_actions_requests(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        seen = []

        async def fake_executor(query_request):
            seen.append(query_request["type"])
            return {
                "type": "scene.execute_actions_response",
                "request_id": query_request["request_id"],
                "status": "success",
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        result = await coordinator.execute_query(
            {
                "method": "scene.execute_actions",
                "params": {
                    "scene_version": 3,
                    "actions": [
                        {"target_id": "", "action_type": "spawn_avatar", "parameters": {"avatar_id": "avatar_main"}}
                    ],
                },
            }
        )

        self.assertEqual(result["type"], "scene.execute_actions_response")
        self.assertEqual(seen, ["scene.execute_actions"])

    async def test_accepts_recording_status_query(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        seen = []

        async def fake_executor(query_request):
            seen.append(query_request["type"])
            return {
                "type": "scene.query_response",
                "request_id": query_request["request_id"],
                "method": query_request["type"],
                "recording": {"is_recording": False},
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        result = await coordinator.execute_query(
            {"method": "scene.query_recording_status", "params": {}}
        )

        self.assertEqual(result["method"], "scene.query_recording_status")
        self.assertEqual(result["recording"]["is_recording"], False)
        self.assertEqual(seen, ["scene.query_recording_status"])

    async def test_accepts_sensor_inventory_query(self):
        from core.query_first.coordinator import QueryFirstCoordinator

        seen = []

        async def fake_executor(query_request):
            seen.append(query_request)
            return {
                "type": "scene.query_response",
                "request_id": query_request["request_id"],
                "method": query_request["type"],
                "sensors": [],
            }

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)

        result = await coordinator.execute_query(
            {"method": "scene.query_sensors", "params": {"sensor_type": "IMU"}}
        )

        self.assertEqual(result["method"], "scene.query_sensors")
        self.assertEqual(seen[0]["type"], "scene.query_sensors")
        self.assertEqual(seen[0]["sensor_type"], "IMU")
