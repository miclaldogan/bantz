"""Tests for Issue #439 — Quality Gating Thread Safety.

Covers:
- GeminiAvailabilityGate circuit breaker
- Thread-safe atomic counters
- Config-driven score weights
- GatingPolicy thread-safe _record_decision
- Concurrent access correctness
"""

from __future__ import annotations

import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from bantz.brain.quality_gating import (
    GatingDecision,
    GatingPolicy,
    GatingResult,
    GeminiAvailabilityGate,
    PolicyConfig,
    QualityRateLimiter,
    QualityScore,
)


# ─── GeminiAvailabilityGate ─────────────────────────────────────


class TestGeminiAvailabilityGate:
    def test_initially_available(self):
        gate = GeminiAvailabilityGate(failure_threshold=3)
        assert gate.is_available
        assert gate.state == "closed"

    def test_stays_available_below_threshold(self):
        gate = GeminiAvailabilityGate(failure_threshold=3)
        gate.record_failure()
        gate.record_failure()
        assert gate.is_available
        assert gate.state == "closed"

    def test_opens_at_threshold(self):
        gate = GeminiAvailabilityGate(failure_threshold=3, cooldown_seconds=60.0)
        gate.record_failure()
        gate.record_failure()
        gate.record_failure()
        assert not gate.is_available
        assert gate.state == "open"

    def test_success_resets_failures(self):
        gate = GeminiAvailabilityGate(failure_threshold=3)
        gate.record_failure()
        gate.record_failure()
        gate.record_success()
        gate.record_failure()
        assert gate.is_available  # only 1 consecutive failure

    def test_half_open_after_cooldown(self):
        gate = GeminiAvailabilityGate(failure_threshold=2, cooldown_seconds=0.05)
        gate.record_failure()
        gate.record_failure()
        assert not gate.is_available
        time.sleep(0.06)
        assert gate.is_available
        assert gate.state == "half-open"

    def test_reset(self):
        gate = GeminiAvailabilityGate(failure_threshold=1)
        gate.record_failure()
        assert not gate.is_available
        gate.reset()
        assert gate.is_available

    def test_stats(self):
        gate = GeminiAvailabilityGate(failure_threshold=2, cooldown_seconds=60.0)
        gate.record_failure()
        gate.record_failure()
        stats = gate.get_stats()
        assert stats["state"] == "open"
        assert stats["consecutive_failures"] == 2
        assert stats["total_trips"] == 1

    def test_multiple_trips_counted(self):
        gate = GeminiAvailabilityGate(failure_threshold=1, cooldown_seconds=0.01)
        gate.record_failure()
        assert gate.get_stats()["total_trips"] == 1
        gate.record_success()  # reset
        gate.record_failure()
        assert gate.get_stats()["total_trips"] == 2


# ─── Config-driven weights ──────────────────────────────────────


class TestConfigDrivenWeights:
    def test_default_weights_in_config(self):
        cfg = PolicyConfig()
        assert cfg.score_weights["complexity"] == 0.35
        assert cfg.score_weights["writing"] == 0.45
        assert cfg.score_weights["risk"] == 0.20

    def test_custom_weights_in_config(self):
        cfg = PolicyConfig(score_weights={"complexity": 0.5, "writing": 0.3, "risk": 0.2})
        assert cfg.score_weights["complexity"] == 0.5

    def test_env_weights_parsing(self):
        with patch.dict("os.environ", {"BANTZ_SCORE_WEIGHTS": "complexity=0.5,writing=0.3,risk=0.2"}):
            cfg = PolicyConfig.from_env()
            assert cfg.score_weights["complexity"] == 0.5
            assert cfg.score_weights["writing"] == 0.3

    def test_env_weights_empty_uses_defaults(self):
        with patch.dict("os.environ", {"BANTZ_SCORE_WEIGHTS": ""}, clear=False):
            cfg = PolicyConfig.from_env()
            assert cfg.score_weights["complexity"] == 0.35

    def test_policy_uses_config_weights(self):
        """Policy should pass config weights to score computation."""
        cfg = PolicyConfig(
            score_weights={"complexity": 0.9, "writing": 0.05, "risk": 0.05},
            finalizer_mode="auto",
        )
        policy = GatingPolicy(config=cfg)
        # We just verify policy is created and works with custom weights
        # (actual scoring depends on tiered module mock)
        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock_compute:
            mock_compute.return_value = QualityScore(
                complexity=1, writing=1, risk=1, total=1.0
            )
            result = policy.evaluate("test input")
            # Verify weights were passed
            call_kwargs = mock_compute.call_args[1]
            assert call_kwargs["weights"]["complexity"] == 0.9


# ─── Thread-safe atomic counters ────────────────────────────────


class TestAtomicCounters:
    def test_counters_increment(self):
        cfg = PolicyConfig(finalizer_mode="auto")
        policy = GatingPolicy(config=cfg)

        # Mock score computation
        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock:
            # Fast decision
            mock.return_value = QualityScore(complexity=0, writing=0, risk=0, total=0.0)
            policy.evaluate("merhaba")

            # Quality decision
            mock.return_value = QualityScore(complexity=5, writing=5, risk=5, total=5.0)
            policy.evaluate("resmi email yaz")

        stats = policy.get_stats()
        assert stats["fast_count"] >= 1
        assert stats["quality_count"] >= 1
        assert stats["total_decisions"] >= 2

    def test_counters_reset(self):
        cfg = PolicyConfig(finalizer_mode="never")
        policy = GatingPolicy(config=cfg)
        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock:
            mock.return_value = QualityScore(complexity=0, writing=0, risk=0, total=0.0)
            policy.evaluate("test")
        assert policy.get_stats()["total_decisions"] == 1
        policy.reset_stats()
        assert policy.get_stats()["total_decisions"] == 0


# ─── Gemini gate integration in GatingPolicy ────────────────────


class TestGeminiGateIntegration:
    def test_gemini_unavailable_forces_fast(self):
        cfg = PolicyConfig(finalizer_mode="always")
        policy = GatingPolicy(config=cfg)
        # Trip the gate
        policy.gemini_gate = GeminiAvailabilityGate(failure_threshold=1, cooldown_seconds=60)
        policy.gemini_gate.record_failure()

        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock:
            mock.return_value = QualityScore(complexity=5, writing=5, risk=5, total=5.0)
            result = policy.evaluate("resmi email yaz")
        assert result.decision == GatingDecision.USE_FAST
        assert result.reason == "gemini_unavailable"

    def test_gemini_available_allows_quality(self):
        cfg = PolicyConfig(finalizer_mode="always")
        policy = GatingPolicy(config=cfg)
        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock:
            mock.return_value = QualityScore(complexity=5, writing=5, risk=5, total=5.0)
            result = policy.evaluate("resmi email yaz")
        assert result.decision == GatingDecision.USE_QUALITY

    def test_gemini_gate_stats_in_policy_stats(self):
        policy = GatingPolicy()
        stats = policy.get_stats()
        assert "gemini_gate" in stats
        assert stats["gemini_gate"]["state"] == "closed"


# ─── Thread safety under concurrent access ──────────────────────


class TestConcurrentAccess:
    def test_concurrent_evaluations(self):
        """Multiple threads evaluating simultaneously should not corrupt state."""
        cfg = PolicyConfig(finalizer_mode="never")
        policy = GatingPolicy(config=cfg)
        errors = []
        n_threads = 10
        n_per_thread = 20

        original_compute = QualityScore.compute

        def fake_compute(text, **kwargs):
            return QualityScore(complexity=1, writing=1, risk=1, total=1.0)

        def worker():
            try:
                for _ in range(n_per_thread):
                    policy.evaluate("concurrent test")
            except Exception as e:
                errors.append(e)

        with patch.object(QualityScore, "compute", side_effect=fake_compute):
            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(errors) == 0
        stats = policy.get_stats()
        assert stats["total_decisions"] == n_threads * n_per_thread

    def test_concurrent_rate_limiter(self):
        """Rate limiter should be thread-safe under concurrent access."""
        rl = QualityRateLimiter(max_requests=50, window_seconds=60.0)
        errors = []
        acquired = []
        lock = threading.Lock()

        def worker():
            try:
                for _ in range(10):
                    result = rl.acquire()
                    with lock:
                        acquired.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(acquired) == 100
        # First 50 should succeed, rest blocked
        assert sum(1 for a in acquired if a) == 50

    def test_concurrent_gemini_gate(self):
        """GeminiAvailabilityGate should be thread-safe."""
        gate = GeminiAvailabilityGate(failure_threshold=5, cooldown_seconds=60)
        errors = []

        def fail_worker():
            try:
                for _ in range(3):
                    gate.record_failure()
            except Exception as e:
                errors.append(e)

        def success_worker():
            try:
                for _ in range(3):
                    gate.record_success()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=fail_worker))
            threads.append(threading.Thread(target=success_worker))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # State should be valid (no crash)
        assert gate.state in ("closed", "open", "half-open")


# ─── Edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_config_weights(self):
        cfg = PolicyConfig(score_weights={})
        policy = GatingPolicy(config=cfg)
        # Should still work with empty weights
        with patch("bantz.brain.quality_gating.QualityScore.compute") as mock:
            mock.return_value = QualityScore(complexity=0, writing=0, risk=0, total=0.0)
            result = policy.evaluate("test")
        assert result is not None

    def test_policy_stats_zero_decisions(self):
        policy = GatingPolicy()
        stats = policy.get_stats()
        assert stats["total_decisions"] == 0
        assert stats["quality_ratio"] == 0.0
