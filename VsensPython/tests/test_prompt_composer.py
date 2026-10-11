import unittest

from core.prompting.composer import PromptComposer
from core.prompting.registry import load_feature_registry
from vsens_openai import VsensOpenAI


class TestPromptComposer(unittest.TestCase):
    def test_compose_includes_core_and_enabled_features(self):
        composer = PromptComposer(project_root=".")

        prompt = composer.compose(
            enabled_features=["control", "clarification", "proposal", "scene_query"]
        )

        self.assertTrue(
            "You are Vsens+" in prompt or "You are VsensAgent" in prompt,
            "expected identity header in prompt",
        )
        self.assertIn("<clarification>", prompt)
        self.assertIn("<proposal>", prompt)
        self.assertIn("<control>", prompt)
        self.assertIn("scene.query_objects", prompt)
        self.assertIn("spawn_avatar", prompt)
        self.assertIn("load_avatar_motion", prompt)

    def test_compose_omits_disabled_feature_sections(self):
        composer = PromptComposer(project_root=".")

        prompt = composer.compose(enabled_features=["control"])

        self.assertIn("<control>", prompt)
        self.assertNotIn("<clarification>", prompt)
        self.assertNotIn("<proposal>", prompt)

    def test_clarification_module_teaches_when_to_ask(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "clarification"])

        self.assertIn("Use <clarification>", prompt)
        self.assertIn("when the user intent is ambiguous", prompt)
        self.assertIn("respond with exactly one <clarification> block", prompt)

    def test_proposal_module_teaches_option_generation(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "proposal"])

        self.assertIn("Use <proposal>", prompt)
        self.assertIn("\"options\"", prompt)
        self.assertIn("present candidate plans before executing them", prompt)

    def test_core_policy_defines_response_mode_priority(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose()

        lowered = prompt.lower()
        self.assertIn("Choose exactly one primary response mode per turn", prompt)
        self.assertIn("clarification over proposal", lowered)
        self.assertIn("proposal over control", lowered)
        self.assertIn("control over plain conversation", lowered)

    def test_core_policy_covers_query_and_job_routing(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose()

        lowered = prompt.lower()
        self.assertIn("use query-first reasoning", lowered)
        self.assertIn("long-running work", lowered)
        self.assertIn("job-oriented", lowered)

    def test_default_prompt_teaches_avatar_prerequisites_for_motion_and_body_sensors(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose()

        self.assertIn("avatar-before-motion", prompt)
        self.assertIn("avatar-before-body-sensor", prompt)
        self.assertIn("scene.query_avatars", prompt)
        self.assertIn("attachment_points", prompt)
        self.assertIn("spawn_avatar", prompt)
        self.assertIn("load_avatar_motion", prompt)
        self.assertIn("attach_mode=avatar_joint", prompt)
        self.assertNotIn("scene.query_avatar" + "_attachment_points", prompt)
        self.assertNotIn("confirm the managed avatar", prompt)

    def test_default_prompt_includes_static_sensor_knowledge(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose()

        self.assertIn("Available sensor types", prompt)
        self.assertIn("OPTICAL", prompt)
        self.assertIn("DISTANCE", prompt)
        self.assertIn("IMU", prompt)
        self.assertIn("Unity world space", prompt)
        self.assertIn("SENSOR_TYPE-NN", prompt)

    def test_control_prompt_teaches_sensor_visual_defaults(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control"])

        self.assertIn('default `show_visualization` to `"true"`', prompt)
        self.assertIn('default `show_data_graph` to `"false"`', prompt)

    def test_control_prompt_requires_sensor_inventory_before_edits(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "scene_query"])

        self.assertIn("scene.query_sensors", prompt)
        self.assertIn('"update"', prompt)
        self.assertIn('"create"', prompt)
        self.assertIn("do not guess ids", prompt)

    def test_control_prompt_teaches_delegate_task_contract(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control"])

        self.assertIn("delegate_task", prompt)
        self.assertIn("task_type", prompt)
        self.assertIn("analysis", prompt)
        self.assertIn("goal", prompt)
        self.assertIn("selector", prompt)

    def test_control_prompt_includes_coffee_dataset_avatar_flow_example(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control"])

        self.assertIn("coffee dataset example", prompt)
        self.assertIn("scene.query_avatars", prompt)
        self.assertIn("attachment_points", prompt)
        self.assertNotIn("scene.query_avatar" + "_attachment_points", prompt)
        self.assertIn("spawn_avatar", prompt)
        self.assertIn('"action": "set_sensor"', prompt)
        self.assertIn("load_avatar_motion", prompt)

    def test_prompt_rejects_avatar_sensor_pseudo_actions(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["control", "experiment"])

        self.assertIn("ensure_avatar", prompt)
        self.assertIn("attach_imu", prompt)
        self.assertIn("use `spawn_avatar`", prompt)
        self.assertIn("use `set_sensor`", prompt)

    def test_default_prompt_teaches_experiment_collection_workflows(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose()

        self.assertIn("<experiment>", prompt)
        self.assertIn("object-state workflow", prompt)
        self.assertIn("embodied-human/activity workflow", prompt)
        self.assertIn("start_sensor_recording", prompt)
        self.assertIn("mark_recording_phase", prompt)
        self.assertIn("stop_sensor_recording", prompt)
        self.assertIn("scene.query_recording_status", prompt)
        self.assertIn("stove", prompt)
        self.assertIn("sink", prompt)
        self.assertIn("phase", prompt)
        self.assertIn("actor_mode", prompt)
        self.assertIn("target_alias", prompt)


class TestPromptRegistry(unittest.TestCase):
    def test_registry_contains_protocol_backed_features(self):
        registry = load_feature_registry(project_root=".")

        for feature_name in ("control", "clarification", "proposal", "job", "experiment", "scene_query"):
            self.assertIn(feature_name, registry)

    def test_registry_declares_prompt_files(self):
        registry = load_feature_registry(project_root=".")

        self.assertTrue(registry["clarification"].prompt_files)
        self.assertTrue(registry["proposal"].prompt_files)
        self.assertTrue(registry["scene_query"].prompt_files)

    def test_scene_query_module_teaches_query_first_lookup(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["scene_query"])

        self.assertIn("query-first", prompt)
        self.assertIn("scene.query_objects", prompt)
        self.assertIn("scene.query_surfaces", prompt)
        self.assertIn("alias-first", prompt)
        self.assertIn("object_selection.request", prompt)

    def test_scene_query_module_teaches_internal_query_block(self):
        composer = PromptComposer(project_root=".")
        prompt = composer.compose(enabled_features=["scene_query"])

        self.assertIn("<query>", prompt)
        self.assertIn("scene.query_relations", prompt)
        self.assertIn("scene.query_summary", prompt)
        self.assertIn("scene.query_avatars", prompt)
        self.assertIn("scene.query_sensors", prompt)
        self.assertIn("attachment_points", prompt)
        self.assertNotIn("scene.query_avatar" + "_attachment_points", prompt)
        self.assertIn("scene.query_motions", prompt)


class TestVsensOpenAIPromptLoading(unittest.TestCase):
    def test_default_system_prompt_is_composed(self):
        agent = VsensOpenAI.__new__(VsensOpenAI)
        agent_prompt = VsensOpenAI._load_system_prompt(agent, None)

        self.assertTrue(
            "You are Vsens+" in agent_prompt or "You are VsensAgent" in agent_prompt,
            "expected identity header in composed system prompt",
        )
        self.assertIn("<clarification>", agent_prompt)
        self.assertIn("<proposal>", agent_prompt)
