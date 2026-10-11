# Architectural Decisions

This file records significant design and architecture decisions for the VsensAgent
project, including the rationale and any alternatives considered. Each entry is
permanent — closed decisions stay for historical reference.

Ongoing open issues are tracked on GitHub:
https://github.com/Gullintani/VsensAgent/issues

---

## Decision Log

### D-001 · WebSocket framing protocol
**Date:** 2025  
**Status:** Accepted  
**Decision:** Use plain JSON frames over NativeWebSocket. Each message is a
top-level JSON object with a `type` field used as the discriminator.  
**Rationale:** Minimal overhead; Unity's NativeWebSocket already supports raw
text frames; no binary serialization needed at current data rates.  
**Alternatives considered:** MessagePack (rejected — adds a Unity plugin
dependency with no measurable benefit at this scale).

---

### D-002 · Sensor perception pipeline
**Date:** Phase 2  
**Status:** Accepted  
**Decision:** Scene-state diffs are computed server-side in Python. Unity sends
full `scene_heartbeat` snapshots; Python diffs against cached state and
decides whether to call the LLM.  
**Rationale:** Keeps Unity logic simple (no diff bookkeeping); Python is easier
to iterate on rapidly; Unity side becomes a thin data broadcaster.  
**Alternatives considered:** Unity-side diff (rejected — harder to unit-test
and would couple perception logic to the game engine).

---

### D-003 · Per-object LLM cooldown
**Date:** Phase 3  
**Status:** Accepted  
**Decision:** After an LLM call is triggered for a specific object, a 10-second
cooldown is applied **per object ID** to suppress duplicate pushes caused by
oscillating sensor values.  
**Rationale:** Prevents chatty agent responses for rapidly toggling states
(observed in Door_A test on 2026-03-03).  
**Open issue:** Potential early re-fire at ~9 s — see
[GitHub Issue #TBD](https://github.com/Gullintani/VsensAgent/issues) (Cooldown
early re-fire).

---

### D-004 · Heartbeat LLM interruptibility (OPEN)
**Date:** Phase 3  
**Status:** Deferred / Under discussion  
**Decision:** TBD — see GitHub Issue (Item C).  
**Options:**  
1. Cancel in-flight heartbeat LLM call when `agent_interrupt` arrives.  
2. Let heartbeat LLM call finish but discard the push if interrupt was received.  
3. Formally defer to a later phase; document as known limitation.  
**Notes:** Option 2 is likely safest; option 1 requires `asyncio.Task`
cancellation and careful state cleanup.

---

### D-005 · Audio queue priority on agent_push arrival (OPEN)
**Date:** Phase 3  
**Status:** Deferred / Under discussion  
**Decision:** TBD — see GitHub Issue (Item D).  
**Options:**  
1. Interrupt current audio immediately and play push audio.  
2. Queue push audio to play after current clip finishes.  
3. Drop push audio silently if voice is already playing.  
**Notes:** Option 2 (queue) is most user-friendly; option 1 is simplest to
implement; option 3 risks silent failure.

---

## Template

Copy and fill in for each new decision:

```
### D-XXX · <Short title>
**Date:** <YYYY-MM-DD or phase>  
**Status:** Accepted | Rejected | Deferred | Superseded by D-YYY  
**Decision:** <What was decided, one or two sentences.>  
**Rationale:** <Why this approach. What problem it solves.>  
**Alternatives considered:** <Other options and why they were not chosen.>  
**Notes / linked issues:** <Optional — GitHub issue #, PR, or follow-up.>
```
