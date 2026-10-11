# Acceptance Tests

## 1. Wall Mount Correctness
- Given fridge target in kitchen.
- When querying placements for wall mount.
- Then all returned candidates reference `surface_type=wall` and `mountable=true`.

## 2. No Penetration
- Given selected candidate.
- When validating placement.
- Then collision report is `collision_free=true`.

## 3. Coverage Sufficiency
- Given `min_coverage=0.8` constraint.
- When generating candidates.
- Then top candidate has coverage >= 0.8.

## 4. Strict Transaction
- Given action batch of 3 actions.
- When action #2 fails.
- Then action #1 is rolled back and version unchanged.

## 5. Version Safety
- Given stale request scene_version.
- When validating or executing.
- Then API rejects with `SCENE_VERSION_MISMATCH`.

## 6. Query Determinism
- Given fixed scene_version and same query input.
- When requesting placements repeatedly.
- Then ranking order is stable.
