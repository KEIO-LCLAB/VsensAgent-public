from __future__ import annotations

import json


def parse_visual_review(raw_text: str) -> dict:
    try:
        payload = json.loads(raw_text)
    except Exception:
        return {
            "decision": "retry",
            "issues": ["review_parse_error"],
            "reason": "Unable to parse visual review output.",
        }

    decision = payload.get("decision")
    if decision not in {"accept", "retry"}:
        return {
            "decision": "retry",
            "issues": ["review_parse_error"],
            "reason": "Unable to parse visual review output.",
        }

    issues = payload.get("issues")
    if not isinstance(issues, list):
        issues = []

    reason = str(payload.get("reason") or "").strip() or "No reason provided."
    return {
        "decision": decision,
        "issues": [str(issue) for issue in issues],
        "reason": reason,
    }
