"""
Plugin Loader.

Dynamic plugin discovery and loading mechanism.
Handles importing plugin modules and instantiating plugin classes.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Set
import importlib.util
import importlib
import logging
import sys
import os

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginState,
    PluginError,
    PluginLoadError,
    PluginValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class PluginSpec:
    """Plugin specification from discovery."""
    
    name: str
    path: Path
    module_name: str
    metadata: Optional[PluginMetadata] = None
    plugin_class: Optional[Type[BantzPlugin]] = None
    error: Optional[str] = None
    
    @property
    def is_valid(self) -> bool:
        """Check if spec is valid for loading."""
        return self.error is None and self.path.exists()
    
    @property
    def config_path(self) -> Path:
        """Get config.yaml path."""
        return self.path.parent / "config.yaml"
    
    @property
    def has_config(self) -> bool:
        """Check if plugin has config file."""
        return self.config_path.exists()


class PluginLoader:
    """
    Plugin discovery and loading.
    
    Handles:
    - Discovering plugins in directories
    - Loading plugin modules dynamically
    - Instantiating plugin classes
    - Validation before loading
    
    Example:
        loader = PluginLoader([Path("~/.config/bantz/plugins")])
        
        # Discover all plugins
        specs = loader.discover()
        
        # Load a specific plugin
        plugin = loader.load("spotify")
    """
    
    PLUGIN_FILENAME = "plugin.py"
    METADATA_FILENAME = "metadata.yaml"
    
    def __init__(
        self,
        plugin_dirs: List[Path],
        auto_validate: bool = True,
    ):
        """
        Initialize plugin loader.
        
        Args:
            plugin_dirs: Directories to search for plugins
            auto_validate: Validate plugins on load
        """
        self.plugin_dirs = [Path(d).expanduser() for d in plugin_dirs]
        self.auto_validate = auto_validate
        
        self._specs: Dict[str, PluginSpec] = {}
        self._loaded_modules: Dict[str, Any] = {}
        self._plugin_classes: Dict[str, Type[BantzPlugin]] = {}
    
    def discover(self) -> List[PluginSpec]:
        """
        Discover all available plugins.
        
        Searches plugin directories for valid plugin packages.
        
        Returns:
            List of plugin specifications
        """
        discovered = []
        
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                logger.debug(f"Plugin directory does not exist: {plugin_dir}")
                continue
            
            for item in plugin_dir.iterdir():
                if not item.is_dir():
                    continue
                
                plugin_file = item / self.PLUGIN_FILENAME
                if not plugin_file.exists():
                    continue
                
                spec = self._create_spec(item.name, plugin_file)
                discovered.append(spec)
                self._specs[spec.name] = spec
        
        logger.info(f"Discovered {len(discovered)} plugins")
        return discovered
    
    def _create_spec(self, name: str, plugin_file: Path) -> PluginSpec:
        """Create a plugin spec from a plugin file."""
        module_name = f"bantz_plugins_{name}"
        
        spec = PluginSpec(
            name=name,
            path=plugin_file,
            module_name=module_name,
        )
        
        # Try to extract metadata without full load
        try:
            metadata = self._extract_metadata(plugin_file)
            spec.metadata = metadata
        except Exception as e:
            spec.error = f"Failed to extract metadata: {e}"
        
        return spec
    
    def _extract_metadata(self, plugin_file: Path) -> Optional[PluginMetadata]:
        """
        Extract metadata from plugin file without executing.
        
        This is a lightweight check - full metadata comes from
        the instantiated plugin.
        """
        # For now, just check if file is readable
        # Could add AST parsing for safer metadata extraction
        plugin_file.read_text()
        return None
    
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
        if name not in self._specs:
            # Try to find it
            self.discover()
        
        if name not in self._specs:
            raise PluginLoadError(f"Plugin not found: {name}")
        
        spec = self._specs[name]
        
        if not spec.is_valid:
            raise PluginLoadError(f"Invalid plugin: {spec.error}")
        
        try:
            # Load the module
            module = self._load_module(spec)
            
            # Find the plugin class
            plugin_class = self._find_plugin_class(module, name)
            spec.plugin_class = plugin_class
            
            # Instantiate
            plugin = plugin_class()
            
            # Validate if enabled
            if self.auto_validate:
                errors = plugin.validate()
                if errors:
                    raise PluginValidationError(
                        f"Plugin validation failed: {', '.join(errors)}"
                    )
            
            # Update spec with metadata from instance
            spec.metadata = plugin.metadata
            
            # Call on_load hook
            plugin.state = PluginState.LOADING
            plugin.on_load()
            plugin.state = PluginState.LOADED
            
            logger.info(f"Loaded plugin: {name} v{plugin.metadata.version}")
            return plugin
            
        except PluginError:
            raise
        except Exception as e:
            logger.error(f"Failed to load plugin {name}: {e}")
            raise PluginLoadError(f"Failed to load plugin {name}: {e}") from e
    
    def _load_module(self, spec: PluginSpec) -> Any:
        """Load a plugin module dynamically."""
        if spec.module_name in self._loaded_modules:
            return self._loaded_modules[spec.module_name]
        
        # Add parent directory to path temporarily
        parent_dir = str(spec.path.parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        
        try:
            # Create module spec
            module_spec = importlib.util.spec_from_file_location(
                spec.module_name,
                spec.path,
            )
            
            if module_spec is None or module_spec.loader is None:
                raise PluginLoadError(f"Cannot create module spec for {spec.name}")
            
            # Create and load module
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[spec.module_name] = module
            module_spec.loader.exec_module(module)
            
            self._loaded_modules[spec.module_name] = module
            return module
            
        except Exception as e:
            raise PluginLoadError(f"Failed to load module: {e}") from e
    
    def _find_plugin_class(
        self,
        module: Any,
        name: str,
    ) -> Type[BantzPlugin]:
        """Find the plugin class in a module."""
        plugin_classes = []
        
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            
            # Check if it's a class that inherits from BantzPlugin
            if (
                isinstance(attr, type) and
                issubclass(attr, BantzPlugin) and
                attr is not BantzPlugin and
                not attr_name.startswith("_")
            ):
                plugin_classes.append(attr)
        
        if not plugin_classes:
            raise PluginLoadError(
                f"No BantzPlugin subclass found in {name}"
            )
        
        if len(plugin_classes) > 1:
            # Prefer class with matching name
            for cls in plugin_classes:
                if name.lower().replace("-", "") in cls.__name__.lower():
                    return cls
            
            logger.warning(
                f"Multiple plugin classes found in {name}, using first"
            )
        
        return plugin_classes[0]
    
    def unload(self, name: str) -> bool:
        """
        Unload a plugin module.
        
        Args:
            name: Plugin name
            
        Returns:
            True if successfully unloaded
        """
        if name not in self._specs:
            return False
        
        spec = self._specs[name]
        
        # Remove from sys.modules
        if spec.module_name in sys.modules:
            del sys.modules[spec.module_name]
        
        if spec.module_name in self._loaded_modules:
            del self._loaded_modules[spec.module_name]
        
        logger.info(f"Unloaded plugin module: {name}")
        return True
    
    def reload(self, name: str) -> BantzPlugin:
        """
        Reload a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            Reloaded plugin instance
        """
        self.unload(name)
        return self.load(name)
    
    def get_spec(self, name: str) -> Optional[PluginSpec]:
        """Get plugin specification by name."""
        return self._specs.get(name)
    
    def get_all_specs(self) -> List[PluginSpec]:
        """Get all discovered plugin specifications."""
        return list(self._specs.values())
    
    def is_discovered(self, name: str) -> bool:
        """Check if a plugin has been discovered."""
        return name in self._specs
    
    def is_loaded(self, name: str) -> bool:
        """Check if a plugin module is loaded."""
        return name in self._loaded_modules
    
    def add_plugin_dir(self, path: Path) -> None:
        """Add a plugin directory."""
        path = Path(path).expanduser()
        if path not in self.plugin_dirs:
            self.plugin_dirs.append(path)
    
    def remove_plugin_dir(self, path: Path) -> bool:
        """Remove a plugin directory."""
        path = Path(path).expanduser()
        if path in self.plugin_dirs:
            self.plugin_dirs.remove(path)
            return True
        return False
    
    def create_plugin_template(
        self,
        name: str,
        target_dir: Optional[Path] = None,
    ) -> Path:
        """
        Create a plugin template.
        
        Args:
            name: Plugin name
            target_dir: Directory to create plugin in
            
        Returns:
            Path to created plugin directory
        """
        if target_dir is None:
            target_dir = self.plugin_dirs[0] if self.plugin_dirs else Path.cwd()
        
        target_dir = Path(target_dir).expanduser()
        plugin_dir = target_dir / name
        plugin_dir.mkdir(parents=True, exist_ok=True)
        
        # Create plugin.py
        plugin_file = plugin_dir / self.PLUGIN_FILENAME
        plugin_file.write_text(self._get_plugin_template(name))
        
        # Create config.yaml
        config_file = plugin_dir / "config.yaml"
        config_file.write_text(self._get_config_template(name))
        
        logger.info(f"Created plugin template: {plugin_dir}")
        return plugin_dir
    
    def _get_plugin_template(self, name: str) -> str:
        """Get plugin.py template content."""
        class_name = "".join(word.capitalize() for word in name.split("-")) + "Plugin"
        
        return f'''"""
{name} - A Bantz Plugin

Description of what this plugin does.
"""

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginPermission,
    Tool,
    ToolParameter,
    IntentPattern,
)
from typing import List


class {class_name}(BantzPlugin):
    """Plugin implementation."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="{name}",
            version="1.0.0",
            author="Your Name",
            description="Description of the plugin",
            permissions=[],
            tags=["example"],
        )
    
    def get_intents(self) -> List[IntentPattern]:
        return [
            IntentPattern(
                pattern=r"example (.+)",
                intent="{name.replace("-", "_")}.example",
                examples=["example hello"],
            ),
        ]
    
    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="example_tool",
                description="An example tool",
                function=self.example_tool,
                parameters=[
                    ToolParameter(
                        name="input",
                        description="Input text",
                        required=True,
                    ),
                ],
            ),
        ]
    
    def on_load(self) -> None:
        """Initialize plugin."""
        self._logger.info(f"{{self.metadata.name}} loaded!")
    
    def on_unload(self) -> None:
        """Cleanup plugin."""
        self._logger.info(f"{{self.metadata.name}} unloaded!")
    
    def example_tool(self, input: str) -> str:
        """Example tool implementation."""
        return f"Processed: {{input}}"
    
    def handle_example(self, **slots) -> str:
        """Handle example intent."""
        return "Example intent handled!"
'''
    
    def _get_config_template(self, name: str) -> str:
        """Get config.yaml template content."""
        return f'''# {name} Plugin Configuration

# Add your plugin settings here
# These will be available via self.config in your plugin

# Example:
# api_key: "your-api-key"
# timeout: 30
# enabled_features:
#   - feature1
#   - feature2
'''
