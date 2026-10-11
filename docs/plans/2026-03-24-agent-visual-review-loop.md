# Agent Visual Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make avatar placement retries Python-led by adding a dedicated multimodal screenshot review pass and using its structured output to accept or retry candidates.

**Architecture:** Keep Unity responsible for capture and execution, but move screenshot judgment and bounded retry policy into Python. Use a separate multimodal review request so screenshot analysis does not pollute the main conversation history.

**Tech Stack:** Python, OpenAI chat completions with image inputs, Unity Scene API, PyCharm MCP, Rider MCP, Unity MCP test runner.

---

### Task 1: Add a Multimodal Review Prompt Contract

**Files:**
- Create: `VsensPython/data/prompts/features/avatar_visual_review.txt`
- Modify: `VsensPython/core/prompting/composer.py`
- Test: `VsensPython/tests/test_prompt_composer.py`

**Step 1: Write the failing test**

Add a test that asserts the composed prompt stack includes the new avatar visual review feature text when requested.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_prompt_composer -v`
Expected: FAIL because the new feature prompt is not present.

**Step 3: Write minimal implementation**

Create a prompt file describing:

- review role
- allowed decisions
- allowed issue tags
- output shape

Update prompt composition so the review prompt can be loaded independently from the main chat prompt.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_prompt_composer -v`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/data/prompts/features/avatar_visual_review.txt VsensPython/core/prompting/composer.py VsensPython/tests/test_prompt_composer.py
git commit -m "feat: add avatar visual review prompt contract"
```

### Task 2: Add a Non-Persistent Multimodal Review Method

**Files:**
- Modify: `VsensPython/vsens_openai.py`
- Test: `VsensPython/tests/test_vsens_openai_visual_review.py`

**Step 1: Write the failing test**

Add a unit test that exercises a new method for multimodal visual review and verifies:

- image inputs are accepted
- the method does not append to normal conversation history
- structured text content is returned

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_vsens_openai_visual_review -v`
Expected: FAIL because the method does not exist.

**Step 3: Write minimal implementation**

Add a dedicated method such as `review_validation_images(...)` that:

- builds a non-persistent request
- sends text context plus image inputs
- returns the model text

Do not reuse the normal persistent `send_message(...)` path.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_vsens_openai_visual_review -v`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/vsens_openai.py VsensPython/tests/test_vsens_openai_visual_review.py
git commit -m "feat: add multimodal avatar review request path"
```

### Task 3: Parse Structured Review Decisions

**Files:**
- Create: `VsensPython/core/protocol/visual_review.py`
- Test: `VsensPython/tests/test_visual_review.py`

**Step 1: Write the failing test**

Add tests for parsing model output into:

- `decision`
- `issues`
- `reason`

Include one valid `accept`, one valid `retry`, and one malformed response case.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_visual_review -v`
Expected: FAIL because the parser does not exist.

**Step 3: Write minimal implementation**

Implement a strict parser with:

- narrow accepted decision values
- safe fallback on malformed output
- compact normalized result object

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_visual_review -v`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/core/protocol/visual_review.py VsensPython/tests/test_visual_review.py
git commit -m "feat: add structured avatar visual review parser"
```

### Task 4: Build the Review Packet from Validation Artifacts

**Files:**
- Create: `VsensPython/core/avatar_review/review_packet.py`
- Test: `VsensPython/tests/test_avatar_review_packet.py`

**Step 1: Write the failing test**

Add tests that build a review packet from:

- task hint
- target alias
- candidate metadata
- validation metrics
- artifact file paths

Verify the output is compact and ordered.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_avatar_review_packet -v`
Expected: FAIL because the builder does not exist.

**Step 3: Write minimal implementation**

Implement a small builder that:

- filters to the key fields only
- preserves artifact order
- returns both text context and image path list

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_avatar_review_packet -v`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/core/avatar_review/review_packet.py VsensPython/tests/test_avatar_review_packet.py
git commit -m "feat: build avatar visual review packets"
```

### Task 5: Move Avatar Screenshot Retry Orchestration into Python

**Files:**
- Modify: `VsensPython/core/agent_core.py`
- Modify: `VsensPython/core/query_first/coordinator.py`
- Modify: `VsensPython/tests/test_agent_core_protocol.py`
- Modify: `VsensPython/tests/test_query_first_coordinator.py`

**Step 1: Write the failing test**

Add tests for this sequence:

1. candidate query returns multiple candidates
2. placement validation passes for candidate 1
3. capture returns artifacts
4. visual review returns `retry`
5. candidate 2 is executed
6. second review returns `accept`

Also add an exhausted-candidate failure test.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_agent_core_protocol tests.test_query_first_coordinator -v`
Expected: FAIL because retry is not Python-led yet.

**Step 3: Write minimal implementation**

Refactor avatar task orchestration so Python:

- requests candidates
- validates a candidate
- executes avatar actions
- requests capture
- runs multimodal review
- retries deterministically on `retry`

Remove Unity-local screenshot retry as the primary control path, or gate it off for Python-led avatar tasks.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_agent_core_protocol tests.test_query_first_coordinator -v`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensPython/core/agent_core.py VsensPython/core/query_first/coordinator.py VsensPython/tests/test_agent_core_protocol.py VsensPython/tests/test_query_first_coordinator.py
git commit -m "feat: move avatar screenshot retry into python orchestration"
```

### Task 6: Keep Unity Capture and Execution Clean

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/Core/Managers/ControlManager.cs`
- Modify: `VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs`

**Step 1: Write the failing test**

Add or update a Unity test that verifies:

- avatar control still triggers screenshot capture
- Unity does not silently override a Python-driven retry decision

**Step 2: Run test to verify it fails**

Run with Unity Test Runner:
`AvatarSceneApiTests`
Expected: FAIL until the Unity-side retry behavior is adjusted. After the later runtime-edit-mode simplification, Unity-side screenshot scoring is no longer part of the active runtime path.

**Step 3: Write minimal implementation**

Change Unity so it still captures screenshots and returns artifacts, but no longer acts as the authoritative screenshot retry controller for Python-driven avatar review flows.

**Step 4: Run test to verify it passes**

Run with Unity Test Runner:
`AvatarSceneApiTests`
Expected: PASS

**Step 5: Commit**

```bash
git add VsensAgent/Assets/VsensAgent/Core/Managers/ControlManager.cs VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs
git commit -m "refactor: leave avatar screenshot retry authority to python"
```

### Task 7: End-to-End Verification

**Files:**
- Modify: `docs/architecture/AVATAR_MOTION_RUNTIME.md`
- Modify: `docs/architecture/REFACTOR_CHECKLIST.md`
- Modify: `docs/scene_api/QUERY_API.md`

**Step 1: Run Python test suite for the new review path**

Run:
`python -m unittest tests.test_prompt_composer tests.test_vsens_openai_visual_review tests.test_visual_review tests.test_avatar_review_packet tests.test_agent_core_protocol tests.test_query_first_coordinator -v`

Expected: PASS

**Step 2: Run Unity avatar test suite**

Run with Unity Test Runner:
`VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`

Expected: PASS

**Step 3: Manual verification**

Run one real task:
- `place the avatar so it can make coffee naturally, validate the placement, then play a coffee-making motion`

Confirm:

- screenshots are captured
- a rejected first candidate causes a Python-led retry
- final user-facing reply stays clean

**Step 4: Update docs**

Document:

- Python-led visual review loop
- new multimodal review pass
- narrowed Unity responsibility

**Step 5: Commit**

```bash
git add docs/architecture/AVATAR_MOTION_RUNTIME.md docs/architecture/REFACTOR_CHECKLIST.md docs/scene_api/QUERY_API.md
git commit -m "docs: document python-led avatar visual review loop"
```
