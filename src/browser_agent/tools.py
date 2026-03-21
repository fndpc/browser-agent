from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from browser_agent.browser_engine import BrowserEngine
from browser_agent.dom_snapshot import SnapshotConfig
from browser_agent.security import DestructiveApproval, confirm_destructive_action, looks_destructive
from browser_agent.ui import UI

log = logging.getLogger("browser_agent.tools")


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "navigate_to_url",
                "description": "Navigate the current tab to a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_page_snapshot",
                "description": "Get a compact JSON snapshot of the current page (interactive elements + visible text).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_element_and_click",
                "description": "Find an element by natural-language description and click it.",
                "parameters": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}},
                    "required": ["description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "type_text_to_field",
                "description": "Find an input field by description and type text into it (fill).",
                "parameters": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["description", "text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "wait_for_element",
                "description": "Wait until an element described by natural language appears.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "timeout": {"type": "integer", "description": "Timeout in milliseconds."},
                    },
                    "required": ["description", "timeout"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "confirm_destructive_action",
                "description": "Ask the user for confirmation before destructive actions (payments, deletion, sending).",
                "parameters": {
                    "type": "object",
                    "properties": {"action": {"type": "string"}},
                    "required": ["action"],
                },
            },
        },
    ]


@dataclass
class ToolContext:
    engine: BrowserEngine
    snapshot_cfg: SnapshotConfig
    destructive_approval: DestructiveApproval
    ui: UI


ToolFn = Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def _guard(ctx: ToolContext, *, tool_name: str, args: dict[str, Any]) -> None:
    # Enforce confirmation on suspicious actions even if the model forgets.
    if tool_name in {"find_element_and_click", "type_text_to_field"}:
        desc = str(args.get("description") or "")
        if looks_destructive(desc):
            if not ctx.destructive_approval.consume_if_valid():
                raise PermissionError(
                    "Destructive action requires explicit confirm_destructive_action first"
                )


def _navigate(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.engine.navigate_to_url(url=str(args["url"]))


def _snapshot(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    return ctx.engine.get_current_page_snapshot(cfg=ctx.snapshot_cfg)


def _click(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _guard(ctx, tool_name="find_element_and_click", args=args)
    return ctx.engine.find_element_and_click(description=str(args["description"]))


def _type(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _guard(ctx, tool_name="type_text_to_field", args=args)
    return ctx.engine.type_text_to_field(
        description=str(args["description"]), text=str(args["text"])
    )


def _wait(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.engine.wait_for_element(
        description=str(args["description"]), timeout_ms=int(args["timeout"])
    )


def _confirm(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args["action"])
    ok = confirm_destructive_action(action, ui=ctx.ui)
    if ok:
        # Allow the next "risky" click/type within a short window.
        ctx.destructive_approval.allow_next_for(seconds=30, action_hint=action)
    return {"ok": ok}


_TOOL_IMPL: dict[str, ToolFn] = {
    "navigate_to_url": _navigate,
    "get_current_page_snapshot": _snapshot,
    "find_element_and_click": _click,
    "type_text_to_field": _type,
    "wait_for_element": _wait,
    "confirm_destructive_action": _confirm,
}


def dispatch_tool(ctx: ToolContext, *, name: str, arguments_json: str) -> dict[str, Any]:
    if name not in _TOOL_IMPL:
        raise KeyError(f"Unknown tool: {name}")
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid tool arguments JSON for {name}: {e}") from e

    _status_hint(ctx, name=name, args=args)
    log.info("TOOL %s args=%s", name, args)
    res = _TOOL_IMPL[name](ctx, args)
    log.info("TOOL %s result=%s", name, _short(res))
    return res


def _status_hint(ctx: ToolContext, *, name: str, args: dict[str, Any]) -> None:
    if name == "navigate_to_url":
        ctx.ui.status(f"Открываю {args.get('url')}")
    elif name == "get_current_page_snapshot":
        ctx.ui.status("Снимаю snapshot страницы")
    elif name == "find_element_and_click":
        ctx.ui.status(f"Кликаю: {args.get('description')}")
    elif name == "type_text_to_field":
        ctx.ui.status(f"Ввожу текст в поле: {args.get('description')}")
    elif name == "wait_for_element":
        ctx.ui.status(f"Жду элемент: {args.get('description')}")
    elif name == "confirm_destructive_action":
        ctx.ui.status("Запрашиваю подтверждение пользователя")


def _short(obj: Any, limit: int = 400) -> str:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= limit else s[: limit - 1] + "…"
