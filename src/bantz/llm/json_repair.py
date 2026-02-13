"""JSON Repair and Validation Layer (Issue #156).

This module provides JSON repair capabilities for LLM outputs:
- Enum mapping (create_meeting → calendar)
- Type coercion (string → list for tool_plan)
- Structure repair
- Logging and statistics
"""

import json
import re
import logging
from typing import Any
from collections import defaultdict

from pydantic import ValidationError

from bantz.router.schemas import (
    RouterOutputSchema,
    RouteType,
    CalendarIntent,
    validate_router_output,
)

logger = logging.getLogger(__name__)


class RepairStats:
    """Track JSON repair statistics."""
    
    def __init__(self):
        self.total_attempts = 0
        self.successful_repairs = 0
        self.failed_repairs = 0
        self.repair_types = defaultdict(int)
    
    def record_attempt(self):
        self.total_attempts += 1
    
    def record_success(self, repair_type: str):
        self.successful_repairs += 1
        self.repair_types[repair_type] += 1
    
    def record_failure(self):
        self.failed_repairs += 1
    
    @property
    def repair_rate(self) -> float:
        """Calculate repair rate percentage."""
        if self.total_attempts == 0:
            return 0.0
        return (self.successful_repairs / self.total_attempts) * 100
    
    def summary(self) -> dict[str, Any]:
        """Get repair statistics summary."""
        return {
            "total_attempts": self.total_attempts,
            "successful_repairs": self.successful_repairs,
            "failed_repairs": self.failed_repairs,
            "repair_rate_percent": round(self.repair_rate, 2),
            "repair_types": dict(self.repair_types),
        }


# Global stats instance
_REPAIR_STATS = RepairStats()


def get_repair_stats() -> RepairStats:
    """Get global repair statistics."""
    return _REPAIR_STATS


def reset_repair_stats():
    """Reset global repair statistics."""
    global _REPAIR_STATS
    _REPAIR_STATS = RepairStats()


# Enum mapping tables
ROUTE_MAPPINGS = {
    # Common LLM mistakes → correct enum
    "create_meeting": "calendar",
    "schedule": "calendar",
    "create_event": "calendar",
    "event": "calendar",
    "appointment": "calendar",
    "meeting": "calendar",
    "chat": "smalltalk",
    "conversation": "smalltalk",
    "talk": "smalltalk",
    "greet": "smalltalk",
    "greeting": "smalltalk",
    "other": "unknown",
    "unclear": "unknown",
    "unsure": "unknown",
}

INTENT_MAPPINGS = {
    # Common LLM mistakes → correct enum
    "create_meeting": "create",
    "schedule": "create",
    "create_event": "create",
    "new": "create",
    "add": "create",
    "update": "modify",
    "change": "modify",
    "edit": "modify",
    "reschedule": "modify",
    "delete": "cancel",
    "remove": "cancel",
    "search": "query",
    "find": "query",
    "list": "query",
    "show": "query",
    "what": "query",
    "when": "query",
    "na": "none",
    "null": "none",
    "empty": "none",
}


def repair_route_enum(route: str) -> str:
    """Repair route value to valid enum.
    
    Args:
        route: Raw route string from LLM
        
    Returns:
        Repaired route (calendar|gmail|smalltalk|system|unknown)
    """
    route_lower = route.lower().strip()
    
    # Already valid? (Issue #421: expanded valid set to match llm_router)
    if route_lower in {"calendar", "gmail", "smalltalk", "system", "unknown"}:
        return route_lower
    
    # Try mapping
    if route_lower in ROUTE_MAPPINGS:
        repaired = ROUTE_MAPPINGS[route_lower]
        logger.info(f"Repaired route: {route} → {repaired}")
        _REPAIR_STATS.record_success("route_enum")
        return repaired
    
    # Substring matching (e.g., "create_meeting_now" → "calendar")
    for key, value in ROUTE_MAPPINGS.items():
        if key in route_lower:
            logger.info(f"Fuzzy matched route: {route} → {value}")
            _REPAIR_STATS.record_success("route_fuzzy")
            return value
    
    # Default to unknown
    logger.warning(f"Could not repair route '{route}', defaulting to 'unknown'")
    _REPAIR_STATS.record_success("route_default")
    return "unknown"


def repair_intent_enum(intent: str) -> str:
    """Repair calendar_intent to valid enum.
    
    Args:
        intent: Raw intent string from LLM
        
    Returns:
        Repaired intent (create|modify|cancel|query|none)
    """
    intent_lower = intent.lower().strip()
    
    # Already valid?
    if intent_lower in ["create", "modify", "cancel", "query", "none"]:
        return intent_lower
    
    # Try mapping
    if intent_lower in INTENT_MAPPINGS:
        repaired = INTENT_MAPPINGS[intent_lower]
        logger.info(f"Repaired intent: {intent} → {repaired}")
        _REPAIR_STATS.record_success("intent_enum")
        return repaired
    
    # Substring matching
    for key, value in INTENT_MAPPINGS.items():
        if key in intent_lower:
            logger.info(f"Fuzzy matched intent: {intent} → {value}")
            _REPAIR_STATS.record_success("intent_fuzzy")
            return value
    
    # Default to none
    logger.warning(f"Could not repair intent '{intent}', defaulting to 'none'")
    _REPAIR_STATS.record_success("intent_default")
    return "none"


def repair_tool_plan(tool_plan: Any) -> list[str]:
    """Repair tool_plan to list[str].
    
    Args:
        tool_plan: Raw tool_plan from LLM (could be str, list, None)
        
    Returns:
        Repaired list[str]
    """
    if tool_plan is None:
        return []
    
    if isinstance(tool_plan, list):
        # Already list, just ensure strings
        return [str(item).strip() for item in tool_plan if item]
    
    if isinstance(tool_plan, str):
        # Single string → list
        tool_plan_clean = tool_plan.strip()
        if not tool_plan_clean:
            return []
        
        # Check if it's JSON array string
        if tool_plan_clean.startswith("[") and tool_plan_clean.endswith("]"):
            try:
                parsed = json.loads(tool_plan_clean)
                if isinstance(parsed, list):
                    logger.info(f"Parsed tool_plan from JSON string: {tool_plan_clean}")
                    _REPAIR_STATS.record_success("tool_plan_json_parse")
                    return [str(item).strip() for item in parsed if item]
            except json.JSONDecodeError:
                pass
        
        # Split by comma or newline
        if "," in tool_plan_clean or "\n" in tool_plan_clean:
            items = re.split(r"[,\n]+", tool_plan_clean)
            result = [item.strip() for item in items if item.strip()]
            if result:
                logger.info(f"Split tool_plan: '{tool_plan_clean}' → {result}")
                _REPAIR_STATS.record_success("tool_plan_split")
                return result
        
        # Single tool
        logger.info(f"Coerced tool_plan string to list: '{tool_plan_clean}'")
        _REPAIR_STATS.record_success("tool_plan_coerce")
        return [tool_plan_clean]
    
    # Unknown type
    logger.warning(f"Unknown tool_plan type: {type(tool_plan)}, defaulting to []")
    return []


def repair_json_structure(data: dict[str, Any]) -> dict[str, Any]:
    """Repair common JSON structure issues.
    
    Args:
        data: Raw LLM output dictionary
        
    Returns:
        Repaired dictionary
    """
    repaired = data.copy()
    
    # Repair route enum
    if "route" in repaired:
        original_route = repaired["route"]
        repaired["route"] = repair_route_enum(str(original_route))
    
    # Repair intent enum
    if "calendar_intent" in repaired:
        original_intent = repaired["calendar_intent"]
        repaired["calendar_intent"] = repair_intent_enum(str(original_intent))
    
    # Repair tool_plan
    if "tool_plan" in repaired:
        original_plan = repaired["tool_plan"]
        repaired["tool_plan"] = repair_tool_plan(original_plan)
    
    # Ensure required fields exist
    if "route" not in repaired:
        logger.warning("Missing 'route' field, defaulting to 'unknown'")
        repaired["route"] = "unknown"
        _REPAIR_STATS.record_success("field_default_route")
    
    if "calendar_intent" not in repaired:
        logger.warning("Missing 'calendar_intent' field, defaulting to 'none'")
        repaired["calendar_intent"] = "none"
        _REPAIR_STATS.record_success("field_default_intent")
    
    if "confidence" not in repaired:
        logger.warning("Missing 'confidence' field, defaulting to 0.5")
        repaired["confidence"] = 0.5
        _REPAIR_STATS.record_success("field_default_confidence")
    
    # Ensure confidence is float in [0, 1]
    if "confidence" in repaired:
        try:
            conf = float(repaired["confidence"])
            repaired["confidence"] = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            logger.warning(f"Invalid confidence value: {repaired['confidence']}, defaulting to 0.5")
            repaired["confidence"] = 0.5
            _REPAIR_STATS.record_success("confidence_repair")
    
    return repaired


def validate_and_repair_json(
    raw_output: str,
    max_repair_attempts: int = 3
) -> tuple[RouterOutputSchema | None, str | None]:
    """Validate and repair LLM JSON output.
    
    Args:
        raw_output: Raw LLM output string
        max_repair_attempts: Maximum repair attempts
        
    Returns:
        Tuple of (validated_schema, error_message)
        - (schema, None) on success
        - (None, error) on failure
    """
    _REPAIR_STATS.record_attempt()
    
    # Step 1: Parse JSON
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        _REPAIR_STATS.record_failure()
        return None, f"JSON parse error: {e}"
    
    # Step 2: Attempt validation (may succeed immediately)
    try:
        schema = validate_router_output(data)
        logger.info("Validation succeeded without repair")
        return schema, None
    except ValidationError as e:
        logger.info(f"Initial validation failed: {e.error_count()} errors")
    
    # Step 3: Repair and retry
    for attempt in range(max_repair_attempts):
        try:
            logger.info(f"Repair attempt {attempt + 1}/{max_repair_attempts}")
            repaired_data = repair_json_structure(data)
            schema = validate_router_output(repaired_data)
            logger.info(f"Validation succeeded after repair (attempt {attempt + 1})")
            return schema, None
        except ValidationError as e:
            logger.warning(f"Repair attempt {attempt + 1} failed: {e.error_count()} errors")
            if attempt == max_repair_attempts - 1:
                # Last attempt failed
                error_msg = f"Validation failed after {max_repair_attempts} repair attempts: {e}"
                logger.error(error_msg)
                _REPAIR_STATS.record_failure()
                return None, error_msg
            # Update data for next attempt
            data = repaired_data
    
    # Should not reach here
    _REPAIR_STATS.record_failure()
    return None, "Unknown validation error"


def extract_json_from_text(text: str) -> str | None:
    """Extract JSON from LLM output text (handles markdown, extra text).
    
    Args:
        text: Raw LLM output (may contain markdown, prose)
        
    Returns:
        Extracted JSON string or None if not found
    """
    # Try to find JSON in markdown code block
    json_block_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(json_block_pattern, text, re.DOTALL)
    if match:
        logger.info("Extracted JSON from markdown code block")
        return match.group(1)
    
    # Try to find JSON object
    json_pattern = r"\{.*\}"
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        logger.info("Extracted JSON object from text")
        return match.group(0)
    
    logger.warning("Could not extract JSON from text")
    return None
