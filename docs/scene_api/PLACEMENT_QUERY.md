# Placement Query

## PlacementCandidate
```json
{
  "candidate_id": "cand_001",
  "surface_id": "surf_wall_kitchen_east",
  "pose": {
    "position": [2.45, 1.55, 3.12],
    "rotation": [0.0, 270.0, 0.0]
  },
  "score": 0.872,
  "coverage_score": 0.90,
  "occlusion_risk": 0.08,
  "distance_penalty": 0.04,
  "collision_free": true,
  "explanations": [
    "Mounted on wall surface",
    "Target center in sensor FOV",
    "No static geometry overlap"
  ]
}
```

## Candidate Generation Pipeline
1. Resolve eligible mountable surfaces.
2. Sample points on surfaces under spatial constraints.
3. Generate orientation candidates per sensor model.
4. Fast collision filter.
5. Fast coverage/occlusion estimation.
6. Score and rank.

## Default Scoring
`score = coverage_weight * coverage - occlusion_weight * occlusion - distance_weight * distance_penalty`

Default weights:
- `coverage_weight = 0.7`
- `occlusion_weight = 0.2`
- `distance_weight = 0.1`

## Deterministic Ranking
Tie-break order:
1. Higher `score`
2. Lower `occlusion_risk`
3. Lower `distance_penalty`
4. Lexicographical `candidate_id`
