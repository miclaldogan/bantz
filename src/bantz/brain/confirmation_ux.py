"""Write-Confirmation UX v2 (Issue #230).

This module provides:
1. Preview normalization (standardize title, quotes, dots)
2. Edit path (single-question updates)
3. Idempotency key (prevent duplicate operations)

Goal: Clean, predictable confirmation UX for write operations.
"""

from __future__ import annotations

import hashlib
import re
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class PreviewNormalization:
    """Normalize and format event/action preview for confirmation."""
    
    # Max title length before truncation
    MAX_TITLE_LENGTH: int = 50
    
    @classmethod
    def normalize_title(cls, title: str) -> str:
        """Normalize event/action title.
        
        - Strip whitespace
        - Capitalize first letter
        - Remove excessive punctuation
        - Truncate if too long
        
        Args:
            title: Raw title string
            
        Returns:
            Normalized title string
        """
        if not title:
            return ""
        
        t = str(title).strip()
        
        # Remove leading/trailing quotes
        t = t.strip("\"'""''")
        
        # Remove excessive punctuation at end
        t = re.sub(r'[.!?]+$', '', t).strip()
        
        # Capitalize first letter (preserve rest)
        if t:
            t = t[0].upper() + t[1:] if len(t) > 1 else t.upper()
        
        # Truncate if too long
        if len(t) > cls.MAX_TITLE_LENGTH:
            t = t[:cls.MAX_TITLE_LENGTH - 3] + "..."
        
        return t
    
    @classmethod
    def format_time(cls, time_str: str) -> str:
        """Format time string for display.
        
        Converts various formats to HH:MM.
        
        Args:
            time_str: Time string like "14:00", "2:00 PM", etc.
            
        Returns:
            Formatted time string
        """
        if not time_str:
            return ""
        
        t = str(time_str).strip()
        
        # Already in HH:MM format
        if re.match(r'^\d{1,2}:\d{2}$', t):
            # Pad hour if needed
            parts = t.split(':')
            return f"{int(parts[0]):02d}:{parts[1]}"
        
        # Handle "2:00 PM" format
        match = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$', t)
        if match:
            hour = int(match.group(1))
            minute = match.group(2)
            period = match.group(3).upper()
            
            if period == "PM" and hour < 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0
            
            return f"{hour:02d}:{minute}"
        
        return t
    
    @classmethod
    def format_date(cls, date_str: str) -> str:
        """Format date string for Turkish display.
        
        Converts YYYY-MM-DD to more readable format.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            Formatted date string for display
        """
        if not date_str:
            return ""
        
        d = str(date_str).strip()
        
        # Parse YYYY-MM-DD
        match = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', d)
        if match:
            year = match.group(1)
            month = match.group(2)
            day = match.group(3)
            
            # Check if it's today/tomorrow
            try:
                target = datetime(int(year), int(month), int(day)).date()
                today = datetime.now().date()
                
                if target == today:
                    return "Bugün"
                elif target == today.replace(day=today.day + 1) if today.day < 28 else target:
                    from datetime import timedelta
                    if target == today + timedelta(days=1):
                        return "Yarın"
            except Exception:
                pass
            
            # Turkish month names
            months = [
                "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
            ]
            month_idx = int(month)
            if 1 <= month_idx <= 12:
                return f"{int(day)} {months[month_idx]}"
        
        return d
    
    @classmethod
    def format_duration(cls, duration_minutes: Optional[int]) -> str:
        """Format duration in minutes to readable string.
        
        Args:
            duration_minutes: Duration in minutes
            
        Returns:
            Formatted string like "1 saat" or "30 dakika"
        """
        if not duration_minutes:
            return ""
        
        try:
            minutes = int(duration_minutes)
        except (TypeError, ValueError):
            return str(duration_minutes)
        
        if minutes < 60:
            return f"{minutes} dakika"
        
        hours = minutes // 60
        remaining_mins = minutes % 60
        
        if remaining_mins == 0:
            return f"{hours} saat"
        elif remaining_mins == 30:
            return f"{hours} buçuk saat"
        else:
            return f"{hours} saat {remaining_mins} dakika"


@dataclass
class ConfirmationPreview:
    """Generate standardized confirmation preview."""
    
    action_type: str  # create, update, delete, send
    target: str  # calendar, gmail
    title: str
    time: Optional[str] = None
    date: Optional[str] = None
    duration: Optional[int] = None
    recipient: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
    
    def to_turkish(self) -> str:
        """Generate Turkish confirmation prompt.
        
        Returns:
            Turkish confirmation prompt string
        """
        norm = PreviewNormalization
        title = norm.normalize_title(self.title)
        
        if self.target == "calendar":
            return self._calendar_prompt(title, norm)
        elif self.target == "gmail":
            return self._gmail_prompt(title, norm)
        else:
            return f"'{title}' işlemi yapılsın mı?"
    
    def _calendar_prompt(self, title: str, norm: type) -> str:
        """Generate calendar-specific prompt."""
        time_str = norm.format_time(self.time) if self.time else ""
        date_str = norm.format_date(self.date) if self.date else ""
        duration_str = norm.format_duration(self.duration) if self.duration else ""
        
        if self.action_type == "create":
            parts = []
            if date_str:
                parts.append(date_str)
            if time_str:
                parts.append(time_str)
            
            time_info = " ".join(parts) if parts else ""
            
            if duration_str:
                return f"'{title}' ({duration_str}) {time_info}'de eklensin mi?"
            elif time_info:
                return f"'{title}' {time_info}'de eklensin mi?"
            else:
                return f"'{title}' etkinliği eklensin mi?"
        
        elif self.action_type == "update":
            return f"'{title}' güncellensin mi?"
        
        elif self.action_type == "delete":
            return f"'{title}' silinsin mi?"
        
        return f"'{title}' işlemi yapılsın mı?"
    
    def _gmail_prompt(self, title: str, norm: type) -> str:
        """Generate gmail-specific prompt."""
        if self.action_type == "send":
            recipient = self.recipient or self.extra.get("to", "")
            if recipient:
                return f"'{recipient}' adresine '{title}' konulu mail gönderilsin mi?"
            return f"'{title}' konulu mail gönderilsin mi?"
        
        elif self.action_type == "delete":
            return f"'{title}' maili silinsin mi?"
        
        return f"'{title}' işlemi yapılsın mı?"


@dataclass
class EditPath:
    """Handle single-question edit path for confirmations.
    
    When user says something like "14:30 olsun" after a confirmation prompt,
    this handles the partial update.
    """
    
    # Patterns that indicate an edit request
    EDIT_PATTERNS: list[str] = field(default_factory=lambda: [
        r"^(\d{1,2}:\d{2})\s*(?:olsun|yap|koy)?$",  # "14:30 olsun"
        r"^saat\s*(\d{1,2}:\d{2})$",  # "saat 14:30"
        r"^(\d{1,2})\s*(?:olsun|yap)?$",  # "15 olsun" (just hour)
        r"^(\w+)\s*olsun$",  # "Toplantı olsun" (title change)
        r"^(?:tarih|gün)\s*(.+)$",  # "tarih yarın"
        r"^(\d+)\s*(?:saat|dakika)\s*(?:olsun)?$",  # "2 saat olsun"
    ])
    
    @classmethod
    def detect_edit(cls, text: str) -> Optional[dict[str, str]]:
        """Detect if text is an edit request and extract the change.
        
        Args:
            text: User input after confirmation prompt
            
        Returns:
            Dict with field and value if edit detected, None otherwise
        """
        if not text:
            return None
        
        t = text.strip().lower()
        
        # Time edit: "14:30 olsun"
        match = re.match(r'^(\d{1,2}:\d{2})\s*(?:olsun|yap|koy)?$', t)
        if match:
            return {"field": "time", "value": match.group(1)}
        
        # Time with saat: "saat 14:30"
        match = re.match(r'^saat\s*(\d{1,2}:\d{2})$', t)
        if match:
            return {"field": "time", "value": match.group(1)}
        
        # Hour only: "15 olsun"
        match = re.match(r'^(\d{1,2})\s*(?:olsun|yap)?$', t)
        if match:
            hour = int(match.group(1))
            if 0 <= hour <= 23:
                return {"field": "time", "value": f"{hour:02d}:00"}
        
        # Duration edit: "2 saat olsun"
        match = re.match(r'^(\d+)\s*saat\s*(?:olsun)?$', t)
        if match:
            hours = int(match.group(1))
            return {"field": "duration", "value": str(hours * 60)}
        
        match = re.match(r'^(\d+)\s*dakika\s*(?:olsun)?$', t)
        if match:
            return {"field": "duration", "value": match.group(1)}
        
        # Date edit: "yarın olsun"
        if any(d in t for d in ["yarın", "bugün", "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]):
            # Extract the date hint
            for day in ["yarın", "bugün", "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]:
                if day in t:
                    return {"field": "date_hint", "value": day}
        
        return None
    
    @classmethod
    def apply_edit(
        cls,
        slots: dict[str, Any],
        edit: dict[str, str],
    ) -> dict[str, Any]:
        """Apply edit to existing slots.
        
        Args:
            slots: Current slots dict
            edit: Edit dict from detect_edit
            
        Returns:
            Updated slots dict
        """
        if not edit:
            return slots
        
        result = dict(slots)
        field = edit.get("field", "")
        value = edit.get("value", "")
        
        if field == "time":
            result["time"] = value
        elif field == "duration":
            result["duration"] = int(value)
        elif field == "date_hint":
            result["window_hint"] = value
            # Also set date if possible
            # This would need integration with turkish_time module
        elif field == "title":
            result["title"] = value
        
        return result


@dataclass(frozen=True)
class IdempotencyKey:
    """Generate and check idempotency keys for operations.
    
    Prevents duplicate operations by generating a unique key based on
    operation parameters.
    """
    
    key: str
    created_at: datetime
    
    @classmethod
    def generate(
        cls,
        action_type: str,
        target: str,
        **params: Any,
    ) -> "IdempotencyKey":
        """Generate idempotency key for operation.
        
        Args:
            action_type: Type of action (create, update, delete)
            target: Target system (calendar, gmail)
            **params: Operation parameters
            
        Returns:
            IdempotencyKey instance
        """
        # Create deterministic string from parameters
        key_parts = [
            str(action_type),
            str(target),
        ]
        
        # Sort params for determinism
        for k in sorted(params.keys()):
            v = params[k]
            if v is not None:
                key_parts.append(f"{k}={v}")
        
        key_string = "|".join(key_parts)
        
        # Hash for consistent length
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()[:16]
        
        return cls(
            key=key_hash,
            created_at=datetime.now(),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "key": self.key,
            "created_at": self.created_at.isoformat(),
        }


class IdempotencyTracker:
    """Track recent operations to prevent duplicates."""
    
    def __init__(self, max_entries: int = 100, ttl_seconds: int = 300):
        """Initialize tracker.
        
        Args:
            max_entries: Maximum number of keys to track
            ttl_seconds: Time-to-live for keys in seconds
        """
        self._keys: dict[str, datetime] = {}
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
    
    def check_and_mark(self, key: IdempotencyKey) -> bool:
        """Check if operation is duplicate and mark as seen.
        
        Args:
            key: Idempotency key to check
            
        Returns:
            True if this is a new operation, False if duplicate
        """
        self._cleanup()
        
        if key.key in self._keys:
            return False  # Duplicate
        
        self._keys[key.key] = key.created_at
        return True  # New operation
    
    def _cleanup(self) -> None:
        """Remove expired keys."""
        from datetime import timedelta
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=self._ttl_seconds)
        
        # Remove expired
        expired = [k for k, v in self._keys.items() if v < cutoff]
        for k in expired:
            del self._keys[k]
        
        # Trim to max if needed
        if len(self._keys) > self._max_entries:
            # Remove oldest entries
            sorted_keys = sorted(self._keys.items(), key=lambda x: x[1])
            for k, _ in sorted_keys[:len(self._keys) - self._max_entries]:
                del self._keys[k]


def build_confirmation_prompt(
    slots: dict[str, Any],
    action_type: str = "create",
    target: str = "calendar",
) -> str:
    """Build a standardized confirmation prompt from slots.
    
    Args:
        slots: Slot dictionary with title, time, date, duration, etc.
        action_type: Action type (create, update, delete, send)
        target: Target system (calendar, gmail)
        
    Returns:
        Turkish confirmation prompt string
    """
    preview = ConfirmationPreview(
        action_type=action_type,
        target=target,
        title=slots.get("title", "Etkinlik"),
        time=slots.get("time"),
        date=slots.get("date"),
        duration=slots.get("duration"),
        recipient=slots.get("to") or slots.get("recipient"),
        extra=slots,
    )
    
    return preview.to_turkish()


# ---------------------------------------------------------------------------
# Issue #426: Deterministic confirmation prompt (by tool_name)
# ---------------------------------------------------------------------------

# Mapping tool_name → (action_type, target)
_TOOL_ACTION_MAP: dict[str, tuple[str, str]] = {
    "calendar.create_event": ("create", "calendar"),
    "calendar.update_event": ("update", "calendar"),
    "calendar.delete_event": ("delete", "calendar"),
    "gmail.send": ("send", "gmail"),
    "gmail.send_to_contact": ("send", "gmail"),
    "gmail.send_draft": ("send", "gmail"),
    "gmail.create_draft": ("create", "gmail"),
    "gmail.generate_reply": ("send", "gmail"),
    "gmail.download_attachment": ("create", "generic"),
    "gmail.archive": ("update", "gmail"),
    "gmail.batch_modify": ("update", "gmail"),
    "file.delete": ("delete", "generic"),
    "file.move": ("update", "generic"),
    "app.close": ("delete", "generic"),
    "system.execute_command": ("create", "generic"),
    "system.shutdown": ("delete", "generic"),
    "payment.submit": ("create", "generic"),
    "email.delete": ("delete", "gmail"),
    "database.delete": ("delete", "generic"),
}

# Generic fallback templates (by tool_name) for tools not covered by ConfirmationPreview
_GENERIC_TOOL_TEMPLATES: dict[str, str] = {
    "gmail.send_draft": "Taslak gönderilsin mi?",
    "gmail.download_attachment": "E-postadaki ek indirilsin mi?",
    "gmail.archive": "E-posta arşivlensin mi?",
    "gmail.batch_modify": "Birden fazla e-posta için etiket değişikliği yapılsın mı?",
    "gmail.generate_reply": "E-postaya yanıt taslağı oluşturulsun mu?",
    "file.delete": "'{path}' dosyası silinsin mi? Bu işlem geri alınamaz.",
    "file.move": "Dosya taşınsın mı?",
    "app.close": "Uygulama kapatılsın mı?",
    "system.execute_command": "Komut çalıştırılsın mı?",
    "system.shutdown": "Sistem kapatılsın mı? Kaydedilmemiş işler kaybolacak.",
    "payment.submit": "Ödeme yapılsın mı? Bu işlem geri alınamaz.",
    "database.delete": "Veritabanından silme yapılsın mı? Bu işlem geri alınamaz.",
}


def deterministic_confirmation_prompt(
    tool_name: str,
    slots: dict[str, Any],
) -> str:
    """Build a deterministic confirmation prompt from tool_name + slots only.

    Issue #426: This is the PREFERRED way to generate confirmation prompts.
    It NEVER uses LLM-generated text — only slot data and predefined templates.

    Args:
        tool_name: The tool requiring confirmation.
        slots: Slot dict from the orchestrator output.

    Returns:
        A Turkish confirmation prompt string.
    """
    slots = slots or {}

    # Resolve action_type and target from tool_name
    mapping = _TOOL_ACTION_MAP.get(tool_name)

    if mapping:
        action_type, target = mapping
    else:
        # Unknown tool: use generic
        return f"{tool_name} çalıştırılsın mı? (evet/hayır)"

    # For calendar and gmail tools with well-known slot shapes, delegate to
    # the ConfirmationPreview builder.
    if target in ("calendar", "gmail"):
        title = slots.get("title") or slots.get("subject") or slots.get("summary", "")

        # Gmail send: use 'to' or 'name'
        if tool_name == "gmail.send_to_contact":
            title = title or slots.get("name", "")
        # Gmail with no useful title: use generic template
        if target == "gmail" and not title and tool_name in _GENERIC_TOOL_TEMPLATES:
            return _safe_format(_GENERIC_TOOL_TEMPLATES[tool_name], slots)

        # Issue #1212: For calendar events, use a descriptive default
        # instead of generic "İşlem" so user sees what's being created.
        if target == "calendar" and not title:
            default_title = "Etkinlik"
        elif not title:
            default_title = "İşlem"
        else:
            default_title = title

        preview = ConfirmationPreview(
            action_type=action_type,
            target=target,
            title=default_title,
            time=slots.get("time"),
            date=slots.get("date"),
            duration=slots.get("duration"),
            recipient=slots.get("to") or slots.get("recipient") or slots.get("name"),
            extra=slots,
        )
        return preview.to_turkish()

    # Generic tools: use template if available
    if tool_name in _GENERIC_TOOL_TEMPLATES:
        return _safe_format(_GENERIC_TOOL_TEMPLATES[tool_name], slots)

    return f"{tool_name} çalıştırılsın mı? (evet/hayır)"


def _safe_format(template: str, slots: dict[str, Any]) -> str:
    """Format template with slot values, ignoring missing keys."""
    try:
        safe_kwargs = {k: str(v) for k, v in slots.items() if v is not None}
        return template.format(**safe_kwargs)
    except (KeyError, ValueError, IndexError):
        # Strip unresolved placeholders
        return re.sub(r"'\{[^}]+\}'", "?", template)


# ---------------------------------------------------------------------------
# No-new-facts guard (Issue #426)
# ---------------------------------------------------------------------------

def no_new_facts(prompt: str, slots: dict[str, Any]) -> bool:
    """Validate that a prompt does not introduce facts absent from slots.

    Heuristic: every *quoted* value in the prompt must be traceable to a
    slot value. This prevents LLM hallucinated times/dates/names from
    sneaking into confirmation messages.

    Args:
        prompt: The confirmation prompt to validate.
        slots: The slot dict that was used to build the prompt.

    Returns:
        True if the prompt is safe (all quoted facts are in slots),
        False if the prompt contains information not traceable to slots.
    """
    if not slots:
        return True  # nothing to verify against

    # Collect all slot value strings (flattened, lowercased)
    slot_values: set[str] = set()
    for v in slots.values():
        if v is None:
            continue
        sv = str(v).strip().lower()
        if sv:
            slot_values.add(sv)

    # Extract quoted strings from prompt
    quoted = re.findall(r"'([^']+)'", prompt)
    for q in quoted:
        q_lower = q.strip().lower()
        if not q_lower:
            continue
        # Check if quoted value appears in any slot value (or vice versa)
        if not any(q_lower in sv or sv in q_lower for sv in slot_values):
            return False

    return True

