from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path


ANSI_RESET = "\x1b[0m"
ANSI_GRAY = "\x1b[90m"


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


class GrayFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        if _supports_color():
            return f"{ANSI_GRAY}{s}{ANSI_RESET}"
        return s


@dataclass(frozen=True)
class LoggingConfig:
    verbose: bool
    log_file: Path | None = None


def setup_logging(cfg: LoggingConfig) -> None:
    # Console should be quiet by default: only real problems.
    # Detailed request/tool logs go to the log file.
    console_level = logging.INFO if cfg.verbose else logging.WARNING
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)  # let handlers filter

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(
        GrayFormatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console)

    if cfg.log_file is not None:
        cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(cfg.log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(fh)

    # Make sure request logs are captured (URL, status code).
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.INFO)
