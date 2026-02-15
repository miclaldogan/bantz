"""Orchestrator State Management (Issue #134).

Manages rolling summary, tool results, confirmation state, and trace metadata
for LLM-first orchestrator architecture.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from bantz.brain.anaphora import ReferenceTable
    from bantz.brain.disambiguation import DisambiguationRequest

logger = logging.getLogger(__name__)

# ── Issue #1276: Cross-Turn Slot Tracking ────────────────────────────
# EntitySlot holds a tracked entity (calendar event, gmail message, etc.)
# that can be referenced in follow-up turns via pronouns or ordinals.
# SlotRegistry manages active entities with TTL-based expiry.

# Mapping from tool name (prefix) to entity type
_TOOL_ENTITY_TYPE_MAP: dict[str, str] = {
    "calendar.create_event": "calendar_event",
    "calendar.update_event": "calendar_event",
    "calendar.get_event": "calendar_event",
    "calendar.list_events": "calendar_events",
    "gmail.send": "gmail_message",
    "gmail.reply": "gmail_message",
    "gmail.read_message": "gmail_message",
    "gmail.list_messages": "gmail_messages",
    "gmail.smart_search": "gmail_messages",
    "system.": "system",
}

# Keys to extract from tool results as entity slots
_ENTITY_SLOT_KEYS: dict[str, list[str]] = {
    "calendar_event": ["id", "summary", "start", "end", "location", "htmlLink", "all_day"],
    "calendar_events": ["events"],
    "gmail_message": ["message_id", "id", "to", "subject", "from"],
    "gmail_messages": ["messages"],
    "system": [],
}

# Default TTL (number of turns before entity expires)
_ENTITY_TTL: int = 5


@dataclass
class EntitySlot:
    """A tracked entity that can be referenced across turns.

    Holds structured data (id + slots) extracted from tool results
    so follow-up turns like "saatini değiştir" can resolve to the
    concrete entity without re-querying.
    """

    entity_type: str            # e.g. "calendar_event", "gmail_message"
    entity_id: Optional[str]    # primary key (event_id, message_id, …)
    slots: dict[str, Any]       # extracted fields (summary, start, end, …)
    source_tool: str            # tool that produced this entity
    created_at_turn: int        # turn number when entity was created
    ttl: int = _ENTITY_TTL      # turns until auto-expiry

    @property
    def age(self) -> int:
        """Return how many turns old relative to creation.

        NOTE: Requires ``current_turn`` to be set externally via
        ``SlotRegistry.expire_stale()`` context. Falls back to 0
        when the registry hasn't stamped the entity yet.
        """
        return getattr(self, "_current_turn", self.created_at_turn) - self.created_at_turn

    def is_expired(self, current_turn: int) -> bool:
        """Check if entity has exceeded its TTL."""
        return (current_turn - self.created_at_turn) >= self.ttl

    def to_prompt_dict(self) -> dict[str, Any]:
        """Compact representation for LLM prompt injection."""
        d: dict[str, Any] = {"type": self.entity_type}
        if self.entity_id:
            d["id"] = self.entity_id
        # Only include non-empty slots
        compact_slots = {k: v for k, v in self.slots.items() if v}
        if compact_slots:
            d.update(compact_slots)
        return d


class SlotRegistry:
    """Registry for cross-turn entity tracking (Issue #1276).

    Maintains an *active entity* (the most recently created/modified entity)
    and a small history of recent entities for multi-entity workflows.

    Active entity is injected into the LLM prompt so follow-up turns
    (e.g. "saatini 5'e değiştir") can resolve to the concrete entity_id.
    """

    def __init__(self, max_entities: int = 10, default_ttl: int = _ENTITY_TTL):
        self._active: Optional[EntitySlot] = None
        self._entities: dict[str, EntitySlot] = {}  # keyed by entity_id
        self._max_entities = max_entities
        self._default_ttl = default_ttl

    # ── Public API ───────────────────────────────────────────────────

    def register(self, entity: EntitySlot) -> None:
        """Register a new entity and set it as active."""
        self._active = entity
        if entity.entity_id:
            self._entities[entity.entity_id] = entity
            # Evict oldest if over capacity
            if len(self._entities) > self._max_entities:
                oldest_key = min(
                    self._entities,
                    key=lambda k: self._entities[k].created_at_turn,
                )
                del self._entities[oldest_key]
        logger.debug(
            "[SlotRegistry] Registered entity: type=%s id=%s tool=%s",
            entity.entity_type, entity.entity_id, entity.source_tool,
        )

    def get_active(self) -> Optional[EntitySlot]:
        """Return the currently active entity (may be None or expired)."""
        return self._active

    def get_by_id(self, entity_id: str) -> Optional[EntitySlot]:
        """Lookup entity by its primary key."""
        return self._entities.get(entity_id)

    def expire_stale(self, current_turn: int) -> int:
        """Remove entities that have exceeded their TTL.

        Issue #1316: Also stamps ``_current_turn`` on surviving entities
        so that ``EntitySlot.age`` returns the correct value.

        Returns the number of expired entities.
        """
        expired_keys = [
            k for k, e in self._entities.items()
            if e.is_expired(current_turn)
        ]
        for k in expired_keys:
            del self._entities[k]
        # Issue #1316: Stamp current turn on surviving entities for age calc
        for entity in self._entities.values():
            object.__setattr__(entity, "_current_turn", current_turn)
        if self._active and self._active.is_expired(current_turn):
            logger.debug(
                "[SlotRegistry] Active entity expired: type=%s id=%s (turn %d, created %d, ttl %d)",
                self._active.entity_type, self._active.entity_id,
                current_turn, self._active.created_at_turn, self._active.ttl,
            )
            self._active = None
        elif self._active:
            object.__setattr__(self._active, "_current_turn", current_turn)
        return len(expired_keys)

    def to_prompt_block(self) -> str:
        """Render active entity as a compact prompt block for LLM injection.

        Target: ~50-100 tokens to stay within context budget.
        Returns empty string if no active entity.

        Issue #1316: Uses key-based trimming instead of raw string
        truncation to avoid injecting broken JSON into the prompt.
        """
        if not self._active:
            return ""
        d = self._active.to_prompt_dict()
        # Issue #1316: Trim large slot values instead of slicing raw JSON
        _MAX_BLOCK_CHARS = 400
        try:
            block = json.dumps(d, ensure_ascii=False)
        except (TypeError, ValueError):
            block = str(d)
        if len(block) > _MAX_BLOCK_CHARS:
            # Progressively trim longest slot values
            trimmed = dict(d)
            for key in sorted(trimmed, key=lambda k: len(str(trimmed.get(k, ""))), reverse=True):
                val = trimmed[key]
                if isinstance(val, str) and len(val) > 80:
                    trimmed[key] = val[:77] + "..."
                try:
                    block = json.dumps(trimmed, ensure_ascii=False)
                except (TypeError, ValueError):
                    block = str(trimmed)
                if len(block) <= _MAX_BLOCK_CHARS:
                    break
            # Final hard cap — but on a best-effort valid-JSON block
            if len(block) > _MAX_BLOCK_CHARS:
                block = block[:_MAX_BLOCK_CHARS]
        return block

    def clear(self) -> None:
        """Clear all tracked entities."""
        self._active = None
        self._entities.clear()

    @property
    def active_entity_type(self) -> str:
        """Return the type of the active entity, or empty string."""
        return self._active.entity_type if self._active else ""

    @property
    def active_entity_id(self) -> Optional[str]:
        """Return the ID of the active entity, or None."""
        return self._active.entity_id if self._active else None

    def __len__(self) -> int:
        return len(self._entities)

    def __repr__(self) -> str:
        active_id = self._active.entity_id if self._active else None
        return f"<SlotRegistry active={active_id} total={len(self._entities)}>"


def extract_entity_from_tool_result(
    tool_name: str,
    result_raw: Any,
    current_turn: int,
    ttl: int = _ENTITY_TTL,
) -> Optional[EntitySlot]:
    """Extract an EntitySlot from a successful tool result.

    Inspects the tool name to determine entity type and extracts
    relevant fields (id, summary, start, end, etc.) from the raw result.

    Returns None if the tool is not entity-producing or result is invalid.
    """
    # Determine entity type from tool name
    entity_type: Optional[str] = None
    for prefix, etype in _TOOL_ENTITY_TYPE_MAP.items():
        if tool_name == prefix or tool_name.startswith(prefix):
            entity_type = etype
            break
    if not entity_type:
        return None

    if not isinstance(result_raw, dict):
        return None

    # Skip failed results
    if not result_raw.get("ok", True):
        return None

    # Determine entity_id and slots based on type
    entity_id: Optional[str] = None
    slots: dict[str, Any] = {}

    slot_keys = _ENTITY_SLOT_KEYS.get(entity_type, [])

    if entity_type == "calendar_event":
        entity_id = str(result_raw.get("id") or result_raw.get("event_id") or "")
        for key in slot_keys:
            val = result_raw.get(key)
            if val is not None:
                slots[key] = val

    elif entity_type == "calendar_events":
        # For list results, track the list itself but don't set a single entity_id
        events = result_raw.get("events")
        if isinstance(events, list) and events:
            # Store first event as entity_id for quick reference
            first = events[0] if events else {}
            entity_id = str(first.get("id") or first.get("event_id") or "") if isinstance(first, dict) else None
            slots["count"] = len(events)
            # Store compact summaries (max 5)
            slots["items"] = [
                {
                    "id": ev.get("id", ""),
                    "summary": ev.get("summary", ""),
                    "start": ev.get("start", ""),
                }
                for ev in events[:5]
                if isinstance(ev, dict)
            ]

    elif entity_type == "gmail_message":
        entity_id = str(
            result_raw.get("message_id")
            or result_raw.get("id")
            or ""
        )
        for key in slot_keys:
            val = result_raw.get(key)
            if val is not None:
                slots[key] = val

    elif entity_type == "gmail_messages":
        messages = result_raw.get("messages")
        if isinstance(messages, list) and messages:
            first = messages[0] if messages else {}
            entity_id = str(first.get("id") or "") if isinstance(first, dict) else None
            slots["count"] = len(messages)
            slots["items"] = [
                {
                    "id": m.get("id", ""),
                    "from": m.get("from", ""),
                    "subject": m.get("subject", ""),
                }
                for m in messages[:5]
                if isinstance(m, dict)
            ]

    if not entity_id:
        return None

    return EntitySlot(
        entity_type=entity_type,
        entity_id=entity_id,
        slots=slots,
        source_tool=tool_name,
        created_at_turn=current_turn,
        ttl=ttl,
    )


@dataclass
class OrchestratorState:
    """State maintained across turns in LLM orchestrator.
    
    This state provides memory and context for the LLM to make informed decisions.
    """
    
    # Rolling summary (5-10 lines, updated by LLM each turn)
    rolling_summary: str = ""
    
    # Last N tool results (kept short for context window)
    last_tool_results: list[dict[str, Any]] = field(default_factory=list)
    max_tool_results: int = 5  # Issue #1278: Keep last 5 tool results (was 3)
    
    # Pending confirmations (FIFO queue for multiple destructive tools)
    pending_confirmations: list[dict[str, Any]] = field(default_factory=list)
    max_pending_confirmations: int = 10  # Issue #1314: Cap pending confirmations

    # Confirmation override (used when a pending confirmation is accepted)
    confirmed_tool: Optional[str] = None
    
    # Trace metadata (for debugging and testing)
    trace: dict[str, Any] = field(default_factory=dict)
    max_trace_keys: int = 20  # Issue #1314: Cap trace dict keys
    
    # Conversation history (last N turns)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    max_history_turns: int = 8  # Issue #1278: Keep last 8 turns (was 3)

    # Turn counter (used by memory-lite summaries)
    turn_count: int = 0

    # Issue #1313: Thread-safety lock for pending_confirmations and slot_registry
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # Current user input (set at the start of each turn for param builder fallback)
    current_user_input: str = ""
    
    # Session context (timezone, locale, datetime) - Issue #359
    session_context: Optional[dict[str, Any]] = None

    # Issue #416: Last reference table for anaphora resolution
    reference_table: Optional[ReferenceTable] = field(default=None)

    # Issue #875: Pending disambiguation request
    disambiguation_pending: Optional[DisambiguationRequest] = field(default=None)

    # Issue #1212: Follow-up context — track last successful tool for anaphora
    last_tool_called: str = ""
    last_tool_route: str = ""

    # Issue #1217: Gmail pagination — store next_page_token for continuation
    gmail_next_page_token: str = ""
    gmail_last_query: str = ""

    # Issue #1218: Store last listed gmail message headers for entity resolution
    gmail_listed_messages: list[dict[str, str]] = field(default_factory=list)
    max_gmail_listed: int = 50  # Issue #1314: Cap listed messages

    # Issue #1224: Store last listed calendar events for #N follow-up resolution
    calendar_listed_events: list[dict[str, Any]] = field(default_factory=list)
    max_calendar_listed: int = 50  # Issue #1314: Cap listed events

    # Issue #1242: Language Bridge — detected language and canonical EN input
    detected_lang: str = ""
    canonical_input: str = ""

    # Issue #1273: ReAct loop — per-turn observations from tool execution
    # Each entry: {"iteration": int, "tool": str, "result_summary": str, "success": bool}
    # Cleared at the start of each turn. Carries observations across ReAct
    # iterations so the LLM can see what happened and decide next action.
    react_observations: list[dict[str, Any]] = field(default_factory=list)
    max_react_observations: int = 50  # Issue #1314: Cap observations per turn
    react_iteration: int = 0  # current ReAct iteration within a turn

    # Issue #1276: Cross-turn entity/slot tracking
    # SlotRegistry holds entities extracted from tool results so follow-up
    # turns can resolve pronouns ("saatini değiştir") to concrete entity IDs.
    slot_registry: SlotRegistry = field(default_factory=SlotRegistry)

    # Issue #1279: Hierarchical task decomposition — active subtask plan
    # Holds the current SubtaskPlan during multi-step execution.
    # Cleared at the start of each new turn (not carried across turns).
    subtask_plan: Any = field(default=None)  # Optional[SubtaskPlan]
    
    def add_tool_result(self, tool_name: str, result: Any, success: bool = True) -> None:
        """Add a tool result to state (FIFO queue).

        Issue #893 – smart truncation:
        * ``result_raw``    – the original Python object (list / dict / str)
        * ``result``        – JSON-serialised string (max *max_chars*)
        * ``result_summary``– short human-readable summary for the LLM prompt
        """
        max_chars = 1500
        max_list_items = 5   # keep first N items for list results
        max_raw_items = 50   # cap result_raw for memory safety

        # ── raw storage (structured, capped) ──
        if isinstance(result, list) and len(result) > max_raw_items:
            result_raw = result[:max_raw_items]
        else:
            result_raw = result

        # ── JSON string ──
        try:
            result_str = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            result_str = str(result)

        if len(result_str) > max_chars:
            result_str = result_str[:max_chars] + "… [truncated]"

        # ── smart summary for LLM prompt context ──
        result_summary = self._build_result_summary(
            tool_name, result_raw, max_list_items, max_chars=400,
        )

        self.last_tool_results.append({
            "tool": tool_name,
            "result": result_str,
            "result_raw": result_raw,
            "result_summary": result_summary,
            "success": success,
        })

        # Keep only last N results
        if len(self.last_tool_results) > self.max_tool_results:
            self.last_tool_results = self.last_tool_results[-self.max_tool_results:]

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_result_summary(
        tool_name: str,
        result: Any,
        max_items: int = 5,
        max_chars: int = 400,
    ) -> str:
        """Build a concise summary of a tool result for LLM context.

        Lists are truncated to *max_items* entries (with a count note).
        Dicts are serialised compactly.  Everything is capped at *max_chars*.
        """
        if isinstance(result, list):
            total = len(result)
            items = result[:max_items]
            try:
                summary = json.dumps(items, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                summary = str(items)
            if total > max_items:
                summary += f" … (+{total - max_items} more, {total} total)"
            if len(summary) > max_chars:
                summary = summary[:max_chars] + "…"
            return summary

        if isinstance(result, dict):
            try:
                summary = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                summary = str(result)
            if len(summary) > max_chars:
                summary = summary[:max_chars] + "…"
            return summary

        summary = str(result)
        if len(summary) > max_chars:
            summary = summary[:max_chars] + "…"
        return summary
    
    def add_conversation_turn(self, user_input: str, assistant_reply: str) -> None:
        """Add a conversation turn to history (FIFO queue)."""
        self.conversation_history.append({
            "user": user_input,
            "assistant": assistant_reply,
        })
        
        # Keep only last N turns
        if len(self.conversation_history) > self.max_history_turns:
            self.conversation_history = self.conversation_history[-self.max_history_turns:]
    
    # ------------------------------------------------------------------
    # Issue #1278: Adaptive conversation compaction
    # ------------------------------------------------------------------

    def compact_conversation_history(
        self,
        *,
        raw_tail: int = 3,
        max_summary_chars_per_turn: int = 120,
        token_budget: int = 0,
    ) -> list[dict[str, str]]:
        """Return conversation history with adaptive compaction.

        The most recent *raw_tail* turns are returned verbatim.
        Older turns are compacted into one-line summaries to save tokens.

        If *token_budget* > 0, the compacted list is further trimmed
        so that its estimated token cost stays within budget.

        Returns a new list — does NOT mutate ``self.conversation_history``.
        """
        history = self.conversation_history
        if not history:
            return []

        n = len(history)
        tail_start = max(0, n - raw_tail)

        compacted: list[dict[str, str]] = []

        # Older turns → summarised
        for turn in history[:tail_start]:
            user_text = str(turn.get("user", ""))[:max_summary_chars_per_turn]
            asst_text = str(turn.get("assistant", ""))[:max_summary_chars_per_turn]
            compacted.append({
                "user": user_text,
                "assistant": asst_text,
                "_compacted": "true",
            })

        # Recent turns → verbatim
        for turn in history[tail_start:]:
            compacted.append(dict(turn))

        # Token budget enforcement
        if token_budget > 0:
            from bantz.llm.token_utils import estimate_tokens_json
            while compacted and estimate_tokens_json(compacted) > token_budget:
                # Drop oldest compacted turn first
                compacted.pop(0)

        return compacted

    def update_rolling_summary(self, new_summary: str) -> None:
        """Update rolling summary (LLM-generated each turn)."""
        self.rolling_summary = new_summary.strip()
    
    def set_pending_confirmation(self, action: dict[str, Any]) -> None:
        """Backward-compat: set a single pending confirmation (FIFO queue)."""
        with self._lock:
            self.pending_confirmations = [action]

    def add_pending_confirmation(self, action: dict[str, Any]) -> None:
        """Add a pending confirmation to the queue (FIFO).

        Issue #1314: Enforces max_pending_confirmations cap. Oldest entries
        are evicted when the queue is full.
        """
        with self._lock:
            self.pending_confirmations.append(action)
            if len(self.pending_confirmations) > self.max_pending_confirmations:
                self.pending_confirmations = self.pending_confirmations[
                    -self.max_pending_confirmations :
                ]

    def pop_pending_confirmation(self) -> Optional[dict[str, Any]]:
        """Pop the next pending confirmation from the queue (FIFO)."""
        with self._lock:
            if not self.pending_confirmations:
                return None
            return self.pending_confirmations.pop(0)

    def peek_pending_confirmation(self) -> Optional[dict[str, Any]]:
        """Peek the next pending confirmation without removing it."""
        with self._lock:
            if not self.pending_confirmations:
                return None
            return self.pending_confirmations[0]
    
    def clear_pending_confirmation(self) -> None:
        """Clear all pending confirmations (user approved/rejected)."""
        with self._lock:
            self.pending_confirmations = []
            self.confirmed_tool = None
    
    def has_pending_confirmation(self) -> bool:
        """Check if there's a pending confirmation."""
        with self._lock:
            return bool(self.pending_confirmations)
    
    def update_trace(self, **kwargs: Any) -> None:
        """Update trace metadata.

        Issue #1314: Enforces max_trace_keys cap. Oldest keys are evicted
        when the dict exceeds the limit.
        """
        self.trace.update(kwargs)
        if len(self.trace) > self.max_trace_keys:
            keys_to_drop = list(self.trace.keys())[
                : len(self.trace) - self.max_trace_keys
            ]
            for k in keys_to_drop:
                del self.trace[k]

    def set_gmail_listed_messages(self, messages: list[dict[str, str]]) -> None:
        """Set gmail listed messages with cap enforcement.

        Issue #1314: Keeps only the last max_gmail_listed entries.

        Args:
            messages: List of Gmail message dicts (id, from, subject).

        Returns:
            None. Caps ``gmail_listed_messages`` to ``max_gmail_listed``.
        """
        self.gmail_listed_messages = messages[-self.max_gmail_listed :]

    def set_calendar_listed_events(self, events: list[dict[str, Any]]) -> None:
        """Set calendar listed events with cap enforcement.

        Issue #1314: Keeps only the last max_calendar_listed entries.

        Args:
            events: List of calendar event dicts (id, summary, start, end).

        Returns:
            None. Caps ``calendar_listed_events`` to ``max_calendar_listed``.
        """
        self.calendar_listed_events = events[-self.max_calendar_listed :]

    def add_react_observation(self, observation: dict[str, Any]) -> None:
        """Add a ReAct observation with cap enforcement.

        Issue #1314: Keeps only the last max_react_observations entries.

        Args:
            observation: ReAct observation dict (iteration, tool, result_summary, success).

        Returns:
            None. Appends to ``react_observations`` and caps to ``max_react_observations``.
        """
        self.react_observations.append(observation)
        if len(self.react_observations) > self.max_react_observations:
            self.react_observations = self.react_observations[
                -self.max_react_observations :
            ]
    
    def get_context_for_llm(self) -> dict[str, Any]:
        """Get context to send to LLM (summary + recent history + tool results).

        NOTE: result_raw is intentionally excluded — only the lightweight
        result_summary is sent to the LLM to save context window budget.

        Issue #1278: Uses adaptive compaction — last 3 turns raw, older
        turns summarised.  Falls back to raw list when ≤3 turns.
        """
        safe_results = [
            {
                "tool": r.get("tool", ""),
                "result_summary": r.get("result_summary", r.get("result", "")),
                "success": r.get("success", True),
            }
            for r in self.last_tool_results
        ]
        # Issue #1278: adaptive compaction instead of hardcoded [-2:]
        compacted_history = self.compact_conversation_history(raw_tail=3)
        ctx = {
            "rolling_summary": self.rolling_summary,
            "recent_conversation": compacted_history,
            "last_tool_results": safe_results,
            "pending_confirmation": self.peek_pending_confirmation(),
            "pending_confirmations": list(self.pending_confirmations),
        }
        # Issue #1273: Include ReAct observations if mid-loop
        if self.react_observations:
            ctx["react_observations"] = list(self.react_observations)
        # Issue #1276: Include active entity context for cross-turn slot tracking
        entity_block = self.slot_registry.to_prompt_block()
        if entity_block:
            ctx["entity_context"] = entity_block
        # Issue #1279: Include subtask progress if mid-plan
        if self.subtask_plan is not None and not self.subtask_plan.is_empty:
            progress = self.subtask_plan.to_progress_block()
            if progress:
                ctx["subtask_progress"] = progress
        return ctx
    
    def reset(self) -> None:
        """Reset state (new session)."""
        self.rolling_summary = ""
        self.last_tool_results = []
        self.pending_confirmations = []
        self.confirmed_tool = None
        self.trace = {}
        self.conversation_history = []
        self.turn_count = 0
        self.current_user_input = ""  # Issue #1316: clear stale input
        self.session_context = None
        self.reference_table = None
        self.disambiguation_pending = None
        self.last_tool_called = ""
        self.last_tool_route = ""
        self.gmail_next_page_token = ""
        self.gmail_last_query = ""
        self.gmail_listed_messages = []
        self.calendar_listed_events = []
        self.detected_lang = ""
        self.canonical_input = ""
        self.react_observations = []
        self.react_iteration = 0
        self.slot_registry.clear()
        self.subtask_plan = None
