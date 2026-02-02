"""LLM-Based JSON Repair for Bantz (Issue #86).

This module provides intelligent repair of malformed LLM outputs using
progressive repair strategies and error-specific guidance.

Key Features:
- Error-specific repair prompts
- Progressive repair strategies (simple → complex)
- Repair attempt tracking and metrics
- Turkish language support for repair prompts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from bantz.brain.json_protocol import (
    JsonParseError,
    ValidationError,
    extract_first_json_object,
    validate_action_shape,
    validate_tool_action,
)

logger = logging.getLogger(__name__)


class RepairLLM(Protocol):
    def complete_text(self, *, prompt: str) -> str: ...


@dataclass(frozen=True)
class RepairResult:
    """Result of JSON repair operation.
    
    Attributes:
        ok: Whether repair succeeded
        value: Repaired JSON object if successful
        attempts: Number of repair attempts made
        error: Final error message if repair failed
        error_type: Category of final error (parse_error, schema_error, etc.)
    """
    ok: bool
    value: dict[str, Any] | None
    attempts: int
    error: str | None = None
    error_type: str | None = None


def build_repair_prompt(*, raw_text: str, error_summary: str, validation_error: ValidationError | None = None) -> str:
    """Build error-specific repair prompt with detailed guidance.
    
    Args:
        raw_text: Original LLM output text
        error_summary: Summary of the error
        validation_error: Optional ValidationError with detailed context
        
    Returns:
        Repair prompt in Turkish with error-specific guidance
    """
    
    base_prompt = (
        "Aşağıdaki metinden sadece GEÇERLİ JSON OBJESİ döndür.\n"
        "- Markdown, backtick, açıklama, yorum, extra anahtar YAZMA.\n"
        "- Çıktın yalnızca tek bir JSON object olsun.\n"
        "- Trailing comma kullanma (son eleman sonrasında virgül olmasın).\n\n"
        "ZORUNLU ŞEKİL:\n"
        "- JSON object içinde mutlaka 'type' alanı olmalı.\n"
        "- type ∈ {SAY, CALL_TOOL, ASK_USER, FAIL}\n"
        "- SAY => {\"type\":\"SAY\",\"text\":\"...\"}\n"
        "- ASK_USER => {\"type\":\"ASK_USER\",\"question\":\"...\"}\n"
        "- FAIL => {\"type\":\"FAIL\",\"error\":\"...\"}\n"
        "- CALL_TOOL => {\"type\":\"CALL_TOOL\",\"name\":\"tool_name\",\"params\":{}}\n\n"
    )
    
    # Add error-specific guidance
    error_guidance = ""
    if validation_error:
        error_type = validation_error.error_type
        suggestions = validation_error.suggestions
        field_path = validation_error.field_path
        
        if error_type == "unknown_tool":
            error_guidance += "⚠️ TOOL HATASI:\n"
            if suggestions:
                error_guidance += f"- Geçerli tool adları: {', '.join(suggestions[:5])}\n"
            if field_path:
                error_guidance += f"- Hatalı alan: {field_path}\n"
        
        elif error_type == "schema_error":
            error_guidance += "⚠️ ŞEKİL HATASI:\n"
            if field_path:
                error_guidance += f"- Eksik/Hatalı alan: {field_path}\n"
            if suggestions:
                for sug in suggestions[:3]:
                    error_guidance += f"- {sug}\n"
        
        elif error_type == "missing_param":
            error_guidance += "⚠️ PARAMETRE HATASI:\n"
            if field_path:
                error_guidance += f"- Eksik parametre: {field_path}\n"
            if suggestions:
                error_guidance += f"- Gerekli: {', '.join(suggestions[:5])}\n"
        
        elif error_type == "bad_type":
            error_guidance += "⚠️ TİP HATASI:\n"
            if field_path:
                error_guidance += f"- Hatalı alan: {field_path}\n"
            if suggestions:
                error_guidance += f"- {suggestions[0]}\n"
        
        error_guidance += "\n"
    
    return (
        base_prompt +
        error_guidance +
        f"Hata özeti: {error_summary}\n\n"
        "Orijinal metin:\n"
        f"{raw_text}\n"
    )


def repair_to_json_object(
    *,
    llm: RepairLLM,
    raw_text: str,
    max_attempts: int = 2,
) -> RepairResult:
    """Try to repair arbitrary text into a valid JSON object using an LLM.
    
    Progressive repair strategy:
    1. First attempt: Generic repair prompt
    2. Subsequent attempts: Error-specific guidance
    
    Args:
        llm: LLM instance with complete_text method
        raw_text: Malformed text to repair
        max_attempts: Maximum repair attempts (default: 2)
        
    Returns:
        RepairResult with success status and repaired object
        
    Example:
        >>> result = repair_to_json_object(
        ...     llm=my_llm,
        ...     raw_text='```json\\n{"type": "SAY", "text": "hello",}\\n```'
        ... )
        >>> assert result.ok
        >>> assert result.value == {"type": "SAY", "text": "hello"}
    """

    last_error: str | None = None
    last_error_obj: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        # Build prompt with error-specific guidance if available
        validation_error = last_error_obj if isinstance(last_error_obj, ValidationError) else None
        prompt = build_repair_prompt(
            raw_text=raw_text,
            error_summary=last_error or "parse_or_schema_error",
            validation_error=validation_error
        )
        
        repaired = llm.complete_text(prompt=prompt)
        logger.debug(f"[json_repair] attempt {attempt}/{max_attempts}, repaired length: {len(repaired)}")

        try:
            obj = extract_first_json_object(repaired)
            logger.info(f"[json_repair] SUCCESS after {attempt} attempt(s)")
            return RepairResult(ok=True, value=obj, attempts=attempt)
        except JsonParseError as e:
            last_error = str(e)
            last_error_obj = e
            logger.info(f"[json_repair] attempt {attempt} failed (parse): {last_error}")
        except ValidationError as e:
            last_error = str(e)
            last_error_obj = e
            logger.info(f"[json_repair] attempt {attempt} failed (validation): {last_error}")
        except Exception as e:
            last_error = str(e)
            last_error_obj = e
            logger.info(f"[json_repair] attempt {attempt} failed (unexpected): {last_error}")

    error_type = getattr(last_error_obj, 'error_type', 'parse_error') if last_error_obj else 'parse_error'
    return RepairResult(
        ok=False,
        value=None,
        attempts=max_attempts,
        error=last_error,
        error_type=error_type
    )


def validate_or_repair_action(
    *,
    llm: RepairLLM,
    raw_text: str,
    tool_registry: Any,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Parse + validate a tool action; if it fails, repair up to max_attempts.
    
    Progressive repair with detailed error feedback:
    1. Try to extract and validate from raw text
    2. If fails, repair with error-specific guidance
    3. Retry validation on repaired text
    
    Args:
        llm: LLM instance for repair
        raw_text: Raw LLM output text
        tool_registry: Tool registry for validation
        max_attempts: Maximum repair attempts (default: 2)
        
    Returns:
        Valid action dictionary
        
    Raises:
        ValidationError: If repair exhausted or deterministic error (e.g., unknown_tool)
        
    Example:
        >>> action = validate_or_repair_action(
        ...     llm=my_llm,
        ...     raw_text='{"type": "CALL_TOOL", "name": "searc"}',  # typo
        ...     tool_registry=registry
        ... )
        # Will suggest "search" and repair
    """

    current_text = raw_text

    last_error_type: str = "parse_error"
    last_error: str = "parse_or_schema_error"
    last_error_obj: Exception | None = None

    # Total attempts = 1 initial parse/validate + up to max_attempts repair rounds
    for attempt in range(0, max_attempts + 1):
        try:
            action = extract_first_json_object(current_text)
            _validate_action(action=action, tool_registry=tool_registry)
            
            if attempt > 0:
                logger.info(f"[validate_or_repair] SUCCESS after {attempt} repair(s)")
            
            return action
            
        except ValidationError as e:
            # Unknown tool is deterministic - don't retry
            if e.error_type == "unknown_tool":
                logger.error(f"[validate_or_repair] deterministic error: {e.message}")
                raise
            
            last_error_type = e.error_type
            last_error = str(e)
            last_error_obj = e
            logger.debug(f"[validate_or_repair] attempt {attempt} ValidationError: {e.error_type} - {e.message}")
            
        except JsonParseError as e:
            last_error_type = "parse_error"
            last_error = str(e)
            last_error_obj = e
            logger.debug(f"[validate_or_repair] attempt {attempt} JsonParseError: {e.reason}")
            
        except Exception as e:
            last_error_type = "parse_error"
            last_error = str(e)
            last_error_obj = e
            logger.debug(f"[validate_or_repair] attempt {attempt} Exception: {e}")

        # Max attempts reached?
        if attempt >= max_attempts:
            logger.error(f"[validate_or_repair] exhausted {max_attempts} attempts, final error: {last_error}")
            raise ValidationError(last_error_type, last_error or "repair_failed")

        # Build error-specific repair prompt
        validation_error = last_error_obj if isinstance(last_error_obj, ValidationError) else None
        prompt = build_repair_prompt(
            raw_text=current_text,
            error_summary=last_error,
            validation_error=validation_error
        )
        current_text = llm.complete_text(prompt=prompt)
        logger.debug(f"[validate_or_repair] repair attempt {attempt + 1}, new text length: {len(current_text)}")

    # Should never reach here due to the check above, but for type safety
    raise ValidationError(last_error_type, last_error or "repair_failed")


def _validate_action(*, action: dict[str, Any], tool_registry: Any) -> None:
    validate_action_shape(action)

    typ = str(action.get("type") or "").strip().upper()
    if typ == "CALL_TOOL":
        validate_tool_action(action=action, tool_registry=tool_registry)
