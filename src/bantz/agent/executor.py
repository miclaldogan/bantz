from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol
from .tools import ToolRegistry


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    awaiting_confirmation: bool = False
    confirmation_prompt: str | None = None
    risk_level: str | None = None


class Executor:
    """Execute a step using a provided runner.

    In Bantz, runtime execution usually happens via Router dispatch/queue.
    This class exists to support a standalone agent loop and unit tests.
    
    Confirmation Firewall (Issue #160):
    - DESTRUCTIVE tools require user confirmation
    - LLM cannot override this requirement
    - Returns awaiting_confirmation=True until confirmed
    """

    def __init__(self, tools: ToolRegistry, confirmed_actions: Optional[set[str]] = None):
        self.tools = tools
        self.confirmed_actions = confirmed_actions or set()

    def execute(
        self,
        step: "StepLike",
        *,
        runner: Callable[[str, dict[str, Any]], ExecutionResult],
        preview: Optional[Callable[[str], None]] = None,
        skip_confirmation: bool = False,
    ) -> ExecutionResult:
        """Execute a step with confirmation firewall.
        
        Args:
            step: Step to execute
            runner: Function to run the tool
            preview: Optional preview callback
            skip_confirmation: Skip confirmation check (for testing)
        
        Returns:
            ExecutionResult with ok/error/awaiting_confirmation status
        """
        # Import here to avoid circular dependency
        from bantz.tools.metadata import (
            get_tool_risk,
            is_destructive,
            get_confirmation_prompt,
        )
        
        ok, reason = self.tools.validate_call(step.action, step.params)
        if not ok:
            return ExecutionResult(ok=False, error=f"invalid_step:{reason}")

        # Check if tool is destructive and needs confirmation
        risk = get_tool_risk(step.action)
        
        if not skip_confirmation and is_destructive(step.action):
            # Check if this action is already confirmed
            action_key = f"{step.action}:{hash(frozenset(step.params.items()))}"
            
            if action_key not in self.confirmed_actions:
                # Need confirmation
                prompt = get_confirmation_prompt(step.action, step.params)
                return ExecutionResult(
                    ok=False,
                    awaiting_confirmation=True,
                    confirmation_prompt=prompt,
                    risk_level=risk.value,
                )
            
            # Action was confirmed, remove from set and proceed
            self.confirmed_actions.discard(action_key)

        if preview:
            try:
                preview(step.description)
            except Exception:
                pass

        try:
            result = runner(step.action, dict(step.params))
            # Add risk level to result
            return ExecutionResult(
                ok=result.ok,
                data=result.data,
                error=result.error,
                risk_level=risk.value,
            )
        except Exception as e:
            return ExecutionResult(
                ok=False,
                error=str(e),
                risk_level=risk.value,
            )
    
    def confirm_action(self, step: "StepLike") -> None:
        """Confirm a destructive action for execution.
        
        Args:
            step: Step to confirm
        """
        action_key = f"{step.action}:{hash(frozenset(step.params.items()))}"
        self.confirmed_actions.add(action_key)


class StepLike(Protocol):
    action: str
    params: dict[str, Any]
    description: str
