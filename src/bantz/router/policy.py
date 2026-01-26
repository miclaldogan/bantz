from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bantz.router.types import PolicyDecision


# Risky click text patterns (case-insensitive)
RISKY_CLICK_PATTERNS = [
    r"\b(send|gönder|paylaş|post|share|submit)\b",
    r"\b(pay|ödeme|öde|satın\s+al|purchase|buy|checkout)\b",
    r"\b(delete|sil|kaldır|remove)\b",
    r"\b(confirm|onayla|approve)\b",
    r"\b(sign\s+out|log\s*out|çıkış|oturumu\s+kapat)\b",
]


@dataclass(frozen=True)
class Policy:
    deny_patterns: tuple[re.Pattern[str], ...]
    confirm_patterns: tuple[re.Pattern[str], ...]
    deny_even_if_confirmed_patterns: tuple[re.Pattern[str], ...]
    intent_levels: dict[str, PolicyDecision]
    risky_click_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)

    @staticmethod
    def from_json_file(path: str | Path) -> "Policy":
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))

        deny = tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in data.get("deny_patterns", []))
        confirm = tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in data.get("confirm_patterns", []))
        deny_even = tuple(
            re.compile(pattern, flags=re.IGNORECASE) for pattern in data.get("deny_even_if_confirmed_patterns", [])
        )

        # Custom risky click patterns from config, or use defaults
        risky_click_raw = data.get("risky_click_patterns", RISKY_CLICK_PATTERNS)
        risky_click = tuple(re.compile(p, flags=re.IGNORECASE) for p in risky_click_raw)

        raw_levels = data.get("intent_levels", {})
        # default: unknown is deny unless explicitly set
        levels: dict[str, PolicyDecision] = {"unknown": "deny"}
        for k, v in raw_levels.items():
            if v not in {"allow", "confirm", "deny"}:
                continue
            levels[str(k)] = v

        return Policy(
            deny_patterns=deny,
            confirm_patterns=confirm,
            deny_even_if_confirmed_patterns=deny_even,
            intent_levels=levels,
            risky_click_patterns=risky_click,
        )

    def is_denied(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self.deny_patterns)

    def _matches(self, patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
        return any(p.search(text) for p in patterns)

    def is_risky_click(self, element_text: str) -> bool:
        """Check if clicking this element text is risky."""
        return self._matches(self.risky_click_patterns, element_text)

    def decide(self, *, text: str, intent: str, confirmed: bool = False, click_target: str | None = None) -> tuple[PolicyDecision, str]:
        """Return (decision, reason).

        - deny_patterns: immediate deny
        - confirm_patterns: ask confirmation (unless already confirmed)
        - deny_even_if_confirmed_patterns: still deny after confirmation ("asla")
        - intent_levels: default action-level decision
        - click_target: if browser_click, check element text for risky patterns
        """

        if self._matches(self.deny_patterns, text):
            return "deny", "deny_pattern"

        if confirmed and self._matches(self.deny_even_if_confirmed_patterns, text):
            return "deny", "deny_even_if_confirmed"

        # Intent-level decision
        intent_level = self.intent_levels.get(intent, self.intent_levels.get("unknown", "deny"))

        # Risky click check
        if intent == "browser_click" and click_target and not confirmed:
            if self.is_risky_click(click_target):
                return "confirm", f"risky_click:{click_target[:30]}"

        # Pattern-based override
        if self._matches(self.confirm_patterns, text):
            if confirmed:
                # confirmed -> allow unless denied above
                return "allow", "confirmed"
            return "confirm", "confirm_pattern"

        if intent_level == "confirm" and not confirmed:
            return "confirm", "intent_confirm"
        if intent_level == "deny":
            return "deny", "intent_deny"

        return "allow", "intent_allow"
