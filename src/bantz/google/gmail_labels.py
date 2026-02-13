"""Gmail label utilities with Turkish language support.

Issue #317: Gmail label/kategori desteği

Provides:
- Gmail label enum with standard labels
- Turkish keyword mapping for label detection
- Label query builder for smart search
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import re


class GmailLabel(Enum):
    """Standard Gmail labels with their IDs.
    
    Gmail uses specific label IDs for system labels.
    User-created labels have IDs like "Label_123".
    """
    
    # Primary categories
    INBOX = "INBOX"
    SENT = "SENT"
    DRAFT = "DRAFT"
    TRASH = "TRASH"
    SPAM = "SPAM"
    STARRED = "STARRED"
    IMPORTANT = "IMPORTANT"
    UNREAD = "UNREAD"
    
    # Category tabs
    CATEGORY_PERSONAL = "CATEGORY_PERSONAL"
    CATEGORY_SOCIAL = "CATEGORY_SOCIAL"
    CATEGORY_PROMOTIONS = "CATEGORY_PROMOTIONS"
    CATEGORY_UPDATES = "CATEGORY_UPDATES"
    CATEGORY_FORUMS = "CATEGORY_FORUMS"
    
    @property
    def label_id(self) -> str:
        """Get the Gmail label ID."""
        return self.value
    
    @property
    def display_name_tr(self) -> str:
        """Get Turkish display name."""
        names = {
            GmailLabel.INBOX: "Gelen Kutusu",
            GmailLabel.SENT: "Gönderilenler",
            GmailLabel.DRAFT: "Taslaklar",
            GmailLabel.TRASH: "Çöp Kutusu",
            GmailLabel.SPAM: "Spam",
            GmailLabel.STARRED: "Yıldızlı",
            GmailLabel.IMPORTANT: "Önemli",
            GmailLabel.UNREAD: "Okunmamış",
            GmailLabel.CATEGORY_PERSONAL: "Birincil",
            GmailLabel.CATEGORY_SOCIAL: "Sosyal",
            GmailLabel.CATEGORY_PROMOTIONS: "Promosyonlar",
            GmailLabel.CATEGORY_UPDATES: "Güncellemeler",
            GmailLabel.CATEGORY_FORUMS: "Forumlar",
        }
        return names.get(self, self.value)
    
    @property
    def display_name_en(self) -> str:
        """Get English display name."""
        names = {
            GmailLabel.INBOX: "Inbox",
            GmailLabel.SENT: "Sent",
            GmailLabel.DRAFT: "Drafts",
            GmailLabel.TRASH: "Trash",
            GmailLabel.SPAM: "Spam",
            GmailLabel.STARRED: "Starred",
            GmailLabel.IMPORTANT: "Important",
            GmailLabel.UNREAD: "Unread",
            GmailLabel.CATEGORY_PERSONAL: "Primary",
            GmailLabel.CATEGORY_SOCIAL: "Social",
            GmailLabel.CATEGORY_PROMOTIONS: "Promotions",
            GmailLabel.CATEGORY_UPDATES: "Updates",
            GmailLabel.CATEGORY_FORUMS: "Forums",
        }
        return names.get(self, self.value)
    
    @property
    def query_filter(self) -> str:
        """Get the Gmail query filter for this label."""
        # For categories, use label: prefix
        if self.value.startswith("CATEGORY_"):
            return f"label:{self.value}"
        # For system labels, use in: or is: prefix
        elif self == GmailLabel.INBOX:
            return "in:inbox"
        elif self == GmailLabel.SENT:
            return "in:sent"
        elif self == GmailLabel.TRASH:
            return "in:trash"
        elif self == GmailLabel.SPAM:
            return "in:spam"
        elif self == GmailLabel.DRAFT:
            return "in:drafts"
        elif self == GmailLabel.STARRED:
            return "is:starred"
        elif self == GmailLabel.IMPORTANT:
            return "is:important"
        elif self == GmailLabel.UNREAD:
            return "is:unread"
        else:
            return f"label:{self.value}"


# Turkish keyword to label mapping
TURKISH_LABEL_KEYWORDS: dict[str, GmailLabel] = {
    # Gelen Kutusu
    "gelen kutusu": GmailLabel.INBOX,
    "gelen kutusundaki": GmailLabel.INBOX,
    "inbox": GmailLabel.INBOX,
    
    # Gönderilenler
    "gönderilenler": GmailLabel.SENT,
    "gönderilen": GmailLabel.SENT,
    "gönderdiğim": GmailLabel.SENT,
    "gönderdiğim mailler": GmailLabel.SENT,
    "sent": GmailLabel.SENT,
    
    # Taslaklar
    "taslaklar": GmailLabel.DRAFT,
    "taslak": GmailLabel.DRAFT,
    "draft": GmailLabel.DRAFT,
    "drafts": GmailLabel.DRAFT,
    
    # Çöp
    "çöp": GmailLabel.TRASH,
    "çöp kutusu": GmailLabel.TRASH,
    "silinen": GmailLabel.TRASH,
    "silinenler": GmailLabel.TRASH,
    "trash": GmailLabel.TRASH,
    
    # Spam
    "spam": GmailLabel.SPAM,
    "istenmeyen": GmailLabel.SPAM,
    "junk": GmailLabel.SPAM,
    
    # Yıldızlı
    "yıldızlı": GmailLabel.STARRED,
    "yildizli": GmailLabel.STARRED,  # ASCII variant
    "starred": GmailLabel.STARRED,
    "favoriler": GmailLabel.STARRED,
    "favori": GmailLabel.STARRED,
    
    # Önemli
    "önemli": GmailLabel.IMPORTANT,
    "onemli": GmailLabel.IMPORTANT,  # ASCII variant
    "important": GmailLabel.IMPORTANT,
    
    # Okunmamış
    "okunmamış": GmailLabel.UNREAD,
    "okunmamis": GmailLabel.UNREAD,  # ASCII variant
    "unread": GmailLabel.UNREAD,
    
    # Categories - Sosyal
    "sosyal": GmailLabel.CATEGORY_SOCIAL,
    "social": GmailLabel.CATEGORY_SOCIAL,
    "sosyal mailleri": GmailLabel.CATEGORY_SOCIAL,
    
    # Categories - Promosyonlar
    "promosyon": GmailLabel.CATEGORY_PROMOTIONS,
    "promosyonlar": GmailLabel.CATEGORY_PROMOTIONS,
    "promotions": GmailLabel.CATEGORY_PROMOTIONS,
    "reklam": GmailLabel.CATEGORY_PROMOTIONS,
    "reklamlar": GmailLabel.CATEGORY_PROMOTIONS,
    
    # Categories - Güncellemeler
    "güncelleme": GmailLabel.CATEGORY_UPDATES,
    "güncellemeler": GmailLabel.CATEGORY_UPDATES,
    "guncelleme": GmailLabel.CATEGORY_UPDATES,  # ASCII variant
    "guncellemeler": GmailLabel.CATEGORY_UPDATES,  # ASCII variant
    "updates": GmailLabel.CATEGORY_UPDATES,
    "bildirimler": GmailLabel.CATEGORY_UPDATES,
    
    # Categories - Forumlar
    "forum": GmailLabel.CATEGORY_FORUMS,
    "forumlar": GmailLabel.CATEGORY_FORUMS,
    "forums": GmailLabel.CATEGORY_FORUMS,
    
    # Categories - Birincil
    "birincil": GmailLabel.CATEGORY_PERSONAL,
    "primary": GmailLabel.CATEGORY_PERSONAL,
    "ana": GmailLabel.CATEGORY_PERSONAL,
    "ana kutu": GmailLabel.CATEGORY_PERSONAL,
}


@dataclass
class LabelMatch:
    """Result of label detection from text."""
    
    label: Optional[GmailLabel]
    matched_keyword: Optional[str]
    confidence: float
    original_text: str
    
    @property
    def detected(self) -> bool:
        """Whether a label was detected."""
        return self.label is not None
    
    @staticmethod
    def no_match(text: str) -> "LabelMatch":
        """Create a no-match result."""
        return LabelMatch(
            label=None,
            matched_keyword=None,
            confidence=0.0,
            original_text=text,
        )


def detect_label_from_text(text: str) -> LabelMatch:
    """Detect Gmail label from Turkish/English text.
    
    Args:
        text: User input text (e.g., "güncellemeler kategorisindeki mailler")
    
    Returns:
        LabelMatch with detected label or no match
    
    Examples:
        >>> detect_label_from_text("sosyal mailleri göster")
        LabelMatch(label=GmailLabel.CATEGORY_SOCIAL, ...)
        
        >>> detect_label_from_text("promosyonlar kategorisindeki mailleri oku")
        LabelMatch(label=GmailLabel.CATEGORY_PROMOTIONS, ...)
    """
    text_lower = text.lower().strip()
    
    if not text_lower:
        return LabelMatch.no_match(text)
    
    # Try longest matches first for better accuracy
    sorted_keywords = sorted(TURKISH_LABEL_KEYWORDS.keys(), key=len, reverse=True)
    
    for keyword in sorted_keywords:
        if keyword in text_lower:
            return LabelMatch(
                label=TURKISH_LABEL_KEYWORDS[keyword],
                matched_keyword=keyword,
                confidence=0.9,
                original_text=text,
            )
    
    return LabelMatch.no_match(text)


def build_label_query(
    label: GmailLabel,
    *,
    include_unread_only: bool = False,
    additional_query: Optional[str] = None,
) -> str:
    """Build Gmail query string for a label.
    
    Args:
        label: Gmail label to filter by
        include_unread_only: Add is:unread filter
        additional_query: Additional query terms to include
    
    Returns:
        Gmail query string
    
    Examples:
        >>> build_label_query(GmailLabel.CATEGORY_UPDATES)
        'label:CATEGORY_UPDATES'
        
        >>> build_label_query(GmailLabel.INBOX, include_unread_only=True)
        'in:inbox is:unread'
    """
    parts = [label.query_filter]
    
    if include_unread_only:
        parts.append("is:unread")
    
    if additional_query:
        parts.append(additional_query.strip())
    
    return " ".join(parts)


def build_smart_query(
    text: str,
    *,
    default_label: Optional[GmailLabel] = None,
    include_unread_only: bool = False,
) -> tuple[str, Optional[GmailLabel]]:
    """Build Gmail query from natural language text.
    
    Detects labels from Turkish text and builds appropriate query.
    Falls back to default_label if no label detected.
    
    Args:
        text: Natural language text (Turkish/English)
        default_label: Label to use if none detected (default: INBOX)
        include_unread_only: Add is:unread filter
    
    Returns:
        Tuple of (query_string, detected_label)
    
    Examples:
        >>> build_smart_query("sosyal mailleri göster")
        ('label:CATEGORY_SOCIAL', GmailLabel.CATEGORY_SOCIAL)
        
        >>> build_smart_query("son mailler")
        ('in:inbox', None)  # Falls back to default
    """
    match = detect_label_from_text(text)
    
    if match.detected and match.label:
        query = build_label_query(
            match.label,
            include_unread_only=include_unread_only,
        )
        return query, match.label
    
    # Fall back to default
    if default_label:
        query = build_label_query(
            default_label,
            include_unread_only=include_unread_only,
        )
        return query, default_label
    
    # No label - just basic inbox query
    parts = ["in:inbox"]
    if include_unread_only:
        parts.append("is:unread")
    return " ".join(parts), None


def format_labels_summary(labels: list[GmailLabel], language: str = "tr") -> str:
    """Format a list of labels for display.
    
    Args:
        labels: List of Gmail labels
        language: Display language ("tr" or "en")
    
    Returns:
        Formatted string with label names
    """
    if not labels:
        return ""
    
    names = []
    for label in labels:
        if language == "tr":
            names.append(label.display_name_tr)
        else:
            names.append(label.display_name_en)
    
    return ", ".join(names)


def get_all_labels() -> list[GmailLabel]:
    """Get all available Gmail labels."""
    return list(GmailLabel)


def get_category_labels() -> list[GmailLabel]:
    """Get Gmail category labels (tabs)."""
    return [
        GmailLabel.CATEGORY_PERSONAL,
        GmailLabel.CATEGORY_SOCIAL,
        GmailLabel.CATEGORY_PROMOTIONS,
        GmailLabel.CATEGORY_UPDATES,
        GmailLabel.CATEGORY_FORUMS,
    ]


def get_system_labels() -> list[GmailLabel]:
    """Get Gmail system labels."""
    return [
        GmailLabel.INBOX,
        GmailLabel.SENT,
        GmailLabel.DRAFT,
        GmailLabel.TRASH,
        GmailLabel.SPAM,
        GmailLabel.STARRED,
        GmailLabel.IMPORTANT,
        GmailLabel.UNREAD,
    ]
