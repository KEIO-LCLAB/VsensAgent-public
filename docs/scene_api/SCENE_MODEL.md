# Scene Model

## Top-level Envelope
```json
{
  "scene_id": "kitchen_demo_01",
  "scene_version": 102,
  "generated_at": "2026-03-05T10:00:00Z",
  "objects": [],
  "surfaces": [],
  "zones": [],
  "relations": []
}
```

## SceneObject
```json
{
  "id": "obj_fridge_01",
  "alias": "Fridge",
  "kind": "state_object",
  "room_id": "room_kitchen",
  "pose": {
    "position": [1.2, 0.0, 3.4],
    "rotation": [0.0, 90.0, 0.0],
    "scale": [1.0, 1.0, 1.0]
  },
  "bounds": {
    "center": [1.2, 0.9, 3.4],
    "size": [0.8, 1.8, 0.7]
  },
  "state": {
    "door": "closed"
  },
  "capabilities": ["set_state", "highlight"],
  "tags": ["appliance", "occluder"]
}
```

### `kind` enum
- `structure`
- `state_object`
- `movable`
- `sensor`
- `actor`
- `zone`

## Surface
```json
{
  "surface_id": "surf_wall_kitchen_east",
  "parent_object_id": "obj_wall_kitchen_east",
  "surface_type": "wall",
  "plane": {
    "point": [2.5, 1.5, 3.0],
    "normal": [-1.0, 0.0, 0.0]
  },
  "boundary_polygon": [[2.5,0.0,2.0],[2.5,2.8,2.0],[2.5,2.8,4.2],[2.5,0.0,4.2]],
  "mountable": true,
  "clearance_min": 0.05,
  "tags": ["kitchen", "sensor_mount"]
}
```

## Zone
```json
{
  "zone_id": "zone_kitchen_main",
  "name": "Kitchen",
  "type": "semantic",
  "volume": {
    "shape": "aabb",
    "center": [1.8, 1.4, 3.3],
    "size": [3.2, 2.8, 2.6]
  },
  "entry_points": [
    {"id": "ep_door_kitchen", "position": [0.2, 0.0, 2.1], "normal": [1.0,0.0,0.0]}
  ]
}
```

## Relation
```json
{
  "type": "near",
  "from_id": "obj_fridge_01",
  "to_id": "obj_wall_kitchen_east",
  "metadata": {
    "distance": 0.68
  }
}
```

### `type` enum
- `near`
- `inside`
- `attached_to`
- `facing`
- `can_mount_on`
- `can_cover`

## Identity Rules
- `id` is immutable during object lifetime.
- `alias` is mutable and non-unique; never used as execution primary key.
- All execution APIs require `target_id`.
