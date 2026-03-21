from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotConfig:
    max_elements: int = 80
    max_text_chars: int = 4000
    include_visible_text: bool = True


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def format_snapshot_for_llm(snapshot: dict, *, max_chars: int = 12000) -> str:
    """
    Turn snapshot JSON into a compact string for the model.
    We still keep it as JSON because it is easiest to parse.
    """
    s = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return _truncate(s, max_chars)

