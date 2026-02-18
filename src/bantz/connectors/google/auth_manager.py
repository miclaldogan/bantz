"""Unified Google OAuth2 Token Manager — single refresh token, incremental scopes.

Issue #1292: Replaces fragmented per-service tokens with a single
``google_unified_token.json`` that can be incrementally expanded
to cover new Google APIs without re-authenticating from scratch.

Design
------
- One ``GoogleAuthManager`` instance per Bantz process.
- ``SCOPE_REGISTRY`` maps service names to their Google OAuth scopes.
- ``ensure_scope(service)`` checks whether the current token covers
  the requested scopes; if not, triggers an incremental consent flow.
- ``get_service(service_name)`` returns an authenticated
  ``googleapiclient.discovery.Resource`` ready for use.
- Atomic file writing with ``fcntl`` locking to prevent corruption.

Backward Compatibility
----------------------
Existing per-service tokens (``token.json``, ``gmail_token.json``) are
still supported.  ``GoogleAuthManager`` can optionally *migrate* them
into the unified token on first use.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from bantz.security.secrets import mask_path

logger = logging.getLogger(__name__)

__all__ = ["GoogleAuthManager", "UnifiedAuthConfig"]


# ═══════════════════════════════════════════════════════════════════
# Scope Registry
# ═══════════════════════════════════════════════════════════════════

SCOPE_REGISTRY: dict[str, list[str]] = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "calendar": [
        "https://www.googleapis.com/auth/calendar",
    ],
    "contacts": [
        "https://www.googleapis.com/auth/contacts.readonly",
    ],
    "tasks": [
        "https://www.googleapis.com/auth/tasks",
    ],
    "keep": [
        "https://www.googleapis.com/auth/keep",
    ],
    "classroom": [
        "https://www.googleapis.com/auth/classroom.courses.readonly",
        "https://www.googleapis.com/auth/classroom.coursework.me",
    ],
}

# Google API discovery service names + versions
SERVICE_MAP: dict[str, tuple[str, str]] = {
    "gmail": ("gmail", "v1"),
    "calendar": ("calendar", "v3"),
    "contacts": ("people", "v1"),
    "tasks": ("tasks", "v1"),
    "keep": ("keep", "v1"),
    "classroom": ("classroom", "v1"),
}

# Implied scope map — prevents re-consent loops when a broader scope
# already satisfies a narrower one.
_IMPLIED_SCOPES: dict[str, set[str]] = {
    "https://www.googleapis.com/auth/calendar": {
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.events.readonly",
    },
    "https://www.googleapis.com/auth/gmail.modify": {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.metadata",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.compose",
    },
    "https://www.googleapis.com/auth/contacts": {
        "https://www.googleapis.com/auth/contacts.readonly",
    },
    "https://www.googleapis.com/auth/tasks": {
        "https://www.googleapis.com/auth/tasks.readonly",
    },
    "https://www.googleapis.com/auth/classroom.courses": {
        "https://www.googleapis.com/auth/classroom.courses.readonly",
    },
}


# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

DEFAULT_UNIFIED_TOKEN_PATH = "~/.config/bantz/google/google_unified_token.json"
DEFAULT_CLIENT_SECRET_PATH = "~/.config/bantz/google/client_secret.json"


@dataclass(frozen=True)
class UnifiedAuthConfig:
    """Configuration for the unified Google auth manager."""
    client_secret_path: Path
    token_path: Path


def _resolve_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def _get_unified_config(
    *,
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> UnifiedAuthConfig:
    """Resolve file paths for unified auth.

    Env vars:
    - ``BANTZ_GOOGLE_CLIENT_SECRET``
    - ``BANTZ_GOOGLE_UNIFIED_TOKEN_PATH``
    """
    secret = (
        client_secret_path
        or os.getenv("BANTZ_GOOGLE_CLIENT_SECRET")
        or DEFAULT_CLIENT_SECRET_PATH
    )
    token = (
        token_path
        or os.getenv("BANTZ_GOOGLE_UNIFIED_TOKEN_PATH")
        or DEFAULT_UNIFIED_TOKEN_PATH
    )
    return UnifiedAuthConfig(
        client_secret_path=_resolve_path(secret),
        token_path=_resolve_path(token),
    )


# ═══════════════════════════════════════════════════════════════════
# Lazy Google deps
# ═══════════════════════════════════════════════════════════════════

def _import_google_deps():
    """Lazily import Google auth and API client libraries."""
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Google API dependencies are not installed. "
            "Install with: pip install google-api-python-client "
            "google-auth-oauthlib google-auth-httplib2"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


# ═══════════════════════════════════════════════════════════════════
# Auth Manager
# ═══════════════════════════════════════════════════════════════════

class GoogleAuthManager:
    """Unified Google OAuth2 token manager with incremental scope expansion.

    A single refresh token that is progressively expanded as new
    Google services are enabled.  Replaces the fragmented per-service
    token files used before Issue #1292.

    Parameters
    ----------
    token_path : str, optional
        Path to the unified token JSON file.
    client_secret_path : str, optional
        Path to the Google OAuth client secret JSON.
    interactive : bool
        If ``False``, raise ``RuntimeError`` instead of opening a browser
        when re-consent is needed.  Defaults to ``True``.
    """

    def __init__(
        self,
        *,
        token_path: Optional[str] = None,
        client_secret_path: Optional[str] = None,
        interactive: bool = True,
    ):
        self._cfg = _get_unified_config(
            client_secret_path=client_secret_path,
            token_path=token_path,
        )
        self._interactive = interactive
        self._credentials: Any = None
        self._service_cache: dict[str, Any] = {}

    # ── public API ──────────────────────────────────────────────

    @property
    def token_path(self) -> Path:
        return self._cfg.token_path

    @property
    def client_secret_path(self) -> Path:
        return self._cfg.client_secret_path

    def ensure_scope(self, service: str) -> Any:
        """Ensure the token covers *service*'s scopes.  Returns credentials.

        If the current token is missing the required scopes, triggers
        an incremental consent flow (interactive) or raises
        ``RuntimeError`` (non-interactive).
        """
        if service not in SCOPE_REGISTRY:
            raise ValueError(
                "Bilinmeyen Google servisi: %s. "
                "Geçerli servisler: %s" % (service, ", ".join(sorted(SCOPE_REGISTRY)))
            )

        required = set(SCOPE_REGISTRY[service])
        self._load_credentials()

        if self._credentials is not None:
            current = self._effective_scopes(
                getattr(self._credentials, "scopes", None)
            )
            missing = required - current
        else:
            missing = required

        if missing:
            logger.info(
                "Yeni scope gerekli: %s → %s", service, sorted(missing),
            )
            self._expand_scopes(list(missing))

        return self._credentials

    def get_service(self, service_name: str) -> Any:
        """Return an authenticated Google API resource for *service_name*.

        Results are cached per service to avoid repeated ``build()`` calls.
        """
        if service_name in self._service_cache:
            return self._service_cache[service_name]

        creds = self.ensure_scope(service_name)

        if service_name not in SERVICE_MAP:
            raise ValueError(
                "Bilinmeyen Google servisi: %s" % service_name
            )

        api_name, api_version = SERVICE_MAP[service_name]
        _Request, _Creds, _Flow, build = _import_google_deps()

        svc = build(api_name, api_version, credentials=creds, cache_discovery=False)
        self._service_cache[service_name] = svc
        return svc

    def get_credentials(self, *, scopes: list[str]) -> Any:
        """Low-level: ensure the token covers *scopes* and return credentials.

        This bridges the old ``get_credentials(scopes=...)`` pattern used by
        ``bantz.google.auth`` and ``bantz.google.gmail_auth``.
        """
        self._load_credentials()

        if self._credentials is not None:
            current = self._effective_scopes(
                getattr(self._credentials, "scopes", None)
            )
            missing = set(scopes) - current
        else:
            missing = set(scopes)

        if missing:
            self._expand_scopes(list(missing))

        return self._credentials

    def invalidate_cache(self, service_name: Optional[str] = None) -> None:
        """Drop cached API service objects.

        Call after a token refresh or scope expansion if services need
        to be rebuilt with fresh credentials.
        """
        if service_name:
            self._service_cache.pop(service_name, None)
        else:
            self._service_cache.clear()

    def current_scopes(self) -> list[str]:
        """Return the scopes the current token covers (empty if no token)."""
        self._load_credentials()
        if self._credentials is None:
            return []
        return list(getattr(self._credentials, "scopes", None) or [])

    def connected_services(self) -> list[str]:
        """Return service names whose scopes are fully covered."""
        current = self._effective_scopes(
            getattr(self._credentials, "scopes", None) if self._credentials else None
        )
        result = []
        for svc, scopes in SCOPE_REGISTRY.items():
            if set(scopes).issubset(current):
                result.append(svc)
        return sorted(result)

    # ── internal ────────────────────────────────────────────────

    def _load_credentials(self) -> None:
        """Load credentials from disk if not already loaded."""
        if self._credentials is not None:
            return

        _Request, Credentials, _Flow, _build = _import_google_deps()

        if not self._cfg.token_path.exists():
            return

        try:
            self._credentials = Credentials.from_authorized_user_file(
                str(self._cfg.token_path)
            )
        except Exception as exc:
            logger.warning("Token dosyası okunamadı: %s", exc)
            self._credentials = None
            return

        # Refresh if expired
        if (
            getattr(self._credentials, "expired", False)
            and getattr(self._credentials, "refresh_token", None)
        ):
            self._refresh_with_retry()

    def _refresh_with_retry(self, max_retries: int = 3) -> None:
        """Refresh the access token with exponential back-off."""
        _Request, _Creds, _Flow, _build = _import_google_deps()
        request = _Request()

        for attempt in range(max_retries):
            try:
                self._credentials.refresh(request)
                return
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = 2 ** attempt
                    logger.warning(
                        "Token yenileme başarısız (deneme %d/%d): %s — %ds sonra tekrar",
                        attempt + 1, max_retries, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Token yenileme %d denemeden sonra başarısız: %s",
                        max_retries, exc,
                    )
                    raise

    def _effective_scopes(self, granted: list[str] | None) -> set[str]:
        """Expand *granted* scopes with implied sub-scopes."""
        base = set(granted or [])
        expanded = set(base)
        for scope in list(base):
            expanded |= _IMPLIED_SCOPES.get(scope, set())
        return expanded

    def _expand_scopes(self, additional_scopes: list[str]) -> None:
        """Run a consent flow for *additional_scopes* and save the new token."""
        if not self._interactive:
            raise RuntimeError(
                "Google OAuth yetkilendirmesi gerekli (yeni scope'lar: %s). "
                "'/auth google' komutu ile yetkilendirme yapın. "
                "client_secret=%s token=%s" % (
                    ", ".join(sorted(additional_scopes)),
                    mask_path(str(self._cfg.client_secret_path)),
                    mask_path(str(self._cfg.token_path)),
                )
            )

        if not self._cfg.client_secret_path.exists():
            raise FileNotFoundError(
                "Google client secret bulunamadı. BANTZ_GOOGLE_CLIENT_SECRET "
                "env var'ını ayarlayın. Eksik: %s"
                % mask_path(str(self._cfg.client_secret_path))
            )

        _Request, _Creds, InstalledAppFlow, _build = _import_google_deps()

        # Combine existing + new scopes for the consent flow
        current = list(getattr(self._credentials, "scopes", None) or [])
        all_scopes = sorted(set(current) | set(additional_scopes))

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._cfg.client_secret_path), scopes=all_scopes
        )

        try:
            self._credentials = flow.run_local_server(port=0, open_browser=True)
        except Exception:
            try:
                self._credentials = flow.run_local_server(port=0, open_browser=False)
            except Exception:
                self._credentials = flow.run_console()

        # Persist
        self._save_token()
        # Clear service cache — credentials changed
        self._service_cache.clear()

    def _save_token(self) -> None:
        """Atomically save the current credentials to disk."""
        if self._credentials is None:
            return

        self._cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
        token_json = self._credentials.to_json()
        dir_str = str(self._cfg.token_path.parent)

        fd, tmp_path = tempfile.mkstemp(dir=dir_str, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                fh.write(token_json)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, str(self._cfg.token_path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── migration helpers ───────────────────────────────────────

    def migrate_legacy_tokens(self) -> dict[str, bool]:
        """Import scopes from old per-service token files.

        Reads ``token.json`` (Calendar/Contacts) and ``gmail_token.json``
        and merges their scopes into the unified token.  The legacy files
        are **not** deleted — users can remove them manually.

        Returns a dict of ``{service: migrated_bool}``.
        """
        legacy_map = {
            "calendar": _resolve_path(
                os.getenv("BANTZ_GOOGLE_TOKEN_PATH")
                or "~/.config/bantz/google/token.json"
            ),
            "gmail": _resolve_path(
                os.getenv("BANTZ_GMAIL_TOKEN_PATH")
                or "~/.config/bantz/google/gmail_token.json"
            ),
        }
        result: dict[str, bool] = {}

        _Request, Credentials, _Flow, _build = _import_google_deps()

        merged_scopes: set[str] = set()
        best_creds: Any = None

        for svc, path in legacy_map.items():
            if not path.exists():
                result[svc] = False
                continue
            try:
                creds = Credentials.from_authorized_user_file(str(path))
                scopes = set(getattr(creds, "scopes", None) or [])
                merged_scopes |= scopes

                # Prefer the credential with a refresh token
                if getattr(creds, "refresh_token", None):
                    best_creds = creds

                result[svc] = True
                logger.info("Legacy token migrated: %s (%s)", svc, mask_path(str(path)))
            except Exception as exc:
                logger.warning("Legacy token okunamadı (%s): %s", svc, exc)
                result[svc] = False

        if best_creds is not None and merged_scopes:
            # Set merged scopes on the best credential
            best_creds.scopes = list(merged_scopes)
            self._credentials = best_creds
            self._save_token()
            logger.info(
                "Unified token oluşturuldu: %d scope → %s",
                len(merged_scopes),
                mask_path(str(self._cfg.token_path)),
            )

        return result


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_auth_manager: Optional[GoogleAuthManager] = None


def get_auth_manager() -> Optional[GoogleAuthManager]:
    """Return the global ``GoogleAuthManager`` instance (or ``None``)."""
    return _auth_manager


def setup_auth_manager(
    *,
    token_path: Optional[str] = None,
    client_secret_path: Optional[str] = None,
    interactive: bool = True,
    auto_migrate: bool = False,
) -> GoogleAuthManager:
    """Create and store the global ``GoogleAuthManager``.

    Called once during startup (e.g. from ``runtime_factory.py``).
    """
    global _auth_manager

    _auth_manager = GoogleAuthManager(
        token_path=token_path,
        client_secret_path=client_secret_path,
        interactive=interactive,
    )

    if auto_migrate:
        _auth_manager.migrate_legacy_tokens()

    return _auth_manager
