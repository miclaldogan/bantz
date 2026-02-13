"""
Adaptive Response module.

Personalizes responses based on learned user preferences.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from bantz.learning.profile import BehavioralProfile as UserProfile


class VerbosityLevel(Enum):
    """Response verbosity levels."""
    
    MINIMAL = "minimal"     # Çok kısa, sadece sonuç
    BRIEF = "brief"         # Kısa açıklama
    NORMAL = "normal"       # Standart detay
    DETAILED = "detailed"   # Detaylı açıklama
    VERBOSE = "verbose"     # Maksimum detay


class FormalityLevel(Enum):
    """Response formality levels."""
    
    CASUAL = "casual"       # Samimi, arkadaşça
    FRIENDLY = "friendly"   # Dostane
    NEUTRAL = "neutral"     # Nötr
    FORMAL = "formal"       # Resmi
    PROFESSIONAL = "professional"  # Çok resmi


class SpeedPreference(Enum):
    """User speed preference."""
    
    FAST = "fast"           # Hızlı yanıt tercih
    BALANCED = "balanced"   # Dengeli
    THOROUGH = "thorough"   # Kapsamlı tercih


@dataclass
class ResponseStyle:
    """Defines a response style configuration."""
    
    verbosity: VerbosityLevel = VerbosityLevel.NORMAL
    """How detailed responses should be."""
    
    formality: FormalityLevel = FormalityLevel.FRIENDLY
    """How formal responses should be."""
    
    speed: SpeedPreference = SpeedPreference.BALANCED
    """Speed vs thoroughness preference."""
    
    use_emojis: bool = True
    """Whether to use emojis in responses."""
    
    use_confirmations: bool = True
    """Whether to confirm before actions."""
    
    proactive_suggestions: bool = True
    """Whether to offer proactive suggestions."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "verbosity": self.verbosity.value,
            "formality": self.formality.value,
            "speed": self.speed.value,
            "use_emojis": self.use_emojis,
            "use_confirmations": self.use_confirmations,
            "proactive_suggestions": self.proactive_suggestions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResponseStyle":
        """Create from dictionary."""
        return cls(
            verbosity=VerbosityLevel(data.get("verbosity", "normal")),
            formality=FormalityLevel(data.get("formality", "friendly")),
            speed=SpeedPreference(data.get("speed", "balanced")),
            use_emojis=data.get("use_emojis", True),
            use_confirmations=data.get("use_confirmations", True),
            proactive_suggestions=data.get("proactive_suggestions", True),
        )


@dataclass
class ResponseTemplate:
    """A response template with placeholders."""
    
    template: str
    """Template string with {placeholders}."""
    
    verbosity: VerbosityLevel = VerbosityLevel.NORMAL
    """Verbosity level for this template."""
    
    formality: FormalityLevel = FormalityLevel.NEUTRAL
    """Formality level for this template."""
    
    context: str = ""
    """Context/intent this template is for."""


class AdaptiveResponse:
    """
    Generates personalized responses based on user preferences.
    
    Adapts:
    - Verbosity (brief vs detailed)
    - Formality (casual vs formal)
    - Speed (quick vs thorough)
    - Emoji usage
    - Confirmation behavior
    """
    
    # Default templates for different verbosity levels
    DEFAULT_TEMPLATES = {
        VerbosityLevel.MINIMAL: {
            "success": "✓",
            "error": "✗ {error}",
            "confirm": "{action}?",
            "info": "{info}",
        },
        VerbosityLevel.BRIEF: {
            "success": "Tamam, {action}.",
            "error": "Hata: {error}",
            "confirm": "{action} yapayım mı?",
            "info": "{info}",
        },
        VerbosityLevel.NORMAL: {
            "success": "{action} başarıyla tamamlandı.",
            "error": "Bir hata oluştu: {error}. Tekrar denemek ister misin?",
            "confirm": "{action} yapmak istediğinden emin misin?",
            "info": "İşte bilgi: {info}",
        },
        VerbosityLevel.DETAILED: {
            "success": "Harika! {action} işlemi başarıyla tamamlandı. {details}",
            "error": "Üzgünüm, bir hata oluştu: {error}. Bu genellikle {cause} nedeniyle olur. Tekrar denememi ister misin?",
            "confirm": "{action} yapmak üzereyim. Bu işlem {description}. Devam edeyim mi?",
            "info": "İşte istediğin bilgi: {info}. Daha fazla detay ister misin?",
        },
        VerbosityLevel.VERBOSE: {
            "success": "🎉 Harika haber! {action} işlemi başarıyla tamamlandı! İşte detaylar: {details}. Başka bir şey yapmamı ister misin?",
            "error": "😔 Üzgünüm, bir sorunla karşılaştım: {error}. Bu genellikle {cause} nedeniyle olabilir. Şunları deneyebiliriz: {suggestions}. Ne yapmamı istersin?",
            "confirm": "🤔 {action} yapmak üzereyim. Bu işlem şunları yapacak: {description}. Emin misin? Onaylamak için 'evet' de.",
            "info": "📚 İşte istediğin detaylı bilgi:\n\n{info}\n\nBaşka soruların varsa sormaktan çekinme!",
        },
    }
    
    # Formality transformations
    FORMALITY_TRANSFORMS = {
        FormalityLevel.CASUAL: {
            "başarıyla tamamlandı": "oldu",
            "yapmak istediğinden emin misin": "yapayım mı",
            "Bir hata oluştu": "Bi' sorun çıktı",
            "Üzgünüm": "Pardon",
        },
        FormalityLevel.FORMAL: {
            "yapayım mı": "gerçekleştirmemi ister misiniz",
            "ister misin": "ister misiniz",
            "Tamam": "Anlaşıldı",
            "oldu": "tamamlanmıştır",
        },
    }
    
    def __init__(
        self,
        profile: Optional[UserProfile] = None,
        style: Optional[ResponseStyle] = None,
    ):
        """
        Initialize adaptive response generator.
        
        Args:
            profile: User profile for personalization.
            style: Override style (or derive from profile).
        """
        self._profile = profile
        self._style = style or ResponseStyle()
        self._custom_templates: Dict[str, Dict[str, str]] = {}
        
        # Sync style from profile
        if profile:
            self._sync_style_from_profile()
    
    @property
    def profile(self) -> Optional[UserProfile]:
        """Get current profile."""
        return self._profile
    
    @property
    def style(self) -> ResponseStyle:
        """Get current style."""
        return self._style
    
    def set_profile(self, profile: UserProfile) -> None:
        """Set user profile and sync style."""
        self._profile = profile
        self._sync_style_from_profile()
    
    def set_style(self, style: ResponseStyle) -> None:
        """Set response style."""
        self._style = style
    
    def generate(
        self,
        response_type: str,
        context: Dict = None,
        override_style: Optional[ResponseStyle] = None,
    ) -> str:
        """
        Generate a personalized response.
        
        Args:
            response_type: Type of response (success, error, confirm, info).
            context: Variables to fill in template.
            override_style: Optional style override.
            
        Returns:
            Formatted response string.
        """
        context = context or {}
        style = override_style or self._style
        
        # Get template
        template = self._get_template(response_type, style.verbosity)
        
        # Fill in placeholders
        response = self._fill_template(template, context)
        
        # Apply formality
        response = self._apply_formality(response, style.formality)
        
        # Handle emojis
        if not style.use_emojis:
            response = self._remove_emojis(response)
        
        return response
    
    def generate_success(self, action: str, details: str = "", **kwargs) -> str:
        """Generate a success response."""
        return self.generate("success", {
            "action": action,
            "details": details,
            **kwargs,
        })
    
    def generate_error(
        self,
        error: str,
        cause: str = "",
        suggestions: str = "",
        **kwargs,
    ) -> str:
        """Generate an error response."""
        return self.generate("error", {
            "error": error,
            "cause": cause,
            "suggestions": suggestions,
            **kwargs,
        })
    
    def generate_confirm(
        self,
        action: str,
        description: str = "",
        **kwargs,
    ) -> str:
        """Generate a confirmation request."""
        # Check if confirmations are disabled
        if not self._style.use_confirmations:
            return ""
        
        return self.generate("confirm", {
            "action": action,
            "description": description,
            **kwargs,
        })
    
    def generate_info(self, info: str, **kwargs) -> str:
        """Generate an info response."""
        return self.generate("info", {
            "info": info,
            **kwargs,
        })
    
    def generate_suggestion(
        self,
        suggestion: str,
        reason: str = "",
    ) -> str:
        """Generate a proactive suggestion."""
        if not self._style.proactive_suggestions:
            return ""
        
        if self._style.verbosity == VerbosityLevel.MINIMAL:
            return f"💡 {suggestion}"
        elif self._style.verbosity == VerbosityLevel.BRIEF:
            return f"💡 {suggestion} diyebilirsin."
        elif self._style.verbosity == VerbosityLevel.VERBOSE:
            if reason:
                return f"💡 Bir öneri: {suggestion}. {reason}"
            return f"💡 Belki şunu denemek istersin: {suggestion}"
        else:
            return f"💡 Öneri: {suggestion}"
    
    def add_custom_template(
        self,
        response_type: str,
        verbosity: VerbosityLevel,
        template: str,
    ) -> None:
        """Add a custom template."""
        verbosity_key = verbosity.value
        
        if verbosity_key not in self._custom_templates:
            self._custom_templates[verbosity_key] = {}
        
        self._custom_templates[verbosity_key][response_type] = template
    
    def should_confirm(self, action_type: str) -> bool:
        """
        Check if an action should require confirmation.
        
        Args:
            action_type: Type of action.
            
        Returns:
            Whether to confirm.
        """
        if not self._style.use_confirmations:
            return False
        
        # Always confirm for destructive actions
        destructive = ["delete", "remove", "clear", "reset", "shutdown"]
        if action_type in destructive:
            return True
        
        # Check profile preference
        if self._profile:
            return self._profile.confirmation_preference > 0.5
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            "style": self._style.to_dict(),
            "custom_templates": self._custom_templates,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        if "style" in data:
            self._style = ResponseStyle.from_dict(data["style"])
        
        self._custom_templates = data.get("custom_templates", {})
    
    def _sync_style_from_profile(self) -> None:
        """Sync style from profile preferences."""
        if not self._profile:
            return
        
        # Verbosity from profile
        verbosity_pref = self._profile.verbosity_preference
        if verbosity_pref < 0.2:
            self._style.verbosity = VerbosityLevel.MINIMAL
        elif verbosity_pref < 0.4:
            self._style.verbosity = VerbosityLevel.BRIEF
        elif verbosity_pref < 0.6:
            self._style.verbosity = VerbosityLevel.NORMAL
        elif verbosity_pref < 0.8:
            self._style.verbosity = VerbosityLevel.DETAILED
        else:
            self._style.verbosity = VerbosityLevel.VERBOSE
        
        # Formality from profile
        formality_pref = self._profile.formality_preference
        if formality_pref < 0.2:
            self._style.formality = FormalityLevel.CASUAL
        elif formality_pref < 0.4:
            self._style.formality = FormalityLevel.FRIENDLY
        elif formality_pref < 0.6:
            self._style.formality = FormalityLevel.NEUTRAL
        elif formality_pref < 0.8:
            self._style.formality = FormalityLevel.FORMAL
        else:
            self._style.formality = FormalityLevel.PROFESSIONAL
        
        # Speed from profile
        speed_pref = self._profile.speed_preference
        if speed_pref < 0.33:
            self._style.speed = SpeedPreference.THOROUGH
        elif speed_pref < 0.66:
            self._style.speed = SpeedPreference.BALANCED
        else:
            self._style.speed = SpeedPreference.FAST
        
        # Confirmation from profile
        self._style.use_confirmations = self._profile.confirmation_preference > 0.5
        
        # Exploration/suggestions from profile
        self._style.proactive_suggestions = self._profile.exploration_tendency > 0.4
    
    def _get_template(self, response_type: str, verbosity: VerbosityLevel) -> str:
        """Get template for response type and verbosity."""
        # Check custom templates first
        verbosity_key = verbosity.value
        if verbosity_key in self._custom_templates:
            if response_type in self._custom_templates[verbosity_key]:
                return self._custom_templates[verbosity_key][response_type]
        
        # Fall back to defaults
        templates = self.DEFAULT_TEMPLATES.get(verbosity, self.DEFAULT_TEMPLATES[VerbosityLevel.NORMAL])
        return templates.get(response_type, "{info}")
    
    def _fill_template(self, template: str, context: Dict) -> str:
        """Fill template with context values."""
        result = template
        
        for key, value in context.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, str(value))
        
        # Remove unfilled placeholders
        import re
        result = re.sub(r'\{[^}]+\}', '', result)
        
        # Clean up extra spaces
        result = ' '.join(result.split())
        
        return result
    
    def _apply_formality(self, text: str, formality: FormalityLevel) -> str:
        """Apply formality transformations."""
        if formality not in self.FORMALITY_TRANSFORMS:
            return text
        
        transforms = self.FORMALITY_TRANSFORMS[formality]
        result = text
        
        for original, replacement in transforms.items():
            result = result.replace(original, replacement)
        
        return result
    
    def _remove_emojis(self, text: str) -> str:
        """Remove emojis from text.
        
        Uses non-overlapping Unicode ranges to avoid CodeQL security warnings.
        Covers most common emoji blocks without character class overlap.
        """
        import re
        
        # Use separate patterns to avoid overlapping ranges (CodeQL alerts #17-20)
        # Each block is processed independently for safety
        patterns = [
            r"[\U0001F600-\U0001F64F]",  # Emoticons
            r"[\U0001F300-\U0001F5FF]",  # Symbols & Pictographs
            r"[\U0001F680-\U0001F6FF]",  # Transport & Map
            r"[\U0001F1E0-\U0001F1FF]",  # Flags
            r"[\U00002702-\U000027B0]",  # Dingbats
            r"[\U0001F900-\U0001F9FF]",  # Supplemental Symbols
        ]
        
        result = text
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.UNICODE)
        
        return result.strip()


def create_adaptive_response(
    profile: Optional[UserProfile] = None,
    style: Optional[ResponseStyle] = None,
) -> AdaptiveResponse:
    """
    Factory function to create an adaptive response generator.
    
    Args:
        profile: User profile for personalization.
        style: Override style.
        
    Returns:
        Configured AdaptiveResponse instance.
    """
    return AdaptiveResponse(
        profile=profile,
        style=style,
    )
