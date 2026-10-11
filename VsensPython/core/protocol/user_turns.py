from __future__ import annotations

import json


def _build_structured_turn(prefix: str, payload: dict) -> str:
    return f"[{prefix}] {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"


def build_clarification_reply_turn(
    *,
    question_id: str,
    selected_ids: list[str] | None = None,
    free_text: str | None = None,
) -> str:
    return _build_structured_turn(
        "clarification.reply",
        {
            "question_id": question_id,
            "selected_ids": selected_ids or [],
            "free_text": free_text or "",
        },
    )


def build_proposal_select_turn(
    *,
    proposal_id: str,
    selected_option_ids: list[str] | None = None,
    note: str | None = None,
) -> str:
    return _build_structured_turn(
        "proposal.select",
        {
            "proposal_id": proposal_id,
            "selected_option_ids": selected_option_ids or [],
            "note": note or "",
        },
    )
