# Action Types

All actions require:
- `target_id` (stable id)
- `action_type`
- `parameters`

Avatar actions are the one current exception to strict target-id lookup. In v1 they may use an empty `target_id` and rely on `parameters.avatar_id` (default `avatar_main`) because the managed avatar may not exist yet at spawn time.

## Shared ActionCommand
```json
{
  "target_id": "obj_door_kitchen",
  "action_type": "set_state",
  "parameters": {},
  "preconditions": []
}
```

## `set_state`
```json
{
  "target_id": "obj_door_kitchen",
  "action_type": "set_state",
  "parameters": {"state": "open"}
}
```

## `set_transform`
```json
{
  "target_id": "obj_avatar_01",
  "action_type": "set_transform",
  "parameters": {
    "position": [1.0,0.0,2.0],
    "rotation": [0.0,90.0,0.0]
  }
}
```

## `set_sensor`
```json
{
  "target_id": "sensor_distance_02",
  "action_type": "set_sensor",
  "parameters": {
    "sensor_type": "IMU",
    "operation": "create",
    "position": [2.45, 1.55, 3.12],
    "rotation": [0.0, 270.0, 0.0],
    "parent": "",
    "show_visualization": "true",
    "show_data_graph": "false"
  }
}
```

Avatar body attachment uses the same `set_sensor` action shape, with semantic attachment metadata:

```json
{
  "target_id": "sensor_imu_left_wrist",
  "action_type": "set_sensor",
  "parameters": {
    "sensor_type": "IMU",
    "operation": "update",
    "attach_mode": "avatar_joint",
    "avatar_id": "avatar_main",
    "joint_name": "left_wrist",
    "local_position": [0.0, 0.0, 0.0],
    "local_rotation": [0.0, 0.0, 0.0],
    "show_visualization": "true",
    "show_data_graph": "false"
  }
}
```

Notes:

- Active avatar attachment uses semantic `joint_name` values returned by `scene.query_avatars` in `avatars[].attachment_points`.
- Use `operation: "create"` for new sensors and `operation: "update"` for moving, rebinding, or configuring an existing sensor. `operation: "update"` fails if `target_id` does not name an existing sensor.
- Query `scene.query_sensors` before moving or removing sensors unless the latest query result already provides exact `sensor_id` values.
- Raw SMPL-X bones are not exposed as scene objects in the active API.
- `avatar_id` is a formal contract field; current single-avatar default is `avatar_main`.

## `highlight`
```json
{
  "target_id": "obj_fridge_01",
  "action_type": "highlight",
  "parameters": {"color": "#FFD700", "duration_s": 5.0}
}
```

## `spawn_avatar`
```json
{
  "target_id": "",
  "action_type": "spawn_avatar",
  "parameters": {
    "avatar_id": "avatar_main",
    "prefab_key": "smplx_male",
    "position": [0.0, 0.0, 0.0],
    "rotation": [0.0, 90.0, 0.0]
  }
}
```

## `set_avatar_transform`
```json
{
  "target_id": "",
  "action_type": "set_avatar_transform",
  "parameters": {
    "avatar_id": "avatar_main",
    "position": [1.0, 0.0, 2.0],
    "rotation": [0.0, 180.0, 0.0]
  }
}
```

## `load_avatar_motion`
```json
{
  "target_id": "",
  "action_type": "load_avatar_motion",
  "parameters": {
    "avatar_id": "avatar_main",
    "motion_id": "motion_walk_sink",
    "motion_name": "walk_to_sink",
    "motion_json": "{\"model\":\"smplx\",\"gender\":\"male\",\"fps\":120.0,\"betas\":[],\"poses\":[],\"trans\":[]}",
    "source_text": "walk to the sink"
  }
}
```

## `play_avatar_motion`
```json
{
  "target_id": "",
  "action_type": "play_avatar_motion",
  "parameters": {
    "avatar_id": "avatar_main",
    "speed": 1.0,
    "loop": false
  }
}
```

## `pause_avatar_motion` / `stop_avatar_motion` / `clear_avatar_motion` / `remove_avatar`
```json
{
  "target_id": "",
  "action_type": "remove_avatar",
  "parameters": {
    "avatar_id": "avatar_main"
  }
}
```

## Type Rules
- Position/rotation vectors must have length 3.
- Enum/string parameters are case-sensitive unless declared otherwise.
- Unknown parameters are rejected with `INVALID_PARAM`.
