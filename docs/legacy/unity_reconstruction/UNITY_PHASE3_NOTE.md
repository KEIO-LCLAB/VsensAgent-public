# Phase 3 — Unity Integration Notes (Heartbeat / Proactive Perception)

**Date**: March 3, 2026  
**Scope**: Unity-side implementation of scene heartbeat + proactive `agent_push` reception.

---

## Changes Applied (Unity Side)

| File | What changed |
|---|---|
| `Core/Constants.cs` | Added `Constants.Heartbeat.HEARTBEAT_INTERVAL = 1.0f` |
| `Network/Protocol/Requests.cs` | Added `HeartbeatRequest` — outbound `scene_heartbeat` message |
| `Network/Protocol/Messages.cs` | Added `AgentPushMessage` (fields: `trigger`, `reply`, `audio_path`, `triggered_by`, `control`), `ServerConfigMessage` |
| `Network/WsClient.cs` | Added `OnAgentPush`, `OnServerConfig` events; handles `"agent_push"` and `"server_config"` message types; added `SendHeartbeat(string)` static method |
| `Network/HeartbeatManager.cs` | **New MonoBehaviour** — sends `scene_heartbeat` on a coroutine timer; subscribes to `OnServerConfig` to apply server-mandated interval; subscribes to `OnAgentStatus` for `pauseWhenAgentBusy` support |
| `UI/Chat/ChatUIManager.cs` | Subscribes/unsubscribes `OnAgentPush`; `OnAgentPushReceived` displays push reply prefixed with `🔔` as an agent chat bubble; passes `audio_path` to `AddAgentMessage` |
| `VirtualObject/RoomDescriber.cs` | Added optional `userCamera` field (falls back to `Camera.main`); appends `"user": {"position": [x,y,z], "properties": []}` to every scene snapshot |

---

## Protocol Additions

### Outbound: `scene_heartbeat`

Sent by `HeartbeatManager` at `heartbeat_interval_s` (default 1.0 s, overridden by server_config).

```json
{
    "type": "scene_heartbeat",
    "scene_snapshot": "<JSON-string of RoomDescriber.GetRoomDescription()>"
}
```

> `scene_snapshot` is a **JSON-serialised string** (same convention as `text_chat` and `transcribe_and_reply`).  
> Python's `WorkingMemory.update_scene()` already handles the `json.loads()` unwrap transparently.

---

### Inbound: `server_config`

Sent by Python **immediately after every new WebSocket connection** (no request needed).

```json
{
    "type": "server_config",
    "heartbeat_interval_s": 1.0,
    "tts_in_push": false,
    "attention_threshold": 0.5
}
```

Unity actions on receipt (implemented in `HeartbeatManager.HandleServerConfig`):
- Overrides `heartbeatInterval` if server value differs from local default.
- Restarts the heartbeat coroutine so the new interval takes effect immediately.

`tts_in_push` and `attention_threshold` are logged but not acted upon yet — see Open Items §1 and §2.

---

### Inbound: `agent_push`

Sent by Python's `HeartbeatHandler` only when a classified event reaches `severity >= 0.5`.

```json
{
    "type":         "agent_push",
    "trigger":      "SENSOR_TRIGGER",
    "reply":        "I noticed OPTICAL-01 just triggered — the door appears to have opened.",
    "triggered_by": ["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"],
    "control": {
        "actions": [
            { "target": "OPTICAL-01", "action": "highlight", "parameters": { "color": "yellow" } }
        ]
    }
}
```

Unity actions on receipt:
1. `WsClient.OnAgentPush` is fired → `ChatUIManager.OnAgentPushReceived` displays `"🔔 <reply>"` in chat.
2. If `control.actions` is non-empty → `WsClient.OnControl` is fired → `ControlManager` executes the actions (same pipeline as `agent_ready`).

> `agent_push` does **not** trigger `StartThinking()` / `StopThinking()` — the Agent's `agent_status` transitions (thinking → idle) are broadcast separately.

---

## Unity Editor Setup

1. **Add `HeartbeatManager`** to the same GameObject as `WsClient` (or any active GameObject that lives through the session).
2. No additional Inspector wiring is required — `HeartbeatManager` resolves the scene via `WsClient.GetCurrentSceneDescription()`.
3. Recommended initial settings (Inspector):
   - `Heartbeat Interval`: `1` (overridden by `server_config` at runtime)
   - `Enable Heartbeat`: ✅ checked
   - `Pause When Agent Busy`: ✅ checked (default `true` — see Resolved Item §4)

---

## Resolved Items

### ✅ 1. `scene_snapshot` Field Type — String (not embedded dict)

`HeartbeatRequest.scene_snapshot` is a `string`, consistent with `TextChatRequest` and `TranscribeRequest`.  
`WorkingMemory.update_scene()` already calls `json.loads()` when the value arrives as a string, so **no change is needed on the Python side**.

### ✅ 2. Heartbeat Interval — Python is Authoritative

`HeartbeatManager` starts with a 1.0 s default and then immediately updates to `server_config.heartbeat_interval_s` on connect. Python's `perception_config` (loaded from config YAML) is the single source of truth.

### ✅ 3. `agent_push` Control Pipeline

`agent_push` control actions flow through the existing `OnControl → ControlManager` pipeline without any new code in `ControlManager`. This matches the `agent_ready` behaviour and requires no Python-side changes.

### ✅ 4. `pauseWhenAgentBusy` — Set to `true`

`HeartbeatManager.pauseWhenAgentBusy` defaults to `true`. Heartbeats are paused while the agent is busy (non-idle), reducing unnecessary SceneDiff / EventClassifier work on the Python side during LLM calls. Any scene changes that occur while the agent is busy will be captured on the next heartbeat after the agent returns to idle.

### ✅ 5. `scene_snapshot` double-serialisation — Accepted as protocol convention

Unity serialises `scene_snapshot` as a JSON string (consistent with `text_chat` and `transcribe_and_reply`).
Python's `_coerce_snapshot()` handles the `json.loads()` unwrap transparently.
**Decision (2026-03-03)**: accepted as the established protocol convention — no change on either side.

### ✅ 6. User position in `scene_snapshot` (2026-03-03)

`RoomDescriber.cs` now appends `"user": {"position": [x, y, z], "properties": []}` using `userCamera` (or `Camera.main` fallback). `USER_PROXIMITY` events will now fire on the Python side.

---

## Open Items (Decisions Needed)

### ✅ 1. TTS for `agent_push` — `audio_path` field added (2026-03-03)

`AgentPushMessage` now includes `audio_path` matching the confirmed schema:
- Present in the push only when `server_config.tts_in_push == true`.
- `ChatUIManager.OnAgentPushReceived` now calls `AddAgentMessage("🔔 " + push.reply, push.audio_path ?? "")`.

### ✅ 2. `triggered_by` Field Format — Python emits pre-formatted strings (2026-03-03)

Python's `HeartbeatHandler` now emits `triggered_by` as pre-formatted strings
(Option A): e.g. `["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"]`.
`AgentPushMessage.triggered_by` as `string[]` is correct. Currently used for Debug logging only.

---

### 3. `agent_push` During Quiet Scenes

If the scene is static for a long period, Python will receive many heartbeats with zero-diff and never send `agent_push`. No issue on the Unity side, but confirm Python's `HeartbeatHandler` correctly short-circuits (returns `None`) without accumulating memory.

---

### 4. UI Treatment for Proactive Push

Currently, `agent_push` appears in the chat window as a `🔔`-prefixed agent message.

Alternative options (decision deferred):
- **Floating toast notification** (appears briefly then disappears, non-intrusive)  
- **Dedicated "Alerts" tab** in the chat panel  
- **No chat bubble** — only TTS audio (if `tts_in_push = true`)

No changes required on the Python side; this is purely a Unity UI decision.

---

### 5. `attention_threshold` HUD

`server_config.attention_threshold` (default 0.5) is logged but not displayed.  
The debug tools guide (`SENSOR_DEBUG_TOOLS.md`) may want to expose this in the sensor monitor overlay so developers can see why certain heartbeats do or don't trigger a push.  
Defer to Phase 4/5 unless specifically requested.
