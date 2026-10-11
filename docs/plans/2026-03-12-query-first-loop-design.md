# Query-First Loop Design

**Date:** 2026-03-12  
**Status:** Approved discussion draft  
**Scope:** Minimal query-first orchestration for the current collaboration runtime

---

## 1. Problem Statement

VsensAgent already has three important pieces:

- prompt guidance that says the agent should use query-first reasoning,
- a Unity-side Scene API runtime that can answer `scene.query_*` requests,
- typed collaboration replies such as `clarification.*` and `proposal.*`.

What it does not have yet is the actual runtime loop that connects them.

Today the Python side still handles a user turn as one mostly linear step:

1. build prompt,
2. call the LLM,
3. parse `clarification` / `proposal` / `control`,
4. return a final reply.

That means the agent can talk *about* querying, but it cannot reliably pause a turn, ask Unity for more scene detail, and continue reasoning from the returned result. This is the main remaining gap between the current prototype and a world-grounded collaborative agent.

---

## 2. Existing Constraints

### Runtime state today

- Python `AgentCore` owns the main text/voice interaction path.
- Python `VsensWebSocketServer` currently processes one incoming message at a time per connection.
- Unity `WsClient` already routes `scene.query_*` requests to `SceneApiManager`.
- Unity `SceneQueryService` already returns structured read-only query results.

### Architectural tension

The current server loop blocks while handling a user turn. That is acceptable for simple request/response chat, but it prevents the server from:

- sending a mid-turn query request to Unity,
- continuing to read the socket,
- receiving the matching `scene.query_response`,
- resuming the suspended turn.

This is the core runtime limitation that must change for query-first reasoning to become real.

---

## 3. Goals

- Let the Python agent issue read-only scene queries during a user turn.
- Keep the external user-facing protocol stable for this MVP.
- Reuse the existing `scene.query_*` Unity runtime instead of inventing a separate query service.
- Preserve current collaboration reply families:
  - `conversation.reply`
  - `clarification.request`
  - `proposal.ready`
  - control-backed conversation replies
- Add timeout/error fallback so a failed query does not deadlock the interaction.

## 4. Non-Goals

- Full agent tool framework redesign.
- User-visible `query.*` message family.
- Multi-client or multi-user concurrency semantics.
- Full scene mirror/cache synchronization in Python.
- Full experiment pipeline (`job.*`, `result.*`, `artifact.*`) in this slice.

---

## 5. Approaches Considered

### Approach A: Internal query orchestration MVP

Teach the LLM to emit an internal `<query>{...}</query>` block when it needs more scene detail. The Python server consumes that block, sends a `scene.query_*` request to Unity, waits for the result, then continues with a second LLM call that produces the final collaboration reply.

**Pros**
- Smallest change that creates a real query-first loop.
- Reuses existing Unity Scene API infrastructure.
- Preserves current user-visible protocol families.

**Cons**
- Introduces a lightweight two-stage orchestration path on the Python side.
- Query is still an internal mode, not yet a full first-class external protocol family.

### Approach B: Full explicit query protocol family

Promote query to a full user-visible structured reply family alongside proposal and clarification.

**Pros**
- Strongest conceptual symmetry.
- Cleaner long-term protocol taxonomy.

**Cons**
- More prompt, parser, server, UI, and protocol churn than needed for the MVP.
- Adds interface complexity before the loop itself is proven.

### Approach C: Python-side scene mirror first

Build a stronger scene cache or mirror in Python and reduce live query frequency.

**Pros**
- Better long-term foundation for planning and experimentation.
- Potentially lower latency after warm-up.

**Cons**
- Introduces consistency and invalidation complexity too early.
- Solves a later optimization before the basic loop is working.

### Recommendation

Choose **Approach A** for the next slice.

---

## 6. Recommended Architecture

The MVP should add one new internal response mode while keeping all existing external reply families.

### 6.1 Internal Query Mode

The LLM may emit:

```xml
<query>
{
  "method": "scene.query_objects",
  "params": {
    "ids": [],
    "aliases": ["CoffeeMaker"],
    "tags": [],
    "zone_id": ""
  },
  "reason": "Need the canonical object id and bounds before proposing placement."
}
</query>
```

Properties:

- `method`
  - One of:
    - `scene.query_summary`
    - `scene.query_objects`
    - `scene.query_relations`
    - `scene.query_surfaces`
- `params`
  - Query-specific request payload fields
- `reason`
  - Human-readable explanation for debugging/logging only

For this MVP:

- support only one `<query>` block per LLM reply,
- support only one query per orchestration step,
- allow multiple query rounds only by re-running the LLM after each result,
- cap the number of query rounds per user turn.

### 6.2 External Collaboration Replies

After query resolution, the final reply must still be one of the existing outcomes:

- `conversation.reply`
- `clarification.request`
- `proposal.ready`
- control-backed conversation reply

The user should not need to understand or manually participate in the mid-turn query exchange.

---

## 7. Request/Response Correlation

Scene queries need correlation IDs because the Python server must match a Unity response to the suspended user turn that initiated it.

### Query request shape

Python should send:

```json
{
  "type": "scene.query_objects",
  "request_id": "qry_123",
  "ids": [],
  "aliases": ["CoffeeMaker"],
  "tags": [],
  "zone_id": ""
}
```

### Query response shape

Unity should reply with:

```json
{
  "type": "scene.query_response",
  "request_id": "qry_123",
  "method": "scene.query_objects",
  "scene_version": 104,
  "objects": [...]
}
```

### Error shape

Unity should also include `request_id` when it emits a scene error related to a query request:

```json
{
  "type": "scene.error",
  "request_id": "qry_123",
  "code": "INVALID_PARAM",
  "message": "..."
}
```

This lets Python resolve or fail the pending future instead of waiting until timeout.

---

## 8. Python Runtime Changes

### 8.1 AgentCore becomes two-stage when needed

`AgentCore` should no longer assume that one LLM call always produces a final reply.

Instead:

1. build the normal prompt from user text, memory, and scene summary/diff,
2. call the LLM,
3. parse for `<query>`,
4. if absent:
   - continue with the current final-reply path,
5. if present:
   - call a query executor,
   - inject the query result into a follow-up prompt,
   - call the LLM again,
   - parse the final reply families as usual.

### 8.2 Query execution stays outside AgentCore transport details

`AgentCore` should not own websocket transport details.

Instead it should receive an async query-executor callback from the server layer, for example:

```python
await core.handle_text(message, scene_snapshot, query_executor=...)
```

This keeps `AgentCore` responsible for orchestration logic while leaving socket ownership inside `VsensWebSocketServer`.

### 8.3 Timeout and fallback

If a query times out or returns a scene error:

- the turn must not hang,
- the agent should fall back to a safe explanation or clarification-style response,
- the error should be surfaced in logs and tests.

---

## 9. Server Connection Model

This is the most important runtime refactor in the slice.

### Problem

The current websocket loop waits for a full handler result before it continues reading the connection. That works for ordinary request/response chat, but not for mid-turn query orchestration.

### Required change

The server should move to a lightweight per-connection interaction model:

- keep reading the websocket continuously,
- route `scene.query_response` and `scene.error` immediately to a pending-query table,
- run a user turn in an async task,
- allow only one active user-turn task per connection for this MVP.

### Minimal per-connection state

- `active_turn_task`
- `pending_queries: dict[request_id, asyncio.Future]`

This is enough to support one suspended query-first interaction without introducing broad concurrency complexity.

---

## 10. Unity Runtime Changes

The Unity side already has most of the machinery needed for this slice.

### Required updates

- `SceneApiManager` must echo `request_id` on all query responses.
- `SceneApiManager` should include `request_id` in `scene.error` when possible.

### Not required for this MVP

- new chat UI
- new editor tooling
- user-visible query widgets

The Unity role in this slice is mostly to become a reliable correlated query responder for the Python orchestrator.

---

## 11. Prompt Changes

The prompt stack must explicitly teach the model that query is an internal response mode.

The current `scene_query` feature already teaches the idea of query-first reasoning, but the MVP needs stronger guidance:

- when to emit `<query>`,
- what methods are allowed,
- what parameters are expected,
- that the agent should not output final proposal/execution content in the same turn when it still lacks required scene facts.

This should live in the modular prompt system, not in ad hoc string concatenation.

---

## 12. Testing Strategy

The MVP should add or extend tests at four levels.

### Parser tests

- `<query>` block extraction
- spoken text stripping
- malformed query JSON behavior

### AgentCore tests

- query path triggers a second-stage completion
- final reply uses query result context
- query timeout fallback returns a safe reply

### Server protocol tests

- pending query futures resolve on `scene.query_response`
- `scene.error` resolves a pending failure path
- only one active user turn is allowed per connection

### Unity regression tests

- query response includes `request_id`
- existing scene query behavior remains intact

---

## 13. MVP Acceptance Criteria

This slice should be considered complete when:

- the LLM can emit a valid internal `<query>` block,
- Python can pause a turn, send `scene.query_*`, and resume after `scene.query_response`,
- Unity query responses include `request_id`,
- final replies still land in the existing collaboration families,
- query failures do not deadlock the conversation,
- Python regression tests cover the orchestration path,
- the new architecture is documented in plans and referenced from current docs.

---

## 14. Follow-On Work

Once this MVP is stable, the next natural slices are:

1. richer multi-step query planning,
2. real `job.*` execution and progress,
3. structured `result.*` / `artifact.*`,
4. stronger Unity verification and batch testing,
5. optional promotion of query into a more explicit external protocol family if it proves useful.
