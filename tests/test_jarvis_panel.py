"""Tests for Jarvis Panel UI (Issue #19).

Tests cover:
- JarvisPanel widget dataclasses and factory functions
- MockJarvisPanel behavior
- MockJarvisPanelController pagination
- NLU panel control patterns
- Context panel state management
- Router panel handlers
- Persona panel responses
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─────────────────────────────────────────────────────────────
# Dataclass Tests
# ─────────────────────────────────────────────────────────────

class TestPanelColors:
    """Test PanelColors dataclass."""
    
    def test_default_colors(self):
        from bantz.ui.jarvis_panel import PanelColors
        colors = PanelColors()
        
        assert colors.background.alpha() == 200
        assert colors.border.red() == 0
        assert colors.border.green() == 195
        assert colors.border.blue() == 255
        assert colors.text.alpha() == 230
    
    def test_from_theme(self):
        from bantz.ui.jarvis_panel import PanelColors
        from bantz.ui.themes import JARVIS_THEME
        
        colors = PanelColors.from_theme(JARVIS_THEME)
        assert colors.accent.name().lower() == JARVIS_THEME.primary.lower()


class TestResultItem:
    """Test ResultItem dataclass."""
    
    def test_result_item_creation(self):
        from bantz.ui.jarvis_panel import ResultItem
        
        item = ResultItem(
            title="Test Title",
            source="Source",
            time="1 saat önce",
            snippet="Test snippet...",
            url="https://example.com"
        )
        
        assert item.title == "Test Title"
        assert item.source == "Source"
        assert item.url == "https://example.com"
        assert item.index == 0  # default
    
    def test_result_item_with_metadata(self):
        from bantz.ui.jarvis_panel import ResultItem
        
        item = ResultItem(
            title="Test",
            metadata={"category": "news", "score": 0.95}
        )
        
        assert item.metadata["category"] == "news"
        assert item.metadata["score"] == 0.95


class TestSummaryData:
    """Test SummaryData dataclass."""
    
    def test_summary_data_creation(self):
        from bantz.ui.jarvis_panel import SummaryData
        
        summary = SummaryData(
            title="Article Title",
            summary="This is a summary of the article.",
            key_points=["Point 1", "Point 2", "Point 3"],
            source_url="https://example.com/article"
        )
        
        assert summary.title == "Article Title"
        assert len(summary.key_points) == 3
        assert summary.source_url == "https://example.com/article"
    
    def test_summary_data_defaults(self):
        from bantz.ui.jarvis_panel import SummaryData
        
        summary = SummaryData(title="Title", summary="Summary text")
        
        assert summary.key_points == []
        assert summary.source_url == ""
        assert summary.metadata == {}


class TestPanelPosition:
    """Test PanelPosition enum and aliases."""
    
    def test_panel_positions(self):
        from bantz.ui.jarvis_panel import PanelPosition
        
        assert PanelPosition.RIGHT.value == "right"
        assert PanelPosition.LEFT.value == "left"
        assert PanelPosition.TOP_RIGHT.value == "top_right"
        assert PanelPosition.CENTER.value == "center"
    
    def test_position_aliases(self):
        from bantz.ui.jarvis_panel import PANEL_POSITION_ALIASES, PanelPosition
        
        assert PANEL_POSITION_ALIASES["sağ"] == PanelPosition.RIGHT
        assert PANEL_POSITION_ALIASES["sola"] == PanelPosition.LEFT
        assert PANEL_POSITION_ALIASES["sağ üst"] == PanelPosition.TOP_RIGHT
        assert PANEL_POSITION_ALIASES["ortaya"] == PanelPosition.CENTER


# ─────────────────────────────────────────────────────────────
# MockJarvisPanel Tests
# ─────────────────────────────────────────────────────────────

class TestMockJarvisPanel:
    """Test MockJarvisPanel for testing without Qt."""
    
    def test_initial_state(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel, PanelPosition
        
        panel = MockJarvisPanel()
        
        assert not panel.is_visible
        assert not panel.is_minimized
        assert panel.position == PanelPosition.RIGHT
    
    def test_show_results(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel
        
        panel = MockJarvisPanel()
        results = [
            {"title": "Result 1", "url": "https://example.com/1"},
            {"title": "Result 2", "url": "https://example.com/2"},
        ]
        
        panel.show_results(results, "HABERLER")
        
        assert panel.is_visible
        assert panel._results == results
        assert panel._title == "HABERLER"
        assert panel._summary is None
    
    def test_show_summary(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel
        
        panel = MockJarvisPanel()
        summary = {
            "title": "Article",
            "summary": "Summary text",
            "key_points": ["Point 1"]
        }
        
        panel.show_summary(summary)
        
        assert panel.is_visible
        assert panel._summary == summary
        assert panel._results == []
    
    def test_move_to_position(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel, PanelPosition
        
        panel = MockJarvisPanel()
        
        panel.move_to_position("sol üst")
        assert panel.position == PanelPosition.TOP_LEFT
        
        panel.move_to_position("ortaya")
        assert panel.position == PanelPosition.CENTER
    
    def test_toggle_minimize(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel
        
        panel = MockJarvisPanel()
        assert not panel.is_minimized
        
        panel.toggle_minimize()
        assert panel.is_minimized
        
        panel.toggle_minimize()
        assert not panel.is_minimized
    
    def test_show_hide(self):
        from bantz.ui.jarvis_panel import MockJarvisPanel
        
        panel = MockJarvisPanel()
        
        panel.show()
        assert panel.is_visible
        
        panel.hide()
        assert not panel.is_visible


class TestMockJarvisPanelController:
    """Test MockJarvisPanelController pagination."""
    
    def test_pagination_calculation(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.items_per_page = 5
        
        # 12 results = 3 pages
        results = [{"title": f"Result {i}"} for i in range(12)]
        controller.show_results(results)
        
        assert controller.total_pages == 3
        assert controller.current_page == 1
    
    def test_next_prev_page(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.items_per_page = 5
        results = [{"title": f"Result {i}"} for i in range(12)]
        controller.show_results(results)
        
        assert controller.current_page == 1
        
        controller.next_page()
        assert controller.current_page == 2
        
        controller.next_page()
        assert controller.current_page == 3
        
        # Can't go past last page
        controller.next_page()
        assert controller.current_page == 3
        
        controller.prev_page()
        assert controller.current_page == 2
        
        controller.prev_page()
        assert controller.current_page == 1
        
        # Can't go before first page
        controller.prev_page()
        assert controller.current_page == 1
    
    def test_get_item_by_index(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        results = [
            {"title": "First", "url": "url1"},
            {"title": "Second", "url": "url2"},
            {"title": "Third", "url": "url3"},
        ]
        controller.show_results(results)
        
        assert controller.get_item_by_index(1)["title"] == "First"
        assert controller.get_item_by_index(2)["title"] == "Second"
        assert controller.get_item_by_index(3)["title"] == "Third"
        assert controller.get_item_by_index(0) is None
        assert controller.get_item_by_index(4) is None
    
    def test_show_summary(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        results = [{"title": f"Result {i}"} for i in range(5)]
        controller.show_results(results)
        
        summary = {"title": "Summary", "summary": "Text"}
        controller.show_summary(summary)
        
        # Results cleared for summary
        assert controller._results == []
        assert controller.panel._summary == summary


# ─────────────────────────────────────────────────────────────
# NLU Pattern Tests
# ─────────────────────────────────────────────────────────────

class TestNLUPanelMovePatterns:
    """Test NLU patterns for panel move commands."""
    
    def test_panel_move_saga(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli sağa taşı")
        assert result.intent == "panel_move"
        assert "sağ" in result.slots.get("position", "").lower()
    
    def test_panel_move_sol_ust(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli sol üste götür")
        assert result.intent == "panel_move"
    
    def test_panel_move_ortaya(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli ortaya al")
        assert result.intent == "panel_move"
    
    def test_alternative_format(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("sağa taşı paneli")
        assert result.intent == "panel_move"


class TestNLUPanelHidePatterns:
    """Test NLU patterns for panel hide commands."""
    
    def test_panel_kapat(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli kapat")
        assert result.intent == "panel_hide"
    
    def test_panel_gizle(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli gizle")
        assert result.intent == "panel_hide"
    
    def test_sonuclari_kapat(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("sonuçları kapat")
        assert result.intent == "panel_hide"


class TestNLUPanelMinimizePatterns:
    """Test NLU patterns for panel minimize/maximize commands."""
    
    def test_panel_kucult(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli küçült")
        assert result.intent == "panel_minimize"
    
    def test_panel_buyut(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli büyüt")
        assert result.intent == "panel_maximize"
    
    def test_panel_goster(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneli göster")
        assert result.intent == "panel_maximize"


class TestNLUPanelPaginationPatterns:
    """Test NLU patterns for panel pagination."""
    
    def test_sonraki_sayfa(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("sonraki sayfa")
        assert result.intent == "panel_next_page"
    
    def test_panelde_sonraki(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("panelde sonraki")
        assert result.intent == "panel_next_page"
    
    def test_onceki_sayfa(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("önceki sayfa")
        assert result.intent == "panel_prev_page"
    
    def test_panelde_onceki(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("panelde önceki")
        assert result.intent == "panel_prev_page"


class TestNLUPanelSelectPatterns:
    """Test NLU patterns for panel item selection."""
    
    def test_panel_select_with_keyword(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("panelde 3. sonucu aç")
        assert result.intent == "panel_select_item"
        assert result.slots.get("index") == 3
    
    def test_panel_select_variant(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("panelden 2. sonucu seç")
        assert result.intent == "panel_select_item"
        assert result.slots.get("index") == 2
    
    def test_panel_select_deki(self):
        from bantz.router.nlu import parse_intent
        
        result = parse_intent("paneldeki 1. sonucu göster")
        assert result.intent == "panel_select_item"
        assert result.slots.get("index") == 1
    
    def test_without_panel_goes_to_news(self):
        from bantz.router.nlu import parse_intent
        
        # Without "panel" keyword, goes to news_open_result
        result = parse_intent("3. sonucu aç")
        assert result.intent == "news_open_result"


# ─────────────────────────────────────────────────────────────
# Context Panel State Tests
# ─────────────────────────────────────────────────────────────

class TestContextPanelState:
    """Test ConversationContext panel state management."""
    
    def test_panel_controller_state(self):
        from bantz.router.context import ConversationContext
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        ctx = ConversationContext()
        controller = MockJarvisPanelController()
        
        assert ctx.get_panel_controller() is None
        
        ctx.set_panel_controller(controller)
        assert ctx.get_panel_controller() is controller
    
    def test_panel_results_state(self):
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        results = [
            {"title": "Result 1", "url": "url1"},
            {"title": "Result 2", "url": "url2"},
        ]
        
        ctx.set_panel_results(results)
        
        assert ctx.get_panel_results() == results
        assert ctx.is_panel_visible()
    
    def test_panel_result_by_index(self):
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        results = [
            {"title": "First", "url": "url1"},
            {"title": "Second", "url": "url2"},
            {"title": "Third", "url": "url3"},
        ]
        ctx.set_panel_results(results)
        
        assert ctx.get_panel_result_by_index(1)["title"] == "First"
        assert ctx.get_panel_result_by_index(2)["title"] == "Second"
        assert ctx.get_panel_result_by_index(0) is None
        assert ctx.get_panel_result_by_index(4) is None
    
    def test_clear_panel(self):
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        ctx.set_panel_results([{"title": "Test"}])
        ctx.set_panel_visible(True)
        
        ctx.clear_panel()
        
        assert ctx.get_panel_results() == []
        assert not ctx.is_panel_visible()
    
    def test_snapshot_includes_panel(self):
        from bantz.router.context import ConversationContext
        
        ctx = ConversationContext()
        ctx.set_panel_results([{"title": "Test"}])
        ctx.set_panel_visible(True)
        
        snapshot = ctx.snapshot()
        
        assert "panel_visible" in snapshot
        assert "panel_results_count" in snapshot
        assert snapshot["panel_visible"] is True
        assert snapshot["panel_results_count"] == 1


# ─────────────────────────────────────────────────────────────
# Router Handler Tests
# ─────────────────────────────────────────────────────────────

class TestRouterPanelHandlers:
    """Test Router panel intent handlers."""
    
    @pytest.fixture
    def router_and_context(self):
        from bantz.router.engine import Router
        from bantz.router.policy import Policy
        from bantz.router.context import ConversationContext
        from bantz.logs.logger import JsonlLogger
        
        policy = Policy(
            intent_levels={
                "panel_move": 1,
                "panel_hide": 1,
                "panel_minimize": 1,
                "panel_maximize": 1,
                "panel_next_page": 1,
                "panel_prev_page": 1,
                "panel_select_item": 1,
            },
            deny_patterns=[],
            confirm_patterns=[],
            deny_even_if_confirmed_patterns=[],
        )
        logger = JsonlLogger(path="/dev/null")
        router = Router(policy=policy, logger=logger)
        ctx = ConversationContext()
        
        return router, ctx
    
    def test_panel_hide_no_panel(self, router_and_context):
        router, ctx = router_and_context
        
        result = router.handle("paneli kapat", ctx)
        
        # Should succeed even with no panel (already closed)
        assert result.ok is True
        assert result.intent == "panel_hide"
    
    def test_panel_move_no_position(self, router_and_context):
        router, ctx = router_and_context
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        ctx.set_panel_controller(controller)
        
        # Empty position should fail gracefully
        result = router.handle("paneli taşı", ctx)
        # Intent might not match exactly, but shouldn't crash
    
    def test_panel_select_with_results(self, router_and_context):
        router, ctx = router_and_context
        
        results = [
            {"title": "First", "url": "https://example.com/1"},
            {"title": "Second", "url": "https://example.com/2"},
        ]
        ctx.set_panel_results(results)
        
        result = router.handle("panelde 1. sonucu aç", ctx)
        
        assert result.intent == "panel_select_item"
    
    def test_panel_select_invalid_index(self, router_and_context):
        router, ctx = router_and_context
        
        results = [{"title": "Only One", "url": "url"}]
        ctx.set_panel_results(results)
        
        result = router.handle("panelde 5. sonucu aç", ctx)
        
        assert result.intent == "panel_select_item"
        assert result.ok is False


# ─────────────────────────────────────────────────────────────
# Persona Response Tests
# ─────────────────────────────────────────────────────────────

class TestPersonaPanelResponses:
    """Test Persona panel-related responses."""
    
    def test_panel_moved_response(self):
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("panel_moved")
        
        assert response is not None
        assert "efendim" in response.lower() or "panel" in response.lower()
    
    def test_panel_shown_response(self):
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("panel_shown")
        
        assert response is not None
    
    def test_panel_hidden_response(self):
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("panel_hidden")
        
        assert response is not None
    
    def test_panel_page_response(self):
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("panel_page")
        
        assert response is not None
    
    def test_panel_select_response(self):
        from bantz.llm.persona import JarvisPersona
        
        persona = JarvisPersona()
        response = persona.get_response("panel_select")
        
        assert response is not None


# ─────────────────────────────────────────────────────────────
# Types Tests
# ─────────────────────────────────────────────────────────────

class TestTypesPanelIntents:
    """Test that panel intents are properly defined in types."""
    
    def test_panel_intents_in_intent_type(self):
        from bantz.router.types import Intent
        from typing import get_args
        
        intent_values = get_args(Intent)
        
        assert "panel_move" in intent_values
        assert "panel_hide" in intent_values
        assert "panel_minimize" in intent_values
        assert "panel_maximize" in intent_values
        assert "panel_next_page" in intent_values
        assert "panel_prev_page" in intent_values
        assert "panel_select_item" in intent_values


# ─────────────────────────────────────────────────────────────
# UI Export Tests
# ─────────────────────────────────────────────────────────────

class TestUIExports:
    """Test that panel components are exported from bantz.ui."""
    
    def test_exports(self):
        from bantz.ui import (
            JarvisPanel,
            JarvisPanelController,
            PanelPosition,
            PanelColors,
            PANEL_POSITION_ALIASES,
            ResultItem,
            SummaryData,
            create_jarvis_panel,
            MockJarvisPanel,
            MockJarvisPanelController,
        )
        
        # Just verify imports work
        assert JarvisPanel is not None
        assert JarvisPanelController is not None
        assert PanelPosition is not None
        assert MockJarvisPanel is not None
        assert MockJarvisPanelController is not None


# ─────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────

class TestPanelIntegration:
    """Integration tests for panel with news and summarizer."""
    
    def test_news_results_to_panel(self):
        """Test that news results can be displayed in panel."""
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        from bantz.router.context import ConversationContext
        
        controller = MockJarvisPanelController()
        ctx = ConversationContext()
        ctx.set_panel_controller(controller)
        
        # Simulate news results
        news_results = [
            {
                "title": "Tesla hisseleri rekor kırdı",
                "source": "Bloomberg",
                "time": "2 saat önce",
                "url": "https://bloomberg.com/tesla"
            },
            {
                "title": "Yapay zeka sektöründe yeni gelişmeler",
                "source": "TechCrunch",
                "time": "3 saat önce",
                "url": "https://techcrunch.com/ai"
            },
        ]
        
        controller.show_results(news_results, "HABERLER")
        ctx.set_panel_results(news_results)
        
        assert ctx.is_panel_visible()
        assert len(ctx.get_panel_results()) == 2
        assert ctx.get_panel_result_by_index(1)["source"] == "Bloomberg"
    
    def test_summary_to_panel(self):
        """Test that page summary can be displayed in panel."""
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        
        summary = {
            "title": "Elektrikli Araç Pazarı Raporu",
            "summary": "Elektrikli araç pazarı 2024'te %40 büyüdü. Tesla lider konumunu koruyor.",
            "key_points": [
                "Pazar %40 büyüdü",
                "Tesla lider",
                "Çin üreticileri hızla yükseliyor"
            ],
            "source_url": "https://example.com/ev-report"
        }
        
        controller.show_summary(summary)
        
        assert controller.panel._summary == summary
        assert controller.panel.is_visible


class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_results(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.show_results([])
        
        assert controller.total_pages == 1
        assert controller.current_page == 1
    
    def test_single_result(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.show_results([{"title": "Single"}])
        
        assert controller.total_pages == 1
        assert controller.get_item_by_index(1)["title"] == "Single"
    
    def test_exactly_items_per_page(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.items_per_page = 5
        results = [{"title": f"Result {i}"} for i in range(5)]
        controller.show_results(results)
        
        assert controller.total_pages == 1
    
    def test_items_per_page_plus_one(self):
        from bantz.ui.jarvis_panel import MockJarvisPanelController
        
        controller = MockJarvisPanelController()
        controller.items_per_page = 5
        results = [{"title": f"Result {i}"} for i in range(6)]
        controller.show_results(results)
        
        assert controller.total_pages == 2
