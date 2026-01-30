"""
Task Listening Policy (Issue #35 - Voice-2).

Defines what commands are allowed during task execution (TASK_RUNNING mode).

By default, only job control intents are accepted:
- job_pause: "bekle", "dur"
- job_resume: "devam et", "devam"
- job_cancel: "iptal", "vazgeç"
- interrupt: New command after wake word

All other intents are rejected with a message explaining
that a task is currently running.
"""

from typing import List, Optional, Set


class TaskListeningPolicy:
    """
    Policy for what commands are accepted during task execution.
    
    When the system is in TASK_RUNNING mode, only specific
    intents related to job control are accepted. This prevents
    accidental commands while a task is being performed.
    
    Usage:
        policy = TaskListeningPolicy()
        
        if policy.should_accept("job_pause"):
            # Accept and handle
        else:
            message = policy.get_rejection_message()
            # Speak message to user
    """
    
    # Default allowed intents during task execution
    DEFAULT_ALLOWED_INTENTS = {
        "job_pause",      # "bekle", "dur"
        "job_resume",     # "devam et", "devam"
        "job_cancel",     # "iptal", "vazgeç"
        "interrupt",      # New command via wake word
        "status",         # "ne yapıyorsun?", "durum"
        "help",           # "yardım"
    }
    
    # Turkish rejection message
    DEFAULT_REJECTION_MESSAGE = (
        "Şu an bir görev çalışıyor. "
        "'Bekle' diyerek duraklatabilir, "
        "'İptal' diyerek sonlandırabilir, "
        "veya 'Hey Bantz' ile kesebilirsin."
    )
    
    # Short rejection for quick response
    SHORT_REJECTION_MESSAGE = "Şu an bir görev çalışıyor."
    
    def __init__(
        self,
        allowed_intents: Optional[Set[str]] = None,
        rejection_message: Optional[str] = None,
        use_short_rejection: bool = False
    ):
        """
        Initialize TaskListeningPolicy.
        
        Args:
            allowed_intents: Set of allowed intent names
            rejection_message: Custom rejection message
            use_short_rejection: Use short rejection message
        """
        self._allowed_intents = allowed_intents or self.DEFAULT_ALLOWED_INTENTS.copy()
        
        if rejection_message:
            self._rejection_message = rejection_message
        elif use_short_rejection:
            self._rejection_message = self.SHORT_REJECTION_MESSAGE
        else:
            self._rejection_message = self.DEFAULT_REJECTION_MESSAGE
    
    def should_accept(self, intent: str) -> bool:
        """
        Check if an intent should be accepted during task execution.
        
        Args:
            intent: Intent name to check
            
        Returns:
            True if intent is allowed during task execution
        """
        return intent.lower() in self._allowed_intents
    
    def get_rejection_message(self) -> str:
        """
        Get the rejection message for disallowed commands.
        
        Returns:
            Rejection message to speak to user
        """
        return self._rejection_message
    
    def add_allowed_intent(self, intent: str) -> None:
        """
        Add an intent to the allowed list.
        
        Args:
            intent: Intent name to allow
        """
        self._allowed_intents.add(intent.lower())
    
    def remove_allowed_intent(self, intent: str) -> None:
        """
        Remove an intent from the allowed list.
        
        Args:
            intent: Intent name to remove
        """
        self._allowed_intents.discard(intent.lower())
    
    def get_allowed_intents(self) -> Set[str]:
        """Get set of currently allowed intents."""
        return self._allowed_intents.copy()
    
    def set_rejection_message(self, message: str) -> None:
        """Set custom rejection message."""
        self._rejection_message = message
    
    def is_job_control_intent(self, intent: str) -> bool:
        """
        Check if intent is a job control command.
        
        Args:
            intent: Intent name to check
            
        Returns:
            True if intent is job-related (pause/resume/cancel)
        """
        job_control_intents = {"job_pause", "job_resume", "job_cancel"}
        return intent.lower() in job_control_intents
    
    def get_intent_action(self, intent: str) -> Optional[str]:
        """
        Get the action type for an intent.
        
        Args:
            intent: Intent name
            
        Returns:
            Action type ("pause", "resume", "cancel") or None
        """
        intent_lower = intent.lower()
        if intent_lower == "job_pause":
            return "pause"
        elif intent_lower == "job_resume":
            return "resume"
        elif intent_lower == "job_cancel":
            return "cancel"
        elif intent_lower == "interrupt":
            return "interrupt"
        elif intent_lower == "status":
            return "status"
        return None


# Intent keywords for NLU mapping
INTENT_KEYWORDS = {
    "job_pause": ["bekle", "dur", "pause", "wait", "stop"],
    "job_resume": ["devam et", "devam", "resume", "continue"],
    "job_cancel": ["iptal", "vazgeç", "cancel", "abort"],
    "status": ["ne yapıyorsun", "durum", "status", "what are you doing"],
    "help": ["yardım", "help", "ne yapabilirim"],
}


def classify_task_command(text: str) -> Optional[str]:
    """
    Classify text into task control intent.
    
    Args:
        text: User's spoken text
        
    Returns:
        Intent name or None if not a task command
    """
    text_lower = text.lower().strip()
    
    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return intent
    
    return None


def create_task_policy(
    allowed_intents: Optional[List[str]] = None,
    rejection_message: Optional[str] = None,
    use_short_rejection: bool = False
) -> TaskListeningPolicy:
    """
    Factory function to create TaskListeningPolicy.
    
    Args:
        allowed_intents: List of allowed intent names
        rejection_message: Custom rejection message
        use_short_rejection: Use short rejection message
    
    Returns:
        Configured TaskListeningPolicy instance
    """
    intents_set = set(allowed_intents) if allowed_intents else None
    return TaskListeningPolicy(
        allowed_intents=intents_set,
        rejection_message=rejection_message,
        use_short_rejection=use_short_rejection
    )
