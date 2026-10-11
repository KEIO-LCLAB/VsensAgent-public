"""
core/memory/semantic_memory.py
Loads static domain-knowledge YAML files at startup and exposes them
for prompt injection and agent queries.
"""
import logging
import ast
from pathlib import Path
from typing import Optional

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local test fallback
    yaml = None

logger = logging.getLogger(__name__)


def _parse_scalar(value: str):
    text = value.strip()
    if text == "":
        return ""
    if text.startswith("[") and text.endswith("]"):
        return ast.literal_eval(text)
    if text.startswith('"') and text.endswith('"'):
        return ast.literal_eval(text)
    if text.startswith("'") and text.endswith("'"):
        return ast.literal_eval(text)
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _simple_yaml_safe_load(text: str):
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]

    def parse_block(index: int, indent: int):
        result = {}
        while index < len(lines):
            raw_line = lines[index]
            current_indent = len(raw_line) - len(raw_line.lstrip(" "))
            if current_indent < indent:
                break
            if current_indent > indent:
                index += 1
                continue
            stripped = raw_line.strip()
            if ":" not in stripped:
                index += 1
                continue
            key, remainder = stripped.split(":", 1)
            remainder = remainder.strip()
            if remainder == "":
                nested, index = parse_block(index + 1, indent + 2)
                result[key] = nested
            else:
                result[key] = _parse_scalar(remainder)
                index += 1
        return result, index

    parsed, _ = parse_block(0, 0)
    return parsed


class SemanticMemory:
    """
    Reads every *.yaml file from *knowledge_dir* into a dict keyed by stem.

    Example:
        data/memory/knowledge/sensors.yaml  → self.knowledge["sensors"]
        data/memory/knowledge/scene_conventions.yaml → self.knowledge["scene_conventions"]

    Parameters
    ----------
    knowledge_dir : Path to the directory containing *.yaml knowledge files.
    """

    def __init__(self, knowledge_dir: str):
        self.knowledge: dict = {}
        self._load(knowledge_dir)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self, knowledge_dir: str) -> None:
        kdir = Path(knowledge_dir)
        if not kdir.exists():
            logger.warning("[SemanticMemory] Knowledge dir not found: %s", kdir)
            return
        for yaml_file in sorted(kdir.glob("*.yaml")):
            try:
                raw_text = yaml_file.read_text(encoding="utf-8")
                data = yaml.safe_load(raw_text) if yaml is not None else _simple_yaml_safe_load(raw_text)
                self.knowledge[yaml_file.stem] = data
                logger.debug("[SemanticMemory] Loaded '%s'.", yaml_file.name)
            except Exception as exc:
                logger.warning("[SemanticMemory] Failed to load %s: %s", yaml_file.name, exc)
        logger.info("[SemanticMemory] Loaded %d knowledge files from %s.",
                    len(self.knowledge), kdir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[dict]:
        """Return the knowledge entry for *key*, or None if not found."""
        return self.knowledge.get(key)

    def as_text(self) -> str:
        """
        Compact string summary of all loaded knowledge — used only if
        the static system-prompt section is insufficient for a given query.
        """
        parts = []
        for key, value in self.knowledge.items():
            parts.append(f"[{key}]")
            if isinstance(value, dict):
                for k, v in value.items():
                    parts.append(f"  {k}: {v}")
            else:
                parts.append(f"  {value}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        keys = list(self.knowledge.keys())
        return f"SemanticMemory(keys={keys})"
