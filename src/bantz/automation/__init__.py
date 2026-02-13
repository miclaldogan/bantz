"""
V2-8: Agentic automation v1 (PEV + templates + fail-safe).

This module provides Planner-Executor-Verifier (PEV) automation framework
with task templates and fail-safe handling.
"""

from bantz.automation.plan import (
    StepStatus,
    PlanStep,
    TaskPlan,
    create_task_plan,
)

from bantz.automation.planner import (
    Planner,
    create_planner,
)

from bantz.automation.executor import (
    ExecutionResult,
    Executor,
    create_executor,
)

from bantz.automation.verifier import (
    VerificationResult,
    Verifier,
    create_verifier,
)

from bantz.automation.failsafe import (
    FailSafeAction,
    FailSafeChoice,
    FailSafeHandler,
    create_failsafe_handler,
)

from bantz.automation.templates import (
    TaskTemplate,
    TemplateRegistry,
    create_template_registry,
)

from bantz.automation.orchestrator import (
    PEVOrchestrator,
    create_pev_orchestrator,
)

from bantz.automation.overnight import (
    OvernightRunner,
    OvernightState,
    OvernightTask,
    OvernightFailSafe,
    ResourceMonitor,
    is_overnight_request,
    parse_overnight_tasks,
    resume_overnight,
    generate_morning_report,
)

__all__ = [
    # Plan
    "StepStatus",
    "PlanStep",
    "TaskPlan",
    "create_task_plan",
    # Planner
    "Planner",
    "create_planner",
    # Executor
    "ExecutionResult",
    "Executor",
    "create_executor",
    # Verifier
    "VerificationResult",
    "Verifier",
    "create_verifier",
    # Fail-safe
    "FailSafeAction",
    "FailSafeChoice",
    "FailSafeHandler",
    "create_failsafe_handler",
    # Templates
    "TaskTemplate",
    "TemplateRegistry",
    "create_template_registry",
    # Orchestrator
    "PEVOrchestrator",
    "create_pev_orchestrator",
    # Overnight (Issue #836)
    "OvernightRunner",
    "OvernightState",
    "OvernightTask",
    "OvernightFailSafe",
    "ResourceMonitor",
    "is_overnight_request",
    "parse_overnight_tasks",
    "resume_overnight",
    "generate_morning_report",
]
