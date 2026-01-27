"""
Plugin Configuration.

YAML-based configuration management for plugins:
- Per-plugin settings
- Global plugin settings
- Enable/disable state
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import logging
import os

logger = logging.getLogger(__name__)


@dataclass
class PluginConfig:
    """Configuration for a single plugin."""
    
    enabled: bool = True
    settings: Dict[str, Any] = field(default_factory=dict)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a setting value."""
        self.settings[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            **self.settings,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginConfig":
        """Create from dictionary."""
        enabled = data.pop("enabled", True)
        return cls(enabled=enabled, settings=data)


@dataclass
class PluginsConfig:
    """
    Global plugins configuration.
    
    Stores:
    - List of enabled plugins
    - List of disabled plugins
    - Per-plugin settings
    
    Example YAML:
        enabled:
          - spotify
          - notion
        
        disabled:
          - experimental
        
        settings:
          spotify:
            client_id: "xxx"
            client_secret: "xxx"
          
          notion:
            api_key: "xxx"
    """
    
    enabled: List[str] = field(default_factory=list)
    disabled: List[str] = field(default_factory=list)
    settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auto_load: bool = True
    auto_discover: bool = True
    
    @classmethod
    def get_default_path(cls) -> Path:
        """Get default config file path."""
        config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        return Path(config_home) / "bantz" / "plugins.yaml"
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PluginsConfig":
        """
        Load configuration from YAML file.
        
        Args:
            path: Path to config file
            
        Returns:
            Loaded configuration
        """
        if path is None:
            path = cls.get_default_path()
        
        path = Path(path)
        
        if not path.exists():
            logger.debug(f"Config file not found: {path}")
            return cls()
        
        try:
            # Try yaml first
            try:
                import yaml
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
            except ImportError:
                # Fall back to simple parsing
                data = cls._parse_simple_yaml(path)
            
            return cls.from_dict(data)
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return cls()
    
    @classmethod
    def _parse_simple_yaml(cls, path: Path) -> Dict[str, Any]:
        """Simple YAML-like parsing without yaml library."""
        data: Dict[str, Any] = {
            "enabled": [],
            "disabled": [],
            "settings": {},
        }
        
        content = path.read_text()
        current_section = None
        current_plugin = None
        
        for line in content.split("\n"):
            line = line.rstrip()
            
            if not line or line.startswith("#"):
                continue
            
            # Section headers
            if line in ("enabled:", "disabled:", "settings:"):
                current_section = line[:-1]
                current_plugin = None
                continue
            
            # List items
            if line.startswith("  - "):
                item = line[4:].strip()
                if current_section in ("enabled", "disabled"):
                    data[current_section].append(item)
                continue
            
            # Nested settings
            if line.startswith("  ") and not line.startswith("    "):
                if current_section == "settings":
                    if line.endswith(":"):
                        current_plugin = line.strip()[:-1]
                        data["settings"][current_plugin] = {}
                continue
            
            # Setting values
            if line.startswith("    ") and current_plugin:
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    data["settings"][current_plugin][key] = value
        
        return data
    
    def save(self, path: Optional[Path] = None) -> bool:
        """
        Save configuration to YAML file.
        
        Args:
            path: Path to config file
            
        Returns:
            True if saved successfully
        """
        if path is None:
            path = self.get_default_path()
        
        path = Path(path)
        
        try:
            # Ensure directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Try yaml first
            try:
                import yaml
                with open(path, "w") as f:
                    yaml.safe_dump(self.to_dict(), f, default_flow_style=False)
            except ImportError:
                # Fall back to simple format
                path.write_text(self._to_simple_yaml())
            
            logger.info(f"Saved config to {path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def _to_simple_yaml(self) -> str:
        """Convert to simple YAML format."""
        lines = ["# Bantz Plugins Configuration\n"]
        
        if self.enabled:
            lines.append("enabled:")
            for name in self.enabled:
                lines.append(f"  - {name}")
            lines.append("")
        
        if self.disabled:
            lines.append("disabled:")
            for name in self.disabled:
                lines.append(f"  - {name}")
            lines.append("")
        
        if self.settings:
            lines.append("settings:")
            for plugin_name, plugin_settings in self.settings.items():
                lines.append(f"  {plugin_name}:")
                for key, value in plugin_settings.items():
                    if isinstance(value, str):
                        lines.append(f'    {key}: "{value}"')
                    else:
                        lines.append(f"    {key}: {value}")
            lines.append("")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "disabled": self.disabled,
            "settings": self.settings,
            "auto_load": self.auto_load,
            "auto_discover": self.auto_discover,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginsConfig":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", []),
            disabled=data.get("disabled", []),
            settings=data.get("settings", {}),
            auto_load=data.get("auto_load", True),
            auto_discover=data.get("auto_discover", True),
        )
    
    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        if name in self.disabled:
            return False
        if self.enabled:
            return name in self.enabled
        return True  # Default enabled if not in disabled list
    
    def enable(self, name: str) -> None:
        """Enable a plugin."""
        if name in self.disabled:
            self.disabled.remove(name)
        if self.enabled and name not in self.enabled:
            self.enabled.append(name)
    
    def disable(self, name: str) -> None:
        """Disable a plugin."""
        if name not in self.disabled:
            self.disabled.append(name)
        if name in self.enabled:
            self.enabled.remove(name)
    
    def get_plugin_settings(self, name: str) -> Dict[str, Any]:
        """Get settings for a plugin."""
        return self.settings.get(name, {})
    
    def set_plugin_settings(self, name: str, settings: Dict[str, Any]) -> None:
        """Set settings for a plugin."""
        self.settings[name] = settings
    
    def update_plugin_setting(self, name: str, key: str, value: Any) -> None:
        """Update a single setting for a plugin."""
        if name not in self.settings:
            self.settings[name] = {}
        self.settings[name][key] = value
