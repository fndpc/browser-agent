from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

log = logging.getLogger("browser_agent.openai")


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str
    base_url: str


def load_openai_config(model_override: str | None = None) -> OpenAIConfig:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = (model_override or os.environ.get("OPENAI_MODEL") or "gpt-4-turbo").strip()
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://ru-2.gateway.nekocode.app/alpha").strip()
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
