"""
Fail-safe handler module.

Handles failures with user interaction for recovery decisions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

from bantz.automation.plan import TaskPlan, PlanStep


class TTSEngine(Protocol):
    """Protocol for TTS engine."""
    
    async def speak(self, text: str) -> None:
        """Speak text."""
        ...


class ASREngine(Protocol):
    """Protocol for ASR engine."""
    
    async def listen(self) -> str:
        """Listen for speech."""
        ...


class FailSafeAction(Enum):
    """Actions that can be taken on failure."""
    
    RETRY = "retry"           # Tekrar dene
    SKIP = "skip"             # Bu step'i atla
    ABORT = "abort"           # Planı iptal et
    MANUAL = "manual"         # Kullanıcı manuel yapsın
    MODIFY = "modify"         # Planı değiştir


@dataclass
class FailSafeChoice:
    """User's choice for handling failure."""
    
    action: FailSafeAction
    """Chosen action."""
    
    reason: Optional[str] = None
    """User's reason for choice."""
    
    modified_step: Optional[PlanStep] = None
    """Modified step (if action is MODIFY)."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action": self.action.value,
            "reason": self.reason,
            "modified_step": self.modified_step.to_dict() if self.modified_step else None,
        }


class FailSafeHandler:
    """
    Handles execution failures with user interaction.
    
    After consecutive failures, asks user for recovery decision.
    """
    
    # Maximum consecutive failures before asking user
    MAX_CONSECUTIVE_FAILURES = 2
    
    # Failure messages (Turkish)
    MESSAGES_TR = {
        "failure_notice": "Bu adım {count} kez başarısız oldu: {step}",
        "ask_choice": "Ne yapmamı istersin?",
        "options": [
            "Tekrar dene",
            "Bu adımı atla",
            "Görevi iptal et",
            "Ben manuel yapacağım",
        ],
        "choice_confirmed": "Anladım, {action} seçtim.",
        "retrying": "Tekrar deniyorum...",
        "skipping": "Bu adımı atlıyorum.",
        "aborting": "Görevi iptal ediyorum.",
        "manual": "Tamam, sen manuel yap. Bittiğinde söyle.",
    }
    
    # Failure messages (English)
    MESSAGES_EN = {
        "failure_notice": "This step failed {count} times: {step}",
        "ask_choice": "What would you like me to do?",
        "options": [
            "Retry",
            "Skip this step",
            "Abort the task",
            "I'll do it manually",
        ],
        "choice_confirmed": "Got it, choosing {action}.",
        "retrying": "Retrying...",
        "skipping": "Skipping this step.",
        "aborting": "Aborting the task.",
        "manual": "Okay, you do it manually. Let me know when done.",
    }
    
    def __init__(
        self,
        tts: Optional[TTSEngine] = None,
        asr: Optional[ASREngine] = None,
        language: str = "tr",
    ):
        """
        Initialize the fail-safe handler.
        
        Args:
            tts: TTS engine for speaking.
            asr: ASR engine for listening.
            language: Language for messages.
        """
        self._tts = tts
        self._asr = asr
        self._language = language
        self._messages = self.MESSAGES_TR if language == "tr" else self.MESSAGES_EN
        self._failure_history: list[dict] = []
    
    def should_ask_user(self, consecutive_failures: int) -> bool:
        """
        Check if user should be asked for decision.
        
        Args:
            consecutive_failures: Number of consecutive failures.
            
        Returns:
            True if user should be asked.
        """
        return consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES
    
    async def handle_failure(
        self,
        plan: TaskPlan,
        step: PlanStep,
        error: str,
        consecutive_failures: int,
    ) -> FailSafeChoice:
        """
        Handle a step failure.
        
        Args:
            plan: Current plan.
            step: Failed step.
            error: Error message.
            consecutive_failures: Number of consecutive failures.
            
        Returns:
            User's choice for handling.
        """
        # Log failure
        self._failure_history.append({
            "plan_id": plan.id,
            "step_id": step.id,
            "error": error,
            "consecutive": consecutive_failures,
        })
        
        # First failure - auto retry
        if consecutive_failures < self.MAX_CONSECUTIVE_FAILURES:
            return FailSafeChoice(
                action=FailSafeAction.RETRY,
                reason="Auto-retry on first failure",
            )
        
        # Multiple failures - ask user
        return await self._ask_user_for_choice(plan, step, consecutive_failures)
    
    async def _ask_user_for_choice(
        self,
        plan: TaskPlan,
        step: PlanStep,
        consecutive_failures: int,
    ) -> FailSafeChoice:
        """Ask user for failure recovery choice."""
        # Speak failure notice
        failure_msg = self._messages["failure_notice"].format(
            count=consecutive_failures,
            step=step.description,
        )
        
        await self._speak(failure_msg)
        
        # Speak options
        await self._speak(self._messages["ask_choice"])
        
        options = self._messages["options"]
        for i, option in enumerate(options, 1):
            await self._speak(f"{i}. {option}")
        
        # Get user choice
        choice_index = await self.ask_user_choice(options)
        
        # Map index to action
        action_map = [
            FailSafeAction.RETRY,
            FailSafeAction.SKIP,
            FailSafeAction.ABORT,
            FailSafeAction.MANUAL,
        ]
        
        action = action_map[choice_index] if 0 <= choice_index < len(action_map) else FailSafeAction.ABORT
        
        # Confirm choice
        await self._speak(self._messages["choice_confirmed"].format(
            action=options[choice_index] if 0 <= choice_index < len(options) else "abort"
        ))
        
        return FailSafeChoice(action=action)
    
    async def ask_user_choice(self, options: list[str]) -> int:
        """
        Ask user to choose from options.
        
        Args:
            options: List of options.
            
        Returns:
            Index of chosen option (0-based).
        """
        if not self._asr:
            # Default to retry if no ASR
            return 0
        
        try:
            response = await self._asr.listen()
            
            # Parse response
            response_lower = response.lower()
            
            # Check for number
            for i in range(len(options)):
                if str(i + 1) in response:
                    return i
            
            # Check for keywords
            keywords = {
                0: ["tekrar", "retry", "dene"],
                1: ["atla", "skip", "geç"],
                2: ["iptal", "abort", "durdur", "cancel"],
                3: ["manuel", "manual", "ben", "kendim"],
            }
            
            for idx, words in keywords.items():
                if any(word in response_lower for word in words):
                    return idx
            
            # Default to first option
            return 0
            
        except Exception:
            return 0
    
    async def _speak(self, text: str) -> None:
        """Speak text using TTS."""
        if self._tts:
            await self._tts.speak(text)
    
    async def notify_retry(self) -> None:
        """Notify user about retry."""
        await self._speak(self._messages["retrying"])
    
    async def notify_skip(self) -> None:
        """Notify user about skip."""
        await self._speak(self._messages["skipping"])
    
    async def notify_abort(self) -> None:
        """Notify user about abort."""
        await self._speak(self._messages["aborting"])
    
    async def notify_manual(self) -> None:
        """Notify user about manual handling."""
        await self._speak(self._messages["manual"])
    
    async def wait_for_manual_completion(self) -> bool:
        """
        Wait for user to complete manual step.
        
        Returns:
            True if user confirms completion.
        """
        if not self._asr:
            return True
        
        try:
            response = await self._asr.listen()
            
            completion_words = [
                "bitti", "tamam", "done", "finished", "complete",
                "tamamlandı", "yaptım", "oldu",
            ]
            
            return any(word in response.lower() for word in completion_words)
            
        except Exception:
            return True
    
    def get_failure_history(self) -> list[dict]:
        """Get failure history."""
        return list(self._failure_history)
    
    def clear_history(self) -> None:
        """Clear failure history."""
        self._failure_history.clear()


def create_failsafe_handler(
    tts: Optional[TTSEngine] = None,
    asr: Optional[ASREngine] = None,
    language: str = "tr",
) -> FailSafeHandler:
    """
    Factory function to create a fail-safe handler.
    
    Args:
        tts: TTS engine for speaking.
        asr: ASR engine for listening.
        language: Language for messages.
        
    Returns:
        Configured FailSafeHandler instance.
    """
    return FailSafeHandler(
        tts=tts,
        asr=asr,
        language=language,
    )
