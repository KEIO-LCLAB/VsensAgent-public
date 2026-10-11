# Transaction Rules

## Default Policy
- `strict=true` by default.
- Under strict mode: all actions succeed or all rolled back.

## Lifecycle
1. Validate request envelope and version.
2. Validate all actions.
3. Begin transaction and capture rollback journal.
4. Execute actions in order.
5. If any action fails:
   - start rollback in reverse order
   - emit failure report with rollback result
6. If all succeed:
   - commit transaction
   - increment `scene_version`

## Rollback Semantics
- Best effort rollback for each applied action.
- Any rollback failure sets `rollback_status=partial_failure` and emits `TRANSACTION_ROLLBACK_FAILED`.

## Preconditions
- Every action may include `preconditions[]`.
- If precondition fails, action fails with `CONSTRAINT_VIOLATION`.

## Idempotency
- `request_id` should be unique.
- Duplicate `request_id` handling policy:
  - return previous report if retained in in-memory cache window
  - otherwise treat as new request
