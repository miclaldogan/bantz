"""Tests for Issue #1014: Deprecated finalizer cleanup — no circular import."""

from __future__ import annotations

import unittest
import warnings
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestFinalizerImportSafety(unittest.TestCase):
    """Verify finalizer.py imports from tool_result_summarizer (not orchestrator_loop)."""

    def test_no_orchestrator_loop_import(self):
        """finalizer.py should NOT import from orchestrator_loop (circular risk)."""
        source = (_SRC / "brain" / "finalizer.py").read_text("utf-8")
        # The old import was: from bantz.brain.orchestrator_loop import ...
        self.assertNotIn(
            "from bantz.brain.orchestrator_loop import",
            source,
            "finalizer.py still imports from orchestrator_loop — circular risk!",
        )

    def test_imports_from_tool_result_summarizer(self):
        """finalizer.py should import _prepare_tool_results_for_finalizer from tool_result_summarizer."""
        source = (_SRC / "brain" / "finalizer.py").read_text("utf-8")
        self.assertIn("from bantz.brain.tool_result_summarizer import", source)

    def test_prepare_tool_results_callable(self):
        """_prepare_tool_results_for_finalizer should be importable and callable."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from bantz.brain.finalizer import _prepare_tool_results_for_finalizer

        result, was_truncated = _prepare_tool_results_for_finalizer([])
        self.assertEqual(result, [])
        self.assertFalse(was_truncated)

    def test_estimate_tokens_callable(self):
        """_estimate_tokens should be importable and callable."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from bantz.brain.finalizer import _estimate_tokens

        n = _estimate_tokens("hello world")
        self.assertIsInstance(n, int)
        self.assertGreater(n, 0)

    def test_deprecation_warning_emitted(self):
        """Importing finalizer should emit DeprecationWarning."""
        import importlib
        import bantz.brain.finalizer as _mod

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(_mod)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(
                len(dep_warnings) >= 1,
                "DeprecationWarning not emitted on import",
            )


if __name__ == "__main__":
    unittest.main()
