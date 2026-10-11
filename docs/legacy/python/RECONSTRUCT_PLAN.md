# VsensPython Backend — Reconstruction Plan

> Historical design document. Keep for architecture history and rationale, not as the current implementation contract.
>
> Current references:
> - [<repository>/docs/architecture/REFACTOR_CHECKLIST.md](../../architecture/REFACTOR_CHECKLIST.md)
> - [<repository>/docs/architecture/PYTHON_AGENT.md](../../architecture/PYTHON_AGENT.md)

**Author**: Copilot Discussion Draft  
**Date**: February 28, 2026  
**Status**: Planning / Discussion

---

## 1. Current System Summary

The current backend is a simple **reactive request-response** pipeline:

```
Unity sends voice/text → Server routes → InteractionManager formats prompt
→ GPT-4.1 replies → Parse <control> block → Return to Unity
```

It works well for single-turn commands but has no memory beyond in-session conversation history, no ability to act without user prompts, no plan decomposition, and no scripting capabilities. For an XR sensor simulation platform to feel truly *intelligent*, the agent needs to behave more like an autonomous collaborator than a smart command dispatcher.

---

## 2. Motivation: What Is Missing

| Capability | Current State | Desired State |
|---|---|---|
| Memory | Only in-session message list | Persistent, searchable, context-aware |
| Initiative | Waits for user input | Can proactively observe and respond |
| Planning | Single LLM call per command | Decomposes complex tasks into steps |
| Scripting | Hard-coded control actions | Can write and run logic at runtime |
| Scene Awareness | Snapshot per request only | Continuous monitoring with change detection |

---

## 3. Proposed Architecture (OpenCog-inspired)

The new architecture is loosely inspired by cognitive agent frameworks (e.g., OpenCog, BabyAGI, Voyager). It separates concerns into four subsystems that communicate through a central **Agent Core**.

```
┌────────────────────────────────────────────────────────────┐
│                       Agent Core                           │
│   Coordinates all modules; entry point for all messages    │
└──────┬─────────────┬──────────────┬──────────────┬─────────┘
       │             │              │              │
  ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐  ┌─────▼──────┐
  │ Memory  │  │ Heartbeat  │  │Planner  │  │ Workspace  │
  │ Module  │  │ /Perception│  │         │  │ (Scripting)│
  └─────────┘  └────────────┘  └─────────┘  └────────────┘
       │                               │
  ┌────▼───────────────────────────────▼────┐
  │              LLM Layer (GPT-4.1)         │
  │   Tool-calling + Structured Outputs      │
  └──────────────────────────────────────────┘
       │
  ┌────▼────────────────────────┐
  │    WebSocket Server          │
  │    (Unity <-> Python)        │
  └──────────────────────────────┘
```

---

## 4. Module Breakdown

### 4.1 Memory Module

**Purpose**: Give the agent context beyond the current session. When a user asks "set up the sensor like last time", the agent can actually retrieve what "last time" meant.

**Three tiers:**

#### Working Memory (Short-term)
- Holds the current scene snapshot, active plan, and recent events
- In-process Python object (no persistence needed)
- Updated on every heartbeat and every interaction
- Replaces the current flat `scene_snapshot` dict passed around per message

#### Episodic Memory (Mid-term, Vector DB)
- Each interaction (user utterance + agent reply + scene context + control actions) gets embedded and stored
- Allows retrieval of relevant past situations at query time
- **Recommended**: ChromaDB (local, no server), with OpenAI's `text-embedding-3-small` for embeddings
- Use case examples:
  - "Retrieve similar sensor configurations used in past sessions"
  - "What did the user ask about the coffee maker last week?"
  - "Find sessions where DISTANCE sensor exceeded threshold"
- Storage: `data/memory/episodes/` as a persistent ChromaDB collection

#### Semantic Memory (Long-term, Curated)
- Static domain knowledge: sensor types, their typical configurations, known Unity object patterns
- Stored as structured YAML/JSON documents, loaded at startup
- Can be extended by the agent writing new facts through the Script Workspace
- Storage: `data/memory/knowledge/`

**Prompt Augmentation**: Before every LLM call, the memory manager injects:
```
[Relevant past context]
<3 most similar past episodes retrieved from vector DB>

[Current working memory]
<active plan step, recent events>
```

---

### 4.2 Heartbeat / Proactive Perception

**Purpose**: The agent should not just wait to be spoken to. In a sensor simulation context, interesting things happen continuously — a sensor starts reading anomalous values, the user moves near a trigger zone, a placed sensor drifts out of position. The agent should detect these and act or notify proactively.

**Design:**

Unity sends a periodic `scene_heartbeat` message to the server (configurable interval, suggested 1–2 seconds). The server registers this as a new message type alongside `transcribe_and_reply` and `text_chat`.

```python
# New message type from Unity
{
    "type": "scene_heartbeat",
    "scene_snapshot": { ... }
}
```

On receiving a heartbeat, the Perception module runs:

1. **Scene Diff**: Compare the new snapshot against the last known state in working memory. Produce a structured change log:
   ```
   - OPTICAL-01: value changed 0 → 1 (trigger)
   - user_position: moved 0.4m toward CoffeeMaker
   - Window_A: state changed open → closed
   ```

2. **Event Classification**: Classify diffs as:
   - `sensor_trigger` — a sensor crossed a threshold
   - `state_change` — an object changed state
   - `user_proximity` — user moved near an object of interest
   - `anomaly` — sensor value outside expected range
   - `no_op` — nothing meaningful changed

3. **Attention Gate**: Only wake the LLM if events are above a significance threshold. The vast majority of heartbeats will be `no_op` and cost nothing.

4. **Proactive Response**: For significant events, the agent formulates a push message to Unity:
   ```python
   # Agent-initiated push (server → Unity, no user prompt)
   {
       "type": "agent_push",
       "trigger": "sensor_trigger",
       "message": "Optical sensor one just detected presence at the coffee maker.",
       "control": { "actions": [ { "target": "OPTICAL-01", "action": "highlight" } ] }
   }
   ```

This makes the agent feel "alive" — it notices what's happening and comments or acts unprompted.

**Cost control**: The LLM is only called when the event classifier flags a meaningful event. Routine silence on the sensor front costs nothing.

---

### 4.3 Multi-Step Planner

**Purpose**: Users give high-level instructions that require multiple sequential or conditional steps. Currently, a single LLM call tries to handle everything in one shot, which breaks for complex tasks ("Set up a proximity detection system for the entrance area using three sensors, then run a 30-second recording").

**Design:**

The Planner introduces a two-phase process:

#### Phase 1 — Plan Generation
When the agent receives a complex command, it calls the LLM in **planner mode** (a separate system prompt that asks for a JSON plan instead of a direct response):

```json
{
  "goal": "Set up proximity detection for the entrance",
  "steps": [
    { "id": 1, "type": "set_sensor", "description": "Place DISTANCE-01 at entrance, facing inward", "params": {...} },
    { "id": 2, "type": "set_sensor", "description": "Place DISTANCE-02 at side, angled 45 degrees", "params": {...} },
    { "id": 3, "type": "wait_condition", "description": "Wait for DISTANCE-01 value < 1.5m", "condition": {...} },
    { "id": 4, "type": "agent_speak", "description": "Notify user when triggered", "message": "Proximity triggered at entrance." }
  ]
}
```

#### Phase 2 — Plan Execution
The `PlanExecutor` runs steps sequentially:
- `set_sensor`, `set_state`, `set_transform`, `highlight` → emit control commands immediately
- `wait_condition` → register a condition listener in the Heartbeat module
- `agent_speak` → send a push message to Unity TTS
- `run_script` → delegate to the Script Workspace

The active plan is stored in working memory. The user can interrupt ("stop the plan", "skip step 2"), and the agent updates its plan accordingly.

**Why this matters for VsensAgent**: Researchers often want to set up multi-sensor rigs with specific spatial relationships. This cannot be done in a single command without losing precision. A planner lets the user say "arrange sensors for gait detection" and the agent works through the geometry step by step, confirming each placement.

---

### 4.4 Script Workspace

**Purpose**: Not all sensor logic can be pre-defined. A researcher may want to generate a custom sinusoidal IMU data stream, run a statistical analysis on recorded sensor values, or define an automation rule that has no built-in action type. The Script Workspace lets the agent write Python code at runtime and execute it.

**Design:**

The workspace is a sandboxed Python execution environment. The agent emits a `run_script` action inside the `<control>` block, which the local `SkillRegistry` routes to the `ScriptWorkspace` module. No API configuration change is needed to enable this — it is just another registered skill.

1. **Write a script** — LLM emits a `run_script` action with inline code in the `<control>` block:
   ```python
   # Example: generated data pattern script
   import math, time
   def imu_sine_wave(t):
       return [math.sin(t), 0, math.cos(t)]  # simulated IMU x,y,z
   ```

2. **Execute it** in the workspace with restricted imports (whitelist: `math`, `numpy`, `json`, `time`, `random`)

3. **Return results** back into the agent's working memory or directly to Unity:
   ```python
   # Workspace output is injected back as context
   {"script_result": {"type": "sensor_pattern", "values": [...]}}
   ```

**Safety**:
- All scripts run in a `RestrictedPython` or `exec()` jail with an import whitelist
- Execution timeout (5s default)
- No file system access outside `data/workspace/output/`
- No network calls

**Use cases**:
- Generate custom sensor data streams (sine, noise, random walk)
- Compute sensor placement geometry (e.g., "triangle with 2m sides centered at x,y")
- Parse and analyze exported sensor log files
- Define multi-sensor fusion rules ("if IMU acceleration > 2g AND OPTICAL = 1, flag fall")

---

## 5. Revised File Structure

```
VsensPython/
│
├── core/
│   ├── agent_core.py              # Central orchestrator, replaces interactionManager
│   │
│   ├── memory/
│   │   ├── memory_manager.py      # Coordinates all memory tiers
│   │   ├── working_memory.py      # In-process short-term state
    │   ├── episodic_memory.py     # LanceDB vector store wrapper
│   │   └── semantic_memory.py     # Loads and queries knowledge files
│   │
│   ├── perception/
│   │   ├── heartbeat_handler.py   # Process scene_heartbeat messages
│   │   ├── scene_diff.py          # Diff engine: new vs. last snapshot
│   │   └── event_classifier.py    # Classify diffs into event types
│   │
│   ├── planning/
│   │   ├── planner.py             # LLM-based plan generation
│   │   ├── plan_executor.py       # Step-by-step execution loop
│   │   └── task_types.py          # Definitions/schemas for plan steps
│   │
│   └── workspace/
│       ├── script_workspace.py    # Runtime code generation + execution
│       └── sandbox.py             # Restricted exec environment
│
├── vsens_server.py                # WebSocket server (extended message types)
├── vsens_openai.py                # OpenAI layer (add tool-calling support)
│
├── monitor_stats.py               # (unchanged)
├── monitor_gui.py                 # (unchanged, extend for new modules)
│
└── data/
    ├── prompts/
    │   ├── core/                  # Core identity / behavior / output contract
    │   ├── features/              # Feature-specific prompt modules
    │   ├── examples/              # Few-shot examples for selected features
    │   ├── manifests/
    │   │   └── features.json      # Feature registry for prompt composition
    │   ├── planner_prompt.txt     # New: plan-generation system prompt
    │   ├── event_prompt.txt       # New: heartbeat event reasoning prompt
    │   └── system_prompt.txt      # Legacy reference snapshot; no longer primary entry
    ├── keys/
    │   └── openai_key_bak.txt
    ├── memory/
    │   ├── episodes/              # LanceDB persistent collection (Lance columnar files)
    │   └── knowledge/             # YAML sensor knowledge files
    └── workspace/
        ├── scripts/               # Saved generated scripts
        └── output/                # Script execution outputs
```

---

## 6. LLM Layer: Local Skill Registry

The current system uses plain `chat.completions.create()` and parses `<control>` blocks with regex. Rather than migrating to OpenAI's server-side function/tool-calling API (which couples skill definitions to online API schemas and requires schema maintenance in API calls), the new design uses a **local skill registry** — inspired by OpenCog's skill/action pattern.

**Key principle**: the LLM continues to emit structured text blocks. A local Python dispatcher owns all skill logic. No API schema changes are needed to add or modify a skill.

### 6.1 Skill Registry

Skills are registered locally as plain Python functions with a decorator:

```python
# core/skills/skill_registry.py
class SkillRegistry:
    _registry: dict[str, Callable] = {}

    @classmethod
    def register(cls, action_name: str):
        def decorator(fn):
            cls._registry[action_name] = fn
            return fn
        return decorator

    @classmethod
    def dispatch(cls, action: str, target: str, parameters: dict) -> dict:
        handler = cls._registry.get(action)
        if not handler:
            return {"status": "unknown_skill", "action": action}
        return handler(target, parameters)


# core/skills/scene_skills.py  (example registrations)
@SkillRegistry.register("set_state")
def skill_set_state(target, params):
    """Forwards state change to Unity via control output."""
    return {"target": target, "action": "set_state", "parameters": params}

@SkillRegistry.register("set_sensor")
def skill_set_sensor(target, params):
    """Validates and forwards sensor placement."""
    # local validation before sending to Unity
    assert params.get("sensor_type") in ("OPTICAL", "DISTANCE", "IMU")
    return {"target": target, "action": "set_sensor", "parameters": params}

@SkillRegistry.register("run_script")
def skill_run_script(target, params):
    """Delegate to the Script Workspace module."""
    from core.workspace.script_workspace import ScriptWorkspace
    return ScriptWorkspace.execute(params.get("code", ""))

@SkillRegistry.register("generate_plan")
def skill_generate_plan(target, params):
    """Hand off to the Planner module."""
    from core.planning.planner import Planner
    return Planner.create_plan(params.get("goal", ""))
```

### 6.2 Control Block Format (Improved)

The LLM output format stays almost identical to what the system prompt already defines — no prompt restructuring needed. The `<control>` block is valid, comment-free JSON. The only additions are new action types that map to new skill registrations:

```xml
<control>
{
  "actions": [
    { "target": "DISTANCE-01", "action": "set_sensor", "parameters": { "sensor_type": "DISTANCE", ... } },
    { "target": "_workspace", "action": "run_script",  "parameters": { "code": "...python string..." } },
    { "target": "_planner",   "action": "generate_plan", "parameters": { "goal": "..." } },
    { "target": "_memory",    "action": "memory_search", "parameters": { "query": "..." } }
  ]
}
</control>
```

### 6.3 Dispatch Flow

```
LLM reply text
    └─► ControlParser.extract()   — regex unchanged, extracts JSON from <control> block
            └─► for each action:
                    └─► SkillRegistry.dispatch(action, target, parameters)
                            └─► local Python handler
                                    ├─► returns Unity-bound control command  →  sent over WebSocket
                                    ├─► triggers Planner internally
                                    ├─► triggers ScriptWorkspace internally
                                    └─► triggers MemoryManager internally
```

**Benefits over OpenAI tool calling**:
- Skills are pure local Python — add a skill by writing a function, no API schema to update
- Works identically regardless of which LLM backend is used (swap GPT for a local model later)
- Validation and side-effects live in the skill handler, not in LLM API configuration
- No round-trip to OpenAI for skill execution — the LLM just decides *what* to call, Python does the rest
- The system prompt already describes available actions, so the LLM knows what to emit

---

## 7. New WebSocket Message Types

| Direction | Type | Description |
|---|---|---|
| Unity → Python | `scene_heartbeat` | Periodic scene state push |
| Unity → Python | `transcribe_and_reply` | (existing) Voice interaction |
| Unity → Python | `text_chat` | (existing) Text interaction |
| Unity → Python | `reset` | (existing) Reset conversation |
| Unity → Python | `plan_interrupt` | User cancels or modifies active plan |
| Unity → Python | `agent_interrupt` | **New**: hard interrupt of any in-progress agent activity |
| Python → Unity | `agent_ready` | (existing) Response to explicit request |
| Python → Unity | `agent_push` | **New**: proactive message from heartbeat |
| Python → Unity | `agent_status` | **New**: continuous agent state indicator |
| Python → Unity | `plan_update` | **New**: current plan step status |
| Python → Unity | `script_result` | **New**: result from workspace execution |

The server needs to support **server-initiated pushes** — sending messages to Unity without a corresponding request. The current design only responds to requests. A small broadcast utility on the server is needed.

### 7.1 Agent Status Indicator

This is a first-class design concern. Users in XR need to know what the agent is doing at all times so they can decide whether to wait or interrupt. The agent broadcasts its current state on every transition:

```python
# Python → Unity, pushed on every state change (no Unity request needed)
{
    "type": "agent_status",
    "state": "thinking",          # see state enum below
    "detail": "Generating plan for sensor placement",  # optional human-readable
    "plan_step": { "current": 2, "total": 5 }          # only when state == "executing"
}
```

**Agent State Enum:**

| State | Meaning |
|---|---|
| `idle` | Waiting for input, no active work |
| `listening` | Audio is being recorded (Unity-side, but agent acknowledges) |
| `transcribing` | Whisper STT in progress |
| `thinking` | LLM call in progress (single-turn) |
| `planning` | LLM generating a multi-step plan |
| `executing` | PlanExecutor is stepping through actions |
| `speaking` | TTS generation in progress |
| `waiting` | Blocked on a `wait_condition` from the Planner |
| `scripting` | ScriptWorkspace is running generated code |

Unity renders this as a persistent HUD indicator (e.g., a status ring around the agent avatar or a floating label). The idle state is visually distinct so the user always knows when it's safe to speak.

### 7.2 Interrupt Mechanism

The `agent_interrupt` message is a hard interrupt signal. On receipt:

1. Any active LLM API call is cancelled (via `asyncio.Task.cancel()`)
2. The active plan is discarded from working memory
3. Any pending `wait_condition` listeners are cleared
4. Agent transitions to `idle` and broadcasts `agent_status { state: "idle" }`
5. A brief acknowledgement is sent back: `{ "type": "interrupt_ack", "message": "Stopped." }`

```python
# Unity → Python: hard interrupt
{ "type": "agent_interrupt" }

# Python → Unity: acknowledgement
{ "type": "interrupt_ack", "message": "Stopped." }
```

`plan_interrupt` is a softer version — it halts only the current plan but leaves the agent in a ready conversational state, so the user can then redirect with a new command.

Both interrupt types need to be handled in `vsens_server.py` as top-priority messages that can preempt any in-flight async handler.

---

## 8. Phased Implementation Suggestion

Given the scope, it makes sense to implement incrementally so the system stays functional throughout:

### Phase 1 — Foundation Refactor
- Refactor `interactionManager` → `AgentCore` with cleaner module separation
- Implement local `SkillRegistry` + `ControlParser` replacing ad-hoc `_extract_control_from_reply`
- Add `WorkingMemory` class (replaces passing `scene_snapshot` around as a raw dict)
- Add `AgentStatusBroadcaster` and wire `agent_status` pushes into all async handlers

### Phase 2 — Memory
- Integrate LanceDB for episodic memory (cross-platform, zero-server)
- Implement `MemoryManager` with retrieval-augmented prompt building
- Add semantic memory YAML loader

### Phase 3 — Heartbeat + Perception
- Implement `scene_diff` and `event_classifier`
- Add Unity-side heartbeat sender (periodic WebSocket message)
- Implement `HeartbeatHandler` with attention gate
- Add `agent_push` message routing on server

### Phase 4 — Planner
- Implement `Planner` with LLM plan generation
- Implement `PlanExecutor` with step dispatch loop
- Integrate `wait_condition` with the heartbeat event system

### Phase 5 — Script Workspace
- Implement `ScriptWorkspace` with sandboxed exec
- Define safe import whitelist and timeout
- Add `run_script` tool call to LLM layer

---

## 9. Open Questions / Decisions Needed

1. **Vector DB choice** *(resolved)*: **LanceDB** is the recommended choice for this project. Rationale:
   - Pure Python (`pip install lancedb`) — no native compilation, no server process, no Docker
   - Fully cross-platform: Windows, macOS, Linux with identical behaviour
   - Embedded: data lives in `data/memory/episodes/` as a directory of Lance files (Apache Arrow columnar format)
   - Lightweight footprint (~40 MB installed, no Rust/C++ build step for the Python client)
   - Native ANN vector search with cosine/dot/L2 distance
   - Can store metadata alongside embeddings — useful for tagging episodes with session id, timestamp, sensor names
   - ChromaDB is a close alternative; it is also embedded + cross-platform but has a heavier install and opinionated internal schema. LanceDB is more flexible for custom metadata queries.
   - FAISS is ruled out: requires native compilation and has no built-in metadata storage.

2. **Heartbeat rate**: 1–2 seconds is suggested. Too fast wastes CPU on diff computation; too slow misses fast sensor events. Should this be configurable from Unity side?

3. **Attention gate threshold**: What qualifies as "significant enough to wake the LLM"? Initial suggestion: sensor value changes > 20%, state changes, user moving > 0.5m. This needs tuning.

4. **Script sandbox strictness**: Should the agent be allowed to import `numpy`? Useful for signal processing but larger attack surface. Recommendation: whitelist `numpy` explicitly since it's essential for sensor data manipulation.

5. **Plan complexity limit**: Should there be a max number of steps per plan? Recommend starting with 10 as a cap to avoid runaway plans.

6. **Unity-side heartbeat**: Does Unity currently send periodic messages, or does Python need to request snapshots? If Unity is passive, Python would need to send `request_snapshot` messages on a timer instead.

---

## 10. Token Optimization Strategy

Keeping LLM token usage under control is important both for cost and for latency. Every call carries four token buckets:

```
[1] System prompt          ~800–1200 tokens   fixed, OpenAI-cached after first call
[2] Scene context          ~500–2000 tokens   varies with scene size, sent every call
[3] Conversation history   grows unbounded    accumulates across turns
[4] User query             ~20–100 tokens     trivial
```

Bucket 2 and 3 are the targets. The strategies below are ordered by impact and listed with their implementation status in this plan.

---

### Strategy A — Scene Diff as Context *(High impact / implement in Phase 3)*

After the first full-snapshot call, working memory holds the complete scene state. Subsequent prompts only inject what changed since the last call:

```
Call 1 (full): 1800 tokens of scene JSON
Call 2 (diff): "Window_A: state open→closed. DISTANCE-01: value 0.08→1.42"  ~40 tokens
```

The agent already knows the full scene from the previous exchange. The `WorkingMemory` module owns the canonical state and generates a minimal delta string for each prompt. The full snapshot is still sent on the *first* call of a session and on `reset`.

This also applies to heartbeats: Unity sends only changed fields on each `scene_heartbeat`, not the full snapshot. That's a 10–50× size reduction for typical frames.

---

### Strategy B — LanceDB History Retrieval *(High impact for long sessions / implement in Phase 2)*

Without retrieval, conversation history grows linearly. A 100-turn session injects ~79 past exchanges into every call:

```
Without LanceDB (turn 80): ~8,000 extra tokens of history
With LanceDB    (turn 80): ~300 tokens — only 2–3 retrieved relevant exchanges
```

LanceDB stores each interaction as a vector-embedded episode. Before each LLM call, `MemoryManager` queries for the 2–3 episodes most semantically similar to the current user input and injects only those into the prompt instead of the full history. Retrieval use embeddings already computed for storage — no extra API calls.

---

### Strategy C — Relevance Filtering on Scene Objects *(Medium impact / implement alongside Phase 2)*

Not every interaction needs every object. Before injecting scene context, filter by relevance to the current user utterance:

```python
# User: "how far is the coffee maker from the door?"
# Include: CoffeeMaker, Door_A   (high cosine similarity to query)
# Exclude: Bowl, Lamp_3, unrelated sensors
```

Object descriptions are embedded once when they enter working memory (or on `reset`). Per-call filtering is a local cosine similarity computation — no extra API calls. Typical result: 60–80% reduction in scene context tokens for focused queries.

---

### Strategy D — Static Knowledge in System Prompt *(Low impact / implement in Phase 1)*

Static domain knowledge (sensor type descriptions, Unity coordinate conventions, valid action list) is currently re-sent in every user message. Moving it into the system prompt means it is cached by OpenAI on the first call and never billed again. This is a prompt restructuring only — no code change required.

---

### Strategy E — Schema Compression *(Deferred indefinitely)*

Compressing the scene JSON (shorter key names, dropping default-value fields) could reduce scene context tokens by ~30–50%. However, this requires coordinated changes to Unity's serialisation layer and risks breaking the two-system integration during active development. **This strategy is explicitly deferred** — the existing Unity scene snapshot format is kept as-is. Strategies A, C, and D achieve sufficient token reduction without touching the Unity side.

---

### Summary Table

| Strategy | Bucket | Token saving | Unity change needed | Status |
|---|---|---|---|---|
| A — Scene diff | 2 | High | Send diffs on heartbeat | Phase 3 |
| B — LanceDB history retrieval | 3 | High (long sessions) | None | Phase 2 |
| C — Relevance filtering | 2 | Medium–High | None | Phase 2 |
| D — Static knowledge → system prompt | 1 | Low | None | Phase 1 |
| E — Schema compression | 2 | Medium | Yes — **deferred** | ✗ |

---

## 11. Summary

The reconstructed backend transforms VsensAgent from a command dispatcher into a **cognitive, proactive collaborator**. The agent will:
- **Remember** past sensor configurations and user preferences (memory)
- **Notice** when sensor values change or users approach objects (heartbeat)
- **Plan** multi-step sensor setups without requiring step-by-step voice commands (planner)
- **Script** custom data patterns and analysis logic on demand (workspace)

This positions VsensAgent as a platform where a researcher can walk into an XR environment and have a genuine AI partner that understands the simulation context, recalls previous sessions, watches the scene autonomously, and handles complex multi-sensor workflows.

**Design principles guiding the reconstruction:**
- **Local-first**: skill dispatch, vector memory, and sandboxed execution all run on the local machine — the only online dependency is the OpenAI API call itself
- **Cross-platform**: all new dependencies (LanceDB, standard library `exec()` sandbox) are pure Python and install identically on Windows, macOS, and Linux
- **Observable**: the agent broadcasts its state on every transition so Unity can render live feedback and the user always has a clear interrupt path
- **Extensible**: adding a new skill is one decorated Python function; no API schemas, no prompt structural changes
