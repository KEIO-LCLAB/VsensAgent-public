import unittest
from unittest.mock import AsyncMock, MagicMock
import asyncio

from core.agent_core import AgentCore
from core.prompting.composer import PromptComposer
from core.skills.skill_registry import SkillRegistry


def _make_agent():
    agent = MagicMock()
    agent.client = MagicMock()
    agent._last_token_stats = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
    }
    return agent


class _HistoryTrackingAgent:
    def __init__(self, replies):
        self.client = MagicMock()
        self._last_token_stats = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
        }
        self._replies = list(replies)
        self.send_calls = []
        self.appended_exchanges = []

    def send_message(self, user_input: str, persist: bool = True) -> str:
        self.send_calls.append({"user_input": user_input, "persist": persist})
        reply = self._replies.pop(0)
        if persist:
            self.append_exchange(user_input, reply)
        return reply

    def append_exchange(self, user_input: str, reply: str) -> None:
        self.appended_exchanges.append({"user_input": user_input, "reply": reply})


class TestAgentCoreProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_default_prompt_stack_includes_structured_collaboration_features(self):
        prompt = PromptComposer(project_root="VsensPython").compose()

        self.assertIn("<clarification>", prompt)
        self.assertIn("<proposal>", prompt)
        self.assertIn("parameters.sensor_type", prompt)
        self.assertIn('"action": "set_sensor"', prompt)
        self.assertIn("scene.query_avatar_candidates", prompt)
        self.assertIn("scene.validate_avatar_placement", prompt)
        self.assertIn("scene.capture_validation_views", prompt)

    async def test_plain_text_returns_conversation_reply(self):
        agent = _make_agent()
        agent.send_message.return_value = "I can help you explore sensor placement."
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        result = await core.handle_text("Help me", {})

        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["reply"], "I can help you explore sensor placement.")
        self.assertEqual(result["control"]["actions"], [])

    async def test_proposal_block_returns_proposal_message(self):
        agent = _make_agent()
        agent.send_message.return_value = """I found two wall-mount candidates.

<proposal>
{
  "proposal_id": "prop_1",
  "title": "Wall placement options",
  "summary": "Two good wall placements near the fridge.",
  "options": [
    {"id": "cand_1", "label": "East wall", "description": "Best coverage"},
    {"id": "cand_2", "label": "North wall", "description": "Lower occlusion"}
  ]
}
</proposal>
"""
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        result = await core.handle_text("Suggest placements", {})

        self.assertEqual(result["type"], "proposal.ready")
        self.assertEqual(result["proposal_id"], "prop_1")
        self.assertEqual(result["title"], "Wall placement options")
        self.assertEqual(len(result["options"]), 2)
        self.assertEqual(result["reply"], "I found two wall-mount candidates.")

    async def test_clarification_block_returns_clarification_request(self):
        agent = _make_agent()
        agent.send_message.return_value = """I need you to narrow the target first.

<clarification>
{
  "question_id": "q_1",
  "prompt": "Which appliance should I optimize for?",
  "selection_mode": "single",
  "options": [
    {"id": "fridge", "label": "Fridge"},
    {"id": "coffee_maker", "label": "Coffee maker"}
  ]
}
</clarification>
"""
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        result = await core.handle_text("Optimize placement", {})

        self.assertEqual(result["type"], "clarification.request")
        self.assertEqual(result["question_id"], "q_1")
        self.assertEqual(result["prompt"], "Which appliance should I optimize for?")
        self.assertEqual(result["selection_mode"], "single")
        self.assertEqual(result["reply"], "I need you to narrow the target first.")

    async def test_query_result_is_injected_before_final_reply(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need to inspect the object first.

<query>
{
  "method": "scene.query_objects",
  "params": {
    "aliases": ["CoffeeMaker"]
  },
  "reason": "Need object details."
}
</query>
""",
            """I found the target.

<proposal>
{
  "proposal_id": "p1",
  "title": "Placement candidates",
  "summary": "Two candidates.",
  "options": [
    {"id": "c1", "label": "Near coffee maker"}
  ]
}
</proposal>
""",
        ]
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        async def fake_query_executor(query_payload):
            self.assertEqual(query_payload["type"], "scene.query_objects")
            self.assertTrue(query_payload["request_id"].startswith("qry_"))
            return {
                "type": "scene.query_response",
                "request_id": query_payload["request_id"],
                "method": "scene.query_objects",
                "scene_version": 3,
                "objects": [{"id": "obj_coffee_01", "alias": "CoffeeMaker"}],
            }

        result = await core.handle_text(
            "Suggest placements near the coffee maker",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(result["type"], "proposal.ready")
        self.assertEqual(result["proposal_id"], "p1")
        self.assertEqual(result["reply"], "I found the target.")

    async def test_prompt_includes_current_scene_even_after_heartbeat_memory_exists(self):
        agent = _make_agent()
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)
        core.memory.scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "Door_B": {"properties": ["with_state"], "state": "closed"},
        }
        core.memory.last_scene = {
            "Door_A": {"properties": ["with_state"], "state": "closed"},
            "Door_B": {"properties": ["with_state"], "state": "closed"},
        }
        core.memory_manager.build_context = MagicMock(return_value="")

        prompt = core._build_prompt("place a distance sensor on the door")

        self.assertIn("Current scene", prompt)
        self.assertIn("Door_A", prompt)
        self.assertIn("Door_B", prompt)

    async def test_query_objects_multiple_candidates_uses_object_selection(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need the target door.

<query>
{
  "method": "scene.query_objects",
  "params": {
    "aliases": ["Door"]
  },
  "reason": "Need the target door before placing the distance sensor."
}
</query>
""",
            """I can place the distance sensor on the selected door.

<control>
[
  {
    "action": "set_sensor",
    "target": "DISTANCE-01",
    "parameters": {
      "sensor_type": "DISTANCE",
      "operation": "create",
      "attach_mode": "object",
      "parent": "Door_A"
    }
  }
]
</control>
""",
        ]
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)
        selections = []

        async def fake_query_executor(query_payload):
            return {
                "type": "scene.query_response",
                "request_id": query_payload["request_id"],
                "method": "scene.query_objects",
                "scene_version": 3,
                "objects": [
                    {"id": "Door_A", "alias": "Door_A", "tags": ["state_object"]},
                    {"id": "Door_B", "alias": "Door_B", "tags": ["state_object"]},
                ],
            }

        async def fake_object_selector(request):
            selections.append(request)
            return {
                "selection_id": request["selection_id"],
                "selected_object_id": "Door_A",
                "selected_alias": "Door_A",
                "world_position": [-1.25, 1.17, -0.49],
                "cancelled": False,
            }

        result = await core.handle_text(
            "I want to place a distance sensor on the door",
            {},
            query_executor=fake_query_executor,
            object_selector=fake_object_selector,
        )

        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]["type"], "object_selection.request")
        self.assertEqual(selections[0]["candidate_aliases"], ["Door_A", "Door_B"])
        follow_up_prompt = agent.send_message.call_args_list[1].args[0]
        self.assertIn("Selected object", follow_up_prompt)
        self.assertIn("Door_A", follow_up_prompt)

    async def test_avatar_imu_attach_uses_attachment_points_from_avatar_query(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I will inspect the managed avatar before binding the IMU.

<query>
{
  "method": "scene.query_avatars",
            "params": {},
            "reason": "Need managed avatar before binding an IMU."
}
</query>
""",
            """avatar_main includes right_wrist in attachment_points, so I will bind the IMU now.

<control>
{
  "actions": [
    {
      "target": "IMU-01",
      "action": "set_sensor",
      "parameters": {
        "sensor_type": "IMU",
        "attach_mode": "avatar_joint",
        "avatar_id": "avatar_main",
        "joint_name": "right_wrist",
        "show_visualization": "true",
        "show_data_graph": "false"
      }
    }
  ]
}
</control>
""",
        ]
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)
        queries = []

        async def fake_query_executor(query_payload):
            queries.append(query_payload)
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "avatars": [
                        {
                            "avatar_id": "avatar_main",
                            "attachment_points": [
                                {"joint_name": "right_wrist", "label": "Right wrist"},
                                {"joint_name": "left_wrist", "label": "Left wrist"},
                            ],
                        }
                    ],
                }
            raise AssertionError(query_payload["type"])

        result = await core.handle_text(
            "attach the IMU to the right wrist",
            {"avatars": [{"avatar_id": "avatar_main"}]},
            query_executor=fake_query_executor,
        )

        self.assertEqual([query["type"] for query in queries], ["scene.query_avatars"])
        self.assertEqual(result["control"]["actions"][0]["target"], "IMU-01")
        self.assertEqual(result["control"]["actions"][0]["action"], "set_sensor")
        self.assertEqual(result["control"]["actions"][0]["parameters"]["attach_mode"], "avatar_joint")
        self.assertEqual(result["control"]["actions"][0]["parameters"]["avatar_id"], "avatar_main")
        self.assertEqual(result["control"]["actions"][0]["parameters"]["joint_name"], "right_wrist")

    async def test_agent_core_does_not_keep_avatar_attachment_synthesis_helpers(self):
        self.assertFalse(hasattr(AgentCore, "_maybe_synthesize_avatar_attachment_from_avatar_query"))
        self.assertFalse(hasattr(AgentCore, "_synthesize_avatar_sensor_attachment_reply"))
        self.assertFalse(hasattr(AgentCore, "_select_avatar_attachment_sensor_id"))
        self.assertFalse(hasattr(AgentCore, "_select_avatar_attachment_joint"))

    async def test_avatar_candidate_query_is_followed_by_hard_validation_and_capture_metadata(self):
        motion_json = "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}"
        motion_json_for_reply = motion_json.replace('"', '\\"')
        agent = _make_agent()
        agent.review_validation_images = None
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 3
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            f"""I'll place the avatar at the validated coffee-making spot, then load and play the motion.

<control>
{{
  "actions": [
    {{
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {{
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "load_avatar_motion",
      "parameters": {{
        "motion_id": "motion_make_coffee",
        "motion_name": "make_coffee_basic",
        "motion_json": "{motion_json_for_reply}",
        "source_text": "make coffee"
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {{
        "speed": 1.0,
        "loop": false
      }}
    }}
  ]
}}
</control>
""",
        ]
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        seen_methods = []

        async def fake_query_executor(query_payload):
            seen_methods.append(query_payload["type"])
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }

            if query_payload["type"] == "scene.validate_avatar_placement":
                self.assertEqual(query_payload["target_object_id"], "obj_coffee_01")
                self.assertEqual(query_payload["task_hint"], "make_coffee")
                self.assertEqual(query_payload["position"], [1.9, 0.0, 4.9])
                self.assertEqual(query_payload["rotation"], [0, 180, 0])
                self.assertEqual(query_payload["motion_json"], motion_json)
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }

            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        result = await core.handle_text(
            "place the avatar so it can make coffee naturally, validate the placement, then play a coffee-making motion",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(seen_methods, ["scene.query_avatar_candidates", "scene.validate_avatar_placement"])
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["reply"], "I'll place the avatar at the validated coffee-making spot, then load and play the motion.")
        actions = result["control"]["actions"]
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0]["parameters"]["position"], [1.9, 0.0, 4.9])
        self.assertEqual(actions[0]["parameters"]["validation_target_object_id"], "obj_coffee_01")
        self.assertEqual(actions[0]["parameters"]["validation_task_hint"], "make_coffee")
        self.assertEqual(actions[0]["parameters"]["validator_context"], "validator_coffee")
        self.assertEqual(actions[0]["parameters"]["validation_candidate_id"], "avatar_cand_000")
        self.assertEqual(len(actions[0]["parameters"]["validation_candidates"]), 1)
        self.assertEqual(actions[0]["parameters"]["validation_candidates"][0]["candidate_id"], "avatar_cand_000")
        self.assertTrue(actions[2]["parameters"]["capture_validation_views"])

    async def test_query_timeout_falls_back_to_safe_reply(self):
        agent = _make_agent()
        agent.send_message.return_value = """I need to inspect the object first.

<query>
{
  "method": "scene.query_objects",
  "params": {
    "aliases": ["CoffeeMaker"]
  },
  "reason": "Need object details."
}
</query>
"""
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        async def fake_query_executor(_query_payload):
            raise asyncio.TimeoutError()

        result = await core.handle_text(
            "Suggest placements near the coffee maker",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(result["type"], "conversation.reply")
        self.assertIn("couldn't retrieve the latest scene details", result["reply"])
        self.assertEqual(agent.send_message.call_count, 1)

    async def test_avatar_visual_review_executes_actions_and_keeps_only_final_reply(self):
        motion_json = "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}"
        motion_json_for_reply = motion_json.replace('"', '\\"')
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 3
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            f"""I'll place the avatar at a natural coffee-making position and start the motion now.

<control>
{{
  "actions": [
    {{
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {{
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "load_avatar_motion",
      "parameters": {{
        "motion_id": "motion_make_coffee",
        "motion_name": "make_coffee_basic",
        "motion_json": "{motion_json_for_reply}",
        "source_text": "make coffee"
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {{
        "speed": 1.0,
        "loop": false
      }}
    }}
  ]
}}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(return_value='{"decision":"accept","issues":[],"reason":"Looks natural."}')
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        seen_methods = []

        async def fake_query_executor(query_payload):
            seen_methods.append(query_payload["type"])
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                self.assertEqual(query_payload["actions"][0]["action_type"], "spawn_avatar")
                self.assertEqual(query_payload["actions"][1]["action_type"], "load_avatar_motion")
                self.assertEqual(query_payload["actions"][2]["action_type"], "play_avatar_motion")
                self.assertEqual(query_payload["scene_version"], 3)
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 3,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_coffee",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/coffee_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/coffee_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        result = await core.handle_text(
            "place the avatar so it can make coffee naturally, validate the placement, then play a coffee-making motion",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(
            seen_methods,
            [
                "scene.query_avatar_candidates",
                "scene.query_avatars",
                "scene.validate_avatar_placement",
                "scene.execute_actions",
                "scene.capture_validation_views",
            ],
        )
        agent.review_validation_images.assert_called_once()
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["reply"], "I'll place the avatar at a natural coffee-making position and start the motion now.")
        self.assertEqual(result["control"]["actions"], [])

    async def test_avatar_visual_review_retries_next_candidate_when_review_fails(self):
        motion_json = "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}"
        motion_json_for_reply = motion_json.replace('"', '\\"')
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 3
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            f"""I'll place the avatar at a natural coffee-making position and start the motion now.

<control>
{{
  "actions": [
    {{
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {{
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "load_avatar_motion",
      "parameters": {{
        "motion_id": "motion_make_coffee",
        "motion_name": "make_coffee_basic",
        "motion_json": "{motion_json_for_reply}",
        "source_text": "make coffee"
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {{
        "speed": 1.0,
        "loop": false
      }}
    }}
  ]
}}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(side_effect=[
            '{"decision":"retry","issues":["too_far"],"reason":"Avatar is too far from the coffee maker."}',
            '{"decision":"accept","issues":[],"reason":"Second candidate looks good."}',
        ])
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        execute_positions = []
        execute_scene_versions = []

        async def fake_query_executor(query_payload):
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        },
                        {
                            "candidate_id": "avatar_cand_001",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front_right",
                            "position": {"x": 2.2, "y": 0.0, "z": 4.6},
                            "rotation": {"x": 0.0, "y": 160.0, "z": 0.0},
                            "score": 0.92,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        },
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                execute_scene_versions.append(query_payload["scene_version"])
                execute_positions.append(query_payload["actions"][0]["parameters"]["position"])
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 3,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_coffee",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/coffee_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/coffee_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        result = await core.handle_text(
            "place the avatar so it can make coffee naturally, validate the placement, then play a coffee-making motion",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(execute_positions, [[1.9, 0.0, 4.9], [2.2, 0.0, 4.6]])
        self.assertEqual(execute_scene_versions, [3, 4])
        self.assertEqual(agent.review_validation_images.call_count, 2)
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_avatar_visual_review_auto_inserts_motion_load_when_only_play_is_present(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 2
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            """I'll place the avatar, then start a coffee-making motion.

<control>
{
  "actions": [
    {
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }
    },
    {
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {
        "speed": 1.0,
        "loop": false
      }
    }
  ]
}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(return_value='{"decision":"accept","issues":[],"reason":"Looks good."}')
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        original_dispatch = SkillRegistry.dispatch

        def dispatch_with_fake_motion(*, action, target, parameters):
            if action == "load_avatar_motion":
                return {
                    "target": target or "avatar_main",
                    "action": "load_avatar_motion",
                    "parameters": {
                        "motion_id": "motion_auto",
                        "motion_name": "make_coffee",
                        "motion_json": "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
                        "source_text": "make coffee",
                    },
                }
            return original_dispatch(action=action, target=target, parameters=parameters)

        execute_actions = []

        async def fake_query_executor(query_payload):
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                self.assertTrue(query_payload["motion_json"])
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                execute_actions.append(query_payload["actions"])
                self.assertEqual(query_payload["actions"][0]["action_type"], "spawn_avatar")
                self.assertEqual(query_payload["actions"][1]["action_type"], "load_avatar_motion")
                self.assertEqual(query_payload["actions"][2]["action_type"], "play_avatar_motion")
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 3,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_coffee",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/coffee_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/coffee_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        with unittest.mock.patch("core.agent_core.SkillRegistry.dispatch", side_effect=dispatch_with_fake_motion):
            result = await core.handle_text(
                "place the avatar so it can make coffee naturally, validate the placement with screenshots, retry if it looks wrong, then play a coffee-making motion",
                {},
                query_executor=fake_query_executor,
            )

        self.assertEqual(len(execute_actions), 1)
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_avatar_visual_review_synthesizes_motion_when_follow_up_only_spawns_avatar(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 2
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            """I'll place the avatar at a natural coffee-making position and then start the motion.

<control>
{
  "actions": [
    {
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }
    }
  ]
}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(
            return_value='{"decision":"accept","issues":[],"reason":"Looks natural enough."}'
        )
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        original_dispatch = SkillRegistry.dispatch
        executed_action_types = []

        def dispatch_with_fake_motion(*, action, target, parameters):
            if action == "load_avatar_motion":
                return {
                    "target": target or "avatar_main",
                    "action": "load_avatar_motion",
                    "parameters": {
                        "motion_id": "motion_auto",
                        "motion_name": "make_coffee",
                        "motion_json": "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
                        "source_text": "make coffee",
                    },
                }
            return original_dispatch(action=action, target=target, parameters=parameters)

        async def fake_query_executor(query_payload):
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                self.assertEqual(
                    query_payload["motion_json"],
                    "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
                )
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                executed_action_types.extend(action["action_type"] for action in query_payload["actions"])
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": len(query_payload["actions"]),
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_coffee",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/coffee_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/coffee_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        with unittest.mock.patch("core.agent_core.SkillRegistry.dispatch", side_effect=dispatch_with_fake_motion):
            result = await core.handle_text(
                "place the avatar so it can make coffee naturally, validate the placement with screenshots, retry if it looks wrong, then play a coffee-making motion",
                {},
                query_executor=fake_query_executor,
            )

        self.assertEqual(executed_action_types, ["spawn_avatar", "load_avatar_motion", "play_avatar_motion"])
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_avatar_visual_review_synthesizes_control_when_follow_up_returns_query(self):
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 2
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            """I have good standing candidates, but I still need placement validation before I can safely execute the full sequence.

<query>
{
  "method": "scene.validate_avatar_placement",
  "params": {
    "candidate_id": "avatar_cand_000"
  },
  "reason": "Need placement validation before execution."
}
</query>
""",
        ]
        agent.review_validation_images = MagicMock(
            return_value='{"decision":"accept","issues":[],"reason":"Looks natural enough."}'
        )
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        original_dispatch = SkillRegistry.dispatch
        executed_action_types = []

        def dispatch_with_fake_motion(*, action, target, parameters):
            if action == "load_avatar_motion":
                return {
                    "target": target or "avatar_main",
                    "action": "load_avatar_motion",
                    "parameters": {
                        "motion_id": "motion_auto",
                        "motion_name": "make_coffee",
                        "motion_json": "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
                        "source_text": "make coffee",
                    },
                }
            return original_dispatch(action=action, target=target, parameters=parameters)

        async def fake_query_executor(query_payload):
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                self.assertEqual(query_payload["motion_json"], "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}")
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_coffee",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "make_coffee",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                executed_action_types.extend(action["action_type"] for action in query_payload["actions"])
                self.assertEqual(query_payload["scene_version"], 3)
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 3,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_coffee",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/coffee_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/coffee_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        with unittest.mock.patch("core.agent_core.SkillRegistry.dispatch", side_effect=dispatch_with_fake_motion):
            result = await core.handle_text(
                "place the avatar so it can make coffee naturally, validate the placement with screenshots, retry if it looks wrong, then play a coffee-making motion",
                {},
                query_executor=fake_query_executor,
            )

        self.assertEqual(executed_action_types, ["spawn_avatar", "load_avatar_motion", "play_avatar_motion"])
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_manual_pose_authority_blocks_agent_reposition_but_allows_motion_review(self):
        motion_json = "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}"
        motion_json_for_reply = motion_json.replace('"', '\\"')
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "make_coffee",
    "preferred_side": "front",
    "max_candidates": 2
  },
  "reason": "Need valid standing candidates before placing the avatar."
}
</query>
""",
            f"""I'll keep the avatar near the coffee maker and play a coffee-making motion.

<control>
{{
  "actions": [
    {{
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {{
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "load_avatar_motion",
      "parameters": {{
        "motion_id": "motion_make_coffee",
        "motion_name": "make_coffee_basic",
        "motion_json": "{motion_json_for_reply}",
        "source_text": "make coffee"
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {{
        "speed": 1.0,
        "loop": false
      }}
    }}
  ]
}}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(return_value='{"decision":"accept","issues":[],"reason":"Looks good from the current manual pose."}')
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        seen_methods = []

        async def fake_query_executor(query_payload):
            seen_methods.append(query_payload["type"])
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "make_coffee",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "make_coffee",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [
                        {
                            "avatar_id": "avatar_main",
                            "object_id": "obj_avatar_01",
                            "prefab_key": "smplx_male",
                            "position": {"x": 0.8, "y": 0.0, "z": 4.6},
                            "rotation": {"x": 0.0, "y": 140.0, "z": 0.0},
                            "motion_id": "",
                            "motion_name": "",
                            "is_playing": False,
                            "pose_authority": "manual",
                        }
                    ],
                }
            if query_payload["type"] == "scene.execute_actions":
                action_types = [action["action_type"] for action in query_payload["actions"]]
                self.assertEqual(action_types, ["load_avatar_motion", "play_avatar_motion"])
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 2,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_manual_pose",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/manual_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/manual_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        result = await core.handle_text(
            "place the avatar so it can make coffee naturally, validate the placement with screenshots, retry if it looks wrong, then play a coffee-making motion",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(
            seen_methods,
            [
                "scene.query_avatar_candidates",
                "scene.query_avatars",
                "scene.execute_actions",
                "scene.capture_validation_views",
            ],
        )
        agent.review_validation_images.assert_called_once()
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_explicit_optimize_request_allows_agent_to_override_manual_pose(self):
        motion_json = "{\"model\":\"smplx\",\"gender\":\"neutral\",\"fps\":30.0,\"betas\":[],\"poses\":[],\"trans\":[]}"
        motion_json_for_reply = motion_json.replace('"', '\\"')
        agent = _make_agent()
        agent.send_message.side_effect = [
            """I need standing candidates near the coffee maker first.

<query>
{
  "method": "scene.query_avatar_candidates",
  "params": {
    "target_alias": "CoffeeMaker",
    "task_hint": "optimize_avatar_pose",
    "preferred_side": "front",
    "max_candidates": 2
  },
  "reason": "Need valid standing candidates before optimizing the avatar pose."
}
</query>
""",
            f"""I'll optimize the avatar pose for the coffee maker and play the coffee-making motion.

<control>
{{
  "actions": [
    {{
      "target": "avatar_main",
      "action": "spawn_avatar",
      "parameters": {{
        "prefab_key": "smplx_male",
        "position": [1.9, 0.0, 4.9],
        "rotation": [0, 180, 0]
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "load_avatar_motion",
      "parameters": {{
        "motion_id": "motion_make_coffee",
        "motion_name": "make_coffee_basic",
        "motion_json": "{motion_json_for_reply}",
        "source_text": "make coffee"
      }}
    }},
    {{
      "target": "avatar_main",
      "action": "play_avatar_motion",
      "parameters": {{
        "speed": 1.0,
        "loop": false
      }}
    }}
  ]
}}
</control>
""",
        ]
        agent.review_validation_images = MagicMock(return_value='{"decision":"accept","issues":[],"reason":"Optimized pose looks good."}')
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        broadcaster.reset = AsyncMock()
        core = AgentCore(agent, broadcaster)

        saw_execute_with_pose = False

        async def fake_query_executor(query_payload):
            nonlocal saw_execute_with_pose
            if query_payload["type"] == "scene.query_avatar_candidates":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatar_candidates",
                    "scene_version": 3,
                    "target_object_id": "obj_coffee_01",
                    "task_hint": "optimize_avatar_pose",
                    "preferred_side": "front",
                    "candidates": [
                        {
                            "candidate_id": "avatar_cand_000",
                            "target_object_id": "obj_coffee_01",
                            "task_hint": "optimize_avatar_pose",
                            "preferred_side": "front",
                            "position": {"x": 1.9, "y": 0.0, "z": 4.9},
                            "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                            "score": 1.0,
                            "collision_free": True,
                            "grounded": True,
                            "reasons": [],
                        }
                    ],
                }
            if query_payload["type"] == "scene.query_avatars":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.query_avatars",
                    "scene_version": 3,
                    "avatars": [
                        {
                            "avatar_id": "avatar_main",
                            "object_id": "obj_avatar_01",
                            "prefab_key": "smplx_male",
                            "position": {"x": 0.8, "y": 0.0, "z": 4.6},
                            "rotation": {"x": 0.0, "y": 140.0, "z": 0.0},
                            "motion_id": "",
                            "motion_name": "",
                            "is_playing": False,
                            "pose_authority": "manual",
                        }
                    ],
                }
            if query_payload["type"] == "scene.validate_avatar_placement":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.validate_avatar_placement",
                    "scene_version": 3,
                    "validation": {
                        "validator_id": "validator_optimize",
                        "target_object_id": "obj_coffee_01",
                        "task_hint": "optimize_avatar_pose",
                        "valid": True,
                        "collision_free": True,
                        "grounded": True,
                        "endpoint_valid": True,
                        "trajectory_valid": True,
                        "motion_mode": "static",
                        "facing_score": 1.0,
                        "distance_to_target": 0.8,
                        "sampled_points_checked": 0,
                        "issues": [],
                    },
                }
            if query_payload["type"] == "scene.execute_actions":
                action_types = [action["action_type"] for action in query_payload["actions"]]
                self.assertEqual(action_types, ["spawn_avatar", "load_avatar_motion", "play_avatar_motion"])
                saw_execute_with_pose = True
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": query_payload["request_id"],
                    "status": "success",
                    "scene_version_before": 3,
                    "scene_version_after": 4,
                    "applied_actions": 3,
                    "errors": [],
                }
            if query_payload["type"] == "scene.capture_validation_views":
                return {
                    "type": "scene.query_response",
                    "request_id": query_payload["request_id"],
                    "method": "scene.capture_validation_views",
                    "scene_version": 4,
                    "validator_context": "validator_optimize",
                    "artifacts": [
                        {"label": "avatar_eye", "file_path": "/tmp/opt_avatar_eye.png"},
                        {"label": "user_camera", "file_path": "/tmp/opt_user_camera.png"},
                    ],
                }
            raise AssertionError(f"Unexpected query type: {query_payload['type']}")

        result = await core.handle_text(
            "optimize the avatar pose for making coffee, validate it with screenshots, and then play the coffee-making motion",
            {},
            query_executor=fake_query_executor,
        )

        self.assertTrue(saw_execute_with_pose)
        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_plain_turn_persists_only_final_exchange(self):
        agent = _HistoryTrackingAgent([
            "I can help you explore sensor placement."
        ])
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        result = await core.handle_text("Help me", {})

        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(len(agent.send_calls), 1)
        self.assertFalse(agent.send_calls[0]["persist"])
        self.assertEqual(len(agent.appended_exchanges), 1)
        self.assertIn('The user just said:\n"Help me"', agent.appended_exchanges[0]["user_input"])
        self.assertEqual(
            agent.appended_exchanges[0]["reply"],
            "I can help you explore sensor placement.",
        )

    async def test_invalid_control_action_is_not_forwarded_to_unity(self):
        agent = _make_agent()
        agent.send_message.return_value = """I'll place the sensor.

<control>
{
  "actions": [
    {
      "target": "OPTICAL-01",
      "action": "set_sensor",
      "parameters": {
        "position": [0, 0, 0],
        "rotation": [0, 0, 0]
      }
    }
  ]
}
</control>
"""
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        result = await core.handle_text("Place an optical sensor", {})

        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(result["control"]["actions"], [])

    async def test_query_first_turn_does_not_persist_internal_query_exchange(self):
        agent = _HistoryTrackingAgent([
            """I need to inspect the object first.

<query>
{
  "method": "scene.query_objects",
  "params": {
    "aliases": ["CoffeeMaker"]
  },
  "reason": "Need object details."
}
</query>
""",
            "I found the target and can recommend a placement.",
        ])
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        async def fake_query_executor(query_payload):
            return {
                "type": "scene.query_response",
                "request_id": query_payload["request_id"],
                "method": "scene.query_objects",
                "scene_version": 3,
                "objects": [{"id": "obj_coffee_01", "alias": "CoffeeMaker"}],
            }

        result = await core.handle_text(
            "Suggest placements near the coffee maker",
            {},
            query_executor=fake_query_executor,
        )

        self.assertEqual(result["type"], "conversation.reply")
        self.assertEqual(len(agent.send_calls), 2)
        self.assertFalse(agent.send_calls[0]["persist"])
        self.assertFalse(agent.send_calls[1]["persist"])
        self.assertEqual(len(agent.appended_exchanges), 1)
        persisted = agent.appended_exchanges[0]
        self.assertIn(
            'The user just said:\n"Suggest placements near the coffee maker"',
            persisted["user_input"],
        )
        self.assertNotIn("[Query-first follow-up]", persisted["user_input"])
        self.assertEqual(
            persisted["reply"],
            "I found the target and can recommend a placement.",
        )
