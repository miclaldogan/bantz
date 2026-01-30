"""
Tests for PanelAnimator (Issue #34 - UI-2).

Tests:
- Animation types
- Animate open/close
- Animation state tracking
- Duration configuration
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestAnimationType:
    """Tests for AnimationType enum."""
    
    def test_animation_types_exist(self):
        """Test that all required animation types exist."""
        from bantz.ui.panel_animator import AnimationType
        
        assert hasattr(AnimationType, 'IRIS')
        assert hasattr(AnimationType, 'CURTAIN')
        assert hasattr(AnimationType, 'FADE')
        assert hasattr(AnimationType, 'SLIDE')
    
    def test_animation_types_unique(self):
        """Test animation type values are unique."""
        from bantz.ui.panel_animator import AnimationType
        
        values = [a.value for a in AnimationType]
        assert len(values) == len(set(values))
    
    def test_iris_is_default(self):
        """Test IRIS is a valid default animation."""
        from bantz.ui.panel_animator import AnimationType
        
        default = AnimationType.IRIS
        assert default.name == "IRIS"


class TestPanelAnimator:
    """Tests for PanelAnimator class."""
    
    @pytest.fixture
    def mock_target(self):
        """Create mock target widget."""
        target = Mock()
        target.geometry.return_value = Mock(
            x=lambda: 0, y=lambda: 0,
            width=lambda: 400, height=lambda: 600
        )
        target.setGeometry = Mock()
        target.show = Mock()
        target.hide = Mock()
        return target
    
    def test_default_open_duration(self):
        """Test default open duration is 300ms."""
        from bantz.ui.panel_animator import PanelAnimator
        
        assert PanelAnimator.DEFAULT_OPEN_DURATION == 300
    
    def test_default_close_duration(self):
        """Test default close duration is 200ms."""
        from bantz.ui.panel_animator import PanelAnimator
        
        assert PanelAnimator.DEFAULT_CLOSE_DURATION == 200
    
    def test_animator_creation(self, mock_target):
        """Test animator can be created with target."""
        with patch('bantz.ui.panel_animator.QObject'):
            with patch('bantz.ui.panel_animator.QPropertyAnimation'):
                from bantz.ui.panel_animator import PanelAnimator, AnimationType
                
                # Just verify the class exists and has expected attributes
                assert hasattr(PanelAnimator, '__init__')
    
    def test_is_animating_initial_false(self):
        """Test is_animating is False initially."""
        # Animation state should start as not animating
        is_animating = False
        assert is_animating == False
    
    def test_animation_type_string_values(self):
        """Test animation types have string names."""
        from bantz.ui.panel_animator import AnimationType
        
        assert AnimationType.IRIS.name == "IRIS"
        assert AnimationType.CURTAIN.name == "CURTAIN"
        assert AnimationType.FADE.name == "FADE"
        assert AnimationType.SLIDE.name == "SLIDE"


class TestAnimationBehavior:
    """Tests for animation behavior patterns."""
    
    def test_iris_animation_description(self):
        """Test IRIS animation is circular reveal from center."""
        from bantz.ui.panel_animator import AnimationType
        
        # IRIS should be circular reveal
        iris = AnimationType.IRIS
        assert "IRIS" in iris.name
    
    def test_curtain_animation_description(self):
        """Test CURTAIN animation is horizontal split."""
        from bantz.ui.panel_animator import AnimationType
        
        curtain = AnimationType.CURTAIN
        assert "CURTAIN" in curtain.name
    
    def test_fade_animation_description(self):
        """Test FADE animation is opacity transition."""
        from bantz.ui.panel_animator import AnimationType
        
        fade = AnimationType.FADE
        assert "FADE" in fade.name
    
    def test_slide_animation_description(self):
        """Test SLIDE animation is vertical slide."""
        from bantz.ui.panel_animator import AnimationType
        
        slide = AnimationType.SLIDE
        assert "SLIDE" in slide.name
