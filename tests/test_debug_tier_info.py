"""Tests for debug tier info module.

Issue #244: Debug tier decisions + quality hit/miss.

Tests cover:
- TierBackend, TierDecisionType, QualityResult enums
- TierDecision and TierSession dataclasses
- TierDebugger and session management
- Debug enable/disable via environment
- Timer functionality
- Statistics aggregation
"""

import os
import io
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from bantz.debug.tier_info import (
    TierBackend,
    TierDecisionType,
    QualityResult,
    TierDecision,
    TierSession,
    TierTimer,
    TierDebugger,
    TierDebugSession,
    is_debug_enabled,
    enable_debug,
    disable_debug,
    get_tier_debugger,
    reset_tier_debugger,
    setup_debug_from_cli,
    print_tier_stats,
)


# =============================================================================
# TierBackend Tests
# =============================================================================

class TestTierBackend:
    """Tests for TierBackend enum."""
    
    def test_vllm_local_value(self) -> None:
        """Test VLLM_LOCAL value."""
        assert TierBackend.VLLM_LOCAL.value == "vllm_local"
    
    def test_gemini_cloud_value(self) -> None:
        """Test GEMINI_CLOUD value."""
        assert TierBackend.GEMINI_CLOUD.value == "gemini_cloud"
    
    def test_openai_cloud_value(self) -> None:
        """Test OPENAI_CLOUD value."""
        assert TierBackend.OPENAI_CLOUD.value == "openai_cloud"
    
    def test_mock_value(self) -> None:
        """Test MOCK value."""
        assert TierBackend.MOCK.value == "mock"
    
    def test_unknown_value(self) -> None:
        """Test UNKNOWN value."""
        assert TierBackend.UNKNOWN.value == "unknown"


# =============================================================================
# TierDecisionType Tests
# =============================================================================

class TestTierDecisionType:
    """Tests for TierDecisionType enum."""
    
    def test_router_value(self) -> None:
        """Test ROUTER value."""
        assert TierDecisionType.ROUTER.value == "router"
    
    def test_finalizer_value(self) -> None:
        """Test FINALIZER value."""
        assert TierDecisionType.FINALIZER.value == "finalizer"
    
    def test_quality_value(self) -> None:
        """Test QUALITY_CHECK value."""
        assert TierDecisionType.QUALITY_CHECK.value == "quality"
    
    def test_fallback_value(self) -> None:
        """Test FALLBACK value."""
        assert TierDecisionType.FALLBACK.value == "fallback"
    
    def test_bypass_value(self) -> None:
        """Test BYPASS value."""
        assert TierDecisionType.BYPASS.value == "bypass"


# =============================================================================
# QualityResult Tests
# =============================================================================

class TestQualityResult:
    """Tests for QualityResult enum."""
    
    def test_pass_value(self) -> None:
        """Test PASS value."""
        assert QualityResult.PASS.value == "pass"
    
    def test_fail_value(self) -> None:
        """Test FAIL value."""
        assert QualityResult.FAIL.value == "fail"
    
    def test_skip_value(self) -> None:
        """Test SKIP value."""
        assert QualityResult.SKIP.value == "skip"
    
    def test_pending_value(self) -> None:
        """Test PENDING value."""
        assert QualityResult.PENDING.value == "pending"


# =============================================================================
# TierDecision Tests
# =============================================================================

class TestTierDecision:
    """Tests for TierDecision dataclass."""
    
    def test_creation(self) -> None:
        """Test decision creation."""
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        )
        assert decision.decision_type == TierDecisionType.ROUTER
        assert decision.backend == TierBackend.VLLM_LOCAL
        assert decision.duration_ms == 0.0
        assert decision.reason == ""
        assert decision.confidence == 1.0
    
    def test_creation_with_all_fields(self) -> None:
        """Test decision creation with all fields."""
        decision = TierDecision(
            decision_type=TierDecisionType.FINALIZER,
            backend=TierBackend.GEMINI_CLOUD,
            duration_ms=150.5,
            reason="quality requested",
            confidence=0.95,
            quality_result=QualityResult.PASS,
            metadata={"model": "gemini-1.5-flash"},
        )
        assert decision.duration_ms == 150.5
        assert decision.reason == "quality requested"
        assert decision.confidence == 0.95
        assert decision.quality_result == QualityResult.PASS
        assert decision.metadata["model"] == "gemini-1.5-flash"
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
            duration_ms=25.0,
            reason="local capable",
        )
        d = decision.to_dict()
        assert d["decision_type"] == "router"
        assert d["backend"] == "vllm_local"
        assert d["duration_ms"] == 25.0
        assert d["reason"] == "local capable"
    
    def test_format_short(self) -> None:
        """Test short format."""
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
            duration_ms=25.0,
            reason="local capable",
        )
        formatted = decision.format_short()
        assert "ROUTER" in formatted
        assert "vllm_local" in formatted
        assert "25.0" in formatted
        assert "local capable" in formatted
    
    def test_format_detailed(self) -> None:
        """Test detailed format."""
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
            duration_ms=25.0,
            reason="local capable",
            metadata={"model": "qwen2.5-3b"},
        )
        formatted = decision.format_detailed()
        assert "ROUTER" in formatted
        assert "vllm_local" in formatted
        assert "25.0" in formatted
        assert "model" in formatted
        assert "qwen2.5-3b" in formatted


# =============================================================================
# TierSession Tests
# =============================================================================

class TestTierSession:
    """Tests for TierSession dataclass."""
    
    def test_creation(self) -> None:
        """Test session creation."""
        session = TierSession(session_id="test-123")
        assert session.session_id == "test-123"
        assert len(session.decisions) == 0
    
    def test_add_decision(self) -> None:
        """Test adding decision to session."""
        session = TierSession(session_id="test-123")
        decision = TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        )
        session.add_decision(decision)
        assert len(session.decisions) == 1
        assert session.decisions[0] == decision
    
    def test_get_router_backend(self) -> None:
        """Test getting router backend."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        ))
        assert session.get_router_backend() == TierBackend.VLLM_LOCAL
    
    def test_get_router_backend_none(self) -> None:
        """Test getting router backend when none."""
        session = TierSession(session_id="test-123")
        assert session.get_router_backend() is None
    
    def test_get_finalizer_backend(self) -> None:
        """Test getting finalizer backend."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.FINALIZER,
            backend=TierBackend.GEMINI_CLOUD,
        ))
        assert session.get_finalizer_backend() == TierBackend.GEMINI_CLOUD
    
    def test_was_quality_called_true(self) -> None:
        """Test quality called check when true."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.QUALITY_CHECK,
            backend=TierBackend.UNKNOWN,
            quality_result=QualityResult.PASS,
        ))
        assert session.was_quality_called() is True
    
    def test_was_quality_called_false(self) -> None:
        """Test quality called check when false."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        ))
        assert session.was_quality_called() is False
    
    def test_quality_passed_true(self) -> None:
        """Test quality passed when true."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.QUALITY_CHECK,
            backend=TierBackend.UNKNOWN,
            quality_result=QualityResult.PASS,
        ))
        assert session.quality_passed() is True
    
    def test_quality_passed_false(self) -> None:
        """Test quality passed when failed."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.QUALITY_CHECK,
            backend=TierBackend.UNKNOWN,
            quality_result=QualityResult.FAIL,
        ))
        assert session.quality_passed() is False
    
    def test_format_summary(self) -> None:
        """Test format summary."""
        session = TierSession(session_id="test-123")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        ))
        session.total_duration_ms = 150.5
        
        summary = session.format_summary()
        assert "TIER DEBUG" in summary
        assert "test-123" in summary
        assert "vllm_local" in summary
    
    def test_format_full(self) -> None:
        """Test format full."""
        session = TierSession(
            session_id="test-123",
            user_query="Bugün hava nasıl?",
        )
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
            reason="local capable",
        ))
        session.total_duration_ms = 150.5
        
        full = session.format_full()
        assert "test-123" in full
        assert "Bugün hava nasıl?" in full
        assert "ROUTER" in full
        assert "150.5" in full
    
    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        session = TierSession(session_id="test-123", user_query="test")
        session.add_decision(TierDecision(
            decision_type=TierDecisionType.ROUTER,
            backend=TierBackend.VLLM_LOCAL,
        ))
        
        d = session.to_dict()
        assert d["session_id"] == "test-123"
        assert d["router_backend"] == "vllm_local"
        assert len(d["decisions"]) == 1


# =============================================================================
# TierTimer Tests
# =============================================================================

class TestTierTimer:
    """Tests for TierTimer context manager."""
    
    def test_timer_basic(self) -> None:
        """Test basic timer functionality."""
        with TierTimer() as timer:
            time.sleep(0.01)  # 10ms
        
        assert timer.duration_ms >= 9  # At least 9ms (accounting for precision)
        assert timer.duration_ms < 100  # Less than 100ms
    
    def test_timer_very_short(self) -> None:
        """Test timer for very short operation."""
        with TierTimer() as timer:
            pass
        
        assert timer.duration_ms >= 0
        assert timer.duration_ms < 10


# =============================================================================
# Debug Enable/Disable Tests
# =============================================================================

class TestDebugEnableDisable:
    """Tests for debug enable/disable functions."""
    
    def test_is_debug_enabled_default(self) -> None:
        """Test default debug state."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_debug_enabled() is False
    
    def test_is_debug_enabled_via_bantz_debug_tiers(self) -> None:
        """Test enabling via BANTZ_DEBUG_TIERS."""
        with patch.dict(os.environ, {"BANTZ_DEBUG_TIERS": "1"}):
            assert is_debug_enabled() is True
    
    def test_is_debug_enabled_via_bantz_debug(self) -> None:
        """Test enabling via BANTZ_DEBUG."""
        with patch.dict(os.environ, {"BANTZ_DEBUG": "1"}):
            assert is_debug_enabled() is True
    
    def test_is_debug_enabled_true_string(self) -> None:
        """Test enabling with 'true' string."""
        with patch.dict(os.environ, {"BANTZ_DEBUG_TIERS": "true"}):
            assert is_debug_enabled() is True
    
    def test_is_debug_enabled_yes_string(self) -> None:
        """Test enabling with 'yes' string."""
        with patch.dict(os.environ, {"BANTZ_DEBUG_TIERS": "yes"}):
            assert is_debug_enabled() is True
    
    def test_enable_debug(self) -> None:
        """Test enable_debug function."""
        with patch.dict(os.environ, {}, clear=True):
            enable_debug()
            assert os.environ.get("BANTZ_DEBUG_TIERS") == "1"
    
    def test_disable_debug(self) -> None:
        """Test disable_debug function."""
        with patch.dict(os.environ, {"BANTZ_DEBUG_TIERS": "1"}):
            disable_debug()
            assert os.environ.get("BANTZ_DEBUG_TIERS") is None


# =============================================================================
# TierDebugger Tests
# =============================================================================

class TestTierDebugger:
    """Tests for TierDebugger class."""
    
    def test_creation_disabled(self) -> None:
        """Test creation with debugging disabled."""
        debugger = TierDebugger(enabled=False)
        assert debugger.enabled is False
    
    def test_creation_enabled(self) -> None:
        """Test creation with debugging enabled."""
        debugger = TierDebugger(enabled=True)
        assert debugger.enabled is True
    
    def test_enable_disable(self) -> None:
        """Test enable/disable methods."""
        debugger = TierDebugger(enabled=False)
        assert debugger.enabled is False
        
        debugger.enable()
        assert debugger.enabled is True
        
        debugger.disable()
        assert debugger.enabled is False
    
    def test_timer_creation(self) -> None:
        """Test timer method."""
        debugger = TierDebugger(enabled=False)
        timer = debugger.timer()
        assert isinstance(timer, TierTimer)
    
    def test_session_context(self) -> None:
        """Test session context manager."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            assert session.session_id == "test-123"
            assert session.user_query == "hello"
        
        # Summary should be written
        assert "test-123" in output.getvalue()
    
    def test_log_router_decision(self) -> None:
        """Test logging router decision."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            decision = debugger.log_router_decision(
                session,
                TierBackend.VLLM_LOCAL,
                duration_ms=25.0,
                reason="local capable",
            )
            assert decision.decision_type == TierDecisionType.ROUTER
            assert decision.backend == TierBackend.VLLM_LOCAL
        
        assert "ROUTER" in output.getvalue()
        assert "vllm_local" in output.getvalue()
    
    def test_log_finalizer_decision(self) -> None:
        """Test logging finalizer decision."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            decision = debugger.log_finalizer_decision(
                session,
                TierBackend.GEMINI_CLOUD,
                duration_ms=150.0,
                reason="quality tier",
            )
            assert decision.decision_type == TierDecisionType.FINALIZER
            assert decision.backend == TierBackend.GEMINI_CLOUD
        
        assert "FINALIZER" in output.getvalue()
    
    def test_log_quality_check(self) -> None:
        """Test logging quality check."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            decision = debugger.log_quality_check(
                session,
                QualityResult.PASS,
                score=0.85,
                threshold=0.7,
                duration_ms=50.0,
            )
            assert decision.decision_type == TierDecisionType.QUALITY_CHECK
            assert decision.quality_result == QualityResult.PASS
            assert decision.metadata["score"] == 0.85
            assert decision.metadata["threshold"] == 0.7
        
        assert "QUALITY" in output.getvalue()
    
    def test_log_fallback(self) -> None:
        """Test logging fallback."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            decision = debugger.log_fallback(
                session,
                from_backend=TierBackend.VLLM_LOCAL,
                to_backend=TierBackend.GEMINI_CLOUD,
                reason="timeout",
            )
            assert decision.decision_type == TierDecisionType.FALLBACK
            assert decision.backend == TierBackend.GEMINI_CLOUD
        
        assert "FALLBACK" in output.getvalue()
    
    def test_log_bypass(self) -> None:
        """Test logging bypass."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("test-123", "hello") as session:
            decision = debugger.log_bypass(
                session,
                reason="smalltalk detected",
                rule_name="smalltalk_rule",
            )
            assert decision.decision_type == TierDecisionType.BYPASS
            assert decision.metadata["rule_name"] == "smalltalk_rule"
        
        assert "BYPASS" in output.getvalue()
    
    def test_no_output_when_disabled(self) -> None:
        """Test no output when disabled."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=False, output=output)
        
        with debugger.session("test-123", "hello") as session:
            debugger.log_router_decision(
                session,
                TierBackend.VLLM_LOCAL,
            )
        
        assert output.getvalue() == ""
    
    def test_get_session(self) -> None:
        """Test getting session by ID."""
        debugger = TierDebugger(enabled=False)
        
        with debugger.session("test-123", "hello") as session:
            pass
        
        retrieved = debugger.get_session("test-123")
        assert retrieved is not None
        assert retrieved.session_id == "test-123"
    
    def test_get_session_not_found(self) -> None:
        """Test getting non-existent session."""
        debugger = TierDebugger(enabled=False)
        assert debugger.get_session("nonexistent") is None
    
    def test_get_all_sessions(self) -> None:
        """Test getting all sessions."""
        debugger = TierDebugger(enabled=False)
        
        with debugger.session("test-1", "hello1") as s1:
            pass
        with debugger.session("test-2", "hello2") as s2:
            pass
        
        sessions = debugger.get_all_sessions()
        assert len(sessions) == 2
    
    def test_clear_sessions(self) -> None:
        """Test clearing sessions."""
        debugger = TierDebugger(enabled=False)
        
        with debugger.session("test-123", "hello") as session:
            pass
        
        assert len(debugger.get_all_sessions()) == 1
        debugger.clear_sessions()
        assert len(debugger.get_all_sessions()) == 0
    
    def test_get_stats_empty(self) -> None:
        """Test stats with no sessions."""
        debugger = TierDebugger(enabled=False)
        stats = debugger.get_stats()
        assert stats["total_sessions"] == 0
    
    def test_get_stats_with_sessions(self) -> None:
        """Test stats with sessions."""
        debugger = TierDebugger(enabled=False)
        
        with debugger.session("test-1", "hello1") as s1:
            debugger.log_router_decision(s1, TierBackend.VLLM_LOCAL)
            debugger.log_quality_check(s1, QualityResult.PASS, score=0.9, threshold=0.7)
        
        with debugger.session("test-2", "hello2") as s2:
            debugger.log_router_decision(s2, TierBackend.GEMINI_CLOUD)
        
        stats = debugger.get_stats()
        assert stats["total_sessions"] == 2
        assert stats["router_backends"]["vllm_local"] == 1
        assert stats["router_backends"]["gemini_cloud"] == 1
        assert stats["quality_calls"] == 1
        assert stats["quality_call_rate"] == 0.5


# =============================================================================
# Global Debugger Tests
# =============================================================================

class TestGlobalDebugger:
    """Tests for global debugger functions."""
    
    def test_get_tier_debugger(self) -> None:
        """Test getting global debugger."""
        reset_tier_debugger()
        debugger = get_tier_debugger()
        assert debugger is not None
        assert isinstance(debugger, TierDebugger)
    
    def test_get_tier_debugger_singleton(self) -> None:
        """Test global debugger is singleton."""
        reset_tier_debugger()
        debugger1 = get_tier_debugger()
        debugger2 = get_tier_debugger()
        assert debugger1 is debugger2
    
    def test_reset_tier_debugger(self) -> None:
        """Test resetting global debugger."""
        reset_tier_debugger()
        debugger1 = get_tier_debugger()
        reset_tier_debugger()
        debugger2 = get_tier_debugger()
        assert debugger1 is not debugger2


# =============================================================================
# CLI Integration Tests
# =============================================================================

class TestCLIIntegration:
    """Tests for CLI integration helpers."""
    
    def test_setup_debug_from_cli_enabled(self) -> None:
        """Test setup from CLI with debug enabled."""
        reset_tier_debugger()
        
        class Args:
            debug = True
        
        with patch.dict(os.environ, {}, clear=True):
            setup_debug_from_cli(Args())
            assert is_debug_enabled() is True
            debugger = get_tier_debugger()
            assert debugger.enabled is True
    
    def test_setup_debug_from_cli_disabled(self) -> None:
        """Test setup from CLI with debug disabled."""
        reset_tier_debugger()
        
        class Args:
            debug = False
        
        with patch.dict(os.environ, {}, clear=True):
            setup_debug_from_cli(Args())
            # Should not enable
            assert os.environ.get("BANTZ_DEBUG_TIERS") is None
    
    def test_setup_debug_from_cli_no_attr(self) -> None:
        """Test setup from CLI without debug attribute."""
        class Args:
            pass
        
        # Should not raise
        setup_debug_from_cli(Args())


# =============================================================================
# E2E Integration Tests
# =============================================================================

class TestE2EIntegration:
    """End-to-end integration tests."""
    
    def test_full_request_flow(self) -> None:
        """Test full request flow with all decisions."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("req-001", "Bugün hava nasıl?") as session:
            # Router decision
            with debugger.timer() as t1:
                time.sleep(0.01)
            debugger.log_router_decision(
                session,
                TierBackend.VLLM_LOCAL,
                duration_ms=t1.duration_ms,
                reason="smalltalk - local capable",
            )
            
            # Quality check
            with debugger.timer() as t2:
                time.sleep(0.01)
            debugger.log_quality_check(
                session,
                QualityResult.PASS,
                score=0.88,
                threshold=0.7,
                duration_ms=t2.duration_ms,
            )
            
            # Finalizer decision
            debugger.log_finalizer_decision(
                session,
                TierBackend.VLLM_LOCAL,
                reason="quality passed",
            )
        
        # Verify session data
        assert session.get_router_backend() == TierBackend.VLLM_LOCAL
        assert session.get_finalizer_backend() == TierBackend.VLLM_LOCAL
        assert session.was_quality_called() is True
        assert session.quality_passed() is True
        
        # Verify output
        output_text = output.getvalue()
        assert "ROUTER" in output_text
        assert "QUALITY" in output_text
        assert "FINALIZER" in output_text
    
    def test_fallback_flow(self) -> None:
        """Test fallback flow."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("req-002", "Karmaşık soru") as session:
            # Router decision to local
            debugger.log_router_decision(
                session,
                TierBackend.VLLM_LOCAL,
                reason="initial attempt",
            )
            
            # Quality fails
            debugger.log_quality_check(
                session,
                QualityResult.FAIL,
                score=0.45,
                threshold=0.7,
            )
            
            # Fallback to cloud
            debugger.log_fallback(
                session,
                from_backend=TierBackend.VLLM_LOCAL,
                to_backend=TierBackend.GEMINI_CLOUD,
                reason="quality below threshold",
            )
            
            # Finalizer with cloud
            debugger.log_finalizer_decision(
                session,
                TierBackend.GEMINI_CLOUD,
                reason="fallback triggered",
            )
        
        # Verify
        assert session.get_finalizer_backend() == TierBackend.GEMINI_CLOUD
        assert "FALLBACK" in output.getvalue()
    
    def test_bypass_flow(self) -> None:
        """Test rule-based bypass flow."""
        output = io.StringIO()
        debugger = TierDebugger(enabled=True, output=output)
        
        with debugger.session("req-003", "Merhaba") as session:
            # Bypass router entirely
            debugger.log_bypass(
                session,
                reason="greeting detected",
                rule_name="greeting_rule",
            )
            
            # Direct to local finalizer
            debugger.log_finalizer_decision(
                session,
                TierBackend.VLLM_LOCAL,
                reason="bypass - no router needed",
            )
        
        # Verify no router decision
        assert session.get_router_backend() is None
        assert session.get_finalizer_backend() == TierBackend.VLLM_LOCAL
        assert "BYPASS" in output.getvalue()
    
    def test_stats_aggregation(self) -> None:
        """Test statistics aggregation across sessions."""
        debugger = TierDebugger(enabled=False)
        
        # Session 1: local, quality pass
        with debugger.session("req-1", "q1") as s1:
            debugger.log_router_decision(s1, TierBackend.VLLM_LOCAL)
            debugger.log_quality_check(s1, QualityResult.PASS, score=0.9, threshold=0.7)
            debugger.log_finalizer_decision(s1, TierBackend.VLLM_LOCAL)
        
        # Session 2: local, quality fail, fallback to cloud
        with debugger.session("req-2", "q2") as s2:
            debugger.log_router_decision(s2, TierBackend.VLLM_LOCAL)
            debugger.log_quality_check(s2, QualityResult.FAIL, score=0.5, threshold=0.7)
            debugger.log_fallback(s2, TierBackend.VLLM_LOCAL, TierBackend.GEMINI_CLOUD, "quality fail")
            debugger.log_finalizer_decision(s2, TierBackend.GEMINI_CLOUD)
        
        # Session 3: cloud direct
        with debugger.session("req-3", "q3") as s3:
            debugger.log_router_decision(s3, TierBackend.GEMINI_CLOUD)
            debugger.log_finalizer_decision(s3, TierBackend.GEMINI_CLOUD)
        
        stats = debugger.get_stats()
        
        assert stats["total_sessions"] == 3
        assert stats["router_backends"]["vllm_local"] == 2
        assert stats["router_backends"]["gemini_cloud"] == 1
        assert stats["quality_calls"] == 2
        assert stats["quality_call_rate"] == pytest.approx(2/3)
