# Avatar Visual Retry Design

## Goal

Turn avatar validation screenshots from passive artifacts into an active retry signal for avatar placement tasks.

The first version should stay lightweight:

- Unity computes a visual score from scene geometry and validation cameras
- Python uses that score to accept the current candidate or retry the next one
- screenshots remain saved as artifacts for inspection

This design does not yet require a multimodal model. It prepares the runtime contract so a future image-aware agent can replace or augment the scoring step.

## Recommended Approach

Use a hybrid loop:

1. Python owns the deterministic orchestration for avatar placement tasks.
2. Unity owns capture and lightweight visual scoring.
3. Python retries a bounded number of candidate placements based on Unity's geometry and visual score.

This is preferred over immediately upgrading the OpenAI wrapper for image input because:

- it gives us a reliable retry loop sooner
- it keeps the scoring explainable and testable
- it avoids coupling placement correctness to model quality

## Runtime Flow

The avatar placement flow becomes:

1. `scene.query_avatar_candidates`
2. `scene.validate_avatar_placement`
3. execute `spawn_avatar` / `set_avatar_transform`
4. `load_avatar_motion` and `play_avatar_motion`
5. `scene.capture_validation_views`
6. `scene.score_validation_views`
7. if score fails, retry the next candidate
8. if score passes, accept the current setup

The first implementation should retry at most `2` additional candidates after the first attempt. If every candidate fails, the system should return a structured failure rather than continuing indefinitely.

## New Scene Query

Add a new read-only query:

- `scene.score_validation_views`

### Request shape

```json
{
  "request_id": "qry_visual_001",
  "validator_context": "validator_coffee",
  "avatar_id": "avatar_main",
  "target_object_id": "obj_coffee_01",
  "target_alias": "CoffeeMaker",
  "task_hint": "make_coffee",
  "max_views": 2
}
```

### Response shape

```json
{
  "type": "scene.query_response",
  "request_id": "qry_visual_001",
  "method": "scene.score_validation_views",
  "scene_version": 120,
  "passed": true,
  "score": 0.81,
  "recommended_action": "accept",
  "reasons": [],
  "metrics": {
    "target_visible": true,
    "avatar_visible": true,
    "target_occlusion_score": 0.92,
    "task_framing_score": 0.76
  },
  "artifacts": [
    {
      "artifact_id": "validator_coffee_overview_20260323_123000_001",
      "artifact_type": "image/png",
      "file_path": "<local-path> Support/DefaultCompany/Vsens/ValidationCaptures/validator_coffee_overview_20260323_123000_001.png"
    }
  ]
}
```

## Unity Scoring Rules

The first version should score only four checks:

1. `target_visible`
   - target bounds center or corners are inside the camera viewport and in front of the camera
2. `avatar_visible`
   - avatar renderer bounds are still in frame
3. `target_occlusion_score`
   - raycasts from the camera to a few target anchor points are not heavily blocked by unrelated geometry
4. `task_framing_score`
   - avatar and target both appear in frame with a reasonable relative layout for task execution

These checks are intentionally geometric and camera-based. They are not image-segmentation or semantic vision.

## Python Orchestration

Python should stop treating visual validation as prompt-only guidance and instead make it part of the hard runtime contract for avatar tasks.

When an avatar task contains:

- `spawn_avatar` or `set_avatar_transform`
- `load_avatar_motion`
- `play_avatar_motion`

the runtime should:

1. query candidate placements
2. validate geometry
3. execute the current candidate
4. request screenshot scoring
5. retry if Unity recommends `retry_next_candidate`

## Testing Strategy

### Unity

- add EditMode tests for `scene.score_validation_views`
- verify obvious bad framing returns `passed = false`
- verify normal framing returns `passed = true`
- keep current avatar capture tests green

### Python

- add agent/orchestration tests that:
  - retry when score fails
  - stop retrying when score passes
  - return a structured failure when all candidates are exhausted

## Limits

This design intentionally does not include:

- multimodal OpenAI image input
- pixel-level segmentation or semantic scene understanding
- unbounded search
- posture-quality judgments beyond simple visibility and framing proxies

Those can be layered in later once the runtime retry contract is proven.
