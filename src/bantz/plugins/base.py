"""
Plugin Base Classes and Interfaces.

Provides the foundation for all Bantz plugins:
- BantzPlugin: Abstract base class for plugins
- PluginMetadata: Plugin information
- Tool: Agent tool definition
- PluginPermission: Permission system
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any, Callable, Dict, List, Optional, Set, Union, TypeVar, Generic
)
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PluginPermission(Enum):
    """Permissions that a plugin may require."""
    
    NETWORK = auto()         # Access to network/internet
    FILESYSTEM = auto()      # Read/write files
    SYSTEM = auto()          # System commands, processes
    BROWSER = auto()         # Browser automation
    NOTIFICATIONS = auto()   # Send notifications
    AUDIO = auto()           # Audio input/output
    CLIPBOARD = auto()       # Clipboard access
    KEYBOARD = auto()        # Keyboard control
    MOUSE = auto()           # Mouse control
    SCREEN = auto()          # Screen capture
    CAMERA = auto()          # Camera access
    LOCATION = auto()        # Location data
    CONTACTS = auto()        # Contact data
    CALENDAR = auto()        # Calendar access
    EMAIL = auto()           # Email access
    SECRETS = auto()         # Access to credentials/secrets


class PluginState(Enum):
    """Plugin lifecycle states."""
    
    DISCOVERED = auto()      # Found but not loaded
    LOADING = auto()         # Currently loading
    LOADED = auto()          # Loaded and ready
    ACTIVE = auto()          # Active and processing
    DISABLED = auto()        # Loaded but disabled
    ERROR = auto()           # Error state
    UNLOADING = auto()       # Currently unloading
    UNLOADED = auto()        # Fully unloaded


class PluginError(Exception):
    """Base exception for plugin errors."""
    pass


class PluginLoadError(PluginError):
    """Error loading a plugin."""
    pass


class PluginValidationError(PluginError):
    """Error validating a plugin."""
    pass


@dataclass
class ToolParameter:
    """Parameter definition for a tool."""
    
    name: str
    description: str
    type: str = "string"  # string, number, boolean, array, object
    required: bool = False
    default: Any = None
    enum: Optional[List[Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON Schema-like dict."""
        result = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            result["enum"] = self.enum
        if self.default is not None:
            result["default"] = self.default
        return result


@dataclass
class Tool:
    """
    Agent tool definition.
    
    Tools are functions that the agent can call to perform actions.
    """
    
    name: str
    description: str
    function: Callable[..., Any]
    parameters: List[ToolParameter] = field(default_factory=list)
    returns: str = "string"
    examples: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    timeout: float = 30.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to tool definition dict for agent."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_dict()
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
    
    def execute(self, **kwargs) -> Any:
        """Execute the tool function."""
        return self.function(**kwargs)


@dataclass
class PluginMetadata:
    """
    Plugin metadata and information.
    
    Contains all information about a plugin needed for
    discovery, loading, and display.
    """
    
    name: str
    version: str
    author: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    permissions: List[PluginPermission] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    license: str = "MIT"
    min_bantz_version: str = "0.1.0"
    icon: str = "🔌"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "dependencies": self.dependencies,
            "permissions": [p.name for p in self.permissions],
            "tags": self.tags,
            "homepage": self.homepage,
            "repository": self.repository,
            "license": self.license,
            "min_bantz_version": self.min_bantz_version,
            "icon": self.icon,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginMetadata":
        """Create from dictionary."""
        permissions = []
        for p in data.get("permissions", []):
            if isinstance(p, str):
                try:
                    permissions.append(PluginPermission[p.upper()])
                except KeyError:
                    pass
            elif isinstance(p, PluginPermission):
                permissions.append(p)
        
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
            author=data.get("author", "unknown"),
            description=data.get("description", ""),
            dependencies=data.get("dependencies", []),
            permissions=permissions,
            tags=data.get("tags", []),
            homepage=data.get("homepage", ""),
            repository=data.get("repository", ""),
            license=data.get("license", "MIT"),
            min_bantz_version=data.get("min_bantz_version", "0.1.0"),
            icon=data.get("icon", "🔌"),
        )


@dataclass
class IntentPattern:
    """Intent pattern for NLU matching."""
    
    pattern: str           # Regex pattern
    intent: str            # Intent name
    priority: int = 50     # Higher = checked first
    examples: List[str] = field(default_factory=list)
    slots: Dict[str, str] = field(default_factory=dict)  # slot_name -> type


class BantzPlugin(ABC):
    """
    Abstract base class for all Bantz plugins.
    
    A plugin extends Bantz functionality by providing:
    - Intents: What commands the plugin can handle
    - Tools: Functions the agent can call
    - Event handlers: Respond to system events
    
    Example:
        class MyPlugin(BantzPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="my-plugin",
                    version="1.0.0",
                    author="Me",
                    description="My awesome plugin",
                )
            
            def get_intents(self) -> List[IntentPattern]:
                return [
                    IntentPattern(
                        pattern=r"hello (.+)",
                        intent="my_plugin.greet",
                    ),
                ]
            
            def get_tools(self) -> List[Tool]:
                return [
                    Tool(
                        name="greet",
                        description="Say hello",
                        function=self.greet,
                    ),
                ]
            
            def greet(self, name: str) -> str:
                return f"Hello, {name}!"
    """
    
    def __init__(self):
        """Initialize plugin."""
        self._state = PluginState.DISCOVERED
        self._config: Dict[str, Any] = {}
        self._logger = logging.getLogger(f"bantz.plugins.{self.metadata.name}")
        self._loaded_at: Optional[datetime] = None
        self._error: Optional[str] = None
    
    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """
        Return plugin metadata.
        
        Must be implemented by all plugins.
        """
        pass
    
    @abstractmethod
    def get_intents(self) -> List[IntentPattern]:
        """
        Return list of intent patterns this plugin handles.
        
        Must be implemented by all plugins.
        """
        pass
    
    @abstractmethod
    def get_tools(self) -> List[Tool]:
        """
        Return list of tools for agent framework.
        
        Must be implemented by all plugins.
        """
        pass
    
    @property
    def state(self) -> PluginState:
        """Get current plugin state."""
        return self._state
    
    @state.setter
    def state(self, value: PluginState) -> None:
        """Set plugin state."""
        self._state = value
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get plugin configuration."""
        return self._config
    
    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        """Set plugin configuration."""
        self._config = value
    
    @property
    def is_loaded(self) -> bool:
        """Check if plugin is loaded."""
        return self._state in (PluginState.LOADED, PluginState.ACTIVE)
    
    @property
    def is_active(self) -> bool:
        """Check if plugin is active."""
        return self._state == PluginState.ACTIVE
    
    @property
    def error(self) -> Optional[str]:
        """Get error message if in error state."""
        return self._error
    
    def on_load(self) -> None:
        """
        Called when plugin is loaded.
        
        Override to perform initialization:
        - Connect to external services
        - Load resources
        - Set up state
        """
        pass
    
    def on_unload(self) -> None:
        """
        Called when plugin is unloaded.
        
        Override to perform cleanup:
        - Disconnect from services
        - Save state
        - Release resources
        """
        pass
    
    def on_enable(self) -> None:
        """Called when plugin is enabled."""
        pass
    
    def on_disable(self) -> None:
        """Called when plugin is disabled."""
        pass
    
    def on_config_change(self, key: str, value: Any) -> None:
        """Called when configuration changes."""
        pass
    
    def handle_intent(self, intent: str, slots: Dict[str, Any]) -> Any:
        """
        Handle an intent.
        
        Default implementation looks for a method named after the intent.
        Override for custom routing.
        """
        # Convert intent name to method name: "my_plugin.greet" -> "handle_greet"
        method_name = f"handle_{intent.split('.')[-1]}"
        
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            return method(**slots)
        
        raise NotImplementedError(f"No handler for intent: {intent}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get plugin status information."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "state": self._state.name,
            "loaded_at": self._loaded_at.isoformat() if self._loaded_at else None,
            "error": self._error,
            "config_keys": list(self._config.keys()),
        }
    
    def validate(self) -> List[str]:
        """
        Validate plugin configuration and state.
        
        Returns list of validation errors (empty if valid).
        """
        errors = []
        
        # Check metadata
        if not self.metadata.name:
            errors.append("Plugin name is required")
        if not self.metadata.version:
            errors.append("Plugin version is required")
        
        # Check for duplicate intent names
        intents = self.get_intents()
        intent_names = [i.intent for i in intents]
        if len(intent_names) != len(set(intent_names)):
            errors.append("Duplicate intent names found")
        
        # Check for duplicate tool names
        tools = self.get_tools()
        tool_names = [t.name for t in tools]
        if len(tool_names) != len(set(tool_names)):
            errors.append("Duplicate tool names found")
        
        return errors
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.metadata.name}@{self.metadata.version})>"


class SimplePlugin(BantzPlugin):
    """
    Simple plugin implementation for quick plugin creation.
    
    Example:
        plugin = SimplePlugin(
            metadata=PluginMetadata(
                name="quick-plugin",
                version="1.0.0",
                author="Me",
                description="A quick plugin",
            ),
            intents=[...],
            tools=[...],
        )
    """
    
    def __init__(
        self,
        metadata: PluginMetadata,
        intents: Optional[List[IntentPattern]] = None,
        tools: Optional[List[Tool]] = None,
    ):
        self._metadata = metadata
        self._intents = intents or []
        self._tools = tools or []
        super().__init__()
    
    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata
    
    def get_intents(self) -> List[IntentPattern]:
        return self._intents
    
    def get_tools(self) -> List[Tool]:
        return self._tools
    
    def add_intent(self, pattern: str, intent: str, **kwargs) -> None:
        """Add an intent pattern."""
        self._intents.append(IntentPattern(pattern=pattern, intent=intent, **kwargs))
    
    def add_tool(
        self,
        name: str,
        description: str,
        function: Callable,
        **kwargs,
    ) -> None:
        """Add a tool."""
        self._tools.append(Tool(
            name=name,
            description=description,
            function=function,
            **kwargs,
        ))
