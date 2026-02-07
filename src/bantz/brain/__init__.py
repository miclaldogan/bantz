from bantz.brain.brain_loop import (
    BrainLoop,
    BrainLoopConfig,
    BrainResult,
    LLMClient,
    BrainTranscriptTurn,
    Say,
    AskUser,
    CallTool,
    Fail,
)
from bantz.brain.unified_loop import (
    UnifiedBrain,
    UnifiedConfig,
    UnifiedResult,
    create_brain,
)

__all__ = [
    # Legacy — prefer UnifiedBrain / create_brain() for new code.
    "BrainLoop",
    "BrainLoopConfig",
    "BrainResult",
    "LLMClient",
    "BrainTranscriptTurn",
    "Say",
    "AskUser",
    "CallTool",
    "Fail",
    # Unified interface (Issue #403)
    "UnifiedBrain",
    "UnifiedConfig",
    "UnifiedResult",
    "create_brain",
]
