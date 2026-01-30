"""
Tests for Tool Base (Issue #32 - V2-2).

Tests ToolSpec, ToolContext, ToolResult, and ToolBase.
"""

import pytest
from bantz.agent.tool_base import (
    ToolSpec,
    ToolContext,
    ToolResult,
    ToolBase,
    ErrorType,
    ToolTimeoutError,
    ToolValidationError,
    DEFAULT_TIMEOUT,
    MIN_TIMEOUT,
    MAX_TIMEOUT,
)


class TestToolSpec:
    """Test ToolSpec configuration."""
    
    def test_tool_spec_default_timeout_30(self):
        """Default timeout is 30 seconds."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={}
        )
        assert spec.timeout == 30.0
    
    def test_tool_spec_default_retries_3(self):
        """Default max_retries is 3."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={}
        )
        assert spec.max_retries == 3
    
    def test_tool_spec_custom_timeout(self):
        """Custom timeout is respected within bounds."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={},
            timeout=45.0
        )
        assert spec.timeout == 45.0
    
    def test_tool_spec_timeout_min_20s(self):
        """Timeout below MIN_TIMEOUT is clamped to MIN_TIMEOUT."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={},
            timeout=10.0  # Below MIN_TIMEOUT
        )
        assert spec.timeout == MIN_TIMEOUT  # 20.0
    
    def test_tool_spec_timeout_max_60s(self):
        """Timeout above MAX_TIMEOUT is clamped to MAX_TIMEOUT."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={},
            timeout=120.0  # Above MAX_TIMEOUT
        )
        assert spec.timeout == MAX_TIMEOUT  # 60.0
    
    def test_tool_spec_requires_confirmation_default_false(self):
        """requires_confirmation defaults to False."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={}
        )
        assert spec.requires_confirmation is False
    
    def test_tool_spec_fallback_tool_default_none(self):
        """fallback_tool defaults to None."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={}
        )
        assert spec.fallback_tool is None
    
    def test_tool_spec_with_fallback(self):
        """fallback_tool can be set."""
        spec = ToolSpec(
            name="test",
            description="Test tool",
            parameters={},
            fallback_tool="fallback_test"
        )
        assert spec.fallback_tool == "fallback_test"


class TestToolResult:
    """Test ToolResult creation."""
    
    def test_tool_result_success_true(self):
        """success=True result contains data."""
        result = ToolResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None
    
    def test_tool_result_success_false(self):
        """success=False result contains error."""
        result = ToolResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.data is None
    
    def test_tool_result_error_types(self):
        """error_type is valid ErrorType enum."""
        for error_type in ErrorType:
            result = ToolResult(
                success=False,
                error="Error",
                error_type=error_type
            )
            assert result.error_type == error_type
    
    def test_tool_result_ok_factory(self):
        """ToolResult.ok() creates success result."""
        result = ToolResult.ok(data={"result": 42}, duration_ms=100.5)
        assert result.success is True
        assert result.data == {"result": 42}
        assert result.duration_ms == 100.5
    
    def test_tool_result_fail_factory(self):
        """ToolResult.fail() creates failure result."""
        result = ToolResult.fail(
            error="Network error",
            error_type=ErrorType.NETWORK,
            duration_ms=50.0
        )
        assert result.success is False
        assert result.error == "Network error"
        assert result.error_type == ErrorType.NETWORK
    
    def test_tool_result_timeout_factory(self):
        """ToolResult.timeout() creates timeout result."""
        result = ToolResult.timeout(duration_ms=30000)
        assert result.success is False
        assert result.error_type == ErrorType.TIMEOUT
        assert "timed out" in result.error.lower()
    
    def test_tool_result_retries_used(self):
        """retries_used is tracked."""
        result = ToolResult(success=True, data=None, retries_used=2)
        assert result.retries_used == 2
    
    def test_tool_result_fallback_used(self):
        """fallback_used is tracked."""
        result = ToolResult(success=True, data=None, fallback_used=True)
        assert result.fallback_used is True


class TestToolContext:
    """Test ToolContext."""
    
    def test_tool_context_required_fields(self):
        """job_id and event_bus are required."""
        class MockEventBus:
            pass
        
        ctx = ToolContext(job_id="job123", event_bus=MockEventBus())
        assert ctx.job_id == "job123"
    
    def test_tool_context_optional_user_id(self):
        """user_id is optional."""
        ctx = ToolContext(job_id="job123", event_bus=None, user_id="user456")
        assert ctx.user_id == "user456"
    
    def test_tool_context_session_data_default_empty(self):
        """session_data defaults to empty dict."""
        ctx = ToolContext(job_id="job123", event_bus=None)
        assert ctx.session_data == {}


class TestToolBase:
    """Test ToolBase abstract class."""
    
    def test_tool_base_abstract_methods(self):
        """ToolBase cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ToolBase()
    
    def test_tool_base_concrete_implementation(self):
        """Concrete implementation works."""
        class MyTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="my_tool",
                    description="Test tool",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data={"result": input["query"]})
        
        tool = MyTool()
        assert tool.name == "my_tool"
        assert tool.timeout == 30.0
        assert tool.max_retries == 3
    
    def test_tool_validate_input_required(self):
        """Required param missing returns error."""
        class MyTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="my_tool",
                    description="Test tool",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data=None)
        
        tool = MyTool()
        is_valid, error = tool.validate_input({})
        assert is_valid is False
        assert "query" in error
        assert "missing" in error.lower()
    
    def test_tool_validate_input_empty_required(self):
        """Empty required param returns error."""
        class MyTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="my_tool",
                    description="Test tool",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data=None)
        
        tool = MyTool()
        is_valid, error = tool.validate_input({"query": ""})
        assert is_valid is False
        assert "empty" in error.lower()
    
    def test_tool_validate_input_valid(self):
        """Valid input passes validation."""
        class MyTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="my_tool",
                    description="Test tool",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data=None)
        
        tool = MyTool()
        is_valid, error = tool.validate_input({"query": "hello"})
        assert is_valid is True
        assert error == ""
    
    def test_tool_validate_input_type_check(self):
        """Type mismatch returns error."""
        class MyTool(ToolBase):
            def spec(self):
                return ToolSpec(
                    name="my_tool",
                    description="Test tool",
                    parameters={"count": {"type": "integer", "required": True}}
                )
            
            async def run(self, input, context):
                return ToolResult.ok(data=None)
        
        tool = MyTool()
        is_valid, error = tool.validate_input({"count": "not_an_int"})
        assert is_valid is False
        assert "integer" in error.lower()


class TestConstants:
    """Test module constants."""
    
    def test_default_timeout(self):
        """DEFAULT_TIMEOUT is 30."""
        assert DEFAULT_TIMEOUT == 30.0
    
    def test_min_timeout(self):
        """MIN_TIMEOUT is 20."""
        assert MIN_TIMEOUT == 20.0
    
    def test_max_timeout(self):
        """MAX_TIMEOUT is 60."""
        assert MAX_TIMEOUT == 60.0


class TestExceptions:
    """Test custom exceptions."""
    
    def test_tool_timeout_error(self):
        """ToolTimeoutError can be raised."""
        with pytest.raises(ToolTimeoutError):
            raise ToolTimeoutError("Timeout!")
    
    def test_tool_validation_error(self):
        """ToolValidationError can be raised."""
        with pytest.raises(ToolValidationError):
            raise ToolValidationError("Invalid input!")
