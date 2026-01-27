"""
Fallback Runner (Issue #32 - V2-2).

Provides fallback mechanism when primary tool fails.
If a tool has a fallback_tool configured, it will be tried
when the primary tool fails.
"""

from typing import Optional, Protocol
from bantz.agent.tool_base import (
    ToolBase,
    ToolContext,
    ToolResult,
    ErrorType,
)


class ToolRegistry(Protocol):
    """Protocol for tool registry lookup."""
    
    def get(self, name: str) -> Optional[ToolBase]:
        """Get tool by name."""
        ...


class SimpleToolRegistry:
    """Simple in-memory tool registry."""
    
    def __init__(self):
        self._tools: dict[str, ToolBase] = {}
    
    def register(self, tool: ToolBase) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Optional[ToolBase]:
        """Get tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools


class FallbackRunner:
    """
    Runs tools with fallback support.
    
    When a primary tool fails, if it has a fallback_tool configured,
    the fallback will be attempted. The fallback_used flag in
    ToolResult indicates whether fallback was used.
    
    Example:
        registry = SimpleToolRegistry()
        registry.register(primary_tool)
        registry.register(fallback_tool)
        
        runner = FallbackRunner(registry)
        result = await runner.run_with_fallback(
            primary_tool, {"query": "test"}, context
        )
        
        if result.fallback_used:
            print("Fallback was used")
    """
    
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_runner: Optional["ToolRunner"] = None
    ):
        """
        Initialize FallbackRunner.
        
        Args:
            tool_registry: Registry to look up fallback tools
            tool_runner: Optional ToolRunner for executing tools
                        (if None, will call tool.run directly)
        """
        self.tool_registry = tool_registry
        self.tool_runner = tool_runner
    
    async def run_with_fallback(
        self,
        tool: ToolBase,
        input: dict,
        context: ToolContext,
        max_fallback_depth: int = 3
    ) -> ToolResult:
        """
        Run tool with fallback on failure.
        
        Args:
            tool: Primary tool to run
            input: Input parameters
            context: Execution context
            max_fallback_depth: Maximum fallback chain length (prevents cycles)
            
        Returns:
            ToolResult from primary or fallback tool
        """
        # Try primary tool
        result = await self._run_tool(tool, input, context)
        
        if result.success:
            return result
        
        # Check for fallback
        spec = tool.spec()
        fallback_name = spec.fallback_tool
        
        if not fallback_name:
            # No fallback configured
            return result
        
        # Try fallback chain
        return await self._run_fallback_chain(
            tool=tool,
            primary_result=result,
            fallback_name=fallback_name,
            input=input,
            context=context,
            depth=0,
            max_depth=max_fallback_depth
        )
    
    async def _run_fallback_chain(
        self,
        tool: ToolBase,
        primary_result: ToolResult,
        fallback_name: str,
        input: dict,
        context: ToolContext,
        depth: int,
        max_depth: int
    ) -> ToolResult:
        """Run fallback tools recursively up to max_depth."""
        if depth >= max_depth:
            # Max depth reached, return primary result
            return primary_result
        
        fallback_tool = self.tool_registry.get(fallback_name)
        
        if not fallback_tool:
            # Fallback tool not found
            return primary_result
        
        # Run fallback
        fallback_result = await self._run_tool(fallback_tool, input, context)
        
        if fallback_result.success:
            # Mark that fallback was used
            fallback_result.fallback_used = True
            fallback_result.metadata["primary_tool"] = tool.name
            fallback_result.metadata["fallback_tool"] = fallback_name
            return fallback_result
        
        # Fallback failed, check if it has its own fallback
        fallback_spec = fallback_tool.spec()
        next_fallback = fallback_spec.fallback_tool
        
        if next_fallback:
            return await self._run_fallback_chain(
                tool=fallback_tool,
                primary_result=fallback_result,
                fallback_name=next_fallback,
                input=input,
                context=context,
                depth=depth + 1,
                max_depth=max_depth
            )
        
        # No more fallbacks, return last result
        return fallback_result
    
    async def _run_tool(
        self,
        tool: ToolBase,
        input: dict,
        context: ToolContext
    ) -> ToolResult:
        """Run a single tool (via ToolRunner if available)."""
        if self.tool_runner:
            return await self.tool_runner.run(tool, input, context)
        else:
            # Direct execution without retry/timeout
            try:
                return await tool.run(input, context)
            except Exception as e:
                return ToolResult.fail(
                    error=str(e),
                    error_type=ErrorType.UNKNOWN
                )


# Import for type hints (avoid circular import)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bantz.agent.tool_runner import ToolRunner
