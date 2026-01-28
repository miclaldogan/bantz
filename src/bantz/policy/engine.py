from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from .risk_map import RiskLevel, RiskMap, max_risk
from .session_permits import InMemorySessionPermits


DecisionReason = Literal[
    "LOW_RISK_ALLOW",
    "MED_RISK_REQUIRE_CONFIRMATION",
    "MED_RISK_ALREADY_CONFIRMED",
    "HIGH_RISK_REQUIRE_CONFIRMATION",
    "DENY_BY_POLICY",
]


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "set-cookie",
}


def _mask_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                out[key] = "***"
            else:
                out[key] = _mask_jsonable(v)
        return out
    if isinstance(value, list):
        return [_mask_jsonable(v) for v in value]
    if isinstance(value, str):
        return value if len(value) <= 500 else (value[:499] + "…")
    return value


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_confirmation: bool
    prompt_to_user: str
    reason: DecisionReason
    risk_level: RiskLevel

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "requires_confirmation": bool(self.requires_confirmation),
            "prompt_to_user": str(self.prompt_to_user),
            "reason": str(self.reason),
            "risk_level": str(self.risk_level),
        }


class PolicyEngine:
    """LLM-first policy guardrail for tool execution (Issue #87).

    Semantics:
    - LOW: allow immediately
    - MED: confirm once per session, then remember
    - HIGH: confirm every time (never remembered)

    Also writes a JSONL audit trail if configured.
    """

    def __init__(
        self,
        *,
        risk_map: Optional[RiskMap] = None,
        permits: Optional[InMemorySessionPermits] = None,
        audit_path: Optional[str | Path] = None,
    ):
        self._risk_map = risk_map or RiskMap()
        self._permits = permits or InMemorySessionPermits()

        if audit_path is None:
            env = (os.getenv("BANTZ_POLICY_AUDIT_PATH") or "").strip()
            audit_path = env or None

        self._audit_path: Optional[Path] = Path(audit_path) if audit_path else None

    def check(
        self,
        *,
        session_id: str,
        tool_name: str,
        params: Optional[dict[str, Any]] = None,
        risk_level: RiskLevel = "LOW",
        requires_confirmation: bool = False,
        prompt_to_user: Optional[str] = None,
    ) -> Decision:
        session_id = str(session_id or "default")
        tool_name = str(tool_name or "")
        params = params if isinstance(params, dict) else {}

        # Effective risk = override OR tool risk; and requires_confirmation bumps to at least MED.
        override = self._risk_map.get(tool_name)
        effective: RiskLevel = override or risk_level
        if requires_confirmation:
            effective = max_risk(effective, "MED")

        if effective == "LOW":
            decision = Decision(
                allowed=True,
                requires_confirmation=False,
                prompt_to_user="",
                reason="LOW_RISK_ALLOW",
                risk_level=effective,
            )
            self._audit(
                action="check",
                session_id=session_id,
                tool_name=tool_name,
                params=params,
                decision=decision,
            )
            return decision

        if effective == "MED":
            if self._permits.is_confirmed(session_id=session_id, tool_name=tool_name):
                decision = Decision(
                    allowed=True,
                    requires_confirmation=False,
                    prompt_to_user="",
                    reason="MED_RISK_ALREADY_CONFIRMED",
                    risk_level=effective,
                )
                self._audit(
                    action="check",
                    session_id=session_id,
                    tool_name=tool_name,
                    params=params,
                    decision=decision,
                )
                return decision

            decision = Decision(
                allowed=False,
                requires_confirmation=True,
                prompt_to_user=(
                    prompt_to_user
                    or "Efendim bu işlem için onayınız gerekli. Devam edeyim mi?"
                ),
                reason="MED_RISK_REQUIRE_CONFIRMATION",
                risk_level=effective,
            )
            self._audit(
                action="check",
                session_id=session_id,
                tool_name=tool_name,
                params=params,
                decision=decision,
            )
            return decision

        # HIGH
        decision = Decision(
            allowed=False,
            requires_confirmation=True,
            prompt_to_user=(
                prompt_to_user
                or "Efendim bu işlem yüksek riskli. Onaylıyor musunuz?"
            ),
            reason="HIGH_RISK_REQUIRE_CONFIRMATION",
            risk_level="HIGH",
        )
        self._audit(
            action="check",
            session_id=session_id,
            tool_name=tool_name,
            params=params,
            decision=decision,
        )
        return decision

    def confirm(self, *, session_id: str, tool_name: str, risk_level: RiskLevel) -> None:
        session_id = str(session_id or "default")
        tool_name = str(tool_name or "")
        if risk_level == "MED":
            self._permits.confirm(session_id=session_id, tool_name=tool_name)
        self._audit(
            action="confirm",
            session_id=session_id,
            tool_name=tool_name,
            params={},
            decision=Decision(
                allowed=True,
                requires_confirmation=False,
                prompt_to_user="",
                reason="MED_RISK_ALREADY_CONFIRMED" if risk_level == "MED" else "LOW_RISK_ALLOW",
                risk_level=risk_level,
            ),
        )

    def _audit(
        self,
        *,
        action: str,
        session_id: str,
        tool_name: str,
        params: dict[str, Any],
        decision: Decision,
    ) -> None:
        if self._audit_path is None:
            return

        record = {
            "ts": time.time(),
            "action": str(action),
            "session_id": str(session_id),
            "tool": str(tool_name),
            "params": _mask_jsonable(params),
            "decision": decision.to_dict(),
        }

        try:
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            # Policy must never crash core execution.
            return
