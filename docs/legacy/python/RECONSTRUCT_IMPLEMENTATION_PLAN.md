# VsensPython Backend — Implementation Plan

> Historical implementation plan. Many tasks in this file were written for an older runtime state.
>
> Current references:
> - [<repository>/docs/plans/README.md](../../plans/README.md)
> - [<repository>/docs/architecture/REFACTOR_CHECKLIST.md](../../architecture/REFACTOR_CHECKLIST.md)

> Historical implementation plan: prompt-related tasks in this file were written
> for the older single-file `system_prompt.txt` workflow.
>
> Treat those prompt references as design history. For the current prompt system, use:
> - [PROMPT_ARCHITECTURE.md](../../../VsensPython/docs/PROMPT_ARCHITECTURE.md)
> - [PATH_SETUP.md](../../../VsensPython/docs/PATH_SETUP.md)
> - [docs/README.md](../../README.md)

**Based on**: `RECONSTRUCT_PLAN.md`  
**Date**: February 28, 2026  
**Status**: Ready to implement

---

## How to Read This Document

Each task block follows this format:

```
[TASK ID] Task Title
  Depends on : other task IDs that must be done first
  Files      : files to create (✦) or modify (✎)
  Goal       : what this task achieves at a functional level
  Notes      : key implementation details
  Verify     : how to confirm the task is complete and correct
```

Tasks within a phase are ordered so that each one can merge cleanly into a working codebase. The system stays runnable after every phase completes.

---

## Dependency Graph (Summary)

```
Phase 1 (Foundation)
  P1-T1 → P1-T2 → P1-T3 → P1-T4
                         → P1-T5 → P1-T6 → P1-T7
                                          → P1-T8
Phase 2 (Memory)
  P2-T1 → P2-T2
        → P2-T3
  P2-T2 + P2-T3 → P2-T4 → P2-T5 → P2-T6

Phase 3 (Heartbeat)
  P3-T1 → P3-T2 → P3-T3 → P3-T4 → P3-T5
                                  → P3-T6

Phase 4 (Planner)
  P4-T1 → P4-T2 → P4-T3 → P4-T4 → P4-T5
                         → P4-T6

Phase 5 (Workspace)
  P5-T1 → P5-T2 → P5-T3
```

---

---

# Phase 1 — Foundation Refactor

**Goal**: Replace the current flat `interactionManager` pipeline with a modular `AgentCore`. Introduce `WorkingMemory`, a local `SkillRegistry`, and an `AgentStatusBroadcaster`. The system must be fully functional (same behaviour as today) when this phase is done.

---

### P1-T1 — Create `core/` Package Skeleton

```
Depends on : nothing
Files      : ✦ core/__init__.py
             ✦ core/memory/__init__.py
             ✦ core/perception/__init__.py
             ✦ core/planning/__init__.py
             ✦ core/workspace/__init__.py
             ✦ core/skills/__init__.py
Goal       : Establish the directory structure so all future imports resolve.
Notes      : All __init__.py files can be empty at this stage.
             Mirrors the structure in RECONSTRUCT_PLAN.md Section 5.
Verify     : `from core.skills import skill_registry` imports without error
             from within VsensPython/.
```

---

### P1-T2 — Implement `WorkingMemory`

```
Depends on : P1-T1
Files      : ✦ core/memory/working_memory.py
Goal       : A single in-process object that holds the canonical scene state,
             active plan reference, and a short recent-events list.
             Replaces the raw scene_snapshot dict being passed around per call.
Notes      :
  class WorkingMemory:
      scene: dict          # full latest scene snapshot, keyed by object name
      last_scene: dict     # snapshot from previous heartbeat/call (for diff)
      active_plan: dict | None
      recent_events: list[dict]   # last N classified events, for prompt context
      session_id: str             # UUID, generated at startup

  Methods:
      update_scene(new_snapshot: dict)
          - copies current scene → last_scene
          - merges new_snapshot into scene
      add_event(event: dict)
          - appends to recent_events, trims to last 10
      clear_plan()
      set_plan(plan: dict)

  Instantiated once in AgentCore and passed by reference to all submodules.

Verify     : Unit test: create WorkingMemory, call update_scene twice,
             confirm last_scene holds first snapshot and scene holds second.
```

---

### P1-T3 — Implement `ControlParser` and `SkillRegistry`

```
Depends on : P1-T1
Files      : ✦ core/skills/control_parser.py
             ✦ core/skills/skill_registry.py
Goal       : Replace the ad-hoc _extract_control_from_reply /
             _strip_control_block methods with a clean parser + dispatcher.
Notes      :
  ControlParser:
      extract(reply_text: str) -> (spoken_text: str, actions: list[dict])
          - Finds <control>...</control> in reply_text
          - Returns (text with control block stripped, parsed action list)
          - On malformed JSON, returns (original_text, []) and logs warning
          - action list item shape: {"target": str, "action": str, "parameters": dict}

  SkillRegistry:
      _registry: dict[str, Callable]  # class-level
      register(action_name: str) -> decorator
      dispatch(action: str, target: str, parameters: dict) -> dict
          - Returns {"status": "unknown_skill"} for unregistered actions
          - Catches and logs exceptions inside skill handlers, returns error dict

  Both classes have no external dependencies — pure Python stdlib only.

Verify     : Unit test ControlParser with a string containing a valid <control>
             block, an empty <control></control>, and a malformed JSON block.
             Confirm extract() returns expected tuples in all three cases.
```

---

### P1-T4 — Register Scene Skills

```
Depends on : P1-T3
Files      : ✦ core/skills/scene_skills.py
Goal       : Register the four existing Unity control actions (set_state,
             set_transform, highlight, set_sensor) as skills so the
             SkillRegistry can dispatch them.
Notes      :
  Each skill function does light local validation then returns the action
  dict unchanged (Unity will execute it). This is intentionally thin —
  skills are validation + routing, not execution.

  @SkillRegistry.register("set_state")
  def skill_set_state(target, params):
      assert "state" in params, "set_state requires 'state' parameter"
      return {"target": target, "action": "set_state", "parameters": params}

  @SkillRegistry.register("set_transform")
  def skill_set_transform(target, params):
      # at least one of position/rotation/scale must be present
      assert any(k in params for k in ("position", "rotation", "scale"))
      return {"target": target, "action": "set_transform", "parameters": params}

  @SkillRegistry.register("highlight")
  def skill_highlight(target, params):
      return {"target": target, "action": "highlight", "parameters": params}

  @SkillRegistry.register("set_sensor")
  def skill_set_sensor(target, params):
      valid_types = ("OPTICAL", "DISTANCE", "IMU")
      assert params.get("sensor_type") in valid_types, f"sensor_type must be one of {valid_types}"
      return {"target": target, "action": "set_sensor", "parameters": params}

  Import scene_skills.py at startup to trigger registration side-effects.

Verify     : SkillRegistry.dispatch("set_state", "Window_A", {"state": "open"})
             returns the expected dict without error.
             SkillRegistry.dispatch("unknown_action", ...) returns
             {"status": "unknown_skill", ...}.
```

---

### P1-T5 — Implement `AgentStatusBroadcaster`

```
Depends on : P1-T1
Files      : ✦ core/agent_status.py
Goal       : Centralise agent state management and push agent_status messages
             to all connected Unity clients whenever state changes.
Notes      :
  Agent states (enum or string constants):
      IDLE, LISTENING, TRANSCRIBING, THINKING, PLANNING,
      EXECUTING, SPEAKING, WAITING, SCRIPTING

  class AgentStatusBroadcaster:
      _current_state: str = "idle"
      _broadcast_fn: Callable   # injected at construction, calls server broadcast

      async def set_state(self, state: str, detail: str = "", plan_step: dict = None)
          - If state == _current_state, skip (no redundant pushes)
          - Build message:
              {"type": "agent_status", "state": state,
               "detail": detail, "plan_step": plan_step}
          - Call self._broadcast_fn(message)
          - Update _current_state

  The broadcaster is constructed in AgentCore which passes in the server's
  broadcast coroutine as broadcast_fn.

  Usage throughout the codebase:
      await status.set_state("thinking")
      ... LLM call ...
      await status.set_state("idle")

Verify     : Mock broadcast_fn, call set_state("thinking") twice with the
             same state — confirm broadcast is called only once (dedup check).
             Confirm calling with a different state triggers broadcast.
```

---

### P1-T6 — Implement `AgentCore`

```
Depends on : P1-T2, P1-T3, P1-T4, P1-T5
Files      : ✦ core/agent_core.py
             ✎ vsens_openai.py  (minor: expose _last_token_stats as property)
Goal       : Single orchestrator class that replaces VsensInteractionManager.
             Owns WorkingMemory, ControlParser, SkillRegistry, and
             AgentStatusBroadcaster references.
Notes      :
  class AgentCore:
      def __init__(self, agent: VsensOpenAI, broadcaster: AgentStatusBroadcaster):
          self.agent = agent
          self.memory = WorkingMemory()
          self.broadcaster = broadcaster

      async def handle_voice(self, audio_path: str, scene_snapshot: dict) -> dict
          1. await broadcaster.set_state("transcribing")
          2. user_text = agent.transcribe_audio(audio_path)
          3. memory.update_scene(scene_snapshot)
          4. await broadcaster.set_state("thinking")
          5. prompt = _build_prompt(user_text)
          6. reply_text = agent.send_message(prompt)
          7. spoken_text, actions = ControlParser.extract(reply_text)
          8. control_output = [SkillRegistry.dispatch(**a) for a in actions]
          9. await broadcaster.set_state("speaking")
         10. audio_path = agent.speak_text(spoken_text, ...)
         11. await broadcaster.set_state("idle")
         12. return {type, transcription, reply, audio_path, control: control_output}

      async def handle_text(self, message: str, scene_snapshot: dict) -> dict
          - same flow minus steps 1-2 and 9-10

      def _build_prompt(self, user_text: str) -> str
          - Uses memory.scene for context (full snapshot for now; diff in Phase 3)
          - Format identical to current _format_prompt output so prompt behaviour
            is unchanged

  VsensInteractionManager is kept but delegates entirely to AgentCore to
  avoid breaking the existing server wiring. It becomes a thin wrapper.

Verify     : Run main.py / test_server.py, send a text_chat message, confirm
             response and control commands match current system behaviour.
             Confirm agent_status messages are received by any WS client.
```

---

### P1-T7 — Update `vsens_server.py` — Interrupt Handling + Broadcast

```
Depends on : P1-T5, P1-T6
Files      : ✎ vsens_server.py
Goal       : Add server-initiated push capability, wire up AgentStatusBroadcaster,
             and handle agent_interrupt / plan_interrupt message types.
Notes      :
  1. Add broadcast coroutine:
       async def broadcast(self, message: dict):
           if self.clients:
               await asyncio.gather(
                   *[ws.send(json.dumps(message)) for ws in self.clients],
                   return_exceptions=True
               )

  2. Construct AgentStatusBroadcaster with self.broadcast as callback.
     Pass broadcaster into AgentCore constructor.

  3. Add handlers:
       "agent_interrupt" → _handle_agent_interrupt
       "plan_interrupt"  → _handle_plan_interrupt

  4. _handle_agent_interrupt:
       - Cancel self._active_task if one exists (store running task as
         self._active_task = asyncio.create_task(...) whenever a handler runs)
       - Call agent_core.memory.clear_plan()
       - await broadcaster.set_state("idle")
       - return {"type": "interrupt_ack", "message": "Stopped."}

  5. Wrap all handler invocations in process_message with task tracking:
       self._active_task = asyncio.ensure_future(handler(msg))
       result = await self._active_task

  Agent interrupt must take priority — check for it before routing to
  normal handlers.

Verify     : Start server, connect two WS clients. Send text_chat from client A.
             Immediately send agent_interrupt from client B mid-processing.
             Confirm interrupt_ack is returned and agent_status idle is broadcast
             to both clients. Server must remain stable afterward.
```

---

### P1-T8 — Move Static Knowledge into System Prompt

```
Depends on : nothing (prompt-only change)
Files      : ✎ data/prompts/system_prompt.txt
Goal       : Append the sensor type catalogue and coordinate conventions to the
             system prompt so they are OpenAI-cached and never re-sent per call.
             Implements Token Strategy D from RECONSTRUCT_PLAN.md Section 10.
Notes      :
  Add a new section at the end of system_prompt.txt:

  ## Sensor Type Reference (static, for context)
  - OPTICAL: binary presence/absence sensor. value: 0 or 1.
  - DISTANCE: range sensor. value: float (meters). params: validDistance, lookDirection.
  - IMU: inertial sensor. value: [ax, ay, az, gx, gy, gz] (accel + gyro).

  ## Coordinate System
  All positions [x, y, z] and rotations [rx, ry, rz] are Unity world-space.
  Y is up. Rotations are Euler angles in degrees.

  Remove any equivalent text from _build_prompt() in AgentCore so it is
  not re-injected per call.

Verify     : Run a sensor query. Check token usage stats (monitor_gui or
             printed token counts) — prompt_tokens should drop slightly and
             cached_tokens should increase after the second call in a session.
```

---

### P1-T9 — Phase 1 Integration Test

```
Depends on : P1-T1 through P1-T8
Files      : ✦ test_phase1.py   (temporary test script, can be deleted after)
Goal       : Confirm the full Phase 1 system works end-to-end identically to
             the pre-reconstruction baseline.
Checklist  :
  □ Server starts without errors
  □ text_chat message → correct reply + control commands returned
  □ transcribe_and_reply message → correct reply + audio path returned
  □ agent_status messages pushed on each state transition
  □ agent_interrupt cancels in-flight request and returns interrupt_ack
  □ plan_interrupt returns interrupt_ack, agent stays ready
  □ reset clears conversation history
  □ All token stats still printed / visible in monitor_gui
```

---

---

# Phase 2 — Memory

**Goal**: Integrate LanceDB for episodic memory and implement relevance-filtered scene context. Long sessions no longer grow unbounded in token cost.

---

### P2-T1 — Install and Configure LanceDB

```
Depends on : P1-T9 (phase 1 complete)
Files      : ✎ environment.yml   (add lancedb, pyarrow)
Goal       : LanceDB importable in the vsens_plus conda environment.
Notes      :
  Add to environment.yml dependencies:
    - lancedb>=0.6
    - pyarrow>=14.0   (LanceDB dependency, ensures correct version)

  Run:  conda env update -f environment.yml --prune

  LanceDB stores data as a directory of .lance files (Apache Arrow columnar).
  No server process, no Docker, works identically on Windows/macOS/Linux.

  Create the storage directory: data/memory/episodes/
  (LanceDB creates it automatically on first write, but document the path.)

Verify     : `import lancedb; db = lancedb.connect("data/memory/episodes")`
             runs without error from VsensPython/.
```

---

### P2-T2 — Implement `EpisodicMemory`

```
Depends on : P2-T1
Files      : ✦ core/memory/episodic_memory.py
Goal       : Wrap LanceDB to store and retrieve interaction episodes as
             vector-embedded records.
Notes      :
  Episode schema (LanceDB table row):
      session_id  : str
      timestamp   : str   (ISO 8601)
      user_input  : str
      agent_reply : str
      scene_summary: str  (json.dumps of scene keys + sensor values only — compact)
      control_actions: str (json.dumps of action list)
      embedding   : list[float]  (1536-dim, text-embedding-3-small)

  class EpisodicMemory:
      TABLE_NAME = "episodes"

      def __init__(self, db_path: str, openai_client):
          self.db = lancedb.connect(db_path)
          self.client = openai_client
          self._table = self._open_or_create_table()

      def _embed(self, text: str) -> list[float]:
          resp = self.client.embeddings.create(
              model="text-embedding-3-small", input=text)
          return resp.data[0].embedding

      def store(self, session_id, user_input, agent_reply,
                scene_snapshot, control_actions):
          text_to_embed = f"{user_input} {agent_reply}"
          embedding = self._embed(text_to_embed)
          scene_summary = _compact_scene(scene_snapshot)   # helper, see below
          self._table.add([{...all fields...}])

      def retrieve(self, query: str, n: int = 3) -> list[dict]:
          embedding = self._embed(query)
          results = self._table.search(embedding).limit(n).to_list()
          return results

  _compact_scene(snapshot: dict) -> str:
      # Strips position/rotation/size, keeps only object names, states,
      # and sensor values. ~80% token reduction vs. full JSON.
      # Used only for the stored scene_summary field, NOT for prompts.

  EpisodicMemory is instantiated once inside MemoryManager (P2-T4).

Verify     : store() 3 episodes, then retrieve("DISTANCE sensor") — confirm
             the most relevant episode is ranked first.
```

---

### P2-T3 — Implement `SemanticMemory`

```
Depends on : P1-T1
Files      : ✦ core/memory/semantic_memory.py
             ✦ data/memory/knowledge/sensors.yaml
             ✦ data/memory/knowledge/scene_conventions.yaml
Goal       : Load static domain knowledge YAML files at startup and expose
             them for prompt injection and agent queries.
Notes      :
  sensors.yaml structure:
    sensors:
      OPTICAL:
        description: "Binary presence sensor. Detects if an object is within range."
        typical_placement: "Attach to surface facing the detection zone."
        value_range: [0, 1]
        key_parameters: []
      DISTANCE:
        description: "Range finder. Reports distance to nearest object along lookDirection."
        typical_placement: "Mount facing open space along measurement axis."
        value_range: [0, "validDistance"]
        key_parameters: ["validDistance", "lookDirection"]
      IMU:
        description: "Inertial sensor. Reports 6-DOF acceleration and angular velocity."
        typical_placement: "Attach to moving object (body segment, door hinge, etc.)."
        value_range: "continuous float array [ax,ay,az,gx,gy,gz]"
        key_parameters: []

  scene_conventions.yaml:
    coordinate_system: "Unity world space. Y-up. Rotations in Euler degrees XYZ."
    units: "meters and degrees"

  class SemanticMemory:
      def __init__(self, knowledge_dir: str):
          self.knowledge = {}
          for yaml_file in Path(knowledge_dir).glob("*.yaml"):
              self.knowledge[yaml_file.stem] = yaml.safe_load(yaml_file.read_text())

      def get(self, key: str) -> dict | None:
          return self.knowledge.get(key)

      def as_text(self) -> str:
          # Returns a compact string summary for prompt injection
          # (used only if the static system prompt section is insufficient)

Verify     : SemanticMemory("data/memory/knowledge").get("sensors")["OPTICAL"]
             returns the expected dict.
```

---

### P2-T4 — Implement `MemoryManager`

```
Depends on : P2-T2, P2-T3
Files      : ✦ core/memory/memory_manager.py
Goal       : Single entry point for all memory operations. Builds the
             memory-augmented context string injected before every LLM call.
Notes      :
  class MemoryManager:
      def __init__(self, working: WorkingMemory, episodic: EpisodicMemory,
                   semantic: SemanticMemory):
          ...

      def build_context(self, user_input: str) -> str:
          """
          Returns a context string to prepend to the user's message before
          sending to the LLM. Contains:
            1. Up to 3 relevant past episodes (from episodic retrieval)
            2. Active plan step from working memory (if any)
            3. Recent events list from working memory (last 3)
          """
          episodes = self.episodic.retrieve(user_input, n=3)
          context_parts = []
          if episodes:
              context_parts.append("[Relevant past interactions]")
              for ep in episodes:
                  context_parts.append(
                      f"- User said: \"{ep['user_input']}\" → "
                      f"Agent replied: \"{ep['agent_reply'][:120]}...\"")
          if self.working.active_plan:
              step = self.working.active_plan.get("current_step")
              context_parts.append(f"[Active plan step: {step}]")
          if self.working.recent_events:
              context_parts.append("[Recent scene events]")
              for ev in self.working.recent_events[-3:]:
                  context_parts.append(f"- {ev['summary']}")
          return "\n".join(context_parts)

      def store_interaction(self, session_id, user_input, agent_reply,
                            scene_snapshot, control_actions):
          self.episodic.store(...)

  MemoryManager is instantiated in AgentCore (update AgentCore in P2-T6).

Verify     : With 5 stored episodes, build_context("move the sensor closer")
             returns a non-empty string containing at least one past episode.
```

---

### P2-T5 — Implement Scene Relevance Filtering

```
Depends on : P2-T1
Files      : ✦ core/memory/scene_filter.py
Goal       : Filter scene objects by semantic relevance to the current user
             query before injecting scene context into the prompt.
             Implements Token Strategy C from RECONSTRUCT_PLAN.md Section 10.
Notes      :
  class SceneFilter:
      def __init__(self, openai_client):
          self.client = openai_client
          self._object_embeddings: dict[str, list[float]] = {}

      def update_embeddings(self, scene: dict):
          """
          Re-embed object descriptions when the scene changes significantly.
          Called by WorkingMemory.update_scene() via MemoryManager.
          Uses a simple text description per object:
            "Window_A: state=closed, position=[3.4,1.9,7.5]"
          Only re-embeds objects that are new or changed.
          """

      def filter(self, scene: dict, query: str, top_k: int = 15) -> dict:
          """
          Returns a subset of scene containing the top_k most relevant objects.
          Falls back to full scene if embeddings not yet computed.
          """
          query_emb = self._embed(query)
          scored = []
          for name, obj_emb in self._object_embeddings.items():
              score = cosine_similarity(query_emb, obj_emb)
              scored.append((name, score))
          top_names = {n for n, _ in sorted(scored, key=lambda x: -x[1])[:top_k]}
          return {k: v for k, v in scene.items() if k in top_names}

  cosine_similarity is a local 3-line function, no scipy needed:
      def cosine_similarity(a, b):
          dot = sum(x*y for x,y in zip(a,b))
          norm_a = sum(x**2 for x in a)**0.5
          norm_b = sum(x**2 for x in b)**0.5
          return dot / (norm_a * norm_b + 1e-9)

  top_k=15 is a sensible default for typical scenes with 20–60 objects.
  Always include objects explicitly named in the user query regardless of score.

Verify     : Build a mock scene of 30 objects. filter(scene, "coffee maker sensor")
             returns a subdict containing CoffeeMaker and its sensors, and
             excludes unrelated objects like Lamp_3.
```

---

### P2-T6 — Wire Memory into `AgentCore`

```
Depends on : P2-T4, P2-T5
Files      : ✎ core/agent_core.py
             ✎ vsens_server.py   (pass openai_client to memory constructors)
Goal       : AgentCore now builds memory-augmented prompts and stores each
             interaction in episodic memory after completion.
Notes      :
  Update AgentCore.__init__:
      self.scene_filter = SceneFilter(agent.client)
      self.memory_manager = MemoryManager(self.memory, episodic, semantic)

  Update _build_prompt(user_text):
      # 1. Filter scene to relevant objects only
      filtered_scene = scene_filter.filter(memory.scene, user_text)
      scene_json = json.dumps(filtered_scene, indent=2)

      # 2. Build memory context
      context = memory_manager.build_context(user_text)

      # 3. Compose prompt
      return (
          f"{context}\n\n"
          f"User said: \"{user_text}\"\n\n"
          f"Current scene (relevant objects):\n{scene_json}\n"
      )

  After each successful handle_voice / handle_text call, call:
      memory_manager.store_interaction(
          session_id = memory.session_id,
          user_input = user_text,
          agent_reply = spoken_text,
          scene_snapshot = memory.scene,
          control_actions = control_output
      )

Verify     : Complete a 10-turn conversation. On turn 10, ask something
             related to turn 2. Confirm the turn 2 episode appears in
             the injected context (visible in printed prompt log).
             Confirm filtered scene contains fewer objects than the full scene
             for a focused query.
```

---

### P2-T7 — Phase 2 Integration Test

```
Depends on : P2-T1 through P2-T6
Files      : ✦ test_phase2.py
Checklist  :
  □ LanceDB data/memory/episodes/ directory created on first interaction
  □ Episodes persist across server restarts (re-run server, check retrieval works)
  □ build_context() injects relevant past episodes into prompts
  □ Scene relevance filter reduces scene context for focused queries
  □ Token count (prompt_tokens) is lower than pre-Phase-2 baseline for
    the same query on a populated memory store
  □ All Phase 1 functionality still works correctly
```

---

---

# Phase 3 — Heartbeat / Proactive Perception

**Goal**: Unity sends periodic scene snapshots. Python detects meaningful changes without an LLM call, then wakes the LLM only for significant events and pushes proactive messages back to Unity.

---

### P3-T1 — Implement `SceneDiff`

```
Depends on : P1-T2  (WorkingMemory)
Files      : ✦ core/perception/scene_diff.py
Goal       : Produce a structured, human-readable change log by comparing
             two consecutive scene snapshots.
Notes      :
  def compute_diff(old: dict, new: dict) -> list[dict]:
      """
      Returns a list of change dicts, e.g.:
        [
          {"object": "OPTICAL-01", "field": "value", "old": 0, "new": 1},
          {"object": "Window_A", "field": "state", "old": "open", "new": "closed"},
          {"object": "user", "field": "position", "delta_m": 0.43}
        ]
      """
  Rules:
    - For sensor objects: compare sensor.value. Flag if delta > threshold
      (default 0.1 absolute or 20% relative for continuous sensors;
       any change for binary sensors like OPTICAL).
    - For state objects: compare state string.
    - For user object (if present): compare position, compute Euclidean distance.
    - Ignore: size, rotation (too noisy for event detection).
    - New objects added to the scene → change type "object_added".
    - Objects removed → change type "object_removed".

  Also expose as_text(changes: list[dict]) -> str for prompt injection:
      "OPTICAL-01: value 0→1. Window_A: state open→closed."

Verify     : Unit test with two mock snapshots differing in one sensor value
             and one state. Confirm exactly two change dicts returned.
             Test with identical snapshots → empty list returned.
```

---

### P3-T2 — Implement `EventClassifier`

```
Depends on : P3-T1
Files      : ✦ core/perception/event_classifier.py
Goal       : Map a list of scene diffs to named event types and a significance
             score, so the attention gate can decide whether to wake the LLM.
Notes      :
  Event types (string constants):
      NO_OP         — no changes above threshold
      SENSOR_TRIGGER — binary sensor changed value (OPTICAL 0→1 or 1→0)
      SENSOR_ANOMALY — continuous sensor value jumped > 50% in one frame
      STATE_CHANGE   — object state changed (door, window, etc.)
      USER_PROXIMITY — user position delta > 0.5m in one heartbeat
      OBJECT_ADDED   — new object in scene
      OBJECT_REMOVED — object disappeared from scene

  def classify(changes: list[dict]) -> list[dict]:
      """Returns list of {"event_type": str, "object": str, "severity": float}"""

  Severity scale: 0.0 (trivial) to 1.0 (critical).
  Attention gate threshold: severity >= 0.5 wakes the LLM.
  Suggested severity assignments:
      SENSOR_TRIGGER  → 0.8
      SENSOR_ANOMALY  → 0.7
      STATE_CHANGE    → 0.6
      USER_PROXIMITY  → 0.4 (below threshold, informational only)
      OBJECT_ADDED    → 0.5
      OBJECT_REMOVED  → 0.5
      NO_OP           → 0.0

  The severity thresholds should be configurable via a simple dict in
  a config section at the top of the file, not hardcoded deep in logic.

Verify     : Feed changes for OPTICAL 0→1 + user moved 0.3m.
             Classify returns [SENSOR_TRIGGER severity 0.8, USER_PROXIMITY 0.4].
             Attention gate check: only SENSOR_TRIGGER exceeds 0.5 threshold.
```

---

### P3-T3 — Implement `HeartbeatHandler`

```
Depends on : P3-T2, P1-T5  (AgentStatusBroadcaster)
Files      : ✦ core/perception/heartbeat_handler.py
Goal       : Process scene_heartbeat messages end-to-end: diff → classify →
             attention gate → optionally wake LLM → broadcast agent_push.
Notes      :
  class HeartbeatHandler:
      def __init__(self, working_memory, memory_manager, agent, broadcaster, broadcast_fn):
          ...

      async def handle(self, scene_snapshot: dict) -> dict | None:
          """
          Returns agent_push dict if a significant event was detected,
          None otherwise.
          """
          # 1. Compute diff vs. last known scene
          changes = SceneDiff.compute_diff(working_memory.last_scene, scene_snapshot)

          # 2. Update working memory regardless
          working_memory.update_scene(scene_snapshot)

          # 3. Classify events
          events = EventClassifier.classify(changes)
          significant = [e for e in events if e["severity"] >= ATTENTION_THRESHOLD]

          # 4. Add low-severity events to recent_events list (for prompt context)
          for ev in events:
              working_memory.add_event({"summary": f"{ev['event_type']} on {ev['object']}"})

          # 5. Attention gate
          if not significant:
              return None

          # 6. Wake LLM with event context
          await broadcaster.set_state("thinking", detail="Reacting to scene event")
          event_summary = _format_events(significant, changes)
          prompt = (
              f"[Scene event detected]\n{event_summary}\n\n"
              f"Current scene:\n{json.dumps(working_memory.scene, indent=2)}\n\n"
              f"Briefly comment or take action if appropriate."
          )
          reply_text = agent.send_message(prompt)
          spoken_text, actions = ControlParser.extract(reply_text)
          control_output = [SkillRegistry.dispatch(**a) for a in actions]
          await broadcaster.set_state("idle")

          return {
              "type": "agent_push",
              "trigger": significant[0]["event_type"],
              "message": spoken_text,
              "control": {"actions": control_output}
          }

Verify     : Mock a heartbeat that changes OPTICAL-01 value 0→1.
             Confirm handle() returns a non-None agent_push dict.
             Mock a heartbeat with no meaningful changes.
             Confirm handle() returns None (no LLM call made).
```

---

### P3-T4 — Register `scene_heartbeat` in Server

```
Depends on : P3-T3
Files      : ✎ vsens_server.py
Goal       : Route scene_heartbeat messages to HeartbeatHandler and broadcast
             any resulting agent_push to all connected clients.
Notes      :
  In VsensWebSocketServer.__init__:
      self.heartbeat_handler = HeartbeatHandler(
          working_memory = self.agent_core.memory,
          memory_manager = self.agent_core.memory_manager,
          agent = self.agent,
          broadcaster = self.broadcaster,
          broadcast_fn = self.broadcast
      )
      self.handlers["scene_heartbeat"] = self._handle_heartbeat

  async def _handle_heartbeat(self, msg):
      scene_snapshot = msg.get("scene_snapshot", {})
      push = await self.heartbeat_handler.handle(scene_snapshot)
      if push:
          await self.broadcast(push)
      # Do NOT send a response back to the requesting client for no-op heartbeats
      # Return None; server skips sending a reply when handler returns None
      return push  # None or the push dict (server only sends if not None)

  Update process_message to skip websocket.send() when handler returns None.

  Heartbeat messages must NOT be wrapped in self._active_task tracking —
  they are lightweight and should not be interruptible.

Verify     : Connect a Unity mock client. Start sending heartbeat messages
             at 1s intervals. Confirm no WS messages are sent back for
             no-op heartbeats, but an agent_push message IS sent when a
             sensor value change is included.
```

---

### P3-T5 — Scene Diff as Prompt Context (Token Strategy A)

```
Depends on : P3-T3, P2-T6
Files      : ✎ core/agent_core.py
Goal       : After Phase 3, regular interactions no longer inject the full scene
             snapshot. Instead they inject only the diff since the last call.
             Implements Token Strategy A from RECONSTRUCT_PLAN.md Section 10.
Notes      :
  Update _build_prompt in AgentCore:

      if memory.last_scene:
          changes = SceneDiff.compute_diff(memory.last_scene, memory.scene)
          if changes:
              scene_context = "[Scene changes since last interaction]\n" + SceneDiff.as_text(changes)
          else:
              scene_context = "[Scene unchanged since last interaction]"
      else:
          # First call of session: inject full filtered scene
          filtered = scene_filter.filter(memory.scene, user_text)
          scene_context = "Current scene:\n" + json.dumps(filtered, indent=2)

  This means the first call of a session still sends the (relevance-filtered)
  full snapshot, and all subsequent calls send only the compact diff.

  IMPORTANT: On reset, memory.last_scene must be cleared so the next call
  sends a full snapshot again.

Verify     : Two-turn conversation with an unchanged scene. Second call's
             prompt should contain "[Scene unchanged since last interaction]"
             and no large JSON blob. Confirm token count for call 2 is
             significantly lower than call 1.
```

---

### P3-T6 — Phase 3 Integration Test

```
Depends on : P3-T1 through P3-T5
Files      : ✦ test_phase3.py
Checklist  :
  □ scene_heartbeat messages handled without error
  □ No-op heartbeats produce no WS output
  □ OPTICAL 0→1 heartbeat triggers agent_push to all clients
  □ agent_status transitions visible during event-triggered LLM call
  □ Second interaction in a session uses diff context, not full snapshot
  □ Token count on second call is lower than first call
  □ All Phase 1 and Phase 2 functionality still works
```

---

---

# Phase 4 — Multi-Step Planner

**Goal**: The agent can decompose high-level user commands into a JSON plan and execute it step by step, including steps that wait for sensor conditions detected by the heartbeat system.

---

### P4-T1 — Define Task Types Schema

```
Depends on : P1-T1
Files      : ✦ core/planning/task_types.py
Goal       : Canonical Python dataclasses (or TypedDicts) for plan step types.
             Used by both Planner (generation) and PlanExecutor (execution).
Notes      :
  from typing import TypedDict, Literal

  class PlanStep(TypedDict):
      id: int
      type: Literal["set_sensor","set_state","set_transform","highlight",
                    "wait_condition","agent_speak","run_script","memory_search"]
      description: str
      params: dict     # type-specific, matches SkillRegistry param shapes

  class Plan(TypedDict):
      goal: str
      steps: list[PlanStep]
      current_step_id: int   # 0 = not started
      status: Literal["pending","running","paused","completed","cancelled"]

  wait_condition params shape:
      {
        "object": "DISTANCE-01",
        "field": "sensor.value",
        "operator": "<",   # one of: <, >, ==, !=, <=, >=
        "threshold": 1.5,
        "timeout_s": 30    # max seconds to wait before giving up
      }

  agent_speak params shape:
      { "message": "Proximity triggered at entrance." }

Verify     : Import task_types, construct a Plan with two steps, confirm
             TypedDict structure is correct.
```

---

### P4-T2 — Implement `Planner`

```
Depends on : P4-T1
Files      : ✦ core/planning/planner.py
             ✦ data/prompts/planner_prompt.txt
Goal       : LLM call in planner mode — takes a high-level goal and a scene
             snapshot, returns a structured Plan dict.
Notes      :
  planner_prompt.txt system prompt content:
      You are a task planner for a virtual XR sensor environment.
      Given a user goal and a scene snapshot, decompose the goal into a
      sequential list of concrete steps.
      Output ONLY valid JSON matching this schema: { "goal": str, "steps": [...] }
      Available step types: set_sensor, set_state, set_transform, highlight,
        wait_condition, agent_speak, run_script.
      Each step must have: id (int), type (str), description (str), params (dict).
      Do not include explanations outside the JSON. Do not include comments.

  class Planner:
      def __init__(self, agent: VsensOpenAI):
          self.agent = agent
          self.planner_prompt = Path("data/prompts/planner_prompt.txt").read_text()

      def generate_plan(self, goal: str, scene: dict) -> Plan:
          prompt = (
              f"Goal: {goal}\n\n"
              f"Scene:\n{json.dumps(scene, indent=2)}"
          )
          # Separate LLM call with planner_prompt as system role
          resp = self.agent.client.chat.completions.create(
              model=self.agent.model,
              messages=[
                  {"role": "system", "content": self.planner_prompt},
                  {"role": "user", "content": prompt}
              ]
          )
          raw = resp.choices[0].message.content
          plan_dict = json.loads(raw)
          plan_dict["current_step_id"] = 0
          plan_dict["status"] = "pending"
          return plan_dict

  Note: This uses a SEPARATE messages list from the main conversation.
  It does not pollute the agent's conversation history.

Verify     : Call generate_plan("Set up proximity detection at the entrance",
             mock_scene). Confirm output is valid JSON parseable into Plan schema
             with at least 2 steps, all of known types.
```

---

### P4-T3 — Implement `PlanExecutor`

```
Depends on : P4-T2, P1-T3  (SkillRegistry), P1-T5 (broadcaster)
Files      : ✦ core/planning/plan_executor.py
Goal       : Step through a Plan sequentially, dispatching each step via
             SkillRegistry and broadcasting plan_update after each step.
Notes      :
  class PlanExecutor:
      def __init__(self, skill_registry, broadcaster, broadcast_fn, working_memory):
          self._condition_listeners: list[dict] = []  # for wait_condition steps
          ...

      async def execute(self, plan: Plan) -> None:
          working_memory.set_plan(plan)
          plan["status"] = "running"
          await broadcaster.set_state("executing")

          for step in plan["steps"]:
              plan["current_step_id"] = step["id"]
              await broadcast_fn({
                  "type": "plan_update",
                  "step_id": step["id"],
                  "description": step["description"],
                  "total_steps": len(plan["steps"])
              })
              # also update agent_status detail
              await broadcaster.set_state("executing",
                  detail=step["description"],
                  plan_step={"current": step["id"], "total": len(plan["steps"])})

              result = await _execute_step(step)
              if result.get("status") == "cancelled":
                  break

          plan["status"] = "completed"
          working_memory.clear_plan()
          await broadcaster.set_state("idle")

      async def _execute_step(self, step: PlanStep) -> dict:
          t = step["type"]
          if t in ("set_sensor","set_state","set_transform","highlight"):
              action = skill_registry.dispatch(t, step.get("target",""), step["params"])
              # broadcast control to Unity
              await broadcast_fn({"type": "agent_ready", "control": {"actions": [action]}})
              return {"status": "ok"}
          elif t == "wait_condition":
              return await _wait_condition(step["params"])
          elif t == "agent_speak":
              await broadcast_fn({
                  "type": "agent_push", "message": step["params"]["message"], "control": {}})
              return {"status": "ok"}
          elif t == "run_script":
              return skill_registry.dispatch("run_script", "_workspace", step["params"])
          else:
              return {"status": "unknown_step_type", "type": t}

Verify     : Build a 3-step plan (set_sensor, agent_speak, highlight).
             Execute it against a mock broadcaster. Confirm 3 plan_update
             messages and 3 action dispatches occur in order.
```

---

### P4-T4 — Implement `wait_condition` Listener

```
Depends on : P4-T3, P3-T1  (SceneDiff)
Files      : ✎ core/planning/plan_executor.py
Goal       : Block a plan step until a scene condition is satisfied (checked
             on every heartbeat) or a timeout is reached.
Notes      :
  async def _wait_condition(self, params: dict) -> dict:
      obj    = params["object"]
      field  = params["field"]       # e.g. "sensor.value"
      op     = params["operator"]    # "<", ">", "==", etc.
      thresh = params["threshold"]
      timeout = params.get("timeout_s", 30)

      deadline = asyncio.get_event_loop().time() + timeout
      while asyncio.get_event_loop().time() < deadline:
          # Read current value from working_memory.scene
          val = _get_nested(working_memory.scene, obj, field)
          if val is not None and _compare(val, op, thresh):
              return {"status": "condition_met"}
          await asyncio.sleep(0.5)   # poll every 500ms

      return {"status": "timeout"}

  _get_nested(scene, obj, field): resolves dotted field path, e.g.
      "sensor.value" → scene[obj]["sensor"]["value"]

  _compare(val, op, thresh): evaluates val op thresh.

  This polling approach is simple and correct. The 500ms poll interval
  means condition detection latency is at most 500ms — acceptable for
  sensor simulation use cases.

Verify     : Set up a wait_condition for OPTICAL-01 value == 1.
             Update working_memory.scene["OPTICAL-01"]["sensor"]["value"] to 1
             from another coroutine after 1 second.
             Confirm wait_condition resolves within ~1.5 seconds.
             Test timeout: condition never true → returns {"status": "timeout"}
             after timeout_s.
```

---

### P4-T5 — Register `generate_plan` Skill + Wire into AgentCore

```
Depends on : P4-T3, P1-T6  (AgentCore)
Files      : ✎ core/skills/scene_skills.py
             ✎ core/agent_core.py
Goal       : When the LLM emits a generate_plan action in its <control> block,
             the SkillRegistry routes it to the Planner, and AgentCore runs the
             resulting plan asynchronously via PlanExecutor.
Notes      :
  In scene_skills.py (or a new planning_skills.py):
      @SkillRegistry.register("generate_plan")
      def skill_generate_plan(target, params):
          # Returns the goal string; AgentCore handles actual execution
          return {"status": "plan_requested", "goal": params.get("goal", "")}

  In AgentCore.handle_voice / handle_text, after dispatching all skills:
      for result in control_output:
          if result.get("status") == "plan_requested":
              plan = planner.generate_plan(result["goal"], memory.scene)
              # Run plan execution as a background task so the current
              # request can return immediately
              asyncio.ensure_future(plan_executor.execute(plan))

  AgentCore needs references to Planner and PlanExecutor (add to __init__).

  The LLM should include a generate_plan action when the user gives a
  high-level compound goal. Update system_prompt.txt to document this
  action type, consistent with existing action documentation.

Verify     : Send text_chat: "Set up a 3-sensor gait detection rig".
             Confirm the LLM response includes a generate_plan action.
             Confirm plan_update messages are broadcast as steps execute.
             Confirm agent_status shows "executing" during plan execution.
```

---

### P4-T6 — Handle `plan_interrupt` in Server

```
Depends on : P4-T3
Files      : ✎ vsens_server.py
             ✎ core/planning/plan_executor.py
Goal       : plan_interrupt halts the running plan gracefully but leaves the
             agent in a conversational ready state (unlike agent_interrupt
             which cancels everything).
Notes      :
  Add a cancel() method to PlanExecutor:
      def cancel(self):
          self._cancelled = True   # checked in _execute_step loop

  Update the execute() loop:
      if self._cancelled:
              plan["status"] = "cancelled"
              working_memory.clear_plan()
              await broadcaster.set_state("idle")
              break

  In vsens_server.py:
      async def _handle_plan_interrupt(self, msg):
          self.plan_executor.cancel()
          return {"type": "interrupt_ack", "message": "Plan cancelled. Ready for new command."}

Verify     : Start a 5-step plan with 1-second pauses between steps.
             Send plan_interrupt after step 2. Confirm execution stops after
             current step completes, agent returns to idle, and a new
             text_chat command is processed correctly afterward.
```

---

### P4-T7 — Phase 4 Integration Test

```
Depends on : P4-T1 through P4-T6
Files      : ✦ test_phase4.py
Checklist  :
  □ "Set up 3 sensors" command produces a valid multi-step plan
  □ plan_update messages broadcast for each step
  □ agent_status shows "executing" with step progress
  □ wait_condition step resolves when scene is updated via heartbeat
  □ wait_condition times out gracefully after timeout_s
  □ plan_interrupt stops execution and agent returns to idle
  □ New commands accepted normally after plan_interrupt
  □ All prior phase functionality still works
```

---

---

# Phase 5 — Script Workspace

**Goal**: The agent can write Python code at runtime, execute it in a sandbox, and return results to the user or inject them into the scene pipeline.

---

### P5-T1 — Implement `Sandbox`

```
Depends on : P1-T1
Files      : ✦ core/workspace/sandbox.py
Goal       : Restricted Python execution environment with import whitelist,
             execution timeout, and no filesystem/network access.
Notes      :
  ALLOWED_IMPORTS = {"math", "json", "time", "random", "numpy",
                     "itertools", "functools", "collections", "statistics"}

  def execute(code: str, timeout_s: float = 5.0) -> dict:
      """
      Executes code string in a restricted namespace.
      Returns {"status": "ok", "output": <captured stdout>, "result": <last expr>}
      or {"status": "error", "message": str, "traceback": str}
      or {"status": "timeout"}
      """
      # 1. Validate imports: parse AST, check all Import/ImportFrom nodes
      #    against ALLOWED_IMPORTS. Reject immediately if any disallowed import.
      import ast
      tree = ast.parse(code)
      for node in ast.walk(tree):
          if isinstance(node, (ast.Import, ast.ImportFrom)):
              names = [n.name for n in node.names] if isinstance(node, ast.Import) \
                      else [node.module]
              for name in names:
                  root = (name or "").split(".")[0]
                  if root not in ALLOWED_IMPORTS:
                      return {"status": "error",
                              "message": f"Import '{root}' is not allowed."}

      # 2. Build restricted globals (no builtins that allow file/network access)
      safe_globals = {
          "__builtins__": {k: __builtins__[k] for k in
              ("print","len","range","enumerate","zip","map","filter",
               "sorted","sum","min","max","abs","round","int","float",
               "str","list","dict","tuple","set","bool","type",
               "isinstance","hasattr","getattr")}
      }

      # 3. Execute with timeout via threading.Timer
      import threading, io, sys
      output_buf = io.StringIO()
      result_container = {}
      def run():
          try:
              old_stdout = sys.stdout
              sys.stdout = output_buf
              exec(code, safe_globals)
              sys.stdout = old_stdout
              result_container["status"] = "ok"
              result_container["output"] = output_buf.getvalue()
          except Exception as e:
              sys.stdout = old_stdout
              result_container["status"] = "error"
              result_container["message"] = str(e)
              result_container["traceback"] = traceback.format_exc()

      thread = threading.Thread(target=run, daemon=True)
      thread.start()
      thread.join(timeout_s)
      if thread.is_alive():
          return {"status": "timeout"}
      return result_container

Verify     : execute("import math; print(math.pi)") → status ok, output "3.14..."
             execute("import os") → status error, message mentions 'os' not allowed
             execute("while True: pass", timeout_s=1) → status timeout
```

---

### P5-T2 — Implement `ScriptWorkspace`

```
Depends on : P5-T1
Files      : ✦ core/workspace/script_workspace.py
Goal       : Higher-level wrapper around Sandbox. Persists generated scripts to
             disk, formats results for injection into agent context or Unity.
Notes      :
  SCRIPTS_DIR = Path("data/workspace/scripts")
  OUTPUT_DIR  = Path("data/workspace/output")

  class ScriptWorkspace:
      @staticmethod
      def execute(code: str, save: bool = True) -> dict:
          """
          Runs code in Sandbox, saves script + output to disk,
          returns a result dict suitable for WebSocket response.
          """
          # 1. Save script to disk with timestamp filename
          if save:
              SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
              ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
              script_path = SCRIPTS_DIR / f"script_{ts}.py"
              script_path.write_text(code, encoding="utf-8")

          # 2. Run in sandbox
          result = Sandbox.execute(code)

          # 3. Save output if successful
          if result["status"] == "ok" and save:
              OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
              output_path = OUTPUT_DIR / f"output_{ts}.txt"
              output_path.write_text(result.get("output", ""), encoding="utf-8")

          return {
              "type": "script_result",
              "status": result["status"],
              "output": result.get("output", ""),
              "error": result.get("message", ""),
              "script_path": str(script_path) if save else None
          }

Verify     : ScriptWorkspace.execute("for i in range(3): print(i)")
             returns status ok, output "0\n1\n2\n", and files exist in
             data/workspace/scripts/ and data/workspace/output/.
```

---

### P5-T3 — Register `run_script` Skill + Wire into Server

```
Depends on : P5-T2, P1-T4
Files      : ✎ core/skills/scene_skills.py   (or a new workspace_skills.py)
             ✎ vsens_server.py
             ✎ data/prompts/system_prompt.txt
Goal       : LLM can emit a run_script action. Server executes it via
             ScriptWorkspace and broadcasts the result back to Unity.
Notes      :
  Register the skill:
      @SkillRegistry.register("run_script")
      def skill_run_script(target, params):
          from core.workspace.script_workspace import ScriptWorkspace
          return ScriptWorkspace.execute(params.get("code", ""))

  In AgentCore, after dispatching skills, check for script_result:
      for result in control_output:
          if result.get("type") == "script_result":
              await broadcast_fn(result)
              # Also inject result summary into working memory recent_events
              working_memory.add_event({
                  "summary": f"Script executed: {result['output'][:100]}"
              })

  Update system_prompt.txt action list documentation to include run_script:
      2.5 [run_script]: Execute a Python script in the secure workspace.
          "parameters" must include "code" (Python string).
          Available modules: math, json, time, random, numpy, itertools,
          functools, collections, statistics.
          Returns output via script_result message to Unity.
          Use for: custom sensor data patterns, geometry calculations,
          statistical analysis of sensor logs.

Verify     : Send text_chat: "Generate a 10-point sine wave for IMU x-axis".
             Confirm LLM produces a run_script action with numpy sine code.
             Confirm script_result message is broadcast with float array output.
             Confirm script file saved in data/workspace/scripts/.
```

---

### P5-T4 — Phase 5 Integration Test

```
Depends on : P5-T1 through P5-T3
Files      : ✦ test_phase5.py
Checklist  :
  □ run_script action in LLM response executes correctly
  □ script_result broadcast to Unity client
  □ Script and output files saved to data/workspace/
  □ Disallowed import in generated code → error returned, no crash
  □ Infinite loop in generated code → timeout returned after 5s, server stable
  □ Script output injected into working memory recent_events
  □ All prior phase functionality still works
```

---

---

# Final Integration Test

```
Depends on : All phases complete
Files      : ✦ test_full_integration.py
Goal       : End-to-end smoke test covering all five phases working together.
Checklist  :
  □ Server starts cleanly, monitor_gui shows correct status
  □ voice interaction: transcribe → memory-augmented reply → TTS → Unity
  □ text interaction: memory retrieved from LanceDB on turn 5+
  □ Heartbeat: OPTICAL trigger → agent_push without user prompt
  □ Complex command: multi-step plan generated, executed, plan_update broadcast
  □ wait_condition: plan pauses until heartbeat delivers the expected value
  □ Script: run_script generates sine wave, script_result sent to Unity
  □ agent_interrupt: cancels mid-LLM-call, agent returns to idle
  □ plan_interrupt: stops running plan, accepts new command
  □ reset: clears conversation, next call sends full scene snapshot
  □ Token efficiency: turn 10 prompt_tokens < turn 1 prompt_tokens
     (confirms scene diff + relevance filtering are active)
```

---

## Package Dependencies Summary

```
New additions to environment.yml:

  - lancedb>=0.6          # Phase 2: episodic memory
  - pyarrow>=14.0         # Phase 2: LanceDB dependency
  - pyyaml>=6.0           # Phase 2: semantic memory YAML loading
                          # (likely already installed, confirm)

  numpy is already in the environment (used in workspace sandbox whitelist).
  No other new external dependencies are introduced across all 5 phases.
```
 
