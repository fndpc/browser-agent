from __future__ import annotations

import logging
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

log = logging.getLogger("browser_agent.openai")


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str
    base_url: str


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _load_dotenv_from(start_dir: Path) -> None:
    """
    Minimal .env loader (no extra dependency).
    - Searches for `.env` from start_dir up to filesystem root.
    - Sets os.environ only if key is not already set.
    """
    cur = start_dir.resolve()
    while True:
        env_path = cur / ".env"
        if env_path.is_file():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = _strip_quotes(v.strip())
                if k and k not in os.environ:
                    os.environ[k] = v
            return
        if cur.parent == cur:
            return
        cur = cur.parent


def load_openai_config(model_override: str | None = None) -> OpenAIConfig:
    _load_dotenv_from(Path.cwd())
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = (model_override or os.environ.get("OPENAI_MODEL") or "gpt-4-turbo").strip()
    # Default to official OpenAI endpoint unless the user overrides via OPENAI_BASE_URL.
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()
    # OpenAI SDK expects base_url to include the API prefix (`/v1`), because it calls `/chat/completions`, etc.
    # Your gateway uses openai-compatible endpoints under `/v1/...`.
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAIConfig(api_key=api_key, model=model, base_url=base_url)


class OpenAIChat:
    def __init__(self, cfg: OpenAIConfig):
        self._cfg = cfg
        self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    @property
    def model(self) -> str:
        return self._cfg.model

    def create(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Any:
        # Chat Completions supports tool calls with `tools` parameter in openai>=1.x
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
        }
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        log.debug("OpenAI request: model=%s messages=%d tools=%s", self._cfg.model, len(messages), bool(tools))
        return self._client.chat.completions.create(**kwargs)
