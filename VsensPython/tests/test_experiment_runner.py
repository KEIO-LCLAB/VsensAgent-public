import asyncio
import unittest

from core.experiments.runner import ExperimentRunner, validate_experiment_plan


class TestExperimentRunner(unittest.IsolatedAsyncioTestCase):
    def test_validate_experiment_plan_requires_labeled_durations(self):
        with self.assertRaises(ValueError):
            validate_experiment_plan(
                {
                    "goal": "collect data",
                    "phases": [{"label": "cooking"}],
                }
            )

    def test_validate_experiment_plan_rejects_non_positive_repeat(self):
        with self.assertRaises(ValueError):
            validate_experiment_plan(
                {
                    "goal": "collect data",
                    "phases": [{"label": "closed", "duration_s": 1}],
                    "repeat": 0,
                }
            )

    async def test_runs_repeated_phases_and_waits_for_snapshot(self):
        requests = []
        events = []
        sleeps = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 6,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 6 + len([item for item in requests if item["type"] == "scene.execute_actions"]),
            }

        async def sleep(duration_s):
            sleeps.append(duration_s)

        async def wait_for_snapshot():
            return {
                "timestamp_label": "kba_0_20260616_160000",
                "saved_directory": "/tmp/recording",
                "saved_files": ["DISTANCE-01_DISTANCE.csv"],
            }

        async def run_analysis(snapshot, plan):
            return {
                "reply": "Candidate threshold is 2.1m.",
                "snapshot": snapshot["timestamp_label"],
                "goal": plan["analysis"]["goal"],
            }

        runner = ExperimentRunner(
            query_executor=query_executor,
            sleep=sleep,
            wait_for_snapshot=wait_for_snapshot,
            run_analysis=run_analysis,
            on_event=lambda event: events.append(event),
        )

        result = await runner.run(
            {
                "goal": "distinguish cooking from washing dishes",
                "requires_avatar": True,
                "setup_actions": [
                    {"target": "avatar_main", "action": "spawn_avatar", "parameters": {}}
                ],
                "recording": {"sensors": ["DISTANCE-01"], "auto_upload": True},
                "phases": [
                    {"label": "cooking", "duration_s": 15, "actions": []},
                    {
                        "label": "washing_dishes",
                        "duration_s": 15,
                        "actions": [
                            {
                                "target": "avatar_main",
                                "action": "load_avatar_motion",
                                "parameters": {"motion_description": "wash dishes"},
                            }
                        ],
                    },
                ],
                "repeat": 2,
                "analysis": {"run_after": True, "goal": "find a distance threshold"},
            }
        )

        execute_requests = [request for request in requests if request["type"] == "scene.execute_actions"]
        action_batches = [request["actions"] for request in execute_requests]
        flattened_actions = [
            action["action_type"]
            for batch in action_batches
            for action in batch
        ]
        self.assertEqual(requests[0]["type"], "scene.query_summary")
        self.assertEqual(execute_requests[0]["scene_version"], 6)
        self.assertEqual(execute_requests[1]["scene_version"], 7)
        self.assertEqual(flattened_actions[0], "spawn_avatar")
        self.assertIn("start_sensor_recording", flattened_actions)
        self.assertEqual(flattened_actions.count("mark_recording_phase"), 4)
        self.assertEqual(flattened_actions[-1], "stop_sensor_recording")
        self.assertEqual(sleeps, [15.0, 15.0, 15.0, 15.0])
        self.assertEqual(result["snapshot"]["timestamp_label"], "kba_0_20260616_160000")
        self.assertEqual(result["analysis"]["reply"], "Candidate threshold is 2.1m.")
        self.assertEqual(events[0]["event"], "experiment.started")
        self.assertEqual(events[-1]["event"], "experiment.completed")

    async def test_stops_when_scene_action_response_reports_failure(self):
        requests = []
        sleeps = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 3,
                }
            execute_count = len([item for item in requests if item["type"] == "scene.execute_actions"])
            if execute_count == 2:
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": request["request_id"],
                    "status": "failed",
                    "errors": [{"message": "mark phase rejected"}],
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 3 + execute_count,
            }

        async def sleep(duration_s):
            sleeps.append(duration_s)

        runner = ExperimentRunner(query_executor=query_executor, sleep=sleep)

        with self.assertRaises(RuntimeError) as ctx:
            await runner.run(
                {
                    "goal": "collect door data",
                    "recording": {"auto_upload": False},
                    "phases": [{"label": "open", "duration_s": 1}],
                }
            )

        self.assertIn("mark phase rejected", str(ctx.exception))
        self.assertEqual([request["type"] for request in requests], [
            "scene.query_summary",
            "scene.execute_actions",
            "scene.execute_actions",
            "scene.execute_actions",
        ])
        self.assertEqual(requests[-1]["actions"][0]["action_type"], "stop_sensor_recording")
        self.assertEqual(sleeps, [])

    async def test_auto_upload_false_does_not_wait_for_snapshot_or_analyze(self):
        waited = False
        analyzed = False

        async def query_executor(request):
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 1,
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 1,
            }

        async def sleep(_duration_s):
            return None

        async def wait_for_snapshot():
            nonlocal waited
            waited = True
            return {}

        async def run_analysis(_snapshot, _plan):
            nonlocal analyzed
            analyzed = True
            return {}

        runner = ExperimentRunner(
            query_executor=query_executor,
            sleep=sleep,
            wait_for_snapshot=wait_for_snapshot,
            run_analysis=run_analysis,
        )

        result = await runner.run(
            {
                "goal": "collect a manual baseline",
                "recording": {"auto_upload": False},
                "phases": [{"label": "baseline", "duration_s": 1}],
                "analysis": {"run_after": True},
            }
        )

        self.assertFalse(waited)
        self.assertFalse(analyzed)
        self.assertIsNone(result["snapshot"])
        self.assertIsNone(result["analysis"])

    async def test_requires_avatar_false_does_not_synthesize_motion_from_phase_description(self):
        requests = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 1,
                }
            execute_count = len([item for item in requests if item["type"] == "scene.execute_actions"])
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 1 + execute_count,
            }

        runner = ExperimentRunner(query_executor=query_executor, sleep=lambda _duration: asyncio.sleep(0))

        await runner.run(
            {
                "goal": "manual cooking-vs-coffee recording",
                "requires_avatar": False,
                "actor_mode": "manual",
                "recording": {"auto_upload": False},
                "phases": [
                    {
                        "label": "making_coffee",
                        "duration_s": 1,
                        "motion_description": "A person stands at the coffee maker.",
                    }
                ],
            }
        )

        action_types = [
            action["action_type"]
            for request in requests
            if request["type"] == "scene.execute_actions"
            for action in request["actions"]
        ]
        self.assertNotIn("load_avatar_motion", action_types)
        self.assertNotIn("play_avatar_motion", action_types)

    async def test_avatar_motion_description_is_prepared_before_sending_to_unity(self):
        requests = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 5,
                }
            execute_count = len([item for item in requests if item["type"] == "scene.execute_actions"])
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 5 + execute_count,
            }

        def action_preparer(action):
            if action["action"] == "load_avatar_motion":
                params = dict(action["parameters"])
                params["motion_json"] = "{\"frames\":[]}"
                params.pop("motion_description", None)
                return {**action, "parameters": params}
            return action

        runner = ExperimentRunner(
            query_executor=query_executor,
            sleep=lambda _duration: asyncio.sleep(0),
            action_preparer=action_preparer,
        )

        await runner.run(
            {
                "goal": "avatar coffee recording",
                "requires_avatar": True,
                "recording": {"auto_upload": False},
                "phases": [
                    {
                        "label": "making_coffee",
                        "duration_s": 1,
                        "motion_description": "A person reaches for a cup.",
                    }
                ],
            }
        )

        load_actions = [
            action
            for request in requests
            if request["type"] == "scene.execute_actions"
            for action in request["actions"]
            if action["action_type"] == "load_avatar_motion"
        ]
        self.assertEqual(len(load_actions), 1)
        self.assertIn("motion_json", load_actions[0]["parameters"])
        self.assertNotIn("motion_description", load_actions[0]["parameters"])

    async def test_failure_after_recording_started_attempts_to_stop_recording(self):
        requests = []

        async def query_executor(request):
            requests.append(request)
            if request["type"] == "scene.query_summary":
                return {
                    "type": "scene.query_response",
                    "request_id": request["request_id"],
                    "scene_version": 9,
                }
            execute_count = len([item for item in requests if item["type"] == "scene.execute_actions"])
            action_types = [action["action_type"] for action in request["actions"]]
            if "set_avatar_transform" in action_types:
                return {
                    "type": "scene.execute_actions_response",
                    "request_id": request["request_id"],
                    "status": "failed",
                    "errors": [{"message": "avatar move rejected"}],
                }
            return {
                "type": "scene.execute_actions_response",
                "request_id": request["request_id"],
                "status": "success",
                "scene_version_after": 9 + execute_count,
            }

        runner = ExperimentRunner(query_executor=query_executor, sleep=lambda _duration: asyncio.sleep(0))

        with self.assertRaises(RuntimeError):
            await runner.run(
                {
                    "goal": "collect avatar data",
                    "requires_avatar": True,
                    "recording": {"auto_upload": True},
                    "phases": [
                        {
                            "label": "making_coffee",
                            "duration_s": 1,
                            "actions": [
                                {
                                    "target": "avatar_main",
                                    "action": "set_avatar_transform",
                                    "parameters": {"position": [1, 0, 2]},
                                }
                            ],
                        }
                    ],
                }
            )

        action_batches = [
            [action["action_type"] for action in request["actions"]]
            for request in requests
            if request["type"] == "scene.execute_actions"
        ]
        self.assertIn(["stop_sensor_recording"], action_batches)
