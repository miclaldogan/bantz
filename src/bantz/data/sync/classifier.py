"""
Sender & content classifier for ingested messages.

Rule-based classification engine that assigns category labels to
Gmail messages based on sender address, sender name, subject, and
content patterns.  Categories are user-extensible via YAML config.

Default categories::

    github        — GitHub notifications, CI/CD alerts
    tubitak       — TÜBİTAK e-mails
    linkedin      — LinkedIn notifications
    google        — Google service mails (Drive, Photos, Meet, etc.)
    amazon        — Amazon orders & shipping
    bank          — Banking / finance alerts
    newsletter    — Newsletters, digests, mailing lists
    social        — Social media (Twitter/X, Instagram, Facebook)
    education     — University / education platforms
    shopping      — E-commerce confirmations
    travel        — Booking, flight, hotel confirmations
    work          — Internal / corporate sender patterns
    personal      — Known personal contacts
    uncategorized — Default fallback

Usage::

    classifier = SenderClassifier()
    label = classifier.classify(sender="noreply@github.com",
                                 sender_name="GitHub",
                                 subject="[bantz] PR #42 merged")
    # → "github"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Classification rule ──────────────────────────────────────

@dataclass
class ClassificationRule:
    """A single rule that matches sender/subject patterns to a category."""
    category: str
    sender_patterns: List[str] = field(default_factory=list)
    sender_name_patterns: List[str] = field(default_factory=list)
    subject_patterns: List[str] = field(default_factory=list)
    domain_patterns: List[str] = field(default_factory=list)
    priority: int = 0  # higher = checked first

    def matches(
        self,
        sender: str = "",
        sender_name: str = "",
        subject: str = "",
    ) -> bool:
        """Return True if any pattern in this rule matches.

        Note: We use re.IGNORECASE on original strings instead of
        .lower() to avoid Turkish İ/i case folding issues where
        'İ'.lower() produces 'i̇' (with combining dot above).
        """
        for pattern in self.domain_patterns:
            if pattern.lower() in sender.lower():
                return True

        for pattern in self.sender_patterns:
            if re.search(pattern, sender, re.IGNORECASE):
                return True

        for pattern in self.sender_name_patterns:
            if re.search(pattern, sender_name, re.IGNORECASE):
                return True

        for pattern in self.subject_patterns:
            if re.search(pattern, subject, re.IGNORECASE):
                return True

        return False


# ── Default rules ────────────────────────────────────────────

_DEFAULT_RULES: List[ClassificationRule] = [
    ClassificationRule(
        category="github",
        sender_patterns=[r"github\.com", r"noreply\+.*@github\.com"],
        sender_name_patterns=[r"github"],
        subject_patterns=[r"\[.*\]\s*(PR|Issue|pull request|commit|merged|closed)"],
        domain_patterns=["github.com"],
        priority=90,
    ),
    ClassificationRule(
        category="tubitak",
        sender_patterns=[r"tubitak\.gov\.tr", r"ulakbim"],
        sender_name_patterns=[r"t[üu]bitak", r"tubitak", r"ulakbim", r"bideb"],
        subject_patterns=[r"t[üu]bitak", r"tubitak", r"bideb", r"ardeb", r"burs"],
        domain_patterns=["tubitak.gov.tr"],
        priority=90,
    ),
    ClassificationRule(
        category="linkedin",
        sender_patterns=[r"linkedin\.com"],
        sender_name_patterns=[r"linkedin"],
        subject_patterns=[r"linkedin"],
        domain_patterns=["linkedin.com"],
        priority=80,
    ),
    ClassificationRule(
        category="google",
        sender_patterns=[r"google\.com", r"youtube\.com"],
        sender_name_patterns=[r"google", r"youtube", r"google\s+(drive|photos|meet|classroom)"],
        domain_patterns=["google.com", "youtube.com", "googlemail.com"],
        priority=70,
    ),
    ClassificationRule(
        category="amazon",
        sender_patterns=[r"amazon\.(com|co|de|fr|com\.tr)"],
        sender_name_patterns=[r"amazon"],
        subject_patterns=[r"(sipariş|order|shipping|kargo|teslimat)"],
        domain_patterns=["amazon.com", "amazon.com.tr"],
        priority=70,
    ),
    ClassificationRule(
        category="bank",
        sender_patterns=[
            r"(garanti|akbank|isbank|yapikredi|ziraat|qnb|ing|hsbc|deniz)",
            r"(paypal|stripe|wise|n26)",
        ],
        sender_name_patterns=[
            r"(garanti|akbank|iş\s*bank|yapı\s*kredi|ziraat|finans|banka)",
            r"(paypal|stripe|wise)",
        ],
        subject_patterns=[r"(hesap|bakiye|transfer|ödeme|payment|transaction|fatura)"],
        priority=80,
    ),
    ClassificationRule(
        category="newsletter",
        sender_patterns=[r"(newsletter|digest|weekly|noreply|no-reply)"],
        sender_name_patterns=[r"(newsletter|digest|weekly|bulletin)"],
        subject_patterns=[r"(newsletter|digest|haftalık|weekly|roundup|özet)"],
        priority=30,
    ),
    ClassificationRule(
        category="social",
        sender_patterns=[
            r"(twitter|x\.com|instagram|facebook|meta\.com|tiktok|reddit)",
        ],
        sender_name_patterns=[
            r"(twitter|instagram|facebook|tiktok|reddit|x\.com)",
        ],
        domain_patterns=[
            "twitter.com", "x.com", "instagram.com",
            "facebook.com", "facebookmail.com", "tiktok.com",
        ],
        priority=60,
    ),
    ClassificationRule(
        category="education",
        sender_patterns=[r"\.edu(\.tr)?$", r"(university|üniversite|moodle|canvas)"],
        sender_name_patterns=[r"(university|üniversite|fakülte|rektörlük|öğrenci)"],
        subject_patterns=[r"(ders|sınav|ödev|exam|assignment|course|lecture|dönem)"],
        priority=60,
    ),
    ClassificationRule(
        category="shopping",
        sender_patterns=[
            r"(trendyol|hepsiburada|n11|gittigidiyor|aliexpress|etsy)",
        ],
        sender_name_patterns=[
            r"(trendyol|hepsiburada|n11|aliexpress|etsy)",
        ],
        subject_patterns=[r"(sipariş|kargo|teslimat|iade|fatura|order|delivery)"],
        domain_patterns=["trendyol.com", "hepsiburada.com"],
        priority=60,
    ),
    ClassificationRule(
        category="travel",
        sender_patterns=[
            r"(booking\.com|airbnb|hotels|thy\.com|pegasus|skyscanner|trivago)",
        ],
        sender_name_patterns=[
            r"(booking|airbnb|thy|türk\s*hava|pegasus|skyscanner)",
        ],
        subject_patterns=[r"(reservation|rezervasyon|flight|uçuş|otel|hotel)"],
        domain_patterns=["booking.com", "airbnb.com", "thy.com", "pegasus.com.tr"],
        priority=85,
    ),
]


# ── Classifier ───────────────────────────────────────────────

class SenderClassifier:
    """Rule-based email classifier with extensible rules.

    Parameters
    ----------
    extra_rules : list[ClassificationRule], optional
        Additional rules to merge with defaults.
    config_path : Path, optional
        Path to YAML config for custom rules (future).
    """

    def __init__(
        self,
        extra_rules: Optional[List[ClassificationRule]] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self._rules: List[ClassificationRule] = list(_DEFAULT_RULES)
        if extra_rules:
            self._rules.extend(extra_rules)
        # Sort by priority descending — higher priority checked first
        self._rules.sort(key=lambda r: r.priority, reverse=True)

        if config_path and config_path.exists():
            self._load_yaml_rules(config_path)

    def classify(
        self,
        sender: str = "",
        sender_name: str = "",
        subject: str = "",
    ) -> str:
        """Return the best matching category label, or 'uncategorized'."""
        for rule in self._rules:
            if rule.matches(sender=sender, sender_name=sender_name, subject=subject):
                return rule.category
        return "uncategorized"

    def classify_with_confidence(
        self,
        sender: str = "",
        sender_name: str = "",
        subject: str = "",
    ) -> Tuple[str, float]:
        """Return (category, confidence) where confidence ∈ [0, 1].

        Confidence is heuristic:
        - domain match → 0.95
        - sender regex match → 0.85
        - name match → 0.75
        - subject match → 0.60
        - no match → ('uncategorized', 0.0)

        Note: Uses re.IGNORECASE on original strings to avoid
        Turkish İ/i case folding issues.
        """
        for rule in self._rules:
            for pattern in rule.domain_patterns:
                if pattern.lower() in sender.lower():
                    return rule.category, 0.95

            for pattern in rule.sender_patterns:
                if re.search(pattern, sender, re.IGNORECASE):
                    return rule.category, 0.85

            for pattern in rule.sender_name_patterns:
                if re.search(pattern, sender_name, re.IGNORECASE):
                    return rule.category, 0.75

            for pattern in rule.subject_patterns:
                if re.search(pattern, subject, re.IGNORECASE):
                    return rule.category, 0.60

        return "uncategorized", 0.0

    @property
    def categories(self) -> List[str]:
        """Return all known category names."""
        seen: set[str] = set()
        result: list[str] = []
        for rule in self._rules:
            if rule.category not in seen:
                seen.add(rule.category)
                result.append(rule.category)
        result.append("uncategorized")
        return result

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def add_rule(self, rule: ClassificationRule) -> None:
        """Add a rule at runtime and re-sort."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def _load_yaml_rules(self, path: Path) -> None:
        """Load custom rules from YAML config (future extension point)."""
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict) or "rules" not in data:
                return
            for entry in data["rules"]:
                rule = ClassificationRule(
                    category=entry["category"],
                    sender_patterns=entry.get("sender_patterns", []),
                    sender_name_patterns=entry.get("sender_name_patterns", []),
                    subject_patterns=entry.get("subject_patterns", []),
                    domain_patterns=entry.get("domain_patterns", []),
                    priority=entry.get("priority", 50),
                )
                self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority, reverse=True)
            logger.info("Loaded %d custom classification rules from %s", len(data["rules"]), path)
        except Exception as e:
            logger.warning("Failed to load classification rules from %s: %s", path, e)


# ── Module-level convenience ─────────────────────────────────

_default_classifier: Optional[SenderClassifier] = None


def classify_sender(
    sender: str = "",
    sender_name: str = "",
    subject: str = "",
) -> str:
    """Classify using the default singleton classifier."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = SenderClassifier()
    return _default_classifier.classify(
        sender=sender, sender_name=sender_name, subject=subject,
    )
