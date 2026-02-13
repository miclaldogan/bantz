from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os

from bantz.security.secrets import mask_path


DEFAULT_SERVICE_ACCOUNT_PATH = "~/.config/bantz/google/service_account.json"


@dataclass(frozen=True)
class GoogleServiceAccountConfig:
    service_account_path: Path


def _resolve_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def get_google_service_account_config(
    *,
    service_account_path: Optional[str] = None,
) -> GoogleServiceAccountConfig:
    # Prefer standard GCP env var, but allow a Bantz-specific override.
    env_path = os.getenv("BANTZ_GOOGLE_SERVICE_ACCOUNT") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    raw = service_account_path or env_path or DEFAULT_SERVICE_ACCOUNT_PATH
    return GoogleServiceAccountConfig(service_account_path=_resolve_path(raw))


def get_service_account_credentials(
    *,
    scopes: list[str],
    service_account_path: Optional[str] = None,
):
    """Return Google service-account credentials.

    Reads path from env vars by default:
    - BANTZ_GOOGLE_SERVICE_ACCOUNT
    - GOOGLE_APPLICATION_CREDENTIALS

    Falls back to: ~/.config/bantz/google/service_account.json

    Lazy-imports google-auth so repo can run without vision deps.
    """

    cfg = get_google_service_account_config(service_account_path=service_account_path)
    if not cfg.service_account_path.exists():
        raise FileNotFoundError(
            "Google service account JSON not found. Set BANTZ_GOOGLE_SERVICE_ACCOUNT or "
            "GOOGLE_APPLICATION_CREDENTIALS, or place the file at "
            f"{DEFAULT_SERVICE_ACCOUNT_PATH}. Missing: {mask_path(str(cfg.service_account_path))}"
        )

    try:
        from google.oauth2 import service_account  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google auth dependencies are not installed. Install with: pip install -e '.[vision]'"
        ) from e

    return service_account.Credentials.from_service_account_file(str(cfg.service_account_path), scopes=scopes)
