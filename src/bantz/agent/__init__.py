"""Agent framework (Issue #3).

This package provides a lightweight ReAct-style planning layer that can turn a
natural-language request into a multi-step queue of existing Bantz intents.
"""

from .core import Agent, AgentState, Step, Task
from .planner import Planner
from .tools import Tool, ToolRegistry
from .controller import (
    AgentController,
    ControllerState,
    PlanDisplay,
    PlanStepDisplay,
    MockAgentController,
    get_step_icon,
    STEP_STATUS_COLORS,
)

__all__ = [
    "Agent",
    "AgentState",
    "Planner",
    "Step",
    "Task",
    "Tool",
    "ToolRegistry",
    "AgentController",
    "ControllerState",
    "PlanDisplay",
    "PlanStepDisplay",
    "MockAgentController",
    "get_step_icon",
    "STEP_STATUS_COLORS",
]
