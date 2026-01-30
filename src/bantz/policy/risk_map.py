from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


RiskLevel = Literal["LOW", "MED", "HIGH"]


_RISK_ORDER: dict[RiskLevel, int] = {"LOW": 0, "MED": 1, "HIGH": 2}


def max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b


@dataclass
class RiskMap:
    """Optional tool->risk overrides.

    If a tool isn't present, caller/tool spec risk_level is used.
    """

    overrides: dict[str, RiskLevel] = field(default_factory=dict)

    def get(self, tool_name: str) -> Optional[RiskLevel]:
        value = self.overrides.get(str(tool_name))
        if value in {"LOW", "MED", "HIGH"}:
            return value
        return None
