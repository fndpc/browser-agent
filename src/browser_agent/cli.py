from __future__ import annotations

import argparse
import datetime as _dt
import logging
from pathlib import Path

from browser_agent.agent import AgentConfig, BrowserAgent
from browser_agent.browser_engine import BrowserConfig, BrowserEngine
from browser_agent.logging_utils import LoggingConfig, setup_logging
from browser_agent.openai_client import OpenAIChat, load_openai_config
from browser_agent.ui import UI, UIConfig


log = logging.getLogger("browser_agent.cli")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="browser-agent")
    p.add_argument("--task", type=str, default=None, help="Task in natural language")
    p.add_argument(
        "--profile-dir",
        type=Path,
        default=Path(".browser_profile"),
        help="Persistent Chromium profile directory",
    )
    p.add_argument("--slowmo-ms", type=int, default=0, help="Playwright slow_mo in ms")
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument("--max-seconds", type=int, default=15 * 60)
    p.add_argument("--model", type=str, default=None, help="Override OPENAI_MODEL")
    p.add_argument("--no-subagents", action="store_true", help="Disable sub-agent calls")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors in terminal")
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write debug logs to this file (default: logs/run-<timestamp>.log)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_file = args.log_file
    if log_file is None:
        ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = Path("logs") / f"run-{ts}.log"
    setup_logging(LoggingConfig(verbose=bool(args.verbose), log_file=log_file))
    ui = UI(UIConfig(color=not bool(args.no_color)))
    ui.status(f"Логи пишутся в файл: {log_file}")

    cfg = load_openai_config(model_override=args.model)
    chat = OpenAIChat(cfg)
    log.info("OpenAI model=%s base_url=%s", chat.model, cfg.base_url)

    browser_cfg = BrowserConfig(profile_dir=args.profile_dir, slowmo_ms=int(args.slowmo_ms))
    engine = BrowserEngine(browser_cfg)
    engine.start()

    try:
        agent_cfg = AgentConfig(
            max_steps=int(args.max_steps),
            max_seconds=int(args.max_seconds),
            use_subagents=not bool(args.no_subagents),
        )

        def run_one(task: str) -> None:
            agent = BrowserAgent(chat=chat, engine=engine, cfg=agent_cfg, ui=ui)
            result = agent.run(task)
            ui.result(f"\nRESULT: {result}\n")

        # If a task was provided, run it once first.
        if args.task:
            task0 = args.task.strip()
            if not task0:
                ui.meta("Empty task, exiting.")
                return 2
            run_one(task0)

        ui.meta("Привет! Чем могу помочь?")
        ui.meta("Команды: :exit (выйти), :help (помощь). Любой другой текст = новая задача.")

        # Interactive loop: keep browser/session alive until user exits.
        while True:
            try:
                raw = ui.ask("> ")
            except (EOFError, KeyboardInterrupt):
                ui.status("Выход.")
                break

            task = (raw or "").strip()
            if not task:
                continue
            if task in {":q", ":quit", ":exit", "exit", "quit"}:
                ui.status("Выход.")
                break
            if task in {":help", "help"}:
                ui.meta("Команды: :exit (выйти), :help (помощь).")
                continue

            run_one(task)

        return 0
    finally:
        log.info("Closing browser...")
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
