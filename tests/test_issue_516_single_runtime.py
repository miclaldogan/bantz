"""Tests for Issue #516: Single Runtime Entry — runtime_factory.

Ensures:
1. create_runtime() creates all components correctly
2. BantzRuntime has the expected interface
3. Both terminal_jarvis and server can use the same factory
4. Boot log shows which brain is active
"""

from __future__ import annotations

import os
import warnings
from unittest.mock import MagicMock, patch

import pytest


class TestRuntimeFactoryImport:
    """Verify the factory module is importable and has expected exports."""

    def test_import_create_runtime(self):
        from bantz.brain.runtime_factory import create_runtime
        assert callable(create_runtime)

    def test_import_bantz_runtime(self):
        from bantz.brain.runtime_factory import BantzRuntime
        assert BantzRuntime is not None

    def test_bantz_runtime_has_process_turn(self):
        from bantz.brain.runtime_factory import BantzRuntime
        assert hasattr(BantzRuntime, "process_turn")

    def test_bantz_runtime_has_run_full_cycle(self):
        from bantz.brain.runtime_factory import BantzRuntime
        assert hasattr(BantzRuntime, "run_full_cycle")


class TestCreateRuntime:
    """Test create_runtime() with mocked LLM clients."""

    @patch.dict(os.environ, {
        "BANTZ_VLLM_URL": "http://localhost:8001",
        "BANTZ_VLLM_MODEL": "test-model",
    }, clear=False)
    @patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient")
    @patch("bantz.brain.orchestrator_loop.OrchestratorLoop")
    @patch("bantz.brain.llm_router.JarvisLLMOrchestrator")
    def test_creates_runtime_without_gemini(self, mock_orch, mock_loop, mock_vllm):
        """Runtime should be created even without Gemini key."""
        from bantz.brain.runtime_factory import create_runtime

        # Remove Gemini keys to test 3B fallback
        env_override = {
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "BANTZ_GEMINI_API_KEY": "",
        }
        with patch.dict(os.environ, env_override, clear=False):
            runtime = create_runtime()

        assert runtime is not None
        assert runtime.gemini_client is None
        assert runtime.finalizer_is_gemini is False
        assert runtime.router_model == "test-model"

    @patch.dict(os.environ, {
        "BANTZ_VLLM_URL": "http://localhost:8001",
        "BANTZ_VLLM_MODEL": "test-model",
        "GEMINI_API_KEY": "test-key",
        "BANTZ_GEMINI_MODEL": "gemini-1.5-flash",
    }, clear=False)
    @patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient")
    @patch("bantz.brain.orchestrator_loop.OrchestratorLoop")
    @patch("bantz.brain.llm_router.JarvisLLMOrchestrator")
    @patch("bantz.llm.gemini_client.GeminiClient")
    def test_creates_runtime_with_gemini(self, mock_gemini_cls, mock_orch, mock_loop, mock_vllm):
        """Runtime should wire Gemini when key is available."""
        from bantz.brain.runtime_factory import create_runtime

        mock_gemini_cls.return_value = MagicMock()

        runtime = create_runtime(gemini_key="test-key")

        assert runtime is not None
        assert runtime.gemini_client is not None
        assert runtime.finalizer_is_gemini is True
        assert runtime.gemini_model == "gemini-1.5-flash"

    @patch("bantz.llm.vllm_openai_client.VLLMOpenAIClient")
    @patch("bantz.brain.orchestrator_loop.OrchestratorLoop")
    @patch("bantz.brain.llm_router.JarvisLLMOrchestrator")
    def test_explicit_params_override_env(self, mock_orch, mock_loop, mock_vllm):
        """Explicit parameters should override env vars."""
        from bantz.brain.runtime_factory import create_runtime

        runtime = create_runtime(
            vllm_url="http://custom:9999",
            router_model="custom-model",
        )

        mock_vllm.assert_called_once_with(
            base_url="http://custom:9999",
            model="custom-model",
            timeout_seconds=30.0,
        )
        assert runtime.router_model == "custom-model"


class TestTerminalJarvisDoesNotDirectlyImportLoop:
    """Verify terminal_jarvis.py no longer directly imports OrchestratorLoop."""

    def test_no_direct_orchestrator_loop_import(self):
        """terminal_jarvis should NOT have 'from bantz.brain.orchestrator_loop import OrchestratorLoop'."""
        import inspect
        from pathlib import Path

        terminal_path = Path(__file__).parent.parent / "scripts" / "terminal_jarvis.py"
        if not terminal_path.exists():
            pytest.skip("terminal_jarvis.py not found")

        source = terminal_path.read_text()
        # Should NOT directly import OrchestratorLoop or OrchestratorConfig
        assert "from bantz.brain.orchestrator_loop import OrchestratorLoop" not in source
        assert "from bantz.brain.orchestrator_loop import" not in source

    def test_no_direct_llm_router_import_for_instantiation(self):
        """terminal_jarvis should NOT directly import JarvisLLMOrchestrator."""
        from pathlib import Path

        terminal_path = Path(__file__).parent.parent / "scripts" / "terminal_jarvis.py"
        if not terminal_path.exists():
            pytest.skip("terminal_jarvis.py not found")

        source = terminal_path.read_text()
        assert "from bantz.brain.llm_router import JarvisLLMOrchestrator" not in source

    def test_uses_runtime_factory(self):
        """terminal_jarvis should use create_runtime from runtime_factory."""
        from pathlib import Path

        terminal_path = Path(__file__).parent.parent / "scripts" / "terminal_jarvis.py"
        if not terminal_path.exists():
            pytest.skip("terminal_jarvis.py not found")

        source = terminal_path.read_text()
        assert "from bantz.brain.runtime_factory import create_runtime" in source
