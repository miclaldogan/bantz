"""Pydantic Schemas for Router Output - Strict Validation (Issue #156).

This module provides strict Pydantic schemas for LLM router output validation.
Key features:
- Enum enforcement for routes and intents
- Strict type checking (list[str] not str)
- Extra fields forbidden
- Turkish language validation
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class RouteType(str, Enum):
    """Valid route types for router output."""
    CALENDAR = "calendar"
    GMAIL = "gmail"
    SYSTEM = "system"
    SMALLTALK = "smalltalk"
    UNKNOWN = "unknown"


class CalendarIntent(str, Enum):
    """Valid calendar intents."""
    CREATE = "create"
    MODIFY = "modify"
    CANCEL = "cancel"
    QUERY = "query"
    NONE = "none"


class RouterSlots(BaseModel):
    """Slot extraction schema (flexible dict for now)."""
    
    model_config = ConfigDict(extra="allow")  # Allow dynamic slots
    
    date: Optional[str] = None
    time: Optional[str] = None
    duration: Optional[str] = None
    title: Optional[str] = None
    window_hint: Optional[str] = None


class RouterOutputSchema(BaseModel):
    """Strict schema for router LLM output (Issue #156).
    
    Enforces:
    - Route enum (calendar|smalltalk|unknown)
    - Calendar intent enum (create|modify|cancel|query|none)
    - tool_plan as list[str] (NOT string)
    - Turkish confirmation prompts
    
    Config:
    - extra = "forbid": Reject unexpected fields
    - validate_assignment: Validate on field assignment
    """
    
    model_config = ConfigDict(
        extra="forbid",  # Reject extra fields
        validate_assignment=True,  # Validate on assignment
        str_strip_whitespace=True,  # Strip whitespace from strings
    )
    
    # Core routing
    route: RouteType = Field(
        ...,
        description="Route classification (calendar|smalltalk|unknown)"
    )
    calendar_intent: CalendarIntent = Field(
        ...,
        description="Calendar intent (create|modify|cancel|query|none)"
    )
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted slots (date, time, duration, title, etc.)"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0)"
    )
    tool_plan: list[str] = Field(
        default_factory=list,
        description="Tool execution plan (must be list, not string)"
    )
    assistant_reply: str = Field(
        default="",
        description="Assistant response text"
    )
    
    # Orchestrator extensions
    ask_user: bool = Field(
        default=False,
        description="Need clarification?"
    )
    question: str = Field(
        default="",
        description="Clarification question"
    )
    requires_confirmation: bool = Field(
        default=False,
        description="Destructive operation requiring confirmation?"
    )
    confirmation_prompt: str = Field(
        default="",
        description="Confirmation prompt (must be Turkish)"
    )
    memory_update: str = Field(
        default="",
        description="Memory/dialog summary update"
    )
    reasoning_summary: list[str] = Field(
        default_factory=list,
        description="Reasoning summary (1-3 bullet points)"
    )
    
    @field_validator("tool_plan", mode="before")
    @classmethod
    def coerce_tool_plan_to_list(cls, v):
        """Coerce tool_plan from string to list if needed."""
        if isinstance(v, str):
            # LLM sometimes returns "tool_name" instead of ["tool_name"]
            if v.strip():
                return [v.strip()]
            return []
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item).strip() for item in v if item]
        return []
    
    @field_validator("confirmation_prompt")
    @classmethod
    def validate_turkish_confirmation(cls, v, info):
        """Validate that confirmation prompts are in Turkish."""
        # Requires confirmation but prompt is empty
        requires_confirmation = info.data.get("requires_confirmation", False)
        if requires_confirmation:
            if not v or not v.strip():
                raise ValueError("confirmation_prompt cannot be empty when requires_confirmation=True")
        
        # If no prompt, return early
        if not v:
            return v
        
        # Basic Turkish check: common Turkish words
        turkish_indicators = [
            "efendim", "musunuz", "misiniz", "mısınız", "oluştur", 
            "sil", "değiştir", "onay", "tamam", "evet", "hayır",
            "için", "ile", "olsun", "yapacak", "göre"
        ]
        
        v_lower = v.lower()
        has_turkish = any(word in v_lower for word in turkish_indicators)
        
        # Only warn if requires_confirmation (strict for destructive ops)
        if requires_confirmation and not has_turkish:
            # Lenient: Allow if short or contains question mark
            if len(v) < 20 or "?" in v:
                return v
            raise ValueError(
                f"confirmation_prompt should be in Turkish, got: {v[:50]}..."
            )
        
        return v
    
    @field_validator("reasoning_summary", mode="before")
    @classmethod
    def coerce_reasoning_to_list(cls, v):
        """Coerce reasoning_summary to list if needed."""
        if v is None:
            return []
        if isinstance(v, str):
            # Split by common separators
            if "\n" in v:
                return [line.strip() for line in v.split("\n") if line.strip()]
            return [v.strip()] if v.strip() else []
        if isinstance(v, list):
            return [str(item).strip() for item in v if item]
        return []


class RouterErrorResponse(BaseModel):
    """Schema for router error responses."""
    
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    raw_output: Optional[str] = Field(None, description="Raw LLM output for debugging")


def validate_router_output(data: dict[str, Any]) -> RouterOutputSchema:
    """Validate router output against strict schema.
    
    Args:
        data: Raw router output dictionary
        
    Returns:
        Validated RouterOutputSchema
        
    Raises:
        ValidationError: If validation fails
        
    Example:
        >>> data = {"route": "calendar", "calendar_intent": "query", ...}
        >>> validated = validate_router_output(data)
        >>> assert validated.route == RouteType.CALENDAR
    """
    return RouterOutputSchema.model_validate(data)


def router_output_to_dict(schema: RouterOutputSchema) -> dict[str, Any]:
    """Convert RouterOutputSchema to dictionary.
    
    Args:
        schema: Validated schema instance
        
    Returns:
        Dictionary representation
    """
    return schema.model_dump(mode="python")
