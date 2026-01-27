"""
Bantz Conversation Engine Module (V2-6).

Conversation state machine, barge-in handling, and feedback phrases:
- FSM: idle → listening → thinking → speaking → idle
- Barge-in: TTS stops when user interrupts
- Feedback: Standard acknowledgment/error/confirmation phrases
"""

from bantz.conversation.fsm import (
    ConversationState,
    StateTransition,
    ConversationFSM,
    TRIGGER_WAKEWORD,
    TRIGGER_SPEECH_START,
    TRIGGER_SPEECH_END,
    TRIGGER_THINKING_START,
    TRIGGER_THINKING_DONE,
    TRIGGER_SPEAKING_START,
    TRIGGER_SPEAKING_DONE,
    TRIGGER_BARGE_IN,
    TRIGGER_TIMEOUT,
)
from bantz.conversation.bargein import (
    BargeInAction,
    BargeInEvent,
    BargeInHandler,
)
from bantz.conversation.feedback import (
    FeedbackType,
    FeedbackPhrase,
    FeedbackRegistry,
)
from bantz.conversation.context import (
    TurnInfo,
    ConversationContext,
)
from bantz.conversation.orchestrator import (
    ConversationOrchestrator,
)

__all__ = [
    # FSM
    "ConversationState",
    "StateTransition",
    "ConversationFSM",
    "TRIGGER_WAKEWORD",
    "TRIGGER_SPEECH_START",
    "TRIGGER_SPEECH_END",
    "TRIGGER_THINKING_START",
    "TRIGGER_THINKING_DONE",
    "TRIGGER_SPEAKING_START",
    "TRIGGER_SPEAKING_DONE",
    "TRIGGER_BARGE_IN",
    "TRIGGER_TIMEOUT",
    # Barge-in
    "BargeInAction",
    "BargeInEvent",
    "BargeInHandler",
    # Feedback
    "FeedbackType",
    "FeedbackPhrase",
    "FeedbackRegistry",
    # Context
    "TurnInfo",
    "ConversationContext",
    # Orchestrator
    "ConversationOrchestrator",
]
