"""Agent framework (Issue #3, #32).

This package provides a lightweight ReAct-style planning layer that can turn a
natural-language request into a multi-step queue of existing Bantz intents.

Issue #32 additions:
- Tool runtime standard (ToolBase, ToolSpec, ToolResult, ToolContext)
- Retry/timeout/circuit-breaker infrastructure
- Fallback mechanism
- Reference web tools
"""

from .core import Agent, AgentState, Step, Task
from .planner import Planner
from .tools import Tool, ToolRegistry

# Back-compat alias (older code/tests may refer to LegacyToolRegistry)
LegacyToolRegistry = ToolRegistry

from .controller import (
    AgentController,
    ControllerState,
    PlanDisplay,
    PlanStepDisplay,
    MockAgentController,
    get_step_icon,
    STEP_STATUS_COLORS,
)

# Issue #32 - Tool Runtime
from .tool_base import (
    ToolBase,
    ToolSpec,
    ToolContext,
    ToolResult,
    ErrorType,
    ToolTimeoutError,
    ToolValidationError,
    DEFAULT_TIMEOUT,
    MIN_TIMEOUT,
    MAX_TIMEOUT,
)

from .circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitStats,
    get_circuit_breaker,
)

from .tool_runner import (
    ToolRunner,
    RunConfig,
    RETRY_DELAYS,
    get_tool_runner,
)

from .fallback import (
    FallbackRunner,
    SimpleToolRegistry,
)

from .web_tools import (
    WebSearchTool,
    WebSearchRequestsTool,
    PageReaderTool,
    FetchUrlTool,
    web_search_tool,
    web_search_requests_tool,
    page_reader_tool,
    fetch_url_tool,
)


__all__ = [
    # Legacy Agent
    "Agent",
    "AgentState",
    "Planner",
    "Step",
    "Task",
    "Tool",
    "ToolRegistry",
    "LegacyToolRegistry",
    "AgentController",
    "ControllerState",
    "PlanDisplay",
    "PlanStepDisplay",
    "MockAgentController",
    "get_step_icon",
    "STEP_STATUS_COLORS",
    # Tool Base (V2-2)
    "ToolBase",
    "ToolSpec",
    "ToolContext",
    "ToolResult",
    "ErrorType",
    "ToolTimeoutError",
    "ToolValidationError",
    "DEFAULT_TIMEOUT",
    "MIN_TIMEOUT",
    "MAX_TIMEOUT",
    # Circuit Breaker (V2-2)
    "CircuitBreaker",
    "CircuitState",
    "CircuitStats",
    "get_circuit_breaker",
    # Tool Runner (V2-2)
    "ToolRunner",
    "RunConfig",
    "RETRY_DELAYS",
    "get_tool_runner",
    # Fallback (V2-2)
    "FallbackRunner",
    "SimpleToolRegistry",
    # Web Tools (V2-2)
    "WebSearchTool",
    "WebSearchRequestsTool",
    "PageReaderTool",
    "FetchUrlTool",
    "web_search_tool",
    "web_search_requests_tool",
    "page_reader_tool",
    "fetch_url_tool",
]
