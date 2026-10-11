"""
core/skills/control_parser.py
Parses the <control>...</control> block that the LLM emits in its reply text.

Public API
----------
ControlParser.extract(reply_text) -> (spoken_text: str, actions: list[dict])
"""
import json
import re
import logging

logger = logging.getLogger(__name__)

_OPEN_TAG  = "<control>"
_CLOSE_TAG = "</control>"
_INTERNAL_LINE_PATTERN = re.compile(r"(?im)^[^\S\r\n]*[^A-Za-z0-9<\r\n]*to=scene\.[^\r\n]*\n?")
_REMAINING_BLOCK_PATTERN = re.compile(
    r"(?is)<(?:control|proposal|clarification|query|experiment)>(?:.*?</(?:control|proposal|clarification|query|experiment)>|.*$)"
)


class ControlParser:
    """
    Stateless parser for the <control> block embedded in LLM reply text.

    The block is expected to contain comment-free JSON with this shape:
        {
            "actions": [
                {"target": "...", "action": "...", "parameters": {...}},
                ...
            ]
        }
    """

    @staticmethod
    def extract(reply_text: str) -> tuple[str, list[dict]]:
        """
        Parameters
        ----------
        reply_text : full LLM response string

        Returns
        -------
        spoken_text : reply with the <control> block stripped
        actions     : list of action dicts, empty list if none or on error
        """
        structured = ControlParser.extract_structured_reply(reply_text)
        return structured["spoken_text"], structured["actions"]

    @staticmethod
    def extract_structured_reply(reply_text: str) -> dict:
        """
        Parse supported structured blocks from a single LLM reply.

        Supported blocks:
          - <control>{...}</control>
          - <proposal>{...}</proposal>
          - <clarification>{...}</clarification>
          - <query>{...}</query>
          - <experiment>{...}</experiment>
        """
        spoken_text = reply_text.strip()
        spoken_text, control_payload = ControlParser._extract_json_block(spoken_text, "control")
        spoken_text, proposal_payload = ControlParser._extract_json_block(spoken_text, "proposal")
        spoken_text, clarification_payload = ControlParser._extract_json_block(spoken_text, "clarification")
        spoken_text, query_payload = ControlParser._extract_json_block(spoken_text, "query")
        spoken_text, experiment_payload = ControlParser._extract_json_block(spoken_text, "experiment")

        actions = ControlParser._normalize_actions(control_payload)

        return {
            "spoken_text": ControlParser._clean_spoken_text(spoken_text),
            "actions": actions,
            "proposal": proposal_payload if isinstance(proposal_payload, dict) else None,
            "clarification": clarification_payload if isinstance(clarification_payload, dict) else None,
            "query": query_payload if isinstance(query_payload, dict) else None,
            "experiment": experiment_payload if isinstance(experiment_payload, dict) else None,
        }

    @staticmethod
    def strip_control_block(reply_text: str) -> str:
        """Convenience: return only the spoken portion of the reply."""
        spoken, _ = ControlParser.extract(reply_text)
        return spoken

    @staticmethod
    def _extract_json_block(reply_text: str, tag_name: str) -> tuple[str, dict | list | None]:
        pattern = re.compile(rf"<{tag_name}>(.*?)</{tag_name}>", re.DOTALL | re.IGNORECASE)
        match = pattern.search(reply_text)
        if not match:
            return reply_text, None

        raw = match.group(1).strip()
        before = reply_text[:match.start()].rstrip()
        after = reply_text[match.end():].lstrip()
        updated_text = (before + (" " if before and after else "") + after).strip()

        if not raw:
            return updated_text, {}

        try:
            return updated_text, json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("[ControlParser] Malformed JSON in <%s> block: %s", tag_name, exc)
            logger.debug("[ControlParser] Raw <%s> block: %s", tag_name, raw)
            return updated_text, None

    @staticmethod
    def _normalize_actions(payload: dict | list | None) -> list[dict]:
        if not isinstance(payload, dict):
            return []

        actions = payload.get("actions", [])
        if not isinstance(actions, list):
            logger.warning("[ControlParser] 'actions' field is not a list; ignoring control block.")
            return []

        normalised: list[dict] = []
        for item in actions:
            if not isinstance(item, dict):
                logger.warning("[ControlParser] Skipping non-dict action item: %s", item)
                continue
            normalised.append({
                "target": item.get("target", ""),
                "action": item.get("action", ""),
                "parameters": item.get("parameters", {}),
            })
        return normalised

    @staticmethod
    def _clean_spoken_text(spoken_text: str) -> str:
        cleaned = spoken_text or ""
        cleaned = _INTERNAL_LINE_PATTERN.sub("", cleaned)
        cleaned = _REMAINING_BLOCK_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
