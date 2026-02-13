"""Tool plan sanitization and force-injection (extracted from orchestrator_loop.py).

Issue #941: Extracted to reduce orchestrator_loop.py from 2434 lines.
Contains: _TOOL_REMAP, _force_tool_plan, _sanitize_tool_plan.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from bantz.brain.llm_router import OrchestratorOutput

logger = logging.getLogger(__name__)

# Map of known LLM-hallucinated or mismatched tool names to correct tools.
# Key: (tool_name, gmail_intent or "*") → replacement tool name.
TOOL_REMAP: dict[tuple[str, str], str] = {
    ("gmail.list_all", "*"): "gmail.list_messages",
    ("gmail.search_messages", "*"): "gmail.smart_search",
    ("gmail.check_inbox", "*"): "gmail.list_messages",
    ("gmail.get_unread", "*"): "gmail.unread_count",
    ("gmail.inbox", "*"): "gmail.list_messages",
    ("gmail.read_mail", "*"): "gmail.get_message",
    ("calendar.get_events", "*"): "calendar.list_events",
    ("calendar.add_event", "*"): "calendar.create_event",
    ("calendar.remove_event", "*"): "calendar.delete_event",
}


def force_tool_plan(
    output: OrchestratorOutput,
    mandatory_tool_map: dict[tuple[str, str], list[str]],
    gmail_intent_map: dict[str, list[str]],
    *,
    debug: bool = False,
) -> OrchestratorOutput:
    """Force mandatory tools based on route+intent (Issue #282).

    Prevents LLM hallucination by ensuring queries always have tool_plan.
    """
    if output.ask_user:
        return output

    gmail_intent = (getattr(output, "gmail_intent", None) or "").strip().lower()
    if output.confidence < 0.5 and not (
        output.route == "gmail" and gmail_intent == "send"
    ):
        return output

    if output.tool_plan:
        return output

    if output.route in ("smalltalk", "unknown"):
        return output

    if output.route == "gmail" and gmail_intent and gmail_intent != "none":
        mandatory_tools = gmail_intent_map.get(gmail_intent)
        if mandatory_tools:
            if debug:
                logger.debug("[FORCE_TOOL_PLAN] Gmail intent '%s', forcing: %s", gmail_intent, mandatory_tools)
            return replace(output, tool_plan=mandatory_tools)

    if output.calendar_intent in ("none", ""):
        if output.route == "gmail":
            mandatory_tools = ["gmail.list_messages"]
            if debug:
                logger.debug("[FORCE_TOOL_PLAN] Gmail fallback, forcing: %s", mandatory_tools)
            return replace(output, tool_plan=mandatory_tools)
        return output

    if output.route == "gmail":
        mandatory_tools = gmail_intent_map.get(gmail_intent)
        if not mandatory_tools:
            mandatory_tools = ["gmail.list_messages"]
    else:
        key = (output.route, output.calendar_intent)
        mandatory_tools = mandatory_tool_map.get(key)

    if not mandatory_tools:
        if output.route == "system":
            mandatory_tools = ["time.now"]
        else:
            return output

    if debug:
        logger.debug("[FORCE_TOOL_PLAN] Empty tool_plan, forcing: %s", mandatory_tools)

    return replace(output, tool_plan=mandatory_tools)


def sanitize_tool_plan(
    output: OrchestratorOutput,
    tool_remap: dict[tuple[str, str], str] | None = None,
) -> OrchestratorOutput:
    """Remap hallucinated or intent-mismatched tool names (Issue #870)."""
    if not output.tool_plan:
        return output

    remap = tool_remap if tool_remap is not None else TOOL_REMAP

    gmail_intent = (getattr(output, "gmail_intent", None) or "").strip().lower()
    calendar_intent = (output.calendar_intent or "").strip().lower()
    intent_key = gmail_intent or calendar_intent or "*"

    changed = False
    new_plan: list[str] = []
    for tool_name in output.tool_plan:
        replacement = remap.get((tool_name, intent_key))
        if replacement is None:
            replacement = remap.get((tool_name, "*"))

        if replacement and replacement != tool_name:
            logger.info(
                "[SANITIZE] Remapping tool '%s' → '%s' (intent=%s)",
                tool_name, replacement, intent_key,
            )
            new_plan.append(replacement)
            changed = True
        else:
            new_plan.append(tool_name)

    if not changed:
        return output

    return replace(output, tool_plan=new_plan)
