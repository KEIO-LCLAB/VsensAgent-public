from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    load_dotenv = None

try:
    from anthropic import Anthropic
except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests/imports
    Anthropic = None


def _load_runtime_env() -> None:
    if load_dotenv is None:
        return
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(dotenv_path=project_root / ".env.vsensagent", override=False)


class TodoManager:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for index, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(index + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in {"pending", "in_progress", "completed"}:
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for item in self.items if item["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


class _WorkspaceTools:
    def __init__(self, *, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.todo = TodoManager()

    def safe_path(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError(f"Path escapes workspace: {relative_path}")
        return path

    def run_shell(self, command: str) -> str:
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(token in command for token in dangerous):
            return "Error: Dangerous command blocked"
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                encoding="utf-8",
            )
            output = (result.stdout + result.stderr).strip()
            return output[:50000] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (120s)"

    def read_file(self, path: str, limit: int | None = None) -> str:
        try:
            lines = self.safe_path(path).read_text(encoding="utf-8").splitlines()
            if limit is not None and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
            return "\n".join(lines)[:50000]
        except Exception as exc:
            return f"Error: {exc}"

    def write_file(self, path: str, content: str) -> str:
        try:
            target = self.safe_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes"
        except Exception as exc:
            return f"Error: {exc}"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        try:
            target = self.safe_path(path)
            content = target.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: Text not found in {path}"
            target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"Edited {path}"
        except Exception as exc:
            return f"Error: {exc}"


class AnthropicSubagentRunner:
    TOOLS = [
        {
            "name": "bash",
            "description": "Run a shell command inside the task workspace.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file contents from the task workspace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to a file in the task workspace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "edit_file",
            "description": "Replace exact text in a workspace file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
        {
            "name": "todo",
            "description": "Update the task list and track progress on multi-step work.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["id", "text", "status"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
        {
            "name": "ask_main_agent",
            "description": "Ask the main agent for clarification when the task cannot proceed reliably.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["questions"],
            },
        },
        {
            "name": "return_result",
            "description": "Finish the delegated task and return the final result payload.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["completed", "failed"],
                    },
                    "report_text": {"type": "string"},
                    "artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "working_notes": {"type": "string"},
                    "error": {"type": "string"},
                },
                "required": ["status", "report_text"],
            },
        },
    ]

    def __init__(
        self,
        *,
        client=None,
        model: str | None = None,
        max_rounds: int = 24,
        max_tokens: int = 12000,
    ) -> None:
        _load_runtime_env()
        self.client = client or self._build_default_client()
        self.model = model or os.environ.get("ANTHROPIC_MODEL_ID") or "claude-sonnet-4-6"
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens

    def run(self, *, workspace: Path, task_payload: dict, session_state: dict | None = None) -> dict:
        workspace = Path(workspace).resolve()
        messages = [{"role": "user", "content": self._build_initial_prompt(task_payload=task_payload, session_state=session_state or {})}]
        tools = _WorkspaceTools(workspace=workspace)
        rounds_since_todo = 0
        for _ in range(self.max_rounds):
            response = self.client.messages.create(
                model=self.model,
                system=self._build_system_prompt(workspace=workspace),
                messages=messages,
                tools=self.TOOLS,
                max_tokens=self.max_tokens,
            )
            assistant_content = self._serialize_content_blocks(response.content)
            messages.append({"role": "assistant", "content": assistant_content})
            if response.stop_reason != "tool_use":
                return {
                    "status": "completed",
                    "report_text": self._extract_text_response(response.content),
                    "questions_for_agent": [],
                    "artifacts": [],
                    "working_notes": "",
                }
            results = []
            used_todo = False
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                tool_name = getattr(block, "name", "")
                tool_input = dict(getattr(block, "input", {}) or {})
                if tool_name == "ask_main_agent":
                    questions = [str(item).strip() for item in (tool_input.get("questions") or []) if str(item).strip()]
                    return {
                        "status": "needs_agent_input",
                        "report_text": "",
                        "questions_for_agent": questions,
                        "artifacts": [],
                        "working_notes": "",
                    }
                if tool_name == "return_result":
                    return self._normalize_final_result(tool_input)
                output = self._dispatch_tool(tools=tools, tool_name=tool_name, tool_input=tool_input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(block, "id", ""),
                        "content": str(output),
                    }
                )
                if tool_name == "todo":
                    used_todo = True
            rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
            if rounds_since_todo >= 3:
                results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})
            messages.append({"role": "user", "content": results})
        return {
            "status": "failed",
            "report_text": "",
            "questions_for_agent": [],
            "artifacts": [],
            "working_notes": "",
            "error": f"Subagent exceeded max rounds ({self.max_rounds})",
        }

    @staticmethod
    def _build_system_prompt(*, workspace: Path) -> str:
        return (
            f"You are a coding subagent working in {workspace}.\n"
            "Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done, only one task can be in_progress at a time. .\n"
            "Prefer tools over prose. Work only inside the provided task workspace.\n"
            "If you are blocked on missing information or a choice the main agent must make, use ask_main_agent.\n"
            "For analysis tasks, inspect recording data under inputs/ before drawing conclusions.\n"
            "Return a clear summary plus decision criteria, key metrics, and a recommendation when the task compares recordings.\n"
            "When useful, create figures or artifacts such as PNG plots, CSV summaries, or tables so users can understand the result quickly.\n"
            "Figures are encouraged but not mandatory; if the data is insufficient or a plot would not help, explain that in the report.\n"
            "When you are done, call return_result with the final report and any artifact files if necessary (e.g., generated PNG files to show analysis result).\n"
        )

    @staticmethod
    def _build_initial_prompt(*, task_payload: dict, session_state: dict) -> str:
        history = session_state.get("history") or []
        history_lines = []
        for item in history:
            role = (item.get("role") or "unknown").upper()
            content = (item.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")
        history_text = "\n".join(history_lines) or "(no prior history)"
        return (
            "Continue this delegated task.\n"
            "Read task.json and context/scene_context.json before making assumptions.\n"
            "If recording data exists under inputs/, inspect it directly.\n\n"
            "For recording comparison analysis, state the decision criteria, compute or summarize key metrics, give a recommendation, and create a visualization when it would help the user compare runs quickly.\n\n"
            f"Task payload:\n{json.dumps(task_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Session history:\n{history_text}\n"
        )

    @staticmethod
    def _serialize_content_blocks(blocks) -> list[dict]:
        serialized = []
        for block in blocks:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                serialized.append({"type": "text", "text": getattr(block, "text", "")})
            elif block_type == "tool_use":
                serialized.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": dict(getattr(block, "input", {}) or {}),
                    }
                )
        return serialized

    @staticmethod
    def _extract_text_response(blocks) -> str:
        parts = [getattr(block, "text", "").strip() for block in blocks if getattr(block, "type", "") == "text"]
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _normalize_final_result(tool_input: dict) -> dict:
        return {
            "status": tool_input.get("status", "completed"),
            "report_text": tool_input.get("report_text", ""),
            "questions_for_agent": [],
            "artifacts": tool_input.get("artifacts") or [],
            "working_notes": tool_input.get("working_notes", ""),
            "error": tool_input.get("error", ""),
        }

    @staticmethod
    def _dispatch_tool(*, tools: _WorkspaceTools, tool_name: str, tool_input: dict) -> str:
        if tool_name == "bash":
            return tools.run_shell(str(tool_input.get("command", "")))
        if tool_name == "read_file":
            return tools.read_file(
                str(tool_input.get("path", "")),
                tool_input.get("limit"),
            )
        if tool_name == "write_file":
            return tools.write_file(
                str(tool_input.get("path", "")),
                str(tool_input.get("content", "")),
            )
        if tool_name == "edit_file":
            return tools.edit_file(
                str(tool_input.get("path", "")),
                str(tool_input.get("old_text", "")),
                str(tool_input.get("new_text", "")),
            )
        if tool_name == "todo":
            return tools.todo.update(tool_input.get("items") or [])
        return f"Unknown tool: {tool_name}"

    @staticmethod
    def _build_default_client():
        if Anthropic is None:
            raise RuntimeError("anthropic is required for AnthropicSubagentRunner unless a client is injected")
        if os.getenv("ANTHROPIC_BASE_URL"):
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        return Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))


# Backward-compatible alias for earlier integration points.
ClaudeWorkerRunner = AnthropicSubagentRunner
