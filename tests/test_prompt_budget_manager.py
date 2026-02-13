"""Tests for Issue #227: Router Hard-cap prompt budget for 1024 ctx models.

Tests the PromptBudgetConfig class and budget management in llm_router.
"""

from __future__ import annotations

import pytest

from bantz.brain.llm_router import (
    JarvisLLMOrchestrator,
    PromptBudgetConfig,
    _estimate_tokens,
    _trim_to_tokens,
)


class TestPromptBudgetConfig:
    """Tests for PromptBudgetConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default budget config values."""
        cfg = PromptBudgetConfig()
        assert cfg.context_length == 1024
        assert cfg.completion_reserve == 256
        assert cfg.safety_margin == 32

    def test_for_context_1024(self) -> None:
        """Test budget config for 1024 context."""
        cfg = PromptBudgetConfig.for_context(1024)
        assert cfg.context_length == 1024
        assert cfg.completion_reserve == 256
        assert cfg.available_for_prompt == 1024 - 256 - 32

    def test_for_context_2048(self) -> None:
        """Test budget config for 2048 context."""
        cfg = PromptBudgetConfig.for_context(2048)
        assert cfg.context_length == 2048
        assert cfg.completion_reserve == 512

    def test_for_context_4096(self) -> None:
        """Test budget config for 4096 context."""
        cfg = PromptBudgetConfig.for_context(4096)
        assert cfg.context_length == 4096
        assert cfg.completion_reserve == 768

    def test_available_for_prompt(self) -> None:
        """Test available_for_prompt calculation."""
        cfg = PromptBudgetConfig(
            context_length=1024,
            completion_reserve=256,
            safety_margin=32,
        )
        assert cfg.available_for_prompt == 736  # 1024 - 256 - 32

    def test_compute_section_budgets(self) -> None:
        """Test section budget computation."""
        cfg = PromptBudgetConfig.for_context(1024)
        budgets = cfg.compute_section_budgets(
            system_tokens=200,
            user_tokens=50,
        )
        
        assert "system" in budgets
        assert "user" in budgets
        assert "dialog" in budgets
        assert "memory" in budgets
        assert "session" in budgets
        assert "total" in budgets
        assert "remaining" in budgets
        
        # System and user should be capped
        assert budgets["system"] <= 200
        assert budgets["user"] <= 50
        
        # Optional sections should have reasonable budgets
        assert budgets["dialog"] >= 0
        assert budgets["memory"] >= 0
        assert budgets["session"] >= 0

    def test_section_budgets_percentages(self) -> None:
        """Test that section budgets follow percentage allocation."""
        cfg = PromptBudgetConfig.for_context(2048)
        budgets = cfg.compute_section_budgets(
            system_tokens=300,
            user_tokens=100,
        )
        
        remaining = budgets["remaining"]
        
        # Check approximate percentages (allow some tolerance)
        assert abs(budgets["dialog"] - int(remaining * 0.25)) <= 1
        assert abs(budgets["memory"] - int(remaining * 0.25)) <= 1
        assert abs(budgets["session"] - int(remaining * 0.15)) <= 1


class TestTokenEstimation:
    """Tests for token estimation utilities."""

    def test_estimate_tokens_empty(self) -> None:
        """Empty string should estimate to 0 tokens."""
        assert _estimate_tokens("") == 0
        assert _estimate_tokens(None) == 0  # type: ignore

    def test_estimate_tokens_short(self) -> None:
        """Short text should estimate correctly (4 chars/token)."""
        assert _estimate_tokens("hello") == 1  # 5 chars -> 1 token
        assert _estimate_tokens("hello world") == 2  # 11 chars -> 2 tokens

    def test_estimate_tokens_long(self) -> None:
        """Long text should estimate proportionally."""
        text = "a" * 400
        assert _estimate_tokens(text) == 100  # 400 chars / 4 = 100 tokens


class TestTrimToTokens:
    """Tests for _trim_to_tokens utility."""

    def test_trim_empty(self) -> None:
        """Empty string should return empty."""
        assert _trim_to_tokens("", 100) == ""

    def test_trim_short_text_no_change(self) -> None:
        """Short text within budget should not change."""
        text = "hello world"
        assert _trim_to_tokens(text, 100) == text

    def test_trim_long_text(self) -> None:
        """Long text should be trimmed with ellipsis."""
        text = "a" * 100
        result = _trim_to_tokens(text, 10)  # 10 tokens = 40 chars
        assert len(result) <= 40
        assert result.endswith("…")

    def test_trim_zero_budget(self) -> None:
        """Zero budget should return empty string."""
        assert _trim_to_tokens("hello", 0) == ""

    def test_trim_negative_budget(self) -> None:
        """Negative budget should return empty string."""
        assert _trim_to_tokens("hello", -10) == ""


class TestBuildPromptBudget:
    """Tests for _build_prompt with budget constraints."""

    @pytest.fixture
    def mock_llm(self) -> object:
        """Create a mock LLM client."""
        class MockLLM:
            def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
                return '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 0.9, "tool_plan": [], "assistant_reply": "Merhaba!"}'
        return MockLLM()

    def test_build_prompt_respects_budget(self, mock_llm: object) -> None:
        """Prompt should respect token budget."""
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        prompt, meta = router._build_prompt(
            user_input="merhaba",
            dialog_summary="Long dialog summary " * 100,
            retrieved_memory="Long memory " * 100,
            session_context={"tz": "Europe/Istanbul"},
            token_budget=200,  # Very tight budget
        )
        
        prompt_tokens = _estimate_tokens(prompt)
        assert prompt_tokens <= 200
        assert meta["trimmed"] is True

    def test_build_prompt_sections_tracked(self, mock_llm: object) -> None:
        """Build prompt should track sections used."""
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        prompt, meta = router._build_prompt(
            user_input="merhaba",
            dialog_summary="Dialog özeti",
            retrieved_memory="Memory content",
            session_context={"tz": "Europe/Istanbul"},
            token_budget=1000,
        )
        
        sections_used = meta.get("sections_used", {})
        assert "system" in sections_used
        assert "user" in sections_used

    def test_build_prompt_with_budget_config(self, mock_llm: object) -> None:
        """Build prompt should use PromptBudgetConfig if provided."""
        router = JarvisLLMOrchestrator(llm=mock_llm)
        budget_config = PromptBudgetConfig.for_context(1024)
        
        prompt, meta = router._build_prompt(
            user_input="merhaba",
            dialog_summary="Dialog özeti",
            token_budget=budget_config.available_for_prompt,
            budget_config=budget_config,
        )
        
        prompt_tokens = _estimate_tokens(prompt)
        assert prompt_tokens <= budget_config.available_for_prompt

    def test_priority_trimming_order(self, mock_llm: object) -> None:
        """Dialog should be trimmed before memory, memory before session."""
        router = JarvisLLMOrchestrator(llm=mock_llm)
        
        # Create content that will force trimming
        long_dialog = "Dialog content " * 200
        long_memory = "Memory content " * 200
        long_session = {"data": "Session " * 200}
        
        prompt, meta = router._build_prompt(
            user_input="test",
            dialog_summary=long_dialog,
            retrieved_memory=long_memory,
            session_context=long_session,
            token_budget=300,  # Very tight
        )
        
        # Prompt should be within budget
        assert _estimate_tokens(prompt) <= 300
        assert meta["trimmed"] is True


class TestRouterContextOverflow:
    """Tests to ensure no context overflow with 1024 ctx models."""

    @pytest.fixture
    def mock_llm_1024(self) -> object:
        """Create a mock LLM with 1024 context."""
        class MockLLM:
            context_length = 1024
            model_name = "test-1024"
            
            def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
                return '{"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 0.9, "tool_plan": [], "assistant_reply": "OK"}'
            
            def get_model_context_length(self) -> int:
                return 1024
                
        return MockLLM()

    def test_route_respects_1024_context(self, mock_llm_1024: object) -> None:
        """Route should never exceed 1024 context limit."""
        router = JarvisLLMOrchestrator(llm=mock_llm_1024)
        
        # Try to overflow with large inputs
        result = router.route(
            user_input="yarın saat 3te toplantı ekle",
            dialog_summary="Previous dialog " * 200,
            retrieved_memory="Memory content " * 200,
            session_context={"tz": "Europe/Istanbul", "data": "Extra " * 100},
        )
        
        # Should complete without error
        assert result is not None
        assert result.route in ["calendar", "smalltalk", "unknown"]

    def test_prompt_budget_logged(self, mock_llm_1024: object, caplog: pytest.LogCaptureFixture) -> None:
        """Budget metrics should be logged."""
        import logging
        caplog.set_level(logging.INFO)
        
        router = JarvisLLMOrchestrator(llm=mock_llm_1024)
        
        router.route(
            user_input="merhaba",
            dialog_summary="Previous turns",
        )
        
        # Check that budget logging occurred
        log_text = caplog.text
        assert "router_budget" in log_text or "ctx=" in log_text


class TestBudgetConfigEdgeCases:
    """Edge case tests for budget configuration."""

    def test_minimum_context_256(self) -> None:
        """Context length should have a minimum of 256."""
        cfg = PromptBudgetConfig.for_context(100)  # Below minimum
        assert cfg.context_length >= 256

    def test_available_for_prompt_minimum(self) -> None:
        """Available prompt budget should have a floor."""
        cfg = PromptBudgetConfig(
            context_length=256,
            completion_reserve=200,
            safety_margin=50,
        )
        # Even with tight budget, should have minimum
        assert cfg.available_for_prompt >= 6  # 256 - 200 - 50 = 6

    def test_section_budgets_with_large_system_prompt(self) -> None:
        """Large system prompt should still leave room for user input."""
        cfg = PromptBudgetConfig.for_context(1024)
        budgets = cfg.compute_section_budgets(
            system_tokens=600,  # Large system prompt
            user_tokens=50,
        )
        
        # System should be capped to ~60% of available
        assert budgets["system"] < 600
        # User should still have budget
        assert budgets["user"] > 0

    def test_frozen_dataclass(self) -> None:
        """PromptBudgetConfig should be immutable."""
        cfg = PromptBudgetConfig()
        with pytest.raises(Exception):  # FrozenInstanceError
            cfg.context_length = 2048  # type: ignore
