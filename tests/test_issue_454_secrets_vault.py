"""Tests for issue #454 — Secrets Vault v0."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bantz.security.secret_vault import (
    SecretVault,
    redact_secrets,
    scan_for_leaks,
)


# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture()
def vault(tmp_path):
    """Vault backed by a temporary directory."""
    return SecretVault(base_dir=str(tmp_path), passphrase="test-pass-123")


# ── TestGetSetDelete ──────────────────────────────────────────────────

class TestGetSetDelete:
    def test_set_and_get(self, vault):
        vault.set("MY_KEY", "my_value")
        assert vault.get("MY_KEY") == "my_value"

    def test_get_missing_returns_none(self, vault):
        assert vault.get("NONEXISTENT") is None

    def test_delete(self, vault):
        vault.set("K", "V")
        assert vault.delete("K")
        assert vault.get("K") is None

    def test_delete_nonexistent(self, vault):
        assert not vault.delete("NOPE")

    def test_exists(self, vault):
        vault.set("API_KEY", "abc")
        assert vault.exists("API_KEY")
        assert not vault.exists("NOPE")


# ── TestListKeys ──────────────────────────────────────────────────────

class TestListKeys:
    def test_list_keys(self, vault):
        vault.set("A", "1")
        vault.set("B", "2")
        keys = vault.list_keys()
        assert "A" in keys
        assert "B" in keys

    def test_list_keys_includes_env(self, vault, monkeypatch):
        monkeypatch.setenv("BANTZ_SECRET_ENV_KEY", "env_val")
        keys = vault.list_keys()
        assert "ENV_KEY" in keys


# ── TestEnvFallback ───────────────────────────────────────────────────

class TestEnvFallback:
    def test_env_var_fallback(self, vault, monkeypatch):
        monkeypatch.setenv("BANTZ_SECRET_GOOGLE_API_KEY", "from-env")
        assert vault.get("GOOGLE_API_KEY") == "from-env"

    def test_vault_overrides_env(self, vault, monkeypatch):
        monkeypatch.setenv("BANTZ_SECRET_K", "env-val")
        vault.set("K", "vault-val")
        assert vault.get("K") == "vault-val"


# ── TestPersistence ───────────────────────────────────────────────────

class TestPersistence:
    def test_round_trip(self, tmp_path):
        v1 = SecretVault(base_dir=str(tmp_path), passphrase="pw")
        v1.set("TOKEN", "secret123")

        v2 = SecretVault(base_dir=str(tmp_path), passphrase="pw")
        assert v2.get("TOKEN") == "secret123"

    def test_wrong_passphrase_graceful(self, tmp_path):
        v1 = SecretVault(base_dir=str(tmp_path), passphrase="pw1")
        v1.set("X", "Y")

        # Wrong passphrase — should not crash, just fail to load
        v2 = SecretVault(base_dir=str(tmp_path), passphrase="wrong-pw")
        # Depending on encryption scheme, may or may not load
        # The important thing is no exception
        assert isinstance(v2.list_keys(), list)

    def test_file_permissions(self, tmp_path):
        v = SecretVault(base_dir=str(tmp_path), passphrase="pw")
        v.set("K", "V")
        # Check that at least one secrets file has restricted permissions
        enc = tmp_path / "secrets.enc"
        plain = tmp_path / "secrets.json"
        if enc.exists():
            mode = oct(enc.stat().st_mode)[-3:]
            assert mode == "600"
        elif plain.exists():
            mode = oct(plain.stat().st_mode)[-3:]
            assert mode == "600"


# ── TestRotation ──────────────────────────────────────────────────────

class TestRotation:
    def test_rotate_returns_old(self, vault):
        vault.set("TOKEN", "old_val")
        old = vault.rotate("TOKEN", "new_val")
        assert old == "old_val"
        assert vault.get("TOKEN") == "new_val"

    def test_rotate_new_key(self, vault):
        old = vault.rotate("NEW_KEY", "val")
        assert old is None
        assert vault.get("NEW_KEY") == "val"


# ── TestImportEnv ─────────────────────────────────────────────────────

class TestImportEnv:
    def test_import_all(self, vault, monkeypatch):
        monkeypatch.setenv("BANTZ_SECRET_A", "1")
        monkeypatch.setenv("BANTZ_SECRET_B", "2")
        count = vault.import_env()
        assert count >= 2
        assert vault.get("A") == "1"
        assert vault.get("B") == "2"

    def test_import_specific(self, vault, monkeypatch):
        monkeypatch.setenv("BANTZ_SECRET_X", "10")
        monkeypatch.setenv("BANTZ_SECRET_Y", "20")
        count = vault.import_env(keys=["X"])
        assert count == 1
        assert vault.get("X") == "10"


# ── TestLeakDetection ────────────────────────────────────────────────

class TestLeakDetection:
    def test_scan_finds_leak(self):
        secrets = {"super_secret_123", "api_key_456"}
        leaks = scan_for_leaks("Log: connected with super_secret_123", secrets)
        assert "super_secret_123" in leaks

    def test_scan_no_leak(self):
        secrets = {"my_secret"}
        leaks = scan_for_leaks("Log: all good here", secrets)
        assert leaks == []

    def test_redact_secrets(self):
        result = redact_secrets("token=abc1234", {"abc1234"})
        assert "abc1234" not in result
        assert "[REDACTED]" in result

    def test_short_secrets_skipped(self):
        # Secrets < 4 chars are not scanned (too many false positives)
        leaks = scan_for_leaks("a=1", {"1"})
        assert leaks == []


# ── TestGoldenLeakSafety ──────────────────────────────────────────────

class TestGoldenLeakSafety:
    def test_vault_values_not_in_list_keys(self, vault):
        vault.set("GOOGLE_API_KEY", "AIzaSyB-FAKE-KEY-123")
        keys = vault.list_keys()
        for k in keys:
            assert "AIzaSyB" not in k

    def test_leak_scan_integration(self, vault):
        vault.set("TOKEN", "sk_live_secret_value_xyz")
        all_vals = vault.get_all_values()
        log_line = "INFO: Authenticated with sk_live_secret_value_xyz"
        leaks = scan_for_leaks(log_line, all_vals)
        assert len(leaks) == 1
        cleaned = redact_secrets(log_line, all_vals)
        assert "sk_live_secret_value_xyz" not in cleaned
