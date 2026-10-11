import shutil
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class _FakeMessagesAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessagesAPI(responses)


def _tool_use(tool_id: str, name: str, tool_input: dict):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _response(stop_reason: str, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class TestTodoManager(unittest.TestCase):
    def test_update_renders_progress(self):
        from core.delegation.runner import TodoManager

        manager = TodoManager()
        rendered = manager.update(
            [
                {"id": "1", "text": "Inspect data", "status": "completed"},
                {"id": "2", "text": "Compare placements", "status": "in_progress"},
            ]
        )

        self.assertIn("[x] #1: Inspect data", rendered)
        self.assertIn("[>] #2: Compare placements", rendered)
        self.assertIn("(1/2 completed)", rendered)


class TestAnthropicSubagentRunner(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(__file__).resolve().parent / "_tmp" / f"subagent_runner_{uuid.uuid4().hex[:8]}"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.workspace, ignore_errors=True))

    def test_run_executes_tool_loop_and_returns_completed_result(self):
        from core.delegation.runner import AnthropicSubagentRunner

        (self.workspace / "notes.txt").write_text("door placement notes", encoding="utf-8")
        fake_client = _FakeClient(
            [
                _response(
                    "tool_use",
                    _tool_use("tool_1", "read_file", {"path": "notes.txt"}),
                    _tool_use(
                        "tool_2",
                        "todo",
                        {
                            "items": [
                                {"id": "1", "text": "Read notes", "status": "completed"},
                                {"id": "2", "text": "Return result", "status": "in_progress"},
                            ]
                        },
                    ),
                ),
                _response(
                    "tool_use",
                    _tool_use(
                        "tool_3",
                        "return_result",
                        {
                            "status": "completed",
                            "report_text": "Placement B performs best.",
                            "artifacts": [{"path": "artifacts/chart.png", "kind": "image"}],
                            "working_notes": "Compared recent runs.",
                        },
                    ),
                ),
            ]
        )
        runner = AnthropicSubagentRunner(client=fake_client, model="fake-model")

        result = runner.run(
            workspace=self.workspace,
            task_payload={"task_type": "analysis", "goal": "Compare recordings.", "recording_paths": []},
            session_state={"history": []},
        )

        self.assertEqual(result["status"], "completed")
        self.assertIn("Placement B", result["report_text"])
        self.assertEqual(result["artifacts"][0]["kind"], "image")
        self.assertEqual(len(fake_client.messages.calls), 2)
        second_call_messages = fake_client.messages.calls[1]["messages"]
        tool_results = second_call_messages[-1]["content"]
        self.assertEqual(tool_results[0]["type"], "tool_result")
        self.assertIn("door placement notes", tool_results[0]["content"])
        self.assertIn("[x] #1: Read notes", tool_results[1]["content"])

    def test_run_returns_needs_agent_input_from_tool(self):
        from core.delegation.runner import AnthropicSubagentRunner

        fake_client = _FakeClient(
            [
                _response(
                    "tool_use",
                    _tool_use(
                        "tool_1",
                        "ask_main_agent",
                        {"questions": ["Which placements should be compared?"]},
                    ),
                )
            ]
        )
        runner = AnthropicSubagentRunner(client=fake_client, model="fake-model")

        result = runner.run(
            workspace=self.workspace,
            task_payload={"task_type": "analysis", "goal": "Compare recordings.", "recording_paths": []},
            session_state={"history": []},
        )

        self.assertEqual(result["status"], "needs_agent_input")
        self.assertEqual(result["questions_for_agent"], ["Which placements should be compared?"])

    def test_run_injects_todo_reminder_after_three_rounds_without_todo(self):
        from core.delegation.runner import AnthropicSubagentRunner

        (self.workspace / "notes.txt").write_text("door placement notes", encoding="utf-8")
        fake_client = _FakeClient(
            [
                _response("tool_use", _tool_use("tool_1", "read_file", {"path": "notes.txt"})),
                _response("tool_use", _tool_use("tool_2", "read_file", {"path": "notes.txt"})),
                _response("tool_use", _tool_use("tool_3", "read_file", {"path": "notes.txt"})),
                _response(
                    "tool_use",
                    _tool_use(
                        "tool_4",
                        "return_result",
                        {"status": "completed", "report_text": "done", "artifacts": [], "working_notes": ""},
                    ),
                ),
            ]
        )
        runner = AnthropicSubagentRunner(client=fake_client, model="fake-model")

        result = runner.run(
            workspace=self.workspace,
            task_payload={"task_type": "analysis", "goal": "Compare recordings.", "recording_paths": []},
            session_state={"history": []},
        )

        self.assertEqual(result["status"], "completed")
        fourth_call_messages = fake_client.messages.calls[3]["messages"]
        reminder_blocks = fourth_call_messages[-1]["content"]
        self.assertTrue(any("Update your todos" in block.get("text", "") for block in reminder_blocks if block["type"] == "text"))

    def test_analysis_system_prompt_encourages_figures_and_artifacts(self):
        from core.delegation.runner import AnthropicSubagentRunner

        prompt = AnthropicSubagentRunner._build_system_prompt(workspace=self.workspace)

        self.assertIn("analysis tasks", prompt)
        self.assertIn("figures", prompt)
        self.assertIn("PNG", prompt)
        self.assertIn("return_result", prompt)
        self.assertIn("artifacts", prompt)
        self.assertIn("not mandatory", prompt)

    def test_initial_prompt_guides_recording_comparison_analysis(self):
        from core.delegation.runner import AnthropicSubagentRunner

        prompt = AnthropicSubagentRunner._build_initial_prompt(
            task_payload={
                "task_type": "analysis",
                "goal": "Compare the latest coffee-making recordings.",
                "recording_paths": ["inputs/run_a/IMU.csv", "inputs/run_b/IMU.csv"],
            },
            session_state={"history": []},
        )

        self.assertIn("recording comparison", prompt)
        self.assertIn("decision criteria", prompt)
        self.assertIn("key metrics", prompt)
        self.assertIn("recommendation", prompt)
        self.assertIn("visualization", prompt)

    def test_init_loads_project_env_without_overriding_environment(self):
        from core.delegation.runner import AnthropicSubagentRunner

        fake_client = _FakeClient([])

        with patch("core.delegation.runner.load_dotenv", return_value=True) as load_dotenv:
            AnthropicSubagentRunner(client=fake_client, model="fake-model")

        from pathlib import Path
        project_root = Path(__file__).resolve().parents[1]
        load_dotenv.assert_called_once_with(dotenv_path=project_root / ".env.vsensagent", override=False)
