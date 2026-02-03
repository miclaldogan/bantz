from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import os


# Canonical Gmail OAuth scopes.
# Accept short forms like "gmail.readonly" too.
_GMAIL_SCOPE_PREFIX = "https://www.googleapis.com/auth/"

GMAIL_READONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
]

GMAIL_SEND_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

GMAIL_MODIFY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

DEFAULT_GMAIL_CLIENT_SECRET_PATH = "~/.config/bantz/google/client_secret_gmail.json"
DEFAULT_GMAIL_TOKEN_PATH = "~/.config/bantz/google/gmail_token.json"


@dataclass(frozen=True)
class GmailAuthConfig:
    client_secret_path: Path
    token_path: Path


def _resolve_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def _normalize_gmail_scopes(scopes: list[str]) -> list[str]:
    out: list[str] = []
    for s in scopes:
        raw = (s or "").strip()
        if not raw:
            continue
        if raw.startswith(_GMAIL_SCOPE_PREFIX):
            out.append(raw)
        elif raw.startswith("gmail."):
            out.append(_GMAIL_SCOPE_PREFIX + raw)
        else:
            # Allow passing full URL or already-normalized strings.
            out.append(raw)
    # Keep order stable, de-dup.
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _effective_scopes(granted: list[str] | None) -> set[str]:
    """Treat broad Gmail scopes as satisfying narrower ones.

    This prevents re-consent loops when a token already has a superset scope.
    """
    granted_set = set(_normalize_gmail_scopes(list(granted or [])))

    implied: dict[str, set[str]] = {
        "https://www.googleapis.com/auth/gmail.modify": {
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.metadata",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
        },
        "https://www.googleapis.com/auth/gmail.send": {
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.metadata",
        },
        "https://www.googleapis.com/auth/gmail.compose": {
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.metadata",
        },
    }

    out = set(granted_set)
    for s in list(granted_set):
        out |= implied.get(s, set())
    return out


def get_gmail_auth_config(
    *,
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> GmailAuthConfig:
    """Resolve Gmail OAuth file paths.

    Env vars (new):
    - BANTZ_GMAIL_CLIENT_SECRET (default: ~/.config/bantz/google/client_secret_gmail.json)
    - BANTZ_GMAIL_TOKEN_PATH    (default: ~/.config/bantz/google/gmail_token.json)

    Env vars (legacy/back-compat):
    - BANTZ_GOOGLE_CLIENT_SECRET
    - BANTZ_GOOGLE_GMAIL_TOKEN_PATH
    """

    secret = (
        client_secret_path
        or os.getenv("BANTZ_GMAIL_CLIENT_SECRET")
        or os.getenv("BANTZ_GOOGLE_CLIENT_SECRET")
        or DEFAULT_GMAIL_CLIENT_SECRET_PATH
    )

    token = (
        token_path
        or os.getenv("BANTZ_GMAIL_TOKEN_PATH")
        or os.getenv("BANTZ_GOOGLE_GMAIL_TOKEN_PATH")
        or DEFAULT_GMAIL_TOKEN_PATH
    )

    return GmailAuthConfig(
        client_secret_path=_resolve_path(secret),
        token_path=_resolve_path(token),
    )


def _import_google_deps():  # pragma: no cover
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    return Request, Credentials, InstalledAppFlow, build


def get_gmail_credentials(
    *,
    scopes: list[str],
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
):
    """Return Google OAuth credentials for Gmail.

    - Reads/writes token JSON under ~/.config/bantz/google by default.
    - Refreshes tokens when expired.
    - Escalates scopes (readonly -> send/modify) by forcing re-consent.

    Notes:
    - Access tokens expire quickly; refresh tokens are used to refresh silently.
    - If the stored credential doesn't cover the requested scopes, a new consent
      flow will be triggered.
    """

    requested_scopes = _normalize_gmail_scopes(scopes)
    if not requested_scopes:
        raise ValueError("Gmail scopes must be non-empty")

    cfg = get_gmail_auth_config(client_secret_path=client_secret_path, token_path=token_path)

    if not cfg.client_secret_path.exists():
        raise FileNotFoundError(
            "Gmail client secret not found. Set BANTZ_GMAIL_CLIENT_SECRET "
            f"(default: {DEFAULT_GMAIL_CLIENT_SECRET_PATH}). Missing: {cfg.client_secret_path}"
        )

    try:
        Request, Credentials, InstalledAppFlow, _build = _import_google_deps()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google Gmail dependencies are not installed. Install with: pip install -e '.[calendar]'"
        ) from e

    creds: Any = None

    if cfg.token_path.exists():
        # Important: do NOT pass `scopes=` here.
        creds = Credentials.from_authorized_user_file(str(cfg.token_path))

        # If token is valid but scopes are insufficient, force re-consent.
        has_scopes = getattr(creds, "has_scopes", None)
        if callable(has_scopes) and not has_scopes(requested_scopes):
            effective = _effective_scopes(getattr(creds, "scopes", None))
            if not set(requested_scopes).issubset(effective):
                creds = None

    if creds is not None and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        creds.refresh(Request())

    if creds is None or not getattr(creds, "valid", False):
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret_path), scopes=requested_scopes)
        try:
            creds = flow.run_local_server(port=0, open_browser=False)
        except Exception:
            creds = flow.run_console()

        cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def authenticate_gmail(
    *,
    scopes: list[str],
    token_path: Optional[str] = None,
    secret_path: Optional[str] = None,
):
    """Authenticate and return a Gmail API service.

    Example:
        service = authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)
        profile = service.users().getProfile(userId="me").execute()

    Returns:
        googleapiclient.discovery.Resource for Gmail v1
    """

    creds = get_gmail_credentials(scopes=scopes, client_secret_path=secret_path, token_path=token_path)

    try:
        _Request, _Credentials, _InstalledAppFlow, build = _import_google_deps()
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google Gmail dependencies are not installed. Install with: pip install -e '.[calendar]'"
        ) from e

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
