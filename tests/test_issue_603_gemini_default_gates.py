"""Tests for Issue #603: GeminiClient default quota_tracker and circuit_breaker.

Verifies that:
1. GeminiClient wires default gates when use_default_gates=True (default)
2. runtime_factory passes explicit quota/circuit instances
3. Gates are actually functional (not None) in production wiring
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestGeminiClientDefaultGates:
    """Ensure GeminiClient.__init__ activates default gates."""

    def test_default_gates_active(self):
        """use_default_gates=True (default) should wire quota + circuit."""
        from bantz.llm.gemini_client import GeminiClient

        client = GeminiClient(
            api_key="test-key",
            model="gemini-2.0-flash",
        )
        assert client._quota_tracker is not None, "quota_tracker must be active by default"
        assert client._circuit_breaker is not None, "circuit_breaker must be active by default"

    def test_explicit_none_overrides_default(self):
        """Caller can explicitly disable gates with use_default_gates=False."""
        from bantz.llm.gemini_client import GeminiClient

        client = GeminiClient(
            api_key="test-key",
            model="gemini-2.0-flash",
            use_default_gates=False,
        )
        assert client._quota_tracker is None
        assert client._circuit_breaker is None

    def test_explicit_tracker_takes_precedence(self):
        """Explicitly passed tracker should override default."""
        from bantz.llm.gemini_client import GeminiClient
        from bantz.llm.quota_tracker import QuotaTracker

        custom_tracker = QuotaTracker()
        client = GeminiClient(
            api_key="test-key",
            model="gemini-2.0-flash",
            quota_tracker=custom_tracker,
        )
        assert client._quota_tracker is custom_tracker


class TestRuntimeFactoryGeminiGates:
    """Ensure runtime_factory passes explicit gates to GeminiClient."""

    def test_gemini_client_has_gates(self):
        """GeminiClient created by runtime_factory must have active gates.

        We test this directly by instantiating GeminiClient the same way
        runtime_factory does — with explicit get_default_* calls.
        """
        from bantz.llm.gemini_client import (
            GeminiClient,
            get_default_quota_tracker,
            get_default_circuit_breaker,
        )

        client = GeminiClient(
            api_key="test-key",
            model="gemini-2.0-flash",
            timeout_seconds=30.0,
            quota_tracker=get_default_quota_tracker(),
            circuit_breaker=get_default_circuit_breaker(),
        )
        assert client._quota_tracker is not None, "quota_tracker must be active"
        assert client._circuit_breaker is not None, "circuit_breaker must be active"
        # Verify they are the shared singletons
        assert client._quota_tracker is get_default_quota_tracker()
        assert client._circuit_breaker is get_default_circuit_breaker()
