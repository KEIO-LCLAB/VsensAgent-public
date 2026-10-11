# VsensAgent Architecture Overview

**Current state:** collaboration-oriented virtual sensing prototype with Unity scene control, Python agent runtime, and an in-progress Scene API v2 convergence.

## Runtime Split

### Unity

Unity is the interactive scene runtime. It is responsible for:

- scene rendering and simulation
- avatar/object/sensor manipulation
- chat and scene-facing UI
- websocket transport to Python
- action execution and scene version tracking

Main areas:

- [VsensAgent/Assets/VsensAgent/Network](../../VsensAgent/Assets/VsensAgent/Network)
- [VsensAgent/Assets/VsensAgent/UI](../../VsensAgent/Assets/VsensAgent/UI)
- [VsensAgent/Assets/VsensAgent/SceneApi/V2](../../VsensAgent/Assets/VsensAgent/SceneApi/V2)
- [VsensAgent/Assets/VsensAgent/Core](../../VsensAgent/Assets/VsensAgent/Core)

### Python

Python is the agent runtime. It is responsible for:

- prompt assembly and OpenAI calls
- conversation and structured-response routing
- working memory and episodic memory
- proactive perception / heartbeat handling
- motion preparation and caching for avatar actions
- websocket request handling
- job lifecycle scaffolding

Main areas:

- [VsensPython/core](../../VsensPython/core)
- [VsensPython/vsens_server.py](../../VsensPython/vsens_server.py)
- [VsensPython/vsens_openai.py](../../VsensPython/vsens_openai.py)
- [VsensPython/data/prompts](../../VsensPython/data/prompts)

## Current Architectural Direction

The project is moving away from a single legacy chat-plus-`<control>` path toward a collaboration runtime with multiple structured interaction modes.

Current message families:

- `conversation`
- `clarification`
- `proposal`
- `job`
- Scene API query/action/versioning calls

Avatar-motion control is now also part of the Scene API action/query layer. Python prepares motions, Unity manages avatar runtime state, and the spawned avatar is represented as a normal scene object.

This gives the agent and user a shared loop:

1. discuss a sensing goal
2. inspect the current scene
3. ask clarifying questions when intent is ambiguous
4. present candidate deployment or experiment plans
5. execute scene mutations transactionally
6. run longer tasks such as collection or simulation
7. iterate based on results

## Scene Runtime Convergence

The most important architectural change so far is that scene mutation semantics are no longer treated as a side effect of chat replies alone.

The new direction is:

- scene reads now have a minimal query-first loop and should expand from there
- scene writes should be versioned and transactional
- both user-driven and agent-driven edits should flow through the same version-aware mutation model

Use these docs as the scene contract:

- [Scene API Overview](../scene_api/OVERVIEW.md)
- [Scene Model](../scene_api/SCENE_MODEL.md)
- [Scene Versioning](../scene_api/SCENE_VERSIONING.md)
- [Transaction Rules](../scene_api/TRANSACTION_RULES.md)
- [Avatar Motion Runtime](AVATAR_MOTION_RUNTIME.md)

## Prompt And Agent Coupling

The collaboration features are only reliable when runtime support and prompt support are added together.

Current prompt system:

- core policy and output contract under [data/prompts/core](../../VsensPython/data/prompts/core)
- feature instructions under [data/prompts/features](../../VsensPython/data/prompts/features)
- examples under [data/prompts/examples](../../VsensPython/data/prompts/examples)
- registry under [features.json](../../VsensPython/data/prompts/manifests/features.json)

See [Prompt Architecture](../../VsensPython/docs/PROMPT_ARCHITECTURE.md).

## Current Gaps

- structured UI widgets for clarification/proposal are not finished
- query-first exists as an MVP, but richer multi-query planning and result/report plumbing are not finished
- `job.*` is still a skeleton, not a full experiment pipeline
- result/report/artifact delivery is not formalized yet
- Unity verification is weaker than Python verification

For detailed status, use [Architecture Refactor Checklist](REFACTOR_CHECKLIST.md).
