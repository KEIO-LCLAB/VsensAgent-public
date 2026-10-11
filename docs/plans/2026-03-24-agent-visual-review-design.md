# Agent Visual Review Design

## Summary

This design replaces Unity-side screenshot heuristics as the primary avatar placement judge with a Python-led multimodal review pass.

This document supersedes the older 2026-03-23 Unity-side screenshot-scoring plan.

The core idea is:

1. Unity still captures validation screenshots after avatar placement and motion setup.
2. Python assembles a compact review packet with task context, candidate metadata, lightweight geometry summary, and screenshot paths.
3. A dedicated multimodal review pass decides only:
   - `accept`
   - `retry`
   - `issues`
   - `reason`
4. Python owns bounded retry over the candidate list.

This keeps screenshot judgment visible to the agent without letting the model invent new coordinates outside the validated candidate set.

## Goals

- Make screenshot review an actual control signal, not just an artifact.
- Move placement retry authority to Python/agent orchestration.
- Preserve deterministic candidate bounds by retrying only within the candidate list returned from Scene API.
- Keep the main conversation history clean by isolating screenshot review into a dedicated pass.

## Non-Goals

- No free-form model-generated replacement coordinates in v1.
- No removal of Unity capture support.
- No replacement of all geometry validation; basic geometry checks still gate obviously invalid poses before screenshot review.
- No general-purpose image understanding pipeline for unrelated tasks yet.

## Recommended Architecture

### Approach

Use a **separate multimodal visual review pass** rather than asking the main agent turn to inspect screenshots inline.

Why:

- It avoids polluting the main dialogue history with review-only prompts.
- It makes prompt tuning and failure handling much easier.
- It allows the visual reviewer to have a narrow contract and be tested independently.

### Runtime Split

#### Unity

Unity remains responsible for:

- candidate execution
- motion load/play
- validation screenshot capture
- returning artifact metadata

Unity no longer acts as the primary retry decision-maker for screenshot quality.

#### Python

Python becomes responsible for:

- sequencing avatar candidate attempts
- requesting screenshot capture after an attempt
- running a dedicated multimodal visual review pass
- deciding whether to accept or retry the next candidate
- returning a clean user-facing reply after the final accepted attempt

## Review Packet

The multimodal review pass should receive:

- task hint
- target alias or target object id
- candidate id
- avatar position
- avatar rotation
- motion name
- motion mode
- geometry summary
  - `distance_to_target`
  - `facing_score`
  - `collision_free`
  - `grounded`
- validation screenshots
  - `avatar_eye`
  - `user_camera`
  - later, optional trajectory frames if translational review expands

This provides enough context to judge whether the placement matches the task without asking the model to infer everything from pixels alone.

## Review Output Contract

The review pass should produce a narrow structure:

- `decision`: `accept | retry`
- `issues`: flat list of short machine-readable tags
- `reason`: one short explanation

Suggested issue tags:

- `too_far`
- `bad_facing`
- `embedded`
- `out_of_room`
- `target_not_visible`
- `awkward_framing`

The review pass must not output raw scene actions or new coordinates.

## Retry Policy

Python should own a bounded retry loop:

1. execute current candidate
2. capture screenshots
3. run multimodal review pass
4. if `accept`, finish
5. if `retry`, move to next candidate
6. if candidates exhausted, return structured failure

Recommended v1 limits:

- max 2 to 3 reviewed candidates
- stop at first accepted candidate
- no infinite retry

## OpenAI Integration

The current `VsensOpenAI` wrapper is text-only.

The design requires a new image-capable request path for the review pass. The simplest shape is:

- keep existing `send_message(...)` for text conversation
- add a new method dedicated to multimodal review requests
- keep it non-persistent by default so review prompts do not enter the normal conversation history

This review method should package:

- one system instruction specialized for screenshot judgment
- one compact user context payload
- screenshot references as image inputs

## Error Handling

If screenshot capture fails:

- Python should record a structured review failure
- retry should not silently continue forever
- fallback behavior should be explicit:
  - either accept the geometry-valid candidate without screenshot review
  - or fail the attempt and move to the next candidate

For v1, prefer:

- fail the review attempt
- move to the next candidate if available
- otherwise report a structured validation failure

## Testing Strategy

### Python

- review payload construction
- multimodal review output parsing
- retry loop behavior:
  - `retry` on first candidate, `accept` on second
  - stop on first `accept`
  - fail cleanly when all candidates are rejected

### Unity

- capture queries continue returning artifacts
- no regression in avatar validation/capture test coverage

### Manual

- `make coffee naturally`
- `open the fridge and walk in`

Success means:

- screenshots are captured
- visual review actually influences which candidate is accepted
- final user-facing reply does not expose internal review/control noise
