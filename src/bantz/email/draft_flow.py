"""Email Draft Flow with Safe Placeholders.

Issue #246: Email draft flow with local intent + Gemini quality.

This module provides:
- Email draft generation with placeholder safety
- Local intent detection for email requests
- Gemini quality tier for final drafting
- No actual send - draft only mode

Key Features:
- Safe placeholders for PII (names, emails, dates)
- Draft review before any action
- Quality generation via cloud (Gemini)
- Turkish and English support
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


# =============================================================================
# Enums
# =============================================================================

class EmailType(Enum):
    """Type of email being drafted."""
    FORMAL = "formal"           # Resmi yazışma
    INFORMAL = "informal"       # Samimi yazışma
    BUSINESS = "business"       # İş yazışması
    FOLLOW_UP = "follow_up"     # Takip e-postası
    REPLY = "reply"             # Yanıt
    INTRODUCTION = "introduction"  # Tanışma
    REQUEST = "request"         # İstek/talep
    THANK_YOU = "thank_you"     # Teşekkür
    APOLOGY = "apology"         # Özür
    ANNOUNCEMENT = "announcement"  # Duyuru


class PlaceholderType(Enum):
    """Type of placeholder in email draft."""
    RECIPIENT_NAME = "recipient_name"
    RECIPIENT_EMAIL = "recipient_email"
    SENDER_NAME = "sender_name"
    COMPANY_NAME = "company_name"
    DATE = "date"
    TIME = "time"
    MEETING_LINK = "meeting_link"
    PHONE_NUMBER = "phone_number"
    ADDRESS = "address"
    AMOUNT = "amount"
    CUSTOM = "custom"
    
    @property
    def pattern(self) -> str:
        """Get the placeholder pattern."""
        return f"[[{self.value.upper()}]]"
    
    @property
    def description_tr(self) -> str:
        """Turkish description."""
        descriptions = {
            PlaceholderType.RECIPIENT_NAME: "Alıcı adı",
            PlaceholderType.RECIPIENT_EMAIL: "Alıcı e-posta",
            PlaceholderType.SENDER_NAME: "Gönderen adı",
            PlaceholderType.COMPANY_NAME: "Şirket adı",
            PlaceholderType.DATE: "Tarih",
            PlaceholderType.TIME: "Saat",
            PlaceholderType.MEETING_LINK: "Toplantı linki",
            PlaceholderType.PHONE_NUMBER: "Telefon numarası",
            PlaceholderType.ADDRESS: "Adres",
            PlaceholderType.AMOUNT: "Tutar",
            PlaceholderType.CUSTOM: "Özel alan",
        }
        return descriptions.get(self, "Bilinmeyen")


class DraftStatus(Enum):
    """Status of email draft."""
    DRAFT = "draft"             # İlk taslak
    REVIEW = "review"           # İnceleme aşamasında
    APPROVED = "approved"       # Onaylandı
    REJECTED = "rejected"       # Reddedildi
    SENT = "sent"               # Gönderildi (sadece simülasyon)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Placeholder:
    """A placeholder in the email draft.
    
    Attributes:
        type: Type of placeholder.
        key: Unique key for this placeholder.
        value: Resolved value (None if not resolved).
        required: Whether this placeholder must be filled.
    """
    type: PlaceholderType
    key: str
    value: Optional[str] = None
    required: bool = True
    
    @property
    def pattern(self) -> str:
        """Get the pattern for this placeholder."""
        return f"[[{self.key.upper()}]]"
    
    @property
    def is_resolved(self) -> bool:
        """Check if placeholder is resolved."""
        return self.value is not None
    
    def resolve(self, value: str) -> None:
        """Resolve the placeholder with a value."""
        self.value = value


@dataclass
class EmailDraft:
    """Email draft with safe placeholders.
    
    Attributes:
        subject: Email subject line.
        body: Email body with placeholders.
        email_type: Type of email.
        placeholders: List of placeholders in the draft.
        status: Current draft status.
        language: Draft language (tr/en).
    """
    subject: str
    body: str
    email_type: EmailType = EmailType.FORMAL
    placeholders: list[Placeholder] = field(default_factory=list)
    status: DraftStatus = DraftStatus.DRAFT
    language: str = "tr"
    created_at: datetime = field(default_factory=datetime.now)
    
    # Metadata
    original_request: str = ""
    generation_tier: str = "local"  # local or cloud
    
    def get_unresolved_placeholders(self) -> list[Placeholder]:
        """Get list of unresolved placeholders."""
        return [p for p in self.placeholders if not p.is_resolved]
    
    def has_unresolved(self) -> bool:
        """Check if there are unresolved placeholders."""
        return len(self.get_unresolved_placeholders()) > 0
    
    def has_required_unresolved(self) -> bool:
        """Check if there are required unresolved placeholders."""
        return any(p.required for p in self.get_unresolved_placeholders())
    
    def resolve_placeholder(self, key: str, value: str) -> bool:
        """Resolve a placeholder by key.
        
        Args:
            key: Placeholder key.
            value: Value to set.
        
        Returns:
            True if placeholder was found and resolved.
        """
        for p in self.placeholders:
            if p.key.upper() == key.upper():
                p.resolve(value)
                return True
        return False
    
    def get_resolved_body(self) -> str:
        """Get body with resolved placeholders."""
        result = self.body
        for p in self.placeholders:
            if p.is_resolved:
                result = result.replace(p.pattern, p.value or "")
        return result
    
    def get_resolved_subject(self) -> str:
        """Get subject with resolved placeholders."""
        result = self.subject
        for p in self.placeholders:
            if p.is_resolved:
                result = result.replace(p.pattern, p.value or "")
        return result
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "subject": self.subject,
            "body": self.body,
            "email_type": self.email_type.value,
            "placeholders": [
                {
                    "type": p.type.value,
                    "key": p.key,
                    "value": p.value,
                    "required": p.required,
                }
                for p in self.placeholders
            ],
            "status": self.status.value,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
            "original_request": self.original_request,
            "generation_tier": self.generation_tier,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmailDraft:
        """Create from dictionary."""
        placeholders = [
            Placeholder(
                type=PlaceholderType(p["type"]),
                key=p["key"],
                value=p.get("value"),
                required=p.get("required", True),
            )
            for p in data.get("placeholders", [])
        ]
        
        return cls(
            subject=data["subject"],
            body=data["body"],
            email_type=EmailType(data.get("email_type", "formal")),
            placeholders=placeholders,
            status=DraftStatus(data.get("status", "draft")),
            language=data.get("language", "tr"),
            original_request=data.get("original_request", ""),
            generation_tier=data.get("generation_tier", "local"),
        )
    
    def format_preview(self) -> str:
        """Format draft for preview."""
        lines = [
            "=" * 50,
            "E-POSTA TASLAĞI",
            "=" * 50,
            f"Durum: {self.status.value}",
            f"Tip: {self.email_type.value}",
            "-" * 50,
            f"Konu: {self.subject}",
            "-" * 50,
            self.body,
            "-" * 50,
        ]
        
        if self.placeholders:
            lines.append("Doldurulması gereken alanlar:")
            for p in self.placeholders:
                status = "✓" if p.is_resolved else "○"
                value_str = f" = {p.value}" if p.is_resolved else ""
                lines.append(f"  {status} {p.pattern}: {p.type.description_tr}{value_str}")
        
        lines.append("=" * 50)
        return "\n".join(lines)


# =============================================================================
# Intent Detection
# =============================================================================

@dataclass
class EmailIntent:
    """Detected email intent from user request.
    
    Attributes:
        detected: Whether email intent was detected.
        email_type: Detected email type.
        recipient_hint: Hint about recipient from request.
        subject_hint: Hint about subject from request.
        body_hints: Key points for body from request.
        urgency: Detected urgency level (0-1).
        language: Detected language preference.
    """
    detected: bool
    email_type: EmailType = EmailType.FORMAL
    recipient_hint: str = ""
    subject_hint: str = ""
    body_hints: list[str] = field(default_factory=list)
    urgency: float = 0.5
    language: str = "tr"
    confidence: float = 0.0
    
    @classmethod
    def no_match(cls) -> EmailIntent:
        """Create a no-match intent."""
        return cls(detected=False)


def detect_email_intent(text: str) -> EmailIntent:
    """Detect email drafting intent from user text.
    
    Args:
        text: User's request text.
    
    Returns:
        Detected email intent.
    """
    text_lower = text.lower()
    
    # Check for email keywords
    email_keywords = [
        "e-posta", "eposta", "email", "mail", "mektup",
        "yaz", "hazırla", "taslak", "draft",
    ]
    
    has_email_keyword = any(kw in text_lower for kw in email_keywords)
    
    if not has_email_keyword:
        return EmailIntent.no_match()
    
    # Detect email type
    email_type = EmailType.FORMAL
    confidence = 0.7
    
    formal_keywords = ["resmi", "formal", "profesyonel"]
    informal_keywords = ["samimi", "arkadaşça", "informal"]
    business_keywords = ["iş", "business", "ticari", "teklif"]
    followup_keywords = ["takip", "hatırlatma", "follow up"]
    reply_keywords = ["yanıt", "cevap", "reply"]
    thank_keywords = ["teşekkür", "thanks", "thank you"]
    request_keywords = ["rica", "talep", "istek", "request"]
    apology_keywords = ["özür", "sorry", "apology"]
    
    if any(kw in text_lower for kw in formal_keywords):
        email_type = EmailType.FORMAL
        confidence = 0.9
    elif any(kw in text_lower for kw in informal_keywords):
        email_type = EmailType.INFORMAL
        confidence = 0.9
    elif any(kw in text_lower for kw in business_keywords):
        email_type = EmailType.BUSINESS
        confidence = 0.85
    elif any(kw in text_lower for kw in followup_keywords):
        email_type = EmailType.FOLLOW_UP
        confidence = 0.85
    elif any(kw in text_lower for kw in reply_keywords):
        email_type = EmailType.REPLY
        confidence = 0.85
    elif any(kw in text_lower for kw in thank_keywords):
        email_type = EmailType.THANK_YOU
        confidence = 0.9
    elif any(kw in text_lower for kw in request_keywords):
        email_type = EmailType.REQUEST
        confidence = 0.85
    elif any(kw in text_lower for kw in apology_keywords):
        email_type = EmailType.APOLOGY
        confidence = 0.9
    
    # Extract hints
    recipient_hint = ""
    # Look for "... için" or "... ye/ya"
    recipient_patterns = [
        r"(\w+(?:\s+\w+)?)\s+(?:için|ye|ya|e)\s+(?:e-?posta|mail)",
        r"(?:e-?posta|mail)\s+(?:yaz|gönder)\s+(\w+(?:\s+\w+)?)",
    ]
    
    for pattern in recipient_patterns:
        m = re.search(pattern, text_lower)
        if m:
            recipient_hint = m.group(1).strip()
            break
    
    # Extract subject hint
    subject_hint = ""
    subject_patterns = [
        r"hakkında\s+(.+?)(?:\s+e-?posta|\s+mail|\s+yaz|$)",
        r"konu(?:su)?\s*[:=]?\s*(.+?)(?:\s+e-?posta|\s+mail|\s+yaz|$)",
    ]
    
    for pattern in subject_patterns:
        m = re.search(pattern, text_lower)
        if m:
            subject_hint = m.group(1).strip()
            break
    
    # Detect urgency
    urgency = 0.5
    urgent_keywords = ["acil", "hemen", "urgent", "asap", "önemli"]
    if any(kw in text_lower for kw in urgent_keywords):
        urgency = 0.9
    
    # Detect language
    # Note: Turkish 'İ' lowercases to 'i̇' (i with combining dot), not 'i'
    language = "tr"
    english_keywords = ["english", "ingilizce", "i̇ngilizce"]  # Include Turkish lowercase
    if any(kw in text_lower for kw in english_keywords):
        language = "en"
    
    return EmailIntent(
        detected=True,
        email_type=email_type,
        recipient_hint=recipient_hint,
        subject_hint=subject_hint,
        body_hints=[text],  # Full text as context
        urgency=urgency,
        language=language,
        confidence=confidence,
    )


# =============================================================================
# Draft Generator
# =============================================================================

class EmailDraftGenerator:
    """Generator for email drafts with placeholders.
    
    Uses local templates for initial draft, then optionally
    refines with cloud (Gemini) for quality.
    """
    
    def __init__(
        self,
        cloud_refiner: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        """Initialize generator.
        
        Args:
            cloud_refiner: Optional function for cloud refinement.
                Takes (draft_text, context) and returns refined text.
        """
        self.cloud_refiner = cloud_refiner
    
    def generate_draft(
        self,
        intent: EmailIntent,
        use_cloud: bool = False,
    ) -> EmailDraft:
        """Generate email draft from intent.
        
        Args:
            intent: Detected email intent.
            use_cloud: Whether to use cloud for quality refinement.
        
        Returns:
            Generated email draft.
        """
        # Get template based on type
        template = self._get_template(intent.email_type, intent.language)
        
        # Create placeholders
        placeholders = self._create_placeholders(intent)
        
        # Apply hints to template
        subject, body = self._apply_hints(template, intent)
        
        # Cloud refinement if requested
        generation_tier = "local"
        if use_cloud and self.cloud_refiner:
            context = f"Type: {intent.email_type.value}, Hints: {intent.body_hints}"
            body = self.cloud_refiner(body, context)
            generation_tier = "cloud"
        
        return EmailDraft(
            subject=subject,
            body=body,
            email_type=intent.email_type,
            placeholders=placeholders,
            status=DraftStatus.DRAFT,
            language=intent.language,
            original_request=" ".join(intent.body_hints),
            generation_tier=generation_tier,
        )
    
    def _get_template(self, email_type: EmailType, language: str) -> dict[str, str]:
        """Get template for email type."""
        templates_tr = {
            EmailType.FORMAL: {
                "subject": "[[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[ANA_MESAJ]]

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.INFORMAL: {
                "subject": "[[KONU]]",
                "body": """Merhaba [[RECIPIENT_NAME]],

[[ANA_MESAJ]]

Sevgiler,
[[SENDER_NAME]]""",
            },
            EmailType.BUSINESS: {
                "subject": "[[KONU]] - İş Teklifi",
                "body": """Sayın [[RECIPIENT_NAME]],

[[COMPANY_NAME]] adına sizinle iletişime geçiyorum.

[[ANA_MESAJ]]

Detayları görüşmek için müsait olduğunuz bir zamanda toplantı ayarlayabiliriz.

Saygılarımla,
[[SENDER_NAME]]
[[COMPANY_NAME]]""",
            },
            EmailType.FOLLOW_UP: {
                "subject": "Takip: [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[DATE]] tarihli görüşmemizle ilgili takip etmek istiyorum.

[[ANA_MESAJ]]

Geri dönüşünüzü bekliyorum.

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.REPLY: {
                "subject": "Re: [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

E-postanız için teşekkür ederim.

[[ANA_MESAJ]]

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.THANK_YOU: {
                "subject": "Teşekkürler - [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[ANA_MESAJ]] için teşekkür etmek istiyorum.

Bu deneyim benim için çok değerliydi.

Tekrar teşekkür eder, saygılarımı sunarım.
[[SENDER_NAME]]""",
            },
            EmailType.REQUEST: {
                "subject": "Talep: [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[ANA_MESAJ]]

Bu konuda yardımcı olabilirseniz çok memnun olurum.

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.APOLOGY: {
                "subject": "Özür - [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[ANA_MESAJ]] konusunda özür dilemek istiyorum.

Bu durumun tekrarlanmaması için gerekli önlemleri alacağım.

Anlayışınız için teşekkür ederim.

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.ANNOUNCEMENT: {
                "subject": "Duyuru: [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

[[ANA_MESAJ]]

Detaylı bilgi için bizimle iletişime geçebilirsiniz.

Saygılarımla,
[[SENDER_NAME]]""",
            },
            EmailType.INTRODUCTION: {
                "subject": "Tanışma - [[KONU]]",
                "body": """Sayın [[RECIPIENT_NAME]],

Kendimi tanıtmak istiyorum. Ben [[SENDER_NAME]].

[[ANA_MESAJ]]

Tanışmak için sabırsızlanıyorum.

Saygılarımla,
[[SENDER_NAME]]""",
            },
        }
        
        templates_en = {
            EmailType.FORMAL: {
                "subject": "[[SUBJECT]]",
                "body": """Dear [[RECIPIENT_NAME]],

[[MAIN_MESSAGE]]

Best regards,
[[SENDER_NAME]]""",
            },
            EmailType.INFORMAL: {
                "subject": "[[SUBJECT]]",
                "body": """Hi [[RECIPIENT_NAME]],

[[MAIN_MESSAGE]]

Cheers,
[[SENDER_NAME]]""",
            },
            EmailType.BUSINESS: {
                "subject": "[[SUBJECT]] - Business Proposal",
                "body": """Dear [[RECIPIENT_NAME]],

I am reaching out on behalf of [[COMPANY_NAME]].

[[MAIN_MESSAGE]]

I would be happy to schedule a call to discuss further.

Best regards,
[[SENDER_NAME]]
[[COMPANY_NAME]]""",
            },
            # Add more English templates as needed
        }
        
        if language == "en":
            return templates_en.get(email_type, templates_en[EmailType.FORMAL])
        return templates_tr.get(email_type, templates_tr[EmailType.FORMAL])
    
    def _create_placeholders(self, intent: EmailIntent) -> list[Placeholder]:
        """Create placeholders based on intent."""
        placeholders = [
            Placeholder(
                type=PlaceholderType.RECIPIENT_NAME,
                key="RECIPIENT_NAME",
                value=intent.recipient_hint if intent.recipient_hint else None,
                required=True,
            ),
            Placeholder(
                type=PlaceholderType.SENDER_NAME,
                key="SENDER_NAME",
                required=True,
            ),
        ]
        
        # Add subject placeholder
        subject_key = "KONU" if intent.language == "tr" else "SUBJECT"
        placeholders.append(Placeholder(
            type=PlaceholderType.CUSTOM,
            key=subject_key,
            value=intent.subject_hint if intent.subject_hint else None,
            required=True,
        ))
        
        # Add main message placeholder
        message_key = "ANA_MESAJ" if intent.language == "tr" else "MAIN_MESSAGE"
        placeholders.append(Placeholder(
            type=PlaceholderType.CUSTOM,
            key=message_key,
            required=True,
        ))
        
        # Add company for business type
        if intent.email_type == EmailType.BUSINESS:
            placeholders.append(Placeholder(
                type=PlaceholderType.COMPANY_NAME,
                key="COMPANY_NAME",
                required=True,
            ))
        
        # Add date for follow-up type
        if intent.email_type == EmailType.FOLLOW_UP:
            placeholders.append(Placeholder(
                type=PlaceholderType.DATE,
                key="DATE",
                required=True,
            ))
        
        return placeholders
    
    def _apply_hints(
        self,
        template: dict[str, str],
        intent: EmailIntent,
    ) -> tuple[str, str]:
        """Apply hints to template."""
        subject = template["subject"]
        body = template["body"]
        
        # Apply subject hint
        if intent.subject_hint:
            subject_key = "KONU" if intent.language == "tr" else "SUBJECT"
            subject = subject.replace(f"[[{subject_key}]]", intent.subject_hint)
        
        # Apply recipient hint
        if intent.recipient_hint:
            body = body.replace("[[RECIPIENT_NAME]]", intent.recipient_hint)
        
        return subject, body


# =============================================================================
# Draft Flow Controller
# =============================================================================

class EmailDraftFlow:
    """Controller for the email draft flow.
    
    Manages the lifecycle of an email draft from request to completion.
    No actual sending - draft only mode.
    """
    
    def __init__(
        self,
        generator: Optional[EmailDraftGenerator] = None,
    ) -> None:
        """Initialize flow controller.
        
        Args:
            generator: Draft generator (creates default if None).
        """
        self.generator = generator or EmailDraftGenerator()
        self._current_draft: Optional[EmailDraft] = None
        self._history: list[EmailDraft] = []
    
    @property
    def current_draft(self) -> Optional[EmailDraft]:
        """Get current draft."""
        return self._current_draft
    
    @property
    def history(self) -> list[EmailDraft]:
        """Get draft history."""
        return list(self._history)
    
    def start_draft(
        self,
        request: str,
        use_cloud: bool = False,
    ) -> EmailDraft:
        """Start a new email draft from request.
        
        Args:
            request: User's request text.
            use_cloud: Whether to use cloud for quality.
        
        Returns:
            Generated draft.
        """
        # Detect intent
        intent = detect_email_intent(request)
        
        if not intent.detected:
            # Create minimal draft for unrecognized requests
            intent = EmailIntent(
                detected=True,
                email_type=EmailType.FORMAL,
                body_hints=[request],
                language="tr",
                confidence=0.5,
            )
        
        # Generate draft
        draft = self.generator.generate_draft(intent, use_cloud=use_cloud)
        
        self._current_draft = draft
        return draft
    
    def update_placeholder(self, key: str, value: str) -> bool:
        """Update a placeholder in the current draft.
        
        Args:
            key: Placeholder key.
            value: Value to set.
        
        Returns:
            True if placeholder was updated.
        """
        if not self._current_draft:
            return False
        
        return self._current_draft.resolve_placeholder(key, value)
    
    def approve_draft(self) -> bool:
        """Approve the current draft.
        
        Returns:
            True if draft was approved.
        """
        if not self._current_draft:
            return False
        
        if self._current_draft.has_required_unresolved():
            return False
        
        self._current_draft.status = DraftStatus.APPROVED
        self._history.append(self._current_draft)
        return True
    
    def reject_draft(self) -> bool:
        """Reject the current draft.
        
        Returns:
            True if draft was rejected.
        """
        if not self._current_draft:
            return False
        
        self._current_draft.status = DraftStatus.REJECTED
        self._history.append(self._current_draft)
        self._current_draft = None
        return True
    
    def get_preview(self) -> str:
        """Get preview of current draft.
        
        Returns:
            Formatted preview string.
        """
        if not self._current_draft:
            return "Aktif taslak yok."
        
        return self._current_draft.format_preview()
    
    def get_resolved_email(self) -> Optional[dict[str, str]]:
        """Get fully resolved email content.
        
        Returns:
            Dict with subject and body, or None if not ready.
        """
        if not self._current_draft:
            return None
        
        if self._current_draft.has_required_unresolved():
            return None
        
        return {
            "subject": self._current_draft.get_resolved_subject(),
            "body": self._current_draft.get_resolved_body(),
        }
    
    def simulate_send(self) -> dict[str, Any]:
        """Simulate sending the email (no actual send).
        
        Returns:
            Simulation result with draft details.
        """
        if not self._current_draft:
            return {"success": False, "error": "No active draft"}
        
        if self._current_draft.status != DraftStatus.APPROVED:
            return {"success": False, "error": "Draft not approved"}
        
        # Mark as "sent" (simulated)
        self._current_draft.status = DraftStatus.SENT
        
        result = {
            "success": True,
            "simulated": True,
            "message": "E-posta simüle edildi (gerçekte gönderilmedi)",
            "draft": self._current_draft.to_dict(),
        }
        
        self._current_draft = None
        return result


# =============================================================================
# Convenience Functions
# =============================================================================

def create_email_draft(
    request: str,
    use_cloud: bool = False,
    cloud_refiner: Optional[Callable[[str, str], str]] = None,
) -> EmailDraft:
    """Convenience function to create an email draft.
    
    Args:
        request: User's request text.
        use_cloud: Whether to use cloud for quality.
        cloud_refiner: Optional cloud refiner function.
    
    Returns:
        Generated email draft.
    """
    generator = EmailDraftGenerator(cloud_refiner=cloud_refiner)
    intent = detect_email_intent(request)
    
    if not intent.detected:
        intent = EmailIntent(
            detected=True,
            email_type=EmailType.FORMAL,
            body_hints=[request],
            language="tr",
            confidence=0.5,
        )
    
    return generator.generate_draft(intent, use_cloud=use_cloud)


def extract_placeholders_from_text(text: str) -> list[str]:
    """Extract placeholder patterns from text.
    
    Args:
        text: Text containing placeholders.
    
    Returns:
        List of placeholder patterns found.
    """
    pattern = r"\[\[([A-Z_]+)\]\]"
    matches = re.findall(pattern, text)
    return list(set(matches))


def validate_draft_safety(draft: EmailDraft) -> dict[str, Any]:
    """Validate draft for safety before any action.
    
    Args:
        draft: Email draft to validate.
    
    Returns:
        Validation result with any issues.
    """
    issues: list[str] = []
    
    # Check for unresolved required placeholders
    unresolved = draft.get_unresolved_placeholders()
    required_unresolved = [p for p in unresolved if p.required]
    
    if required_unresolved:
        for p in required_unresolved:
            issues.append(f"Zorunlu alan doldurulmamış: {p.pattern}")
    
    # Check for PII patterns in resolved content
    pii_patterns = [
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "E-posta adresi tespit edildi"),
        (r"\b\d{10,11}\b", "Telefon numarası tespit edildi"),
        (r"\b\d{11}\b", "TC kimlik numarası olabilir"),
    ]
    
    resolved_body = draft.get_resolved_body()
    for pattern, message in pii_patterns:
        if re.search(pattern, resolved_body):
            issues.append(f"Uyarı: {message}")
    
    return {
        "valid": len([i for i in issues if not i.startswith("Uyarı")]) == 0,
        "issues": issues,
        "warnings": [i for i in issues if i.startswith("Uyarı")],
        "errors": [i for i in issues if not i.startswith("Uyarı")],
    }
