# Python Agent Architecture

This document describes the current Python runtime, not the older single-path `VsensInteractionManager` architecture.

## Main Runtime Pieces

### WebSocket Server

[vsens_server.py](../../VsensPython/vsens_server.py) is the integration boundary with Unity.

It currently handles:

- conversation requests
- clarification/proposal follow-up turns
- query-first mid-turn scene lookups
- mid-turn scene action execution for avatar validation/retry
- job lifecycle requests
- reset and compatibility aliases
- heartbeat and push-oriented flows

For `query-first` turns, the server now keeps a pending request table, sends `scene.query_*` and `scene.execute_actions` requests to Unity mid-turn, and resumes the active interaction task when the matching response arrives.

### Agent Core

[agent_core.py](../../VsensPython/core/agent_core.py) is the main orchestration layer.

It is responsible for:

- building prompt-ready turns from user input and scene state
- routing plain replies vs structured `<clarification>`, `<proposal>`, `<query>`, and `<control>` outputs
- running a two-stage query-first completion path when the model emits an internal `<query>` block
- executing avatar candidate attempts directly through Scene API when screenshot review is required
- running a separate multimodal visual-review pass over validation screenshots and deciding bounded retry vs accept
- respecting avatar pose authority:
  - `agent` pose can be repositioned through the normal candidate loop
  - `manual` pose is preserved unless the user explicitly asks to move/adjust/optimize it
- coordinating memory and perception helpers
- emitting protocol-shaped messages back to the server

The first LLM pass may emit an internal `<query>` block instead of a final user-facing reply. `AgentCore` then executes the query through `QueryFirstCoordinator`, injects the correlated scene result into a follow-up prompt, and asks the model for the final collaboration message. If the scene lookup times out or returns a request-scoped `scene.error`, `AgentCore` degrades to a safe plain reply instead of hanging the turn.

The intermediate query-planning pass is now treated as transient runtime state. The main conversation history keeps the original assembled user turn and the final assistant reply, but it does not persist the internal `<query>` exchange or the synthetic follow-up prompt that carried the query result.

For avatar tasks, there is now a second transient pass as well: after candidate selection, Python can execute an avatar attempt, request validation screenshots, and send those screenshots through a separate multimodal visual-review prompt. That review pass is also non-persistent; it does not pollute the main user-visible conversation history.

The current avatar visual-review packet uses exactly two labeled images:

- `avatar_eye`: what the avatar sees from a head/eye-height forward-facing view
- `user_camera`: what the current runtime user camera sees

Python is now the sole screenshot-based accept/retry authority. Unity still performs geometric
preflight validation, but it no longer makes the final screenshot-based placement decision.

The current avatar-placement loop in Python is:

1. query avatar state via `scene.query_avatars`
2. respect manual pose authority unless the user explicitly asks to adjust or optimize pose
3. query candidates
4. run geometric placement validation
5. execute avatar actions in Unity
6. request `scene.capture_validation_views`
7. build a review packet from exactly two captures:
   - `avatar_eye`
   - `user_camera`
8. run a non-persistent multimodal review pass
9. accept or retry the next candidate

### Protocol Layer

Current protocol helpers live under:

- [core/protocol/messages.py](../../VsensPython/core/protocol/messages.py)
- [core/protocol/user_turns.py](../../VsensPython/core/protocol/user_turns.py)

These files define the current structured collaboration message shapes.

### Prompt System

[vsens_openai.py](../../VsensPython/vsens_openai.py) now loads the runtime prompt through [composer.py](../../VsensPython/core/prompting/composer.py).

The prompt is assembled from:

- [data/prompts/core](../../VsensPython/data/prompts/core)
- [data/prompts/features](../../VsensPython/data/prompts/features)
- [data/prompts/examples](../../VsensPython/data/prompts/examples)
- [features.json](../../VsensPython/data/prompts/manifests/features.json)
- static knowledge YAML under [data/memory/knowledge](../../VsensPython/data/memory/knowledge)

This is where the model is taught when to produce `clarification`, `proposal`, `control`, and job-oriented responses.

`scene_query` is now also part of the prompt feature stack. It teaches the model to use an internal `<query>` block only when scene grounding is required before it can safely produce a final reply.

The `control` prompt feature now also teaches avatar-motion actions. The Python runtime can implicitly prepare motion JSON during `load_avatar_motion` skill dispatch instead of exposing a separate user-visible motion-preparation protocol.

The default composed prompt now also includes static domain knowledge derived from:

- [sensors.yaml](../../VsensPython/data/memory/knowledge/sensors.yaml)
- [scene_conventions.yaml](../../VsensPython/data/memory/knowledge/scene_conventions.yaml)

That keeps sensor availability, naming conventions, and coordinate-system guidance aligned with the current knowledge files rather than relying on stale hardcoded prompt text alone.

### Memory And Perception

Important subareas under [core](../../VsensPython/core):

- `memory/`
  - working memory
  - episodic memory
  - scene relevance/filtering
- `perception/`
  - heartbeat processing
  - scene diff classification
- `skills/`
  - control parsing and scene skill registration
- `jobs/`
  - in-memory lifecycle scaffolding for longer-running tasks
- `motion/`
  - remote HY-Motion integration
  - `.npz` to SMPL-X JSON conversion
  - Python-side disk cache for prepared avatar motions

## Current Response Modes

The Python side now has a clearer response taxonomy:

- plain conversation reply
- clarification request
- proposal presentation
- control execution intent
- job lifecycle messaging

Internally, there is also one non-user-facing mode:

- query-first lookup request via `<query>`

Only one primary structured mode should be emitted per turn.

## Verification Status

Python-side protocol and prompt tests currently cover:

- prompt composition
- structured protocol messages
- user-turn reconstruction
- server routing
- agent core structured response routing
- job lifecycle scaffolding
- heartbeat/perception regression checks

See [tests](../../VsensPython/tests) and [test_phase3.py](../../VsensPython/test_phase3.py).

## Legacy Note

If you need the older reconstruction notes, phase notes, or narrative walkthroughs, use [Legacy Archive](../legacy/README.md) instead of treating them as current architecture docs.
