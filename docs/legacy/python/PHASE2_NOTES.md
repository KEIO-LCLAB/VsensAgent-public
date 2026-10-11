# Phase 2 — Unity-Side Changes Required

> Historical phase note. Preserved for implementation history, not current runtime onboarding.

**Date**: March 1, 2026  
**Phase**: 2 — Memory (LanceDB Episodic + Scene Relevance Filtering)  
**Status**: Python backend complete — Unity integration actions below

---

## Summary

Phase 2 introduces episodic memory (persisted to disk via LanceDB) and scene
relevance filtering (per-query selective scene injection).  From Unity's
perspective the WebSocket **message format is unchanged**, but there are a few
things Unity should do to get the best out of the new capabilities.

---

## 1. No Breaking Changes

Phase 2 is **fully backward-compatible** with Phase 1 Unity code.

- Existing `text_chat`, `transcribe_and_reply`, `reset`, `agent_interrupt`,
  and `plan_interrupt` message types are unchanged.
- The `agent_ready` response schema is unchanged.
- `agent_status` broadcasts continue to fire on every state transition.

---

## 2. Send Richer `scene_snapshot` Payloads

The Python backend now passes scene snapshots through a **relevance filter**
before injecting them into the LLM prompt.  The filter works best when each
object in `scene_snapshot` exposes **all** of its readable fields, not just
a subset.

### Recommended object shape

Regular objects:

```json
"Window_A": {
    "state":           "open",
    "availableStates": ["open", "closed"],
    "position":        [3.4, 1.9, 7.5],
    "rotation":        [0, 90, 0],
    "scale":           [1, 1, 1],
    "size":            [1.2, 1.0, 0.1],
    "properties":      ["with_state", "movable"]
}
```

Sensor objects — keep the Unity nested `sensor` sub-key format:

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

```json
"OPTICAL-01": {
    "position":   [0.2, 0.9, 3.1],
    "properties": ["sensor", "movable"],
    "attachTo":   "Door_A",
    "sensor": {
        "sensorType": "OPTICAL",
        "value":      0.72
    }
}
```

```json
"IMU-01": {
    "position":   [0.1, 1.0, 0.0],
    "properties": ["sensor", "movable"],
    "attachTo":   "Wrist_L",
    "sensor": {
        "sensorType": "IMU"
    }
}
```

The Python `_compact_scene` and `SceneFilter` read sensor data from `obj["sensor"]["sensorType"]`
and `obj["sensor"]["value"]` — the nested structure is handled natively.

---

## 3. Send `scene_snapshot` as a JSON Object, Not a String

**Root cause of known bug**: If Unity serialises the full WebSocket payload
with `JsonUtility.ToJson` (or similar) and `scene_snapshot` is itself a
pre-serialised string, the server receives:

```json
{ "type": "text_chat", "message": "Hello", "scene_snapshot": "{\"Window_A\":{...}}" }
```

Notice `scene_snapshot` is a **string**, not an **object**.  This causes
`ValueError: dictionary update sequence element #0 has length 1; 2 is required`
on the Python side.

**Fix**: ensure `scene_snapshot` is a nested JSON object in the payload:

```json
{ "type": "text_chat", "message": "Hello", "scene_snapshot": { "Window_A": { ... } } }
```

The Python backend now detects and auto-corrects this (logs a warning), but
the Unity sender should be fixed to avoid the overhead of double-parsing.

---

## 4. Include `scene_snapshot` on Every Message

For memory retrieval and scene filtering to work correctly, include the **full
current scene snapshot** on every `text_chat` and `transcribe_and_reply`
message, not just on the first one.

```json
{
  "type": "text_chat",
  "message": "Which sensor is closest to the window?",
  "scene_snapshot": { ... }
}
```

This is already recommended from Phase 1; Phase 2 makes it more important
because the episodic store records the scene at interaction time.

---

## 5. Handle the New `memory_ready` Status (Optional)

When the server starts it now initialises LanceDB.  This is fast (< 1 s on
first run, instant on subsequent runs), so no spinner is strictly required.
However, if you display a loading indicator, you may add `"memory_ready"` as
a known `agent_status.state` value to dismiss it.

_The Python side does not currently emit `memory_ready`; this is a reserved
name for a future enhancement._

---

## 6. `reset` Clears Working Memory — Episodic Memory Persists

Sending `{"type": "reset"}` clears the LLM conversation history and the
in-process scene snapshot.  It does **not** wipe the LanceDB episodic store.

- If you want a full memory wipe (e.g. for a new subject or new session),
  the simplest approach is to delete the `VsensPython/data/memory/episodes/`
  directory on the Python side and restart the server.
- A `reset_memory` message type may be added in a future phase.

---

## 7. Episodic Memory Storage Location

Episodes are stored under:

```
VsensPython/data/memory/episodes/
```

This directory is created automatically on first use.  Back it up or
version-control it if you want persistent memory across machines.

---

## 8. Token Cost Expectations

| Scenario                          | Expected change vs Phase 1 |
|-----------------------------------|-----------------------------|
| First interaction (cold start)    | +0–5 % (embedding overhead) |
| Focused query in a large scene    | −20–60 % prompt tokens      |
| Broad query referencing many objects | ≈ same as Phase 1         |
| Second+ interaction (warm cache)  | Small embedding saving (diff only) |

The relevance filter defaults to **top 15 objects** per query.  If your
scenes are typically small (< 20 objects) the filter is a no-op, which is
intentional.

---

## 9. No New Unity Package Dependencies

Phase 2 has no new requirements on the Unity side.  All embedding, storage,
and retrieval logic lives entirely within the Python backend.
