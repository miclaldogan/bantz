"""Tests for Issue #1020: vLLM configurable model name and API key."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestVLLMConfigurableDefaults(unittest.TestCase):
    """Model name and API key should be configurable via env vars."""

    def test_model_from_env(self):
        """VLLM_MODEL env var should override default."""
        with patch.dict(os.environ, {"VLLM_MODEL": "meta/Llama-3.2-8B"}):
            from bantz.llm.vllm_openai_client import VLLMOpenAIClient
            client = VLLMOpenAIClient()
            self.assertEqual(client.model, "meta/Llama-3.2-8B")

    def test_base_url_from_env(self):
        """VLLM_BASE_URL env var should override default."""
        with patch.dict(os.environ, {"VLLM_BASE_URL": "http://gpu-server:8080"}):
            from bantz.llm.vllm_openai_client import VLLMOpenAIClient
            client = VLLMOpenAIClient()
            self.assertEqual(client.base_url, "http://gpu-server:8080")

    def test_constructor_arg_overrides_env(self):
        """Explicit constructor arg should take precedence over env var."""
        with patch.dict(os.environ, {"VLLM_MODEL": "env-model", "VLLM_BASE_URL": "http://env:1234"}):
            from bantz.llm.vllm_openai_client import VLLMOpenAIClient
            client = VLLMOpenAIClient(model="explicit-model", base_url="http://explicit:5678")
            self.assertEqual(client.model, "explicit-model")
            self.assertEqual(client.base_url, "http://explicit:5678")

    def test_default_fallback(self):
        """Without env vars, defaults should be used."""
        env = {k: v for k, v in os.environ.items() if k not in ("VLLM_MODEL", "VLLM_BASE_URL")}
        with patch.dict(os.environ, env, clear=True):
            from bantz.llm.vllm_openai_client import VLLMOpenAIClient
            client = VLLMOpenAIClient()
            self.assertEqual(client.model, "Qwen/Qwen2.5-3B-Instruct-AWQ")
            self.assertEqual(client.base_url, "http://127.0.0.1:8001")

    def test_api_key_from_env(self):
        """VLLM_API_KEY env var should be picked up in _get_client."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn('os.getenv("VLLM_API_KEY"', source)

    def test_source_uses_os_getenv_for_model(self):
        """Source should use os.getenv for VLLM_MODEL."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn('os.getenv("VLLM_MODEL"', source)

    def test_source_uses_os_getenv_for_base_url(self):
        """Source should use os.getenv for VLLM_BASE_URL."""
        source = (_SRC / "llm" / "vllm_openai_client.py").read_text("utf-8")
        self.assertIn('os.getenv("VLLM_BASE_URL"', source)


if __name__ == "__main__":
    unittest.main()
