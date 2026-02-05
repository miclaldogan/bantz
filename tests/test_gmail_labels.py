"""Tests for Gmail label utilities.

Issue #317: Gmail label/kategori desteği

Tests cover:
- GmailLabel enum
- Turkish keyword detection
- Query building
- Smart search
"""

from typing import Any

import pytest

from bantz.google.gmail_labels import (
    GmailLabel,
    LabelMatch,
    TURKISH_LABEL_KEYWORDS,
    build_label_query,
    build_smart_query,
    detect_label_from_text,
    format_labels_summary,
    get_all_labels,
    get_category_labels,
    get_system_labels,
)


# =============================================================================
# GmailLabel Enum Tests
# =============================================================================

class TestGmailLabel:
    """Tests for GmailLabel enum."""
    
    def test_inbox_value(self) -> None:
        """Test INBOX value."""
        assert GmailLabel.INBOX.value == "INBOX"
    
    def test_category_social_value(self) -> None:
        """Test CATEGORY_SOCIAL value."""
        assert GmailLabel.CATEGORY_SOCIAL.value == "CATEGORY_SOCIAL"
    
    def test_label_id(self) -> None:
        """Test label_id property."""
        assert GmailLabel.INBOX.label_id == "INBOX"
        assert GmailLabel.CATEGORY_UPDATES.label_id == "CATEGORY_UPDATES"
    
    def test_display_name_tr(self) -> None:
        """Test Turkish display names."""
        assert GmailLabel.INBOX.display_name_tr == "Gelen Kutusu"
        assert GmailLabel.SENT.display_name_tr == "Gönderilenler"
        assert GmailLabel.CATEGORY_SOCIAL.display_name_tr == "Sosyal"
        assert GmailLabel.CATEGORY_PROMOTIONS.display_name_tr == "Promosyonlar"
        assert GmailLabel.CATEGORY_UPDATES.display_name_tr == "Güncellemeler"
    
    def test_display_name_en(self) -> None:
        """Test English display names."""
        assert GmailLabel.INBOX.display_name_en == "Inbox"
        assert GmailLabel.SENT.display_name_en == "Sent"
        assert GmailLabel.CATEGORY_SOCIAL.display_name_en == "Social"
    
    def test_query_filter_inbox(self) -> None:
        """Test query filter for INBOX."""
        assert GmailLabel.INBOX.query_filter == "in:inbox"
    
    def test_query_filter_sent(self) -> None:
        """Test query filter for SENT."""
        assert GmailLabel.SENT.query_filter == "in:sent"
    
    def test_query_filter_starred(self) -> None:
        """Test query filter for STARRED."""
        assert GmailLabel.STARRED.query_filter == "is:starred"
    
    def test_query_filter_category(self) -> None:
        """Test query filter for categories."""
        assert GmailLabel.CATEGORY_SOCIAL.query_filter == "label:CATEGORY_SOCIAL"
        assert GmailLabel.CATEGORY_UPDATES.query_filter == "label:CATEGORY_UPDATES"


# =============================================================================
# Turkish Keyword Mapping Tests
# =============================================================================

class TestTurkishKeywords:
    """Tests for Turkish keyword mappings."""
    
    def test_gelen_kutusu_mapping(self) -> None:
        """Test gelen kutusu maps to INBOX."""
        assert TURKISH_LABEL_KEYWORDS["gelen kutusu"] == GmailLabel.INBOX
    
    def test_sosyal_mapping(self) -> None:
        """Test sosyal maps to CATEGORY_SOCIAL."""
        assert TURKISH_LABEL_KEYWORDS["sosyal"] == GmailLabel.CATEGORY_SOCIAL
    
    def test_promosyonlar_mapping(self) -> None:
        """Test promosyonlar maps to CATEGORY_PROMOTIONS."""
        assert TURKISH_LABEL_KEYWORDS["promosyonlar"] == GmailLabel.CATEGORY_PROMOTIONS
    
    def test_guncellemeler_mapping(self) -> None:
        """Test güncellemeler maps to CATEGORY_UPDATES."""
        assert TURKISH_LABEL_KEYWORDS["güncellemeler"] == GmailLabel.CATEGORY_UPDATES
    
    def test_ascii_variant_onemli(self) -> None:
        """Test ASCII variant 'onemli' maps to IMPORTANT."""
        assert TURKISH_LABEL_KEYWORDS["onemli"] == GmailLabel.IMPORTANT
    
    def test_yildizli_mapping(self) -> None:
        """Test yıldızlı maps to STARRED."""
        assert TURKISH_LABEL_KEYWORDS["yıldızlı"] == GmailLabel.STARRED


# =============================================================================
# LabelMatch Tests
# =============================================================================

class TestLabelMatch:
    """Tests for LabelMatch dataclass."""
    
    def test_detected_true(self) -> None:
        """Test detected property when label found."""
        match = LabelMatch(
            label=GmailLabel.INBOX,
            matched_keyword="gelen kutusu",
            confidence=0.9,
            original_text="gelen kutusundaki mailler",
        )
        assert match.detected is True
    
    def test_detected_false(self) -> None:
        """Test detected property when no label found."""
        match = LabelMatch.no_match("random text")
        assert match.detected is False
    
    def test_no_match_factory(self) -> None:
        """Test no_match factory method."""
        match = LabelMatch.no_match("some text")
        assert match.label is None
        assert match.matched_keyword is None
        assert match.confidence == 0.0
        assert match.original_text == "some text"


# =============================================================================
# Label Detection Tests
# =============================================================================

class TestDetectLabelFromText:
    """Tests for detect_label_from_text function."""
    
    def test_detect_sosyal(self) -> None:
        """Test detecting sosyal category."""
        match = detect_label_from_text("sosyal mailleri göster")
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_SOCIAL
        # Longer keyword "sosyal mailleri" matches before "sosyal"
        assert "sosyal" in match.matched_keyword
    
    def test_detect_promosyonlar(self) -> None:
        """Test detecting promosyonlar category."""
        match = detect_label_from_text("promosyonlar kategorisindeki mailler")
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_PROMOTIONS
    
    def test_detect_guncellemeler(self) -> None:
        """Test detecting güncellemeler category."""
        match = detect_label_from_text("güncellemeler kategorisinde ne var")
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_UPDATES
    
    def test_detect_gonderilenler(self) -> None:
        """Test detecting gönderilenler."""
        match = detect_label_from_text("gönderilen mailleri listele")
        assert match.detected is True
        assert match.label == GmailLabel.SENT
    
    def test_detect_yildizli(self) -> None:
        """Test detecting yıldızlı."""
        match = detect_label_from_text("yıldızlı mailleri göster")
        assert match.detected is True
        assert match.label == GmailLabel.STARRED
    
    def test_detect_gelen_kutusu(self) -> None:
        """Test detecting gelen kutusu."""
        match = detect_label_from_text("gelen kutusundaki maillerimi göster")
        assert match.detected is True
        assert match.label == GmailLabel.INBOX
    
    def test_no_detection_random_text(self) -> None:
        """Test no detection for random text."""
        match = detect_label_from_text("bugün hava nasıl")
        assert match.detected is False
    
    def test_no_detection_empty(self) -> None:
        """Test no detection for empty string."""
        match = detect_label_from_text("")
        assert match.detected is False
    
    def test_case_insensitive(self) -> None:
        """Test case insensitive detection."""
        match = detect_label_from_text("SOSYAL mailleri")
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_SOCIAL
    
    def test_english_keyword(self) -> None:
        """Test English keyword detection."""
        match = detect_label_from_text("show me inbox emails")
        assert match.detected is True
        assert match.label == GmailLabel.INBOX


# =============================================================================
# Query Building Tests
# =============================================================================

class TestBuildLabelQuery:
    """Tests for build_label_query function."""
    
    def test_inbox_query(self) -> None:
        """Test INBOX query."""
        query = build_label_query(GmailLabel.INBOX)
        assert query == "in:inbox"
    
    def test_category_updates_query(self) -> None:
        """Test CATEGORY_UPDATES query."""
        query = build_label_query(GmailLabel.CATEGORY_UPDATES)
        assert query == "label:CATEGORY_UPDATES"
    
    def test_with_unread_filter(self) -> None:
        """Test with unread filter."""
        query = build_label_query(GmailLabel.INBOX, include_unread_only=True)
        assert query == "in:inbox is:unread"
    
    def test_with_additional_query(self) -> None:
        """Test with additional query terms."""
        query = build_label_query(
            GmailLabel.CATEGORY_SOCIAL,
            additional_query="from:twitter",
        )
        assert query == "label:CATEGORY_SOCIAL from:twitter"


# =============================================================================
# Smart Query Tests
# =============================================================================

class TestBuildSmartQuery:
    """Tests for build_smart_query function."""
    
    def test_smart_query_sosyal(self) -> None:
        """Test smart query for sosyal."""
        query, label = build_smart_query("sosyal mailleri göster")
        assert "CATEGORY_SOCIAL" in query
        assert label == GmailLabel.CATEGORY_SOCIAL
    
    def test_smart_query_promosyonlar(self) -> None:
        """Test smart query for promosyonlar."""
        query, label = build_smart_query("promosyonlar kategorisindeki mailler")
        assert "CATEGORY_PROMOTIONS" in query
        assert label == GmailLabel.CATEGORY_PROMOTIONS
    
    def test_smart_query_no_label(self) -> None:
        """Test smart query with no label detected."""
        query, label = build_smart_query("son mailler")
        assert query == "in:inbox"
        assert label is None
    
    def test_smart_query_with_default(self) -> None:
        """Test smart query with default label."""
        query, label = build_smart_query(
            "son mailler",
            default_label=GmailLabel.INBOX,
        )
        assert query == "in:inbox"
        assert label == GmailLabel.INBOX
    
    def test_smart_query_with_unread(self) -> None:
        """Test smart query with unread filter."""
        query, label = build_smart_query(
            "sosyal mailleri",
            include_unread_only=True,
        )
        assert "is:unread" in query
        assert "CATEGORY_SOCIAL" in query


# =============================================================================
# Utility Function Tests
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions."""
    
    def test_format_labels_summary_tr(self) -> None:
        """Test Turkish label summary."""
        labels = [GmailLabel.CATEGORY_SOCIAL, GmailLabel.CATEGORY_UPDATES]
        summary = format_labels_summary(labels, language="tr")
        assert "Sosyal" in summary
        assert "Güncellemeler" in summary
    
    def test_format_labels_summary_en(self) -> None:
        """Test English label summary."""
        labels = [GmailLabel.CATEGORY_SOCIAL, GmailLabel.CATEGORY_UPDATES]
        summary = format_labels_summary(labels, language="en")
        assert "Social" in summary
        assert "Updates" in summary
    
    def test_format_labels_summary_empty(self) -> None:
        """Test empty label summary."""
        summary = format_labels_summary([])
        assert summary == ""
    
    def test_get_all_labels(self) -> None:
        """Test getting all labels."""
        labels = get_all_labels()
        assert len(labels) == len(GmailLabel)
        assert GmailLabel.INBOX in labels
    
    def test_get_category_labels(self) -> None:
        """Test getting category labels."""
        labels = get_category_labels()
        assert len(labels) == 5
        assert GmailLabel.CATEGORY_SOCIAL in labels
        assert GmailLabel.CATEGORY_PROMOTIONS in labels
        assert GmailLabel.INBOX not in labels
    
    def test_get_system_labels(self) -> None:
        """Test getting system labels."""
        labels = get_system_labels()
        assert GmailLabel.INBOX in labels
        assert GmailLabel.SENT in labels
        assert GmailLabel.CATEGORY_SOCIAL not in labels


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for Gmail labels."""
    
    def test_full_flow_updates_category(self) -> None:
        """Test full flow for detecting and querying updates category."""
        text = "güncellemeler kategorisindeki mailleri göster"
        
        # Detect label
        match = detect_label_from_text(text)
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_UPDATES
        
        # Build query
        query = build_label_query(match.label)
        assert query == "label:CATEGORY_UPDATES"
    
    def test_full_flow_promotions_category(self) -> None:
        """Test full flow for promotions category."""
        text = "promosyon mailleri"
        
        match = detect_label_from_text(text)
        assert match.detected is True
        assert match.label == GmailLabel.CATEGORY_PROMOTIONS
        
        query = build_label_query(match.label)
        assert query == "label:CATEGORY_PROMOTIONS"
    
    def test_full_flow_starred(self) -> None:
        """Test full flow for starred emails."""
        text = "yıldızlı mailleri göster"
        
        match = detect_label_from_text(text)
        assert match.detected is True
        assert match.label == GmailLabel.STARRED
        
        query = build_label_query(match.label)
        assert query == "is:starred"
    
    def test_turkish_social_email_request(self) -> None:
        """Test realistic Turkish social email request."""
        requests = [
            "sosyal mailleri göster",
            "sosyal kategorisindeki mailler",
            "social mailleri",
        ]
        
        for text in requests:
            match = detect_label_from_text(text)
            assert match.detected is True, f"Failed for: {text}"
            assert match.label == GmailLabel.CATEGORY_SOCIAL, f"Wrong label for: {text}"
    
    def test_different_label_requests(self) -> None:
        """Test various label requests."""
        test_cases = [
            ("gelen kutusu mailleri", GmailLabel.INBOX),
            ("gönderilenler mailleri", GmailLabel.SENT),
            ("taslaklar", GmailLabel.DRAFT),
            ("çöp kutusu", GmailLabel.TRASH),
            ("spam mailleri", GmailLabel.SPAM),
            ("önemli mailler", GmailLabel.IMPORTANT),
            ("forumlar kategorisi", GmailLabel.CATEGORY_FORUMS),
        ]
        
        for text, expected_label in test_cases:
            match = detect_label_from_text(text)
            assert match.detected is True, f"Failed for: {text}"
            assert match.label == expected_label, f"Wrong label for: {text}, got {match.label}"
