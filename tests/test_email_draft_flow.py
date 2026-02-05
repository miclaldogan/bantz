"""Tests for email draft flow module.

Issue #246: Email draft flow with local intent + Gemini quality.

Tests cover:
- EmailType, PlaceholderType, DraftStatus enums
- Placeholder and EmailDraft dataclasses
- EmailIntent detection
- EmailDraftGenerator with templates
- EmailDraftFlow controller
- Safety validation
"""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from bantz.email.draft_flow import (
    EmailType,
    PlaceholderType,
    DraftStatus,
    Placeholder,
    EmailDraft,
    EmailIntent,
    detect_email_intent,
    EmailDraftGenerator,
    EmailDraftFlow,
    create_email_draft,
    extract_placeholders_from_text,
    validate_draft_safety,
)


# =============================================================================
# EmailType Tests
# =============================================================================

class TestEmailType:
    """Tests for EmailType enum."""
    
    def test_formal_value(self) -> None:
        """Test FORMAL value."""
        assert EmailType.FORMAL.value == "formal"
    
    def test_informal_value(self) -> None:
        """Test INFORMAL value."""
        assert EmailType.INFORMAL.value == "informal"
    
    def test_business_value(self) -> None:
        """Test BUSINESS value."""
        assert EmailType.BUSINESS.value == "business"
    
    def test_follow_up_value(self) -> None:
        """Test FOLLOW_UP value."""
        assert EmailType.FOLLOW_UP.value == "follow_up"
    
    def test_thank_you_value(self) -> None:
        """Test THANK_YOU value."""
        assert EmailType.THANK_YOU.value == "thank_you"


# =============================================================================
# PlaceholderType Tests
# =============================================================================

class TestPlaceholderType:
    """Tests for PlaceholderType enum."""
    
    def test_recipient_name_value(self) -> None:
        """Test RECIPIENT_NAME value."""
        assert PlaceholderType.RECIPIENT_NAME.value == "recipient_name"
    
    def test_pattern(self) -> None:
        """Test placeholder pattern."""
        assert PlaceholderType.RECIPIENT_NAME.pattern == "[[RECIPIENT_NAME]]"
    
    def test_description_tr(self) -> None:
        """Test Turkish description."""
        assert PlaceholderType.RECIPIENT_NAME.description_tr == "Alıcı adı"
        assert PlaceholderType.SENDER_NAME.description_tr == "Gönderen adı"


# =============================================================================
# DraftStatus Tests
# =============================================================================

class TestDraftStatus:
    """Tests for DraftStatus enum."""
    
    def test_draft_value(self) -> None:
        """Test DRAFT value."""
        assert DraftStatus.DRAFT.value == "draft"
    
    def test_approved_value(self) -> None:
        """Test APPROVED value."""
        assert DraftStatus.APPROVED.value == "approved"
    
    def test_sent_value(self) -> None:
        """Test SENT value."""
        assert DraftStatus.SENT.value == "sent"


# =============================================================================
# Placeholder Tests
# =============================================================================

class TestPlaceholder:
    """Tests for Placeholder dataclass."""
    
    def test_creation(self) -> None:
        """Test placeholder creation."""
        p = Placeholder(
            type=PlaceholderType.RECIPIENT_NAME,
            key="RECIPIENT_NAME",
        )
        assert p.type == PlaceholderType.RECIPIENT_NAME
        assert p.key == "RECIPIENT_NAME"
        assert p.value is None
        assert p.required is True
    
    def test_pattern_property(self) -> None:
        """Test pattern property."""
        p = Placeholder(
            type=PlaceholderType.RECIPIENT_NAME,
            key="RECIPIENT_NAME",
        )
        assert p.pattern == "[[RECIPIENT_NAME]]"
    
    def test_is_resolved_false(self) -> None:
        """Test is_resolved when not resolved."""
        p = Placeholder(
            type=PlaceholderType.RECIPIENT_NAME,
            key="RECIPIENT_NAME",
        )
        assert p.is_resolved is False
    
    def test_is_resolved_true(self) -> None:
        """Test is_resolved when resolved."""
        p = Placeholder(
            type=PlaceholderType.RECIPIENT_NAME,
            key="RECIPIENT_NAME",
            value="Ahmet Bey",
        )
        assert p.is_resolved is True
    
    def test_resolve(self) -> None:
        """Test resolve method."""
        p = Placeholder(
            type=PlaceholderType.RECIPIENT_NAME,
            key="RECIPIENT_NAME",
        )
        p.resolve("Ahmet Bey")
        assert p.value == "Ahmet Bey"
        assert p.is_resolved is True


# =============================================================================
# EmailDraft Tests
# =============================================================================

class TestEmailDraft:
    """Tests for EmailDraft dataclass."""
    
    def test_creation(self) -> None:
        """Test draft creation."""
        draft = EmailDraft(
            subject="Test Konu",
            body="Test içerik",
        )
        assert draft.subject == "Test Konu"
        assert draft.body == "Test içerik"
        assert draft.email_type == EmailType.FORMAL
        assert draft.status == DraftStatus.DRAFT
    
    def test_get_unresolved_placeholders(self) -> None:
        """Test getting unresolved placeholders."""
        draft = EmailDraft(
            subject="Test",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME"),
                Placeholder(PlaceholderType.SENDER_NAME, "SENDER_NAME", value="Ben"),
            ],
        )
        unresolved = draft.get_unresolved_placeholders()
        assert len(unresolved) == 1
        assert unresolved[0].key == "RECIPIENT_NAME"
    
    def test_has_unresolved_true(self) -> None:
        """Test has_unresolved when true."""
        draft = EmailDraft(
            subject="Test",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME"),
            ],
        )
        assert draft.has_unresolved() is True
    
    def test_has_unresolved_false(self) -> None:
        """Test has_unresolved when all resolved."""
        draft = EmailDraft(
            subject="Test",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME", value="Ali"),
            ],
        )
        assert draft.has_unresolved() is False
    
    def test_has_required_unresolved(self) -> None:
        """Test has_required_unresolved."""
        draft = EmailDraft(
            subject="Test",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME", required=True),
                Placeholder(PlaceholderType.CUSTOM, "OPTIONAL", required=False),
            ],
        )
        assert draft.has_required_unresolved() is True
    
    def test_resolve_placeholder(self) -> None:
        """Test resolving placeholder."""
        draft = EmailDraft(
            subject="Test",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME"),
            ],
        )
        result = draft.resolve_placeholder("RECIPIENT_NAME", "Ahmet Bey")
        assert result is True
        assert draft.placeholders[0].value == "Ahmet Bey"
    
    def test_resolve_placeholder_not_found(self) -> None:
        """Test resolving non-existent placeholder."""
        draft = EmailDraft(subject="Test", body="Test", placeholders=[])
        result = draft.resolve_placeholder("NONEXISTENT", "value")
        assert result is False
    
    def test_get_resolved_body(self) -> None:
        """Test getting resolved body."""
        draft = EmailDraft(
            subject="Test",
            body="Sayın [[RECIPIENT_NAME]], mesaj",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME", value="Ahmet Bey"),
            ],
        )
        assert draft.get_resolved_body() == "Sayın Ahmet Bey, mesaj"
    
    def test_get_resolved_subject(self) -> None:
        """Test getting resolved subject."""
        draft = EmailDraft(
            subject="Konu: [[KONU]]",
            body="Test",
            placeholders=[
                Placeholder(PlaceholderType.CUSTOM, "KONU", value="Toplantı"),
            ],
        )
        assert draft.get_resolved_subject() == "Konu: Toplantı"
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        draft = EmailDraft(
            subject="Test",
            body="Test body",
            email_type=EmailType.BUSINESS,
        )
        d = draft.to_dict()
        assert d["subject"] == "Test"
        assert d["body"] == "Test body"
        assert d["email_type"] == "business"
    
    def test_from_dict(self) -> None:
        """Test from_dict creation."""
        data = {
            "subject": "Test",
            "body": "Test body",
            "email_type": "informal",
            "placeholders": [
                {"type": "recipient_name", "key": "RECIPIENT_NAME", "value": None, "required": True}
            ],
        }
        draft = EmailDraft.from_dict(data)
        assert draft.subject == "Test"
        assert draft.email_type == EmailType.INFORMAL
        assert len(draft.placeholders) == 1
    
    def test_format_preview(self) -> None:
        """Test format preview."""
        draft = EmailDraft(
            subject="Test Konu",
            body="Test içerik",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME"),
            ],
        )
        preview = draft.format_preview()
        assert "E-POSTA TASLAĞI" in preview
        assert "Test Konu" in preview
        assert "RECIPIENT_NAME" in preview


# =============================================================================
# EmailIntent Tests
# =============================================================================

class TestEmailIntent:
    """Tests for EmailIntent dataclass."""
    
    def test_no_match(self) -> None:
        """Test no_match factory."""
        intent = EmailIntent.no_match()
        assert intent.detected is False
    
    def test_creation(self) -> None:
        """Test intent creation."""
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            recipient_hint="Ahmet",
            confidence=0.9,
        )
        assert intent.detected is True
        assert intent.email_type == EmailType.FORMAL
        assert intent.recipient_hint == "Ahmet"


# =============================================================================
# Intent Detection Tests
# =============================================================================

class TestDetectEmailIntent:
    """Tests for detect_email_intent function."""
    
    def test_detect_email_request(self) -> None:
        """Test detecting email request."""
        intent = detect_email_intent("E-posta yaz")
        assert intent.detected is True
    
    def test_detect_mail_keyword(self) -> None:
        """Test detecting with mail keyword."""
        intent = detect_email_intent("Mail hazırla")
        assert intent.detected is True
    
    def test_no_detection_for_unrelated(self) -> None:
        """Test no detection for unrelated text."""
        intent = detect_email_intent("Bugün hava nasıl?")
        assert intent.detected is False
    
    def test_detect_formal_type(self) -> None:
        """Test detecting formal email type."""
        intent = detect_email_intent("Resmi e-posta yaz")
        assert intent.email_type == EmailType.FORMAL
    
    def test_detect_informal_type(self) -> None:
        """Test detecting informal email type."""
        intent = detect_email_intent("Samimi bir mail hazırla")
        assert intent.email_type == EmailType.INFORMAL
    
    def test_detect_business_type(self) -> None:
        """Test detecting business email type."""
        intent = detect_email_intent("İş teklifi için e-posta yaz")
        assert intent.email_type == EmailType.BUSINESS
    
    def test_detect_thank_you_type(self) -> None:
        """Test detecting thank you email type."""
        intent = detect_email_intent("Teşekkür e-postası hazırla")
        assert intent.email_type == EmailType.THANK_YOU
    
    def test_detect_apology_type(self) -> None:
        """Test detecting apology email type."""
        intent = detect_email_intent("Özür dileme maili yaz")
        assert intent.email_type == EmailType.APOLOGY
    
    def test_detect_urgency(self) -> None:
        """Test detecting urgency."""
        intent = detect_email_intent("Acil e-posta yaz")
        assert intent.urgency > 0.8
    
    def test_detect_english_language(self) -> None:
        """Test detecting English language."""
        intent = detect_email_intent("İngilizce e-posta yaz")
        assert intent.language == "en"


# =============================================================================
# EmailDraftGenerator Tests
# =============================================================================

class TestEmailDraftGenerator:
    """Tests for EmailDraftGenerator class."""
    
    def test_generate_formal_draft(self) -> None:
        """Test generating formal draft."""
        generator = EmailDraftGenerator()
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            language="tr",
        )
        draft = generator.generate_draft(intent)
        
        assert draft.email_type == EmailType.FORMAL
        assert "Sayın" in draft.body
        assert "Saygılarımla" in draft.body
    
    def test_generate_informal_draft(self) -> None:
        """Test generating informal draft."""
        generator = EmailDraftGenerator()
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.INFORMAL,
            language="tr",
        )
        draft = generator.generate_draft(intent)
        
        assert "Merhaba" in draft.body
    
    def test_generate_with_recipient_hint(self) -> None:
        """Test generating with recipient hint."""
        generator = EmailDraftGenerator()
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            recipient_hint="Ahmet Bey",
            language="tr",
        )
        draft = generator.generate_draft(intent)
        
        assert "Ahmet Bey" in draft.body
    
    def test_generate_business_has_company_placeholder(self) -> None:
        """Test business draft has company placeholder."""
        generator = EmailDraftGenerator()
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.BUSINESS,
            language="tr",
        )
        draft = generator.generate_draft(intent)
        
        company_placeholders = [p for p in draft.placeholders if p.type == PlaceholderType.COMPANY_NAME]
        assert len(company_placeholders) > 0
    
    def test_generate_with_cloud_refiner(self) -> None:
        """Test generating with cloud refiner."""
        mock_refiner = MagicMock(return_value="Refined text")
        generator = EmailDraftGenerator(cloud_refiner=mock_refiner)
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            language="tr",
        )
        draft = generator.generate_draft(intent, use_cloud=True)
        
        assert draft.generation_tier == "cloud"
        mock_refiner.assert_called_once()
    
    def test_generate_english_draft(self) -> None:
        """Test generating English draft."""
        generator = EmailDraftGenerator()
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            language="en",
        )
        draft = generator.generate_draft(intent)
        
        assert "Dear" in draft.body
        assert "Best regards" in draft.body


# =============================================================================
# EmailDraftFlow Tests
# =============================================================================

class TestEmailDraftFlow:
    """Tests for EmailDraftFlow controller."""
    
    def test_start_draft(self) -> None:
        """Test starting a draft."""
        flow = EmailDraftFlow()
        draft = flow.start_draft("E-posta yaz")
        
        assert draft is not None
        assert flow.current_draft == draft
    
    def test_start_draft_with_unrecognized_request(self) -> None:
        """Test starting draft with unrecognized request."""
        flow = EmailDraftFlow()
        draft = flow.start_draft("Some random text")
        
        # Should still create a draft with defaults
        assert draft is not None
    
    def test_update_placeholder(self) -> None:
        """Test updating placeholder."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        result = flow.update_placeholder("RECIPIENT_NAME", "Ahmet Bey")
        assert result is True
    
    def test_update_placeholder_no_draft(self) -> None:
        """Test updating placeholder without draft."""
        flow = EmailDraftFlow()
        result = flow.update_placeholder("RECIPIENT_NAME", "Ahmet Bey")
        assert result is False
    
    def test_approve_draft(self) -> None:
        """Test approving draft."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        # Fill required placeholders
        for p in flow.current_draft.placeholders:
            if p.required:
                p.resolve("Test Value")
        
        result = flow.approve_draft()
        assert result is True
        assert flow.current_draft.status == DraftStatus.APPROVED
    
    def test_approve_draft_with_unresolved(self) -> None:
        """Test approving draft with unresolved placeholders."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        # Don't fill placeholders
        result = flow.approve_draft()
        assert result is False
    
    def test_reject_draft(self) -> None:
        """Test rejecting draft."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        result = flow.reject_draft()
        assert result is True
        assert flow.current_draft is None
    
    def test_get_preview(self) -> None:
        """Test getting preview."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        preview = flow.get_preview()
        assert "E-POSTA TASLAĞI" in preview
    
    def test_get_preview_no_draft(self) -> None:
        """Test getting preview without draft."""
        flow = EmailDraftFlow()
        preview = flow.get_preview()
        assert "Aktif taslak yok" in preview
    
    def test_get_resolved_email(self) -> None:
        """Test getting resolved email."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        # Fill all required placeholders
        for p in flow.current_draft.placeholders:
            if p.required:
                p.resolve("Test Value")
        
        result = flow.get_resolved_email()
        assert result is not None
        assert "subject" in result
        assert "body" in result
    
    def test_get_resolved_email_with_unresolved(self) -> None:
        """Test getting resolved email with unresolved placeholders."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        result = flow.get_resolved_email()
        assert result is None
    
    def test_simulate_send(self) -> None:
        """Test simulating send."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        # Fill and approve
        for p in flow.current_draft.placeholders:
            if p.required:
                p.resolve("Test Value")
        flow.approve_draft()
        
        result = flow.simulate_send()
        assert result["success"] is True
        assert result["simulated"] is True
    
    def test_simulate_send_not_approved(self) -> None:
        """Test simulating send without approval."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        result = flow.simulate_send()
        assert result["success"] is False
        assert "not approved" in result["error"]
    
    def test_history_tracking(self) -> None:
        """Test draft history tracking."""
        flow = EmailDraftFlow()
        
        # Create and reject first draft
        flow.start_draft("E-posta yaz")
        flow.reject_draft()
        
        # Create and approve second draft
        flow.start_draft("E-posta yaz")
        for p in flow.current_draft.placeholders:
            if p.required:
                p.resolve("Test Value")
        flow.approve_draft()
        
        assert len(flow.history) == 2


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_create_email_draft(self) -> None:
        """Test create_email_draft function."""
        draft = create_email_draft("E-posta yaz")
        assert draft is not None
        assert isinstance(draft, EmailDraft)
    
    def test_create_email_draft_with_cloud(self) -> None:
        """Test create_email_draft with cloud."""
        mock_refiner = MagicMock(return_value="Refined")
        draft = create_email_draft("E-posta yaz", use_cloud=True, cloud_refiner=mock_refiner)
        mock_refiner.assert_called_once()
    
    def test_extract_placeholders_from_text(self) -> None:
        """Test extracting placeholders."""
        text = "Sayın [[RECIPIENT_NAME]], [[KONU]] hakkında yazıyorum."
        placeholders = extract_placeholders_from_text(text)
        
        assert "RECIPIENT_NAME" in placeholders
        assert "KONU" in placeholders
    
    def test_extract_placeholders_empty(self) -> None:
        """Test extracting from text without placeholders."""
        text = "Normal metin"
        placeholders = extract_placeholders_from_text(text)
        assert len(placeholders) == 0


# =============================================================================
# Safety Validation Tests
# =============================================================================

class TestValidateDraftSafety:
    """Tests for validate_draft_safety function."""
    
    def test_valid_draft(self) -> None:
        """Test validating a valid draft."""
        draft = EmailDraft(
            subject="Test",
            body="Test body",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME", value="Test"),
            ],
        )
        result = validate_draft_safety(draft)
        assert result["valid"] is True
    
    def test_invalid_draft_unresolved(self) -> None:
        """Test validating draft with unresolved required placeholders."""
        draft = EmailDraft(
            subject="Test",
            body="Test body",
            placeholders=[
                Placeholder(PlaceholderType.RECIPIENT_NAME, "RECIPIENT_NAME", required=True),
            ],
        )
        result = validate_draft_safety(draft)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
    
    def test_pii_warning_email(self) -> None:
        """Test PII warning for email addresses."""
        draft = EmailDraft(
            subject="Test",
            body="İletişim: test@example.com",
            placeholders=[],
        )
        result = validate_draft_safety(draft)
        # Email is warning, not error
        assert len(result["warnings"]) > 0
    
    def test_pii_warning_phone(self) -> None:
        """Test PII warning for phone numbers."""
        draft = EmailDraft(
            subject="Test",
            body="Telefon: 05551234567",
            placeholders=[],
        )
        result = validate_draft_safety(draft)
        assert len(result["warnings"]) > 0


# =============================================================================
# E2E Integration Tests
# =============================================================================

class TestEmailDraftE2E:
    """End-to-end integration tests."""
    
    def test_full_flow_formal_email(self) -> None:
        """Test full flow for formal email."""
        flow = EmailDraftFlow()
        
        # Start draft
        draft = flow.start_draft("Resmi e-posta yaz patrona")
        assert draft.email_type == EmailType.FORMAL
        
        # Fill placeholders
        flow.update_placeholder("RECIPIENT_NAME", "Mehmet Bey")
        flow.update_placeholder("SENDER_NAME", "Ahmet")
        flow.update_placeholder("KONU", "Proje Güncellemesi")
        flow.update_placeholder("ANA_MESAJ", "Proje planlandığı gibi ilerliyor.")
        
        # Get preview
        preview = flow.get_preview()
        assert "Mehmet Bey" in preview
        
        # Approve
        assert flow.approve_draft() is True
        
        # Simulate send
        result = flow.simulate_send()
        assert result["success"] is True
        assert result["simulated"] is True
    
    def test_full_flow_thank_you_email(self) -> None:
        """Test full flow for thank you email."""
        flow = EmailDraftFlow()
        
        # Start draft
        draft = flow.start_draft("Teşekkür e-postası hazırla")
        assert draft.email_type == EmailType.THANK_YOU
        
        # Should have appropriate structure
        assert "teşekkür" in draft.body.lower()
    
    def test_reject_and_restart(self) -> None:
        """Test rejecting and restarting draft."""
        flow = EmailDraftFlow()
        
        # Start and reject first
        flow.start_draft("E-posta yaz")
        flow.reject_draft()
        
        assert flow.current_draft is None
        
        # Start new draft
        draft = flow.start_draft("Yeni e-posta yaz")
        assert draft is not None
    
    def test_no_actual_send(self) -> None:
        """Test that no actual sending happens."""
        flow = EmailDraftFlow()
        flow.start_draft("E-posta yaz")
        
        # Fill and approve
        for p in flow.current_draft.placeholders:
            if p.required:
                p.resolve("Test")
        flow.approve_draft()
        
        # Simulate send
        result = flow.simulate_send()
        
        # Verify it's simulated
        assert result["simulated"] is True
        assert "gerçekte gönderilmedi" in result["message"]
