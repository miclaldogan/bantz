"""
Action Classifier for V2-5 (Issue #37).

Classifies actions into permission levels:
- LOW: Read-only, local operations
- MEDIUM: External access, first-time ask
- HIGH: Destructive, always ask

Provides context-aware classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from bantz.security.permission_level import PermissionLevel


@dataclass
class ActionClassification:
    """Result of action classification."""
    
    action: str
    level: PermissionLevel
    is_destructive: bool = False
    is_external: bool = False
    requires_confirmation: bool = False
    reason: Optional[str] = None
    
    def __post_init__(self):
        """Set requires_confirmation based on level."""
        self.requires_confirmation = self.level.requires_confirmation


class ActionClassifier:
    """
    Classifies actions into permission levels.
    
    Uses predefined mappings and context to determine
    the appropriate permission level for each action.
    """
    
    # Default action level mappings
    ACTION_LEVELS: Dict[str, PermissionLevel] = {
        # LOW - Read-only, local operations
        "browser_open": PermissionLevel.LOW,
        "web_search": PermissionLevel.LOW,
        "read_file": PermissionLevel.LOW,
        "list_dir": PermissionLevel.LOW,
        "get_time": PermissionLevel.LOW,
        "get_weather": PermissionLevel.LOW,
        "calculator": PermissionLevel.LOW,
        "translate": PermissionLevel.LOW,
        "define_word": PermissionLevel.LOW,
        "read_clipboard": PermissionLevel.MEDIUM,
        
        # MEDIUM - External access, first-time ask
        "send_email": PermissionLevel.MEDIUM,
        "calendar_access": PermissionLevel.MEDIUM,
        "calendar_create": PermissionLevel.MEDIUM,
        "post_social": PermissionLevel.MEDIUM,
        "api_call": PermissionLevel.MEDIUM,
        "write_file": PermissionLevel.MEDIUM,
        "create_file": PermissionLevel.MEDIUM,
        "download_file": PermissionLevel.MEDIUM,
        "install_package": PermissionLevel.MEDIUM,
        "git_commit": PermissionLevel.MEDIUM,
        "git_push": PermissionLevel.MEDIUM,
        
        # HIGH - Destructive, always ask
        "delete_file": PermissionLevel.HIGH,
        "delete_directory": PermissionLevel.HIGH,
        "make_payment": PermissionLevel.HIGH,
        "send_message": PermissionLevel.HIGH,
        "execute_command": PermissionLevel.HIGH,
        "run_script": PermissionLevel.HIGH,
        "system_shutdown": PermissionLevel.HIGH,
        "format_disk": PermissionLevel.HIGH,
        "modify_system": PermissionLevel.HIGH,
        "access_credentials": PermissionLevel.HIGH,
        "share_screen": PermissionLevel.HIGH,
        "remote_access": PermissionLevel.HIGH,
    }
    
    # Destructive actions
    DESTRUCTIVE_ACTIONS: Set[str] = {
        "delete_file",
        "delete_directory",
        "format_disk",
        "system_shutdown",
        "modify_system",
        "make_payment",
    }
    
    # External/network actions
    EXTERNAL_ACTIONS: Set[str] = {
        "send_email",
        "post_social",
        "send_message",
        "api_call",
        "download_file",
        "upload_file",
        "git_push",
        "share_screen",
        "remote_access",
    }
    
    def __init__(
        self,
        custom_levels: Optional[Dict[str, PermissionLevel]] = None,
        default_level: PermissionLevel = PermissionLevel.HIGH
    ):
        """
        Initialize classifier.
        
        Args:
            custom_levels: Custom action-level mappings
            default_level: Default level for unknown actions
        """
        self._levels = dict(self.ACTION_LEVELS)
        if custom_levels:
            self._levels.update(custom_levels)
        
        self._default_level = default_level
    
    def classify(
        self,
        action: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ActionClassification:
        """
        Classify an action into a permission level.
        
        Args:
            action: Action to classify (string or Enum with .value)
            context: Optional context for elevation
            
        Returns:
            ActionClassification result
        """
        context = context or {}
        
        # Normalise: accept Enum members as well as plain strings
        if hasattr(action, "value"):
            action = action.value
        
        # Get base level
        base_level = self._levels.get(action, self._default_level)
        
        # Check for elevation from context
        level = self._check_elevation(action, base_level, context)
        
        # Determine flags
        is_destructive = self.is_destructive(action)
        is_external = self.is_external(action)
        
        # Build reason — include elevation info when level was raised
        if action not in self._levels:
            reason = f"Unknown action, using default: {self._default_level.value}"
        elif level is not base_level:
            reason = (
                f"Mapped action: {action} → {base_level.value}, "
                f"elevated to {level.value} by context"
            )
        else:
            reason = f"Mapped action: {action} → {level.value}"
        
        return ActionClassification(
            action=action,
            level=level,
            is_destructive=is_destructive,
            is_external=is_external,
            reason=reason
        )
    
    def _check_elevation(
        self,
        action: str,
        base_level: PermissionLevel,
        context: Dict[str, Any]
    ) -> PermissionLevel:
        """
        Check if context requires level elevation.
        
        Context can elevate but never lower the level.
        """
        level = base_level
        
        # Sensitive domain elevation
        if context.get("domain") in ["banking", "medical", "legal"]:
            if level < PermissionLevel.HIGH:
                level = PermissionLevel.HIGH
        
        # Large amount elevation
        if context.get("amount", 0) > 1000:
            if level < PermissionLevel.HIGH:
                level = PermissionLevel.HIGH
        
        # Multiple targets elevation
        if context.get("target_count", 1) > 10:
            if level < PermissionLevel.MEDIUM:
                level = PermissionLevel.MEDIUM
        
        # Sensitive file elevation
        if context.get("is_sensitive_file", False):
            if level < PermissionLevel.HIGH:
                level = PermissionLevel.HIGH
        
        return level
    
    def is_destructive(self, action: str) -> bool:
        """Check if action is destructive."""
        if hasattr(action, "value"):
            action = action.value
        return action in self.DESTRUCTIVE_ACTIONS
    
    def is_external(self, action: str) -> bool:
        """Check if action involves external access."""
        if hasattr(action, "value"):
            action = action.value
        return action in self.EXTERNAL_ACTIONS
    
    def get_level(self, action: str) -> PermissionLevel:
        """Get level for action (without context)."""
        if hasattr(action, "value"):
            action = action.value
        return self._levels.get(action, self._default_level)
    
    def add_action(self, action: str, level: PermissionLevel) -> None:
        """Add or update action level mapping."""
        self._levels[action] = level
    
    def remove_action(self, action: str) -> bool:
        """Remove action mapping."""
        if action in self._levels:
            del self._levels[action]
            return True
        return False
    
    @property
    def known_actions(self) -> List[str]:
        """Get list of all known actions."""
        return list(self._levels.keys())
    
    @property
    def low_actions(self) -> List[str]:
        """Get LOW level actions."""
        return [a for a, l in self._levels.items() if l == PermissionLevel.LOW]
    
    @property
    def medium_actions(self) -> List[str]:
        """Get MEDIUM level actions."""
        return [a for a, l in self._levels.items() if l == PermissionLevel.MEDIUM]
    
    @property
    def high_actions(self) -> List[str]:
        """Get HIGH level actions."""
        return [a for a, l in self._levels.items() if l == PermissionLevel.HIGH]


def create_action_classifier(
    custom_levels: Optional[Dict[str, PermissionLevel]] = None,
    default_level: PermissionLevel = PermissionLevel.HIGH
) -> ActionClassifier:
    """Factory for creating action classifier."""
    return ActionClassifier(
        custom_levels=custom_levels,
        default_level=default_level
    )
