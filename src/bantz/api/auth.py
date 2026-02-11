"""Bearer token authentication for the Bantz REST API (Issue #834).

Auth scheme:
    Authorization: Bearer <BANTZ_API_TOKEN>

The token is read from:
  1. BANTZ_API_TOKEN environment variable
  2. Bantz SecureVault (if available)

When BANTZ_API_TOKEN is not set, auth is **disabled** (dev mode).
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# Cached token (resolved once at startup)
_resolved_token: Optional[str] = None
_token_resolved: bool = False


def _resolve_token() -> Optional[str]:
    """Resolve the API token from env or vault. Returns None if unset."""
    global _resolved_token, _token_resolved

    if _token_resolved:
        return _resolved_token

    # 1. Environment variable (highest priority)
    token = os.getenv("BANTZ_API_TOKEN", "").strip()
    if token:
        _resolved_token = token
        _token_resolved = True
        logger.info("API auth: BANTZ_API_TOKEN set (env) ✓")
        return _resolved_token

    # 2. Try SecureVault
    try:
        from bantz.security.vault import get_vault

        vault = get_vault()
        token = vault.get("BANTZ_API_TOKEN", "").strip()
        if token:
            _resolved_token = token
            _token_resolved = True
            logger.info("API auth: BANTZ_API_TOKEN set (vault) ✓")
            return _resolved_token
    except Exception:
        pass

    _resolved_token = None
    _token_resolved = True
    logger.warning(
        "⚠ BANTZ_API_TOKEN not set — API auth is DISABLED. "
        "Set BANTZ_API_TOKEN for production use."
    )
    return None


def reset_token_cache() -> None:
    """Reset the cached token (for testing)."""
    global _resolved_token, _token_resolved
    _resolved_token = None
    _token_resolved = False


def is_auth_enabled() -> bool:
    """Check whether API authentication is enabled."""
    return _resolve_token() is not None


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[str]:
    """FastAPI dependency that enforces Bearer token auth.

    - If BANTZ_API_TOKEN is set: requires valid Bearer token.
    - If BANTZ_API_TOKEN is unset: allows all requests (dev mode).

    Returns the validated token string or None (dev mode).
    """
    expected = _resolve_token()

    # Dev mode: no token configured → allow everything
    if expected is None:
        return None

    if credentials is None:
        # Audit log
        _audit_auth_failure(request, reason="missing_header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header gerekli. Örnek: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(credentials.credentials, expected):
        _audit_auth_failure(request, reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


def _audit_auth_failure(request: Request, reason: str) -> None:
    """Log authentication failure for security audit."""
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path
    logger.warning(
        "AUTH_FAILURE: reason=%s ip=%s path=%s", reason, client_ip, path
    )
    try:
        from bantz.security.audit import log_security_event, SecurityEventType

        log_security_event(
            event_type=SecurityEventType.AUTH_FAILURE,
            details={"reason": reason, "ip": client_ip, "path": path},
        )
    except Exception:
        pass  # Never block on audit failure
