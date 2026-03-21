from __future__ import annotations

import os
import sys
from dataclasses import dataclass


def _isatty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return _isatty()


ANSI_RESET = "\x1b[0m"
ANSI_GRAY = "\x1b[90m"  # bright black (dark gray)
ANSI_BRIGHT = "\x1b[97m"  # bright white


@dataclass(frozen=True)
class UIConfig:
    color: bool = True


class UI:
    def __init__(self, cfg: UIConfig | None = None):
        self._cfg = cfg or UIConfig()

    def _wrap(self, s: str, code: str) -> str:
        if not self._cfg.color or not _supports_color():
            return s
        return f"{code}{s}{ANSI_RESET}"

    def meta(self, s: str) -> None:
        """Anything that's not the final answer (logs, tool calls, status)."""
        print(self._wrap(s, ANSI_GRAY))

    def status(self, s: str) -> None:
        self.meta(f"STATUS: {s}")

    def result(self, s: str) -> None:
        """Final answer / result for the user."""
        print(self._wrap(s, ANSI_BRIGHT))

    def ask(self, prompt: str) -> str:
        return input(self._wrap(prompt, ANSI_GRAY))

    def confirm(self, action: str) -> bool:
        ans = self.ask(
            f"CONFIRM required: {action}\nType 'y' to proceed, anything else to cancel: "
        ).strip().lower()
        return ans == "y"

