# Collaborative Virtual Sensing Design

**Date:** 2026-03-07  
**Status:** Approved discussion draft  
**Scope:** Documentation reorganization and implementation readiness for the
next runtime slice

---

## 1. Problem Statement

VsensAgent is evolving from a reactive "chat + `<control>` block" prototype
into a collaborative virtual sensing system where:

- a user and an agent co-design sensor deployments,
- both can inspect and modify the scene,
- the system can run simulations, collect data, and evaluate simple models,
- the final output may be a deployment recommendation, a dataset, or a trained
  classifier.

The current repository already contains most of the pieces required for this
direction, but they are split across two parallel tracks:

1. the legacy interaction path (`text_chat`, `transcribe_and_reply`,
   `agent_ready`, `<control>`),
2. the Scene API v2 path (`scene.query_*`, `scene.execute_actions`,
   `scene_version`, strict execution reports).

The immediate goal is not a rewrite. The goal is to converge these tracks into
one collaboration-ready protocol and document structure.

---

## 2. Existing Context

### Runtime state today

- Unity already contains network protocol DTOs, heartbeat support, and a
  `SceneApi/V2` area.
- Python already contains `AgentCore`, memory modules, proactive heartbeat
  handling, and agent status broadcasting.
- Scene API v2 docs already define the strongest contracts in the repo:
  identity, queries, placement search, action validation/execution,
  error codes, and observability.

### Current tension

The user-facing interaction model is still centered on natural-language turns
that optionally emit low-level control commands, while the strongest scene
contracts are modeled as explicit query/action APIs. This creates ambiguity
about where planning ends and execution begins.

---

## 3. Goals

- Keep a single coherent collaboration loop across chat, scene inspection,
  proposals, execution, and experiment jobs.
- Preserve the value of Scene API v2 as the authoritative scene runtime
  contract.
- Avoid a big-bang migration that breaks the current prototype.
- Make user edits and agent edits participate in the same scene consistency
  model.
- Prepare the codebase for later simulation/data/modeling work without
  prematurely splitting into multiple independent agents.

## 4. Non-Goals

- Rewriting the entire Unity or Python runtime in one step.
- Building a full multi-agent orchestration layer now.
- Solving multi-user concurrency in v1 of this convergence work.
- Designing the final dataset schema or ML stack in this document.

---

## 5. Approaches Considered

### Approach A: Keep the four existing message classes

Use `comment/command`, `snapshot`, `query`, and `action` as the top-level
interaction model with minimal changes.

**Pros**
- Fastest path for experimentation.
- Lowest short-term implementation cost.

**Cons**
- `query` mixes scene lookups and user clarification.
- `action` mixes proposal and execution.
- `snapshot` is too narrow once heartbeat, diffs, and sensor traces are added.
- Long-running work like simulation or training has no natural home.

### Approach B: Layered typed protocol over the current runtime

Introduce a clearer taxonomy while keeping the current runtime pieces and
migrating incrementally.

**Pros**
- Fits the repo's actual direction.
- Keeps Scene API v2 authoritative for scene mutation.
- Supports collaboration, approval, and long-running jobs cleanly.
- Allows legacy compatibility during transition.

**Cons**
- Requires explicit migration rules and dual handling for a period.
- Slightly more upfront documentation and DTO work.

### Approach C: Full event/job-driven architecture first

Redesign everything around event streams, jobs, and asynchronous artifacts.

**Pros**
- Strong long-term model for simulation and experimentation.
- Scales well once workflows become complex.

**Cons**
- Too heavy for the current prototype stage.
- Introduces orchestration complexity before the core collaboration loop is
  stable.

### Recommendation

Choose **Approach B**. It delivers the needed structure without discarding the
working parts of the current system.

---

## 6. Recommended Architecture

Use one external collaboration protocol with three conceptual layers.

### 6.1 Collaboration Layer

This is the human-facing layer.

- `conversation.*`
  - Free-form chat turns.
- `clarification.*`
  - Agent asks the user to disambiguate targets, pick options, or confirm
    assumptions.
- `proposal.*`
  - Agent presents candidate sensor placements, scenario setups, or experiment
    plans before mutating the scene.

### 6.2 Scene Runtime Layer

This is the deterministic world model and execution layer.

- `observation.*`
  - Full snapshots, heartbeats, diffs, and sensor traces.
- `scene.query_*`
  - Read-only, structured access to objects, relations, surfaces, and
    placements.
- `scene.validate_*` / `scene.execute_*`
  - Transactional scene mutation with explicit reports and `scene_version`.

### 6.3 Experiment Layer

This is the layer that supports research outcomes beyond scene editing.

- `job.*`
  - Start/cancel/progress/complete for simulation, data collection, training,
    and export.
- `result.*`
  - Structured reports, rankings, metrics, and validation outputs.
- `artifact.*`
  - Dataset handles, configuration bundles, evaluation reports, and trained
    model outputs.

---

## 7. Message Taxonomy

The recommended first-class message families are:

| Family | Purpose | Typical Initiator | Sync/Async |
| --- | --- | --- | --- |
| `conversation.*` | normal user-agent exchange | user / agent | sync |
| `observation.*` | scene snapshot, heartbeat, diff, sensor trace | Unity | async or periodic |
| `scene.query_*` | read-only world lookup | agent | sync |
| `clarification.*` | ask user to choose, approve, or disambiguate | agent | sync |
| `proposal.*` | present candidate actions or experiment setup | agent | sync |
| `scene.validate_*` / `scene.execute_*` | deterministic world mutation | agent or UI tooling | sync |
| `job.*` | long-running simulation / collection / training | user / agent | async |
| `status.*` / `event.*` | progress, interrupts, proactive pushes | agent / runtime | async |
| `result.*` / `artifact.*` | reports, metrics, datasets, models | runtime | async |

### Important split decisions

- `snapshot` should be renamed conceptually to `observation`, because the
  system already needs heartbeats and will soon need diffs and traces.
- `query` must be split into:
  - scene queries (`scene.query_*`),
  - user clarification (`clarification.*`).
- `action` must be split into:
  - proposal (`proposal.*`),
  - execution (`scene.validate_*` and `scene.execute_*`).

---

## 8. Single-Agent Recommendation

Do **not** start by splitting the runtime into four separate agents.

For the current stage, the better architecture is:

- one orchestrator agent,
- typed tools and protocols,
- deterministic scene services,
- optional internal specialization later.

If future complexity demands internal roles, a natural split is:

- dialogue/planning,
- scene reasoning and placement,
- experiment manager,
- data/model analysis.

That split should happen behind the same external protocol, not by changing the
interface contract first.

---

## 9. Consistency and Versioning

This is the most important implementation constraint.

The current Scene API v2 contract assumes an optimistic `scene_version` check
with a single-writer execution model. That is already strong enough for the
prototype **if** all scene mutations are normalized through one path.

### Rule

User edits and agent edits must both become versioned mutations.

### Why

If users can drag objects directly in Unity while the agent plans against an
older scene state, the agent will operate on stale assumptions and the
collaboration loop will break.

### Recommended policy

- any scene mutation increments `scene_version`,
- all execution reports expose the before/after version,
- stale actions fail with `SCENE_VERSION_MISMATCH`,
- the agent re-queries and regenerates proposals on mismatch,
- manual Unity edits should be journaled as first-class scene mutations.

---

## 10. Data Flow

The target collaborative loop is:

1. User asks for help with a sensing task.
2. Agent issues `scene.query_*` calls and inspects recent `observation.*`
   context.
3. Agent returns `proposal.*` with candidate placements or experiment plans.
4. User modifies or approves the proposal through `clarification.*`.
5. Agent calls `scene.validate_*`.
6. Agent calls `scene.execute_*`.
7. Unity emits updated `observation.*`.
8. User or agent starts a `job.*` for simulation, data collection, or model
   training.
9. Runtime emits `status.*`, `result.*`, and `artifact.*`.
10. Agent interprets results and proposes the next iteration.

---

## 11. Error Handling

Error handling should be explicit and machine-readable.

### Scene/runtime errors

Continue using the existing Scene API v2 error model:

- `TARGET_NOT_FOUND`
- `UNSUPPORTED_ACTION`
- `INVALID_PARAM`
- `SCENE_VERSION_MISMATCH`
- `CONSTRAINT_VIOLATION`
- `PLACEMENT_*`
- `TRANSACTION_ROLLBACK_FAILED`

### Collaboration errors

Add protocol-level handling for:

- unanswered clarifications,
- expired proposals,
- cancelled jobs,
- interrupted long-running tasks,
- missing artifacts,
- unsupported UI affordances for a message family.

### Recovery pattern

Prefer retry by query and regeneration rather than hidden heuristics.

---

## 12. Testing Strategy

The first convergence slice should be tested at four levels.

### Contract tests

- Python serialization/parsing for new message families.
- Unity DTO parse coverage for protocol envelopes.

### Runtime unit tests

- AgentCore routing between conversation, proposal, and execution.
- Heartbeat and event behavior under mixed scene changes.
- Version mismatch and rollback paths.

### Integration tests

- End-to-end request flow for:
  - proposal without mutation,
  - validation followed by execution,
  - stale version rejection and re-query.

### Manual acceptance

- user modifies scene while agent is planning,
- agent asks for target clarification,
- agent proposes placement options,
- user approves one option,
- system executes and returns structured report.

---

## 13. Documentation Reorganization

The documentation should be read in the following layers:

1. `docs/README.md`
   - repo-level map and reading order
2. `docs/plans/`
   - active design docs and implementation plans
3. `docs/architecture/`
   - current runtime architecture
4. `docs/communication/`
   - transport-level and envelope-level contracts
5. `docs/scene_api/`
   - authoritative scene runtime contract

Near-term doc work should avoid duplicating Scene API v2 details. The design
docs should explain how pieces fit together; the API reference should remain
the source of truth for request/response details.

---

## 14. Roadmap

### Phase 0: Documentation and protocol convergence planning

- Reorganize doc entry points.
- Capture the approved protocol taxonomy.
- Produce a repo-specific implementation plan.

### Phase 1: Protocol convergence MVP

- Introduce proposal/clarification envelopes.
- Keep legacy chat flow working.
- Unify conversation and scene runtime routing.

### Phase 2: Versioned collaborative scene editing

- Journal user and agent mutations through one consistency model.
- Surface validation/execution reports in the UI.

### Phase 3: Spatial planning and simulation

- Strengthen placement reasoning and scenario controls.
- Support avatar motion setup and repeatable simulation cases.

### Phase 4: Experiment jobs

- Data collection, export, and training become explicit jobs with progress and
  artifacts.

### Phase 5: Evaluation and iterative optimization

- Baseline classifiers, metrics, and result interpretation feed back into the
  proposal loop.

---

## 15. Assumptions for the Next Step

This design assumes the next implementation slice prioritizes:

- protocol convergence,
- version-safe collaboration,
- proposal-before-execution behavior,
- implementation readiness over feature breadth.

That is the smallest slice that meaningfully prepares the project for the
larger virtual sensing workflow.
