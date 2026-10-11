# Protocol Convergence MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first implementation slice that converges the legacy chat/control flow and Scene API v2 into one collaboration-ready protocol foundation.

**Architecture:** Keep one orchestrator agent and one deterministic scene runtime. Extend the current runtime with proposal/clarification/job message families while preserving the existing `agent_ready`, `agent_status`, `agent_push`, and `scene.*` flow during migration. Route all scene mutations, including user edits, through the same versioned execution model.

**Tech Stack:** Unity 2021 C#, NativeWebSocket, Newtonsoft.Json, Python 3.x, `websockets`, `unittest`, existing Scene API v2 services, existing AgentCore/Heartbeat runtime.

---

### Task 1: Add shared protocol envelope primitives

**Files:**
- Create: `VsensPython/core/protocol/__init__.py`
- Create: `VsensPython/core/protocol/messages.py`
- Create: `VsensPython/tests/__init__.py`
- Create: `VsensPython/tests/test_protocol_messages.py`
- Modify: `VsensPython/vsens_server.py`
- Modify: `VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Network/Protocol/Requests.cs`

**Step 1: Write the failing test**

```python
import unittest

from core.protocol.messages import (
    build_conversation_reply,
    build_clarification_request,
    build_proposal_ready,
)


class TestProtocolMessages(unittest.TestCase):
    def test_conversation_reply_shape(self):
        msg = build_conversation_reply(turn_id="turn_1", reply="hello")
        self.assertEqual(msg["type"], "conversation.reply")
        self.assertEqual(msg["turn_id"], "turn_1")
        self.assertEqual(msg["reply"], "hello")

    def test_clarification_request_shape(self):
        msg = build_clarification_request(
            question_id="q_1",
            prompt="Which appliance do you mean?",
            options=[{"id": "coffee", "label": "Coffee maker"}],
            selection_mode="single",
        )
        self.assertEqual(msg["type"], "clarification.request")
        self.assertEqual(msg["selection_mode"], "single")
        self.assertEqual(msg["options"][0]["id"], "coffee")

    def test_proposal_ready_shape(self):
        msg = build_proposal_ready(
            proposal_id="prop_1",
            title="Wall placement options",
            options=[{"id": "cand_1", "label": "East wall"}],
        )
        self.assertEqual(msg["type"], "proposal.ready")
        self.assertEqual(msg["proposal_id"], "prop_1")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_protocol_messages -v`  
Expected: FAIL with import errors because `core.protocol.messages` does not exist yet.

**Step 3: Write minimal implementation**

Create `VsensPython/core/protocol/messages.py` with simple builder helpers:

```python
def build_conversation_reply(turn_id: str, reply: str) -> dict:
    return {"type": "conversation.reply", "turn_id": turn_id, "reply": reply}


def build_clarification_request(question_id: str, prompt: str, options: list[dict], selection_mode: str) -> dict:
    return {
        "type": "clarification.request",
        "question_id": question_id,
        "prompt": prompt,
        "options": options,
        "selection_mode": selection_mode,
    }


def build_proposal_ready(proposal_id: str, title: str, options: list[dict]) -> dict:
    return {
        "type": "proposal.ready",
        "proposal_id": proposal_id,
        "title": title,
        "options": options,
    }
```

Add matching Unity DTOs to `Messages.cs` / `Requests.cs`, then update
`vsens_server.py` to accept the new families in its handler table without
removing legacy messages.

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_protocol_messages -v`  
Expected: PASS for the new message builders.

**Step 5: Commit**

```bash
git add VsensPython/core/protocol/__init__.py VsensPython/core/protocol/messages.py VsensPython/tests/__init__.py VsensPython/tests/test_protocol_messages.py VsensPython/vsens_server.py VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs VsensAgent/Assets/VsensAgent/Network/Protocol/Requests.cs
git commit -m "feat: add collaborative protocol envelopes"
```

### Task 2: Separate conversation routing from proposal and clarification routing

**Files:**
- Create: `VsensPython/tests/test_agent_core_protocol.py`
- Modify: `VsensPython/core/agent_core.py`
- Modify: `VsensPython/vsens_server.py`
- Modify: `VsensPython/core/skills/control_parser.py`

**Step 1: Write the failing test**

```python
import unittest
from unittest.mock import MagicMock

from core.agent_core import AgentCore


class TestAgentCoreProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_text_chat_can_return_proposal_without_control_actions(self):
        agent = MagicMock()
        broadcaster = MagicMock()
        broadcaster.set_state = MagicMock()
        core = AgentCore(agent, broadcaster)
        agent.send_message.return_value = "I have two options for sensor placement."

        result = await core.handle_text("Suggest placements", {})

        self.assertIn(result["type"], {"agent_ready", "conversation.reply"})
        self.assertIn("reply", result)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`  
Expected: FAIL because routing is still hard-coded to legacy text replies with control extraction only.

**Step 3: Write minimal implementation**

- Extract message-family routing in `AgentCore`.
- Allow three outcomes from a text turn:
  - plain conversation reply,
  - clarification request,
  - proposal payload.
- Keep legacy `agent_ready` output as a compatibility wrapper until Unity is
  migrated.

Minimal compatibility shape:

```python
return {
    "type": "conversation.reply",
    "legacy_type": "agent_ready",
    "reply": spoken_text,
    "control": {"actions": control_output},
}
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`  
Expected: PASS with deterministic routing for plain text turns.

**Step 5: Commit**

```bash
git add VsensPython/tests/test_agent_core_protocol.py VsensPython/core/agent_core.py VsensPython/vsens_server.py VsensPython/core/skills/control_parser.py
git commit -m "feat: separate conversation proposal and clarification routing"
```

### Task 3: Route manual Unity edits through the versioned scene mutation path

**Files:**
- Create: `VsensAgent/Assets/Tests/Editor/SceneApi/SceneVersioningTests.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneRegistry.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneTransactionExecutor.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Core/Managers/ControlManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Core/Managers/InputController.cs`

**Step 1: Write the failing test**

```csharp
using NUnit.Framework;

public class SceneVersioningTests
{
    [Test]
    public void ManualEdit_IncrementsSceneVersion()
    {
        Assert.Fail("Implement manual edit version tracking");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-editmode.xml -quit`  
Expected: FAIL in `SceneVersioningTests.ManualEdit_IncrementsSceneVersion`.

**Step 3: Write minimal implementation**

- Add a `BeginUserMutation(...)` or equivalent helper in
  `SceneTransactionExecutor`.
- Ensure manual transform/state/sensor edits emit the same scene-version bump
  and rollback metadata path used by agent-driven actions.
- Teach `SceneRegistry` to expose the current `scene_version` after manual UI or
  input-driven changes.

Minimal target behavior:

```csharp
public int RegisterManualMutation(string source, string targetId)
{
    _sceneVersion += 1;
    return _sceneVersion;
}
```

**Step 4: Run test to verify it passes**

Run: `Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-editmode.xml -quit`  
Expected: PASS for the manual versioning test.

**Step 5: Commit**

```bash
git add VsensAgent/Assets/Tests/Editor/SceneApi/SceneVersioningTests.cs VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneRegistry.cs VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneTransactionExecutor.cs VsensAgent/Assets/VsensAgent/Core/Managers/ControlManager.cs VsensAgent/Assets/VsensAgent/Core/Managers/InputController.cs
git commit -m "feat: unify manual scene edits with scene versioning"
```

### Task 4: Surface proposals, clarifications, and reports in the Unity chat UI

**Files:**
- Create: `VsensAgent/Assets/Tests/Editor/UI/ChatProtocolUiTests.cs`
- Create: `VsensAgent/Assets/VsensAgent/UI/Chat/ClarificationOptionView.cs`
- Modify: `VsensAgent/Assets/VsensAgent/UI/Chat/ChatUIManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Network/WsClient.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs`

**Step 1: Write the failing test**

```csharp
using NUnit.Framework;

public class ChatProtocolUiTests
{
    [Test]
    public void ClarificationRequest_RendersAsSelectableOptions()
    {
        Assert.Fail("Implement clarification UI rendering");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-chat-ui.xml -quit`  
Expected: FAIL in the new UI protocol test.

**Step 3: Write minimal implementation**

- Extend `WsClient.HandleMessage()` to dispatch:
  - `clarification.request`
  - `proposal.ready`
  - `result.report`
- Add a small UI view model to render option lists and approval actions in
  `ChatUIManager`.
- Keep plain text fallback so older message types remain visible even before the
  richer widgets are fully styled.

Minimal DTO shape:

```csharp
[Serializable]
public class ClarificationRequestMessage
{
    public string type;
    public string question_id;
    public string prompt;
    public ClarificationOption[] options;
}
```

**Step 4: Run test to verify it passes**

Run: `Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-chat-ui.xml -quit`  
Expected: PASS for clarification/proposal rendering tests.

**Step 5: Commit**

```bash
git add VsensAgent/Assets/Tests/Editor/UI/ChatProtocolUiTests.cs VsensAgent/Assets/VsensAgent/UI/Chat/ClarificationOptionView.cs VsensAgent/Assets/VsensAgent/UI/Chat/ChatUIManager.cs VsensAgent/Assets/VsensAgent/Network/WsClient.cs VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs
git commit -m "feat: render clarification and proposal messages in chat ui"
```

### Task 5: Introduce a long-running job lifecycle for simulation, collection, and training

**Files:**
- Create: `VsensPython/core/jobs/__init__.py`
- Create: `VsensPython/core/jobs/job_manager.py`
- Create: `VsensPython/tests/test_job_manager.py`
- Modify: `VsensPython/vsens_server.py`
- Modify: `VsensPython/core/agent_status.py`
- Modify: `VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs`
- Modify: `VsensAgent/Assets/VsensAgent/UI/Chat/ChatUIManager.cs`

**Step 1: Write the failing test**

```python
import unittest

from core.jobs.job_manager import JobManager


class TestJobManager(unittest.TestCase):
    def test_start_job_returns_running_status(self):
        manager = JobManager()
        job = manager.start_job("simulation.run", {"duration_s": 30})
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["type"], "job.started")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_job_manager -v`  
Expected: FAIL because `core.jobs.job_manager` does not exist yet.

**Step 3: Write minimal implementation**

```python
class JobManager:
    def __init__(self):
        self._jobs = {}

    def start_job(self, kind: str, payload: dict) -> dict:
        job = {"type": "job.started", "job_kind": kind, "status": "running", "payload": payload}
        self._jobs[id(job)] = job
        return job
```

- Broadcast `job.started`, `job.progress`, `job.completed`, and `job.failed`.
- Surface progress in `ChatUIManager` using the existing agent status area until
  a dedicated experiment panel exists.

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_job_manager -v`  
Expected: PASS for job lifecycle creation.

**Step 5: Commit**

```bash
git add VsensPython/core/jobs/__init__.py VsensPython/core/jobs/job_manager.py VsensPython/tests/test_job_manager.py VsensPython/vsens_server.py VsensPython/core/agent_status.py VsensAgent/Assets/VsensAgent/Network/Protocol/Messages.cs VsensAgent/Assets/VsensAgent/UI/Chat/ChatUIManager.cs
git commit -m "feat: add long-running job lifecycle messaging"
```

### Task 6: Lock the convergence slice with contract docs and acceptance tests

**Files:**
- Create: `docs/communication/COLLABORATION_PROTOCOL.md`
- Modify: `docs/README.md`
- Modify: `docs/scene_api/ACCEPTANCE_TESTS.md`
- Modify: `VsensPython/test_phase3.py`
- Create: `VsensPython/tests/test_protocol_acceptance.py`

**Step 1: Write the failing test**

```python
import unittest


class TestProtocolAcceptance(unittest.TestCase):
    def test_stale_version_rejects_after_manual_edit(self):
        self.fail("Implement protocol acceptance fixture")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_protocol_acceptance -v`  
Expected: FAIL because the fixture and assertions do not exist yet.

**Step 3: Write minimal implementation**

- Add acceptance coverage for:
  - proposal without mutation,
  - clarification request/response,
  - manual edit increments `scene_version`,
  - stale agent action is rejected,
  - job status messages arrive during long-running tasks.
- Document the final message families in
  `docs/communication/COLLABORATION_PROTOCOL.md`.

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_protocol_acceptance -v`  
Expected: PASS for the protocol acceptance fixtures.

**Step 5: Commit**

```bash
git add docs/communication/COLLABORATION_PROTOCOL.md docs/README.md docs/scene_api/ACCEPTANCE_TESTS.md VsensPython/test_phase3.py VsensPython/tests/test_protocol_acceptance.py
git commit -m "test: add acceptance coverage for protocol convergence"
```
