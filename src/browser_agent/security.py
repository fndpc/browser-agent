from __future__ import annotations

import re
import time
from dataclasses import dataclass

from browser_agent.ui import UI


_RISK_PATTERNS = [
    # Payments / orders
    r"\bpay\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\border\b",
    r"\bоплат",
    r"\bкуп(и|ить|лю)",
    r"\bзаказ",
    # Deletion / irreversible changes
    r"\bdelete\b",
    r"\bremove\b",
    r"\bdestroy\b",
    r"\bудал",
    r"\bстер",
    r"\bочист",
    # Sending/publishing (narrowed: don't block "send search", etc.)
    r"\bsend\b.*\b(email|message|form|order)\b",
    r"\bотправ(ить|лю|ка)\b.*\b(письм|сообщ|форм|заказ|данн)\b",
]


def looks_destructive(action: str) -> bool:
    a = action.strip().lower()
    if not a:
        return False
    # Searching/submitting a search query is not destructive.
    if re.search(r"\b(search|поиск|запрос)\b", a, flags=re.IGNORECASE):
        # If it also contains a clear destructive keyword, still treat as risky.
        if not re.search(r"\b(delete|remove|destroy|удал|стер|оплат|checkout|buy|purchase)\b", a):
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
