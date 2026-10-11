# Phase 1 & 2 — Unity Integration Notes

**Date**: March 1, 2026  
**Scope**: Items requiring negotiation with the Python side, or further consideration on the Unity side.

---

## Changes Applied (Unity Side)

| File | What changed |
|---|---|
| `Network/Protocol/Messages.cs` | Added `AgentStatusMessage` and `InterruptAckMessage` classes |
| `Network/Protocol/Requests.cs` | Added `AgentInterruptRequest` and `PlanInterruptRequest` classes; updated `ResetRequest` doc comment to clarify episodic memory is **not** cleared |
| `Network/WsClient.cs` | Added `OnAgentStatus` event; handles `agent_status` and `interrupt_ack` message types; added `SendAgentInterrupt()` / `SendPlanInterrupt()` static methods; default `switch` case now silently ignores unknown types (forward-compat) |
| `Core/Controllers/Agent/AgentBehaviorController.cs` | Subscribes to `OnAgentStatus`; maps `thinking / planning / scripting / transcribing / executing` → `StartThinking()`, and `idle / speaking` → `StopThinking()` |
| `VirtualObject/ObjectDescriber.cs` | `GetDescription()` now emits a `scale` array (`lossyScale`, 3 dp) in addition to the existing `position`, `size`, `rotation` from `BoxColliderData` |

---

## Canonical `scene_snapshot` Object Schema

### Regular Objects (`ObjectDescriber.GetDescription()`)

```json
"Window_A": {
    "position":        [3.4, 1.9, 7.5],
    "size":            [1.2, 1.0, 0.1],
    "rotation":        [0, 0, 0],
    "scale":           [1, 1, 1],
    "properties":      ["with_state", "movable"],
    "state":           "open",
    "availableStates": ["open", "closed"]
}
```

### Sensor Objects (`SensorObjectDescriber.GetDescription()`)

Sensor objects carry three additional top-level keys over regular objects:

| Key | Type | Description |
|---|---|---|
| `properties` | `string[]` | Tags that define how the agent can interact with this object. Always contains `"sensor"`. May also contain `"movable"` (user can reposition it in VR). |
| `attachTo` | `string` | Name of the parent `ObjectDescriber` in the Unity scene hierarchy. Indicates which physical object the sensor is mounted on. |
| `sensor` | `object` | Sensor-type-specific data. Always contains `sensorType`. See per-type schemas below. |

#### DISTANCE sensor

```json
"DISTANCE-01": {
    "position":   [1.0, 1.2, 0.5],
    "size":       [0.08, 0.08, 0.08],
    "rotation":   [0, 0, 0],
    "scale":      [1, 1, 1],
    "properties": ["sensor", "movable"],
    "attachTo":   "Wall_A",
    "sensor": {
        "sensorType":        "DISTANCE",
        "showVisualization": false,
        "showDataGraph":     false,
        "validDistance":     5.0,
        "value":             1.23,
        "lookRay":           [0.0, 0.0, 1.0],
        "startPoint":        [1.0, 1.2, 0.5]
    }
}
```

`value` — current raycast distance in metres (0 → `validDistance`).  
`lookRay` — normalised world-space direction vector of the ray.  
`startPoint` — world-space origin of the ray.

#### OPTICAL sensor (`VirtualLightSensor`)

```json
"OPTICAL-01": {
    "position":   [0.2, 0.9, 3.1],
    "size":       [0.06, 0.06, 0.06],
    "rotation":   [0, 0, 0],
    "scale":      [1, 1, 1],
    "properties": ["sensor", "movable"],
    "attachTo":   "Door_A",
    "sensor": {
        "sensorType":        "OPTICAL",
        "showVisualization": false,
        "showDataGraph":     false,
        "value":             0.72
    }
}
```

`value` — normalised light intensity in range [0, 1] (0 = dark, 1 = at or above `maxIntensity`).

#### IMU sensor (`VirtualIMUSensor`)

```json
"IMU-01": {
    "position":   [0.1, 1.0, 0.0],
    "size":       [0.05, 0.05, 0.05],
    "rotation":   [12.3, 0.0, 4.5],
    "scale":      [1, 1, 1],
    "properties": ["sensor", "movable"],
    "attachTo":   "Wrist_L",
    "sensor": {
        "sensorType":        "IMU",
        "showVisualization": false,
        "showDataGraph":     false
    }
}
```

IMU does not expose a scalar `value` in the snapshot because it produces a time-series stream
(`orientation`, `acceleration`, `localAcceleration`, `location`).  
Streaming data is consumed separately; only metadata is present in scene snapshots.

---

## `properties` Tag Reference

| Tag | Source | Meaning |
|---|---|---|
| `"with_state"` | `ObjectDescriber` | Object implements `IStateHolder`; has `state` and `availableStates` fields. |
| `"movable"` | `ObjectDescriber` (flag) / `SensorObjectDescriber` (always) | Agent may issue `set_transform` actions to reposition this object. |
| `"sensor"` | `SensorObjectDescriber` (always) | Object is a virtual sensor; has `sensor` and `attachTo` fields. |

---

## Resolved Items

### ✅ 1. Sensor `scene_snapshot` Format — Keep Unity Nested Structure

**Decision**: The Unity nested format (`"sensor": { ... }`) is kept **as-is**.  
The Python backend (`_compact_scene`, `SceneFilter._object_description`) has been updated in Phase 2 to correctly read `obj["sensor"]["sensorType"]` and `obj["sensor"]["value"]` from the nested key.

> **No change required on the Unity side.**

### ✅ 2. `size` vs `scale`

Both fields are kept. `size` is the world-space bounding-box extent (from `BoxColliderData`); `scale` is the lossy transform scale. The Python relevance filter uses neither for scoring — it uses `state`, `sensor.sensorType`, `sensor.value`, and `attachTo` — so the duplication is harmless and both fields remain available for future use.

### ✅ 3. Interrupt Button — Send/Stop Toggle

The existing send button now acts as a dual-purpose control:
- **Agent idle** → button reads **"OK"**, `onClick` → `SendTextMessage()` (previous behaviour)
- **Agent busy** → button reads **"Stop"**, `onClick` → `WsClient.SendAgentInterrupt()` (hard stop)

`ChatUIManager` subscribes to `WsClient.OnAgentStatus`; `HandleAgentStatusUI()` updates `_agentIsIdle` and calls `UpdateSendButtonLabel()` on every state push. The button label is a `TMP_Text` child resolved via `GetComponentInChildren<TMP_Text>()`.

> No separate "Cancel Plan" (soft interrupt) button yet — deferred to a future phase.

### ✅ 4. Agent-Status HUD Text

A `TMP_Text agentStatusText` field (Inspector-assignable) has been added to `ChatUIManager`.  
Wire it in the Unity Editor to a `TextMeshProUGUI` component at the top of the chat UI panel.  
The displayed strings are:

| Python state | Displayed text |
|---|---|
| `idle` | *(empty)* |
| `listening` | 🎤 Listening... |
| `transcribing` | ✍️ Transcribing... |
| `thinking` | 💭 Thinking... |
| `planning` | 📋 Planning... |
| `executing` | ⚙️ Executing... |
| `speaking` | 🔊 Speaking... |
| `waiting` | ⏳ Waiting... |
| `scripting` | 📝 Scripting... |

---

## Open Items

### 5. `listening` and `waiting` States Produce No Visual Change

`HandleAgentStatus` (in `AgentBehaviorController`) leaves the pupil animation unchanged for `listening` and `waiting` states.  
Decision needed:
- `listening` — agent is waiting for voice input. A pulsing mic icon or "listening…" overlay may be more appropriate.
- `waiting` — agent is pausing between plan steps. Could keep the thinking animation, or introduce a distinct subtle pulse.

---

### 6. Full Memory Wipe Has No Unity API (Pending Python)

`{"type": "reset"}` only clears LLM conversation history; the LanceDB episodic store under `VsensPython/data/memory/episodes/` is **not** cleared.  
A `reset_memory` message type is planned for a future phase.  
Until then, operators must manually delete `VsensPython/data/memory/episodes/` and restart the server.

---

### 7. `memory_ready` Status — Reserved, No Action Needed

`memory_ready` is a future `agent_status.state` that the Python side will emit once LanceDB has finished initialising (i.e., the local vector database is ready).  
The Python side does **not** emit it yet (confirmed Phase 2 notes §4).  
Unity's `HandleAgentStatus` default case silently ignores it — no change needed now; revisit when Python adds the emission.
