# Avatar Motion Runtime

This document describes the current avatar-motion MVP, not a future multi-avatar or job-oriented simulation system.

## Runtime Split

### Python

Python owns motion preparation.

Current responsibilities:

- convert user/agent motion intent into a prepared motion
- call the remote HY-Motion service through a job-style HTTP flow
- poll until the `.npz` result is ready
- convert `.npz` into the SMPL-X JSON shape Unity already consumes
- cache prepared motions under a Python-managed disk cache

Main implementation areas:

- [VsensPython/core/motion/service.py](../../VsensPython/core/motion/service.py)
- [VsensPython/core/skills/scene_skills.py](../../VsensPython/core/skills/scene_skills.py)

The Python side does not create or animate Unity avatars directly. It prepares motion payloads and emits normal scene actions.

### Unity

Unity owns avatar runtime state.

Current responsibilities:

- spawn and remove the managed avatar
- register the runtime avatar into the scene model through `ObjectDescriber`
- load prepared motion JSON onto the avatar
- play, pause, stop, and clear the current motion
- expose runtime avatar and motion state through Scene API queries

Main implementation area:

- [AvatarRuntimeManager.cs](../../VsensAgent/Assets/VsensAgent/SceneApi/V2/AvatarRuntimeManager.cs)

## Protocol Shape

Avatar control stays inside the existing Scene API action family.

Current action types:

- `spawn_avatar`
- `remove_avatar`
- `set_avatar_transform`
- `load_avatar_motion`
- `play_avatar_motion`
- `pause_avatar_motion`
- `stop_avatar_motion`
- `clear_avatar_motion`

Current read-only queries:

- `scene.query_avatars`
- `scene.query_motions`
- `scene.query_avatar_candidates`
- `scene.validate_avatar_placement`
- `scene.capture_validation_views`

The motion preparation step is still implicit in v1. The model can emit `load_avatar_motion` with a `motion_description`, Python prepares the motion, and Unity receives the final inline `motion_json`.

## Current Defaults

- one managed avatar only
- default avatar id: `avatar_main`
- default prefab key: `smplx_male`
- avatar `rotation` parameters are interpreted as the person's visible facing direction; the runtime
  applies the SMPL-X prefab's internal `180°` yaw offset when setting the underlying transform
- avatar pose authority is tracked as `agent` or `manual`
- any runtime user edit switches authority to `manual`
- when pose authority is `manual`, Python can still load/play motion but should not auto-reposition
  unless the user explicitly asks to move, adjust, or optimize the avatar pose
- if a motion is requested and no avatar exists, runtime auto-spawns the default avatar
- if a new motion is loaded while one is playing, runtime stops the current motion and replaces it
- Unity session state keeps a motion catalog for the current runtime session
- persistent motion cache lives on the Python side, not under Unity `Assets/`
- sensors can be attached to semantic avatar body points through `set_sensor` with:
  - `attach_mode = avatar_joint`
  - `avatar_id = avatar_main`
  - `joint_name` from `scene.query_avatars` `avatars[].attachment_points`

## Current Limits

- no multi-avatar support
- no playlist or timeline semantics
- no transition blending
- no job-level progress reporting for motion generation yet
- Unity still consumes inline motion JSON in v1; `motion_id + asset/cache path` is deferred

## Validation Runtime

The runtime now supports a first-pass validation loop for avatar tasks.

Current flow:

- query standing candidates around a task target
- validate candidate geometry before execution
- classify motions as `static` or `translational`
- for translational motions, sample the translation path and reject obvious collisions
- execute avatar placement and motion
- capture exactly two runtime validation screenshots after placement:
  - `avatar_eye`
  - `user_camera`
- run a Python-led multimodal visual review pass against the captured images
- retry the next candidate with a bounded Python-side loop when the visual review rejects the current setup

This is intentionally lightweight in v1:

- heuristic candidate generation based on a small ring search:
  - cardinal and diagonal directions around the target
  - multiple stand-off distances
  - ranked by geometry validity plus a small preferred-side bias
- sampled trajectory checks, not dense per-frame simulation
- screenshots remain saved as artifacts for inspection
- Unity does not do final screenshot scoring anymore; it supplies execution, geometric guardrails,
  and deterministic capture artifacts, while Python decides whether to accept or retry
- bounded retry is now Python-led over the candidate list
- the latest validation snapshot can be visualized in SceneView through `Tools > Vsens > Avatar Validation Debug Overlay`

### Active End-to-End Avatar Review Turn

For an agent-owned avatar placement turn, the current active pipeline is:

1. Python asks Unity for `scene.query_avatars` to check pose authority.
2. If pose authority is `agent`, Python asks Unity for `scene.query_avatar_candidates`.
3. Python asks Unity for `scene.validate_avatar_placement` for the selected candidate.
4. Python asks Unity for `scene.execute_actions` to spawn/move/load/play.
5. Python asks Unity for `scene.capture_validation_views`.
6. Unity returns exactly two deterministic artifacts:
   - `avatar_eye`
   - `user_camera`
7. Python runs the multimodal review pass and either:
   - accepts the attempt
   - retries the next candidate
   - or returns a structured failure after the bounded retry limit

## Runtime Edit Mode

Unity now also exposes a first-pass runtime edit mode for avatar placement correction.

Current behavior:

- the chat panel has an `Edit` / `Done` toggle for runtime editing
- entering edit mode lets the user select `avatar_main`
- left click on the ground moves the avatar on the floor plane
- right drag rotates the avatar around world Y
- manual edits update the scene snapshot immediately
- manual edits set avatar pose authority to `manual`

This is intentionally avatar-only in v1, but the runtime editing scaffold was kept generic so
other scene-editable objects can be added later.

## Avatar Sensor Attachment

The active avatar wearable-sensor path is:

1. Query `scene.query_avatars` to inspect the managed avatar, pose authority, and `attachment_points`.
2. Send `set_sensor` with:
   - `attach_mode = avatar_joint`
   - `avatar_id`
   - `joint_name` from `avatars[].attachment_points`
3. Unity resolves the semantic point to the current avatar rig and parents the sensor there.

This keeps the agent-facing contract stable without exposing raw internal SMPL-X bone objects.

## Scene Scale Reference

Unity world-space remains the physical source of truth.

Target authoring references:

- interior door height: about `2.0m` to `2.2m`
- countertop height: about `0.9m`
- adult avatar height: about `1.7m` to `1.8m`
- coffee maker width/depth: roughly `0.2m` to `0.4m`

If the room prefab is rescaled, the scene snapshot should continue to reflect the corrected world geometry directly without prompt-side normalization.
