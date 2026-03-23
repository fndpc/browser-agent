from __future__ import annotations

import json
import logging
import time
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
                "name": "list_tabs",
                "description": "List open browser tabs with their index, url, and title.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "switch_to_tab",
                "description": "Switch active tab by index.",
                "parameters": {
                    "type": "object",
                    "properties": {"index": {"type": "integer"}},
                    "required": ["index"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open_new_tab",
                "description": "Open a new tab and optionally navigate to a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                },
            },
        },
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
                "description": (
                    "Find an element by short UI text/label (e.g. button text, link text, aria-label) and click it. "
                    "Pass a concise phrase that likely appears on the page, not a full sentence."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "allow_repeat": {
                            "type": "boolean",
                            "description": "Set true only if repeating the same click is intended (e.g. increment quantity).",
                        },
                    },
                    "required": ["description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "type_text_to_field",
                "description": (
                    "Find an input field by short label/placeholder/aria-label and type text into it (fill). "
                    "Use press_enter=true for search boxes. Avoid long explanatory sentences."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "text": {"type": "string"},
                        "press_enter": {
                            "type": "boolean",
                            "description": "If true, press Enter after typing (useful for search boxes).",
                        },
                    },
                    "required": ["description", "text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "wait_for_element",
                "description": (
                    "Wait until an element appears, described by short UI text/label/placeholder. "
                    "Use a concise phrase that likely exists on the page."
                ),
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
    recent_clicks: dict[str, float]


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


def _list_tabs(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    return {"ok": True, "tabs": ctx.engine.list_tabs()}


def _switch_tab(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.engine.switch_to_tab(index=int(args["index"]))


def _open_tab(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    url = args.get("url")
    return ctx.engine.open_new_tab(url=(None if url is None else str(url)))


def _snapshot(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    return ctx.engine.get_current_page_snapshot(cfg=ctx.snapshot_cfg)


def _click(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _guard(ctx, tool_name="find_element_and_click", args=args)
    desc = str(args["description"])
    allow_repeat = bool(args.get("allow_repeat", False))
    key = desc.strip().lower()
    now = time.monotonic()
    last = ctx.recent_clicks.get(key)
    if (not allow_repeat) and last is not None and (now - last) < 15.0:
        return {
            "ok": False,
            "error": "duplicate_click_suppressed: same click repeated too soon; set allow_repeat=true if intentional",
        }
    out = ctx.engine.find_element_and_click(description=desc)
    if out.get("ok"):
        ctx.recent_clicks[key] = now
    return out


def _type(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _guard(ctx, tool_name="type_text_to_field", args=args)
    return ctx.engine.type_text_to_field(
        description=str(args["description"]),
        text=str(args["text"]),
        press_enter=bool(args.get("press_enter", False)),
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
    "list_tabs": _list_tabs,
    "switch_to_tab": _switch_tab,
    "open_new_tab": _open_tab,
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

    # Don't run spinner while blocking on user input.
    if name == "confirm_destructive_action":
        log.info("TOOL %s args=%s", name, args)
        res = _TOOL_IMPL[name](ctx, args)
        log.info("TOOL %s result=%s", name, _short(res))
        return res

    msg = _status_hint(name=name, args=args)
    with ctx.ui.loading(msg):
        log.info("TOOL %s args=%s", name, args)
        res = _TOOL_IMPL[name](ctx, args)
        log.info("TOOL %s result=%s", name, _short(res))
    return res


def _status_hint(*, name: str, args: dict[str, Any]) -> str:
    if name == "list_tabs":
        return "Смотрю список вкладок"
    elif name == "switch_to_tab":
        return f"Переключаюсь на вкладку {args.get('index')}"
    elif name == "open_new_tab":
        return f"Открываю новую вкладку {_short_human(args.get('url'), 40)}"
    if name == "navigate_to_url":
        return f"Открываю {_short_human(args.get('url'), 50)}"
    elif name == "get_current_page_snapshot":
        return "Снимаю snapshot страницы"
    elif name == "find_element_and_click":
        return f"Кликаю: {_short_human(args.get('description'))}"
    elif name == "type_text_to_field":
        return f"Ввожу текст в поле: {_short_human(args.get('description'))}"
    elif name == "wait_for_element":
        return f"Жду элемент: {_short_human(args.get('description'))}"
    elif name == "confirm_destructive_action":
        return "Запрашиваю подтверждение пользователя"
    return f"Выполняю: {name}"


def _short(obj: Any, limit: int = 400) -> str:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _short_human(s: Any, limit: int = 60) -> str:
    t = str(s or "").replace("\n", " ").strip()
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)] + "…"
