"""
Plugin Manager.

Central management of all plugins:
- Loading and unloading plugins
- Enabling and disabling
- Intent and tool aggregation
- Lifecycle management
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import logging
from datetime import datetime

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginState,
    PluginError,
    PluginLoadError,
    Tool,
    IntentPattern,
)
from bantz.plugins.loader import PluginLoader, PluginSpec
from bantz.plugins.config import PluginsConfig, PluginConfig

logger = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    """Container for a loaded plugin with its metadata."""
    
    plugin: BantzPlugin
    spec: PluginSpec
    loaded_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True
    
    @property
    def name(self) -> str:
        return self.plugin.metadata.name
    
    @property
    def version(self) -> str:
        return self.plugin.metadata.version


class PluginManager:
    """
    Load and manage plugins.
    
    Provides:
    - Plugin discovery and loading
    - Enable/disable management
    - Intent aggregation from all plugins
    - Tool aggregation for agent framework
    - Configuration management
    
    Example:
        manager = PluginManager([
            Path("~/.config/bantz/plugins"),
            Path("/usr/share/bantz/plugins"),
        ])
        
        # Discover and load all plugins
        manager.discover()
        manager.load_all()
        
        # Get aggregated intents and tools
        intents = manager.get_all_intents()
        tools = manager.get_all_tools()
        
        # Load specific plugin
        manager.load("spotify")
        
        # Disable plugin
        manager.disable("experimental")
    """
    
    def __init__(
        self,
        plugin_dirs: Optional[List[Path]] = None,
        config: Optional[PluginsConfig] = None,
    ):
        """
        Initialize plugin manager.
        
        Args:
            plugin_dirs: Directories to search for plugins
            config: Plugin configuration
        """
        if plugin_dirs is None:
            plugin_dirs = self._get_default_dirs()
        
        self.loader = PluginLoader(plugin_dirs)
        self.config = config or PluginsConfig()
        
        self._plugins: Dict[str, LoadedPlugin] = {}
        self._disabled: Set[str] = set(self.config.disabled)
        
        # Event callbacks
        self._on_load_callbacks: List[Callable[[BantzPlugin], None]] = []
        self._on_unload_callbacks: List[Callable[[str], None]] = []
    
    def _get_default_dirs(self) -> List[Path]:
        """Get default plugin directories."""
        import os
        
        dirs = []
        
        # User plugins
        config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        dirs.append(Path(config_home) / "bantz" / "plugins")
        
        # System plugins
        data_home = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        dirs.append(Path(data_home) / "bantz" / "plugins")
        
        # Built-in plugins
        dirs.append(Path(__file__).parent / "builtin")
        
        return dirs
    
    @property
    def plugins(self) -> Dict[str, LoadedPlugin]:
        """Get all loaded plugins."""
        return self._plugins.copy()
    
    @property
    def enabled_plugins(self) -> Dict[str, LoadedPlugin]:
        """Get only enabled plugins."""
        return {
            name: lp for name, lp in self._plugins.items()
            if lp.enabled
        }
    
    @property
    def disabled_plugins(self) -> Set[str]:
        """Get disabled plugin names."""
        return self._disabled.copy()
    
    def discover(self) -> List[PluginSpec]:
        """
        Discover available plugins.
        
        Returns:
            List of discovered plugin specifications
        """
        return self.loader.discover()
    
    def load(self, name: str) -> BantzPlugin:
        """
        Load a plugin by name.
        
        Args:
            name: Plugin name
            
        Returns:
            Loaded plugin instance
            
        Raises:
            PluginLoadError: If loading fails
        """
        if name in self._plugins:
            logger.warning(f"Plugin {name} already loaded")
            return self._plugins[name].plugin
        
        # Load via loader
        plugin = self.loader.load(name)
        spec = self.loader.get_spec(name)
        
        # Apply configuration
        if name in self.config.settings:
            plugin.config = self.config.settings[name]
        
        # Create loaded plugin container
        loaded = LoadedPlugin(
            plugin=plugin,
            spec=spec,
            enabled=name not in self._disabled,
        )
        
        self._plugins[name] = loaded
        
        # Set state
        if loaded.enabled:
            plugin.state = PluginState.ACTIVE
            plugin.on_enable()
        else:
            plugin.state = PluginState.DISABLED
        
        # Call callbacks
        for callback in self._on_load_callbacks:
            try:
                callback(plugin)
            except Exception as e:
                logger.error(f"Error in load callback: {e}")
        
        return plugin
    
    def unload(self, name: str) -> bool:
        """
        Unload a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if unloaded successfully
        """
        if name not in self._plugins:
            logger.warning(f"Plugin {name} not loaded")
            return False
        
        loaded = self._plugins[name]
        plugin = loaded.plugin
        
        try:
            # Call lifecycle hooks
            plugin.state = PluginState.UNLOADING
            if loaded.enabled:
                plugin.on_disable()
            plugin.on_unload()
            plugin.state = PluginState.UNLOADED
            
            # Unload module
            self.loader.unload(name)
            
            # Remove from loaded
            del self._plugins[name]
            
            # Call callbacks
            for callback in self._on_unload_callbacks:
                try:
                    callback(name)
                except Exception as e:
                    logger.error(f"Error in unload callback: {e}")
            
            logger.info(f"Unloaded plugin: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error unloading plugin {name}: {e}")
            plugin.state = PluginState.ERROR
            plugin._error = str(e)
            return False
    
    def reload(self, name: str) -> Optional[BantzPlugin]:
        """
        Reload a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            Reloaded plugin instance or None
        """
        was_enabled = name in self._plugins and self._plugins[name].enabled
        
        self.unload(name)
        plugin = self.load(name)
        
        if was_enabled:
            self.enable(name)
        
        return plugin
    
    def load_all(self, ignore_errors: bool = True) -> Dict[str, BantzPlugin]:
        """
        Load all discovered plugins.
        
        Args:
            ignore_errors: Continue loading on errors
            
        Returns:
            Dict of loaded plugins
        """
        loaded = {}
        specs = self.discover()
        
        for spec in specs:
            if not spec.is_valid:
                logger.warning(f"Skipping invalid plugin {spec.name}: {spec.error}")
                continue
            
            try:
                plugin = self.load(spec.name)
                loaded[spec.name] = plugin
            except Exception as e:
                logger.error(f"Failed to load plugin {spec.name}: {e}")
                if not ignore_errors:
                    raise
        
        logger.info(f"Loaded {len(loaded)} plugins")
        return loaded
    
    def unload_all(self) -> int:
        """
        Unload all plugins.
        
        Returns:
            Number of plugins unloaded
        """
        count = 0
        for name in list(self._plugins.keys()):
            if self.unload(name):
                count += 1
        return count
    
    def enable(self, name: str) -> bool:
        """
        Enable a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if enabled
        """
        self._disabled.discard(name)
        self.config.disabled = list(self._disabled)
        
        if name in self._plugins:
            loaded = self._plugins[name]
            if not loaded.enabled:
                loaded.enabled = True
                loaded.plugin.state = PluginState.ACTIVE
                loaded.plugin.on_enable()
                logger.info(f"Enabled plugin: {name}")
        
        return True
    
    def disable(self, name: str) -> bool:
        """
        Disable a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if disabled
        """
        self._disabled.add(name)
        self.config.disabled = list(self._disabled)
        
        if name in self._plugins:
            loaded = self._plugins[name]
            if loaded.enabled:
                loaded.enabled = False
                loaded.plugin.on_disable()
                loaded.plugin.state = PluginState.DISABLED
                logger.info(f"Disabled plugin: {name}")
        
        return True
    
    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        return name not in self._disabled
    
    def is_loaded(self, name: str) -> bool:
        """Check if a plugin is loaded."""
        return name in self._plugins
    
    def get_plugin(self, name: str) -> Optional[BantzPlugin]:
        """Get a loaded plugin by name."""
        loaded = self._plugins.get(name)
        return loaded.plugin if loaded else None
    
    def get_all_intents(self) -> List[IntentPattern]:
        """
        Aggregate intents from all enabled plugins.
        
        Returns:
            List of all intent patterns
        """
        intents = []
        
        for loaded in self.enabled_plugins.values():
            try:
                plugin_intents = loaded.plugin.get_intents()
                # Prefix intent names with plugin name
                for intent in plugin_intents:
                    if not intent.intent.startswith(loaded.name + "."):
                        intent.intent = f"{loaded.name}.{intent.intent}"
                intents.extend(plugin_intents)
            except Exception as e:
                logger.error(f"Error getting intents from {loaded.name}: {e}")
        
        # Sort by priority (higher first)
        intents.sort(key=lambda i: i.priority, reverse=True)
        
        return intents
    
    def get_all_tools(self) -> List[Tool]:
        """
        Aggregate tools from all enabled plugins.
        
        Returns:
            List of all tools
        """
        tools = []
        
        for loaded in self.enabled_plugins.values():
            try:
                plugin_tools = loaded.plugin.get_tools()
                # Prefix tool names with plugin name
                for tool in plugin_tools:
                    if not tool.name.startswith(loaded.name + "_"):
                        tool.name = f"{loaded.name}_{tool.name}"
                tools.extend(plugin_tools)
            except Exception as e:
                logger.error(f"Error getting tools from {loaded.name}: {e}")
        
        return tools
    
    def handle_intent(self, intent: str, slots: Dict[str, Any]) -> Any:
        """
        Route an intent to the appropriate plugin.
        
        Args:
            intent: Intent name (plugin.intent_name format)
            slots: Intent slots
            
        Returns:
            Handler result
        """
        # Extract plugin name from intent
        if "." in intent:
            plugin_name = intent.split(".")[0]
        else:
            raise ValueError(f"Invalid intent format: {intent}")
        
        if plugin_name not in self._plugins:
            raise ValueError(f"Plugin not found: {plugin_name}")
        
        loaded = self._plugins[plugin_name]
        if not loaded.enabled:
            raise ValueError(f"Plugin disabled: {plugin_name}")
        
        return loaded.plugin.handle_intent(intent, slots)
    
    def get_plugin_config(self, name: str) -> Dict[str, Any]:
        """Get plugin configuration."""
        return self.config.settings.get(name, {})
    
    def set_plugin_config(self, name: str, config: Dict[str, Any]) -> None:
        """Set plugin configuration."""
        self.config.settings[name] = config
        
        if name in self._plugins:
            plugin = self._plugins[name].plugin
            old_config = plugin.config
            plugin.config = config
            
            # Notify plugin of changes
            for key, value in config.items():
                if key not in old_config or old_config[key] != value:
                    try:
                        plugin.on_config_change(key, value)
                    except Exception as e:
                        logger.error(f"Error in config change handler: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get manager status."""
        return {
            "plugin_dirs": [str(d) for d in self.loader.plugin_dirs],
            "discovered": len(self.loader.get_all_specs()),
            "loaded": len(self._plugins),
            "enabled": len(self.enabled_plugins),
            "disabled": list(self._disabled),
            "plugins": {
                name: lp.plugin.get_status()
                for name, lp in self._plugins.items()
            },
        }
    
    def on_load(self, callback: Callable[[BantzPlugin], None]) -> None:
        """Register a callback for plugin load events."""
        self._on_load_callbacks.append(callback)
    
    def on_unload(self, callback: Callable[[str], None]) -> None:
        """Register a callback for plugin unload events."""
        self._on_unload_callbacks.append(callback)
    
    def create_plugin(
        self,
        name: str,
        target_dir: Optional[Path] = None,
    ) -> Path:
        """
        Create a new plugin from template.
        
        Args:
            name: Plugin name
            target_dir: Target directory
            
        Returns:
            Path to created plugin
        """
        return self.loader.create_plugin_template(name, target_dir)


class MockPluginManager(PluginManager):
    """Mock plugin manager for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_plugins: Dict[str, BantzPlugin] = {}
    
    def add_mock_plugin(self, plugin: BantzPlugin) -> None:
        """Add a mock plugin directly."""
        name = plugin.metadata.name
        loaded = LoadedPlugin(
            plugin=plugin,
            spec=PluginSpec(
                name=name,
                path=Path("/mock"),
                module_name=f"mock_{name}",
            ),
        )
        self._plugins[name] = loaded
        self._mock_plugins[name] = plugin
    
    def discover(self) -> List[PluginSpec]:
        """Return mock specs."""
        specs = []
        for name, plugin in self._mock_plugins.items():
            specs.append(PluginSpec(
                name=name,
                path=Path("/mock"),
                module_name=f"mock_{name}",
                metadata=plugin.metadata,
            ))
        return specs
