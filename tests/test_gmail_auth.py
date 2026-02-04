from __future__ import annotations

from pathlib import Path
import json

import pytest


def test_get_gmail_auth_config_defaults(monkeypatch, tmp_path: Path):
    from bantz.google import gmail_auth

    monkeypatch.delenv("BANTZ_GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BANTZ_GMAIL_TOKEN_PATH", raising=False)
    monkeypatch.delenv("BANTZ_GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("BANTZ_GOOGLE_GMAIL_TOKEN_PATH", raising=False)

    cfg = gmail_auth.get_gmail_auth_config()

    assert str(cfg.client_secret_path).endswith(".config/bantz/google/client_secret_gmail.json")
    assert str(cfg.token_path).endswith(".config/bantz/google/gmail_token.json")


def test_normalize_gmail_scopes_supports_short_forms():
    from bantz.google.gmail_auth import _normalize_gmail_scopes

    scopes = _normalize_gmail_scopes(["gmail.readonly", "gmail.metadata"])
    assert scopes == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.metadata",
    ]


def test_scope_escalation_forces_reconsent(monkeypatch, tmp_path: Path):
    from bantz.google import gmail_auth

    secret = tmp_path / "client_secret_gmail.json"
    token = tmp_path / "gmail_token.json"

    # Minimal client secret JSON shape accepted by InstalledAppFlow in real life,
    # but in tests we stub the flow so content doesn't matter.
    secret.write_text("{}", encoding="utf-8")

    class DummyCreds:
        def __init__(self, *, scopes: list[str], valid: bool = True, expired: bool = False):
            self.scopes = scopes
            self.valid = valid
            self.expired = expired
            self.refresh_token = "rtok"

        def has_scopes(self, scopes: list[str]) -> bool:
            return set(scopes).issubset(set(self.scopes))

        def refresh(self, _request):
            self.expired = False
            self.valid = True

        def to_json(self) -> str:
            return json.dumps({"scopes": self.scopes})

    # Token exists but is read-only.
    token.write_text(
        json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}),
        encoding="utf-8",
    )

    class DummyCredentials:
        @staticmethod
        def from_authorized_user_file(_path: str, scopes=None):
            _ = scopes
            return DummyCreds(scopes=["https://www.googleapis.com/auth/gmail.readonly"], valid=True)

    class DummyFlow:
        def __init__(self, scopes: list[str]):
            self._scopes = scopes

        def run_local_server(self, port=0, open_browser=False):
            return DummyCreds(scopes=list(self._scopes), valid=True)

        def run_console(self):
            return DummyCreds(scopes=list(self._scopes), valid=True)

    class DummyInstalledAppFlow:
        @staticmethod
        def from_client_secrets_file(_path: str, scopes: list[str]):
            return DummyFlow(scopes)

    def fake_import_deps():
        class DummyRequest:  # noqa: D401
            """Placeholder."""

        def dummy_build(*_args, **_kwargs):
            raise AssertionError("build() should not be called from get_gmail_credentials")

        return DummyRequest, DummyCredentials, DummyInstalledAppFlow, dummy_build

    monkeypatch.setattr(gmail_auth, "_import_google_deps", fake_import_deps)

    creds = gmail_auth.get_gmail_credentials(
        scopes=["https://www.googleapis.com/auth/gmail.send"],
        client_secret_path=str(secret),
        token_path=str(token),
    )

    assert "https://www.googleapis.com/auth/gmail.send" in getattr(creds, "scopes", [])


def test_token_refresh_when_expired(monkeypatch, tmp_path: Path):
    from bantz.google import gmail_auth

    secret = tmp_path / "client_secret_gmail.json"
    token = tmp_path / "gmail_token.json"
    secret.write_text("{}", encoding="utf-8")
    token.write_text(json.dumps({"dummy": True}), encoding="utf-8")

    refreshed = {"called": 0}

    class DummyCreds:
        def __init__(self):
            self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
            self.valid = True
            self.expired = True
            self.refresh_token = "rtok"

        def has_scopes(self, scopes: list[str]) -> bool:
            return True

        def refresh(self, _request):
            refreshed["called"] += 1
            self.expired = False
            self.valid = True

        def to_json(self) -> str:
            return json.dumps({"scopes": self.scopes})

    class DummyCredentials:
        @staticmethod
        def from_authorized_user_file(_path: str, scopes=None):
            _ = scopes
            return DummyCreds()

    class DummyInstalledAppFlow:
        @staticmethod
        def from_client_secrets_file(_path: str, scopes: list[str]):
            raise AssertionError("Flow should not be called when refresh works")

    def fake_import_deps():
        class DummyRequest:  # noqa: D401
            """Placeholder."""

        def dummy_build(*_args, **_kwargs):
            raise AssertionError("build() should not be called from get_gmail_credentials")

        return DummyRequest, DummyCredentials, DummyInstalledAppFlow, dummy_build

    monkeypatch.setattr(gmail_auth, "_import_google_deps", fake_import_deps)

    creds = gmail_auth.get_gmail_credentials(
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        client_secret_path=str(secret),
        token_path=str(token),
    )

    assert refreshed["called"] == 1
    assert getattr(creds, "expired", True) is False
