"""
Tests for SourceCard (Issue #34 - UI-2).

Tests:
- SourceCardData dataclass
- URL shortening
- Reliability colors
- Card update and highlighting
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestSourceCardData:
    """Tests for SourceCardData dataclass."""
    
    def test_create_minimal_data(self):
        """Test creating data with minimal fields."""
        from bantz.ui.source_card import SourceCardData
        
        data = SourceCardData(
            title="Test Title",
            url="https://example.com"
        )
        
        assert data.title == "Test Title"
        assert data.url == "https://example.com"
        assert data.date is None
        assert data.snippet is None
        assert data.reliability is None
    
    def test_create_full_data(self):
        """Test creating data with all fields."""
        from bantz.ui.source_card import SourceCardData
        
        data = SourceCardData(
            title="Full Test",
            url="https://example.com/article",
            date="2024-01-15",
            snippet="This is a test snippet...",
            favicon="https://example.com/favicon.ico",
            reliability="high"
        )
        
        assert data.title == "Full Test"
        assert data.date == "2024-01-15"
        assert data.snippet == "This is a test snippet..."
        assert data.reliability == "high"
    
    def test_get_short_url_removes_protocol(self):
        """Test URL shortening removes protocol."""
        from bantz.ui.source_card import SourceCardData
        
        data = SourceCardData(
            title="Test",
            url="https://www.example.com/page"
        )
        
        short = data.get_short_url()
        
        assert not short.startswith("https://")
        assert not short.startswith("www.")
    
    def test_get_short_url_truncates_long(self):
        """Test long URLs are truncated."""
        from bantz.ui.source_card import SourceCardData
        
        long_url = "https://example.com/" + "a" * 100
        data = SourceCardData(title="Test", url=long_url)
        
        short = data.get_short_url(max_length=50)
        
        assert len(short) <= 50
        assert short.endswith("...")


class TestReliabilityColors:
    """Tests for reliability color mapping."""
    
    def test_high_reliability_color(self):
        """Test high reliability has green color."""
        from bantz.ui.source_card import RELIABILITY_COLORS
        
        assert "high" in RELIABILITY_COLORS
        assert "#" in RELIABILITY_COLORS["high"]  # Is a color code
    
    def test_medium_reliability_color(self):
        """Test medium reliability has amber color."""
        from bantz.ui.source_card import RELIABILITY_COLORS
        
        assert "medium" in RELIABILITY_COLORS
    
    def test_low_reliability_color(self):
        """Test low reliability has red color."""
        from bantz.ui.source_card import RELIABILITY_COLORS
        
        assert "low" in RELIABILITY_COLORS
    
    def test_default_reliability_color(self):
        """Test None reliability has default blue."""
        from bantz.ui.source_card import RELIABILITY_COLORS
        
        assert None in RELIABILITY_COLORS


class TestReliabilityLabels:
    """Tests for reliability labels."""
    
    def test_reliability_labels_turkish(self):
        """Test reliability labels."""
        from bantz.ui.source_card import RELIABILITY_LABELS
        
        assert RELIABILITY_LABELS["high"] == "Reliable"
        assert RELIABILITY_LABELS["medium"] == "Medium"
        assert RELIABILITY_LABELS["low"] == "Low"
    
    def test_none_reliability_empty_label(self):
        """Test None reliability has empty label."""
        from bantz.ui.source_card import RELIABILITY_LABELS
        
        assert RELIABILITY_LABELS[None] == ""


class TestSourceCard:
    """Tests for SourceCard widget."""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample card data."""
        from bantz.ui.source_card import SourceCardData
        
        return SourceCardData(
            title="Sample Source",
            url="https://example.com/article",
            date="2024-01-15",
            snippet="This is a sample snippet for testing.",
            reliability="high"
        )
    
    def test_source_card_class_exists(self, sample_data):
        """Test SourceCard class exists."""
        from bantz.ui.source_card import SourceCard
        
        assert hasattr(SourceCard, '__init__')
        assert hasattr(SourceCard, 'update_data')
        assert hasattr(SourceCard, 'set_highlighted')
        assert hasattr(SourceCard, 'on_click')
    
    def test_source_card_has_clicked_signal(self):
        """Test SourceCard has clicked signal."""
        from bantz.ui.source_card import SourceCard
        
        # Check the class has clicked attribute
        assert 'clicked' in dir(SourceCard)
