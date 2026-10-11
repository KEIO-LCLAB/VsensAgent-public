# Observability

## Logging Fields
Every query/action execution log should include:
- `timestamp`
- `trace_id`
- `request_id`
- `api_method`
- `scene_version`
- `status`
- `duration_ms`
- `error_codes[]`

## Trace Model
- One `trace_id` per external request.
- Sub-steps (validation, candidate generation, rollback) share same trace.

## Recommended Metrics
- `query_latency_ms` (by method)
- `execute_latency_ms`
- `validation_failure_rate`
- `rollback_rate`
- `placement_success_rate`
- `coverage_mean`

## Diagnostic Logging
For `scene.find_sensor_placements`, include:
- candidate count before/after filters
- rejection reasons by stage
- top-N candidate score breakdown
