from __future__ import annotations

import uuid


class QueryFirstCoordinator:
    ALLOWED_METHODS = {
        "scene.query_summary",
        "scene.query_objects",
        "scene.query_relations",
        "scene.query_surfaces",
        "scene.query_avatars",
        "scene.query_motions",
        "scene.query_sensors",
        "scene.query_avatar_candidates",
        "scene.validate_avatar_placement",
        "scene.capture_validation_views",
        "scene.query_recording_status",
        "scene.execute_actions",
    }

    def __init__(self, *, query_executor):
        self._query_executor = query_executor

    async def execute_query(self, query_payload: dict) -> dict:
        method = (query_payload or {}).get("method", "")
        if method not in self.ALLOWED_METHODS:
            raise ValueError(f"Unsupported query method: {method}")

        params = dict((query_payload or {}).get("params") or {})
        request = {
            "type": method,
            "request_id": f"qry_{uuid.uuid4().hex}",
            **params,
        }
        return await self._query_executor(request)
