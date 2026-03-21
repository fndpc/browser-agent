from __future__ import annotations

import argparse
import logging
from pathlib import Path

from browser_agent.agent import AgentConfig, BrowserAgent
from browser_agent.browser_engine import BrowserConfig, BrowserEngine
from browser_agent.logging_utils import setup_logging
from browser_agent.openai_client import OpenAIChat, load_openai_config


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
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(verbose=bool(args.verbose))

    if args.task is None:
        print("Enter a task (example: 'Open https://example.com and click More information'):")
        task = input("> ").strip()
    else:
        task = args.task.strip()

    if not task:
        print("Empty task, exiting.")
        return 2

    cfg = load_openai_config(model_override=args.model)
    chat = OpenAIChat(cfg)

    browser_cfg = BrowserConfig(profile_dir=args.profile_dir, slowmo_ms=int(args.slowmo_ms))
    engine = BrowserEngine(browser_cfg)
    engine.start()

    try:
        agent_cfg = AgentConfig(
            max_steps=int(args.max_steps),
            max_seconds=int(args.max_seconds),
            use_subagents=not bool(args.no_subagents),
        )
        agent = BrowserAgent(chat=chat, engine=engine, cfg=agent_cfg)
        result = agent.run(task)
        print(f"\nRESULT: {result}")
        return 0
    finally:
        log.info("Closing browser...")
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())

