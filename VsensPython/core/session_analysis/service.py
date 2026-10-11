from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


HEARTBEAT_MESSAGE_TYPE = "scene_heartbeat"


def parse_session_log(path: str | Path) -> list[dict[str, Any]]:
    log_path = Path(path)
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError(f"Session log line {line_number} is not a JSON object")
        events.append(event)
    events.sort(key=lambda event: event.get("elapsed_ms", 0))
    return events


def analyze_session_flow(path: str | Path, *, include_heartbeat: bool = False) -> dict[str, Any]:
    raw_events = parse_session_log(path)
    events = [
        _normalize_event(event)
        for event in raw_events
        if include_heartbeat or event.get("message_type") != HEARTBEAT_MESSAGE_TYPE
    ]

    session = _build_session_summary(raw_events, events)
    message_counts = Counter(
        event["message_type"]
        for event in events
        if event.get("message_type")
    )
    flow_nodes = _build_flow_nodes(events)
    flow_edges = _build_flow_edges(flow_nodes)

    return {
        "session": session,
        "events": events,
        "message_counts": dict(sorted(message_counts.items())),
        "durations": {
            "requests": _calculate_request_durations(events),
            "jobs": _calculate_job_durations(events),
            "actions": _calculate_action_durations(events),
        },
        "action_flow_nodes": flow_nodes,
        "action_flow_edges": flow_edges,
        "flow": {
            "nodes": flow_nodes,
            "edges": flow_edges,
        },
    }


def export_flow_mermaid(analysis: dict[str, Any]) -> str:
    nodes = analysis.get("action_flow_nodes") or analysis.get("flow", {}).get("nodes") or []
    edges = analysis.get("action_flow_edges") or analysis.get("flow", {}).get("edges") or []
    lines = ["flowchart TD"]
    for node in nodes:
        lines.append(f'  {node["id"]}["{_escape_mermaid_label(node["label"])}"]')
    for edge in edges:
        lines.append(f'  {edge["from"]} --> {edge["to"]}')
    return "\n".join(lines)


def export_analysis_json(analysis: dict[str, Any]) -> str:
    return json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True)


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    message_type = event.get("message_type")
    if not message_type and isinstance(payload, dict):
        message_type = payload.get("type")
    summary = event.get("summary") or _summarize_event(event, message_type)
    return {
        "schema_version": event.get("schema_version", 1),
        "timestamp": event.get("timestamp", ""),
        "elapsed_ms": int(event.get("elapsed_ms") or 0),
        "client_id": event.get("client_id", ""),
        "username": event.get("username", ""),
        "us": event.get("us", ""),
        "direction": event.get("direction", ""),
        "event_kind": event.get("event_kind", ""),
        "message_type": message_type,
        "payload": payload,
        "summary": summary,
    }


def _build_session_summary(raw_events: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    source = raw_events or events
    first = source[0] if source else {}
    last = source[-1] if source else {}
    return {
        "client_id": first.get("client_id", ""),
        "username": _last_non_empty(source, "username"),
        "us": _last_non_empty(source, "us"),
        "started_at": first.get("timestamp", ""),
        "ended_at": last.get("timestamp", ""),
        "duration_ms": max(0, int(last.get("elapsed_ms") or 0) - int(first.get("elapsed_ms") or 0)) if source else 0,
        "event_count": len(events),
        "raw_event_count": len(raw_events),
    }


def _last_non_empty(events: list[dict[str, Any]], key: str) -> str:
    for event in reversed(events):
        value = event.get(key)
        if value:
            return value
    return ""


def _calculate_request_durations(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    starts: dict[str, dict[str, Any]] = {}
    durations: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        request_id = payload.get("request_id")
        if not request_id:
            continue
        message_type = event.get("message_type") or ""
        if _is_request_start(message_type, event.get("direction")):
            starts.setdefault(request_id, event)
            continue
        if _is_request_end(message_type) and request_id in starts:
            start = starts[request_id]
            durations[request_id] = {
                "request_id": request_id,
                "method": payload.get("method") or start.get("message_type"),
                "start_message_type": start.get("message_type"),
                "end_message_type": message_type,
                "start_elapsed_ms": start.get("elapsed_ms", 0),
                "end_elapsed_ms": event.get("elapsed_ms", 0),
                "duration_ms": max(0, event.get("elapsed_ms", 0) - start.get("elapsed_ms", 0)),
                "status": payload.get("status") or payload.get("type"),
            }
    return durations


def _is_request_start(message_type: str, direction: str | None) -> bool:
    if direction != "send":
        return False
    if message_type in {"scene.query_response", "scene.execute_actions_response", "scene.validate_actions_response", "scene.error"}:
        return False
    return message_type.startswith("scene.")


def _is_request_end(message_type: str) -> bool:
    return message_type in {
        "scene.query_response",
        "scene.execute_actions_response",
        "scene.validate_actions_response",
        "scene.error",
    }


def _calculate_job_durations(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    starts: dict[str, dict[str, Any]] = {}
    durations: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        job_id = payload.get("job_id")
        if not job_id:
            continue
        message_type = event.get("message_type") or ""
        status = payload.get("status")
        if message_type == "job.started" or (message_type == "job.status" and status == "running"):
            starts.setdefault(job_id, event)
            continue
        if message_type in {"job.completed", "job.cancelled", "task.result"} or (
            message_type == "job.status" and status in {"completed", "cancelled", "failed"}
        ):
            start = starts.get(job_id)
            if start is None:
                continue
            durations[job_id] = {
                "job_id": job_id,
                "job_kind": payload.get("job_kind") or start.get("payload", {}).get("job_kind", ""),
                "start_message_type": start.get("message_type"),
                "end_message_type": message_type,
                "start_elapsed_ms": start.get("elapsed_ms", 0),
                "end_elapsed_ms": event.get("elapsed_ms", 0),
                "duration_ms": max(0, event.get("elapsed_ms", 0) - start.get("elapsed_ms", 0)),
                "status": status or message_type.removeprefix("job."),
            }
    return durations


def _calculate_action_durations(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    actions: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("message_type") != "unity.scene_action":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        record = payload.get("record")
        if not isinstance(record, dict):
            continue
        action_id = record.get("actionId")
        if not action_id:
            continue
        actions[action_id] = {
            "action_id": action_id,
            "action_type": record.get("actionType", ""),
            "target_id": record.get("targetId", ""),
            "source": record.get("source", ""),
            "timestamp_utc": record.get("timestampUtc", ""),
            "start_elapsed_ms": event.get("elapsed_ms", 0),
            "end_elapsed_ms": event.get("elapsed_ms", 0),
            "duration_ms": 0,
        }
    return actions


def _build_flow_nodes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        label = _flow_label(event)
        nodes.append(
            {
                "id": f"e{index}",
                "label": label,
                "message_type": event.get("message_type"),
                "event_kind": event.get("event_kind"),
                "direction": event.get("direction"),
                "elapsed_ms": event.get("elapsed_ms", 0),
            }
        )
    return nodes


def _build_flow_edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"from": previous["id"], "to": current["id"]}
        for previous, current in zip(nodes, nodes[1:])
    ]


def _flow_label(event: dict[str, Any]) -> str:
    message_type = event.get("message_type")
    direction = event.get("direction")
    elapsed = event.get("elapsed_ms", 0)
    if message_type:
        return f"{elapsed}ms {direction} {message_type}"
    return f"{elapsed}ms {direction} {event.get('event_kind', 'event')}"


def _summarize_event(event: dict[str, Any], message_type: str | None) -> str:
    direction = event.get("direction") or "event"
    if message_type:
        return f"{direction} {message_type}"
    return f"{direction} {event.get('event_kind') or 'event'}"


def _escape_mermaid_label(label: str) -> str:
    return str(label).replace("\\", "\\\\").replace('"', '\\"')
