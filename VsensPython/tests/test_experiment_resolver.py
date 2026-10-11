import unittest

from core.experiments.resolver import ExperimentPreflightResolver


class TestExperimentPreflightResolver(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_coffee_and_stove_from_scene_snapshot_without_selection(self):
        selection_calls = []

        async def object_selector(_request):
            selection_calls.append(_request)
            raise AssertionError("object selector should not be needed")

        resolver = ExperimentPreflightResolver(
            scene_snapshot={
                "CoffeeMaker": {"position": [1.689, 1.266, -1.026], "size": [0.224, 0.333, 0.19]},
                "Stove": {"position": [1.692, 0.57, -0.391], "size": [0.67, 0.964, 0.834]},
            },
            object_selector=object_selector,
        )

        resolved = await resolver.resolve(
            {
                "goal": "用一个传感器检测用户是否在煮咖啡还是在做菜",
                "requires_avatar": False,
                "recording": {"sensors": ["DISTANCE-01"], "auto_upload": True},
                "phases": [
                    {"label": "making_coffee", "duration_s": 10, "motion_description": "make coffee"},
                    {"label": "cooking", "duration_s": 10, "motion_description": "cook at stove"},
                ],
            }
        )

        self.assertTrue(resolved["requires_avatar"])
        self.assertEqual(resolved["actor_mode"], "avatar")
        self.assertEqual(resolved["phases"][0]["target_alias"], "CoffeeMaker")
        self.assertEqual(resolved["phases"][1]["target_alias"], "Stove")
        self.assertEqual(resolved["resolved_anchors"]["making_coffee"]["alias"], "CoffeeMaker")
        self.assertEqual(resolved["resolved_anchors"]["cooking"]["alias"], "Stove")
        self.assertEqual(selection_calls, [])

    async def test_alias_lookup_falls_back_without_tags_when_tag_filter_misses(self):
        requests = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_objects" and request.get("tags"):
                return {
                    "type": "scene.query_response",
                    "method": "scene.query_objects",
                    "scene_version": 1,
                    "objects": [],
                }
            return {
                "type": "scene.query_response",
                "method": "scene.query_objects",
                "scene_version": 1,
                "objects": [
                    {
                        "id": "obj_stove",
                        "alias": "Stove",
                        "tags": ["structure"],
                        "position": {"x": 1.692, "y": 0.57, "z": -0.391},
                        "bounds_size": {"x": 0.67, "y": 0.964, "z": 0.834},
                    }
                ],
            }

        resolver = ExperimentPreflightResolver(query_executor=query_executor)

        resolved = await resolver.resolve(
            {
                "goal": "检测是否在做饭",
                "actor_mode": "manual",
                "recording": {"sensors": ["DISTANCE-01"], "auto_upload": False},
                "phases": [{"label": "cooking_at_stove", "duration_s": 5}],
            }
        )

        self.assertEqual(resolved["phases"][0]["target_alias"], "Stove")
        self.assertEqual(resolved["resolved_anchors"]["cooking_at_stove"]["object_id"], "obj_stove")
        self.assertTrue(
            any(
                request["type"] == "scene.query_objects"
                and request.get("aliases") == ["Stove", "Cooktop", "Oven"]
                and request.get("tags") == []
                for request in requests
            )
        )

    async def test_missing_anchor_requests_object_selection_and_uses_reply(self):
        selection_requests = []

        async def object_selector(request):
            selection_requests.append(request)
            return {
                "selection_id": request["selection_id"],
                "selected_object_id": "obj_custom_stove",
                "selected_alias": "CustomStove",
                "world_position": [1.0, 0.5, 2.0],
                "cancelled": False,
            }

        resolver = ExperimentPreflightResolver(object_selector=object_selector)

        resolved = await resolver.resolve(
            {
                "goal": "检测是否在做饭",
                "actor_mode": "manual",
                "phases": [{"label": "cooking", "duration_s": 5}],
            }
        )

        self.assertEqual(len(selection_requests), 1)
        self.assertEqual(selection_requests[0]["type"], "object_selection.request")
        self.assertEqual(selection_requests[0]["candidate_aliases"], ["Stove", "Cooktop", "Oven"])
        self.assertEqual(resolved["phases"][0]["target_alias"], "CustomStove")
        self.assertEqual(resolved["resolved_anchors"]["cooking"]["object_id"], "obj_custom_stove")

    async def test_normalizes_pseudo_avatar_imu_setup_actions_before_runner(self):
        requests = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "avatars": [],
                }
            raise AssertionError(request["type"])

        resolver = ExperimentPreflightResolver(
            query_executor=query_executor,
            scene_snapshot={
                "CoffeeMaker": {"position": [1.0, 0.0, 2.0]},
                "Sink": {"position": [2.0, 0.0, 3.0]},
            },
        )

        resolved = await resolver.resolve(
            {
                "goal": "通过 IMU 区分做咖啡和洗碗",
                "actor_mode": "avatar",
                "setup_actions": [
                    {
                        "action": "ensure_avatar",
                        "target": "avatar_main",
                        "parameters": {"prefab_key": "smplx_male"},
                    },
                    {
                        "action": "attach_imu",
                        "target": "IMU-01",
                        "parameters": {"joint_name": "right_wrist"},
                    },
                    {
                        "action": "attach_imu",
                        "target": "IMU-02",
                        "parameters": {"joint_name": "waist"},
                    },
                ],
                "phases": [
                    {"label": "making_coffee", "duration_s": 15, "target_alias": "CoffeeMaker"},
                    {"label": "washing_dishes", "duration_s": 15, "target_alias": "Sink"},
                ],
            }
        )

        self.assertEqual([request["type"] for request in requests], ["scene.query_avatars"])
        self.assertEqual(
            [action["action"] for action in resolved["setup_actions"]],
            ["spawn_avatar", "set_sensor", "set_sensor"],
        )
        self.assertEqual(resolved["setup_actions"][0]["target"], "avatar_main")
        self.assertEqual(resolved["setup_actions"][0]["parameters"]["avatar_id"], "avatar_main")
        self.assertEqual(resolved["setup_actions"][1]["parameters"]["sensor_type"], "IMU")
        self.assertEqual(resolved["setup_actions"][1]["parameters"]["attach_mode"], "avatar_joint")
        self.assertEqual(resolved["setup_actions"][1]["parameters"]["avatar_id"], "avatar_main")
        self.assertEqual(resolved["setup_actions"][1]["parameters"]["joint_name"], "right_wrist")
        self.assertEqual(resolved["setup_actions"][2]["parameters"]["joint_name"], "waist")

    async def test_existing_avatar_drops_ensure_avatar_but_keeps_imu_attachment(self):
        async def query_executor(request):
            if request["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "avatars": [{"avatar_id": "avatar_main"}],
                }
            raise AssertionError(request["type"])

        resolver = ExperimentPreflightResolver(query_executor=query_executor)

        resolved = await resolver.resolve(
            {
                "goal": "attach wearable IMU",
                "actor_mode": "avatar",
                "setup_actions": [
                    {"action": "ensure_avatar", "target": "avatar_main", "parameters": {}},
                    {"action": "attach_imu", "target": "IMU-01", "parameters": {"joint_name": "right_wrist"}},
                ],
                "phases": [{"label": "baseline", "duration_s": 1}],
            }
        )

        self.assertEqual([action["action"] for action in resolved["setup_actions"]], ["set_sensor"])
        self.assertEqual(resolved["setup_actions"][0]["target"], "IMU-01")
