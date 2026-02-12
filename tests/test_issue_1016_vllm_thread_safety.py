"""Tests for Issue #1016: vLLM client thread safety."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestVLLMThreadSafety(unittest.TestCase):
    """Thread safety for model auto-resolution and client lazy init."""

    def test_has_lock_attribute(self):
        """VLLMOpenAIClient should have a threading.Lock."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn("threading.Lock()", source)
        self.assertIn("self._lock", source)

    def test_resolve_auto_model_method_exists(self):
        """_resolve_auto_model should be defined."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn("def _resolve_auto_model(self)", source)

    def test_get_client_double_check_locking(self):
        """_get_client should use double-checked locking pattern."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        # Find _get_client method — should have 'with self._lock'
        idx = source.find("def _get_client(")
        self.assertGreater(idx, -1)
        block = source[idx:idx + 500]
        self.assertIn("with self._lock", block)

    def test_no_inline_auto_resolution(self):
        """chat_detailed and chat_stream should not have inline auto-resolution."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        # After _resolve_auto_model extraction, chat_detailed and chat_stream
        # should call _resolve_auto_model() instead of inline checks.
        for method_name in ("def chat_detailed(", "def chat_stream("):
            idx = source.find(method_name)
            self.assertGreater(idx, -1, f"{method_name} not found")
            block = source[idx:idx + 1200]
            self.assertIn("_resolve_auto_model()", block)
            self.assertNotIn("list_available_models", block)

    def test_resolve_auto_model_uses_lock(self):
        """_resolve_auto_model should use self._lock."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        idx = source.find("def _resolve_auto_model(")
        self.assertGreater(idx, -1)
        block = source[idx:idx + 500]
        self.assertIn("with self._lock", block)

    def test_concurrent_resolve_auto_model(self):
        """Multiple threads calling _resolve_auto_model should not race."""
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient

        client = VLLMOpenAIClient(model="auto")
        resolve_count = {"calls": 0}

        def mock_list_models(timeout_seconds=2.0):
            resolve_count["calls"] += 1
            return ["Qwen/Qwen2.5-3B-Instruct-AWQ"]

        client.list_available_models = mock_list_models

        threads = []
        for _ in range(10):
            t = threading.Thread(target=client._resolve_auto_model)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Model should be resolved
        self.assertEqual(client.model, "Qwen/Qwen2.5-3B-Instruct-AWQ")
        # Due to double-checked locking, list_available_models should be called
        # at most once (the first thread resolves, others skip)
        self.assertEqual(resolve_count["calls"], 1)

    def test_api_key_from_env(self):
        """_get_client should read VLLM_API_KEY from environment."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn('os.getenv("VLLM_API_KEY"', source)


if __name__ == "__main__":
    unittest.main()
