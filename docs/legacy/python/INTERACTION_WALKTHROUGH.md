# VsensAgent — Interaction Walkthrough

> Historical walkthrough. Useful for understanding the older reconstruction effort, but not the canonical source for the current architecture.

**Date**: March 1, 2026  
**Audience**: Developers working on this project  
**Purpose**: Describe in concrete detail how every mechanism works during a real
interaction — from the moment the user speaks in Unity to the moment the agent
acts in the scene — including memory retrieval, episode storage, workspace
scripting, and proactive heartbeat responses.

---

## Table of Contents

1. [Startup Sequence](#1-startup-sequence)
2. [How a Voice Command Is Processed](#2-how-a-voice-command-is-processed)
3. [How LanceDB Memory Works](#3-how-lancedb-memory-works)
4. [How Scene Context Is Filtered](#4-how-scene-context-is-filtered)
5. [How the Agent Uses Its Workspace](#5-how-the-agent-uses-its-workspace)
6. [How the Heartbeat Makes the Agent Proactive](#6-how-the-heartbeat-makes-the-agent-proactive)
7. [How the Planner Handles Complex Commands](#7-how-the-planner-handles-complex-commands)
8. [How Interrupts Work](#8-how-interrupts-work)
9. [Full Example: A Complete Research Session](#9-full-example-a-complete-research-session)
10. [Data Flow Diagram](#10-data-flow-diagram)

---

## 1. Startup Sequence

When the researcher starts the Python backend (`main.py` or `test_server_with_monitor.py`), the following happens in order before any Unity message is accepted:

### 1.1 VsensOpenAI initialises
- Reads the OpenAI API key from `data/keys/openai_key_bak.txt`
- Composes the system prompt from modular assets under `data/prompts/`
  (`core/`, `features/`, `examples/`, plus `manifests/features.json`)
- Constructs the OpenAI client — no API call is made yet

### 1.2 AgentStatusBroadcaster is created
- Holds the server's `broadcast()` coroutine as a callback
- Current state initialised to `idle`
- The broadcaster is the single source of truth for what the agent is doing

### 1.3 EpisodicMemory connects to LanceDB
```
data/memory/episodes/          ← directory of .lance columnar files
```
- `lancedb.connect("data/memory/episodes")` opens or creates the database directory
- If the `episodes` table exists (from a previous session), it is opened
- If not, a new empty table is created with the schema:
  ```
  session_id, timestamp, user_input, agent_reply,
  scene_summary, control_actions, embedding (1536-dim float32 vector)
  ```
- **No API call is made** — this is a pure local file operation
- The table persists on disk between server restarts; episodes accumulate across sessions

### 1.4 SemanticMemory loads YAML knowledge files
- All `.yaml` files under `data/memory/knowledge/` are loaded into memory as dicts
- Example files: `sensors.yaml` (sensor type descriptions), `scene_conventions.yaml`
- This is read-only static knowledge, used for prompt context enrichment

### 1.5 AgentCore is assembled
- `WorkingMemory` is created with a fresh `session_id` (UUID)
- `SceneFilter` is created (empty embedding cache at this point)
- `MemoryManager` is assembled from the four memory components
- `SkillRegistry` is populated by importing `core/skills/scene_skills.py`,
  which decorates four functions: `set_state`, `set_transform`, `highlight`, `set_sensor`

### 1.6 WebSocket server starts
- Listens on `ws://localhost:8765`
- Ready to accept connections from Unity

The entire startup takes a few hundred milliseconds — dominated by the YAML file reads and the LanceDB connection. No OpenAI API calls happen until the first user interaction.

---

## 2. How a Voice Command Is Processed

### Scenario
The researcher puts on the XR headset, holds the voice button, and says:
> "Move the coffee maker 30 centimetres closer to the window."

Unity records audio to a `.wav` file, then sends:
```json
{
  "type": "transcribe_and_reply",
  "audio_path": "AudioRecordings/Input/input_20260301_143022.wav",
  "scene_snapshot": {
    "CoffeeMaker": { "position": [2.5, 0.9, 4.0], "properties": ["movable"], ... },
    "Window_A": { "position": [3.4, 1.9, 7.5], "state": "closed", ... },
    "OPTICAL-01": { "position": [2.6, 1.4, 4.2], "properties": ["sensor", "movable"],
                    "sensor": { "sensorType": "OPTICAL", "value": 0 } },
    ...
  }
}
```

### Step-by-step processing

**Step 1 — Server receives message**  
`VsensWebSocketServer.process_message()` parses the JSON, looks up
`"transcribe_and_reply"` in its handler table, and wraps the call in
`asyncio.ensure_future()`, storing it as `self._active_task` so it can be
cancelled by an interrupt.

**Step 2 — State: `transcribing`**  
`AgentStatusBroadcaster.set_state("transcribing")` is called.
The server immediately broadcasts to all connected Unity clients:
```json
{ "type": "agent_status", "state": "transcribing", "detail": "" }
```
Unity renders a "listening" ring around the agent avatar. The researcher
sees the agent is processing their speech.

**Step 3 — Whisper STT**  
`VsensOpenAI.transcribe_audio(audio_path)` sends the `.wav` file to OpenAI
Whisper. Returns:
```
"Move the coffee maker 30 centimetres closer to the window."
```

**Step 4 — Working memory update**  
`WorkingMemory.update_scene(scene_snapshot)` is called:
- The previous `scene` dict is copied into `last_scene`
- The new snapshot is merged into `scene`
- This diff pair is now available for Phase 3 scene-diff context

**Step 5 — State: `thinking`**  
`agent_status { state: "thinking" }` is broadcast. Unity changes the
avatar indicator to a "thinking" pulse animation.

**Step 6 — Prompt is built**  
`AgentCore._build_prompt(user_text)` runs:

  a. **Scene filter**: `SceneFilter.filter(working_memory.scene, user_text, top_k=15)`  
     Computes cosine similarity between the user query embedding and each stored
     object description embedding. Returns the 15 most relevant objects.
     For this query, `CoffeeMaker` and `Window_A` score highest — unrelated
     objects like `Lamp_3` or `Bookshelf_2` are excluded.

  b. **Memory context**: `MemoryManager.build_context(user_text)` queries LanceDB
     for the 3 most semantically similar past episodes. If this is the first
     interaction of the first session, the store is empty and nothing is injected.

  c. **Final prompt assembled**:
     ```
     The user just said:
     "Move the coffee maker 30 centimetres closer to the window."

     Current scene (relevant objects):
     {
       "CoffeeMaker": { "position": [2.5, 0.9, 4.0], "properties": ["movable"], ... },
       "Window_A":    { "position": [3.4, 1.9, 7.5], ... },
       ...
     }
     ```

**Step 7 — GPT-4.1 call**  
`VsensOpenAI.send_message(prompt)` appends the prompt to `self.messages`
(which starts with the system prompt) and calls `chat.completions.create()`.

The model responds:
```
Moving the coffee maker 0.3 metres toward the window.

<control>
{
  "actions": [
    {
      "target": "CoffeeMaker",
      "action": "set_transform",
      "parameters": {
        "position": [2.5, 0.9, 4.3]
      }
    }
  ]
}
</control>
```

**Step 8 — ControlParser extracts the reply**  
`ControlParser.extract(reply_text)` returns:
- `spoken_text`: `"Moving the coffee maker 0.3 metres toward the window."`
- `actions`: `[{ "target": "CoffeeMaker", "action": "set_transform", "parameters": {...} }]`

**Step 9 — SkillRegistry dispatches**  
`SkillRegistry.dispatch("set_transform", "CoffeeMaker", {"position": [2.5, 0.9, 4.3]})`
calls `skill_set_transform()` which validates that at least one of
`position/rotation/scale` is present and returns the action dict unchanged.

**Step 10 — State: `speaking`**  
`AgentStatusBroadcaster.set_state("speaking")` broadcasts. Unity shows a
"speaking" wave animation on the avatar.

**Step 11 — TTS audio generated**  
`VsensOpenAI.speak_text(spoken_text)` sends the text to OpenAI TTS (`tts-1`,
voice `nova`). The MP3 is saved to:
```
VsensAgent/AudioRecordings/Response/reply_audio_20260301_143025.mp3
```
The absolute path is returned to Unity.

**Step 12 — Episode stored in LanceDB**  
`MemoryManager.store_interaction(...)` is called:
- Concatenates `user_text + " " + spoken_text` into a single string
- Calls `embeddings.create(model="text-embedding-3-small", input=combined_text)`
- Gets back a 1536-dimensional float32 vector
- Writes one row to the `episodes` LanceDB table with all fields including the embedding
- The `.lance` files on disk are updated immediately in the background thread

**Step 13 — State: `idle`; response sent to Unity**  
The server sends back:
```json
{
  "type": "agent_ready",
  "status": "success",
  "transcription": "Move the coffee maker 30 centimetres closer to the window.",
  "reply": "Moving the coffee maker 0.3 metres toward the window.",
  "audio_path": "G:\\LCLab\\VsensAgent\\VsensAgent\\AudioRecordings\\Response\\reply_audio_20260301_143025.mp3",
  "control": {
    "actions": [
      { "target": "CoffeeMaker", "action": "set_transform", "parameters": { "position": [2.5, 0.9, 4.3] } }
    ]
  }
}
```

Unity receives this, plays the MP3 through the XR headset speakers, and
tells the `CoffeeMaker` transform to lerp to the new position.

**Total wall-clock time**: ~1.5–3 seconds (dominated by Whisper + GPT-4.1 API calls)

---

## 3. How LanceDB Memory Works

### 3.1 Physical Storage

LanceDB stores data as a directory of Apache Arrow columnar `.lance` files:
```
data/memory/episodes/
  _latest_transaction.manifest
  episodes.lance/
    data-0000.lance      ← row batches (Arrow columnar)
    data-0001.lance
    ...
    _indices/            ← ANNS vector index (built on first search)
```
This is a local directory — no server process, no Docker, no daemon. Accessed
directly by the Python process via memory-mapped file I/O.

### 3.2 How Episodes Are Embedded

Each interaction produces one row. The text embedded is:
```
"{user_input} {agent_reply}"
```
For example: `"Move the coffee maker closer Moving the coffee maker 0.3 metres toward the window."`

This concatenated string captures both the intent (user) and the resolution
(agent) so retrieval finds episodes that are similar in *both* what was asked
*and* what was done.

Embedding model: `text-embedding-3-small` (1536 dimensions, ~$0.00002 per call)

### 3.3 How Episodes Are Retrieved

When the next user query arrives, `EpisodicMemory.retrieve(query, n=3)`:
1. Embeds the query string with the same model
2. Calls `table.search(embedding).limit(3).to_list()` — LanceDB performs
   approximate nearest-neighbour search (ANN) using the stored index
3. Returns the 3 rows with highest cosine similarity to the query

These are injected into the prompt as:
```
[Relevant past interactions]
- User said: "Move the coffee maker closer" → Agent replied: "Moving the coffee maker 0.3 metres toward the window."
- User said: "Place an optical sensor on the coffee maker" → Agent replied: "Placing OPTICAL-02 on the CoffeeMaker..."
```

### 3.4 Example: Session Continuity

**Session 1 (yesterday)**:
- User placed OPTICAL-01 on CoffeeMaker at position [2.5, 1.0, 4.0]
- User asked "what sensor type detects presence?" → agent explained OPTICAL
- Both episodes stored in LanceDB

**Session 2 (today)** — server restarts, conversation history is cleared, but LanceDB persists:
- User says: "set up a sensor on the coffee maker again"
- LanceDB retrieve() finds the previous placement episode (high similarity to
  "set up a sensor on the coffee maker")
- Agent has context: "Last time you placed OPTICAL-01 at position [2.5, 1.0, 4.0]
  attached to CoffeeMaker" — without the user needing to repeat themselves
- Agent can suggest: "Same configuration as last time, or do you want a different sensor type?"

### 3.5 Session vs. Cross-Session Behaviour

| State | Cleared on reset? | Persists across restarts? |
|---|---|---|
| OpenAI message list (conversation) | Yes | No |
| WorkingMemory scene | Yes | No |
| LanceDB episodic store | No | Yes ✓ |
| Semantic memory YAML | N/A (read-only) | Yes ✓ |

---

## 4. How Scene Context Is Filtered

### The Problem
A real scene can have 50+ objects. Sending the full JSON snapshot on every
call wastes ~800–1500 tokens on objects irrelevant to the current query.

### The Solution: SceneFilter

`SceneFilter` maintains an embedding cache of all objects in working memory.
Each object is represented as a short description string:
```
"CoffeeMaker: properties=['movable'], position=[2.5,0.9,4.0]"
"OPTICAL-01: type=OPTICAL, value=0, parent=CoffeeMaker"
"Window_A: state=closed, position=[3.4,1.9,7.5]"
```

These descriptions are embedded **once** when the scene is first loaded
(or when a new object appears). The embeddings are cached in memory and
reused across all subsequent calls.

### Per-Call Filtering

For query `"Move the coffee maker closer to the window"`:
1. Embed the query (one API call, ~0.00002 USD)
2. Compute cosine similarity between query embedding and each object embedding
   (local dot products — no API call, near-instant)
3. Return the top-15 objects by similarity score

Result: The prompt contains `CoffeeMaker` and `Window_A` prominently, and
irrelevant objects like `Lamp_3`, `Bookshelf_2`, `Rug_1` are excluded.

Additionally, any object whose name appears literally in the user query string
is always included regardless of similarity score (exact name matching as a
safety net).

### Savings
A scene with 40 objects at ~30 tokens each = ~1200 scene tokens unfiltered.
After filtering to 15 objects = ~450 tokens. **~62% reduction** for focused queries.

---

## 5. How the Agent Uses Its Workspace

The Script Workspace lets the agent write and run Python at runtime. It is
activated when the LLM emits a `run_script` action in its `<control>` block.

### 5.1 Example: Custom Sensor Data Pattern

**User says**: "Generate a 10-second sine wave pattern for the IMU x-axis"

**LLM responds**:
```
Generating a 10-second 1 Hz sine wave pattern for IMU x-axis.

<control>
{
  "actions": [
    {
      "target": "_workspace",
      "action": "run_script",
      "parameters": {
        "code": "import math\nvalues = [round(math.sin(2*math.pi*t/10), 4) for t in range(100)]\nprint(values)"
      }
    }
  ]
}
</control>
```

**What happens**:
1. `SkillRegistry.dispatch("run_script", ...)` routes to `skill_run_script()`
2. `ScriptWorkspace.execute(code)` is called:
   - Parses the AST — confirms only `math` is imported (whitelisted)
   - Runs `exec()` in a restricted namespace with only safe builtins
   - Captures stdout via a `StringIO` buffer
   - Returns `{ "status": "ok", "output": "[0.0, 0.6235, ..., -0.6235]" }`
3. Script is saved to `data/workspace/scripts/script_20260301_143100.py`
4. Output is saved to `data/workspace/output/output_20260301_143100.txt`
5. A `script_result` message is broadcast to Unity:
   ```json
   { "type": "script_result", "status": "ok", "output": "[0.0, 0.6235, ...]" }
   ```
6. The output summary is added to `WorkingMemory.recent_events` so future
   prompts know a script was just run and what it produced

### 5.2 Security: The Sandbox

The sandbox rejects scripts before execution if they:
- Import any module not in the whitelist:
  `{math, json, time, random, numpy, itertools, functools, collections, statistics}`
- Would raise a syntax error (caught by `ast.parse()` before `exec()`)

The execution namespace strips dangerous builtins — `open`, `__import__`, `eval`,
`exec`, `compile` are not available to the script. The script cannot:
- Access the filesystem (no `open()`)
- Make network calls (no `requests`, `http`, `socket`)
- Import OS-level modules (`os`, `sys`, `subprocess`)

If a script runs longer than 5 seconds (configurable), the background thread
is abandoned and `{ "status": "timeout" }` is returned.

### 5.3 Example: Geometry Calculation

**User says**: "Place three distance sensors in a triangle with 2-metre sides, centred at the entrance at [1.0, 1.0, 2.0]"

The agent could calculate the positions natively, but for more complex geometry
it can delegate to the workspace:

```python
import math
cx, cy, cz = 1.0, 1.0, 2.0
r = 2.0 / math.sqrt(3)   # circumradius of equilateral triangle with side 2m
angles = [90, 210, 330]   # degrees
positions = [
    [round(cx + r*math.cos(math.radians(a)), 3),
     cy,
     round(cz + r*math.sin(math.radians(a)), 3)]
    for a in angles
]
print(positions)
```

Output: `[[1.0, 1.0, 3.155], [-0.155, 1.0, 1.422], [2.155, 1.0, 1.422]]`

The agent then uses these coordinates in the `set_sensor` actions that follow.

---

## 6. How the Heartbeat Makes the Agent Proactive

The heartbeat channel allows the agent to observe the scene continuously and
react to events without the user saying anything.

### 6.1 Unity's Side

Unity sends a `scene_heartbeat` message every 1–2 seconds (configurable):
```json
{
  "type": "scene_heartbeat",
  "scene_snapshot": { ... current full scene state ... }
}
```
This is sent regardless of whether the user is doing anything — it is a
passive data push, not a request.

### 6.2 Python's Side: The Diff Pipeline

The `HeartbeatHandler` processes each heartbeat in three lightweight stages
before deciding whether to wake the LLM:

**Stage 1 — SceneDiff**  
Compares the incoming snapshot against `WorkingMemory.last_scene`:
```
Changes detected:
- OPTICAL-01: sensor.value changed 0 → 1
- user_head: position moved 0.82m (from [2.0,1.7,3.0] to [2.8,1.7,3.0])
```

**Stage 2 — EventClassifier**  
Maps each diff to a named event type with a severity score:
```
SENSOR_TRIGGER on OPTICAL-01  severity=0.8  (binary sensor fired)
USER_PROXIMITY                severity=0.4  (user moved, but < threshold)
```

**Stage 3 — Attention Gate**  
The LLM is only woken if at least one event has `severity >= 0.5`.
Here `SENSOR_TRIGGER` at `0.8` passes. User proximity at `0.4` does not
(it is added to `recent_events` for context but does not wake the LLM).

### 6.3 Proactive LLM Call

The attention gate fires. The agent transitions to `thinking` state and calls GPT-4.1
with an event-focused prompt:
```
[Scene event detected]
OPTICAL-01: value 0→1 (trigger)

Current scene:
{ ... }

Briefly comment or take action if appropriate.
```

The LLM responds:
```
Optical sensor one just triggered. Something entered the detection zone at the coffee maker.

<control>
{
  "actions": [
    { "target": "OPTICAL-01", "action": "highlight", "parameters": { "color": "#FF6600" } }
  ]
}
</control>
```

### 6.4 Agent Push to Unity

The server broadcasts to all connected clients **without any Unity request**:
```json
{
  "type": "agent_push",
  "trigger": "SENSOR_TRIGGER",
  "message": "Optical sensor one just triggered. Something entered the detection zone at the coffee maker.",
  "control": {
    "actions": [
      { "target": "OPTICAL-01", "action": "highlight", "parameters": { "color": "#FF6600" } }
    ]
  }
}
```

Unity plays the TTS message, highlights OPTICAL-01 in orange, and the researcher
— who was busy placing another sensor — is informed of the event without having
to ask.

### 6.5 Cost Control

Of 100 heartbeats per minute, typically 95–99 result in `no_op` (no diff above
threshold) and cost nothing (no LLM call). Only meaningful events trigger the
OpenAI API. The classification and diff steps are pure local Python computation.

---

## 7. How the Planner Handles Complex Commands

### Scenario

**User says**: "Set up a gait detection system using two distance sensors on either side of the walkway between the door and the sofa."

A single LLM call cannot reliably produce two precisely-placed sensor commands
and also explain the setup — it tends to hallucinate positions or skip steps.
The Planner decomposes this into explicit steps.

### 7.1 Plan Generation

The agent detects a multi-step intent and emits a `generate_plan` action:
```json
{ "action": "generate_plan", "parameters": { "goal": "Gait detection setup: two DISTANCE sensors flanking the Door_A–Sofa_1 walkway" } }
```

`SkillRegistry.dispatch("generate_plan", ...)` hands off to `Planner.generate_plan()`,
which makes a **separate LLM call** using `planner_prompt.txt` as the system role.
This call asks for a JSON plan only — it does not affect the main conversation history.

The planner returns:
```json
{
  "goal": "Gait detection: two DISTANCE sensors flanking Door_A–Sofa_1",
  "steps": [
    { "id": 1, "type": "set_sensor", "description": "Place DISTANCE-02 on left side of walkway",
      "params": { "sensor_type": "DISTANCE", "position": [1.2, 0.9, 3.5], "rotation": [0, 90, 0],
                  "validDistance": 2.0, "lookDirection": [1, 0, 0] } },
    { "id": 2, "type": "set_sensor", "description": "Place DISTANCE-03 on right side of walkway",
      "params": { "sensor_type": "DISTANCE", "position": [3.8, 0.9, 3.5], "rotation": [0, -90, 0],
                  "validDistance": 2.0, "lookDirection": [-1, 0, 0] } },
    { "id": 3, "type": "agent_speak", "description": "Confirm setup to user",
      "params": { "message": "Gait detection sensors placed. Both sensors face inward across the walkway." } },
    { "id": 4, "type": "wait_condition", "description": "Wait for first gait crossing",
      "params": { "object": "DISTANCE-02", "field": "sensor.value", "operator": "<", "threshold": 1.0, "timeout_s": 60 } },
    { "id": 5, "type": "agent_speak", "description": "Alert on first detected crossing",
      "params": { "message": "Gait crossing detected on the left sensor." } }
  ]
}
```

### 7.2 Plan Execution

`PlanExecutor.execute(plan)` runs asynchronously in the background. For each step:

- **Steps 1–2** (`set_sensor`): `SkillRegistry.dispatch("set_sensor", ...)` validates
  and returns the action dict. Server broadcasts a `plan_update` and an `agent_ready`
  with the sensor placement control command to Unity. Unity places both sensors.

- **Step 3** (`agent_speak`): Server broadcasts `agent_push` with the confirmation
  message. Unity plays it as TTS.

- **Step 4** (`wait_condition`): The executor enters a 500ms polling loop.
  It reads `working_memory.scene["DISTANCE-02"]["sensor"]["value"]` every 500ms.
  When a heartbeat delivers a new snapshot showing `value < 1.0`, the condition
  resolves. If 60 seconds pass without the condition being met, the step times
  out with `{ "status": "timeout" }` and execution continues.

- **Step 5** (`agent_speak`): Broadcasts the crossing alert.

Throughout execution, Unity receives:
```json
{ "type": "agent_status", "state": "executing", "detail": "Place DISTANCE-02 on left side of walkway", "plan_step": { "current": 1, "total": 5 } }
```
This drives a step progress indicator in the XR HUD.

---

## 8. How Interrupts Work

### Hard Interrupt (`agent_interrupt`)

The user presses a dedicated "stop" button in the XR controller menu. Unity sends:
```json
{ "type": "agent_interrupt" }
```

In `VsensWebSocketServer.process_message()`, interrupt messages are handled
**before** the normal dispatch table — they bypass task wrapping entirely.

`_handle_agent_interrupt()`:
1. Calls `self._active_task.cancel()` — this injects `asyncio.CancelledError`
   into the currently awaited coroutine (e.g., an in-flight OpenAI API call)
2. Clears `working_memory.active_plan`
3. Calls `broadcaster.reset()` which forces `agent_status { state: "idle" }` broadcast
4. Returns `{ "type": "interrupt_ack", "message": "Stopped." }` immediately

The researcher hears nothing, the avatar snaps back to idle, and the scene
is unmodified from the last confirmed state.

### Soft Interrupt (`plan_interrupt`)

The user says "stop the plan" during a multi-step execution. Unity sends:
```json
{ "type": "plan_interrupt" }
```

`_handle_plan_interrupt()`:
1. Calls `working_memory.clear_plan()` — sets `active_plan` to `None`
2. Does **not** cancel the current `_active_task` (if a single LLM call is
   running for the current step, it completes normally)
3. The `PlanExecutor` loop checks `active_plan` before each step — when it
   finds `None`, it exits gracefully
4. Agent returns to `idle` state

The difference: after a soft interrupt the agent is still in a fully
conversational state and will respond normally to the next voice command.
After a hard interrupt, the agent cleanly aborts even if the network call
is mid-flight.

---

## 9. Full Example: A Complete Research Session

This traces a realistic 15-minute session with all mechanisms active.

---

**T+0:00 — Server starts**  
LanceDB connects. 47 episodes from yesterday's session exist in the table.
SemanticMemory loads `sensors.yaml` and `scene_conventions.yaml`.

---

**T+0:30 — Unity connects**  
WebSocket client connects. `agent_status { state: "idle" }` broadcast.
The XR avatar shows its idle ring in the scene.

---

**T+1:00 — Heartbeat begins**  
Unity starts sending `scene_heartbeat` every 1.5 seconds. The scene has
18 objects. WorkingMemory is populated. SceneFilter embeds all 18 object
descriptions (18 × 1 embedding API call, ~$0.00036). After the first
heartbeat, all subsequent ones are diff-only — most return `no_op`.

---

**T+1:30 — First voice command**  
*"Where did we put the distance sensor last time?"*

`EpisodicMemory.retrieve("where did we put the distance sensor")` scores
a past episode: `"place DISTANCE-01 on the shelf facing the door"` with
cosine similarity 0.87 (high). This is injected into the prompt:
```
[Relevant past interactions]
- User said: "put a distance sensor facing the door" → Agent replied: "Placing DISTANCE-01 on Shelf_1 at position [1.8, 1.2, 2.5], facing toward Door_A."
```

GPT-4.1 answers:
> "Last session you placed DISTANCE-01 on the shelf at position 1.8, 1.2, 2.5, facing Door-A."

The researcher did not need to remember this — the agent retrieved it from
LanceDB automatically.

---

**T+3:00 — Complex command**  
*"Set up proximity detection at the entrance with two sensors"*

The LLM generates a `generate_plan` action. Planner creates a 4-step plan.
PlanExecutor places two sensors sequentially, confirms to the user, then
enters `wait_condition` watching `DISTANCE-01.value < 0.8`.

`agent_status { state: "executing", plan_step: {current: 3, total: 4} }` broadcast.

---

**T+4:20 — Researcher walks through the virtual entrance**  
Heartbeat delivers: `DISTANCE-01.value: 2.3 → 0.61`.
`wait_condition` polling resolves immediately (next 500ms poll).
PlanExecutor proceeds to step 4: broadcasts "Proximity triggered at the entrance."

---

**T+5:00 — Scripting request**  
*"Generate a noisy sine wave for the IMU to simulate walking"*

LLM emits `run_script` with numpy code. Sandbox validates (numpy is
whitelisted), runs `exec()`, captures 100 float values in stdout.
`script_result` broadcast to Unity. Script saved to `data/workspace/scripts/`.

---

**T+8:00 — Proactive alert (no user input)**  
While the researcher is reading documentation in the headset, a heartbeat
delivers `OPTICAL-01.value: 0 → 1`.

EventClassifier: `SENSOR_TRIGGER` severity 0.8. Attention gate fires.
Agent calls GPT-4.1 with event prompt. Agent pushes:
> "Optical sensor one at the coffee maker just triggered."
`highlight` action on OPTICAL-01 in orange.

The researcher glances up and sees the highlighted sensor. They didn't have
to ask or look at any data panel.

---

**T+12:00 — Interrupt during a slow API call**  
The researcher accidentally triggers a complex multi-sensor plan and
immediately presses the stop button.

`agent_interrupt` arrives. The currently awaited `await openai_call()` is
cancelled via `asyncio.CancelledError`. Agent returns to `idle` in <100ms.
No partial control commands are sent to Unity. Scene is unaffected.

---

**T+15:00 — Session ends**  
Researcher disconnects. All 14 interactions from this session are stored
as embedded episodes in LanceDB. Tomorrow, they will be retrieved as relevant
context in future queries without any manual notes.

---

## 10. Data Flow Diagram

```
Unity (XR Client)
│
│  ── WebSocket (ws://localhost:8765) ──────────────────────────────────────
│
│  ► transcribe_and_reply / text_chat
│  ► scene_heartbeat (every 1–2s, independent channel)
│  ► agent_interrupt / plan_interrupt
│
│  ◄ agent_status     (pushed on every state change)
│  ◄ agent_ready      (response to explicit requests)
│  ◄ agent_push       (proactive, heartbeat-triggered)
│  ◄ plan_update      (step progress during plan execution)
│  ◄ script_result    (workspace output)
│  ◄ interrupt_ack
│
▼

VsensWebSocketServer
  │  routes messages to handlers
  │  wraps handlers in asyncio.Task (for interrupt cancellation)
  │  broadcasts agent_status + agent_push to all clients
  ▼

AgentCore (central orchestrator)
  │
  ├── WorkingMemory
  │     scene (current)
  │     last_scene (previous heartbeat, for diff)
  │     active_plan
  │     recent_events
  │     session_id
  │
  ├── MemoryManager
  │     │
  │     ├── EpisodicMemory (LanceDB)
  │     │     data/memory/episodes/*.lance
  │     │     store()   ← after every interaction
  │     │     retrieve() → injected into prompt
  │     │
  │     ├── SemanticMemory (YAML)
  │     │     data/memory/knowledge/sensors.yaml
  │     │     data/memory/knowledge/scene_conventions.yaml
  │     │
  │     └── SceneFilter
  │           embedding cache (object descriptions)
  │           filter(scene, query) → top-15 relevant objects
  │
  ├── VsensOpenAI
  │     send_message() → GPT-4.1 chat API
  │     transcribe_audio() → Whisper
  │     speak_text() → TTS mp3 → VsensAgent/AudioRecordings/Response/
  │
  ├── ControlParser
  │     extract(reply_text) → (spoken_text, [action dicts])
  │
  ├── SkillRegistry
  │     set_state, set_transform, highlight, set_sensor
  │     generate_plan → Planner
  │     run_script → ScriptWorkspace
  │     memory_search → MemoryManager
  │
  ├── HeartbeatHandler (Phase 3)
  │     SceneDiff → EventClassifier → Attention Gate → LLM (if needed)
  │
  ├── Planner (Phase 4)
  │     generate_plan(goal, scene) → Plan JSON (separate LLM call)
  │
  ├── PlanExecutor (Phase 4)
  │     execute(plan) → dispatches steps sequentially
  │     wait_condition → polls WorkingMemory every 500ms
  │
  └── ScriptWorkspace (Phase 5)
        Sandbox (AST validation, exec(), timeout, restricted builtins)
        Saves to data/workspace/scripts/ and data/workspace/output/
```
