from __future__ import annotations

import logging
from dataclasses import dataclass
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
    ok: bool
    value: dict[str, Any] | None
    attempts: int
    error: str | None = None


def build_repair_prompt(*, raw_text: str, error_summary: str) -> str:
    return (
        "Aşağıdaki metinden sadece GEÇERLİ JSON OBJESİ döndür.\n"
        "- Markdown, backtick, açıklama, yorum, extra anahtar yazma.\n"
        "- Çıktın yalnızca tek bir JSON object olsun.\n\n"
        "ZORUNLU ŞEKİL:\n"
        "- JSON object içinde mutlaka 'type' alanı olmalı.\n"
        "- type ∈ {SAY, CALL_TOOL, ASK_USER, FAIL}\n"
        "- SAY => {\"type\":\"SAY\",\"text\":\"...\"}\n"
        "- ASK_USER => {\"type\":\"ASK_USER\",\"question\":\"...\"}\n"
        "- FAIL => {\"type\":\"FAIL\",\"error\":\"...\"}\n"
        "- CALL_TOOL => {\"type\":\"CALL_TOOL\",\"name\":\"tool_name\",\"params\":{}}\n\n"
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
    """Try to repair arbitrary text into a valid JSON object using an LLM."""

    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        prompt = build_repair_prompt(
            raw_text=raw_text,
            error_summary=last_error or "parse_or_schema_error",
        )
        repaired = llm.complete_text(prompt=prompt)

        try:
            obj = extract_first_json_object(repaired)
            return RepairResult(ok=True, value=obj, attempts=attempt)
        except Exception as e:
            last_error = str(e)
            logger.info("[json_repair] attempt=%s failed: %s", attempt, last_error)

    return RepairResult(ok=False, value=None, attempts=max_attempts, error=last_error)


def validate_or_repair_action(
    *,
    llm: RepairLLM,
    raw_text: str,
    tool_registry: Any,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Parse + validate a tool action; if it fails, repair up to max_attempts.

    Returns a dict action if successful.
    Raises ValidationError on deterministic failure.
    """

    current_text = raw_text

    last_error_type: str = "parse_error"
    last_error: str = "parse_or_schema_error"

    # Total attempts = 1 initial parse/validate + up to max_attempts repair rounds.
    for attempt in range(0, max_attempts + 1):
        try:
            action = extract_first_json_object(current_text)
            _validate_action(action=action, tool_registry=tool_registry)
            return action
        except ValidationError as e:
            if e.error_type == "unknown_tool":
                raise
            last_error_type = e.error_type
            last_error = str(e)
        except JsonParseError as e:
            last_error_type = "parse_error"
            last_error = str(e)
        except Exception as e:
            last_error_type = "parse_error"
            last_error = str(e)

        if attempt >= max_attempts:
            raise ValidationError(last_error_type, last_error or "repair_failed")

        prompt = build_repair_prompt(raw_text=current_text, error_summary=last_error)
        current_text = llm.complete_text(prompt=prompt)

    raise ValidationError(last_error_type, last_error or "repair_failed")


def _validate_action(*, action: dict[str, Any], tool_registry: Any) -> None:
    validate_action_shape(action)

    typ = str(action.get("type") or "").strip().upper()
    if typ == "CALL_TOOL":
        validate_tool_action(action=action, tool_registry=tool_registry)
