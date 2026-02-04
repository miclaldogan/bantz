from __future__ import annotations

import logging
import re
from typing import Any

_REDACTED = "***REDACTED***"

# Common API keys / tokens
_RE_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b")
_RE_OAUTH_YA29 = re.compile(r"\bya29\.[0-9A-Za-z\-_]+\b")
_RE_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE)
_RE_JWT = re.compile(r"\beyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\b")

# Private key blocks
_RE_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN PRIVATE KEY-----[\s\S]*?-----END PRIVATE KEY-----",
    re.MULTILINE,
)

# Env-style assignments that might end up in logs
_RE_ENV_ASSIGN = re.compile(
    r"\b("
    r"GEMINI_API_KEY|GOOGLE_API_KEY|BANTZ_GEMINI_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|"
    r"BANTZ_GOOGLE_CLIENT_SECRET|BANTZ_GMAIL_CLIENT_SECRET|BANTZ_GOOGLE_SERVICE_ACCOUNT|GOOGLE_APPLICATION_CREDENTIALS"
    r")\b\s*[:=]\s*([^\s'\"\n]+)",
    re.IGNORECASE,
)

# JSON key/value patterns
_RE_JSON_SECRET_FIELDS = re.compile(
    r"(\"(?:api_key|access_token|refresh_token|client_secret|private_key)\"\s*:\s*)\"([^\"]*)\"",
    re.IGNORECASE,
)

# Path-ish tokens that are commonly sensitive (credential files)
_RE_CRED_PATH = re.compile(
    r"(?P<path>(?:~|/)[^\s\"]*(?:service_account|client_secret|token)[^\s\"]*\.json)",
    re.IGNORECASE,
)


def mask_path(path: str) -> str:
    """Mask a filesystem path while preserving only the basename."""

    p = str(path or "").strip()
    if not p:
        return p

    # Normalize slashes; keep only the last segment.
    sep = "/"
    if sep in p:
        base = p.rsplit(sep, 1)[-1]
        return f"…/{base}"

    # No directory component
    return "…/" + p


def mask_secrets(text: str) -> str:
    """Best-effort masking for logs/CLI output.

    This is intentionally heuristic. It aims to prevent accidental leakage of
    API keys, OAuth tokens, private keys, and credential paths.
    """

    t = str(text or "")
    if not t:
        return t

    # Mask private key blocks first (they can contain other patterns).
    t = _RE_PRIVATE_KEY_BLOCK.sub(_REDACTED, t)

    # Mask explicit env assignments
    t = _RE_ENV_ASSIGN.sub(lambda m: f"{m.group(1)}={_REDACTED}", t)

    # Mask JSON fields
    t = _RE_JSON_SECRET_FIELDS.sub(lambda m: f"{m.group(1)}\"{_REDACTED}\"", t)

    # Mask known token formats
    t = _RE_GOOGLE_API_KEY.sub(_REDACTED, t)
    t = _RE_OAUTH_YA29.sub(_REDACTED, t)
    t = _RE_JWT.sub(_REDACTED, t)

    # Mask bearer tokens but keep the word "Bearer".
    t = _RE_BEARER.sub("Bearer " + _REDACTED, t)

    # Mask credential paths.
    t = _RE_CRED_PATH.sub(lambda m: mask_path(m.group("path")), t)

    return t


def sanitize(obj: Any) -> Any:
    """Recursively sanitize strings inside dict/list structures for safe display."""

    if obj is None:
        return None
    if isinstance(obj, str):
        return mask_secrets(obj)
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize(x) for x in obj)
    return obj


class SecretsRedactionFilter(logging.Filter):
    """Redact secrets from logging records (best-effort).

    This filter replaces the *formatted* message with a masked version and
    clears args to avoid leaking secrets via formatting.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
            msg = mask_secrets(msg)
            record.msg = msg
            record.args = ()
        except Exception:
            # Never break logging.
            pass
        return True


def install_secrets_redaction_filter(logger: logging.Logger | None = None) -> SecretsRedactionFilter:
    """Install a secrets redaction filter on a logger (default: root)."""

    log = logger or logging.getLogger()
    filt = SecretsRedactionFilter()
    try:
        log.addFilter(filt)
        for handler in getattr(log, "handlers", []) or []:
            handler.addFilter(filt)
    except Exception:
        pass
    return filt
