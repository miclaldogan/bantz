"""Site Profiles System for Bantz Browser.

Provides domain-specific automation profiles for common websites.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Default profiles path
DEFAULT_PROFILES_PATH = Path(__file__).parent.parent.parent.parent / "config" / "site_profiles.json"


@dataclass
class SiteProfile:
    """A site automation profile."""
    name: str
    domains: List[str]
    description: str = ""
    auto_scan: bool = True
    scan_delay: int = 1500
    selectors: Dict[str, str] = field(default_factory=dict)
    actions: Dict[str, Dict] = field(default_factory=dict)
    risks: Dict[str, List[str]] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiteProfile":
        return cls(
            name=data.get("name", "Unknown"),
            domains=data.get("domains", []),
            description=data.get("description", ""),
            auto_scan=data.get("autoScan", True),
            scan_delay=data.get("scanDelay", 1500),
            selectors=data.get("selectors", {}),
            actions=data.get("actions", {}),
            risks=data.get("risks", {}),
        )
    
    def matches_url(self, url: str) -> bool:
        """Check if profile matches a URL."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.domains)
    
    def get_action(self, action_name: str) -> Optional[Dict]:
        """Get action definition by name."""
        return self.actions.get(action_name)
    
    def is_risky_action(self, action_name: str) -> bool:
        """Check if action requires confirmation."""
        confirm_list = self.risks.get("confirm", [])
        return any(risk in action_name.lower() for risk in confirm_list)


class SiteProfileManager:
    """Manager for site profiles."""
    
    def __init__(self, profiles_path: Optional[Path] = None):
        self.profiles_path = profiles_path or DEFAULT_PROFILES_PATH
        self._profiles: Dict[str, SiteProfile] = {}
        self._load_profiles()
    
    def _load_profiles(self) -> None:
        """Load profiles from JSON file."""
        if not self.profiles_path.exists():
            logger.warning(f"Profiles file not found: {self.profiles_path}")
            return
        
        try:
            with open(self.profiles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            profiles_data = data.get("profiles", {})
            for domain, profile_data in profiles_data.items():
                profile = SiteProfile.from_dict(profile_data)
                self._profiles[domain] = profile
                # Also index by all domains
                for d in profile.domains:
                    self._profiles[d] = profile
            
            logger.info(f"Loaded {len(profiles_data)} site profiles")
        except Exception as e:
            logger.error(f"Failed to load profiles: {e}")
    
    def get_profile(self, url: str) -> Optional[SiteProfile]:
        """Get profile for a URL."""
        url_lower = url.lower()
        
        # Direct domain lookup
        for domain, profile in self._profiles.items():
            if domain in url_lower:
                return profile
        
        return None
    
    def get_profile_by_name(self, name: str) -> Optional[SiteProfile]:
        """Get profile by site name."""
        name_lower = name.lower()
        
        for profile in self._profiles.values():
            if profile.name.lower() == name_lower:
                return profile
            if any(name_lower in d for d in profile.domains):
                return profile
        
        return None
    
    def list_profiles(self) -> List[str]:
        """List all available profile names."""
        seen = set()
        names = []
        for profile in self._profiles.values():
            if profile.name not in seen:
                seen.add(profile.name)
                names.append(profile.name)
        return sorted(names)
    
    def reload(self) -> None:
        """Reload profiles from file."""
        self._profiles.clear()
        self._load_profiles()


class ProfileActionExecutor:
    """Executes profile actions on a Playwright page."""
    
    def __init__(self, page):
        self.page = page
    
    def execute_action(
        self, 
        profile: SiteProfile, 
        action_name: str,
        variables: Dict[str, str] = None
    ) -> tuple[bool, str]:
        """Execute a profile action.
        
        Args:
            profile: Site profile
            action_name: Name of action to execute
            variables: Variables to substitute (e.g., {"prompt": "Hello"})
        
        Returns:
            (success, message)
        """
        action = profile.get_action(action_name)
        if not action:
            return False, f"Action '{action_name}' not found"
        
        steps = action.get("steps", [])
        if not steps:
            return False, f"No steps defined for '{action_name}'"
        
        variables = variables or {}
        
        try:
            for i, step in enumerate(steps):
                step_action = step.get("action", "")
                
                # Substitute variables in selector and text
                selector = self._substitute(step.get("selector", ""), variables)
                text = self._substitute(step.get("text", ""), variables)
                
                if step_action == "wait":
                    timeout = step.get("timeout", 5000)
                    if selector:
                        self.page.wait_for_selector(selector, timeout=timeout)
                    elif step.get("ms"):
                        import time
                        time.sleep(step["ms"] / 1000)
                
                elif step_action == "click":
                    self.page.locator(selector).first.click(timeout=5000)
                
                elif step_action == "type":
                    self.page.keyboard.type(text)
                
                elif step_action == "press":
                    key = step.get("key", "Enter")
                    self.page.keyboard.press(key)
                
                elif step_action == "clear":
                    self.page.keyboard.press("Control+a")
                    self.page.keyboard.press("Backspace")
                
                elif step_action == "getText":
                    el = self.page.locator(selector).first
                    return True, el.text_content()
                
                elif step_action == "fill":
                    self.page.locator(selector).first.fill(text, timeout=5000)
                
                else:
                    logger.warning(f"Unknown action: {step_action}")
            
            return True, f"'{action_name}' completed"
            
        except Exception as e:
            return False, f"'{action_name}' failed: {e}"
    
    def _substitute(self, template: str, variables: Dict[str, str]) -> str:
        """Substitute ${var} placeholders in template."""
        if not template or not variables:
            return template
        
        result = template
        for key, value in variables.items():
            result = result.replace(f"${{{key}}}", value)
        
        return result


# Global manager instance
_manager: Optional[SiteProfileManager] = None


def get_profile_manager() -> SiteProfileManager:
    """Get the global profile manager."""
    global _manager
    if _manager is None:
        _manager = SiteProfileManager()
    return _manager


def get_profile_for_url(url: str) -> Optional[SiteProfile]:
    """Convenience function to get profile for URL."""
    return get_profile_manager().get_profile(url)


def execute_profile_action(
    page,
    url: str,
    action_name: str,
    variables: Dict[str, str] = None
) -> tuple[bool, str]:
    """Convenience function to execute a profile action."""
    profile = get_profile_for_url(url)
    if not profile:
        return False, f"No profile found for '{url}'"
    
    executor = ProfileActionExecutor(page)
    return executor.execute_action(profile, action_name, variables)
