from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


_TIMESTAMP_RE = re.compile(r"(\d{8}_\d{6})$")


@dataclass(frozen=True)
class RecordingSelection:
    selector: str
    us: str
    username: str
    resolved_paths: list[Path]


def resolve_recording_paths(
    *,
    root: Path,
    us: str,
    username: str,
    selector: str,
    timestamp_label: str | None = None,
    recent_n: int = 3,
) -> RecordingSelection:
    safe_us = _sanitize_segment(us)
    safe_username = _sanitize_segment(username)
    user_root = root / safe_us / safe_username

    if not user_root.exists() or not user_root.is_dir():
        return RecordingSelection(
            selector=selector,
            us=safe_us,
            username=safe_username,
            resolved_paths=[],
        )

    candidates = sorted(
        [path for path in user_root.iterdir() if path.is_dir()],
        key=_sort_key,
        reverse=True,
    )

    selected: list[Path]
    if selector == "latest":
        selected = candidates[:1]
    elif selector == "all":
        selected = candidates
    elif selector == "recent_n":
        selected = candidates[: max(0, recent_n)]
    elif selector == "by_label":
        label = _sanitize_segment(timestamp_label or "")
        selected = [user_root / label] if label else []
        selected = [path for path in selected if path.exists() and path.is_dir()]
    else:
        raise ValueError(f"Unsupported selector: {selector}")

    return RecordingSelection(
        selector=selector,
        us=safe_us,
        username=safe_username,
        resolved_paths=selected,
    )


def _sanitize_segment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (value or "anonymous").strip())
    return safe.strip("_") or "anonymous"


def _sort_key(path: Path) -> tuple[datetime, float, str]:
    label = path.name
    match = _TIMESTAMP_RE.search(label)
    parsed = datetime.min
    if match:
        try:
            parsed = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            parsed = datetime.min
    return (parsed, path.stat().st_mtime, label)
