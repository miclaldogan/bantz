# SPDX-License-Identifier: MIT
"""Issue #657: create_fast_client default model must be vLLM/HF ID."""

from bantz.llm import create_fast_client


def test_create_fast_client_default_model(monkeypatch):
    monkeypatch.delenv("BANTZ_VLLM_MODEL", raising=False)

    client = create_fast_client()
    assert client.backend_name == "vllm"
    assert client.model_name == "Qwen/Qwen2.5-3B-Instruct-AWQ"
