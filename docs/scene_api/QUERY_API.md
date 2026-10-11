# Query API

All query methods are request/response style and read-only.

## Transport Contract

- The websocket `type` is the method name itself, for example `scene.query_objects`.
- Query callers should include a unique `request_id`.
- Unity echoes the same `request_id` on `scene.query_response`.
- If the failure is request-specific, Unity should also echo `request_id` on `scene.error`.
- Query responses should include the relevant `scene_version` so the caller can reason about staleness.

Minimal correlation shape:

```json
{
  "type": "scene.query_response",
  "request_id": "qry_123",
  "method": "scene.query_summary",
  "scene_version": 102
}
```

## 1. `scene.query_summary`
### Request
```json
{
  "request_id": "qry_123",
  "scene_version": 101
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_123",
  "method": "scene.query_summary",
  "scene_id": "kitchen_demo_01",
  "scene_version": 102,
  "counts": {"objects": 48, "surfaces": 22, "zones": 4, "relations": 128},
  "changed": {"objects": ["obj_door_kitchen"], "sensors": ["sensor_distance_02"]}
}
```

## 2. `scene.query_objects`
### Request
```json
{
  "request_id": "qry_124",
  "scene_version": 102,
  "ids": ["obj_fridge_01"],
  "aliases": [],
  "tags": [],
  "zone_id": ""
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_124",
  "method": "scene.query_objects",
  "scene_version": 102,
  "objects": [/* SceneObject[] */]
}
```

Known lookup fields:

- `ids`: canonical object ids
- `aliases`: user-facing or prompt-facing names, such as `CoffeeMaker`
- `tags`: scene tags
- `zone_id`: optional zone restriction

These are the main lookup shapes used by the current query-first MVP in the Python runtime.

## 3. `scene.query_relations`
### Request
```json
{
  "request_id": "qry_125",
  "scene_version": 102,
  "object_id": "obj_fridge_01",
  "relation_types": ["near", "can_mount_on"],
  "radius": 2.0
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_125",
  "method": "scene.query_relations",
  "scene_version": 102,
  "relations": [/* Relation[] */],
  "neighbors": ["obj_wall_kitchen_east", "obj_counter_01"]
}
```

## 4. `scene.query_surfaces`
### Request
```json
{
  "request_id": "qry_126",
  "scene_version": 102,
  "near_object_id": "obj_fridge_01",
  "zone_id": "zone_kitchen_main",
  "mountable_only": true
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_126",
  "method": "scene.query_surfaces",
  "scene_version": 102,
  "surfaces": [/* Surface[] */]
}
```

## 5. `scene.query_avatars`
### Request
```json
{
  "request_id": "qry_127"
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_127",
  "method": "scene.query_avatars",
  "scene_version": 102,
  "avatars": [
    {
      "avatar_id": "avatar_main",
      "object_id": "obj_1234abcd",
      "prefab_key": "smplx_male",
      "position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
      "motion_id": "motion_walk_sink",
      "motion_name": "walk_to_sink",
      "is_playing": true,
      "pose_authority": "agent",
      "attachment_points": [
        {
          "avatar_id": "avatar_main",
          "joint_name": "left_wrist",
          "world_position": {"x": 1.9, "y": 1.1, "z": 4.6},
          "world_rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
          "description": "Semantic avatar attachment point 'left_wrist'."
        }
      ]
    }
  ]
}
```

Notes:

- `scene.query_avatars` is the canonical way to inspect managed avatars and semantic body mount points.
- Current supported `attachment_points[].joint_name` values are `head`, `chest`, `waist`, `left_wrist`, `right_wrist`, `left_ankle`, and `right_ankle`.
- Use these `joint_name` values directly when attaching sensors to the avatar body.

## 6. `scene.query_motions`
### Request
```json
{
  "request_id": "qry_128"
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_128",
  "method": "scene.query_motions",
  "scene_version": 102,
  "motions": [
    {
      "motion_id": "motion_walk_sink",
      "motion_name": "walk_to_sink",
      "source_text": "walk to the sink",
      "has_inline_json": true,
      "loaded_to_avatar_id": "avatar_main"
    }
  ]
}
```

## 7. `scene.query_sensors`
### Request
```json
{
  "request_id": "qry_129",
  "sensor_type": "IMU"
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_129",
  "method": "scene.query_sensors",
  "scene_version": 102,
  "sensors": [
    {
      "sensor_id": "IMU-01",
      "sensor_type": "IMU",
      "position": {"x": 1.0, "y": 1.2, "z": 0.0},
      "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
      "parent_object_id": "avatar_main",
      "parent_name": "left_wrist",
      "attach_mode": "avatar_joint",
      "avatar_id": "avatar_main",
      "joint_name": "left_wrist",
      "local_position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "local_rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
      "show_visualization": true,
      "show_data_graph": false
    }
  ]
}
```

Notes:

- `sensor_type` is optional. Omit it to list all runtime sensors.
- Use `sensor_id` from this response for `set_sensor operation=update` and `remove_sensor`.
- Avatar-mounted sensors report `attach_mode: "avatar_joint"` plus `avatar_id` and `joint_name`.

## 8. `scene.find_sensor_placements`
### Request
```json
{
  "request_id": "qry_127",
  "scene_version": 102,
  "sensor_type": "DISTANCE",
  "target_ids": ["obj_fridge_01"],
  "constraints": {
    "mount_type": "wall",
    "min_height": 1.0,
    "max_height": 2.0,
    "min_coverage": 0.8,
    "max_distance_to_target": 2.5
  }
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_127",
  "method": "scene.find_sensor_placements",
  "scene_version": 102,
  "candidates": [/* PlacementCandidate[] */],
  "scoring": {"coverage_weight": 0.7, "occlusion_weight": 0.2, "distance_weight": 0.1}
}
```

## 9. `scene.query_avatar_candidates`
### Request
```json
{
  "request_id": "qry_129",
  "target_object_id": "",
  "target_alias": "CoffeeMaker",
  "task_hint": "make_coffee",
  "preferred_side": "front",
  "preferred_distance": 0.9,
  "max_candidates": 3
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_129",
  "method": "scene.query_avatar_candidates",
  "scene_version": 102,
  "target_object_id": "obj_coffee_01",
  "task_hint": "make_coffee",
  "preferred_side": "front",
  "candidates": [
    {
      "candidate_id": "avatar_cand_000",
      "target_object_id": "obj_coffee_01",
      "position": {"x": 2.1, "y": 0.0, "z": 4.8},
      "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
      "score": 0.87,
      "grounded": true,
      "collision_free": true
    }
  ]
}
```

## 10. `scene.validate_avatar_placement`
### Request
```json
{
  "request_id": "qry_130",
  "target_object_id": "",
  "target_alias": "CoffeeMaker",
  "task_hint": "make_coffee",
  "position": [2.1, 0.0, 4.8],
  "rotation": [0.0, 180.0, 0.0],
  "motion_json": "",
  "trajectory_sample_count": 7
}
```

## 11. `scene.capture_validation_views`
### Request
```json
{
  "request_id": "qry_131",
  "avatar_id": "avatar_main",
  "target_object_id": "obj_coffee_01",
  "validator_context": "make_coffee"
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_131",
  "method": "scene.capture_validation_views",
  "scene_version": 102,
  "avatar_id": "avatar_main",
  "artifacts": [
    {
      "role": "avatar_eye",
      "path": "<local-path> Support/DefaultCompany/Vsens/ValidationCaptures/attempt_01_avatar_eye.png"
    },
    {
      "role": "user_camera",
      "path": "<local-path> Support/DefaultCompany/Vsens/ValidationCaptures/attempt_01_user_camera.png"
    }
  ]
}
```

Notes:

- The active runtime contract returns exactly two deterministic captures:
  - `avatar_eye`
  - `user_camera`
- `scene.score_validation_views` is not part of the active runtime path anymore.
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_130",
  "method": "scene.validate_avatar_placement",
  "scene_version": 102,
  "validation": {
    "valid": true,
    "collision_free": true,
    "grounded": true,
    "endpoint_valid": true,
    "trajectory_valid": true,
    "motion_mode": "static",
    "issues": []
  }
}
```

## 10. `scene.capture_validation_views`
### Request
```json
{
  "request_id": "qry_131",
  "validator_context": "avatar_make_coffee",
  "avatar_id": "avatar_main",
  "target_object_id": "",
  "target_alias": "CoffeeMaker"
}
```

Notes:

- The active runtime always returns exactly two captures in stable order:
  1. `avatar_eye`
  2. `user_camera`

### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_131",
  "method": "scene.capture_validation_views",
  "scene_version": 102,
  "artifacts": [
    {
      "artifact_id": "avatar_make_coffee_avatar_eye_20260318",
      "artifact_type": "image/png",
      "file_path": "/.../ValidationCaptures/avatar_make_coffee_avatar_eye_20260318.png",
      "label": "avatar_eye"
    },
    {
      "artifact_id": "avatar_make_coffee_user_camera_20260318",
      "artifact_type": "image/png",
      "file_path": "/.../ValidationCaptures/avatar_make_coffee_user_camera_20260318.png",
      "label": "user_camera"
    }
  ]
}
```

## 11. `scene.validate_placement`
### Request
```json
{
  "request_id": "qry_128",
  "scene_version": 102,
  "candidate": {/* PlacementCandidate */}
}
```
### Response
```json
{
  "type": "scene.query_response",
  "request_id": "qry_128",
  "method": "scene.validate_placement",
  "scene_version": 102,
  "valid": true,
  "reasons": [],
  "coverage_report": {"coverage": 0.86},
  "collision_report": {"collision_free": true}
}
```

## Error Correlation

Request-scoped query failures should use `scene.error` and echo the triggering `request_id`:

```json
{
  "type": "scene.error",
  "request_id": "qry_123",
  "code": "invalid_param",
  "message": "Unsupported scene api request type 'scene.query_unknown'"
}
```
