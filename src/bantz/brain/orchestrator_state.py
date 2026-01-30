"""Orchestrator State Management (Issue #134).

Manages rolling summary, tool results, confirmation state, and trace metadata
for LLM-first orchestrator architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class OrchestratorState:
    """State maintained across turns in LLM orchestrator.
    
    This state provides memory and context for the LLM to make informed decisions.
    """
    
    # Rolling summary (5-10 lines, updated by LLM each turn)
    rolling_summary: str = ""
    
    # Last N tool results (kept short for context window)
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)
    max_tool_results: int = 3  # Keep only last 3 tool results
    
    # Pending confirmation (waiting for user approval)
    pending_confirmation: Optional[dict[str, Any]] = None
    
    # Trace metadata (for debugging and testing)
    trace: dict[str, Any] = field(default_factory=dict)
    
    # Conversation history (last N turns)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    max_history_turns: int = 3  # Keep only last 3 turns
    
    def add_tool_result(self, tool_name: str, result: Any, success: bool = True) -> None:
        """Add a tool result to state (FIFO queue)."""
        self.last_tool_results.append({
            "tool": tool_name,
            "result": str(result)[:500],  # Truncate to 500 chars
            "success": success,
        })
        
        # Keep only last N results
        if len(self.last_tool_results) > self.max_tool_results:
            self.last_tool_results = self.last_tool_results[-self.max_tool_results:]
    
    def add_conversation_turn(self, user_input: str, assistant_reply: str) -> None:
        """Add a conversation turn to history (FIFO queue)."""
        self.conversation_history.append({
            "user": user_input,
            "assistant": assistant_reply,
        })
        
        # Keep only last N turns
        if len(self.conversation_history) > self.max_history_turns:
            self.conversation_history = self.conversation_history[-self.max_history_turns:]
    
    def update_rolling_summary(self, new_summary: str) -> None:
        """Update rolling summary (LLM-generated each turn)."""
        self.rolling_summary = new_summary.strip()
    
    def set_pending_confirmation(self, action: dict[str, Any]) -> None:
        """Set pending confirmation (waiting for user approval)."""
        self.pending_confirmation = action
    
    def clear_pending_confirmation(self) -> None:
        """Clear pending confirmation (user approved/rejected)."""
        self.pending_confirmation = None
    
    def has_pending_confirmation(self) -> bool:
        """Check if there's a pending confirmation."""
        return self.pending_confirmation is not None
    
    def update_trace(self, **kwargs: Any) -> None:
        """Update trace metadata."""
        self.trace.update(kwargs)
    
    def get_context_for_llm(self) -> dict[str, Any]:
        """Get context to send to LLM (summary + recent history + tool results)."""
        return {
            "rolling_summary": self.rolling_summary,
            "recent_conversation": self.conversation_history[-2:] if self.conversation_history else [],
            "last_tool_results": self.last_tool_results,
            "pending_confirmation": self.pending_confirmation,
        }
    
    def reset(self) -> None:
        """Reset state (new session)."""
        self.rolling_summary = ""
        self.last_tool_results = []
        self.pending_confirmation = None
        self.trace = {}
        self.conversation_history = []
