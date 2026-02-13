"""Tests for bantz doctor + onboard (Issue #1223)."""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Doctor tests
# ---------------------------------------------------------------------------
from bantz.doctor import (
    CheckResult,
    _check_python_version,
    _check_env_file,
    _check_env_vars,
    _check_google_token,
    _check_dangerous_mode,
    _check_llm_endpoint,
    run_doctor,
)


class TestCheckResult:
    def test_icon_ok(self):
        assert CheckResult("t", "ok").icon == "✓"

    def test_icon_warn(self):
        assert CheckResult("t", "warn").icon == "⚠"

    def test_icon_fail(self):
        assert CheckResult("t", "fail").icon == "✗"

    def test_icon_unknown(self):
        assert CheckResult("t", "other").icon == "?"


class TestPythonVersionCheck:
    def test_passes_on_current(self):
        result = _check_python_version()
        assert result.status == "ok"

    def test_fails_on_old_version(self):
        import sys
        from collections import namedtuple
        VersionInfo = namedtuple("version_info", ["major", "minor", "micro", "releaselevel", "serial"])
        fake_vi = VersionInfo(3, 9, 0, "final", 0)
        with patch.object(sys, "version_info", fake_vi):
            # _check_python_version uses module-level sys, so patch the module attr
            import bantz.doctor as doc_mod
            orig = doc_mod.sys.version_info
            doc_mod.sys.version_info = fake_vi
            try:
                result = _check_python_version()
                assert result.status == "fail"
            finally:
                doc_mod.sys.version_info = orig


class TestEnvFileCheck:
    def test_env_exists(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("FOO=bar")
        monkeypatch.setenv("BANTZ_ENV_FILE", str(env))
        result = _check_env_file()
        assert result.status == "ok"

    def test_env_missing(self, monkeypatch):
        monkeypatch.setenv("BANTZ_ENV_FILE", "/nonexistent/.env.xxx")
        result = _check_env_file()
        assert result.status == "warn"


class TestEnvVarsCheck:
    def test_critical_set(self, monkeypatch):
        monkeypatch.setenv("BANTZ_LLM_BACKEND", "ollama")
        results = _check_env_vars()
        lbl = [r for r in results if "LLM backend" in r.name]
        assert lbl[0].status == "ok"

    def test_critical_missing(self, monkeypatch):
        monkeypatch.delenv("BANTZ_LLM_BACKEND", raising=False)
        results = _check_env_vars()
        lbl = [r for r in results if "LLM backend" in r.name]
        assert lbl[0].status == "warn"


class TestGoogleTokenCheck:
    def test_valid_token(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        cfg = home / ".config" / "bantz"
        cfg.mkdir(parents=True)
        token = cfg / "token.json"
        token.write_text(json.dumps({"refresh_token": "abc"}))
        monkeypatch.setattr(Path, "home", lambda: home)
        result = _check_google_token()
        assert result.status == "ok"

    def test_no_token(self, tmp_path, monkeypatch):
        home = tmp_path / "nope"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(tmp_path)
        result = _check_google_token()
        assert result.status == "warn"

    def test_corrupt_token(self, tmp_path, monkeypatch):
        home = tmp_path / "home2"
        cfg = home / ".config" / "bantz"
        cfg.mkdir(parents=True)
        (cfg / "token.json").write_text("NOT JSON{{{")
        monkeypatch.setattr(Path, "home", lambda: home)
        result = _check_google_token()
        assert result.status == "fail"


class TestDangerousMode:
    def test_disabled(self, monkeypatch):
        monkeypatch.delenv("BANTZ_DANGEROUS_MODE", raising=False)
        assert _check_dangerous_mode().status == "ok"

    def test_enabled(self, monkeypatch):
        monkeypatch.setenv("BANTZ_DANGEROUS_MODE", "true")
        assert _check_dangerous_mode().status == "warn"


class TestLLMEndpoint:
    def test_no_url(self, monkeypatch):
        monkeypatch.delenv("BANTZ_VLLM_URL", raising=False)
        monkeypatch.delenv("VLLM_URL", raising=False)
        result = _check_llm_endpoint()
        assert result.status == "warn"


class TestRunDoctor:
    def test_returns_zero_when_ok(self, monkeypatch, capsys):
        """Patches all checks to return ok → exit 0."""
        monkeypatch.setattr("bantz.doctor._check_python_version",
                            lambda: CheckResult("py", "ok"))
        monkeypatch.setattr("bantz.doctor._check_key_dependencies",
                            lambda: [CheckResult("dep", "ok")])
        monkeypatch.setattr("bantz.doctor._check_env_file",
                            lambda: CheckResult("env", "ok"))
        monkeypatch.setattr("bantz.doctor._check_env_vars",
                            lambda: [CheckResult("var", "ok")])
        monkeypatch.setattr("bantz.doctor._check_google_token",
                            lambda: CheckResult("oauth", "ok"))
        monkeypatch.setattr("bantz.doctor._check_llm_endpoint",
                            lambda: CheckResult("llm", "ok"))
        monkeypatch.setattr("bantz.doctor._check_tool_registry",
                            lambda: CheckResult("tools", "ok"))
        monkeypatch.setattr("bantz.doctor._check_dangerous_mode",
                            lambda: CheckResult("danger", "ok"))
        assert run_doctor() == 0

    def test_returns_one_on_failure(self, monkeypatch, capsys):
        monkeypatch.setattr("bantz.doctor._check_python_version",
                            lambda: CheckResult("py", "fail", action="fix"))
        monkeypatch.setattr("bantz.doctor._check_key_dependencies",
                            lambda: [])
        monkeypatch.setattr("bantz.doctor._check_env_file",
                            lambda: CheckResult("env", "ok"))
        monkeypatch.setattr("bantz.doctor._check_env_vars",
                            lambda: [])
        monkeypatch.setattr("bantz.doctor._check_google_token",
                            lambda: CheckResult("oauth", "ok"))
        monkeypatch.setattr("bantz.doctor._check_llm_endpoint",
                            lambda: CheckResult("llm", "ok"))
        monkeypatch.setattr("bantz.doctor._check_tool_registry",
                            lambda: CheckResult("tools", "ok"))
        monkeypatch.setattr("bantz.doctor._check_dangerous_mode",
                            lambda: CheckResult("danger", "ok"))
        assert run_doctor() == 1


# ---------------------------------------------------------------------------
# Onboard tests
# ---------------------------------------------------------------------------
from bantz.onboard import run_onboard, _step_env_check


class TestStepEnvCheck:
    def test_passes(self, tmp_path, monkeypatch):
        for d in ("artifacts/logs", "artifacts/results", "artifacts/tmp", "config"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(tmp_path)
        assert _step_env_check() is True


class TestRunOnboard:
    def test_non_interactive_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Ensure dirs exist
        for d in ("artifacts/logs", "artifacts/results", "artifacts/tmp", "config"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        # Skip google auth check
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
        monkeypatch.delenv("BANTZ_VLLM_URL", raising=False)
        monkeypatch.delenv("VLLM_URL", raising=False)
        monkeypatch.delenv("BANTZ_LLM_BACKEND", raising=False)
        result = run_onboard(non_interactive=True)
        assert result == 0
        # Should have created .env
        # (may or may not exist depending on example file)
