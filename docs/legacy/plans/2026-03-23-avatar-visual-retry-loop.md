# Avatar Visual Retry Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Unity-side visual scoring and Python-side bounded retry so avatar screenshots actively drive placement acceptance or retry.

**Architecture:** Unity captures and scores validation views using scene geometry and camera visibility checks. Python runs a deterministic avatar loop that queries candidates, validates geometry, executes a candidate, asks Unity to score the captured views, and retries when Unity recommends a retry.

**Tech Stack:** Unity C#, Unity Test Runner EditMode tests, Python unittest, websocket Scene API queries.

---

### Task 1: Document the new visual scoring loop

**Files:**
- Create: `docs/plans/2026-03-23-avatar-visual-retry-design.md`
- Create: `docs/plans/2026-03-23-avatar-visual-retry-loop.md`
- Modify: `docs/plans/README.md`

**Step 1: Write the design and implementation docs**

- describe the new `scene.score_validation_views` contract
- describe the bounded retry flow

**Step 2: Update the plans index**

- add both new docs to `docs/plans/README.md`

### Task 2: Add a failing Unity visual scoring test

**Files:**
- Modify: `VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs`

**Step 1: Write a failing test for bad visual framing**

- create a target and avatar placement where target or avatar is badly framed or occluded
- call `SceneValidationService.ScoreValidationViews(...)`
- assert `passed == false`

**Step 2: Write a failing test for a valid setup**

- create a reasonable target/avatar layout
- call the same scoring method
- assert `passed == true`

**Step 3: Run Unity EditMode tests and confirm the new tests fail for the expected reason**

### Task 3: Implement Unity-side visual scoring

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneValidationService.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiModels.cs`

**Step 1: Add `scene.score_validation_views` request handling**

- accept validator context, avatar id, target object id or alias, and task hint

**Step 2: Implement the four visual checks**

- target visible
- avatar visible
- occlusion score
- task framing score

**Step 3: Return structured scoring output**

- `passed`
- `score`
- `recommended_action`
- `reasons`
- `metrics`
- `artifacts`

**Step 4: Re-run Unity EditMode tests and make them pass**

### Task 4: Add a failing Python retry test

**Files:**
- Modify: `VsensPython/tests/test_agent_core_protocol.py`

**Step 1: Write a failing test for score-driven retry**

- first candidate scores as retry
- second candidate scores as accept
- assert the final control payload uses the second candidate

**Step 2: Write a failing test for candidate exhaustion**

- all candidates score as retry
- assert the runtime returns a structured failure instead of looping forever

**Step 3: Run targeted Python tests and confirm the new tests fail first**

### Task 5: Implement Python-side bounded retry

**Files:**
- Modify: `VsensPython/core/agent_core.py`
- Modify: `VsensPython/core/query_first/coordinator.py`

**Step 1: Add a hard call to `scene.score_validation_views`**

- run it after avatar execution metadata is assembled

**Step 2: Add bounded candidate retry**

- retry the next candidate when Unity recommends `retry_next_candidate`
- stop when Unity recommends `accept`
- stop after the configured candidate limit

**Step 3: Return a structured failure if no candidate passes**

**Step 4: Re-run targeted Python tests and make them pass**

### Task 6: Update current runtime docs

**Files:**
- Modify: `docs/scene_api/QUERY_API.md`
- Modify: `docs/architecture/AVATAR_MOTION_RUNTIME.md`
- Modify: `docs/architecture/REFACTOR_CHECKLIST.md`

**Step 1: Document `scene.score_validation_views`**

**Step 2: Document that screenshots now participate in bounded retry**

**Step 3: Update the architecture checklist**

### Task 7: Verify end to end behavior

**Files:**
- Test: `VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs`
- Test: `VsensPython/tests/test_agent_core_protocol.py`

**Step 1: Run Python tests**

Run: `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`

**Step 2: Run Unity EditMode tests**

Run through Unity Test Runner for:
- `VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`

**Step 3: Manually verify a coffee-making placement**

- confirm screenshots are generated
- confirm a failed visual score retries the next candidate
- confirm the accepted candidate remains in-frame and near the target
