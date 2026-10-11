# Scene API v2 Overview

This document explains what each Scene API v2 module does and when to use it.

## One-Line Positioning
Scene API v2 is an **Action-first + Query-first** runtime contract for simulation-oriented scene reasoning and execution.

## Architecture Modules

## 1) Scene Model
- Purpose: Define canonical scene entities and relations.
- Main docs: `SCENE_MODEL.md`, `SCENE_VERSIONING.md`.
- Use when:
  - You need stable object identity (`id`) and semantics (`kind`, `capabilities`).
  - You need to reason about `Object/Surface/Zone/Relation` uniformly.

## 2) Query Layer
- Purpose: Let the agent fetch only the context it needs.
- Main docs: `QUERY_API.md`.
- Use when:
  - Agent needs scene summary, object details, relations, or mountable surfaces.
  - You want lower token cost than full snapshot push.

### Query endpoints
- `scene.query_summary`: Scene-level health and counts.
- `scene.query_objects`: Fetch objects by ids/aliases/tags/zone.
- `scene.query_relations`: Fetch semantic/spatial edges around an object.
- `scene.query_surfaces`: Fetch candidate mountable surfaces.

## 3) Spatial Planning Layer
- Purpose: Convert geometric constraints into executable placement candidates.
- Main docs: `PLACEMENT_QUERY.md`, `SPATIAL_CONSTRAINTS.md`.
- Use when:
  - Agent needs "place sensor near target on wall" behavior.
  - You need coverage/collision/occlusion-aware proposals.

### Spatial endpoints
- `scene.find_sensor_placements`: Get ranked candidates.
- `scene.validate_placement`: Validate one candidate before execution.

## 4) Action Execution Layer
- Purpose: Validate and execute action batches with strict transaction semantics.
- Main docs: `ACTION_API.md`, `ACTION_TYPES.md`, `TRANSACTION_RULES.md`.
- Use when:
  - Agent has finalized `actions[]` and wants deterministic execution.
  - You need all-or-nothing behavior and rollback on failure.

### Action endpoints
- `scene.validate_actions`: Schema/capability/constraint pre-check.
- `scene.execute_actions`: Synchronous strict execution + rollback.

## 5) Reliability & Diagnostics Layer
- Purpose: Standardize failures and runtime diagnostics.
- Main docs: `ERROR_CODES.md`, `EXECUTION_REPORT.md`, `OBSERVABILITY.md`.
- Use when:
  - Agent must self-recover based on machine-readable error codes.
  - Operators need traceability (`request_id`, `trace_id`, latency, failure stage).

## Typical Lifecycle (When to Call What)

1. `scene.query_summary`
2. `scene.query_objects` / `scene.query_surfaces` / `scene.query_relations` (as needed)
3. `scene.find_sensor_placements`
4. `scene.validate_placement` (optional but recommended)
5. `scene.validate_actions`
6. `scene.execute_actions`
7. Read `ExecutionReport` and retry via query if needed

## Decision Guide
- Need context only: use Query endpoints.
- Need feasible mounting point: use Spatial endpoints.
- Need scene mutation: use Action endpoints.
- Need failure recovery: use Error/Report contracts.

## Example Scenario
For a historical fridge-wall sensor workflow example, see [SCENARIO_FRIDGE_WALL_SENSOR.md](../legacy/scene_api/SCENARIO_FRIDGE_WALL_SENSOR.md).

## Acceptance Reference
For validation checklist and pass criteria, see `ACCEPTANCE_TESTS.md`.
