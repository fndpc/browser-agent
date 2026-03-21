from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from browser_agent.dom_snapshot import format_snapshot_for_llm
from browser_agent.openai_client import OpenAIChat

log = logging.getLogger("browser_agent.subagents")


@dataclass(frozen=True)
class NavSuggestion:
    should_navigate: bool
    url: str | None
    next_subgoal: str
    rationale: str


@dataclass(frozen=True)
class DomSuggestion:
    tool_name: str
    description: str
    text: str | None
    timeout_ms: int | None
    rationale: str


def _parse_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except Exception:
        # best-effort: return a structured fallback
        return {"error": "invalid_json", "raw": content}


class NavigationAgent:
    def __init__(self, chat: OpenAIChat):
        self._chat = chat

    def suggest(self, *, task: str, snapshot: dict[str, Any], memory: str) -> NavSuggestion:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are NavigationAgent for browser automation. "
                    "You decide whether a URL navigation is needed next. "
                    "Return STRICT JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Task:\n"
                    f"{task}\n\n"
                    "Current page snapshot (compact JSON):\n"
                    f"{format_snapshot_for_llm(snapshot)}\n\n"
                    "Recent memory:\n"
                    f"{memory}\n\n"
                    "Output JSON schema:\n"
                    '{'
                    '"should_navigate": true|false,'
                    '"url": "https://..."|null,'
                    '"next_subgoal": "short",'
                    '"rationale": "short"'
                    "}"
                ),
            },
        ]
        resp = self._chat.create(messages=messages, tools=None)
        content = resp.choices[0].message.content or "{}"
        data = _parse_json(content)
        return NavSuggestion(
            should_navigate=bool(data.get("should_navigate", False)),
            url=data.get("url"),
            next_subgoal=str(data.get("next_subgoal") or ""),
            rationale=str(data.get("rationale") or ""),
        )


class DOMAgent:
    def __init__(self, chat: OpenAIChat):
        self._chat = chat

    def suggest(
        self, *, task: str, snapshot: dict[str, Any], memory: str, subgoal: str
    ) -> DomSuggestion:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are DOMAgent for browser automation. "
                    "Given a compact snapshot, pick the next best UI action. "
                    "You MUST choose one tool among: "
                    "find_element_and_click, type_text_to_field, wait_for_element, get_current_page_snapshot. "
                    "For `description`, output a SHORT UI phrase taken from the snapshot (button/link text, placeholder, aria_label). "
                    "Do NOT output long explanatory sentences. "
                    "Return STRICT JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Task:\n"
                    f"{task}\n\n"
                    "Immediate subgoal:\n"
                    f"{subgoal}\n\n"
                    "Page snapshot (compact JSON):\n"
                    f"{format_snapshot_for_llm(snapshot)}\n\n"
                    "Recent memory:\n"
                    f"{memory}\n\n"
                    "Output JSON schema:\n"
                    "{"
                    '"tool_name":"...",'
                    '"description":"what to click/wait/type",'
                    '"text": "only for type_text_to_field",'
                    '"timeout_ms": 0|number,'
                    '"rationale":"short"'
                    "}"
                ),
            },
        ]
        resp = self._chat.create(messages=messages, tools=None)
        content = resp.choices[0].message.content or "{}"
        data = _parse_json(content)
        return DomSuggestion(
            tool_name=str(data.get("tool_name") or "get_current_page_snapshot"),
            description=str(data.get("description") or ""),
            text=(None if data.get("text") is None else str(data.get("text"))),
            timeout_ms=(None if data.get("timeout_ms") is None else int(data.get("timeout_ms"))),
            rationale=str(data.get("rationale") or ""),
        )
