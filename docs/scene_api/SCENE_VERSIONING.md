# Scene Versioning

## Version Model
- `scene_version` is a monotonic integer.
- Version increments on any state mutation committed by `scene.execute_actions`.
- Query endpoints return current `scene_version`.

## Consistency Rules
- `scene.validate_actions` and `scene.execute_actions` must include `scene_version`.
- If request version != current version: reject with `SCENE_VERSION_MISMATCH`.
- Agent should re-query and regenerate action batch on mismatch.

## Determinism Contract
- Same `scene_version` + same query input => stable semantic output.
- Floating-point fields can have epsilon drift; sorting keys must be deterministic.

## Single-Writer Assumption
- v2 assumes single-scene, single-writer execution pipeline.
- Concurrency controls beyond optimistic version check are out of scope for v2.
