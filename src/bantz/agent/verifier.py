from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .executor import ExecutionResult


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str = ""


class Verifier:
    """Step verification.

    Default policy: trust the tool/runner's ok flag.
    """

    def verify(self, step: "StepLike", result: ExecutionResult) -> VerificationResult:
        if result.ok:
            return VerificationResult(ok=True)
        return VerificationResult(ok=False, reason=result.error or "failed")


class StepLike(Protocol):
    pass
