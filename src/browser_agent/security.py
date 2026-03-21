from __future__ import annotations

import re
import time
from dataclasses import dataclass

from browser_agent.ui import UI


_RISK_PATTERNS = [
    # EN
    r"\bpay\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\border\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bdestroy\b",
    r"\bsend\b",
    r"\bsubmit\b",
    r"\bconfirm\b",
    # RU
    r"\bоплат",
    r"\bкуп(и|ить|лю)",
    r"\bзаказ",
    r"\bудал",
    r"\bстер",
    r"\bотправ",
    r"\bподтверд",
    r"\bсохран",
]


def looks_destructive(action: str) -> bool:
    a = action.strip().lower()
    if not a:
        return False
    return any(re.search(p, a, flags=re.IGNORECASE) for p in _RISK_PATTERNS)


@dataclass
class DestructiveApproval:
    approved_until_monotonic: float = 0.0
    approved_action_hint: str | None = None

    def allow_next_for(self, seconds: int, action_hint: str) -> None:
        self.approved_until_monotonic = time.monotonic() + seconds
        self.approved_action_hint = action_hint

    def consume_if_valid(self) -> bool:
        ok = time.monotonic() <= self.approved_until_monotonic
        # single-use semantics: if it was valid, consume it
        self.approved_until_monotonic = 0.0
        self.approved_action_hint = None
        return ok


def confirm_destructive_action(action: str, *, ui: UI | None = None) -> bool:
    return (ui or UI()).confirm(action)
