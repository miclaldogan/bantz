"""
Tests for Fallback Runner (Issue #32 - V2-2).

Tests FallbackRunner and fallback mechanism.
"""

import pytest
from bantz.agent.tool_base import (
    ToolBase,
    ToolSpec,
    ToolContext,
    ToolResult,
    ErrorType,
)
from bantz.agent.fallback import (
    FallbackRunner,
    SimpleToolRegistry,
)
from bantz.core.events import EventBus


class PrimaryTool(ToolBase):
    """Primary tool that can succeed or fail."""
    
    def __init__(self, should_fail: bool = False, fallback_tool: str = None):
        self._should_fail = should_fail
        self._fallback_tool = fallback_tool
    
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="primary_tool",
            description="Primary tool",
            parameters={},
            fallback_tool=self._fallback_tool
        )
    
    async def run(self, input: dict, context: ToolContext) -> ToolResult:
        if self._should_fail:
            return ToolResult.fail(
                error="Primary failed",
                error_type=ErrorType.NETWORK
            )
        return ToolResult.ok(data={"source": "primary"})


class FallbackTool(ToolBase):
    """Fallback tool."""
    
    def __init__(self, should_fail: bool = False):
        self._should_fail = should_fail
    
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="fallback_tool",
            description="Fallback tool",
            parameters={}
        )
    
    async def run(self, input: dict, context: ToolContext) -> ToolResult:
        if self._should_fail:
            return ToolResult.fail(
                error="Fallback failed",
                error_type=ErrorType.NETWORK
            )
        return ToolResult.ok(data={"source": "fallback"})


@pytest.fixture
def event_bus():
    """Create EventBus for testing."""
    return EventBus()


@pytest.fixture
def context(event_bus):
    """Create ToolContext for testing."""
    return ToolContext(job_id="test-job-123", event_bus=event_bus)


class TestSimpleToolRegistry:
    """Test SimpleToolRegistry."""
    
    def test_registry_register_and_get(self):
        """Register and retrieve tool."""
        registry = SimpleToolRegistry()
        tool = PrimaryTool()
        
        registry.register(tool)
        
        retrieved = registry.get("primary_tool")
        assert retrieved is tool
    
    def test_registry_get_nonexistent(self):
        """Get returns None for unknown tool."""
        registry = SimpleToolRegistry()
        
        assert registry.get("unknown") is None
    
    def test_registry_list_tools(self):
        """list_tools returns all registered names."""
        registry = SimpleToolRegistry()
        registry.register(PrimaryTool())
        registry.register(FallbackTool())
        
        tools = registry.list_tools()
        
        assert "primary_tool" in tools
        assert "fallback_tool" in tools
    
    def test_registry_contains(self):
        """__contains__ works."""
        registry = SimpleToolRegistry()
        registry.register(PrimaryTool())
        
        assert "primary_tool" in registry
        assert "unknown" not in registry


class TestFallbackNotUsed:
    """Test when fallback is not needed."""
    
    @pytest.mark.asyncio
    async def test_fallback_not_used_on_success(self, context):
        """Fallback not used when primary succeeds."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=False, fallback_tool="fallback_tool")
        fallback = FallbackTool()
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is True
        assert result.data["source"] == "primary"
        assert result.fallback_used is False


class TestFallbackUsed:
    """Test when fallback is used."""
    
    @pytest.mark.asyncio
    async def test_fallback_used_on_failure(self, context):
        """Fallback used when primary fails."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool(should_fail=False)
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is True
        assert result.data["source"] == "fallback"
    
    @pytest.mark.asyncio
    async def test_fallback_marked_in_result(self, context):
        """fallback_used is True when fallback used."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool()
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.fallback_used is True
    
    @pytest.mark.asyncio
    async def test_fallback_returns_data(self, context):
        """Fallback result contains data."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool()
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.data == {"source": "fallback"}
    
    @pytest.mark.asyncio
    async def test_fallback_metadata_contains_tool_names(self, context):
        """Metadata contains primary and fallback tool names."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool()
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.metadata["primary_tool"] == "primary_tool"
        assert result.metadata["fallback_tool"] == "fallback_tool"


class TestNoFallbackConfigured:
    """Test when no fallback is configured."""
    
    @pytest.mark.asyncio
    async def test_no_fallback_configured(self, context):
        """Returns primary error when no fallback configured."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool=None)
        
        registry.register(primary)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is False
        assert result.error == "Primary failed"
    
    @pytest.mark.asyncio
    async def test_fallback_not_found(self, context):
        """Returns primary error when fallback not in registry."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="nonexistent_fallback")
        
        registry.register(primary)
        # Don't register fallback
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is False


class TestFallbackChain:
    """Test fallback chain behavior."""
    
    @pytest.mark.asyncio
    async def test_fallback_also_fails(self, context):
        """Returns fallback error when both fail."""
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool(should_fail=True)
        
        registry.register(primary)
        registry.register(fallback)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is False
        assert "Fallback failed" in result.error
    
    @pytest.mark.asyncio
    async def test_max_fallback_depth(self, context):
        """Respects max_fallback_depth limit."""
        # Create chain: tool1 -> tool2 -> tool3 -> tool4
        class ChainedTool(ToolBase):
            def __init__(self, name: str, next_tool: str = None):
                self._name = name
                self._next = next_tool
            
            def spec(self):
                return ToolSpec(
                    name=self._name,
                    description="Chained tool",
                    parameters={},
                    fallback_tool=self._next
                )
            
            async def run(self, input, context):
                return ToolResult.fail(error=f"{self._name} failed")
        
        registry = SimpleToolRegistry()
        registry.register(ChainedTool("tool1", "tool2"))
        registry.register(ChainedTool("tool2", "tool3"))
        registry.register(ChainedTool("tool3", "tool4"))
        registry.register(ChainedTool("tool4", None))
        
        runner = FallbackRunner(registry)
        
        # With max_depth=2, should try: tool1 -> tool2 -> tool3 (stops)
        result = await runner.run_with_fallback(
            registry.get("tool1"),
            {},
            context,
            max_fallback_depth=2
        )
        
        assert result.success is False


class TestFallbackWithToolRunner:
    """Test FallbackRunner with ToolRunner integration."""
    
    @pytest.mark.asyncio
    async def test_fallback_with_tool_runner(self, context):
        """FallbackRunner can use ToolRunner."""
        from bantz.agent.tool_runner import ToolRunner
        
        registry = SimpleToolRegistry()
        primary = PrimaryTool(should_fail=True, fallback_tool="fallback_tool")
        fallback = FallbackTool()
        
        registry.register(primary)
        registry.register(fallback)
        
        tool_runner = ToolRunner()
        runner = FallbackRunner(registry, tool_runner=tool_runner)
        
        result = await runner.run_with_fallback(primary, {}, context)
        
        assert result.success is True
        assert result.data["source"] == "fallback"
