"""Smart Mail Management — prioritization, auto-reply, digest, tone (Issue #843).

Gmail'i "oku" seviyesinden "akıllı yönetim" seviyesine çıkarır.

Özellikler
──────────
- Mail önceliklendirme: aciliyet × önem × kişi skoru
- Otomatik yanıt önerisi + onay (confirmation firewall)
- Toplu mail özeti (günlük digest)
- Mail gönderme: isimden e-posta çözümleme
- Kişi bazlı ton ayarı (hocaya resmi, arkadaşa informal)
- Takip hatırlatma: "3 gündür yanıt gelmedi"
- Gemini quality tier entegrasyonu
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Priority model ──────────────────────────────────────────────────

class MailPriority(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class ScoredMail:
    """An email with computed priority score."""
    message_id: str
    subject: str
    sender: str
    sender_email: str
    date: str
    snippet: str
    priority: MailPriority = MailPriority.NORMAL
    score: float = 0.0
    labels: List[str] = field(default_factory=list)
    needs_reply: bool = False
    days_without_reply: int = 0
    suggested_tone: str = "neutral"
    raw: Dict[str, Any] = field(default_factory=dict)


# ── Keyword-based urgency heuristics ─────────────────────────────────

_URGENT_KEYWORDS = [
    "acil", "urgent", "asap", "hemen", "immediately", "critical",
    "son tarih", "deadline", "önemli", "important", "dikkat", "attention",
]
_HIGH_KEYWORDS = [
    "toplantı", "meeting", "bugün", "today", "yarın", "tomorrow",
    "onay", "approval", "confirm", "lütfen", "please",
]
_SENDER_VIP_PATTERNS = [
    r"(?i)(prof|dr|doç|hoca|müdür|dean|director|ceo|cto|manager)",
    r"(?i)@(.*\.edu\.tr|.*\.edu|.*\.gov)",
]


def _compute_priority(subject: str, sender: str, labels: List[str]) -> tuple[MailPriority, float]:
    """Compute mail priority from subject + sender + labels."""
    score = 0.0

    text = (subject + " " + sender).lower()

    # Keyword scoring
    for kw in _URGENT_KEYWORDS:
        if kw in text:
            score += 10
    for kw in _HIGH_KEYWORDS:
        if kw in text:
            score += 5

    # VIP sender
    for pattern in _SENDER_VIP_PATTERNS:
        if re.search(pattern, sender):
            score += 8
            break

    # Label scoring
    if "IMPORTANT" in labels:
        score += 7
    if "STARRED" in labels:
        score += 5
    if "CATEGORY_UPDATES" in labels or "CATEGORY_PROMOTIONS" in labels:
        score -= 5

    # Determine tier
    if score >= 18:
        return MailPriority.URGENT, score
    elif score >= 10:
        return MailPriority.HIGH, score
    elif score >= 3:
        return MailPriority.NORMAL, score
    else:
        return MailPriority.LOW, score


# ── Tone detection ──────────────────────────────────────────────────

@dataclass
class ContactTone:
    """Preferred communication tone for a contact."""
    name: str
    email: str
    tone: str  # formal | informal | business | academic
    language: str = "tr"  # tr | en


# Default tone rules
_TONE_RULES = [
    (r"(?i)(prof|dr|doç|hoca)", "academic"),
    (r"(?i)(müdür|dean|director|ceo|manager|hr)", "formal"),
    (r"(?i)@.*\.edu", "academic"),
    (r"(?i)@.*\.gov", "formal"),
    (r"(?i)@(gmail|hotmail|yahoo|outlook)", "informal"),
]

# Contact-specific overrides (loaded from config or memory)
_contact_tones: Dict[str, str] = {}


def set_contact_tone(email: str, tone: str) -> None:
    """Override tone for a specific contact."""
    _contact_tones[email.lower()] = tone


def detect_tone(sender_name: str, sender_email: str) -> str:
    """Detect appropriate reply tone for this sender."""
    # Check overrides first
    override = _contact_tones.get(sender_email.lower())
    if override:
        return override

    combined = f"{sender_name} {sender_email}"
    for pattern, tone in _TONE_RULES:
        if re.search(pattern, combined):
            return tone
    return "neutral"


# ── Auto-reply suggestion ───────────────────────────────────────────

_TONE_TEMPLATES = {
    "formal": {
        "greeting": "Sayın {name},",
        "closing": "Saygılarımla,",
        "style": "Resmi ve profesyonel dil kullanın.",
    },
    "academic": {
        "greeting": "Sayın {name} Hocam,",
        "closing": "Saygılarımla,",
        "style": "Akademik ve saygılı dil kullanın.",
    },
    "informal": {
        "greeting": "Selam {name},",
        "closing": "Görüşürüz!",
        "style": "Samimi ve kısa yazın.",
    },
    "business": {
        "greeting": "Merhaba {name},",
        "closing": "İyi çalışmalar,",
        "style": "Profesyonel ama sıcak bir dil kullanın.",
    },
    "neutral": {
        "greeting": "Merhaba {name},",
        "closing": "İyi günler,",
        "style": "Nötr ve kibar bir dil kullanın.",
    },
}


@dataclass
class ReplyDraft:
    """A suggested reply draft for confirmation firewall."""
    message_id: str
    to: str
    subject: str
    body: str
    tone: str
    confidence: float  # 0-1, how confident the auto-reply is on-topic
    needs_confirmation: bool = True


def suggest_reply(
    message_id: str,
    subject: str,
    body_snippet: str,
    sender_name: str,
    sender_email: str,
    user_intent: str = "",
) -> ReplyDraft:
    """Generate a reply draft suggestion.

    The actual body generation should go through Gemini quality tier;
    this function builds the prompt context and tone metadata.
    """
    tone = detect_tone(sender_name, sender_email)
    tpl = _TONE_TEMPLATES.get(tone, _TONE_TEMPLATES["neutral"])

    first_name = sender_name.split()[0] if sender_name else ""
    greeting = tpl["greeting"].format(name=first_name)
    closing = tpl["closing"]
    style_hint = tpl["style"]

    # Build reply body (placeholder for LLM generation)
    if user_intent:
        reply_body = f"{greeting}\n\n{user_intent}\n\n{closing}"
        confidence = 0.7
    else:
        reply_body = (
            f"{greeting}\n\n"
            f"[Otomatik yanıt önerisi — LLM tarafından üretilecek]\n"
            f"Konu: {subject}\n"
            f"Stil: {style_hint}\n\n"
            f"{closing}"
        )
        confidence = 0.3

    return ReplyDraft(
        message_id=message_id,
        to=sender_email,
        subject=f"Re: {subject}" if not subject.startswith("Re:") else subject,
        body=reply_body,
        tone=tone,
        confidence=confidence,
        needs_confirmation=True,
    )


# ── Follow-up tracking ──────────────────────────────────────────────

def check_followups(days_threshold: int = 3) -> List[Dict[str, Any]]:
    """Check for emails sent by us that haven't received a reply.

    Returns a list of follow-up suggestions.
    """
    followups: List[Dict[str, Any]] = []
    try:
        from bantz.google.gmail import gmail_list_messages
        result = gmail_list_messages(max_results=20, label="SENT")
        if not result.get("ok"):
            return followups

        cutoff = datetime.now() - timedelta(days=days_threshold)
        for msg in result.get("messages", []):
            msg_date = msg.get("date", "")
            if not msg_date:
                continue
            # Simple heuristic: if sent > threshold days ago, suggest follow-up
            try:
                from email.utils import parsedate_to_datetime
                sent_dt = parsedate_to_datetime(msg_date)
                if sent_dt.replace(tzinfo=None) < cutoff:
                    followups.append({
                        "message_id": msg.get("id", ""),
                        "subject": msg.get("subject", ""),
                        "to": msg.get("to", ""),
                        "sent_date": msg_date,
                        "days_ago": (datetime.now() - sent_dt.replace(tzinfo=None)).days,
                        "suggestion": f"'{msg.get('subject', '')}' konulu maile {(datetime.now() - sent_dt.replace(tzinfo=None)).days} gündür yanıt gelmedi. Takip maili gönderilsin mi?",
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"[SmartMail] follow-up check failed: {e}")
    return followups


# ── Daily digest ─────────────────────────────────────────────────────

def generate_digest(max_mails: int = 20) -> Dict[str, Any]:
    """Generate a daily email digest.

    Groups emails by priority, provides summary stats,
    and suggests top actions.
    """
    scored: List[ScoredMail] = []
    try:
        from bantz.google.gmail import gmail_list_messages
        result = gmail_list_messages(max_results=max_mails, label="UNREAD")
        if not result.get("ok"):
            return {"ok": False, "error": "Gmail erişimi başarısız"}

        for msg in result.get("messages", []):
            sender = msg.get("from", "")
            sender_email = ""
            # Extract email from "Name <email>" format
            email_match = re.search(r"<(.+?)>", sender)
            if email_match:
                sender_email = email_match.group(1)
            else:
                sender_email = sender

            labels = msg.get("labelIds", [])
            priority, score = _compute_priority(
                msg.get("subject", ""),
                sender,
                labels,
            )
            tone = detect_tone(sender, sender_email)

            scored.append(ScoredMail(
                message_id=msg.get("id", ""),
                subject=msg.get("subject", "Konu yok"),
                sender=sender,
                sender_email=sender_email,
                date=msg.get("date", ""),
                snippet=msg.get("snippet", ""),
                priority=priority,
                score=score,
                labels=labels,
                suggested_tone=tone,
                raw=msg,
            ))
    except Exception as e:
        logger.warning(f"[SmartMail] digest collection failed: {e}")
        return {"ok": False, "error": str(e)}

    # Sort by score descending
    scored.sort(key=lambda m: m.score, reverse=True)

    # Group by priority
    groups: Dict[str, List[Dict[str, Any]]] = {
        "urgent": [],
        "high": [],
        "normal": [],
        "low": [],
    }
    for mail in scored:
        group_name = mail.priority.name.lower()
        groups.get(group_name, groups["normal"]).append({
            "id": mail.message_id,
            "subject": mail.subject,
            "from": mail.sender,
            "score": round(mail.score, 1),
            "tone": mail.suggested_tone,
            "snippet": mail.snippet[:100],
        })

    # Follow-ups
    followups = check_followups()

    return {
        "ok": True,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_unread": len(scored),
        "by_priority": {k: len(v) for k, v in groups.items()},
        "urgent": groups["urgent"],
        "high": groups["high"],
        "normal": groups["normal"][:5],
        "low_count": len(groups["low"]),
        "followups": followups[:5],
        "top_actions": _suggest_actions(scored[:5]),
    }


def _suggest_actions(top_mails: List[ScoredMail]) -> List[Dict[str, str]]:
    """Suggest quick actions for top priority mails."""
    actions = []
    for mail in top_mails:
        action = {
            "mail_id": mail.message_id,
            "subject": mail.subject,
        }
        if mail.priority >= MailPriority.HIGH:
            action["action"] = "Hemen yanıtla"
            action["tone"] = mail.suggested_tone
        elif "meeting" in mail.subject.lower() or "toplantı" in mail.subject.lower():
            action["action"] = "Takvimi kontrol et ve yanıtla"
        else:
            action["action"] = "Oku ve değerlendir"
        actions.append(action)
    return actions


# ── Contact resolution ──────────────────────────────────────────────

def resolve_contact_email(name: str) -> Optional[str]:
    """Resolve a contact name to email using contacts store."""
    try:
        from bantz.contacts.store import contacts_resolve
        return contacts_resolve(name)
    except Exception:
        return None


# ── Tool registration ────────────────────────────────────────────────

def register_smart_mail_tools(registry: Any) -> None:
    """Register smart mail tools with ToolRegistry."""
    from bantz.agent.tools import Tool

    registry.register(Tool(
        name="mail.prioritize",
        description="Get prioritized unread email list with urgency scores.",
        parameters={
            "type": "object",
            "properties": {
                "max_mails": {"type": "integer", "description": "Max emails to analyze (default 20)"},
            },
        },
        function=lambda **kw: generate_digest(max_mails=kw.get("max_mails", 20)),
    ))

    registry.register(Tool(
        name="mail.suggest_reply",
        description="Generate a reply draft with appropriate tone for a contact.",
        parameters={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID"},
                "subject": {"type": "string", "description": "Email subject"},
                "body_snippet": {"type": "string", "description": "Email body preview"},
                "sender_name": {"type": "string", "description": "Sender name"},
                "sender_email": {"type": "string", "description": "Sender email"},
                "user_intent": {"type": "string", "description": "What user wants to say"},
            },
            "required": ["message_id", "sender_email"],
        },
        function=lambda **kw: {
            "ok": True,
            **(lambda d: {
                "to": d.to, "subject": d.subject, "body": d.body,
                "tone": d.tone, "confidence": d.confidence,
                "needs_confirmation": d.needs_confirmation,
            })(suggest_reply(
                message_id=kw.get("message_id", ""),
                subject=kw.get("subject", ""),
                body_snippet=kw.get("body_snippet", ""),
                sender_name=kw.get("sender_name", ""),
                sender_email=kw.get("sender_email", ""),
                user_intent=kw.get("user_intent", ""),
            )),
        },
        risk_level="medium",
        requires_confirmation=True,
    ))

    registry.register(Tool(
        name="mail.check_followups",
        description="Check for sent emails without reply (follow-up needed).",
        parameters={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days threshold (default 3)"},
            },
        },
        function=lambda **kw: {
            "ok": True,
            "followups": check_followups(days_threshold=kw.get("days", 3)),
        },
    ))

    registry.register(Tool(
        name="mail.set_tone",
        description="Set preferred communication tone for a contact.",
        parameters={
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Contact email"},
                "tone": {"type": "string", "enum": ["formal", "informal", "academic", "business", "neutral"],
                         "description": "Preferred tone"},
            },
            "required": ["email", "tone"],
        },
        function=lambda **kw: (
            set_contact_tone(kw.get("email", ""), kw.get("tone", "neutral")),
            {"ok": True, "email": kw.get("email"), "tone": kw.get("tone")},
        )[1],
    ))

    logger.info("[SmartMail] 4 smart mail tools registered")
