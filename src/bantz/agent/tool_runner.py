"""
Tool Runner with Retry, Timeout, and Circuit Breaker (Issue #32 - V2-2).

Orchestrates tool execution with:
- Exponential backoff retry
- Configurable timeout
- Circuit breaker integration
- Event publishing for progress
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from bantz.agent.tool_base import (
    ToolBase,
    ToolContext,
    ToolResult,
    ToolSpec,
    ToolTimeoutError,
    ErrorType,
    DEFAULT_TIMEOUT,
    MIN_TIMEOUT,
    MAX_TIMEOUT,
)
from bantz.agent.circuit_breaker import CircuitBreaker, CircuitState
from bantz.core.events import EventBus, EventType


# Retry delays in seconds (exponential backoff)
RETRY_DELAYS = [1.0, 3.0, 7.0]


@dataclass
class RunConfig:
    """Configuration for a tool run."""
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    skip_circuit_breaker: bool = False


class ToolRunner:
    """
    Runs tools with retry, timeout, and circuit breaker protection.
    
    Features:
    - Automatic retry with exponential backoff
    - Configurable timeout per tool
    - Circuit breaker to prevent cascading failures
    - Event publishing for retry/progress
    
    Example:
        runner = ToolRunner(event_bus, circuit_breaker)
        result = await runner.run(my_tool, {"query": "hello"}, context)
    """
    
    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        circuit_breaker: Optional[CircuitBreaker] = None
    ):
        self.event_bus = event_bus
        self.circuit_breaker = circuit_breaker
    
    async def run(
        self,
        tool: ToolBase,
        input: dict,
        context: ToolContext,
        config: Optional[RunConfig] = None
    ) -> ToolResult:
        """
        Run a tool with full protection.
        
        Args:
            tool: The tool to run
            input: Input parameters
            context: Execution context
            config: Optional run configuration override
            
        Returns:
            ToolResult with success/failure and metadata
        """
        config = config or RunConfig()
        spec = tool.spec()
        
        # Validate input
        is_valid, error = tool.validate_input(input)
        if not is_valid:
            return ToolResult.fail(
                error=error,
                error_type=ErrorType.VALIDATION
            )
        
        # Check circuit breaker
        domain = self._get_domain(tool, input)
        if self.circuit_breaker and not config.skip_circuit_breaker:
            if self.circuit_breaker.is_open(domain):
                return ToolResult.fail(
                    error=f"Circuit breaker open for {domain}",
                    error_type=ErrorType.NETWORK,
                    metadata={"circuit_open": True}
                )
        
        # Run with retry
        result = await self._run_with_retry(
            tool, input, context,
            timeout=config.timeout or spec.timeout,
            max_retries=config.max_retries if config.max_retries is not None else spec.max_retries
        )
        
        # Record circuit breaker status
        if self.circuit_breaker and not config.skip_circuit_breaker:
            if result.success:
                self.circuit_breaker.record_success(domain)
            else:
                self.circuit_breaker.record_failure(domain)
        
        return result
    
    async def _run_with_retry(
        self,
        tool: ToolBase,
        input: dict,
        context: ToolContext,
        timeout: float,
        max_retries: int
    ) -> ToolResult:
        """
        Run tool with retry logic.
        
        Implements exponential backoff: 1s, 3s, 7s delays.
        """
        retries_used = 0
        last_error = None
        last_error_type = ErrorType.UNKNOWN
        start_time = time.time()
        
        for attempt in range(max_retries + 1):
            try:
                # Run with timeout
                result = await self._run_with_timeout(
                    tool, input, context, timeout
                )
                
                if result.success:
                    result.retries_used = retries_used
                    result.duration_ms = (time.time() - start_time) * 1000
                    return result
                
                # Tool returned failure
                last_error = result.error
                last_error_type = result.error_type or ErrorType.UNKNOWN
                
            except ToolTimeoutError:
                last_error = f"Tool '{tool.name}' timed out after {timeout}s"
                last_error_type = ErrorType.TIMEOUT
                
            except asyncio.CancelledError:
                raise
                
            except Exception as e:
                last_error = str(e)
                last_error_type = ErrorType.UNKNOWN
            
            # If not last attempt, wait and retry
            if attempt < max_retries:
                retries_used += 1
                delay = self._get_retry_delay(attempt)
                
                # Publish retry event
                self._emit_retry_event(context, tool, attempt + 1, delay)
                
                await asyncio.sleep(delay)
        
        # All retries exhausted
        duration_ms = (time.time() - start_time) * 1000
        return ToolResult.fail(
            error=last_error or "Unknown error after retries",
            error_type=last_error_type,
            duration_ms=duration_ms,
            retries_used=retries_used
        )
    
    async def _run_with_timeout(
        self,
        tool: ToolBase,
        input: dict,
        context: ToolContext,
        timeout: float
    ) -> ToolResult:
        """
        Run tool with timeout protection.
        
        Raises ToolTimeoutError if timeout exceeded.
        """
        # Normalize timeout bounds
        timeout = max(MIN_TIMEOUT, min(timeout, MAX_TIMEOUT))
        
        try:
            result = await asyncio.wait_for(
                tool.run(input, context),
                timeout=timeout
            )
            return result
            
        except asyncio.TimeoutError:
            raise ToolTimeoutError(
                f"Tool '{tool.name}' timed out after {timeout}s"
            )
    
    def _get_retry_delay(self, attempt: int) -> float:
        """Get delay before retry (exponential backoff)."""
        if attempt < len(RETRY_DELAYS):
            return RETRY_DELAYS[attempt]
        return RETRY_DELAYS[-1]  # Use last delay for additional retries
    
    def _get_domain(self, tool: ToolBase, input: dict) -> str:
        """Extract domain from tool/input for circuit breaker."""
        # Try to extract URL domain
        if "url" in input:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(input["url"])
                if parsed.netloc:
                    return parsed.netloc
            except Exception:
                pass
        
        # Use tool name as domain
        return tool.name
    
    def _emit_retry_event(
        self,
        context: ToolContext,
        tool: ToolBase,
        attempt: int,
        delay: float
    ) -> None:
        """Publish retry event to event bus."""
        if self.event_bus:
            self.event_bus.publish(
                event_type=EventType.RETRY.value,
                data={
                    "job_id": context.job_id,
                    "tool": tool.name,
                    "attempt": attempt,
                    "delay": delay
                },
                source="tool_runner"
            )


# Singleton instance
_tool_runner: Optional[ToolRunner] = None


def get_tool_runner(
    event_bus: Optional[EventBus] = None,
    circuit_breaker: Optional[CircuitBreaker] = None
) -> ToolRunner:
    """Get or create the global ToolRunner instance."""
    global _tool_runner
    if _tool_runner is None:
        _tool_runner = ToolRunner(event_bus, circuit_breaker)
    return _tool_runner
