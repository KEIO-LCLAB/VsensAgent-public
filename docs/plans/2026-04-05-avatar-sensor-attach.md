# Avatar Sensor Attach Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a stable, agent-facing way to attach sensors to semantic avatar body points without exposing raw SMPL-X bone objects as scene objects.

**Architecture:** Keep `set_sensor` as the active control path and use `scene.query_avatars` with `avatars[].attachment_points` so the agent can discover supported semantic points in the same avatar query. Unity resolves semantic points to real avatar transforms internally; Python validates the parameters and teaches the prompt to use the query-first path.

> Current note: the original standalone avatar attachment-points query was removed. Use `scene.query_avatars` and read `avatars[].attachment_points`.

**Tech Stack:** Python `unittest`, Unity Scene API V2, Rider/PyCharm MCP, Unity Test Runner

---

### Task 1: Add failing tests for the new contract

**Files:**
- Modify: `VsensPython/tests/test_agent_core_protocol.py`
- Modify: `VsensAgent/Assets/Tests/Editor/SceneApi/AvatarSceneApiTests.cs`

**Step 1: Write the failing Python tests**

- Add one test that expects the prompt to mention `scene.query_avatars` with `avatars[].attachment_points`.
- Add one skill/protocol test that expects `set_sensor` to accept `attach_mode=avatar_joint`, `avatar_id`, and `joint_name`.

**Step 2: Write the failing Unity tests**

- Add one query test that expects `scene.query_avatars` to return the supported semantic points for `avatar_main`.
- Add one execution test that expects `set_sensor` with `attach_mode=avatar_joint` to parent a sensor under the resolved avatar joint transform.

**Step 3: Run the tests and verify they fail**

Run:
- `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`
- Unity Test Runner for `VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`

Expected:
- Python test fails because the prompt/skill path does not know the new query/parameters yet.
- Unity test fails because the query/action path does not exist yet.

### Task 2: Implement the Unity query and attachment path

**Files:**
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiModels.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneQueryService.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/SceneApiManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/SceneApi/V2/AvatarRuntimeManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Core/Managers/ControlManager.cs`
- Modify: `VsensAgent/Assets/VsensAgent/Network/WsClient.cs`

**Step 1: Add query models**

- Add a serializable model for avatar attachment points with:
  - `avatar_id`
  - `joint_name`
  - `world_position`
  - `world_rotation`
  - optional `description`

**Step 2: Add runtime resolution helpers**

- In `AvatarRuntimeManager`, add a stable mapping from semantic points to avatar transforms:
  - `head`
  - `chest`
  - `waist`
  - `left_wrist`
  - `right_wrist`
  - `left_ankle`
  - `right_ankle`
- Resolve these from the current SMPL-X avatar internally.

**Step 3: Add the query**

- Add `avatars[].attachment_points` to the avatar query response.
- Return the supported points with the managed avatar.

**Step 4: Extend `set_sensor` execution**

- In `ControlManager`, when `attach_mode=avatar_joint`:
  - resolve the avatar
  - resolve the semantic joint transform
  - parent the sensor to that transform
  - apply optional local offset / local rotation
- Keep ordinary sensor placement behavior untouched.

**Step 5: Run Unity tests and verify they pass**

Run:
- Unity Test Runner for `VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`

Expected:
- Query test passes.
- Sensor attach test passes.

### Task 3: Implement the Python-side validation and prompt updates

**Files:**
- Modify: `VsensPython/core/skills/scene_skills.py`
- Modify: `VsensPython/data/prompts/features/control.txt`
- Modify: `VsensPython/data/prompts/features/scene_query.txt`
- Modify: `VsensPython/tests/test_agent_core_protocol.py`

**Step 1: Extend `set_sensor` validation**

- Allow `attach_mode=avatar_joint`.
- Require `avatar_id` and `joint_name` when that mode is used.
- Keep current sensor-type validation intact.

**Step 2: Update the prompt**

- Tell the agent to query `scene.query_avatars` and use `avatars[].attachment_points` before attaching sensors to avatar body points.
- Tell the agent not to guess raw joint object names.

**Step 3: Run Python tests and verify they pass**

Run:
- `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`

Expected:
- Prompt/skill tests pass.

### Task 4: Update current docs only

**Files:**
- Modify: `docs/scene_api/QUERY_API.md`
- Modify: `docs/scene_api/ACTION_TYPES.md`
- Modify: `docs/architecture/AVATAR_MOTION_RUNTIME.md`
- Modify: `docs/architecture/REFACTOR_CHECKLIST.md`

**Step 1: Document the new current contract**

- Document `scene.query_avatars` with `avatars[].attachment_points`
- Document `set_sensor` avatar-joint attach mode
- Clarify that raw joints are not scene objects and attachment goes through semantic points

**Step 2: Re-run the relevant tests**

Run:
- `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`
- Unity Test Runner for `VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`

Expected:
- Tests stay green.

### Task 5: Final verification

**Files:**
- No code changes

**Step 1: Run focused verification**

Run:
- `cd <repository>/VsensPython && python -m unittest tests.test_agent_core_protocol -v`
- Unity Test Runner for `VsensAgent.Tests.Editor.SceneApi.AvatarSceneApiTests`
- Unity Test Runner for `VsensAgent.Tests.Editor.Network.WsClientTests`

**Step 2: Confirm active behavior**

- `scene.query_avatars` returns semantic body points in `avatars[].attachment_points`.
- `set_sensor` with `attach_mode=avatar_joint` can attach a sensor to `avatar_main`.
- Current docs describe only the active path.
