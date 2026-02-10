from __future__ import annotations

import fcntl
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os

from bantz.security.secrets import mask_path

logger = logging.getLogger(__name__)


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
    interactive: bool = True,
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
            f"or example to {DEFAULT_CLIENT_SECRET_PATH}. Missing: {mask_path(str(cfg.client_secret_path))}"
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

    def _read_token_scopes() -> list[str]:
        try:
            import json

            if not cfg.token_path.exists():
                return []
            obj = json.loads(cfg.token_path.read_text(encoding="utf-8"))
            scopes = obj.get("scopes") or obj.get("scope")
            if isinstance(scopes, str):
                out = scopes.split()
            elif isinstance(scopes, list):
                out = [str(x) for x in scopes if str(x).strip()]
            else:
                out = []
            return [s for s in out if s]
        except Exception:
            return []

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
        max_retries = 3
        for attempt in range(max_retries):
            try:
                creds.refresh(Request())
                break
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        "Token refresh failed (attempt %d/%d): %s — retrying in %ds",
                        attempt + 1, max_retries, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error("Token refresh failed after %d attempts: %s", max_retries, exc)
                    raise

    if creds is None or not getattr(creds, "valid", False):
        if not interactive:
            token_scopes = _read_token_scopes()
            scope_hint = ""
            if token_scopes:
                scope_hint = f" token_scopes={sorted(set(token_scopes))}"

            # Suggest the correct interactive auth mode based on requested scopes.
            auth_cmd = "/auth calendar"
            if any("calendar.events" in s for s in scopes):
                auth_cmd = "/auth calendar write"

            raise RuntimeError(
                "Google OAuth yetkilendirmesi gerekli (token yok/uyumsuz ya da scope yetersiz). "
                f"Takvim için '{auth_cmd}' çalıştırın veya 'bantz google auth calendar' kullanın. "
                f"client_secret={mask_path(str(cfg.client_secret_path))} token={mask_path(str(cfg.token_path))}{scope_hint}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secret_path), scopes=scopes)
        try:
            creds = flow.run_local_server(port=0, open_browser=True)
        except Exception:
            try:
                creds = flow.run_local_server(port=0, open_browser=False)
            except Exception:
                # Headless fallback.
                creds = flow.run_console()

        cfg.token_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write with file locking to prevent corruption from
        # concurrent processes reading/writing the same token file.
        token_json = creds.to_json()
        dir_str = str(cfg.token_path.parent)
        fd, tmp_path = tempfile.mkstemp(dir=dir_str, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(token_json)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_path, 0o600)  # owner-only: token grants full Google account access
            os.replace(tmp_path, str(cfg.token_path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    return creds
