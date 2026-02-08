"""bantz.brain — canonical brain/orchestration package.

The only supported entry points are:

- ``create_runtime()``  — build a fully wired runtime (Issue #516)
- ``OrchestratorLoop``  — the canonical orchestrator loop
- ``OrchestratorConfig`` — loop configuration

Legacy orchestrators (brain_loop, unified_loop, gemini_hybrid_orchestrator,
flexible_hybrid_orchestrator, hybrid_orchestrator) were removed in Issue #519.
"""

from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop
from bantz.brain.runtime_factory import BantzRuntime, create_runtime

__all__ = [
    # Canonical runtime factory (Issue #516)
    "BantzRuntime",
    "create_runtime",
    # Canonical orchestrator (the only loop)
    "OrchestratorLoop",
    "OrchestratorConfig",
]
