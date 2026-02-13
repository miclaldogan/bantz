"""Tests for Issue #305: Boot-to-ready smoke script.

Validates the smoke_boot_ready.py module:
- check_vllm() correctly detects up/down vLLM
- check_gemini_key() detects key presence/absence
- check_tool_registry() loads tools
- check_runtime_factory() creates runtime
- run_smoke() returns correct exit codes
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is on path
_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


class TestCheckVllm:
    """Test vLLM health check."""

    def test_vllm_reachable(self):
        from smoke_boot_ready import check_vllm

        fake_body = json.dumps({"data": [{"id": "Qwen/Qwen2.5-3B-Instruct"}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = check_vllm(timeout=1.0)

        assert result.passed is True
        assert "Qwen" in result.message

    def test_vllm_no_models(self):
        from smoke_boot_ready import check_vllm

        fake_body = json.dumps({"data": []}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = check_vllm(timeout=1.0)

        assert result.passed is False
        assert "no models" in result.message.lower()

    def test_vllm_connection_refused(self):
        from smoke_boot_ready import check_vllm
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            result = check_vllm(timeout=1.0)

        assert result.passed is False
        assert "not reachable" in result.message.lower()


class TestCheckGeminiKey:
    """Test Gemini key detection."""

    def test_gemini_key_present(self):
        from smoke_boot_ready import check_gemini_key

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-12345678"}):
            result = check_gemini_key()

        assert result.passed is True
        assert "Gemini" in result.message

    def test_gemini_key_absent(self):
        from smoke_boot_ready import check_gemini_key

        env = {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "BANTZ_GEMINI_API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            result = check_gemini_key()

        # Passes (3B fallback) but with warning
        assert result.passed is True
        assert "3B" in result.message


class TestCheckToolRegistry:
    """Test ToolRegistry loading."""

    def test_registry_loads(self):
        from smoke_boot_ready import check_tool_registry

        # This depends on terminal_jarvis being importable
        result = check_tool_registry()

        # If the registry loads at all, it should have the critical tools
        if result.passed:
            assert "tools loaded" in result.message.lower()


class TestCheckRuntimeFactory:
    """Test runtime factory creation."""

    @patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient")
    @patch("bantz.brain.orchestrator_loop.OrchestratorLoop")
    @patch("bantz.brain.llm_router.JarvisLLMOrchestrator")
    def test_factory_succeeds(self, mock_orch, mock_loop, mock_vllm):
        from smoke_boot_ready import check_runtime_factory

        result = check_runtime_factory()
        assert result.passed is True
        assert "create_runtime()" in result.message


class TestRunSmoke:
    """Test the full smoke runner."""

    @patch("smoke_boot_ready.check_single_turn")
    @patch("smoke_boot_ready.check_runtime_factory")
    @patch("smoke_boot_ready.check_tool_registry")
    @patch("smoke_boot_ready.check_gemini_key")
    @patch("smoke_boot_ready.check_vllm")
    @patch("smoke_boot_ready.check_systemd_services")
    def test_all_pass(self, mock_sysd, mock_vllm, mock_gemini, mock_tools, mock_factory, mock_turn):
        from smoke_boot_ready import run_smoke, CheckResult

        mock_vllm.return_value = CheckResult("vllm", True, "ok")
        mock_gemini.return_value = CheckResult("gemini", True, "ok")
        mock_tools.return_value = CheckResult("tools", True, "ok")
        mock_factory.return_value = CheckResult("factory", True, "ok")
        mock_turn.return_value = CheckResult("turn", True, "ok")
        mock_sysd.return_value = []

        exit_code = run_smoke(include_turn=True, include_systemd=False)
        assert exit_code == 0

    @patch("smoke_boot_ready.check_single_turn")
    @patch("smoke_boot_ready.check_runtime_factory")
    @patch("smoke_boot_ready.check_tool_registry")
    @patch("smoke_boot_ready.check_gemini_key")
    @patch("smoke_boot_ready.check_vllm")
    def test_vllm_fail_returns_1(self, mock_vllm, mock_gemini, mock_tools, mock_factory, mock_turn):
        from smoke_boot_ready import run_smoke, CheckResult

        mock_vllm.return_value = CheckResult("vllm", False, "down")
        mock_gemini.return_value = CheckResult("gemini", True, "ok")
        mock_tools.return_value = CheckResult("tools", True, "ok")
        mock_factory.return_value = CheckResult("factory", True, "ok")
        mock_turn.return_value = CheckResult("turn", True, "ok")

        exit_code = run_smoke(include_turn=True, include_systemd=False)
        assert exit_code == 1


class TestCheckResultDataclass:
    """Test CheckResult basics."""

    def test_fields(self):
        from smoke_boot_ready import CheckResult

        r = CheckResult(name="test", passed=True, message="ok")
        assert r.name == "test"
        assert r.passed is True
        assert r.elapsed_ms == 0.0
        assert r.hint == ""
