from __future__ import annotations

import os
import sys
import threading
import time
import shutil
from contextlib import contextmanager
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
        self.meta(s)

    def assistant(self, s: str) -> None:
        """Assistant messages / 'thoughts' shown to the user."""
        print(self._wrap(s, ANSI_BRIGHT))

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

    @contextmanager
    def loading(self, message: str) -> None:
        """
        Non-blocking spinner so the user sees the app is working.
        Uses a single terminal line and clears it when done.
        """
        if not _isatty():
            # Non-interactive: print a single status line.
            self.status(message + " ...")
            yield
            return

        stop = threading.Event()
        frames = [".", "..", "..."]
        msg = (message or "").replace("\n", " ").strip()
        try:
            width = shutil.get_terminal_size().columns
        except Exception:
            width = 80
        # Keep it on a single line to avoid wrap spam.
        max_msg = max(10, width - 6)
        if len(msg) > max_msg:
            msg = msg[: max_msg - 1] + "…"
        prefix = self._wrap(msg + " ", ANSI_GRAY)

        def run() -> None:
            i = 0
            while not stop.is_set():
                frame = frames[i % len(frames)]
                line = prefix + frame
                sys.stdout.write("\r" + line)
                sys.stdout.flush()
                i += 1
                time.sleep(0.35)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join(timeout=1.0)
            # Clear the spinner line.
            sys.stdout.write("\r" + (" " * (width - 1)) + "\r")
            sys.stdout.flush()
