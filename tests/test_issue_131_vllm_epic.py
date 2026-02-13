"""Tests for Issue #131 — vLLM Epic closure summary.

Verifies the closure document exists and runtime factory works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestIssue131EpicClosure:
    """Verify vLLM epic closure."""

    def test_closure_doc_exists(self):
        assert (ROOT / "docs" / "issues" / "issue-131-vllm-epic-summary.md").is_file()

    def test_closure_doc_content(self):
        doc = (ROOT / "docs" / "issues" / "issue-131-vllm-epic-summary.md").read_text()
        assert "COMPLETED" in doc or "SUPERSEDED" in doc
        assert "vLLM" in doc
        assert "Hybrid" in doc or "hybrid" in doc

    def test_runtime_factory_importable(self):
        from bantz.brain.runtime_factory import create_runtime
        assert callable(create_runtime)

    def test_vllm_client_importable(self):
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient
        assert VLLMOpenAIClient is not None

    def test_llm_base_exists(self):
        from bantz.llm.base import LLMClient
        assert LLMClient is not None

    def test_no_ollama_imports(self):
        """Verify Ollama was fully purged."""
        import os
        src_dir = ROOT / "src" / "bantz"
        ollama_refs = []
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(errors="ignore")
            if "import ollama" in content or "from ollama" in content:
                ollama_refs.append(str(py_file))
        assert ollama_refs == [], f"Ollama imports found in: {ollama_refs}"
