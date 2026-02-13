"""Tool parameter builder (extracted from orchestrator_loop.py).

Issue #941: Extracted to reduce orchestrator_loop.py from 2434 lines.
Contains: build_tool_params with field aliasing logic.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from bantz.brain.llm_router import OrchestratorOutput

logger = logging.getLogger(__name__)

# Valid gmail parameter names (Issue #365)
# Issue #1171: Include known aliases so they survive early filtering
# before remap. Aliases are remapped to canonical names below.
GMAIL_VALID_PARAMS = frozenset({
    "to", "name", "subject", "body", "cc", "bcc",
    "label", "category", "query", "search_term", "natural_query",
    "message_id", "max_results", "unread_only", "prefer_unread",
    # Aliases (remapped in build_tool_params)
    "recipient", "email", "address", "emails", "to_address",
    "message", "text", "content", "message_body",
    "title",
})


def build_tool_params(
    tool_name: str,
    slots: dict[str, Any],
    output: Optional[OrchestratorOutput] = None,
    *,
    user_input: Optional[str] = None,
) -> dict[str, Any]:
    """Build tool parameters from orchestrator slots.

    Maps orchestrator slots to tool-specific parameters.
    Handles nested objects like gmail: {to, subject, body}.

    Issue #340: Applies field aliasing for common LLM variations.
    """
    params: dict[str, Any] = {}

    if tool_name.startswith("gmail."):
        # First check slots.gmail (legacy)
        gmail_params = slots.get("gmail")
        if isinstance(gmail_params, dict):
            for key, val in gmail_params.items():
                if key in GMAIL_VALID_PARAMS and val is not None:
                    params[key] = val

        # Issue #903: Check top-level slots for gmail params
        for key, val in slots.items():
            if key in GMAIL_VALID_PARAMS and val is not None and key not in params:
                params[key] = val

        # Then check output.gmail (Issue #317) — highest priority
        if output is not None:
            gmail_obj = getattr(output, "gmail", None) or {}
            if isinstance(gmail_obj, dict):
                for key, val in gmail_obj.items():
                    if key in GMAIL_VALID_PARAMS and val is not None:
                        params[key] = val

        # Issue #340: Apply field aliasing for gmail.send
        if tool_name == "gmail.send":
            for alias in ["recipient", "email", "address", "emails", "to_address"]:
                if alias in params and "to" not in params:
                    params["to"] = params.pop(alias)
                    break

            for alias in ["message", "text", "content", "message_body"]:
                if alias in params and "body" not in params:
                    params["body"] = params.pop(alias)
                    break

            if "title" in params and "subject" not in params:
                params["subject"] = params.pop("title")

            # Issue #1209: Ensure subject always present (required field).
            # LLM often returns subject=null which gets dropped by null-filter.
            if "subject" not in params:
                params["subject"] = ""

        # Minimal aliasing for gmail.send_to_contact
        if tool_name == "gmail.send_to_contact":
            if "name" not in params and "to" in params:
                params["name"] = params.get("to")

        # Issue #1200: Aliasing for gmail.query_from_nl
        # LLM outputs natural_query / search_term / query but the tool
        # function signature requires `text`.
        if tool_name == "gmail.query_from_nl":
            if "text" not in params:
                for alias in ["natural_query", "search_term", "query"]:
                    if alias in params:
                        params["text"] = params.pop(alias)
                        break
            # Fallback: use user_input as text when no alias matched
            if "text" not in params and user_input:
                params["text"] = user_input

        # Aliasing for gmail.smart_search
        # LLM may put the query into search_term/query instead of natural_query,
        # or may not provide it at all.  Fallback to user_input.
        if tool_name == "gmail.smart_search":
            if "natural_query" not in params:
                for alias in ["search_term", "query"]:
                    if alias in params:
                        params["natural_query"] = params.pop(alias)
                        break
            if "natural_query" not in params and user_input:
                params["natural_query"] = user_input

    else:
        params = dict(slots)

    # Issue #1212: Strip fields that don't belong to the tool schema.
    # LLM often sends calendar_intent, duration, etc. to tools that don't
    # accept them, causing safety guard validation failures.
    _CALENDAR_LIST_VALID = frozenset({
        "date", "window_hint", "query", "max_results", "title",
    })
    _CALENDAR_CREATE_VALID = frozenset({
        "title", "date", "time", "duration", "window_hint",
    })
    _CALENDAR_UPDATE_VALID = frozenset({
        "event_id", "title", "date", "time", "duration",
        "location", "description",
    })
    _CALENDAR_DELETE_VALID = frozenset({"event_id"})
    _TOOL_VALID_FIELDS: dict[str, frozenset[str]] = {
        "calendar.list_events": _CALENDAR_LIST_VALID,
        "calendar.find_event": _CALENDAR_LIST_VALID,
        "calendar.find_free_slots": frozenset({
            "duration", "window_hint", "date", "suggestions",
        }),
        "calendar.create_event": _CALENDAR_CREATE_VALID,
        "calendar.update_event": _CALENDAR_UPDATE_VALID,
        "calendar.delete_event": _CALENDAR_DELETE_VALID,
    }
    valid_fields = _TOOL_VALID_FIELDS.get(tool_name)
    if valid_fields is not None:
        params = {k: v for k, v in params.items() if k in valid_fields}

    return params
