from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any


QueryExecutor = Callable[[dict], Awaitable[dict]]
ObjectSelector = Callable[[dict], Awaitable[dict]]


_ANCHOR_RULES = (
    (("coffee", "咖啡"), ["CoffeeMaker"]),
    (("dish", "washing", "wash", "洗碗", "水槽", "sink"), ["Sink"]),
    (("cooking", "cook", "stove", "做饭", "做菜", "煮饭", "炉灶", "灶台"), ["Stove", "Cooktop", "Oven"]),
    (("fridge", "refrigerator", "冰箱"), ["Fridge_Door_Left", "Fridge_Door_Right", "Fridge"]),
)

_EMBODIED_TERMS = (
    "coffee",
    "咖啡",
    "cooking",
    "cook",
    "做饭",
    "做菜",
    "煮饭",
    "washing",
    "洗碗",
    "activity",
    "动作",
    "用户",
    "human",
)

_OBJECT_STATE_TERMS = (
    "door",
    "open",
    "close",
    "冰箱门",
    "开门",
    "关门",
    "light",
    "灯",
)


class ExperimentPreflightResolver:
    def __init__(
        self,
        *,
        query_executor: QueryExecutor | None = None,
        object_selector: ObjectSelector | None = None,
        scene_snapshot: dict | str | None = None,
    ):
        self._query_executor = query_executor
        self._object_selector = object_selector
        self._scene_snapshot = scene_snapshot if isinstance(scene_snapshot, dict) else {}

    async def resolve(self, plan: dict) -> dict:
        resolved = dict(plan or {})
        phases = [dict(phase) for phase in resolved.get("phases") or []]
        resolved["phases"] = phases
        resolved["actor_mode"] = self._resolve_actor_mode(resolved, phases)
        resolved["requires_avatar"] = resolved["actor_mode"] == "avatar"

        anchors: dict[str, dict] = {}
        for phase in phases:
            aliases = self._candidate_aliases(resolved, phase)
            if not aliases:
                continue
            anchor = await self._resolve_anchor(aliases=aliases, phase=phase)
            label = str(phase.get("label") or aliases[0]).strip()
            phase["target_alias"] = anchor["alias"]
            phase["anchor_alias"] = anchor["alias"]
            anchors[label] = anchor

        if anchors:
            resolved["resolved_anchors"] = anchors
        resolved["setup_actions"] = await self._normalize_setup_actions(resolved.get("setup_actions") or [])
        return resolved

    async def _normalize_setup_actions(self, setup_actions: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        avatar_ids: set[str] | None = None

        for raw in setup_actions:
            if not isinstance(raw, dict):
                continue
            action = str(raw.get("action") or raw.get("action_type") or "").strip()
            target = str(raw.get("target") or raw.get("target_id") or "").strip()
            params = dict(raw.get("parameters") or {})

            if action == "ensure_avatar":
                avatar_id = str(params.get("avatar_id") or target or "avatar_main").strip() or "avatar_main"
                if avatar_ids is None:
                    avatar_ids = await self._query_avatar_ids()
                if avatar_id in avatar_ids:
                    continue
                spawn_params = {
                    "prefab_key": params.get("prefab_key") or "smplx_male",
                    "avatar_id": avatar_id,
                }
                if params.get("position") is not None:
                    spawn_params["position"] = params["position"]
                if params.get("rotation") is not None:
                    spawn_params["rotation"] = params["rotation"]
                normalized.append(
                    {
                        "target": avatar_id,
                        "action": "spawn_avatar",
                        "parameters": spawn_params,
                    }
                )
                continue

            if action == "attach_imu":
                avatar_id = str(params.get("avatar_id") or "avatar_main").strip() or "avatar_main"
                joint_name = str(params.get("joint_name") or params.get("joint") or "right_wrist").strip() or "right_wrist"
                sensor_id = target or str(params.get("sensor_id") or "IMU-01").strip() or "IMU-01"
                normalized.append(
                    {
                        "target": sensor_id,
                        "action": "set_sensor",
                        "parameters": {
                            "sensor_type": "IMU",
                            "attach_mode": "avatar_joint",
                            "avatar_id": avatar_id,
                            "joint_name": joint_name,
                            "show_visualization": str(params.get("show_visualization") or "true").lower(),
                            "show_data_graph": str(params.get("show_data_graph") or "false").lower(),
                        },
                    }
                )
                continue

            normalized.append(
                {
                    "target": target,
                    "action": action,
                    "parameters": params,
                }
            )

        return normalized

    async def _query_avatar_ids(self) -> set[str]:
        if self._query_executor is None:
            return set()
        response = await self._query_executor(
            {
                "type": "scene.query_avatars",
                "request_id": f"exp_avatar_{uuid.uuid4().hex}",
            }
        )
        avatars = response.get("avatars") if isinstance(response, dict) else None
        if not isinstance(avatars, list):
            return set()
        return {
            str((avatar or {}).get("avatar_id") or "").strip()
            for avatar in avatars
            if str((avatar or {}).get("avatar_id") or "").strip()
        }

    def _resolve_actor_mode(self, plan: dict, phases: list[dict]) -> str:
        raw = str(plan.get("actor_mode") or "").strip().lower()
        if raw in {"avatar", "manual"}:
            return raw
        if any(phase.get("manual_actor") for phase in phases):
            return "manual"

        haystack = " ".join(
            [
                str(plan.get("goal") or ""),
                *[
                    " ".join(
                        [
                            str(phase.get("label") or ""),
                            str(phase.get("motion_description") or ""),
                            str(phase.get("target_alias") or ""),
                            str(phase.get("anchor_alias") or ""),
                        ]
                    )
                    for phase in phases
                ],
            ]
        ).lower()
        if any(term in haystack for term in _EMBODIED_TERMS) and not _is_object_state_only(haystack):
            return "avatar"
        return "manual"

    def _candidate_aliases(self, plan: dict, phase: dict) -> list[str]:
        explicit = str(phase.get("target_alias") or phase.get("anchor_alias") or "").strip()
        if explicit:
            return [explicit]
        phase_text = " ".join(
            [str(phase.get("label") or ""), str(phase.get("motion_description") or "")]
        ).lower()
        for terms, aliases in _ANCHOR_RULES:
            if any(term in phase_text for term in terms):
                return list(aliases)
        goal_text = str(plan.get("goal") or "").lower()
        for terms, aliases in _ANCHOR_RULES:
            if any(term in goal_text for term in terms):
                return list(aliases)
        return []

    async def _resolve_anchor(self, *, aliases: list[str], phase: dict) -> dict:
        snapshot_match = self._find_in_scene_snapshot(aliases)
        if snapshot_match is not None:
            return snapshot_match

        queried = await self._query_aliases(aliases)
        if queried is not None:
            return queried

        if self._object_selector is None:
            return {
                "object_id": aliases[0],
                "alias": aliases[0],
                "source": "unresolved_alias",
            }

        selection_request = {
            "type": "object_selection.request",
            "selection_id": f"sel_{uuid.uuid4().hex}",
            "prompt": f"Select the scene object for phase '{phase.get('label') or aliases[0]}'.",
            "mode": "object",
            "candidate_aliases": aliases,
            "allow_cancel": True,
        }
        selection = await self._object_selector(selection_request)
        if not isinstance(selection, dict) or selection.get("cancelled"):
            raise RuntimeError("Object selection was cancelled")
        alias = str(selection.get("selected_alias") or selection.get("selected_object_id") or aliases[0]).strip()
        return {
            "object_id": str(selection.get("selected_object_id") or alias),
            "alias": alias,
            "position": selection.get("world_position"),
            "source": "object_selection",
            "selection_id": selection.get("selection_id") or selection_request["selection_id"],
        }

    def _find_in_scene_snapshot(self, aliases: list[str]) -> dict | None:
        alias_set = {alias.lower() for alias in aliases}
        for name, raw in self._scene_snapshot.items():
            if str(name).lower() not in alias_set:
                continue
            item = raw if isinstance(raw, dict) else {}
            return {
                "object_id": str(item.get("id") or name),
                "alias": str(item.get("alias") or name),
                "position": item.get("position"),
                "size": item.get("size") or item.get("bounds_size"),
                "source": "scene_snapshot",
            }
        return None

    async def _query_aliases(self, aliases: list[str]) -> dict | None:
        if self._query_executor is None:
            return None
        response = await self._query_executor(
            {
                "type": "scene.query_objects",
                "request_id": f"exp_resolve_{uuid.uuid4().hex}",
                "ids": [],
                "aliases": aliases,
                "tags": [],
                "zone_id": "",
            }
        )
        objects = response.get("objects") if isinstance(response, dict) else None
        if not isinstance(objects, list) or not objects:
            return None
        first = objects[0]
        if not isinstance(first, dict):
            return None
        return {
            "object_id": str(first.get("id") or first.get("alias") or aliases[0]),
            "alias": str(first.get("alias") or aliases[0]),
            "position": _vector_to_list(first.get("position") or first.get("bounds_center")),
            "size": _vector_to_list(first.get("bounds_size")),
            "source": "scene.query_objects",
        }


def _is_object_state_only(text: str) -> bool:
    return any(term in text for term in _OBJECT_STATE_TERMS) and not any(
        term in text for term in ("coffee", "咖啡", "做饭", "做菜", "煮饭", "washing", "洗碗")
    )


def _vector_to_list(value: Any) -> list[float] | Any:
    if isinstance(value, dict) and all(axis in value for axis in ("x", "y", "z")):
        return [value["x"], value["y"], value["z"]]
    return value
