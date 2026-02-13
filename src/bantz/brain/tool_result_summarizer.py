"""Tool result summarization helpers (extracted from orchestrator_loop.py).

Issue #941: Extracted to reduce orchestrator_loop.py from 2434 lines.
Functions: _summarize_tool_result, _prepare_tool_results_for_finalizer,
_build_tool_success_summary, _count_items, _extract_count, _extract_field.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _summarize_tool_result(result: Any, max_items: int = 5, max_chars: int = 500) -> str:
    """Smart summarization of tool results that preserves structure.

    Issue #353: Avoid naive string truncation that breaks JSON and loses
    structured data. Instead, intelligently summarize based on type.
    """
    try:
        if result is None:
            return "None"

        if isinstance(result, list):
            total = len(result)
            if total == 0:
                return "[]"
            preview = result[:max_items]
            preview_json = json.dumps(preview, ensure_ascii=False)
            if len(preview_json) > max_chars:
                preview_json = preview_json[:max_chars] + "..."
            if total > max_items:
                return f"[{total} items, showing first {len(preview)}] {preview_json}"
            return preview_json

        if isinstance(result, dict):
            if not result:
                return "{}"
            keys = list(result.keys())
            result_json = json.dumps(result, ensure_ascii=False)
            if len(result_json) > max_chars:
                result_json = result_json[:max_chars] + "..."
            return f"{{keys: {keys}}} {result_json}"

        if isinstance(result, str):
            if len(result) > max_chars:
                return result[:max_chars] + f"... ({len(result)} chars total)"
            return result

        result_str = str(result)
        if len(result_str) > max_chars:
            return result_str[:max_chars] + "..."
        return result_str

    except Exception as e:
        try:
            s = str(result)
            return s[:max_chars] if len(s) > max_chars else s
        except Exception:
            return f"<error serializing result: {e}>"


def _prepare_tool_results_for_finalizer(
    tool_results: list[dict[str, Any]],
    max_tokens: int = 2000,
) -> tuple[list[dict[str, Any]], bool]:
    """Prepare tool results for finalizer prompt with token budget control.

    Issue #354: Finalizer prompts can overflow context when tool results are large.
    """
    if not tool_results:
        return [], False

    from bantz.llm.token_utils import estimate_tokens_json

    finalizer_results = []
    for r in tool_results:
        finalizer_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": r.get("raw_result"),
            "error": r.get("error"),
        }
        finalizer_results.append(finalizer_r)

    tokens = estimate_tokens_json(finalizer_results)
    if tokens <= max_tokens:
        return finalizer_results, False

    logger.warning(
        "[FINALIZER] Tool results (%d tokens) exceed budget (%d), using summaries",
        tokens, max_tokens,
    )

    finalizer_results = []
    for r in tool_results:
        finalizer_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": r.get("result_summary", ""),
            "error": r.get("error"),
        }
        finalizer_results.append(finalizer_r)

    tokens = estimate_tokens_json(finalizer_results)
    if tokens <= max_tokens:
        return finalizer_results, True

    logger.warning(
        "[FINALIZER] Tool result summaries (%d tokens) still exceed budget, truncating",
        tokens,
    )

    truncated_results = []
    for r in finalizer_results[:3]:
        summary = str(r.get("result", ""))
        if len(summary) > 200:
            summary = summary[:200] + "..."
        truncated_r = {
            "tool": r.get("tool"),
            "success": r.get("success"),
            "result": summary,
            "error": r.get("error"),
        }
        truncated_results.append(truncated_r)

    return truncated_results, True


def _count_items(raw: Any) -> int:
    """Count items from a tool result."""
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        for key in ("events", "items", "messages", "results", "data", "contacts", "slots"):
            val = raw.get(key)
            if isinstance(val, list):
                return len(val)
        for key in ("count", "total", "total_count"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                return int(val)
    return 0


def _extract_count(raw: Any) -> int | None:
    """Extract a count value from a tool result."""
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, dict):
        for key in ("count", "total", "unread_count", "value"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                return int(val)
    return None


def _extract_field(raw: Any, *field_names: str) -> str | None:
    """Extract a string field from a tool result dict."""
    if isinstance(raw, dict):
        for name in field_names:
            val = raw.get(name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _extract_event_time(raw: Any) -> str | None:
    """Extract HH:MM time from a calendar event tool result.

    Looks for 'start' field in various formats:
    - ISO string: "2026-02-13T20:00:00+03:00" → "20:00"
    - Dict: {"dateTime": "2026-02-13T20:00:00+03:00"} → "20:00"
    - Params: {"time": "20:00"} → "20:00"
    """
    if not isinstance(raw, dict):
        return None

    # Direct time field (from params echo)
    t = raw.get("time")
    if isinstance(t, str) and ":" in t and len(t) <= 5:
        return t.strip()

    # Start field (ISO datetime or dict)
    start = raw.get("start")
    if isinstance(start, dict):
        start = start.get("dateTime") or start.get("date")
    if isinstance(start, str) and "T" in start:
        # Extract HH:MM from ISO string
        try:
            time_part = start.split("T")[1]
            return time_part[:5]  # "20:00"
        except (IndexError, TypeError):
            pass

    return None


def _build_tool_success_summary(tool_results: list[dict[str, Any]]) -> str:
    """Build a tool-aware success summary instead of generic 'Tamamlandı efendim'.

    Issue #370: When assistant_reply is empty after successful tool execution,
    generate a meaningful summary from tool results.
    """
    if not tool_results:
        return "Tamamlandı efendim."

    parts: list[str] = []

    for r in tool_results:
        tool_name = str(r.get("tool") or "")
        raw = r.get("raw_result")
        success = r.get("success", False)

        if not success:
            continue

        if tool_name in ("calendar.list_events", "calendar.find_free_slots"):
            count = _count_items(raw)
            if tool_name == "calendar.list_events":
                if count == 0:
                    parts.append("Takvimde etkinlik bulunamadı efendim.")
                elif count == 1:
                    parts.append("1 etkinlik bulundu efendim.")
                else:
                    parts.append(f"{count} etkinlik bulundu efendim.")
            else:
                if count == 0:
                    parts.append("Uygun boş zaman dilimi bulunamadı efendim.")
                else:
                    parts.append(f"{count} uygun zaman dilimi bulundu efendim.")

        elif tool_name == "calendar.create_event":
            title = _extract_field(raw, "title", "summary")
            # Extract time from the tool result for deterministic reply
            start_time = _extract_event_time(raw)
            if title and start_time:
                parts.append(f"'{title}' etkinliği {start_time}'de oluşturuldu efendim.")
            elif title:
                parts.append(f"'{title}' etkinliği oluşturuldu efendim.")
            elif start_time:
                parts.append(f"Etkinlik {start_time}'de oluşturuldu efendim.")
            else:
                parts.append("Etkinlik oluşturuldu efendim.")

        elif tool_name in ("gmail.list_messages", "gmail.smart_search"):
            count = _count_items(raw)
            if count == 0:
                parts.append("Mesaj bulunamadı efendim.")
            elif count == 1:
                parts.append("1 mesaj bulundu efendim.")
            else:
                parts.append(f"{count} mesaj bulundu efendim.")

        elif tool_name == "gmail.unread_count":
            count = _extract_count(raw)
            if count is not None:
                if count == 0:
                    parts.append("Okunmamış mesajınız yok efendim.")
                else:
                    parts.append(f"{count} okunmamış mesajınız var efendim.")
            else:
                parts.append("Okunmamış mesaj sayısı alındı efendim.")

        elif tool_name in ("gmail.send", "gmail.send_to_contact", "gmail.send_draft"):
            parts.append("Mail gönderildi efendim.")

        elif tool_name == "gmail.get_message":
            parts.append("Mesaj getirildi efendim.")

        elif tool_name == "gmail.create_draft":
            parts.append("Taslak oluşturuldu efendim.")

        elif tool_name == "contacts.list":
            count = _count_items(raw)
            parts.append(f"{count} kişi listelendi efendim." if count > 0 else "Kayıtlı kişi bulunamadı efendim.")

        elif tool_name == "contacts.resolve":
            parts.append("Kişi bilgisi çözümlendi efendim.")

        else:
            tool_short = tool_name.split(".")[-1] if "." in tool_name else tool_name
            parts.append(f"{tool_short} tamamlandı efendim.")

    if not parts:
        if len(tool_results) > 1:
            return f"{len(tool_results)} işlem tamamlandı efendim."
        return "Tamamlandı efendim."

    if len(parts) == 1:
        return parts[0]

    return "\n".join(parts)
