"""
Bantz Plugin System.

Modular plugin architecture for extending Bantz functionality:
- Plugin base class and interfaces
- Plugin discovery and loading
- Plugin lifecycle management
- Configuration per plugin
- Intent and tool aggregation
"""

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginPermission,
    Tool,
    ToolParameter,
    PluginState,
    PluginError,
    PluginLoadError,
    PluginValidationError,
)
from bantz.plugins.loader import (
    PluginLoader,
    PluginSpec,
)
from bantz.plugins.manager import (
    PluginManager,
)
from bantz.plugins.config import (
    PluginConfig,
    PluginsConfig,
)
from bantz.plugins.registry import (
    SkillRegistry,
    RegistryEntry,
    RegistrySearchResult,
)

__all__ = [
    # Base
    "BantzPlugin",
    "PluginMetadata",
    "PluginPermission",
    "Tool",
    "ToolParameter",
    "PluginState",
    "PluginError",
    "PluginLoadError",
    "PluginValidationError",
    # Loader
    "PluginLoader",
    "PluginSpec",
    # Manager
    "PluginManager",
    # Config
    "PluginConfig",
    "PluginsConfig",
    # Registry
    "SkillRegistry",
    "RegistryEntry",
    "RegistrySearchResult",
]
