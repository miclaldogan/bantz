"""Active Learning Feedback Loop (Issue #876).

Wires the disconnected learning subsystem into the orchestrator:

- ``PreferenceIntegration`` (Issue #441 bridge)
- ``BehavioralLearner`` (reward signals, Q-learning)
- ``AdaptiveResponse`` (style adaptation)
- ``ContextualBandit`` (epsilon-greedy exploration)

Provides a single ``FeedbackLoop`` facade that orchestrator_loop.py
calls at key pipeline stages (turn start, post-tool, finalization).

Three learning modes:
1. **Implicit** — observe every turn (tool usage, timing, choices)
2. **Explicit** — ask when confidence < threshold
3. **Correction** — accept user corrections and update profile
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Confidence threshold: above → auto-decide, below → ask user
CONFIDENCE_AUTO_THRESHOLD = 0.90

# Exploration rate (ε-greedy: 10% explore, 90% exploit)
DEFAULT_EXPLORATION_EPSILON = 0.10

# Correction detection patterns (Turkish)
_CORRECTION_PREFIXES = (
    "hayır",
    "yanlış",
    "hatalı",
    "düzelt",
    "aslında",
    "yok yok",
    "öyle değil",
    "her zaman",
)


@dataclass
class FeedbackEvent:
    """A single feedback event for the learning pipeline."""

    event_type: str  # "turn" | "tool" | "correction" | "cancellation" | "choice"
    intent: str = ""
    tool_name: str = ""
    success: bool = True
    duration_ms: float = 0.0
    user_input: str = ""
    assistant_reply: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class FeedbackDecision:
    """Result of confidence-based decision making."""

    should_ask: bool = False
    question: str = ""
    auto_explanation: str = ""
    confidence: float = 0.0
    exploration_mode: bool = False


class FeedbackLoop:
    """Orchestrator bridge for active learning.

    Usage in orchestrator_loop.py::

        feedback = FeedbackLoop()

        # Phase 0: Turn start
        prompt_ctx = feedback.on_turn_start(user_input)
        # → inject into LLM system prompt

        # Phase 2: After tool execution
        feedback.on_tool_executed(tool_name, params, result, success, elapsed_ms)

        # Phase 3: Confidence-based decision
        decision = feedback.evaluate_confidence(intent, output)
        if decision.should_ask:
            output.ask_user = True
            output.question = decision.question

        # Phase 4: Turn end
        feedback.on_turn_end(user_input, assistant_reply, intent)

        # Correction handling
        if feedback.is_correction(user_input):
            feedback.handle_correction(user_input, previous_reply, intent)
    """

    def __init__(
        self,
        user_id: str = "default",
        exploration_epsilon: float = DEFAULT_EXPLORATION_EPSILON,
        confidence_threshold: float = CONFIDENCE_AUTO_THRESHOLD,
    ):
        self._user_id = user_id
        self._confidence_threshold = confidence_threshold
        self._exploration_epsilon = exploration_epsilon

        # Lazy-loaded components
        self._preference_integration: Any = None
        self._behavioral_learner: Any = None
        self._adaptive_response: Any = None
        self._bandit: Any = None

        # Session metrics
        self._turn_count = 0
        self._tool_usage: Dict[str, int] = {}
        self._corrections: List[Dict[str, str]] = []
        self._rewards: List[float] = []

    # ── Lazy component loading ───────────────────────────────────

    def _get_preference_integration(self):
        if self._preference_integration is None:
            try:
                from bantz.learning.preference_integration import PreferenceIntegration
                self._preference_integration = PreferenceIntegration(
                    user_id=self._user_id,
                )
            except ImportError:
                logger.debug("PreferenceIntegration unavailable")
        return self._preference_integration

    def _get_behavioral_learner(self):
        if self._behavioral_learner is None:
            try:
                from bantz.learning.behavioral import create_behavioral_learner
                self._behavioral_learner = create_behavioral_learner()
            except ImportError:
                logger.debug("BehavioralLearner unavailable")
        return self._behavioral_learner

    def _get_adaptive_response(self):
        if self._adaptive_response is None:
            try:
                from bantz.learning.adaptive import create_adaptive_response
                self._adaptive_response = create_adaptive_response()
            except ImportError:
                logger.debug("AdaptiveResponse unavailable")
        return self._adaptive_response

    def _get_bandit(self):
        if self._bandit is None:
            try:
                from bantz.learning.bandit import create_contextual_bandit
                self._bandit = create_contextual_bandit(
                    epsilon=self._exploration_epsilon,
                )
            except ImportError:
                logger.debug("ContextualBandit unavailable")
        return self._bandit

    # ── Phase 0: Turn start ──────────────────────────────────────

    def on_turn_start(self, user_input: str) -> str:
        """Called at the beginning of each turn.

        Returns preference context string for LLM system prompt injection.
        """
        self._turn_count += 1

        pref = self._get_preference_integration()
        if pref:
            pref.record_turn()
            # Apply learned corrections to user input
            corrected = pref.apply_corrections(user_input)
            if corrected != user_input:
                logger.debug("Applied corrections: %s → %s", user_input, corrected)

        return self.get_prompt_context()

    def get_prompt_context(self) -> str:
        """Generate preference context for LLM prompt."""
        pref = self._get_preference_integration()
        if pref:
            return pref.get_prompt_context()
        return ""

    # ── Phase 2: Post-tool ───────────────────────────────────────

    def on_tool_executed(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        success: bool = True,
        elapsed_ms: float = 0.0,
    ) -> float:
        """Called after each tool execution. Returns reward signal."""
        # Track usage
        self._tool_usage[tool_name] = self._tool_usage.get(tool_name, 0) + 1

        pref = self._get_preference_integration()
        if pref:
            pref.record_tool_usage(tool_name)

        # Compute reward via behavioral learner
        reward = 0.0
        learner = self._get_behavioral_learner()
        if learner:
            try:
                from bantz.learning.behavioral import CommandEvent
                event = CommandEvent(
                    intent=tool_name,
                    parameters=params,
                    success=success,
                    duration_ms=elapsed_ms,
                )
                reward = learner.observe(event)
            except Exception as exc:
                logger.debug("BehavioralLearner.observe failed: %s", exc)

        # Update bandit arm
        bandit = self._get_bandit()
        if bandit:
            try:
                bandit.add_arm(tool_name)
                bandit.update_arm(tool_name, reward)
            except Exception as exc:
                logger.debug("Bandit update failed: %s", exc)

        self._rewards.append(reward)
        return reward

    def get_tool_defaults(self, tool_name: str) -> Dict[str, Any]:
        """Get learned defaults for a tool's parameters."""
        pref = self._get_preference_integration()
        if pref:
            return pref.get_tool_defaults(tool_name)
        return {}

    # ── Phase 3: Confidence decision ─────────────────────────────

    def evaluate_confidence(
        self,
        intent: str,
        confidence: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> FeedbackDecision:
        """Evaluate whether to auto-decide or ask the user.

        Args:
            intent: Detected intent.
            confidence: Router confidence score (0.0 – 1.0).
            context: Optional context for exploration.

        Returns:
            FeedbackDecision with should_ask / auto_explanation.
        """
        # Exploration mode: occasionally try different approach
        exploration = False
        bandit = self._get_bandit()
        if bandit:
            import random
            if random.random() < self._exploration_epsilon:
                exploration = True

        if confidence >= self._confidence_threshold:
            # Auto-decide with explanation
            explanation = self._build_auto_explanation(intent, confidence)
            return FeedbackDecision(
                should_ask=False,
                auto_explanation=explanation,
                confidence=confidence,
                exploration_mode=exploration,
            )

        # Low confidence → ask user
        question = self._build_confidence_question(intent, confidence)
        return FeedbackDecision(
            should_ask=True,
            question=question,
            confidence=confidence,
            exploration_mode=exploration,
        )

    # ── Phase 4: Turn end ────────────────────────────────────────

    def on_turn_end(
        self,
        user_input: str,
        assistant_reply: str,
        intent: str = "",
        success: bool = True,
    ) -> None:
        """Called at end of each turn for implicit learning."""
        # Record choice (the user didn't cancel → positive signal)
        pref = self._get_preference_integration()
        if pref and intent:
            pref.record_choice(
                key=f"intent_{intent}",
                value="used",
                intent=intent,
            )

    # ── Correction handling ──────────────────────────────────────

    def is_correction(self, user_input: str) -> bool:
        """Detect if user input is a correction of previous behavior."""
        lower = user_input.lower().strip()
        return any(lower.startswith(p) for p in _CORRECTION_PREFIXES)

    def handle_correction(
        self,
        user_input: str,
        previous_reply: str,
        intent: str = "",
    ) -> str:
        """Process a user correction and update preferences.

        Returns acknowledgment text for assistant_reply.
        """
        self._corrections.append({
            "user_input": user_input,
            "previous_reply": previous_reply,
            "intent": intent,
            "timestamp": time.time(),
        })

        pref = self._get_preference_integration()
        if pref:
            pref.record_correction(
                original=previous_reply,
                corrected=user_input,
                intent=intent,
            )

        # Negative reward for the correction
        learner = self._get_behavioral_learner()
        if learner and intent:
            try:
                from bantz.learning.behavioral import CommandEvent
                event = CommandEvent(
                    intent=intent,
                    success=False,
                    corrected=True,
                )
                learner.observe(event)
            except Exception:
                pass

        return (
            "Anladım, bundan sonra bunu hatırlayacağım. "
            "Düzeltme için teşekkürler."
        )

    def handle_cancellation(self, intent: str, reason: str = "") -> None:
        """Record a user cancellation (negative signal)."""
        pref = self._get_preference_integration()
        if pref:
            pref.record_cancellation(intent, reason)

        learner = self._get_behavioral_learner()
        if learner:
            try:
                from bantz.learning.behavioral import CommandEvent
                event = CommandEvent(
                    intent=intent,
                    success=False,
                    cancelled=True,
                )
                learner.observe(event)
            except Exception:
                pass

    # ── Exploration ──────────────────────────────────────────────

    def suggest_exploration(
        self,
        available_tools: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Suggest a tool to explore (bandit arm selection).

        Returns tool name if exploration is triggered, None otherwise.
        """
        bandit = self._get_bandit()
        if not bandit:
            return None

        for tool in available_tools:
            bandit.add_arm(tool)

        return bandit.select_arm(available_arms=available_tools, context=context)

    # ── Session summary ──────────────────────────────────────────

    def get_session_summary(self) -> Dict[str, Any]:
        """Get session-level learning summary."""
        avg_reward = (
            sum(self._rewards) / len(self._rewards)
            if self._rewards
            else 0.0
        )
        return {
            "turn_count": self._turn_count,
            "tool_usage": dict(self._tool_usage),
            "corrections_count": len(self._corrections),
            "total_rewards": len(self._rewards),
            "avg_reward": round(avg_reward, 3),
        }

    def reset(self) -> None:
        """Reset session state."""
        self._turn_count = 0
        self._tool_usage = {}
        self._corrections = []
        self._rewards = []

        pref = self._get_preference_integration()
        if pref:
            pref.reset_session()

    # ── Private helpers ──────────────────────────────────────────

    def _build_auto_explanation(self, intent: str, confidence: float) -> str:
        """Build Turkish explanation for auto-decisions."""
        pct = int(confidence * 100)
        return (
            f"Güven skoru %{pct} — otomatik karar verdim. "
            "Eğer yanlışsa 'hayır' diyerek düzeltebilirsin."
        )

    def _build_confidence_question(self, intent: str, confidence: float) -> str:
        """Build Turkish question when confidence is low."""
        pct = int(confidence * 100)
        return (
            f"Bu konuda %{pct} eminim. "
            "Devam etmemi ister misin, yoksa başka bir şey mi yapmamı tercih edersin?"
        )


def create_feedback_loop(
    user_id: str = "default",
    exploration_epsilon: float = DEFAULT_EXPLORATION_EPSILON,
    confidence_threshold: float = CONFIDENCE_AUTO_THRESHOLD,
) -> FeedbackLoop:
    """Factory for creating a FeedbackLoop."""
    return FeedbackLoop(
        user_id=user_id,
        exploration_epsilon=exploration_epsilon,
        confidence_threshold=confidence_threshold,
    )
