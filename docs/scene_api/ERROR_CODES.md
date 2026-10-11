# Error Codes

## Standard Codes
- `TARGET_NOT_FOUND`: target_id does not exist.
- `UNSUPPORTED_ACTION`: target does not support action_type.
- `INVALID_PARAM`: parameter missing, malformed, or out of schema.
- `SCENE_VERSION_MISMATCH`: request version != current scene version.
- `CONSTRAINT_VIOLATION`: precondition or rule check failed.
- `PLACEMENT_NOT_MOUNTABLE`: requested surface is not mountable.
- `PLACEMENT_COLLISION`: placement intersects geometry.
- `COVERAGE_INSUFFICIENT`: estimated/validated coverage below threshold.
- `TRANSACTION_ROLLBACK_FAILED`: rollback could not restore full state.

## Error Item Shape
```json
{
  "code": "INVALID_PARAM",
  "message": "rotation must be array[3]",
  "target_id": "sensor_distance_02",
  "action_index": 1,
  "hint": "Provide Euler degrees [x,y,z]"
}
```

## Agent Recovery Guidance
- `TARGET_NOT_FOUND`: re-query object catalog by tag/zone.
- `SCENE_VERSION_MISMATCH`: refresh summary and regenerate batch.
- `PLACEMENT_*`: call `scene.find_sensor_placements` and retry.
- `INVALID_PARAM`: adjust payload to action schema.
