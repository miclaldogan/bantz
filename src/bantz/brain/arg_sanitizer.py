"""Tool argument sanitization (Issue #425).

Provides input validation and sanitization for tool arguments to prevent:
- HTML/script injection in text fields
- Email format injection (semicolons, SQL fragments)
- Oversized text fields
- Basic prompt injection patterns
- Shell injection in command-like arguments

Usage:
    sanitizer = ArgSanitizer()
    clean_params, issues = sanitizer.sanitize("gmail.send", {"to": "user@x.com", "body": "hello"})
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Sanitization issue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SanitizationIssue:
    """A single sanitization finding."""

    field: str
    issue_type: str  # "html_injection", "email_invalid", "too_long", "prompt_injection", "shell_injection"
    description: str
    severity: str = "warning"  # "warning" (sanitized & passed) or "block" (rejected)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<\s*/?\s*(?:script|iframe|object|embed|form|input|link|meta|style)\b[^>]*>", re.IGNORECASE)
_HTML_EVENT_RE = re.compile(r"\bon\w+\s*=", re.IGNORECASE)

# Strict email: local@domain, no semicolons, pipes, backticks
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_EMAIL_INJECTION_RE = re.compile(r"[;|`\n\r]|DROP\s+TABLE|--\s|\/\*", re.IGNORECASE)

# Prompt injection heuristics
_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?your\s+(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|a\s+new\s+AI|an?\s+unrestricted)", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"\[SYSTEM\]|\[INST\]|\[/INST\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
]

# Shell injection patterns (for system.execute_command args, etc.)
_SHELL_INJECTION_RE = re.compile(r"[;&|`]\s*\w|>\s*/|<<|\\x[0-9a-f]|\$\(|\$\{", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Field limits
# ---------------------------------------------------------------------------

_FIELD_MAX_LENGTHS: dict[str, int] = {
    # Gmail
    "to": 254,
    "cc": 254,
    "bcc": 254,
    "subject": 500,
    "body": 50_000,
    # Calendar
    "title": 200,
    "summary": 200,
    "description": 5000,
    "location": 500,
    # Generic
    "query": 1000,
    "search_term": 500,
    "natural_query": 1000,
    "command": 2000,
    "path": 4096,
    "name": 200,
}


# ---------------------------------------------------------------------------
# Per-tool sanitization rules
# ---------------------------------------------------------------------------

# Fields that must be validated as email addresses
_EMAIL_FIELDS = {"to", "cc", "bcc", "to_address", "recipient", "email"}

# Tools where body/text fields should be checked for prompt injection
_PROMPT_CHECK_TOOLS = {
    "gmail.send",
    "gmail.send_to_contact",
    "gmail.send_draft",
    "gmail.create_draft",
    "gmail.update_draft",
    "gmail.generate_reply",
}

# Tools where arguments may be shell commands
_SHELL_CHECK_TOOLS = {
    "system.execute_command",
    "system.sudo",
}


# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------

class ArgSanitizer:
    """Sanitize and validate tool arguments (Issue #425)."""

    def sanitize(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], list[SanitizationIssue]]:
        """Sanitize tool parameters.

        Returns:
            (cleaned_params, issues) – cleaned_params has sanitized values,
            issues lists any findings. If a severity="block" issue is found,
            the caller should reject the tool call.
        """
        cleaned = dict(params)
        issues: list[SanitizationIssue] = []

        for field_name, value in list(cleaned.items()):
            if not isinstance(value, str):
                continue

            # 1) Length limit
            max_len = _FIELD_MAX_LENGTHS.get(field_name)
            if max_len and len(value) > max_len:
                cleaned[field_name] = value[:max_len]
                issues.append(SanitizationIssue(
                    field=field_name,
                    issue_type="too_long",
                    description=f"Truncated from {len(value)} to {max_len} chars",
                    severity="warning",
                ))
                value = cleaned[field_name]

            # 2) HTML/script injection (strip dangerous tags)
            if _HTML_TAG_RE.search(value):
                cleaned_val = _HTML_TAG_RE.sub("", value)
                cleaned[field_name] = cleaned_val
                issues.append(SanitizationIssue(
                    field=field_name,
                    issue_type="html_injection",
                    description="HTML/script tags removed",
                    severity="warning",
                ))
                value = cleaned_val

            if _HTML_EVENT_RE.search(value):
                cleaned_val = _HTML_EVENT_RE.sub("", value)
                cleaned[field_name] = cleaned_val
                issues.append(SanitizationIssue(
                    field=field_name,
                    issue_type="html_injection",
                    description="HTML event handlers removed",
                    severity="warning",
                ))
                value = cleaned_val

            # 3) Email validation
            if field_name in _EMAIL_FIELDS and value:
                if _EMAIL_INJECTION_RE.search(value):
                    issues.append(SanitizationIssue(
                        field=field_name,
                        issue_type="email_invalid",
                        description=f"Suspicious characters in email field: {value!r}",
                        severity="block",
                    ))
                elif not _EMAIL_RE.match(value.strip()):
                    issues.append(SanitizationIssue(
                        field=field_name,
                        issue_type="email_invalid",
                        description=f"Invalid email format: {value!r}",
                        severity="block",
                    ))

            # 4) Prompt injection detection
            if tool_name in _PROMPT_CHECK_TOOLS and field_name in ("body", "subject", "text", "content", "message"):
                for pattern in _PROMPT_INJECTION_PATTERNS:
                    if pattern.search(value):
                        issues.append(SanitizationIssue(
                            field=field_name,
                            issue_type="prompt_injection",
                            description=f"Prompt injection pattern detected",
                            severity="block",
                        ))
                        break  # one finding is enough

            # 5) Shell injection
            if tool_name in _SHELL_CHECK_TOOLS and field_name in ("command", "args", "cmd"):
                if _SHELL_INJECTION_RE.search(value):
                    issues.append(SanitizationIssue(
                        field=field_name,
                        issue_type="shell_injection",
                        description=f"Shell injection pattern detected",
                        severity="block",
                    ))

        return cleaned, issues

    def has_blocking_issues(self, issues: list[SanitizationIssue]) -> bool:
        """Return True if any issue has severity='block'."""
        return any(i.severity == "block" for i in issues)

    def blocking_summary(self, issues: list[SanitizationIssue]) -> str:
        """Return a human-readable summary of blocking issues."""
        blocked = [i for i in issues if i.severity == "block"]
        if not blocked:
            return ""
        parts = [f"{i.field}: {i.description}" for i in blocked]
        return "; ".join(parts)
