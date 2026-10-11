# Scenario: Mount Sensor on Wall Near Fridge

> Historical example. Useful as a scenario illustration, but not a normative runtime contract.

## Goal
Deploy a wall-mounted distance sensor near fridge with sufficient coverage and no geometry penetration.

## Flow
1. Agent calls `scene.query_objects` for fridge.
2. Agent calls `scene.query_surfaces` near fridge (`mountable_only=true`).
3. Agent calls `scene.find_sensor_placements` with constraints.
4. Agent selects top candidate.
5. Agent calls `scene.validate_placement`.
6. Agent sends `scene.execute_actions` batch:
   - `set_sensor` (mount and config)
   - optional `highlight` on target

## Example Execute Request
```json
{
  "request_id": "req_fridge_sensor_001",
  "scene_version": 102,
  "strict": true,
  "actions": [
    {
      "target_id": "sensor_distance_02",
      "action_type": "set_sensor",
      "parameters": {
        "sensor_type": "DISTANCE",
        "mount": {
          "surface_id": "surf_wall_kitchen_east",
          "position": [2.45, 1.55, 3.12],
          "rotation": [0.0, 270.0, 0.0]
        },
        "config": {
          "valid_distance": 3.0,
          "show_visualization": true,
          "show_data_graph": false
        }
      }
    }
  ]
}
```

## Success Criteria
- Placement is on mountable wall.
- Collision report is clean.
- Coverage >= 0.8 for fridge target.
- Transaction succeeds and increments scene version.
