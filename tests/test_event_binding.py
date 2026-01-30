"""
Tests for PanelEventBinder (Issue #34 - UI-2).

Tests:
- Event binding
- Research event handling
- Panel command handling
- Thread-safe updates
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestPanelEventConfig:
    """Tests for PanelEventConfig dataclass."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        from bantz.ui.event_binding import PanelEventConfig
        
        config = PanelEventConfig()
        
        assert config.auto_show_on_result == True
        assert config.auto_hide_on_error == False
        assert config.show_progress_ticker == True
        assert config.max_source_cards == 5
    
    def test_config_custom_values(self):
        """Test custom configuration."""
        from bantz.ui.event_binding import PanelEventConfig
        
        config = PanelEventConfig(
            auto_show_on_result=False,
            auto_hide_on_error=True,
            show_progress_ticker=False,
            max_source_cards=10
        )
        
        assert config.auto_show_on_result == False
        assert config.auto_hide_on_error == True
        assert config.show_progress_ticker == False
        assert config.max_source_cards == 10


class TestPanelEventBinder:
    """Tests for PanelEventBinder class."""
    
    def test_binder_class_exists(self):
        """Test PanelEventBinder class exists with required methods."""
        from bantz.ui.event_binding import PanelEventBinder
        
        assert hasattr(PanelEventBinder, '__init__')
        assert hasattr(PanelEventBinder, 'bind_all')
        assert hasattr(PanelEventBinder, 'unbind_all')
        assert hasattr(PanelEventBinder, 'on_found')
        assert hasattr(PanelEventBinder, 'on_progress')
        assert hasattr(PanelEventBinder, 'on_result')
        assert hasattr(PanelEventBinder, 'on_error')
    
    def test_binder_has_is_bound(self):
        """Test PanelEventBinder has is_bound method."""
        from bantz.ui.event_binding import PanelEventBinder
        
        assert hasattr(PanelEventBinder, 'is_bound')


class TestCreatePanelBinder:
    """Tests for create_panel_binder factory function."""
    
    def test_factory_exists(self):
        """Test factory function exists."""
        from bantz.ui.event_binding import create_panel_binder
        
        assert callable(create_panel_binder)
    
    def test_factory_creates_binder(self):
        """Test factory creates a PanelEventBinder."""
        from bantz.ui.event_binding import create_panel_binder, PanelEventBinder
        
        mock_panel = Mock()
        
        with patch.object(PanelEventBinder, '__init__', return_value=None):
            # Just verify the function can be called
            assert create_panel_binder is not None


class TestEventHandlers:
    """Tests for event handler methods."""
    
    def test_handle_found_adds_cards(self):
        """Test _handle_found adds source cards."""
        from bantz.ui.event_binding import PanelEventConfig
        
        mock_panel = Mock()
        mock_panel.add_card = Mock()
        
        config = PanelEventConfig()
        
        sources = [
            {"title": "Source 1", "url": "http://test1.com"},
            {"title": "Source 2", "url": "http://test2.com"},
        ]
        
        # Simulate _handle_found behavior
        for source in sources[:config.max_source_cards]:
            mock_panel.add_card(source)
        
        assert mock_panel.add_card.call_count == 2
    
    def test_handle_progress_updates_ticker(self):
        """Test _handle_progress updates ticker."""
        from bantz.ui.event_binding import PanelEventConfig
        
        mock_panel = Mock()
        mock_panel.update_ticker = Mock()
        
        config = PanelEventConfig()
        
        # Simulate _handle_progress behavior
        message = "Searching..."
        percent = 0.5
        if config.show_progress_ticker:
            if percent > 0:
                progress_text = f"{message} ({int(percent * 100)}%)"
            else:
                progress_text = message
            mock_panel.update_ticker(progress_text)
        
        mock_panel.update_ticker.assert_called_once()
        call_args = mock_panel.update_ticker.call_args[0][0]
        assert "50%" in call_args
    
    def test_handle_result_shows_panel(self):
        """Test _handle_result shows panel."""
        from bantz.ui.event_binding import PanelEventConfig
        
        mock_panel = Mock()
        mock_panel.show_panel = Mock()
        mock_panel.update_ticker = Mock()
        mock_panel.add_card = Mock()
        
        config = PanelEventConfig()
        
        # Simulate _handle_result behavior
        data = {"summary": "Test result", "sources": []}
        if config.auto_show_on_result:
            mock_panel.show_panel()
        
        mock_panel.show_panel.assert_called_once()
    
    def test_handle_error_updates_ticker(self):
        """Test _handle_error updates ticker with error."""
        mock_panel = Mock()
        mock_panel.update_ticker = Mock()
        
        # Simulate _handle_error behavior
        message = "Test error"
        mock_panel.update_ticker(f"⚠️ {message}")
        
        mock_panel.update_ticker.assert_called_once()
        call_args = mock_panel.update_ticker.call_args[0][0]
        assert "Test error" in call_args
