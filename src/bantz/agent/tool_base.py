"""
Tool Base Interface (Issue #32 - V2-2).

Defines the standard interface for all Bantz tools including:
- ToolSpec: Tool configuration and metadata
- ToolContext: Execution context with job/event info
- ToolResult: Standardized result with error handling
- ToolBase: Abstract base class for all tools
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import time


class ErrorType(str, Enum):
    """Standardized error types for tool failures."""
    TIMEOUT = "timeout"
    NETWORK = "network"
    PARSE = "parse"
    AUTH = "auth"
    VALIDATION = "validation"
    UNKNOWN = "unknown"


@dataclass
class ToolSpec:
    """
    Tool specification and configuration.
    
    Attributes:
        name: Unique tool identifier
        description: Human-readable description
        parameters: JSON Schema for input parameters
        timeout: Maximum execution time in seconds (default 30)
        max_retries: Maximum retry attempts (default 3)
        requires_confirmation: Whether user confirmation is needed
        fallback_tool: Name of fallback tool if this fails
    """
    name: str
    description: str
    parameters: dict
    timeout: float = 30.0
    max_retries: int = 3
    requires_confirmation: bool = False
    fallback_tool: Optional[str] = None
    
    def __post_init__(self):
        """Validate and normalize timeout bounds."""
        # Enforce timeout bounds
        if self.timeout < MIN_TIMEOUT:
            self.timeout = MIN_TIMEOUT
        elif self.timeout > MAX_TIMEOUT:
            self.timeout = MAX_TIMEOUT


@dataclass
class ToolContext:
    """
    Execution context passed to tools.
    
    Provides access to job info, event bus, and session data.
    """
    job_id: str
    event_bus: Any  # EventBus type (avoid circular import)
    user_id: Optional[str] = None
    session_data: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.
    
    Attributes:
        success: Whether the tool completed successfully
        data: Result data (if success=True)
        error: Error message (if success=False)
        error_type: Categorized error type
        duration_ms: Execution time in milliseconds
        retries_used: Number of retries before success/failure
        fallback_used: Whether fallback tool was used
        metadata: Additional metadata
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[ErrorType] = None
    duration_ms: float = 0
    retries_used: int = 0
    fallback_used: bool = False
    metadata: dict = field(default_factory=dict)
    
    @classmethod
    def ok(cls, data: Any, duration_ms: float = 0, **kwargs) -> "ToolResult":
        """Create successful result."""
        return cls(success=True, data=data, duration_ms=duration_ms, **kwargs)
    
    @classmethod
    def fail(
        cls,
        error: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
        duration_ms: float = 0,
        **kwargs
    ) -> "ToolResult":
        """Create failure result."""
        return cls(
            success=False,
            error=error,
            error_type=error_type,
            duration_ms=duration_ms,
            **kwargs
        )
    
    @classmethod
    def timeout(cls, duration_ms: float = 0) -> "ToolResult":
        """Create timeout result."""
        return cls.fail(
            error="Tool execution timed out",
            error_type=ErrorType.TIMEOUT,
            duration_ms=duration_ms
        )


# Timeout bounds
DEFAULT_TIMEOUT = 30.0
MIN_TIMEOUT = 20.0
MAX_TIMEOUT = 60.0


class ToolTimeoutError(Exception):
    """Raised when tool execution exceeds timeout."""
    pass


class ToolValidationError(Exception):
    """Raised when tool input validation fails."""
    pass


class ToolBase(ABC):
    """
    Abstract base class for all Bantz tools.
    
    Subclasses must implement:
        - spec(): Return tool specification
        - run(): Execute the tool
    
    Example:
        class MyTool(ToolBase):
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="my_tool",
                    description="Does something useful",
                    parameters={"query": {"type": "string", "required": True}}
                )
            
            async def run(self, input: dict, context: ToolContext) -> ToolResult:
                query = input["query"]
                result = await do_something(query)
                return ToolResult.ok(result)
    """
    
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool specification."""
        ...
    
    @abstractmethod
    async def run(self, input: dict, context: ToolContext) -> ToolResult:
        """
        Execute the tool with given input.
        
        Args:
            input: Input parameters matching spec.parameters
            context: Execution context
            
        Returns:
            ToolResult with success/failure status
        """
        ...
    
    def validate_input(self, input: dict) -> tuple[bool, str]:
        """
        Validate input against spec parameters.
        
        Args:
            input: Input dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        spec = self.spec()
        params = spec.parameters
        
        # Check required parameters
        for param_name, param_def in params.items():
            if isinstance(param_def, dict) and param_def.get("required", False):
                if param_name not in input:
                    return False, f"Required parameter '{param_name}' is missing"
                if input[param_name] is None or input[param_name] == "":
                    return False, f"Required parameter '{param_name}' cannot be empty"
        
        # Check parameter types
        for param_name, value in input.items():
            if param_name in params:
                param_def = params[param_name]
                if isinstance(param_def, dict):
                    expected_type = param_def.get("type")
                    if expected_type and not self._check_type(value, expected_type):
                        return False, f"Parameter '{param_name}' must be of type '{expected_type}'"
        
        return True, ""
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON Schema type."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        
        if expected_type not in type_map:
            return True  # Unknown type, allow
        
        return isinstance(value, type_map[expected_type])
    
    @property
    def name(self) -> str:
        """Shortcut for spec().name."""
        return self.spec().name
    
    @property
    def timeout(self) -> float:
        """Shortcut for spec().timeout."""
        return self.spec().timeout
    
    @property
    def max_retries(self) -> int:
        """Shortcut for spec().max_retries."""
        return self.spec().max_retries
