# Architecture Refactor Checklist

This checklist tracks the collaboration-oriented architecture refactor rather than the older single-path chat/control runtime.

## Completed

- Protocol families introduced across Python and Unity:
  - `conversation.*`
  - `clarification.*`
  - `proposal.*`
  - `job.*`
- Python runtime routes structured collaboration responses through [agent_core.py](../../VsensPython/core/agent_core.py)
- Python prompt system migrated from one large prompt file to modular composition:
  - `data/prompts/core/`
  - `data/prompts/features/`
  - `data/prompts/examples/`
  - `data/prompts/manifests/features.json`
- Static knowledge files now feed the default prompt and sensor validation:
  - `data/memory/knowledge/sensors.yaml`
  - `data/memory/knowledge/scene_conventions.yaml`
- Unity websocket layer recognizes the newer reply families and compatibility-maps them into existing chat flow
- Unity chat layer can send structured follow-up turns for clarification/proposal replies
- Scene mutation journaling and version bumping were unified for agent actions and manual mutation batches
- Python-side protocol and prompt regression tests cover the new message families
- Query-first MVP is implemented:
  - prompt teaches the internal `<query>` mode
  - `AgentCore` can pause a turn, query Unity, and resume with grounded context
  - the websocket server correlates `scene.query_response` and request-scoped `scene.error`
  - Unity scene-query responses now echo `request_id`
- Avatar motion MVP foundation is implemented:
  - Python can prepare and cache HY-Motion outputs as Unity-ready SMPL-X JSON
  - avatar actions are part of the current scene-control path
  - Unity runtime can manage one avatar, motion loading, and playback state
  - avatar and motion state can be queried through Scene API
  - wearable sensors can attach to semantic avatar body points through:
    - `scene.query_avatars` with `avatars[].attachment_points`
    - `set_sensor` with `attach_mode = avatar_joint`
    - formal `avatar_id` contract fields, with current default `avatar_main`
- Validation framework foundation is implemented:
  - Unity can return avatar standing candidates through Scene API
  - avatar candidate generation now uses a small ring search with diagonal and multi-distance fallbacks
  - Unity can validate avatar placement geometry and lightweight translational motion paths
  - Unity can capture deterministic runtime validation screenshots for review artifacts:
    - `avatar_eye`
    - `user_camera`
  - Python now owns the primary avatar screenshot review loop:
    - execute candidate
    - capture validation views
    - run multimodal visual review
    - retry the next candidate when needed
  - Python query-first runtime and prompt stack know the validation-oriented avatar query methods
  - avatar pose authority is now explicit:
    - agent placement remains candidate/review driven
    - manual runtime editing becomes authoritative until the user explicitly asks for pose adjustment again
  - runtime edit mode exists for `avatar_main`:
    - chat-adjacent edit toggle
    - click-to-select
    - ground-plane translation
    - yaw rotation

## Partially Completed

- `clarification` and `proposal` are wired end-to-end, but Unity still renders them mostly as text-first interactions instead of dedicated widgets
- `job.*` exists as a lifecycle skeleton, but real long-running simulation / collection / training execution is not connected yet
- avatar motion exists as a runtime foundation, but it is not promoted into `job.*` simulation/data-collection workflows yet
- Query-first exists as a minimal two-stage loop, but richer planning policies, multi-query turns, and explicit result/report plumbing are not complete yet
- Architecture docs now reflect the newer direction, but some lower-level code comments and auxiliary scripts still mention older reconstruction paths
- Unity verification is incomplete because reliable in-editor or batch test confirmation has not been re-established in this environment
- avatar setup now has Python-led screenshot review, but the review contract is still bounded and candidate-based rather than open-ended visual replanning
- runtime edit mode is avatar-only in v1 and still needs UX polish if we want full scene-view-style manipulation

## Not Started Or Not Finished

- Structured result/report/artifact message families for evaluation output, dataset export, and model artifacts
- Interactive proposal/clarification UI widgets
- Full experiment loop:
  - propose deployment
  - inspect/query scene
  - run collection or simulation job
  - evaluate results
  - refine deployment
- Stable automated Unity verification in CI or local batchmode
- Final doc pass over every secondary guide to remove stale references

## Current Exit Criteria For Phase 1

Phase 1 should be considered complete when all of the following are true:

- collaboration protocol messages are stable enough for feature work
- prompt/runtime/parser/server/UI all agree on the structured message families
- scene versioning semantics are unified
- current architecture docs point developers to the right files

Those conditions are mostly satisfied now.

## Current Exit Criteria For Phase 2

Phase 2 is the next real milestone:

- clickable clarification/proposal UI
- richer query-first scene lookup loop beyond the current MVP
- actual job execution and progress reporting
- structured result/artifact delivery
- multimodal screenshot review or richer visual semantics for avatar/sensor validation
- broader generic runtime editing beyond avatar
- reliable Unity-side verification
