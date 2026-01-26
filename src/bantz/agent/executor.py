from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol
from .tools import ToolRegistry


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class Executor:
    """Execute a step using a provided runner.

    In Bantz, runtime execution usually happens via Router dispatch/queue.
    This class exists to support a standalone agent loop and unit tests.
    """

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def execute(
        self,
        step: "StepLike",
        *,
        runner: Callable[[str, dict[str, Any]], ExecutionResult],
        preview: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        ok, reason = self.tools.validate_call(step.action, step.params)
        if not ok:
            return ExecutionResult(ok=False, error=f"invalid_step:{reason}")

        if preview:
            try:
                preview(step.description)
            except Exception:
                pass

        try:
            return runner(step.action, dict(step.params))
        except Exception as e:
            return ExecutionResult(ok=False, error=str(e))


class StepLike(Protocol):
    action: str
    params: dict[str, Any]
    description: str
