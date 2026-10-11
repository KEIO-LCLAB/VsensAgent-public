# Phase 1 — What Changed & How to Test with Unity

> Historical phase note. Preserved for implementation history, not current runtime onboarding.

> Historical note: this document describes the Phase 1 state on March 1, 2026.
> It is useful for implementation history, but it is not the current prompt architecture reference.
>
> Read these first for the current runtime:
> - [PROMPT_ARCHITECTURE.md](../../../VsensPython/docs/PROMPT_ARCHITECTURE.md)
> - [PATH_SETUP.md](../../../VsensPython/docs/PATH_SETUP.md)

**Date**: March 1, 2026  
**Status**: Complete — 27/27 tests passing

---

## What Changed

### New files

| File | Purpose |
|---|---|
| `core/__init__.py` | Package root |
| `core/memory/working_memory.py` | In-process scene state (replaces raw dict) |
| `core/skills/control_parser.py` | Parses `<control>` blocks cleanly |
| `core/skills/skill_registry.py` | Local skill dispatcher |
| `core/skills/scene_skills.py` | Registers set_state / set_transform / highlight / set_sensor |
| `core/agent_status.py` | `AgentStatusBroadcaster` — state push to Unity |
| `core/agent_core.py` | Central orchestrator (replaces `VsensInteractionManager`) |
| `test_phase1.py` | Phase 1 integration tests (can be deleted after you verify) |

### Modified files

| File | What changed |
|---|---|
| `vsens_server.py` | Replaced `VsensInteractionManager` with `AgentCore`; added `broadcast()`, task tracking, and two new message handlers |
| `data/prompts/system_prompt.txt` | Historical Phase 1 change. Current runtime prompt assembly is modular. |

`vsens_interactionManager.py` is **unchanged** and still exists but is no longer used by the server.

---

## New WebSocket Message Types

Unity can now send two new message types:

```json
{ "type": "agent_interrupt" }
```
Hard interrupt — cancels any in-flight LLM call, clears active plan, returns agent to idle.

```json
{ "type": "plan_interrupt" }
```
Soft interrupt — clears the active plan but lets the current LLM call finish.

Both return:
```json
{ "type": "interrupt_ack", "message": "Stopped." }
```

---

## New Server-to-Unity Push

The server now broadcasts `agent_status` messages **without Unity requesting them**.  
Your Unity WebSocket client needs to handle this message type:

```json
{
  "type": "agent_status",
  "state": "thinking",
  "detail": ""
}
```

**States**: `idle` | `listening` | `transcribing` | `thinking` | `planning` | `executing` | `speaking` | `waiting` | `scripting`

### What Unity should do
- Ignore unknown message types gracefully (don't crash on `agent_status` if not yet implemented)
- Optionally render the state as a HUD indicator

---

## Changed Response Shape

The `control` field in `agent_ready` responses is now always a dict with an `actions` list:

```json
{
  "type": "agent_ready",
  "control": {
    "actions": [
      { "target": "Window_A", "action": "set_state", "parameters": { "state": "open" } }
    ]
  }
}
```

**Previously** the `control` field could be `{"status": "no_control"}` or `{"status": "invalid_control_json", ...}` on edge cases.  
**Now** it is always `{"actions": [...]}` — empty list when there are no actions.

> Update your Unity `control` parser if it checks for `"status"` on the control object.

---

## How to Start the Server

Nothing changes:

```powershell
cd G:\LCLab\VsensAgent\VsensPython
conda activate vsens_plus
python main.py
```

---

## Verify Before Connecting Unity

```powershell
cd G:\LCLab\VsensAgent\VsensPython
conda run -n vsens_plus python test_phase1.py
```

Expected output: **27 passed, 0 failed**  
The three warning lines (`ControlParser`, `SkillRegistry`) are expected — they confirm the error-recovery paths work.
