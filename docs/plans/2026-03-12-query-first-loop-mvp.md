# Query-First Loop MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal query-first runtime loop so the Python agent can issue `scene.query_*` requests mid-turn, wait for Unity results, and then produce the final collaboration reply.

**Architecture:** Keep the current external collaboration protocol stable while adding one internal `<query>` mode. Refactor the Python websocket server to support pending query futures and a single active user-turn task per connection. Extend `AgentCore` into a two-stage orchestration path and make Unity query responses correlate by `request_id`.

**Tech Stack:** Python 3, `asyncio`, `websockets`, `unittest`, Unity C#, NativeWebSocket, Newtonsoft.Json, existing Scene API v2 services, existing modular prompt system.

---

### Task 1: Teach the prompt stack and parser about `<query>`

**Files:**
- Modify: `VsensPython/data/prompts/core/decision_policy.txt`
- Modify: `VsensPython/data/prompts/features/scene_query.txt`
- Create: `VsensPython/data/prompts/examples/query.txt`
- Modify: `VsensPython/data/prompts/manifests/features.json`
- Modify: `VsensPython/core/skills/control_parser.py`
- Modify: `VsensPython/tests/test_prompt_composer.py`
- Create: `VsensPython/tests/test_query_parser.py`

**Step 1: Write the failing test**

```python
import unittest

from core.skills.control_parser import ControlParser
from core.prompting.composer import PromptComposer


class TestQueryParser(unittest.TestCase):
    def test_extract_query_block(self):
        reply = """I need one more detail.
<query>
{"method":"scene.query_objects","params":{"aliases":["CoffeeMaker"]},"reason":"Need canonical object identity."}
</query>
"""
        structured = ControlParser.extract_structured_reply(reply)

        self.assertEqual(structured["query"]["method"], "scene.query_objects")
        self.assertEqual(structured["query"]["params"]["aliases"], ["CoffeeMaker"])
        self.assertEqual(structured["spoken_text"], "I need one more detail.")


class TestPromptComposerQueryMode(unittest.TestCase):
    def test_scene_query_prompt_teaches_query_block(self):
        prompt = PromptComposer(project_root=".").compose(enabled_features=["scene_query"])

        self.assertIn("<query>", prompt)
        self.assertIn("scene.query_objects", prompt)
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer tests.test_query_parser -v`

Expected: FAIL because `<query>` is neither taught in the prompt stack nor parsed by `ControlParser`.

**Step 3: Write minimal implementation**

- Extend the `scene_query` prompt feature to define the internal `<query>` contract.
- Add one compact example in `data/prompts/examples/query.txt`.
- Register the example in `features.json`.
- Extend `ControlParser.extract_structured_reply(...)` to parse and expose:

```python
{
    "spoken_text": "...",
    "actions": [...],
    "proposal": ...,
    "clarification": ...,
    "query": {"method": "...", "params": {...}, "reason": "..."},
}
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_prompt_composer tests.test_query_parser -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/data/prompts/core/decision_policy.txt VsensPython/data/prompts/features/scene_query.txt VsensPython/data/prompts/examples/query.txt VsensPython/data/prompts/manifests/features.json VsensPython/core/skills/control_parser.py VsensPython/tests/test_prompt_composer.py VsensPython/tests/test_query_parser.py
git commit -m "feat: add internal query mode to prompt and parser"
```

### Task 2: Add a lightweight query-first coordinator

**Files:**
- Create: `VsensPython/core/query_first/__init__.py`
- Create: `VsensPython/core/query_first/coordinator.py`
- Create: `VsensPython/tests/test_query_first_coordinator.py`

**Step 1: Write the failing test**

```python
import unittest

from core.query_first.coordinator import QueryFirstCoordinator


class TestQueryFirstCoordinator(unittest.IsolatedAsyncioTestCase):
    async def test_builds_query_request_with_request_id(self):
        async def fake_executor(query_request):
            return {"type": "scene.query_response", "request_id": query_request["request_id"], "method": query_request["type"]}

        coordinator = QueryFirstCoordinator(query_executor=fake_executor)
        result = await coordinator.execute_query(
            {"method": "scene.query_summary", "params": {"scene_version": 1}}
        )

        self.assertEqual(result["type"], "scene.query_response")
        self.assertEqual(result["method"], "scene.query_summary")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_query_first_coordinator -v`

Expected: FAIL with import error because `core.query_first.coordinator` does not exist.

**Step 3: Write minimal implementation**

Create a small coordinator that:

- validates allowed query methods,
- injects a generated `request_id`,
- converts the internal query payload into a websocket-ready `scene.query_*` request,
- delegates execution to an injected async `query_executor`,
- returns the correlated response.

Minimal target shape:

```python
class QueryFirstCoordinator:
    async def execute_query(self, query_payload: dict) -> dict:
        ...
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_query_first_coordinator -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/core/query_first/__init__.py VsensPython/core/query_first/coordinator.py VsensPython/tests/test_query_first_coordinator.py
git commit -m "feat: add query-first coordinator"
```

### Task 3: Refactor the websocket server for pending query orchestration

**Files:**
- Modify: `VsensPython/vsens_server.py`
- Modify: `VsensPython/tests/test_vsens_server_protocol.py`
- Create: `VsensPython/tests/test_vsens_server_query_loop.py`

**Step 1: Write the failing test**

```python
import asyncio
import unittest

from vsens_server import VsensWebSocketServer


class TestVsensWebSocketServerQueryLoop(unittest.IsolatedAsyncioTestCase):
    async def test_query_response_resolves_pending_future(self):
        server = VsensWebSocketServer()
        future = asyncio.get_running_loop().create_future()
        server._pending_queries = {"qry_1": future}

        await server._handle_scene_query_response({
            "type": "scene.query_response",
            "request_id": "qry_1",
            "method": "scene.query_summary",
        })

        self.assertTrue(future.done())
        self.assertEqual(future.result()["request_id"], "qry_1")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_vsens_server_protocol tests.test_vsens_server_query_loop -v`

Expected: FAIL because the server has no pending-query table or query-response handler.

**Step 3: Write minimal implementation**

Refactor the server to:

- maintain per-connection pending query futures,
- continue reading the websocket while a user-turn task is running,
- route `scene.query_response` and `scene.error` to future resolution,
- expose a small query-executor callback that sends a request to the current websocket and waits for the matching response,
- keep one active user-turn task per connection for the MVP.

Minimal new helpers should include something like:

```python
async def _execute_scene_query(self, websocket, query_request: dict) -> dict:
    ...

async def _handle_scene_query_response(self, msg: dict) -> None:
    ...
```

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_vsens_server_protocol tests.test_vsens_server_query_loop -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/vsens_server.py VsensPython/tests/test_vsens_server_protocol.py VsensPython/tests/test_vsens_server_query_loop.py
git commit -m "feat: add pending query orchestration to websocket server"
```

### Task 4: Make `AgentCore` support two-stage query-first reasoning

**Files:**
- Modify: `VsensPython/core/agent_core.py`
- Modify: `VsensPython/tests/test_agent_core_protocol.py`

**Step 1: Write the failing test**

```python
import unittest
from unittest.mock import MagicMock, AsyncMock

from core.agent_core import AgentCore


class TestAgentCoreQueryFirst(unittest.IsolatedAsyncioTestCase):
    async def test_query_result_is_injected_before_final_reply(self):
        agent = MagicMock()
        broadcaster = MagicMock()
        broadcaster.set_state = AsyncMock()
        core = AgentCore(agent, broadcaster)

        agent.send_message.side_effect = [
            'I need to inspect the object first.\\n<query>{"method":"scene.query_objects","params":{"aliases":["CoffeeMaker"]},"reason":"Need object details."}</query>',
            'I found the target.\\n<proposal>{"proposal_id":"p1","title":"Placement candidates","summary":"Two candidates.","options":[{"id":"c1","label":"Near coffee maker"}]}</proposal>',
        ]

        async def fake_query_executor(query_payload):
            return {
                "type": "scene.query_response",
                "request_id": "qry_1",
                "method": "scene.query_objects",
                "scene_version": 3,
                "objects": [{"id": "obj_coffee_01", "alias": "CoffeeMaker"}],
            }

        result = await core.handle_text("Suggest placements near the coffee maker", {}, query_executor=fake_query_executor)

        self.assertEqual(result["type"], "proposal.ready")
```

**Step 2: Run test to verify it fails**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`

Expected: FAIL because `AgentCore.handle_text(...)` does not support a query-executor path yet.

**Step 3: Write minimal implementation**

- Add an optional `query_executor` argument to text/voice handlers.
- Detect the parsed `query` payload from the first LLM response.
- Execute the query through `QueryFirstCoordinator`.
- Build a follow-up prompt that includes the correlated query result.
- Run a second LLM call and continue through the existing final-reply builder.
- Add timeout fallback that returns a safe plain reply or clarification instead of hanging.

**Step 4: Run test to verify it passes**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/core/agent_core.py VsensPython/tests/test_agent_core_protocol.py
git commit -m "feat: add two-stage query-first agent flow"
```

### Task 5: Add `request_id` correlation on the Unity scene-query side

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiManager.cs`
- Create: `VsensAgent/Assets/Tests/Editor/SceneApi/SceneApiQueryCorrelationTests.cs`

**Step 1: Write the failing test**

```csharp
using NUnit.Framework;

public class SceneApiQueryCorrelationTests
{
    [Test]
    public void QueryResponse_EchoesRequestId()
    {
        Assert.Fail("Implement query response request_id correlation");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `/Applications/Unity/Hub/Editor/6000.3.9f1/Unity.app/Contents/MacOS/Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-query-loop.xml -quit`

Expected: FAIL in `SceneApiQueryCorrelationTests.QueryResponse_EchoesRequestId`.

**Step 3: Write minimal implementation**

Update `SceneApiManager` so every query request:

- reads `request_id` from the incoming payload,
- includes the same `request_id` in `scene.query_response`,
- includes it in `scene.error` when the failure is request-specific.

Minimal target response shape:

```csharp
return new
{
    type = "scene.query_response",
    request_id = requestId,
    method = "scene.query_objects",
    scene_version = snapshot.scene_version,
    objects = result.ToList()
};
```

**Step 4: Run test to verify it passes**

Run: `/Applications/Unity/Hub/Editor/6000.3.9f1/Unity.app/Contents/MacOS/Unity -batchmode -projectPath <repository>/VsensAgent -runTests -testPlatform EditMode -testResults /tmp/vseneagent-query-loop.xml -quit`

Expected: PASS

**Step 5: Commit**

```bash
git add VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiManager.cs VsensAgent/Assets/Tests/Editor/SceneApi/SceneApiQueryCorrelationTests.cs
git commit -m "feat: correlate scene query responses with request ids"
```

### Task 6: Update runtime docs after the MVP lands

**Files:**
- Modify: `docs/architecture/PYTHON_AGENT.md`
- Modify: `docs/architecture/REFACTOR_CHECKLIST.md`
- Modify: `docs/scene_api/QUERY_API.md`
- Modify: `docs/plans/README.md`

**Step 1: Write the failing doc checklist**

Add a short checklist section to the plan execution notes:

```markdown
- [ ] Python agent docs mention query-first orchestration
- [ ] Refactor checklist notes query-first as implemented or partially complete
- [ ] Scene query docs describe `request_id` correlation
- [ ] Plans index links to the new query-first design and implementation docs
```

**Step 2: Run verification to confirm the docs are stale before updating**

Run: `rg -n "request_id|query-first orchestration|Query-First Loop" <repository>/docs <repository>/VsensPython/docs`

Expected: partial or missing coverage for the new runtime behavior.

**Step 3: Write minimal implementation**

Update the docs so they reflect the implemented MVP rather than only the planned architecture.

**Step 4: Run verification to confirm the docs are updated**

Run: `rg -n "request_id|query-first orchestration|Query-First Loop" <repository>/docs <repository>/VsensPython/docs`

Expected: hits in the updated current docs and plans index.

**Step 5: Commit**

```bash
git add docs/architecture/PYTHON_AGENT.md docs/architecture/REFACTOR_CHECKLIST.md docs/scene_api/QUERY_API.md docs/plans/README.md
git commit -m "docs: record query-first loop runtime"
```
