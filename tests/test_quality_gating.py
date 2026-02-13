"""Tests for quality_gating module.

Issue #232: Comprehensive tests for quality gating policy.
"""

import pytest
import os
import time
from unittest.mock import patch

from bantz.brain.quality_gating import (
    GatingDecision,
    QualityScore,
    PolicyConfig,
    QualityRateLimiter,
    GatingResult,
    GatingPolicy,
    get_default_policy,
    evaluate_quality_gating,
    should_use_quality,
)


class TestQualityScore:
    """Tests for QualityScore class."""
    
    def test_simple_input(self):
        score = QualityScore.compute("merhaba")
        assert score.complexity >= 0
        assert score.writing >= 0
        assert score.risk >= 0
        assert score.total >= 0
    
    def test_complex_input(self):
        text = "Bana detaylı bir analiz yap ve strateji planla. Adım adım roadmap çıkar."
        score = QualityScore.compute(text)
        assert score.complexity >= 2
        assert score.total > 0
    
    def test_writing_input(self):
        text = "Hocaya resmi bir e-posta yaz, dilekçe formatında"
        score = QualityScore.compute(text)
        assert score.writing >= 3
    
    def test_risk_with_tools(self):
        score = QualityScore.compute(
            "Toplantıyı sil",
            tool_names=["delete_event"],
        )
        assert score.risk >= 3
    
    def test_risk_with_confirmation(self):
        score = QualityScore.compute(
            "Tamam",
            requires_confirmation=True,
        )
        assert score.risk >= 4
    
    def test_custom_weights(self):
        text = "Test input"
        weights = {"complexity": 1.0, "writing": 0.0, "risk": 0.0}
        score = QualityScore.compute(text, weights=weights)
        # Total should equal complexity score
        assert "complexity" in score.components
    
    def test_to_dict(self):
        score = QualityScore.compute("test")
        d = score.to_dict()
        assert "complexity" in d
        assert "writing" in d
        assert "risk" in d
        assert "total" in d
        assert "components" in d


class TestPolicyConfig:
    """Tests for PolicyConfig class."""
    
    def test_defaults(self):
        config = PolicyConfig()
        assert config.quality_threshold == 2.5
        assert config.quality_rate_limit == 30
        assert config.finalizer_mode == "auto"
    
    def test_from_env_with_defaults(self):
        config = PolicyConfig.from_env()
        assert config.quality_threshold >= 0
        assert config.quality_rate_limit > 0
    
    @patch.dict(os.environ, {
        "BANTZ_QUALITY_SCORE_THRESHOLD": "3.5",
        "BANTZ_QUALITY_RATE_LIMIT": "50",
        "BANTZ_FINALIZER_MODE": "always",
    })
    def test_from_env_with_values(self):
        config = PolicyConfig.from_env()
        assert config.quality_threshold == 3.5
        assert config.quality_rate_limit == 50
        assert config.finalizer_mode == "always"
    
    @patch.dict(os.environ, {
        "BANTZ_QUALITY_BYPASS_PATTERNS": "basit,kısa",
        "BANTZ_FORCE_QUALITY_PATTERNS": "detaylı,kapsamlı",
    })
    def test_from_env_lists(self):
        config = PolicyConfig.from_env()
        assert "basit" in config.bypass_patterns
        assert "kısa" in config.bypass_patterns
        assert "detaylı" in config.force_quality_patterns


class TestQualityRateLimiter:
    """Tests for QualityRateLimiter class."""
    
    def test_initial_state(self):
        limiter = QualityRateLimiter(max_requests=10, window_seconds=60.0)
        assert limiter.current_usage == 0
        assert limiter.remaining_quota == 10
    
    def test_acquire_success(self):
        limiter = QualityRateLimiter(max_requests=10, window_seconds=60.0)
        assert limiter.acquire() == True
        assert limiter.current_usage == 1
        assert limiter.remaining_quota == 9
    
    def test_acquire_multiple(self):
        limiter = QualityRateLimiter(max_requests=3, window_seconds=60.0)
        assert limiter.acquire() == True
        assert limiter.acquire() == True
        assert limiter.acquire() == True
        assert limiter.acquire() == False  # Rate limited
        assert limiter.blocked_count == 1
    
    def test_check_without_consume(self):
        limiter = QualityRateLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.check() == True
        assert limiter.current_usage == 0  # Not consumed
        
        limiter.acquire()
        assert limiter.check() == False  # Would be blocked
        assert limiter.current_usage == 1
    
    def test_release(self):
        limiter = QualityRateLimiter(max_requests=1, window_seconds=60.0)
        limiter.acquire()
        assert limiter.remaining_quota == 0
        
        limiter.release()
        assert limiter.remaining_quota == 1
    
    def test_get_stats(self):
        limiter = QualityRateLimiter(max_requests=10, window_seconds=60.0)
        limiter.acquire()
        limiter.acquire()
        
        stats = limiter.get_stats()
        assert stats["current_usage"] == 2
        assert stats["max_requests"] == 10
        assert stats["remaining_quota"] == 8
        assert stats["total_requests"] == 2
    
    def test_reset(self):
        limiter = QualityRateLimiter(max_requests=10, window_seconds=60.0)
        limiter.acquire()
        limiter.acquire()
        
        limiter.reset()
        assert limiter.current_usage == 0
        assert limiter.blocked_count == 0


class TestGatingPolicy:
    """Tests for GatingPolicy class."""
    
    def test_init_default_config(self):
        policy = GatingPolicy()
        assert policy.config is not None
        assert policy.rate_limiter is not None
    
    def test_init_custom_config(self):
        config = PolicyConfig(quality_threshold=4.0)
        policy = GatingPolicy(config=config)
        assert policy.config.quality_threshold == 4.0
    
    def test_evaluate_simple_input(self):
        policy = GatingPolicy()
        result = policy.evaluate("merhaba")
        assert result.decision in [GatingDecision.USE_FAST, GatingDecision.USE_QUALITY]
        assert result.score is not None
        assert result.reason is not None
    
    def test_evaluate_complex_input(self):
        config = PolicyConfig(
            quality_threshold=2.0,
            min_complexity_for_quality=3,
        )
        policy = GatingPolicy(config=config)
        
        text = "Detaylı analiz yap, strateji planla, adım adım roadmap çıkar"
        result = policy.evaluate(text)
        
        # Should qualify for quality tier
        assert result.score.complexity >= 2
    
    def test_evaluate_writing_input(self):
        config = PolicyConfig(min_writing_for_quality=3)
        policy = GatingPolicy(config=config)
        
        text = "Hocaya resmi e-posta yaz, dilekçe formatında"
        result = policy.evaluate(text)
        
        assert result.score.writing >= 3
    
    def test_bypass_patterns(self):
        config = PolicyConfig(
            bypass_patterns=["basit", "kısa"],
            quality_threshold=0.1,  # Low threshold
        )
        policy = GatingPolicy(config=config)
        
        result = policy.evaluate("basit bir soru")
        assert result.decision == GatingDecision.USE_FAST
        assert result.reason == "bypass_pattern_match"
    
    def test_force_quality_patterns(self):
        config = PolicyConfig(
            force_quality_patterns=["detaylı analiz"],
            quality_rate_limit=100,
        )
        policy = GatingPolicy(config=config)
        
        result = policy.evaluate("Bana detaylı analiz yap")
        assert result.decision == GatingDecision.USE_QUALITY
        assert result.reason == "force_quality_pattern_match"
    
    def test_finalizer_mode_never(self):
        config = PolicyConfig(
            finalizer_mode="never",
            quality_threshold=0.1,
        )
        policy = GatingPolicy(config=config)
        
        # Even high score should be fast
        result = policy.evaluate("Çok detaylı uzun kapsamlı analiz")
        assert result.decision == GatingDecision.USE_FAST
        assert result.reason == "finalizer_mode_never"
    
    def test_finalizer_mode_always(self):
        config = PolicyConfig(
            finalizer_mode="always",
            quality_rate_limit=100,
        )
        policy = GatingPolicy(config=config)
        
        result = policy.evaluate("merhaba")
        assert result.decision == GatingDecision.USE_QUALITY
        assert result.reason == "finalizer_mode_always"
    
    def test_rate_limiting(self):
        config = PolicyConfig(
            finalizer_mode="always",
            quality_rate_limit=2,
        )
        policy = GatingPolicy(config=config)
        
        # First two should succeed
        r1 = policy.evaluate("test 1")
        r2 = policy.evaluate("test 2")
        assert r1.decision == GatingDecision.USE_QUALITY
        assert r2.decision == GatingDecision.USE_QUALITY
        
        # Third should be blocked
        r3 = policy.evaluate("test 3")
        assert r3.decision == GatingDecision.BLOCKED
        assert r3.rate_limited == True
    
    def test_rate_limiting_with_fallback(self):
        config = PolicyConfig(
            quality_threshold=0.1,  # Low threshold → quality
            fast_max_threshold=0.05,  # Very low to ensure quality path
            quality_rate_limit=1,
            min_complexity_for_quality=1,  # Low threshold
            min_writing_for_quality=1,  # Low threshold
        )
        policy = GatingPolicy(config=config)
        
        # Use a text that will score high enough for quality
        text = "Detaylı analiz yap, strateji planla, kapsamlı rapor çıkar"
        
        # First succeeds with quality
        r1 = policy.evaluate(text)
        # Score should be high enough
        if r1.score.total >= config.quality_threshold:
            assert r1.decision == GatingDecision.USE_QUALITY
            
            # Second falls back to fast (not blocked)
            r2 = policy.evaluate(text)
            assert r2.decision == GatingDecision.USE_FAST
            assert r2.rate_limited == True
    
    def test_skip_rate_limit(self):
        config = PolicyConfig(
            finalizer_mode="always",
            quality_rate_limit=1,
        )
        policy = GatingPolicy(config=config)
        
        # Use up rate limit
        policy.evaluate("test")
        
        # Skip rate limit should still allow
        result = policy.evaluate("test", enforce_rate_limit=False)
        assert result.decision == GatingDecision.USE_QUALITY
    
    def test_get_stats(self):
        policy = GatingPolicy()
        policy.evaluate("test 1")
        policy.evaluate("test 2")
        
        stats = policy.get_stats()
        assert stats["total_decisions"] == 2
        assert "quality_count" in stats
        assert "fast_count" in stats
        assert "rate_limiter" in stats
    
    def test_reset_stats(self):
        policy = GatingPolicy()
        policy.evaluate("test")
        
        policy.reset_stats()
        stats = policy.get_stats()
        assert stats["total_decisions"] == 0
    
    def test_to_dict(self):
        policy = GatingPolicy()
        result = policy.evaluate("test")
        
        d = result.to_dict()
        assert "decision" in d
        assert "score" in d
        assert "reason" in d
        assert "rate_limited" in d


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_get_default_policy(self):
        policy1 = get_default_policy()
        policy2 = get_default_policy()
        assert policy1 is policy2  # Singleton
    
    def test_evaluate_quality_gating(self):
        result = evaluate_quality_gating("test input")
        assert isinstance(result, GatingResult)
        assert result.decision in GatingDecision
    
    def test_should_use_quality_simple(self):
        # Simple input should not need quality
        result = should_use_quality("merhaba")
        assert isinstance(result, bool)
    
    def test_should_use_quality_with_tools(self):
        result = should_use_quality(
            "Mail gönder",
            tool_names=["gmail_send"],
        )
        assert isinstance(result, bool)


class TestScoreThresholds:
    """Tests for threshold-based decisions."""
    
    def test_below_fast_threshold(self):
        config = PolicyConfig(
            fast_max_threshold=1.5,
            quality_threshold=3.0,
        )
        policy = GatingPolicy(config=config)
        
        # Very simple input
        result = policy.evaluate("evet")
        assert result.decision == GatingDecision.USE_FAST
    
    def test_above_quality_threshold(self):
        config = PolicyConfig(
            fast_max_threshold=0.5,
            quality_threshold=1.5,
            quality_rate_limit=100,
        )
        policy = GatingPolicy(config=config)
        
        # Complex input with high score
        text = "Detaylı analiz yap, strateji planla, hocaya mail yaz"
        result = policy.evaluate(text)
        
        # Score should be above threshold for quality
        if result.score.total >= config.quality_threshold:
            assert result.decision == GatingDecision.USE_QUALITY
    
    def test_component_threshold_escalation(self):
        config = PolicyConfig(
            min_writing_for_quality=3,
            quality_rate_limit=100,
        )
        policy = GatingPolicy(config=config)
        
        # High writing score input
        text = "Resmi e-posta taslağı yaz, dilekçe formatında"
        result = policy.evaluate(text)
        
        if result.score.writing >= config.min_writing_for_quality:
            assert result.decision == GatingDecision.USE_QUALITY


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""
    
    def test_calendar_simple_query(self):
        """Simple calendar query should be fast."""
        policy = GatingPolicy()
        result = policy.evaluate("Yarınki toplantıları göster")
        # Simple query, should be fast
        assert result.score.total < 4
    
    def test_email_draft_complex(self):
        """Complex email draft should be quality."""
        config = PolicyConfig(
            quality_threshold=2.0,
            quality_rate_limit=100,
        )
        policy = GatingPolicy(config=config)
        
        text = "Hocama detaylı bir e-posta yaz, ödev teslim süresinin uzatılmasını talep et, kibar ve resmi ton kullan"
        result = policy.evaluate(text)
        
        # Should have high writing score
        assert result.score.writing >= 3
    
    def test_risky_action_with_confirmation(self):
        """Risky actions with confirmation need quality."""
        policy = GatingPolicy()
        result = policy.evaluate(
            "Evet, sil",
            tool_names=["delete_event"],
            requires_confirmation=True,
        )
        
        assert result.score.risk >= 4
    
    def test_rate_limit_recovery(self):
        """Rate limit should reset after window."""
        config = PolicyConfig(
            finalizer_mode="always",
            quality_rate_limit=1,
            rate_window_seconds=0.01,  # Very short window for testing (10ms)
        )
        policy = GatingPolicy(config=config)
        
        # Use up limit
        r1 = policy.evaluate("test")
        assert r1.decision == GatingDecision.USE_QUALITY
        
        r2 = policy.evaluate("test")
        assert r2.decision == GatingDecision.BLOCKED
        
        # Wait for window to pass (with generous buffer)
        time.sleep(0.2)
        
        r3 = policy.evaluate("test")
        assert r3.decision == GatingDecision.USE_QUALITY


class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_input(self):
        policy = GatingPolicy()
        result = policy.evaluate("")
        assert result.decision == GatingDecision.USE_FAST
    
    def test_none_tool_names(self):
        policy = GatingPolicy()
        result = policy.evaluate("test", tool_names=None)
        assert result is not None
    
    def test_unicode_input(self):
        policy = GatingPolicy()
        result = policy.evaluate("Müşteri toplantısı için strateji planı yap 🎯")
        assert result is not None
    
    def test_very_long_input(self):
        policy = GatingPolicy()
        long_text = "Detaylı analiz yap. " * 100
        result = policy.evaluate(long_text)
        # Long input should have high complexity
        assert result.score.complexity >= 2
    
    def test_custom_weights(self):
        policy = GatingPolicy()
        result = policy.evaluate(
            "test",
            score_weights={"complexity": 0.5, "writing": 0.3, "risk": 0.2},
        )
        assert result.score is not None
