"""Proactive Rule Engine — Hybrid rule + LLM reasoning.

The :class:`ProactiveRuleEngine` evaluates collected :class:`DailySignals`
against a set of declarative **rules** and optionally augments the
output with LLM-generated contextual suggestions.

Each :class:`Rule` has a callable ``condition`` that receives a
``DailySignals`` instance along with an ``action`` template rendered
when the condition is met.

Issue #1293
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from bantz.proactive.models import InsightSeverity
from bantz.proactive.signals import DailySignals

logger = logging.getLogger(__name__)


# ── Rule Definition ─────────────────────────────────────────────


@dataclass
class Rule:
    """A single proactive rule.

    Parameters
    ----------
    name:
        Unique identifier.
    condition:
        Callable ``(DailySignals) -> bool``.
    action:
        Message template (may contain ``{var}`` placeholders).
    priority:
        Higher = more important (1–5, default 1).
    severity:
        How urgently the user should know about this.
    enabled:
        Whether the rule is currently active.
    """

    name: str
    condition: Callable[[DailySignals], bool]
    action: str
    priority: int = 1
    severity: InsightSeverity = InsightSeverity.INFO
    enabled: bool = True


@dataclass
class RuleSuggestion:
    """Result of a single rule evaluation."""

    rule_name: str
    message: str
    priority: int = 1
    severity: InsightSeverity = InsightSeverity.INFO
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule_name,
            "message": self.message,
            "priority": self.priority,
            "severity": self.severity.value,
            "metadata": self.metadata,
        }


# ── Built-in Rules ──────────────────────────────────────────────


def _rain_alert(signals: DailySignals) -> bool:
    """Trigger when rain probability > 60%."""
    return signals.weather.rain_probability > 0.6


def _pending_rsvp(signals: DailySignals) -> bool:
    """Trigger when there are pending RSVPs for tomorrow."""
    return len(signals.calendar.pending_rsvp) > 0


def _deadline_approaching(signals: DailySignals) -> bool:
    """Trigger when any task is due today or overdue."""
    return len(signals.tasks.due_today) > 0 or len(signals.tasks.overdue) > 0


def _free_slot_suggestion(signals: DailySignals) -> bool:
    """Trigger when there are free slots and pending tasks."""
    return len(signals.calendar.free_slots) > 0 and signals.tasks.has_pending


def _urgent_mail(signals: DailySignals) -> bool:
    """Trigger when there are urgent unread emails."""
    return len(signals.emails.urgent) > 0


def _high_unread(signals: DailySignals) -> bool:
    """Trigger when unread count exceeds threshold."""
    return signals.emails.unread_count >= 15


def _overdue_tasks(signals: DailySignals) -> bool:
    """Trigger when there are overdue tasks."""
    return len(signals.tasks.overdue) > 0


DEFAULT_RULES: list[Rule] = [
    Rule(
        name="rain_alert",
        condition=_rain_alert,
        action="🌧️ Bugün yağmur olasılığı yüksek — şemsiye almayı unutma!",
        priority=2,
        severity=InsightSeverity.WARNING,
    ),
    Rule(
        name="pending_rsvp",
        condition=_pending_rsvp,
        action="⚠️ Yarınki toplantılarda kabul edilmemiş davetler var.",
        priority=3,
        severity=InsightSeverity.WARNING,
    ),
    Rule(
        name="deadline_approaching",
        condition=_deadline_approaching,
        action="📋 Yaklaşan veya gecikmiş görevler var!",
        priority=4,
        severity=InsightSeverity.WARNING,
    ),
    Rule(
        name="free_slot_suggestion",
        condition=_free_slot_suggestion,
        action="💡 Bugün boş slotlarınız var — bekleyen görevler için çalışma bloğu koyalım mı?",
        priority=1,
        severity=InsightSeverity.INFO,
    ),
    Rule(
        name="urgent_mail",
        condition=_urgent_mail,
        action="⚡ Acil okunmamış mailler var!",
        priority=4,
        severity=InsightSeverity.CRITICAL,
    ),
    Rule(
        name="high_unread",
        condition=_high_unread,
        action="📧 Okunmamış mail sayısı çok yüksek — inbox temizliği gerekebilir.",
        priority=2,
        severity=InsightSeverity.WARNING,
    ),
    Rule(
        name="overdue_tasks",
        condition=_overdue_tasks,
        action="🚨 Süresi geçmiş görevler var — hemen ilgilenilmeli!",
        priority=5,
        severity=InsightSeverity.CRITICAL,
    ),
]


# ── Rule Engine ─────────────────────────────────────────────────


class ProactiveRuleEngine:
    """Hybrid rule-based + LLM reasoning engine.

    Evaluates a set of :class:`Rule` objects against collected
    :class:`DailySignals`.  When ``llm_callback`` is provided,
    an LLM can generate additional contextual suggestions beyond
    the static rules.

    Parameters
    ----------
    rules:
        Initial rule set.  Defaults to :data:`DEFAULT_RULES`.
    llm_callback:
        Optional async callable ``(DailySignals, list[RuleSuggestion]) -> list[RuleSuggestion]``
        for LLM-augmented reasoning.
    """

    def __init__(
        self,
        rules: Optional[List[Rule]] = None,
        llm_callback: Optional[Callable] = None,
    ) -> None:
        self._rules: Dict[str, Rule] = {}
        for rule in (rules if rules is not None else DEFAULT_RULES):
            self._rules[rule.name] = rule
        self._llm_callback = llm_callback

    # ── Public API ──────────────────────────────────────────────

    @property
    def rule_names(self) -> list[str]:
        """Return names of all registered rules."""
        return list(self._rules.keys())

    def add_rule(self, rule: Rule) -> None:
        """Register a custom rule."""
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.  Returns ``True`` if found."""
        return self._rules.pop(name, None) is not None

    def get_rule(self, name: str) -> Optional[Rule]:
        """Get a rule by name."""
        return self._rules.get(name)

    def enable_rule(self, name: str) -> bool:
        """Enable a rule.  Returns ``True`` if found."""
        rule = self._rules.get(name)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, name: str) -> bool:
        """Disable a rule.  Returns ``True`` if found."""
        rule = self._rules.get(name)
        if rule:
            rule.enabled = False
            return True
        return False

    async def evaluate(self, signals: DailySignals) -> list[RuleSuggestion]:
        """Evaluate all enabled rules against collected signals.

        Steps:
        1. Run each enabled rule's condition
        2. Build ``RuleSuggestion`` for matched rules
        3. Enrich with context-specific metadata
        4. Optionally run LLM callback for additional suggestions
        5. Return sorted by priority (highest first)
        """
        suggestions: list[RuleSuggestion] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue
            try:
                if rule.condition(signals):
                    suggestion = self._build_suggestion(rule, signals)
                    suggestions.append(suggestion)
            except Exception as exc:
                logger.warning("Rule '%s' evaluation failed: %s", rule.name, exc)

        # LLM augmentation
        if self._llm_callback is not None:
            try:
                llm_suggestions = await self._llm_callback(signals, suggestions)
                if isinstance(llm_suggestions, list):
                    suggestions.extend(llm_suggestions)
            except Exception as exc:
                logger.warning("LLM reasoning failed: %s", exc)

        # Sort by priority (descending)
        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions

    def evaluate_sync(self, signals: DailySignals) -> list[RuleSuggestion]:
        """Synchronous version of :meth:`evaluate` (no LLM)."""
        suggestions: list[RuleSuggestion] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            try:
                if rule.condition(signals):
                    suggestions.append(self._build_suggestion(rule, signals))
            except Exception as exc:
                logger.warning("Rule '%s' evaluation failed: %s", rule.name, exc)
        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions

    # ── Internal ────────────────────────────────────────────────

    def _build_suggestion(
        self,
        rule: Rule,
        signals: DailySignals,
    ) -> RuleSuggestion:
        """Create a ``RuleSuggestion`` with context-enriched metadata."""
        metadata: Dict[str, Any] = {}
        message = rule.action

        if rule.name == "rain_alert":
            prob = signals.weather.rain_probability
            message = f"🌧️ Bugün yağmur olasılığı %{int(prob * 100)} — şemsiye almayı unutma!"
            metadata["rain_probability"] = prob

        elif rule.name == "pending_rsvp":
            count = len(signals.calendar.pending_rsvp)
            message = f"⚠️ Yarınki toplantılarda {count} katılımcı henüz kabul etmedi."
            metadata["pending_count"] = count
            metadata["events"] = [
                e.get("summary", "?") for e in signals.calendar.pending_rsvp[:3]
            ]

        elif rule.name == "deadline_approaching":
            today_names = [t.get("title", "?") for t in signals.tasks.due_today[:3]]
            overdue_names = [t.get("title", "?") for t in signals.tasks.overdue[:3]]
            parts = []
            if today_names:
                parts.append(f"Bugün: {', '.join(today_names)}")
            if overdue_names:
                parts.append(f"Gecikmiş: {', '.join(overdue_names)}")
            message = f"📋 Yaklaşan görevler — {'; '.join(parts)}"
            metadata["due_today"] = today_names
            metadata["overdue"] = overdue_names

        elif rule.name == "free_slot_suggestion":
            slot = signals.calendar.free_slots[0] if signals.calendar.free_slots else None
            task = signals.tasks.active_tasks[0] if signals.tasks.active_tasks else None
            if slot and task:
                message = (
                    f"💡 {slot.start}-{slot.end} arası boş — "
                    f"'{task.get('title', '?')}' için çalışma bloğu koyalım mı?"
                )
                metadata["slot"] = slot.to_dict()
                metadata["task"] = task.get("title", "?")

        elif rule.name == "urgent_mail":
            count = len(signals.emails.urgent)
            message = f"⚡ {count} acil okunmamış mail var!"
            metadata["urgent_count"] = count

        elif rule.name == "high_unread":
            message = f"📧 {signals.emails.unread_count} okunmamış mail birikmiş — inbox temizliği gerekebilir."
            metadata["unread_count"] = signals.emails.unread_count

        elif rule.name == "overdue_tasks":
            names = [t.get("title", "?") for t in signals.tasks.overdue[:5]]
            message = f"🚨 {len(signals.tasks.overdue)} süresi geçmiş görev: {', '.join(names)}"
            metadata["overdue_tasks"] = names

        return RuleSuggestion(
            rule_name=rule.name,
            message=message,
            priority=rule.priority,
            severity=rule.severity,
            metadata=metadata,
        )
