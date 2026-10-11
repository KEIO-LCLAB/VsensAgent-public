# Action API

## Method: `scene.validate_actions`
Validate an action batch against current scene state without mutation.

### Request
```json
{
  "request_id": "req_20260305_001",
  "scene_version": 102,
  "strict": true,
  "actions": [/* ActionCommand[] */]
}
```

### Response
```json
{
  "request_id": "req_20260305_001",
  "scene_version": 102,
  "ok": true,
  "errors": [],
  "normalized_actions": [/* normalized ActionCommand[] */]
}
```

## Method: `scene.execute_actions`
Execute a validated action batch.

### Request
Same as `scene.validate_actions`.

### Response
```json
{
  "request_id": "req_20260305_001",
  "status": "success",
  "failed_action_index": -1,
  "applied_actions": [0,1,2],
  "rollback_status": "not_needed",
  "scene_version_after": 103,
  "errors": []
}
```

## Validation Checklist
- `scene_version` matches current scene.
- target exists by `target_id`.
- action type supported by target capabilities.
- parameter schema/type correctness.
- spatial constraints for placement actions.
- preconditions satisfied.
