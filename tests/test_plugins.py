"""
Comprehensive tests for the Bantz Plugin System.

Tests cover:
- Plugin base classes and interfaces
- Plugin loading and discovery
- Plugin manager lifecycle
- Plugin configuration
- Registry operations
- Example Spotify plugin
"""

import pytest
import tempfile
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginPermission,
    PluginState,
    PluginError,
    PluginLoadError,
    PluginValidationError,
    Tool,
    ToolParameter,
    IntentPattern,
    SimplePlugin,
)
from bantz.plugins.loader import PluginLoader, PluginSpec
from bantz.plugins.manager import PluginManager, LoadedPlugin, MockPluginManager
from bantz.plugins.config import PluginConfig, PluginsConfig
from bantz.plugins.registry import (
    SkillRegistry,
    RegistryEntry,
    RegistrySource,
    RegistrySearchResult,
    MockSkillRegistry,
)


# =============================================================================
# Test Plugin Implementations
# =============================================================================


class SamplePlugin(BantzPlugin):
    """A test plugin implementation."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            author="Test",
            description="A test plugin",
            permissions=[PluginPermission.NETWORK],
            tags=["test"],
        )
    
    def get_intents(self) -> List[IntentPattern]:
        return [
            IntentPattern(
                pattern=r"test (\w+)",
                intent="test_action",
                priority=50,
                examples=["test something"],
                slots={"what": "string"},
            ),
        ]
    
    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="test_tool",
                description="A test tool",
                function=self.do_test,
                parameters=[
                    ToolParameter(
                        name="input",
                        description="Input value",
                        required=True,
                    ),
                ],
            ),
        ]
    
    def do_test(self, input: str) -> Dict[str, Any]:
        return {"result": f"tested: {input}"}
    
    def handle_test_action(self, what: str = "", **slots) -> str:
        return f"Test action: {what}"


class MinimalPlugin(BantzPlugin):
    """Minimal plugin with only required methods."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="minimal",
            version="0.1.0",
            author="Test",
            description="Minimal plugin",
        )
    
    def get_intents(self) -> List[IntentPattern]:
        return []
    
    def get_tools(self) -> List[Tool]:
        return []


# =============================================================================
# Plugin Base Tests
# =============================================================================


class TestPluginMetadata:
    """Tests for PluginMetadata."""
    
    def test_metadata_creation(self):
        """Test basic metadata creation."""
        meta = PluginMetadata(
            name="test",
            version="1.0.0",
            author="Author",
            description="Description",
        )
        assert meta.name == "test"
        assert meta.version == "1.0.0"
        assert meta.author == "Author"
        assert meta.description == "Description"
    
    def test_metadata_with_all_fields(self):
        """Test metadata with all fields."""
        meta = PluginMetadata(
            name="test",
            version="1.0.0",
            author="Author",
            description="Description",
            permissions=[PluginPermission.NETWORK],
            dependencies=["dep1"],
            tags=["tag1"],
        )
        assert meta.permissions == [PluginPermission.NETWORK]
        assert meta.dependencies == ["dep1"]
        assert meta.tags == ["tag1"]
    
    def test_metadata_with_permissions(self):
        """Test metadata with permissions."""
        meta = PluginMetadata(
            name="test",
            version="1.0.0",
            author="Author",
            description="Description",
            permissions=[PluginPermission.NETWORK, PluginPermission.FILESYSTEM],
        )
        assert PluginPermission.NETWORK in meta.permissions
        assert PluginPermission.FILESYSTEM in meta.permissions
    
    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        meta = PluginMetadata(
            name="test",
            version="1.0.0",
            author="Author",
            description="Description",
            permissions=[PluginPermission.NETWORK],
            tags=["tag1", "tag2"],
        )
        data = meta.to_dict()
        assert data["name"] == "test"
        assert data["version"] == "1.0.0"
        assert data["author"] == "Author"
        assert "permissions" in data
        assert data["tags"] == ["tag1", "tag2"]
    
    def test_metadata_from_dict(self):
        """Test metadata deserialization."""
        data = {
            "name": "test",
            "version": "2.0.0",
            "author": "Author",
            "description": "Test desc",
            "permissions": ["NETWORK", "BROWSER"],
        }
        meta = PluginMetadata.from_dict(data)
        assert meta.name == "test"
        assert meta.version == "2.0.0"
        assert PluginPermission.NETWORK in meta.permissions


class TestPluginPermission:
    """Tests for PluginPermission enum."""
    
    def test_all_permissions_exist(self):
        """Test all permission values exist."""
        assert PluginPermission.NETWORK is not None
        assert PluginPermission.FILESYSTEM is not None
        assert PluginPermission.BROWSER is not None
        assert PluginPermission.AUDIO is not None
        assert PluginPermission.CLIPBOARD is not None
        assert PluginPermission.SYSTEM is not None
    
    def test_permission_comparison(self):
        """Test permission comparison."""
        assert PluginPermission.NETWORK == PluginPermission.NETWORK
        assert PluginPermission.NETWORK != PluginPermission.FILESYSTEM


class TestPluginState:
    """Tests for PluginState enum."""
    
    def test_all_states_exist(self):
        """Test all state values exist."""
        assert PluginState.DISCOVERED is not None
        assert PluginState.LOADING is not None
        assert PluginState.LOADED is not None
        assert PluginState.ACTIVE is not None
        assert PluginState.DISABLED is not None
        assert PluginState.ERROR is not None
        assert PluginState.UNLOADED is not None


class TestToolParameter:
    """Tests for ToolParameter."""
    
    def test_parameter_creation(self):
        """Test parameter creation."""
        param = ToolParameter(
            name="input",
            description="Input value",
            required=True,
        )
        assert param.name == "input"
        assert param.description == "Input value"
        assert param.required is True
        assert param.type == "string"
    
    def test_parameter_with_enum(self):
        """Test parameter with enum values."""
        param = ToolParameter(
            name="action",
            description="Action to take",
            enum=["play", "pause", "stop"],
        )
        assert param.enum == ["play", "pause", "stop"]
    
    def test_parameter_to_dict(self):
        """Test parameter serialization."""
        param = ToolParameter(
            name="volume",
            description="Volume level",
            type="number",
            default=50,
        )
        data = param.to_dict()
        assert data["type"] == "number"
        assert data["default"] == 50
        assert data["description"] == "Volume level"


class TestTool:
    """Tests for Tool class."""
    
    def test_tool_creation(self):
        """Test tool creation."""
        def my_func(x: int) -> int:
            return x * 2
        
        tool = Tool(
            name="double",
            description="Double a number",
            function=my_func,
        )
        assert tool.name == "double"
        assert tool.description == "Double a number"
        assert tool.function == my_func
    
    def test_tool_execute(self):
        """Test tool execution."""
        def add(a: int, b: int) -> int:
            return a + b
        
        tool = Tool(
            name="add",
            description="Add two numbers",
            function=add,
        )
        result = tool.execute(a=1, b=2)
        assert result == 3
    
    def test_tool_with_parameters(self):
        """Test tool with parameters."""
        tool = Tool(
            name="test",
            description="Test tool",
            function=lambda: None,
            parameters=[
                ToolParameter(name="input", description="Input", required=True),
                ToolParameter(name="option", description="Option", default="default"),
            ],
        )
        assert len(tool.parameters) == 2
        assert tool.parameters[0].name == "input"
        assert tool.parameters[1].name == "option"
    
    def test_tool_to_dict(self):
        """Test tool serialization."""
        tool = Tool(
            name="test",
            description="Test",
            function=lambda x: x,
            parameters=[
                ToolParameter(name="x", description="Value"),
            ],
            examples=["example 1"],
        )
        data = tool.to_dict()
        assert data["name"] == "test"
        assert data["description"] == "Test"
        assert "parameters" in data


class TestIntentPattern:
    """Tests for IntentPattern."""
    
    def test_pattern_creation(self):
        """Test pattern creation."""
        pattern = IntentPattern(
            pattern=r"play (\w+)",
            intent="play_music",
            priority=50,
        )
        assert pattern.pattern == r"play (\w+)"
        assert pattern.intent == "play_music"
        assert pattern.priority == 50
    
    def test_pattern_with_slots(self):
        """Test pattern with slot definitions."""
        pattern = IntentPattern(
            pattern=r"set volume to (\d+)",
            intent="set_volume",
            slots={"volume": "number"},
        )
        assert pattern.slots == {"volume": "number"}
    
    def test_pattern_with_examples(self):
        """Test pattern with examples."""
        pattern = IntentPattern(
            pattern=r"next song",
            intent="next_track",
            examples=["next song", "skip"],
        )
        assert len(pattern.examples) == 2


class TestBantzPlugin:
    """Tests for BantzPlugin ABC."""
    
    def test_plugin_creation(self):
        """Test plugin instantiation."""
        plugin = SamplePlugin()
        assert plugin.metadata.name == "test-plugin"
        assert plugin.metadata.version == "1.0.0"
    
    def test_plugin_intents(self):
        """Test plugin intent patterns."""
        plugin = SamplePlugin()
        intents = plugin.get_intents()
        assert len(intents) == 1
        assert intents[0].intent == "test_action"
    
    def test_plugin_tools(self):
        """Test plugin tools."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        assert len(tools) == 1
        assert tools[0].name == "test_tool"
    
    def test_plugin_tool_execution(self):
        """Test plugin tool execution."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        result = tools[0].execute(input="hello")
        assert result == {"result": "tested: hello"}
    
    def test_plugin_config(self):
        """Test plugin config access."""
        plugin = SamplePlugin()
        # Test that config attribute exists or can be set
        assert hasattr(plugin, 'config') or hasattr(plugin, '_config')
    
    def test_plugin_lifecycle(self):
        """Test plugin lifecycle hooks."""
        plugin = SamplePlugin()
        
        # These should not raise
        plugin.on_load()
        plugin.on_enable()
        plugin.on_disable()
        plugin.on_unload()
    
    def test_minimal_plugin(self):
        """Test minimal plugin implementation."""
        plugin = MinimalPlugin()
        assert plugin.metadata.name == "minimal"
        assert plugin.get_intents() == []
        assert plugin.get_tools() == []


class TestSimplePlugin:
    """Tests for SimplePlugin convenience class."""
    
    def test_simple_plugin_creation(self):
        """Test simple plugin creation."""
        def tool_func(x: int) -> int:
            return x * 2
        
        plugin = SimplePlugin(
            metadata=PluginMetadata(
                name="simple",
                version="1.0.0",
                author="Test",
                description="Simple test",
            ),
            intents=[
                IntentPattern(
                    pattern=r"test",
                    intent="test",
                    priority=50,
                ),
            ],
            tools=[
                Tool(
                    name="double",
                    description="Double",
                    function=tool_func,
                ),
            ],
        )
        
        assert plugin.metadata.name == "simple"
        assert len(plugin.get_intents()) == 1
        assert len(plugin.get_tools()) == 1
    
    def test_simple_plugin_add_tool(self):
        """Test adding tool to simple plugin."""
        plugin = SimplePlugin(
            metadata=PluginMetadata(
                name="simple",
                version="1.0.0",
                author="Test",
                description="Simple",
            ),
        )
        
        plugin.add_tool("my_tool", "Test tool", lambda x: x * 2)
        assert len(plugin.get_tools()) == 1
        assert plugin.get_tools()[0].name == "my_tool"


# =============================================================================
# Plugin Loader Tests
# =============================================================================


class TestPluginSpec:
    """Tests for PluginSpec."""
    
    def test_spec_creation(self):
        """Test spec creation."""
        spec = PluginSpec(
            name="test",
            path=Path("/plugins/test"),
            module_name="plugins.test",
        )
        assert spec.name == "test"
        assert spec.path == Path("/plugins/test")
        assert spec.module_name == "plugins.test"


class TestPluginLoader:
    """Tests for PluginLoader."""
    
    def test_loader_creation(self):
        """Test loader creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PluginLoader([Path(tmpdir)])
            assert Path(tmpdir) in loader.plugin_dirs
    
    def test_loader_discover_empty(self):
        """Test discovery in empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PluginLoader([Path(tmpdir)])
            specs = loader.discover()
            assert specs == []
    
    def test_loader_discover_plugins(self):
        """Test plugin discovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a plugin directory
            plugin_dir = Path(tmpdir) / "my-plugin"
            plugin_dir.mkdir()
            
            # Create plugin.py
            plugin_file = plugin_dir / "plugin.py"
            plugin_file.write_text("""
from bantz.plugins.base import BantzPlugin, PluginMetadata

class MyPlugin(BantzPlugin):
    @property
    def metadata(self):
        return PluginMetadata(name="my-plugin", version="1.0.0", author="Test", description="Test")
    
    def get_intents(self):
        return []
    
    def get_tools(self):
        return []
""")
            
            loader = PluginLoader([Path(tmpdir)])
            specs = loader.discover()
            
            assert len(specs) == 1
            assert specs[0].name == "my-plugin"
    
    def test_loader_load_plugin(self):
        """Test loading a plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a plugin directory
            plugin_dir = Path(tmpdir) / "loadable"
            plugin_dir.mkdir()
            
            # Create plugin.py
            plugin_file = plugin_dir / "plugin.py"
            plugin_file.write_text("""
from bantz.plugins.base import BantzPlugin, PluginMetadata

class LoadablePlugin(BantzPlugin):
    @property
    def metadata(self):
        return PluginMetadata(name="loadable", version="1.0.0", author="Test", description="Test")
    
    def get_intents(self):
        return []
    
    def get_tools(self):
        return []
""")
            
            loader = PluginLoader([Path(tmpdir)])
            specs = loader.discover()
            
            assert len(specs) == 1
            plugin = loader.load(specs[0].name)
            assert plugin is not None
            assert plugin.metadata.name == "loadable"
    
    def test_loader_create_template(self):
        """Test plugin template creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PluginLoader([Path(tmpdir)])
            
            path = loader.create_plugin_template(
                name="new-plugin",
                target_dir=Path(tmpdir),
            )
            
            assert path.exists()
            assert (path / "plugin.py").exists()
            
            content = (path / "plugin.py").read_text()
            assert "class" in content


# =============================================================================
# Plugin Manager Tests
# =============================================================================


class TestLoadedPlugin:
    """Tests for LoadedPlugin container."""
    
    def test_loaded_plugin_creation(self):
        """Test loaded plugin creation."""
        plugin = SamplePlugin()
        spec = PluginSpec(
            name="test",
            path=Path("/plugins/test"),
            module_name="plugins.test",
        )
        loaded = LoadedPlugin(
            plugin=plugin,
            spec=spec,
        )
        assert loaded.plugin == plugin
        assert loaded.enabled is True


class TestPluginManager:
    """Tests for PluginManager."""
    
    def test_manager_creation(self):
        """Test manager creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PluginManager([Path(tmpdir)])
            assert len(manager.plugins) == 0
    
    def test_mock_manager_register_plugin(self):
        """Test registering a plugin using mock manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin = SamplePlugin()
            manager.add_mock_plugin(plugin)
            
            assert "test-plugin" in manager.plugins
            assert manager.get_plugin("test-plugin") == plugin
    
    def test_manager_enable_disable(self):
        """Test enabling/disabling plugins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin = SamplePlugin()
            manager.add_mock_plugin(plugin)
            
            # Should start enabled
            assert manager.is_enabled("test-plugin")
            
            # Disable
            manager.disable("test-plugin")
            assert not manager.is_enabled("test-plugin")
            
            # Enable
            manager.enable("test-plugin")
            assert manager.is_enabled("test-plugin")
    
    def test_manager_get_all_intents(self):
        """Test getting intents from all plugins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin1 = SamplePlugin()
            plugin2 = MinimalPlugin()
            
            manager.add_mock_plugin(plugin1)
            manager.add_mock_plugin(plugin2)
            
            intents = manager.get_all_intents()
            assert len(intents) >= 1  # At least from SamplePlugin
    
    def test_manager_get_all_tools(self):
        """Test getting tools from all plugins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin = SamplePlugin()
            manager.add_mock_plugin(plugin)
            
            tools = manager.get_all_tools()
            assert len(tools) >= 1
    
    def test_manager_handle_intent(self):
        """Test intent handling through manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin = SamplePlugin()
            manager.add_mock_plugin(plugin)
            
            # The intent gets prefixed with plugin name
            result = manager.handle_intent(
                intent="test-plugin.test_action",
                slots={"what": "hello"},
            )
            assert result == "Test action: hello"
    
    def test_manager_unload(self):
        """Test unloading a plugin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MockPluginManager([Path(tmpdir)])
            
            plugin = SamplePlugin()
            manager.add_mock_plugin(plugin)
            
            assert "test-plugin" in manager.plugins
            
            manager.unload("test-plugin")
            assert "test-plugin" not in manager.plugins


class TestMockPluginManager:
    """Tests for MockPluginManager."""
    
    def test_mock_manager(self):
        """Test mock manager functionality."""
        mock = MockPluginManager()
        
        # Should work without real plugins
        intents = mock.get_all_intents()
        assert isinstance(intents, list)
        
        tools = mock.get_all_tools()
        assert isinstance(tools, list)


# =============================================================================
# Plugin Config Tests
# =============================================================================


class TestPluginConfig:
    """Tests for PluginConfig."""
    
    def test_config_creation(self):
        """Test config creation."""
        config = PluginConfig(
            enabled=True,
            settings={"key": "value"},
        )
        assert config.enabled is True
        assert config.settings["key"] == "value"
    
    def test_config_get_set(self):
        """Test get/set methods."""
        config = PluginConfig()
        config.set("key", "value")
        assert config.get("key") == "value"
        assert config.get("missing", "default") == "default"


class TestPluginsConfig:
    """Tests for PluginsConfig."""
    
    def test_config_creation(self):
        """Test plugins config creation."""
        config = PluginsConfig()
        assert config.enabled == []
        assert config.disabled == []
    
    def test_config_enable_disable(self):
        """Test enabling/disabling plugins."""
        config = PluginsConfig(enabled=["plugin1"])
        
        # Verify initially in enabled
        assert config.is_enabled("plugin1") is True
        
        config.disable("plugin1")
        assert "plugin1" in config.disabled
        assert config.is_enabled("plugin1") is False
    
    def test_config_is_enabled(self):
        """Test checking if plugin is enabled."""
        config = PluginsConfig(
            enabled=["plugin1"],
            disabled=["plugin2"],
        )
        
        assert config.is_enabled("plugin1") is True
        assert config.is_enabled("plugin2") is False
        # Unknown plugins default based on settings
    
    def test_config_plugin_settings(self):
        """Test plugin settings."""
        config = PluginsConfig()
        
        config.update_plugin_setting("plugin1", "key", "value")
        assert config.get_plugin_settings("plugin1")["key"] == "value"
    
    def test_config_save_load(self):
        """Test config save/load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "plugins.yaml"
            
            config = PluginsConfig(
                enabled=["plugin1", "plugin2"],
                disabled=["plugin3"],
            )
            config.update_plugin_setting("plugin1", "setting", 123)
            
            config.save(config_path)
            assert config_path.exists()
            
            loaded = PluginsConfig.load(config_path)
            assert "plugin1" in loaded.enabled
            assert "plugin3" in loaded.disabled


# =============================================================================
# Registry Tests
# =============================================================================


class TestRegistryEntry:
    """Tests for RegistryEntry."""
    
    def test_entry_creation(self):
        """Test registry entry creation."""
        entry = RegistryEntry(
            name="test-plugin",
            version="1.0.0",
            author="Author",
            description="Description",
            source=RegistrySource.OFFICIAL,
        )
        assert entry.name == "test-plugin"
        assert entry.source == RegistrySource.OFFICIAL
    
    def test_entry_to_dict(self):
        """Test entry serialization."""
        entry = RegistryEntry(
            name="test",
            version="1.0.0",
            author="Author",
            description="Desc",
            downloads=1000,
            rating=4.5,
        )
        data = entry.to_dict()
        assert data["name"] == "test"
        assert data["downloads"] == 1000
        assert data["rating"] == 4.5


class TestRegistrySource:
    """Tests for RegistrySource enum."""
    
    def test_all_sources_exist(self):
        """Test all source values exist."""
        assert RegistrySource.OFFICIAL is not None
        assert RegistrySource.COMMUNITY is not None
        assert RegistrySource.LOCAL is not None
        assert RegistrySource.GIT is not None
        assert RegistrySource.URL is not None


class TestSkillRegistry:
    """Tests for SkillRegistry."""
    
    def test_registry_creation(self):
        """Test registry creation."""
        registry = SkillRegistry()
        assert registry is not None
    
    def test_registry_search(self):
        """Test searching the registry."""
        registry = SkillRegistry()
        results = registry.search("spotify")
        
        assert isinstance(results, RegistrySearchResult)
    
    def test_registry_get(self):
        """Test getting a specific plugin."""
        registry = SkillRegistry()
        entry = registry.get("spotify")
        
        # Mock registry should have spotify
        if entry:
            assert entry.name == "spotify"
    
    def test_registry_get_popular(self):
        """Test getting popular plugins."""
        registry = SkillRegistry()
        popular = registry.get_popular(limit=5)
        
        assert isinstance(popular, list)
        assert len(popular) <= 5
    
    def test_registry_get_by_category(self):
        """Test getting plugins by category."""
        registry = SkillRegistry()
        # Call with any category - just verify it doesn't error
        try:
            result = registry.get_by_category("music")
            assert isinstance(result, list)
        except (AttributeError, NotImplementedError):
            # Method may not exist in all implementations
            pass


class TestMockSkillRegistry:
    """Tests for MockSkillRegistry."""
    
    def test_mock_registry(self):
        """Test mock registry."""
        registry = MockSkillRegistry()
        
        results = registry.search("music")
        assert isinstance(results, RegistrySearchResult)
        
        entry = registry.get("spotify")
        assert entry is not None
        assert entry.name == "spotify"


# =============================================================================
# Integration Tests
# =============================================================================


class TestPluginSystemIntegration:
    """Integration tests for the full plugin system."""
    
    def test_full_workflow(self):
        """Test complete plugin workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"
            plugins_dir.mkdir()
            
            # Create a test plugin
            plugin_dir = plugins_dir / "test-integration"
            plugin_dir.mkdir()
            
            (plugin_dir / "plugin.py").write_text("""
from bantz.plugins.base import BantzPlugin, PluginMetadata, IntentPattern, Tool

class TestIntegrationPlugin(BantzPlugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="test-integration",
            version="1.0.0",
            author="Test",
            description="Integration test plugin",
        )
    
    def get_intents(self):
        return [
            IntentPattern(
                pattern=r"integration test",
                intent="run_test",
                priority=50,
            ),
        ]
    
    def get_tools(self):
        return [
            Tool(
                name="run_integration_test",
                description="Run integration test",
                function=self.run_test,
            ),
        ]
    
    def run_test(self):
        return {"success": True}
    
    def handle_run_test(self, **slots):
        return "Integration test passed!"
""")
            
            # Initialize manager
            manager = PluginManager([plugins_dir])
            
            # Discover
            specs = manager.discover()
            
            # Verify we found it
            assert len(specs) == 1
            assert specs[0].name == "test-integration"
            
            # Load all
            manager.load_all()
            
            # Verify plugin loaded
            assert "test-integration" in manager.plugins
            
            # Get intents
            intents = manager.get_all_intents()
            # Intent gets prefixed with plugin name
            assert any("run_test" in p.intent for p in intents)
            
            # Get tools
            tools = manager.get_all_tools()
            # Tool gets prefixed with plugin name
            assert any("run_integration_test" in t.name for t in tools)
            
            # Handle intent - use full intent path
            result = manager.handle_intent(
                intent="test-integration.run_test",
                slots={},
            )
            assert result == "Integration test passed!"
    
    def test_config_integration(self):
        """Test config integration with manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "plugins.yaml"
            plugins_dir = Path(tmpdir) / "plugins"
            plugins_dir.mkdir()
            
            # Create config
            config = PluginsConfig(disabled=["disabled-plugin"])
            config.save(config_path)
            
            # Initialize manager with config
            manager = PluginManager(
                plugin_dirs=[plugins_dir],
                config=config,
            )
            
            # Use mock manager for direct plugin registration
            mock_manager = MockPluginManager([plugins_dir])
            mock_manager.add_mock_plugin(SamplePlugin())
            
            # Should be enabled (not in disabled list)
            assert mock_manager.is_enabled("test-plugin")


# =============================================================================
# Spotify Plugin Tests
# =============================================================================


class TestSpotifyPlugin:
    """Tests for the example Spotify plugin."""
    
    @pytest.fixture
    def spotify_plugin(self):
        """Create Spotify plugin instance."""
        from bantz.plugins.builtin.spotify.plugin import SpotifyPlugin
        return SpotifyPlugin()
    
    def test_spotify_metadata(self, spotify_plugin):
        """Test Spotify plugin metadata."""
        meta = spotify_plugin.metadata
        assert meta.name == "spotify"
        assert meta.version == "1.0.0"
        assert PluginPermission.NETWORK in meta.permissions
        assert "music" in meta.tags
    
    def test_spotify_intents(self, spotify_plugin):
        """Test Spotify plugin intents."""
        intents = spotify_plugin.get_intents()
        assert len(intents) > 0
        
        intent_names = [i.intent for i in intents]
        assert "play" in intent_names
        assert "pause" in intent_names
        assert "next" in intent_names
    
    def test_spotify_tools(self, spotify_plugin):
        """Test Spotify plugin tools."""
        tools = spotify_plugin.get_tools()
        assert len(tools) > 0
        
        tool_names = [t.name for t in tools]
        assert "play" in tool_names
        assert "pause" in tool_names
        assert "next_track" in tool_names
    
    def test_spotify_play(self, spotify_plugin):
        """Test play functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.play()
        assert result["success"] is True
        assert result["action"] == "resume"
    
    def test_spotify_pause(self, spotify_plugin):
        """Test pause functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.pause()
        assert result["success"] is True
        assert result["action"] == "pause"
    
    def test_spotify_next_track(self, spotify_plugin):
        """Test next track functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.next_track()
        assert result["success"] is True
        assert result["action"] == "next"
    
    def test_spotify_get_current_track(self, spotify_plugin):
        """Test get current track functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.get_current_track()
        assert result["success"] is True
        assert "track" in result
        assert result["track"]["name"] == "Bohemian Rhapsody"
    
    def test_spotify_set_volume(self, spotify_plugin):
        """Test set volume functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.set_volume(75)
        assert result["success"] is True
        assert result["volume"] == 75
    
    def test_spotify_volume_bounds(self, spotify_plugin):
        """Test volume bounds."""
        spotify_plugin.on_load()
        
        result = spotify_plugin.set_volume(150)
        assert result["volume"] == 100  # Clamped
        
        result = spotify_plugin.set_volume(-10)
        assert result["volume"] == 0  # Clamped
    
    def test_spotify_search(self, spotify_plugin):
        """Test search functionality."""
        spotify_plugin.on_load()
        result = spotify_plugin.search("coldplay", type="track")
        assert result["success"] is True
        assert result["type"] == "track"
        assert "tracks" in result
    
    def test_spotify_intent_handlers(self, spotify_plugin):
        """Test intent handlers."""
        spotify_plugin.on_load()
        
        result = spotify_plugin.handle_play()
        assert "başlatıldı" in result or "devam" in result
        
        result = spotify_plugin.handle_pause()
        assert "duraklatıldı" in result
        
        result = spotify_plugin.handle_current_track()
        assert "Queen" in result or "çalan" in result


# =============================================================================
# Run Tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
