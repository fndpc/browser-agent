from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
import uuid

from browser_agent.dom_snapshot import SnapshotConfig, format_snapshot_for_llm
from browser_agent.openai_client import OpenAIChat
from browser_agent.security import DestructiveApproval
from browser_agent.subagents import DOMAgent, NavigationAgent
from browser_agent.tools import ToolContext, dispatch_tool, tool_schemas
from browser_agent.ui import UI

log = logging.getLogger("browser_agent.agent")


@dataclass
class AgentConfig:
    max_steps: int = 40
    max_seconds: int = 15 * 60
    use_subagents: bool = True
    snapshot_cfg: SnapshotConfig = field(default_factory=SnapshotConfig)


@dataclass
class AgentMemory:
    last_snapshots: list[dict[str, Any]] = field(default_factory=list)
    step_log: list[str] = field(default_factory=list)

    def add_snapshot(self, snap: dict[str, Any]) -> None:
        self.last_snapshots.append(snap)
        self.last_snapshots = self.last_snapshots[-2:]

    def add_step(self, s: str) -> None:
        self.step_log.append(s)
        self.step_log = self.step_log[-20:]

    def summary(self) -> str:
        return "\n".join(self.step_log[-12:])


def _parse_json(content: str) -> dict[str, Any] | None:
    try:
        return json.loads(content)
    except Exception:
        return None


def _tool_call_to_dict(tc: Any) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
    }


def _tool_call_id(tc: Any) -> str:
    tid = getattr(tc, "id", None)
    if isinstance(tid, str) and tid.strip():
        return tid
    # Some gateways/SDK combinations can produce missing tool call ids; keep the request valid.
    return "call_local_" + uuid.uuid4().hex


class BrowserAgent:
    def __init__(self, *, chat: OpenAIChat, engine, cfg: AgentConfig, ui: UI):
        self._chat = chat
        self._engine = engine
        self._cfg = cfg
        self._ui = ui
        self._memory = AgentMemory()
        self._approval = DestructiveApproval()
        self._tools = tool_schemas()

        self._nav_agent = NavigationAgent(chat) if cfg.use_subagents else None
        self._dom_agent = DOMAgent(chat) if cfg.use_subagents else None

    def run(self, task: str) -> str:
        start = time.monotonic()

        tool_ctx = ToolContext(
            engine=self._engine,
            snapshot_cfg=self._cfg.snapshot_cfg,
            destructive_approval=self._approval,
            ui=self._ui,
        )

        # Boot snapshot into memory (logged as a tool call).
        snap = dispatch_tool(tool_ctx, name="get_current_page_snapshot", arguments_json="{}")
        self._memory.add_snapshot(snap)

        plan = self._build_plan(task=task, snapshot=snap)
        self._memory.add_step(f"PLAN: {plan}")
        self._ui.status("Начинаю выполнение плана")

        for step_idx in range(1, self._cfg.max_steps + 1):
            if time.monotonic() - start > self._cfg.max_seconds:
                return "Stopped: time limit reached."

            final = self._step(
                step_idx=step_idx,
                task=task,
                plan=plan,
                tool_ctx=tool_ctx,
            )
            if final is not None:
                return final

        return "Stopped: step limit reached."

    def _step(
        self,
        *,
        step_idx: int,
        task: str,
        plan: str,
        tool_ctx: ToolContext,
    ) -> str | None:
        """
        Run a bounded tool-calling micro-loop. We intentionally keep only a compact "state"
        (last 1-2 snapshots + step log) rather than an ever-growing chat history.
        """
        snap = self._memory.last_snapshots[-1] if self._memory.last_snapshots else {}
        sub_hints, nav_subgoal = self._subagent_hints(task=task)
        if nav_subgoal:
            self._ui.status(nav_subgoal)

        user_state = {
            "task": task,
            "plan": plan,
            "memory": self._memory.summary(),
            "page": {"url": snap.get("url"), "title": snap.get("title")},
            "snapshot": snap,
        }

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are the main browser automation agent. "
                    "You MUST use tools to act. "
                    "Never request or output full HTML. "
                    "Whenever you call tools, include a short user-facing sentence in `content` "
                    "describing what you are about to do. "
                    "When calling tools that take `description`, use a SHORT UI phrase (button text, link text, placeholder, aria-label), "
                    "not a full explanation."
                    "Tabs: keep tasks on separate tabs when requested. "
                    "Use open_new_tab(url) to open a new tab and switch_to_tab(index) to return. "
                    "Do NOT navigate an existing tab to a different site unless explicitly asked; prefer opening a new tab."
                    "Only call confirm_destructive_action for truly destructive/irreversible actions "
                    "(payments, deleting data, sending messages/forms). "
                    "Typing a search query and running a search is NOT destructive. "
                    "If you need clarification, output JSON: "
                    '{"status":"need_clarification","question":"..."} '
                    "If the task is done, output JSON: "
                    '{"status":"done","result":"..."}'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Current state (JSON):\n"
                    + json.dumps(user_state, ensure_ascii=False)
                    + ("\n\n" + sub_hints if sub_hints else "")
                ),
            },
        ]

        for hop in range(1, 8):
            with self._ui.loading("Думаю"):
                resp = self._chat.create(messages=messages, tools=self._tools)
            msg = resp.choices[0].message

            if msg.tool_calls:
                # If the model included a user-facing line alongside tool calls, show it.
                if msg.content and msg.content.strip():
                    self._ui.assistant(msg.content.strip())
                # Ensure every tool call has a non-empty id.
                tc_pairs: list[tuple[Any, str]] = [(tc, _tool_call_id(tc)) for tc in msg.tool_calls]
                tc_dicts = [
                    {
                        "id": tid,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for (tc, tid) in tc_pairs
                ]
                messages.append({"role": "assistant", "content": "", "tool_calls": tc_dicts})

                # Execute tools and ALWAYS append a tool message for every tool_call_id.
                expected_ids = [d["id"] for d in tc_dicts]
                responded_ids: set[str] = set()
                post_tool_user_messages: list[str] = []

                for tc, tc_id in tc_pairs:
                    name = tc.function.name
                    args_json = tc.function.arguments
                    self._memory.add_step(f"STEP {step_idx}.{hop}: tool={name} args={args_json}")
                    out: dict[str, Any]
                    fatal: BaseException | None = None
                    try:
                        out = dispatch_tool(tool_ctx, name=name, arguments_json=args_json)
                    except BaseException as e:
                        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                        # Keep the request history consistent, but allow the process to stop afterwards.
                        if isinstance(e, (KeyboardInterrupt, SystemExit)):
                            fatal = e
                    finally:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(out, ensure_ascii=False),
                            }
                        )
                        responded_ids.add(tc_id)
                    if fatal is not None:
                        raise fatal

                    if name == "get_current_page_snapshot" and isinstance(out, dict) and out.get("url"):
                        self._memory.add_snapshot(out)
                    elif name in {"navigate_to_url", "find_element_and_click"} and isinstance(out, dict) and out.get("ok"):
                        # Refresh snapshot after navigation/click to keep state fresh.
                        refreshed = dispatch_tool(tool_ctx, name="get_current_page_snapshot", arguments_json="{}")
                        self._memory.add_snapshot(refreshed)

                    if isinstance(out, dict) and out.get("ok") is False:
                        err_txt = str(out.get("error") or "")
                        if "not enabled" in err_txt or "is not enabled" in err_txt:
                            post_tool_user_messages.append(
                                "The target element appears DISABLED (not enabled). "
                                "This often means a prerequisite isn't satisfied (e.g. choose delivery address/region, "
                                "close a modal/consent banner, or pick a store). "
                                "Ask the user to complete the prerequisite in the visible browser if needed, then continue."
                            )
                        post_tool_user_messages.append(
                            f"Tool {name} failed with: {out}. "
                            "Retry with a different description, wait, re-snapshot, or ask for clarification."
                        )

                # Safety net: never send a tool_call without a tool response in the next request.
                missing = [tid for tid in expected_ids if tid not in responded_ids]
                for tid in missing:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tid,
                            "content": json.dumps(
                                {
                                    "ok": False,
                                    "error": "internal_error: missing tool response (auto-filled)",
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )

                # Only after ALL tool_call_ids are responded to, we may append user guidance.
                for txt in post_tool_user_messages:
                    messages.append({"role": "user", "content": txt})
                continue

            content = (msg.content or "").strip()
            self._memory.add_step(f"STEP {step_idx}.{hop}: assistant={content[:200]}")

            # If the assistant decided to speak to the user (thoughts/instructions), show it.
            if content:
                # Don't show raw JSON control frames.
                if not (content.startswith("{") and content.endswith("}")):
                    self._ui.assistant(content)

            data = _parse_json(content)
            if data and data.get("status") == "need_clarification":
                q = str(data.get("question") or "Please уточните.")
                answer = self._ui.ask(f"AGENT QUESTION: {q}\nYour answer: ").strip()
                self._memory.add_step(f"USER clarification: {answer}")
                messages.append({"role": "user", "content": f"User clarification: {answer}"})
                continue

            if data and data.get("status") == "done":
                return str(data.get("result") or "Done.")

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue by calling tools. "
                        "If you believe the task is done, return JSON {\"status\":\"done\",\"result\":\"...\"}."
                    ),
                }
            )

        return None

    def _build_plan(self, *, task: str, snapshot: dict[str, Any]) -> str:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a planner for browser automation. "
                    "Create a short, multi-step plan (3-10 steps). "
                    "Do NOT include hard-coded selectors. "
                    "Output plain text."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Task:\n"
                    f"{task}\n\n"
                    "Current URL/title:\n"
                    f"{snapshot.get('url','')} | {snapshot.get('title','')}\n"
                ),
            },
        ]
        resp = self._chat.create(messages=messages, tools=None)
        return (resp.choices[0].message.content or "").strip()

    def _subagent_hints(self, *, task: str) -> tuple[str | None, str | None]:
        if not self._cfg.use_subagents:
            return None, None
        if not self._memory.last_snapshots:
            return None, None
        snap = self._memory.last_snapshots[-1]
        memory = self._memory.summary()

        hints: dict[str, Any] = {}
        nav_subgoal: str | None = None

        try:
            if self._nav_agent is not None:
                nav = self._nav_agent.suggest(task=task, snapshot=snap, memory=memory)
                nav_subgoal = nav.next_subgoal.strip() or None
                hints["navigation_agent"] = {
                    "should_navigate": nav.should_navigate,
                    "url": nav.url,
                    "next_subgoal": nav.next_subgoal,
                    "rationale": nav.rationale,
                }
            subgoal = (
                hints.get("navigation_agent", {}).get("next_subgoal")
                if hints.get("navigation_agent")
                else "Make progress towards the task"
            )
            if self._dom_agent is not None:
                dom = self._dom_agent.suggest(task=task, snapshot=snap, memory=memory, subgoal=subgoal)
                hints["dom_agent"] = {
                    "tool_name": dom.tool_name,
                    "description": dom.description,
                    "text": dom.text,
                    "timeout_ms": dom.timeout_ms,
                    "rationale": dom.rationale,
                }
        except Exception as e:
            log.debug("Subagent hints failed: %s", e)
            return None, None

        return (
            "Sub-agent hints (JSON, advisory only):\n" + json.dumps(hints, ensure_ascii=False),
            nav_subgoal,
        )
