# Scene API v2

Scene API v2 defines a new protocol for sensing simulation in Unity.

This directory should stay focused on current scene-runtime contracts.
Examples, old planning notes, and implementation checklists should live under the legacy archive unless they are still normative.

## Goals
- Action-first execution model.
- Query-first context retrieval by agent.
- Synchronous strict transactions by default.
- Stable identity (`id`) first; alias only for lookup.
- No backward compatibility constraints with legacy protocol.

## Scope
- Unified scene model.
- Query API for context, relations, and spatial placement.
- Action validate/execute APIs.
- Transaction and rollback semantics.
- Error model and observability contract.

## Out of Scope
- Legacy `control.actions` compatibility.
- Multi-tenant write concurrency.
- Monthly/yearly storage policy details.

## Terminology
- `SceneObject`: canonical object entity in scene graph.
- `Surface`: mountable geometric plane region.
- `Relation`: semantic/spatial edge between entities.
- `scene_version`: monotonic snapshot version.
- `strict`: all-or-nothing execution policy.

## Document Map
- `OVERVIEW.md`: module responsibilities and when-to-use guide.
- `SCENE_MODEL.md`: entity/relationship schema.
- `SCENE_VERSIONING.md`: consistency/version semantics.
- `QUERY_API.md`: query endpoint contracts.
- `PLACEMENT_QUERY.md`: candidate generation/scoring.
- `SPATIAL_CONSTRAINTS.md`: mount/collision/coverage rules.
- `ACTION_API.md`: validate/execute API contracts.
- `ACTION_TYPES.md`: strongly typed action payloads.
- `TRANSACTION_RULES.md`: rollback and failure semantics.
- `ERROR_CODES.md`: standard error codes and hints.
- `EXECUTION_REPORT.md`: execution output schema.
- `OBSERVABILITY.md`: logging and tracing contract.
- `ACCEPTANCE_TESTS.md`: acceptance criteria and test cases.

## Legacy Material

Historical scenario and checklist documents were moved to:

- [<repository>/docs/legacy/scene_api/SCENARIO_FRIDGE_WALL_SENSOR.md](../legacy/scene_api/SCENARIO_FRIDGE_WALL_SENSOR.md)
- [<repository>/docs/legacy/scene_api/TODO.md](../legacy/scene_api/TODO.md)
