"""
Tests for AdaptiveResponse.
"""

import pytest

from bantz.learning.profile import UserProfile
from bantz.learning.adaptive import (
    AdaptiveResponse,
    ResponseStyle,
    VerbosityLevel,
    FormalityLevel,
    SpeedPreference,
    create_adaptive_response,
)


class TestVerbosityLevel:
    """Tests for VerbosityLevel enum."""
    
    def test_all_levels_exist(self):
        """Test all levels are defined."""
        assert VerbosityLevel.MINIMAL
        assert VerbosityLevel.BRIEF
        assert VerbosityLevel.NORMAL
        assert VerbosityLevel.DETAILED
        assert VerbosityLevel.VERBOSE


class TestFormalityLevel:
    """Tests for FormalityLevel enum."""
    
    def test_all_levels_exist(self):
        """Test all levels are defined."""
        assert FormalityLevel.CASUAL
        assert FormalityLevel.FRIENDLY
        assert FormalityLevel.NEUTRAL
        assert FormalityLevel.FORMAL
        assert FormalityLevel.PROFESSIONAL


class TestSpeedPreference:
    """Tests for SpeedPreference enum."""
    
    def test_all_preferences_exist(self):
        """Test all preferences are defined."""
        assert SpeedPreference.FAST
        assert SpeedPreference.BALANCED
        assert SpeedPreference.THOROUGH


class TestResponseStyle:
    """Tests for ResponseStyle dataclass."""
    
    def test_create_default_style(self):
        """Test creating default style."""
        style = ResponseStyle()
        
        assert style.verbosity == VerbosityLevel.NORMAL
        assert style.formality == FormalityLevel.FRIENDLY
        assert style.speed == SpeedPreference.BALANCED
        assert style.use_emojis is True
        assert style.use_confirmations is True
    
    def test_create_custom_style(self):
        """Test creating custom style."""
        style = ResponseStyle(
            verbosity=VerbosityLevel.BRIEF,
            formality=FormalityLevel.CASUAL,
            use_emojis=False,
        )
        
        assert style.verbosity == VerbosityLevel.BRIEF
        assert style.formality == FormalityLevel.CASUAL
        assert style.use_emojis is False
    
    def test_to_dict(self):
        """Test serialization."""
        style = ResponseStyle(
            verbosity=VerbosityLevel.DETAILED,
            use_confirmations=False,
        )
        
        data = style.to_dict()
        
        assert data["verbosity"] == "detailed"
        assert data["use_confirmations"] is False
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "verbosity": "minimal",
            "formality": "formal",
            "speed": "fast",
            "use_emojis": False,
            "use_confirmations": True,
            "proactive_suggestions": False,
        }
        
        style = ResponseStyle.from_dict(data)
        
        assert style.verbosity == VerbosityLevel.MINIMAL
        assert style.formality == FormalityLevel.FORMAL
        assert style.use_emojis is False


class TestAdaptiveResponse:
    """Tests for AdaptiveResponse class."""
    
    def test_create_response(self):
        """Test creating response generator."""
        response = AdaptiveResponse()
        
        assert response.style is not None
        assert response.profile is None
    
    def test_create_with_profile(self):
        """Test creating with profile."""
        profile = UserProfile()
        response = AdaptiveResponse(profile=profile)
        
        assert response.profile == profile
    
    def test_create_with_style(self):
        """Test creating with custom style."""
        style = ResponseStyle(verbosity=VerbosityLevel.BRIEF)
        response = AdaptiveResponse(style=style)
        
        assert response.style.verbosity == VerbosityLevel.BRIEF
    
    def test_set_profile(self):
        """Test setting profile."""
        response = AdaptiveResponse()
        profile = UserProfile()
        
        response.set_profile(profile)
        
        assert response.profile == profile
    
    def test_set_style(self):
        """Test setting style."""
        response = AdaptiveResponse()
        style = ResponseStyle(formality=FormalityLevel.FORMAL)
        
        response.set_style(style)
        
        assert response.style.formality == FormalityLevel.FORMAL
    
    def test_generate_success(self):
        """Test generating success response."""
        response = AdaptiveResponse()
        
        text = response.generate_success("dosya kaydedildi")
        
        assert len(text) > 0
        assert "kaydedildi" in text.lower() or "tamamlandı" in text.lower()
    
    def test_generate_success_minimal(self):
        """Test minimal success response."""
        style = ResponseStyle(verbosity=VerbosityLevel.MINIMAL)
        response = AdaptiveResponse(style=style)
        
        text = response.generate_success("saved")
        
        assert "✓" in text
    
    def test_generate_success_verbose(self):
        """Test verbose success response."""
        style = ResponseStyle(verbosity=VerbosityLevel.VERBOSE)
        response = AdaptiveResponse(style=style)
        
        text = response.generate_success("dosya kaydedildi", details="10 satır")
        
        assert len(text) > 20  # Should be longer
    
    def test_generate_error(self):
        """Test generating error response."""
        response = AdaptiveResponse()
        
        text = response.generate_error("bağlantı hatası")
        
        assert "hata" in text.lower() or "bağlantı" in text.lower()
    
    def test_generate_confirm(self):
        """Test generating confirmation."""
        response = AdaptiveResponse()
        
        text = response.generate_confirm("dosyayı sil")
        
        assert len(text) > 0
        assert "?" in text or "mi" in text
    
    def test_generate_confirm_disabled(self):
        """Test confirm returns empty when disabled."""
        style = ResponseStyle(use_confirmations=False)
        response = AdaptiveResponse(style=style)
        
        text = response.generate_confirm("delete")
        
        assert text == ""
    
    def test_generate_info(self):
        """Test generating info response."""
        response = AdaptiveResponse()
        
        text = response.generate_info("sistem bilgisi")
        
        assert len(text) > 0
    
    def test_generate_suggestion(self):
        """Test generating suggestion."""
        response = AdaptiveResponse()
        
        text = response.generate_suggestion("tarayıcı aç")
        
        assert len(text) > 0
        assert "💡" in text or "öneri" in text.lower()
    
    def test_generate_suggestion_disabled(self):
        """Test suggestion returns empty when disabled."""
        style = ResponseStyle(proactive_suggestions=False)
        response = AdaptiveResponse(style=style)
        
        text = response.generate_suggestion("do something")
        
        assert text == ""
    
    def test_formality_casual(self):
        """Test casual formality."""
        style = ResponseStyle(formality=FormalityLevel.CASUAL)
        response = AdaptiveResponse(style=style)
        
        text = response.generate("success", {"action": "test"})
        
        # Casual should use shorter forms
        assert len(text) > 0
    
    def test_formality_formal(self):
        """Test formal formality."""
        style = ResponseStyle(formality=FormalityLevel.FORMAL)
        response = AdaptiveResponse(style=style)
        
        text = response.generate("success", {"action": "test"})
        
        # Should have formal text
        assert len(text) > 0
    
    def test_emoji_removal(self):
        """Test emoji removal when disabled."""
        style = ResponseStyle(
            verbosity=VerbosityLevel.VERBOSE,
            use_emojis=False,
        )
        response = AdaptiveResponse(style=style)
        
        text = response.generate_success("test")
        
        # Should not have emojis
        assert "🎉" not in text
        assert "💡" not in text
    
    def test_should_confirm_destructive(self):
        """Test should confirm for destructive actions."""
        response = AdaptiveResponse()
        
        assert response.should_confirm("delete") is True
        assert response.should_confirm("remove") is True
        assert response.should_confirm("reset") is True
    
    def test_should_confirm_disabled(self):
        """Test should confirm when disabled."""
        style = ResponseStyle(use_confirmations=False)
        response = AdaptiveResponse(style=style)
        
        assert response.should_confirm("delete") is False
    
    def test_add_custom_template(self):
        """Test adding custom template."""
        response = AdaptiveResponse()
        
        response.add_custom_template(
            "success",
            VerbosityLevel.NORMAL,
            "Custom: {action} oldu!",
        )
        
        text = response.generate_success("test")
        
        assert "Custom" in text
    
    def test_sync_style_from_profile(self):
        """Test style syncs from profile."""
        profile = UserProfile(
            verbosity_preference=0.1,  # Minimal
            formality_preference=0.9,  # Professional
            confirmation_preference=0.3,  # Don't confirm
        )
        response = AdaptiveResponse(profile=profile)
        
        assert response.style.verbosity == VerbosityLevel.MINIMAL
        assert response.style.formality == FormalityLevel.PROFESSIONAL
        assert response.style.use_confirmations is False
    
    def test_to_dict(self):
        """Test serialization."""
        response = AdaptiveResponse()
        
        response.add_custom_template("test", VerbosityLevel.NORMAL, "Custom")
        
        data = response.to_dict()
        
        assert "style" in data
        assert "custom_templates" in data
    
    def test_from_dict(self):
        """Test deserialization."""
        response = AdaptiveResponse()
        
        data = {
            "style": {
                "verbosity": "brief",
                "formality": "casual",
                "speed": "fast",
                "use_emojis": True,
                "use_confirmations": True,
                "proactive_suggestions": True,
            },
            "custom_templates": {},
        }
        
        response.from_dict(data)
        
        assert response.style.verbosity == VerbosityLevel.BRIEF


class TestProfileIntegration:
    """Tests for profile integration."""
    
    def test_verbosity_from_profile(self):
        """Test verbosity derived from profile."""
        test_cases = [
            (0.1, VerbosityLevel.MINIMAL),
            (0.3, VerbosityLevel.BRIEF),
            (0.5, VerbosityLevel.NORMAL),
            (0.7, VerbosityLevel.DETAILED),
            (0.9, VerbosityLevel.VERBOSE),
        ]
        
        for pref, expected in test_cases:
            profile = UserProfile(verbosity_preference=pref)
            response = AdaptiveResponse(profile=profile)
            
            assert response.style.verbosity == expected, f"Failed for pref={pref}"
    
    def test_formality_from_profile(self):
        """Test formality derived from profile."""
        test_cases = [
            (0.1, FormalityLevel.CASUAL),
            (0.3, FormalityLevel.FRIENDLY),
            (0.5, FormalityLevel.NEUTRAL),
            (0.7, FormalityLevel.FORMAL),
            (0.9, FormalityLevel.PROFESSIONAL),
        ]
        
        for pref, expected in test_cases:
            profile = UserProfile(formality_preference=pref)
            response = AdaptiveResponse(profile=profile)
            
            assert response.style.formality == expected, f"Failed for pref={pref}"
    
    def test_speed_from_profile(self):
        """Test speed derived from profile."""
        fast = UserProfile(speed_preference=0.9)
        slow = UserProfile(speed_preference=0.1)
        
        fast_response = AdaptiveResponse(profile=fast)
        slow_response = AdaptiveResponse(profile=slow)
        
        assert fast_response.style.speed == SpeedPreference.FAST
        assert slow_response.style.speed == SpeedPreference.THOROUGH


class TestFactory:
    """Tests for factory function."""
    
    def test_create_adaptive_response(self):
        """Test factory function."""
        response = create_adaptive_response()
        
        assert response is not None
        assert isinstance(response, AdaptiveResponse)
    
    def test_create_with_profile(self):
        """Test factory with profile."""
        profile = UserProfile()
        response = create_adaptive_response(profile=profile)
        
        assert response.profile == profile
    
    def test_create_with_style(self):
        """Test factory with style."""
        style = ResponseStyle(verbosity=VerbosityLevel.DETAILED)
        response = create_adaptive_response(style=style)
        
        assert response.style.verbosity == VerbosityLevel.DETAILED
