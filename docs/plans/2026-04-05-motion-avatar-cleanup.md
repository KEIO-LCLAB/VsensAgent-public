# Motion Avatar Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove deprecated motion/avatar runtime paths and align active docs/code to the current Python-led visual review pipeline.

**Architecture:** Keep Unity responsible for avatar execution, geometric validation, and deterministic captures only. Keep Python responsible for motion preparation and screenshot-based accept/retry. Remove deprecated `scene.score_validation_views` compatibility from the active runtime path and clean current docs so only the surviving pipeline is documented.

**Tech Stack:** Unity C#, Python, Rider MCP, PyCharm MCP, Unity MCP.

---

### Task 1: Remove deprecated runtime API remnants

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Network/WsClient.cs`
- Modify: `VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs`

**Step 1: Delete the deprecated `scene.score_validation_views` route from Unity runtime dispatch.**

**Step 2: Delete the websocket forwarding case for `scene.score_validation_views`.**

**Step 3: Delete the deprecated-scene-error test that only exists to preserve that retired route.**

**Step 4: Run Unity build/test verification.**

### Task 2: Clean active docs to one motion/avatar pipeline

**Files:**
- Modify: `docs/scene_api/QUERY_API.md`
- Modify: `docs/architecture/AVATAR_MOTION_RUNTIME.md`
- Modify: `docs/architecture/PYTHON_AGENT.md`
- Modify: `docs/architecture/REFACTOR_CHECKLIST.md`
- Modify: `docs/scene_api/ACTION_TYPES.md`

**Step 1: Remove deprecated route mentions from current docs.**

**Step 2: Make the active motion/avatar contract explicit: query avatars/motions, execute actions, capture validation views, Python multimodal review.**

**Step 3: Keep old design references only in `docs/legacy` or `docs/plans`, not in current docs.**

### Task 3: Verify Python-side active motion path still matches docs

**Files:**
- Inspect/modify if needed: `VsensPython/core/agent_core.py`
- Inspect/modify if needed: `VsensPython/core/avatar_review/review_packet.py`
- Inspect/modify if needed: `VsensPython/data/prompts/features/control.txt`
- Inspect/modify if needed: `VsensPython/data/prompts/features/scene_query.txt`

**Step 1: Confirm no Python active path still depends on deprecated Unity screenshot scoring.**

**Step 2: If docs drift exists, update prompt/docs wording only; avoid behavior changes unless clearly dead code is found.**

### Task 4: Verification

**Step 1: Run targeted Python tests for avatar/motion orchestration.**

**Step 2: Run Unity EditMode tests covering avatar runtime.**

**Step 3: Confirm Unity console is free of compiler errors introduced by cleanup.**
