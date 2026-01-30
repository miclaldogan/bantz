from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os


DEFAULT_CLIENT_SECRET_PATH = "~/.config/bantz/google/client_secret.json"
DEFAULT_TOKEN_PATH = "~/.config/bantz/google/token.json"


@dataclass(frozen=True)
class GoogleAuthConfig:
    client_secret_path: Path
    token_path: Path


def _resolve_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def get_google_auth_config(
    *,
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
) -> GoogleAuthConfig:
    secret = client_secret_path or os.getenv("BANTZ_GOOGLE_CLIENT_SECRET") or DEFAULT_CLIENT_SECRET_PATH
    token = token_path or os.getenv("BANTZ_GOOGLE_TOKEN_PATH") or DEFAULT_TOKEN_PATH

    secret_p = _resolve_path(secret)
    token_p = _resolve_path(token)

    return GoogleAuthConfig(client_secret_path=secret_p, token_path=token_p)


def get_credentials(
    *,
    scopes: list[str],
    client_secret_path: Optional[str] = None,
    token_path: Optional[str] = None,
):
    """Return Google OAuth credentials.

    Reads paths from env vars by default:
    - BANTZ_GOOGLE_CLIENT_SECRET (default: ~/.config/bantz/google/client_secret.json)
    - BANTZ_GOOGLE_TOKEN_PATH   (default: ~/.config/bantz/google/token.json)

    This helper intentionally imports Google deps lazily so the rest of the repo
    can run without installing calendar dependencies.
    """

    cfg = get_google_auth_config(client_secret_path=client_secret_path, token_path=token_path)

    if not cfg.client_secret_path.exists():
        raise FileNotFoundError(
            "Google client secret not found. Set BANTZ_GOOGLE_CLIENT_SECRET "
            f"or example to {DEFAULT_CLIENT_SECRET_PATH}. Missing: {cfg.client_secret_path}"
        )

    # Lazy imports
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google calendar dependencies are not installed. Install with: "
            "pip install -e '.[calendar]'"
        ) from e

    def _effective_scopes(granted: list[str] | None) -> set[str]:
        granted_set = set(granted or [])
        implied: dict[str, set[str]] = {
            # Write scope implies read access, but Google represents them as
            # distinct strings. Treat as satisfied to avoid re-consent loops.
            "https://www.googleapis.com/auth/calendar.events": {
                "https://www.googleapis.com/auth/calendar.readonly",
            },
        }

        out = set(granted_set)
        for s in list(granted_set):
            out |= implied.get(s, set())
        return out

    creds = None
    if cfg.token_path.exists():
        # Important: do NOT pass `scopes=` here.
        # Passing `scopes` can overwrite the loaded credential's scope set and
        # prevent reliable detection of insufficient permissions.
        creds = Credentials.from_authorized_user_file(str(cfg.token_path))

        # A token minted for narrower scopes (e.g. read-only) can still be
        # "valid" but will fail at runtime with insufficientPermissions.
        # Detect that early and force a re-consent flow to expand scopes.
        has_scopes = getattr(creds, "has_scopes", None)
        if callable(has_scopes) and not has_scopes(scopes):
            effective = _effective_scopes(getattr(creds, "scopes", None))
            if not set(scopes).issubset(effective):
                creds = None

    if creds is not None and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        creds.refresh(Request())

    if creds is None or not getattr(creds, "valid", False):
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret_path), scopes=scopes)
        try:
            creds = flow.run_local_server(port=0, open_browser=False)
        except Exception:
            # Headless fallback.
            creds = flow.run_console()

        cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds
