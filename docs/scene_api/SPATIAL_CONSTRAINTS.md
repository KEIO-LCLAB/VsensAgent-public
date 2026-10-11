# Spatial Constraints

## Mounting Constraints
- Candidate must lie inside surface boundary polygon.
- Surface must be `mountable=true`.
- Surface normal and sensor facing must satisfy mount rule.
- Candidate local clearance must be >= `clearance_min`.

## Collision Constraints
- Sensor bounds cannot intersect static structure bounds.
- Sensor must not penetrate wall/floor geometry.
- Optional dynamic object collision checks can be enabled per query.

## Coverage Constraints
- Sensor model provides FOV/range profile.
- Target coverage computed against target bounds/critical points.
- `min_coverage` is mandatory when provided by request.
- If coverage below threshold => `COVERAGE_INSUFFICIENT`.

## Occlusion Constraints
- Line-of-sight approximation via ray fan / representative rays.
- If occlusion exceeds threshold => candidate rejected or down-scored.

## Height/Distance Constraints
- `min_height <= candidate.y <= max_height`.
- Distance from candidate to target center <= `max_distance_to_target`.
