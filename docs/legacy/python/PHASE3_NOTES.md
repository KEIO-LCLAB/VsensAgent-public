# Phase 3 — Heartbeat / Proactive Perception: Complete Notes

> Historical phase note. Preserved for implementation history, not current runtime onboarding.

**Date**: March 2, 2026
**Python status**: ✅ Implemented — all 28 unit tests passing.
**Scope**: Python implementation details, protocol specification, and Unity
integration requirements for Phase 3.

---

## Configuration File (Python)

All Phase 3 tunables live in **`VsensPython/config/perception.yaml`**.
Edit and restart the Python server to apply. No code changes needed.

| Key | Default | Effect |
|---|---|---|
| `heartbeat.interval_s` | `5.0` | Broadcast to Unity via `server_config` on connect |
| `diff.continuous_abs_threshold` | `0.10` | Ignores continuous sensor noise below this absolute delta |
| `diff.continuous_rel_threshold` | `0.20` | Ignores continuous sensor noise below this relative delta |
| `attention.threshold` | `0.5` | Minimum event severity to wake the LLM |
| `cooldown.per_object_s` | `10.0` | Seconds between LLM wakeups for the same object |
| `cooldown.enabled` | `true` | Toggle per-object cooldown |
| `agent_push.tts_enabled` | `false` | `true` = Python OpenAI TTS; `false` = Unity-side TTS |
| `agent_push.tts_voice` | `alloy` | OpenAI TTS voice (when `tts_enabled: true`) |

---

## Protocol Messages

Phase 3 introduces **three new WebSocket message types**:

| Direction | Type | Description |
|---|---|---|
| Python → Unity | `server_config` | Sent immediately on every new connection; carries heartbeat interval & push mode |
| Unity → Python | `scene_heartbeat` | Periodic full-scene snapshot; interval set by `server_config.heartbeat_interval_s` |
| Python → Unity | `agent_push` | Proactive agent message triggered by a significant scene event |

The existing `agent_status` message is reused during heartbeat-triggered LLM
calls (`thinking` → `idle`) — `AgentBehaviorController` needs no changes.

---

## 0. `server_config` — Sent on Connect ✅ IMPLEMENTED

Python sends `server_config` **immediately** on every new WebSocket connection
so Unity can dynamically set its heartbeat interval and know whether
`agent_push` will include `audio_path`.

### Message shape

```json
{
  "type":                 "server_config",
  "heartbeat_interval_s": 5.0,
  "tts_in_push":          false,
  "attention_threshold":  0.5
}
```

### Unity implementation required

**`Messages.cs`**

```csharp
[Serializable]
public class ServerConfigMessage
{
    public string type;
    public float  heartbeat_interval_s;
    public bool   tts_in_push;
    public float  attention_threshold;
}
```

**`WsClient.cs`**

```csharp
public static event Action<ServerConfigMessage> OnServerConfig;

case "server_config":
    var sc = JsonUtility.FromJson<ServerConfigMessage>(raw);
    OnServerConfig?.Invoke(sc);
    break;
```

In the heartbeat manager, subscribe to `OnServerConfig` and start or restart
the heartbeat coroutine with the received interval:

```csharp
private bool _ttsInPush = false;

WsClient.OnServerConfig += cfg => {
    if (_heartbeatCoroutine != null) StopCoroutine(_heartbeatCoroutine);
    _heartbeatCoroutine = StartCoroutine(HeartbeatLoop(cfg.heartbeat_interval_s));
    _ttsInPush = cfg.tts_in_push;
};
```

---

## 1. `scene_heartbeat` (Unity → Python) ✅ DECIDED: Unity pushes on timer

**Design decision**: Unity pushes snapshots on a fixed timer. Python purely
reacts. Python does **not** poll or request snapshots.

Rationale: Unity controls the cadence — frame spikes simply miss one tick with
no dangling request. Python stays stateless about scene timing. Works correctly
even when round-trip latency exceeds the interval.

### Message shape

```json
{
  "type": "scene_heartbeat",
  "scene_snapshot": {
    "Window_A":   { "position": [...], "state": "open", "properties": ["with_state"] },
    "OPTICAL-01": { "properties": ["sensor"], "sensor": { "sensorType": "OPTICAL", "value": 0 } },
    "user":       { "position": [1.2, 1.7, 3.4], "properties": [] }
  }
}
```

The `scene_snapshot` content is identical to the one sent in
`transcribe_and_reply` / `text_chat` — reuse the existing `SceneSnapshot`
serialisation.

> **⚠ Critical**: Python sends **no reply** to no-op heartbeats.
> Use **fire-and-forget** `Send()`. Never use `await SendAndReceive()` for
> heartbeats. `agent_push` arrives asynchronously on the same receive loop.

### Unity implementation required

- Implement `SendHeartbeat()` as fire-and-forget (no await, no timeout).
- Start `HeartbeatLoop(interval)` coroutine; initial interval from
  `server_config.heartbeat_interval_s`. **Do not hard-code the interval in C#.**

---

## 2. Heartbeat Frequency ✅ DECIDED: 5 s default, configurable

**Default: 5 seconds.** Start loose; tighten once round-trip latency and
bandwidth are characterised on the actual Quest / Wi-Fi setup.

Heartbeats do **not necessarily trigger agent action** — the vast majority
are no-ops where Python detects no significant changes and sends nothing back.
The LLM is only woken when a diff event crosses `attention.threshold` (0.5).

### Adaptive backoff during `thinking` (recommended)

While the LLM is processing a heartbeat-triggered event, Python broadcasts
`agent_status: thinking`. Unity can use this to skip heartbeats while the
agent is busy, reducing unnecessary bandwidth:

```csharp
IEnumerator HeartbeatLoop(float interval)
{
    while (true)
    {
        yield return new WaitForSeconds(interval);
        // Skip when agent is busy or the user is speaking
        if (agentState == "listening"    ||
            agentState == "transcribing" ||
            agentState == "thinking")    continue;
        WsClient.Send(BuildHeartbeatMessage());
    }
}
```

This is **optional but recommended** — Python handles extra heartbeats
correctly (they return `None` in microseconds via the attention gate), so this
is a pure bandwidth optimisation, not a correctness requirement.

---

## 3. Delta Snapshot ✅ DECIDED: Python-side

**Unity always sends the full snapshot. Python handles all delta logic
internally** via `SceneDiff.compute_diff(old, new)`.

`WorkingMemory.update_scene()` merges partial snapshots if Unity ever moves to
partial in the future, but full is the default and simpler.

> **No change required on the Unity side.**

---

## 4. `agent_push` — Unity Implementation Required

Python can now push proactive messages to **all connected clients** at any time.

### Message shape — TTS disabled (default)

```json
{
  "type":         "agent_push",
  "trigger":      "SENSOR_TRIGGER",
  "reply":        "I detected presence near the entrance.",
  "triggered_by": ["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"],
  "control":      { "actions": [ ... ] }
}
```

### Message shape — TTS enabled (`tts_enabled: true` in perception.yaml)

```json
{
  "type":         "agent_push",
  "trigger":      "SENSOR_TRIGGER",
  "reply":        "I detected presence near the entrance.",
  "triggered_by": ["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"],
  "audio_path":   "/path/to/push_audio_20260302_120000.mp3",
  "control":      { "actions": [ ... ] }
}
```

`audio_path` is **only present** when `server_config.tts_in_push` was `true`.
Always null-check: `if (!string.IsNullOrEmpty(push.audio_path))`.

| Field | Notes |
|---|---|
| `type` | `"agent_push"` |
| `trigger` | `SENSOR_TRIGGER`, `SENSOR_ANOMALY`, `STATE_CHANGE`, `OBJECT_ADDED`, `OBJECT_REMOVED` |
| `reply` | Agent text. Never empty — Python suppresses the push if the LLM returned nothing. |
| `triggered_by` | Pre-formatted list of events that crossed the threshold, e.g. `["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"]`. For debug / HUD display. |
| `audio_path` | Present only when `tts_in_push=true`. Same format as `agent_ready.audio_path`. |
| `control.actions` | Zero or more control actions — same schema as `agent_ready.control.actions`. |

### Unity implementation required

**`Messages.cs`**

```csharp
[Serializable]
public class AgentPushMessage
{
    public string         type;
    public string         trigger;
    public string         reply;
    public string         audio_path;   // null / "" when TTS disabled
    [JsonProperty("triggered_by")]
    public string[]       triggered_by; // e.g. ["SENSOR_TRIGGER:OPTICAL-01 (severity 0.8)"]
    public ControlPayload control;
}
```

**`WsClient.cs`**

```csharp
public static event Action<AgentPushMessage> OnAgentPush;

case "agent_push":
    var push = JsonUtility.FromJson<AgentPushMessage>(raw);
    OnAgentPush?.Invoke(push);
    break;
```

**Chat / interaction controller**

```csharp
WsClient.OnAgentPush += push => {
    if (_ttsInPush && !string.IsNullOrEmpty(push.audio_path))
        AudioPlayer.Play(push.audio_path);     // Python pre-generated audio
    else
        UnityTTS.Speak(push.reply);            // Unity-side TTS fallback

    SceneController.ExecuteActions(push.control.actions);
    chatUI.AppendAgentMessage(push.reply);
    // ⚠ Do NOT send an extra heartbeat here — see Section 11.
};
```

---

## 5. User Position in `scene_snapshot` — Required for Proximity Detection

`USER_PROXIMITY` events fire when the user moves more than **0.5 m** in a
single heartbeat interval (configurable via `diff.user_proximity_threshold_m`).

**Requirement**: Every `scene_heartbeat` snapshot must include:

```json
"user": {
  "position": [1.24, 1.70, 3.41],
  "properties": []
}
```

`position` = camera (head-tracked) world-space position in metres, Y-up.

If the `"user"` key is absent, `USER_PROXIMITY` events silently never fire.

> **Action needed from Unity**: Confirm whether the existing `SceneSnapshot`
> builder includes `Main Camera` world position. If not, add it.

---

## 6. No Reply Sent for No-Op Heartbeats

Python sends **nothing back** for the vast majority of heartbeats.

- Do **not** use `await SendAndReceive(heartbeat)` — it will hang.
- Use fire-and-forget `Send(heartbeat)` — no callback, no timeout.
- `agent_push` arrives asynchronously on the existing receive loop, the same
  channel as `agent_status`. No polling required.

---

## 7. `agent_status` During Heartbeat-Triggered LLM Calls

When a significant scene event wakes the LLM, Python broadcasts:

```
agent_status: thinking  (detail: "Reacting to scene event")
...
agent_status: idle
```

`AgentBehaviorController` already handles these — no Unity changes needed.

> **Concurrency note**: If the user sends a voice message while the agent is
> responding to a heartbeat event, both paths run concurrently. The heartbeat
> LLM call is **not cancellable** via `agent_interrupt` (intentional — calls
> are short, ≤ 1 s). Revisit if this causes UX issues.

---

## 8. Heartbeat Pausing During Voice Recording ⚠ ACTION REQUIRED

Guard the heartbeat sender to prevent overlapping audio while the user speaks.
For the full recommended guard including `thinking` backoff, see Section 2.

Minimum required guard:

```csharp
if (agentState == "listening" || agentState == "transcribing") continue;
```

Subscribe to `WsClient.OnAgentStatus` to keep `agentState` updated.

---

## 9. `agent_push` TTS ✅ DECIDED: configurable

Both modes are implemented. Controlled by `config/perception.yaml` →
`agent_push.tts_enabled`. Unity detects the active mode from
`server_config.tts_in_push`.

| `tts_enabled` | Behaviour |
|---|---|
| `false` (default) | `agent_push` is text only. Unity provides its own TTS (Meta Voice SDK, Azure, etc.). |
| `true` | Python generates audio via OpenAI TTS, adds `audio_path` to the push. |

To switch mode: edit `config/perception.yaml` and restart the server.
No Unity rebuild required.

---

## 10. Duplicate `agent_push` Prevention ✅ DECIDED: Python cooldown

**Decision: Python-side per-object cooldown (implemented).**

```yaml
# config/perception.yaml
cooldown:
  enabled: true
  per_object_s: 10.0
```

If `OPTICAL-01` flickers 0→1→0→1 every 500 ms, only the first trigger fires
within the 10 s window. Tune `per_object_s` to adjust sensitivity.

> **No Unity-side changes required.** See Section 11 for loop-prevention rules
> Unity must preserve.

---

## 11. Agent-Action Feedback Loop — Handled by Python; Unity Rules

When the agent issues `control.actions` (e.g. `set_sensor`, `set_state`),
Unity executes them, changing the scene. The **next heartbeat** includes those
changes as `OBJECT_ADDED` or `STATE_CHANGE` diffs — which would normally
re-wake the LLM, creating an infinite loop.

**Python's fix**: `HeartbeatHandler._agent_touched` table. Every target object
in an outgoing `agent_push.control.actions` is recorded with expiry
`now + cooldown.per_object_s` (default 10 s). Events on those objects are
dropped before the attention gate — the LLM never sees changes it caused.

**No Unity-side code change required.** Three rules must not be violated:

- **Always execute all `control.actions` normally.** Python already recorded
  the targets. Skipping execution desynchronises the scene.
- **Never send an extra heartbeat after `ExecuteActions`.** Stay on the timer.
  Extra heartbeats consume the cooldown budget before a genuine external event
  can fire.
- **Never implement event-driven heartbeats** (e.g. fire on `SceneChanged`).
  If such a heartbeat fires after the 10 s suppression window, an
  agent-originated change looks "foreign" and re-triggers the LLM.
  Timer-only heartbeats are safe: the window always covers ≥ 2 heartbeat
  periods at default settings (5 s interval, 10 s window).

> **Rule of thumb**: timer-driven heartbeats + unconditional `ExecuteActions`
> = no loop.

---

## 12. `agent_push` During Ongoing `text_chat` / `transcribe_and_reply`

A heartbeat can fire while a user-initiated interaction is in flight.
Unity may receive messages in this order:

1. `agent_status: thinking` — from voice call
2. `agent_push: { ... }` — from heartbeat LLM, concurrent
3. `agent_ready: { ... }` — voice call completed

Unity audio playback must queue or prioritise these. Open item — see Section D
in the Open Items table.

---

## 13. `scene_heartbeat` on the Same Connection

All messages (server_config, heartbeats, chat, interrupts, pushes) travel over
**one WebSocket connection**. Do not open a second socket for heartbeats.
Python uses `asyncio` cooperative multitasking — concurrent access is safe.

---

## Open Items

### Carried over from Phase 1 & 2

| # | Item | Status |
|---|---|---|
| 3 | Interrupt buttons not wired to UI | Still open |
| 4 | Agent-status HUD text not implemented | Still open |
| 5 | `listening` / `waiting` states produce no visual change | Still open |
| 6 | Full memory wipe has no Unity API | Still open |
| 7 | `memory_ready` status reserved but not emitted | Still open |

### Phase 3

| | Item | Owner | Status |
|---|---|---|---|
| A | `scene_snapshot` double-serialisation — Unity sends JSON string inside JSON; Python `_coerce_snapshot()` handles unwrap in `WorkingMemory`, but `heartbeat_handler.handle()` was calling `compute_diff` **before** coercion. On first heartbeat: every character of the raw string became an `OBJECT_ADDED` event. On second+ heartbeat: `compute_diff` called `.keys()` on a string → `AttributeError` → WS `1011 internal error` → Unity reconnect loop every 5 s. **Fixed (2026-03-03)**: coercion now happens at the top of `handle()` before any diff. | Python | **✅ Fixed** |
| A2 | `perception.yaml` fails to load on Windows — `path.read_text()` defaults to GBK encoding; YAML has UTF-8 box-drawing chars (`─`) in comments → `'gbk' codec can't decode byte 0x80` → all thresholds fall back to defaults silently. **Fixed (2026-03-03)**: `read_text(encoding="utf-8")`. | Python | **✅ Fixed** |
| B | Include `Main Camera` world-pos in `SceneSnapshot` builder | Unity | **✅ Resolved (2026-03-03)** — `RoomDescriber.cs` now has an optional `userCamera` field (falls back to `Camera.main`); appends `"user": {"position": [x,y,z], "properties": []}` to every snapshot. |
| C | Heartbeat LLM call interruptibility — currently NOT cancellable by `agent_interrupt` | Both | Open — acceptable for now? |
| D | Audio playback queue priority when `agent_push` arrives mid-voice-call | Unity | Open |

---

## Quick-Start Checklist for Unity (Phase 3)

```
✅ Add ServerConfigMessage to Messages.cs
✅ Handle "server_config" in WsClient.cs; fire OnServerConfig event
✅ Wire OnServerConfig → start/restart heartbeat coroutine with heartbeat_interval_s
✅ Wire OnServerConfig → store _ttsInPush flag
✅ Add AgentPushMessage to Messages.cs (fields: trigger, reply, audio_path, triggered_by, control)
✅ Handle "agent_push" in WsClient.cs; fire OnAgentPush event
✅ Wire OnAgentPush → conditional TTS/audio + SceneController.ExecuteActions
✅ Implement SendHeartbeat() fire-and-forget (no await)
✅ Guard heartbeat: skip while agentState is "listening" or "transcribing"
✅ (Recommended) Also skip while agentState is "thinking" — see Section 2
✅ Include "user": { "position": [...] } in every scene_snapshot (RoomDescriber.cs — 2026-03-03)
✅ Heartbeat is timer-driven ONLY — never fire on scene mutation events
✅ double-serialised scene_snapshot — accepted as Unity convention; handle() now coerces before compute_diff (bug fixed 2026-03-03)
□ Test: 5 s static scene → no WS traffic back from Python
□ Test: OPTICAL value change → agent_push.reply received within ~5 s
□ Test: agent_push with control.actions → no follow-up LLM push on same object within 10 s
```

