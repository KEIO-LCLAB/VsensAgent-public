# Execution Report

## Schema
```json
{
  "request_id": "req_20260305_001",
  "status": "success|failed",
  "scene_version_before": 102,
  "scene_version_after": 103,
  "applied_actions": [0,1,2],
  "failed_action_index": -1,
  "rollback_status": "not_needed|success|partial_failure",
  "duration_ms": 24,
  "errors": [/* ErrorItem[] */],
  "diagnostics": {
    "trace_id": "trace_abcd1234",
    "notes": ["validated_with_spatial_engine"]
  }
}
```

## Conventions
- `failed_action_index = -1` when no failure.
- `scene_version_after = scene_version_before` on full failure with full rollback.
- `duration_ms` covers validation + execution + rollback if any.
