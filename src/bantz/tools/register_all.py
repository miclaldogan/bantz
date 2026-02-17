"""Comprehensive tool registration — bridges ALL runtime handlers to ToolRegistry.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
69 planner tools of which 52 previously had no wired runtime handler.
This module registers every handler category in one place.

Usage
─────
    from bantz.tools.register_all import register_all_tools
    register_all_tools(registry)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bantz.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


def register_all_tools(registry: "ToolRegistry") -> int:
    """Register every runtime tool handler with *registry*.

    Returns the number of tools successfully registered.
    """
    count = 0
    count += _register_web(registry)
    count += _register_browser(registry)
    count += _register_pc(registry)
    count += _register_file(registry)
    count += _register_terminal(registry)
    count += _register_code(registry)
    count += _register_gmail(registry)
    count += _register_gmail_extended(registry)
    count += _register_contacts(registry)
    count += _register_coding_skill(registry)
    count += _register_calendar(registry)
    count += _register_system(registry)
    count += _register_time(registry)
    count += _register_google_connectors(registry)
    count += _register_proactive(registry)
    count += _register_messaging(registry)
    count += _register_sandbox_agents(registry)
    count += _register_music(registry)
    count += _register_health(registry)
    count += _register_sync_search(registry)
    count += _register_news(registry)
    logger.info(f"[ToolGap] Total tools registered: {count}")
    return count


# ── helpers ──────────────────────────────────────────────────────────

# Issue #1079: Canonical risk mapping — single vocabulary for both
# register_all and metadata.py ToolRisk.
_RISK_NORMALIZE: dict[str, str] = {
    "low": "LOW",
    "safe": "LOW",
    "medium": "MED",
    "moderate": "MED",
    "med": "MED",
    "high": "HIGH",
    "destructive": "HIGH",
}


def _reg(registry: "ToolRegistry", name: str, desc: str, params: dict,
         fn, *, risk: str = "low", confirm: bool = False) -> bool:
    """Register a single tool, returning True on success."""
    from bantz.agent.tools import Tool
    canonical_risk = _RISK_NORMALIZE.get(risk.lower().strip(), "LOW")
    try:
        registry.register(Tool(
            name=name,
            description=desc,
            parameters=params,
            function=fn,
            risk_level=canonical_risk,
            requires_confirmation=confirm,
        ))
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"[ToolGap] Failed to register {name}: {e}")
        return False


def _obj(*props: tuple[str, str, str], required: list[str] | None = None) -> dict:
    """Shorthand for JSON-Schema object."""
    properties = {}
    for pname, ptype, pdesc in props:
        properties[pname] = {"type": ptype, "description": pdesc}
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# ── Web ──────────────────────────────────────────────────────────────

def _register_web(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.registry import register_web_tools
        register_web_tools(registry)
        return 2
    except Exception as e:
        logger.warning(f"[ToolGap] web tools: {e}")
        return 0


# ── Browser (11) ─────────────────────────────────────────────────────

def _register_browser(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.browser_tools import (browser_back_tool,
                                               browser_click_tool,
                                               browser_detail_tool,
                                               browser_info_tool,
                                               browser_open_tool,
                                               browser_scan_tool,
                                               browser_scroll_down_tool,
                                               browser_scroll_up_tool,
                                               browser_search_tool,
                                               browser_type_tool,
                                               browser_wait_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] browser import: {e}")
        return 0

    n = 0
    n += _reg(registry, "browser.open", "Open a URL in the browser.",
              _obj(("url", "string", "URL to open"), required=["url"]),
              browser_open_tool)
    n += _reg(registry, "browser.scan", "Scan visible page elements for interaction.",
              _obj(("selector", "string", "CSS selector filter (optional)")),
              browser_scan_tool)
    n += _reg(registry, "browser.click", "Click an element on the page.",
              _obj(("index", "integer", "Element index from browser.scan"),
                   ("text", "string", "Text content to match")),
              browser_click_tool, risk="medium", confirm=True)
    n += _reg(registry, "browser.type", "Type text into an input field.",
              _obj(("selector", "string", "CSS selector"), ("text", "string", "Text to type"),
                   required=["selector", "text"]),
              browser_type_tool, risk="medium", confirm=True)
    # Issue #1063: Dispatch scroll direction based on parameter
    def _browser_scroll_dispatch(*, direction: str = "down", **kw: Any) -> Any:
        if direction.lower().strip() in ("up", "yukarı", "yukari"):
            return browser_scroll_up_tool(**kw)
        return browser_scroll_down_tool(**kw)

    n += _reg(registry, "browser.scroll", "Scroll the page up or down.",
              _obj(("direction", "string", "up or down")),
              _browser_scroll_dispatch)
    n += _reg(registry, "browser.search", "Search text on the current page.",
              _obj(("query", "string", "Text to search"), required=["query"]),
              browser_search_tool)
    n += _reg(registry, "browser.back", "Navigate back in the browser.", _obj(), browser_back_tool)
    n += _reg(registry, "browser.info", "Get current page info (title, URL, meta).",
              _obj(), browser_info_tool)
    n += _reg(registry, "browser.detail", "Get detailed content of a page element.",
              _obj(("index", "integer", "Element index from browser.scan (default 0)")),
              browser_detail_tool)
    n += _reg(registry, "browser.wait", "Wait for a specified duration.",
              _obj(("seconds", "integer", "Wait time in seconds (1-30, default 2)")),
              browser_wait_tool)
    n += _reg(registry, "browser.extract", "Extract structured data from page.",
              _obj(("index", "integer", "Element index from browser.scan (default 0)")),
              browser_detail_tool)  # reuse detail handler
    return n


# ── PC Control (5 + clipboard) ──────────────────────────────────────

def _register_pc(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.pc_tools import (clipboard_get_tool,
                                          clipboard_set_tool, pc_hotkey_tool,
                                          pc_mouse_click_tool,
                                          pc_mouse_move_tool,
                                          pc_mouse_scroll_tool, pc_type_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] pc import: {e}")
        return 0

    n = 0
    n += _reg(registry, "pc.hotkey", "Press a keyboard hotkey combination.",
              _obj(("combo", "string", "Key combo e.g. ctrl+c"), required=["combo"]),
              pc_hotkey_tool, risk="medium", confirm=True)
    n += _reg(registry, "pc.mouse_move", "Move mouse to coordinates.",
              _obj(("x", "integer", "X coordinate"), ("y", "integer", "Y coordinate"),
                   required=["x", "y"]),
              pc_mouse_move_tool, risk="medium", confirm=True)
    n += _reg(registry, "pc.mouse_click", "Click mouse at position.",
              _obj(("x", "integer", "X (optional)"), ("y", "integer", "Y (optional)"),
                   ("button", "string", "left/right/middle")),
              pc_mouse_click_tool, risk="medium", confirm=True)
    n += _reg(registry, "pc.mouse_scroll", "Scroll mouse wheel.",
              _obj(("direction", "string", "up or down"), ("amount", "integer", "Scroll amount")),
              pc_mouse_scroll_tool, risk="low")
    n += _reg(registry, "pc.type", "Type text on keyboard.",
              _obj(("text", "string", "Text to type"), required=["text"]),
              pc_type_tool, risk="medium", confirm=True)  # xdotool type
    n += _reg(registry, "clipboard.set", "Set clipboard content.",
              _obj(("text", "string", "Text to copy"), required=["text"]),
              clipboard_set_tool, risk="low")
    n += _reg(registry, "clipboard.get", "Get clipboard content.", _obj(), clipboard_get_tool)
    return n


# ── File System (6) ─────────────────────────────────────────────────

def _register_file(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.file_tools import (file_create_tool, file_edit_tool,
                                            file_read_tool, file_search_tool,
                                            file_undo_tool, file_write_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] file import: {e}")
        return 0

    n = 0
    n += _reg(registry, "file.read", "Read file contents.",
              _obj(("path", "string", "File path"),
                   ("start_line", "integer", "First line to read (1-based)"),
                   ("end_line", "integer", "Last line to read (1-based)"),
                   required=["path"]),
              file_read_tool)
    n += _reg(registry, "file.write", "Write content to a file.",
              _obj(("path", "string", "File path"), ("content", "string", "File content"),
                   required=["path", "content"]),
              file_write_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.edit", "Edit a specific part of a file.",
              _obj(("path", "string", "File path"), ("old_string", "string", "Text to replace"),
                   ("new_string", "string", "Replacement text"), required=["path", "old_string", "new_string"]),
              file_edit_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.create", "Create a new file.",
              _obj(("path", "string", "File path"), ("content", "string", "Initial content"),
                   required=["path"]),
              file_create_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.undo", "Undo last file edit (restore from backup).",
              _obj(("path", "string", "File path"), required=["path"]),
              file_undo_tool, risk="medium")
    n += _reg(registry, "file.search", "Search for files or text patterns.",
              _obj(("pattern", "string", "File name glob pattern"), ("content", "string", "Text to search inside files"),
                   ("path", "string", "Base directory"),
                   required=["pattern"]),
              file_search_tool)
    return n


# ── Terminal (4) ─────────────────────────────────────────────────────

def _register_terminal(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.terminal_tools import (terminal_background_kill_tool,
                                                terminal_background_list_tool,
                                                terminal_background_tool,
                                                terminal_run_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] terminal import: {e}")
        return 0

    n = 0
    n += _reg(registry, "terminal.run", "Run a shell command (policy enforced).",
              _obj(("command", "string", "Command to execute"),
                   ("timeout", "integer", "Timeout in seconds"),
                   required=["command"]),
              terminal_run_tool, risk="high", confirm=True)
    n += _reg(registry, "terminal.background", "Start a background process.",
              _obj(("command", "string", "Command to run"), required=["command"]),
              terminal_background_tool, risk="high", confirm=True)
    n += _reg(registry, "terminal.list", "List running background processes.",
              _obj(), terminal_background_list_tool)
    n += _reg(registry, "terminal.kill", "Kill a background process.",
              _obj(("id", "integer", "Background process ID to kill"), required=["id"]),
              terminal_background_kill_tool, risk="medium", confirm=True)
    return n


# ── Code (6) ─────────────────────────────────────────────────────────

def _register_code(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.code_tools import (code_format_tool,
                                            code_replace_function_tool,
                                            project_info_tool,
                                            project_search_symbol_tool,
                                            project_symbols_tool,
                                            project_tree_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] code import: {e}")
        return 0

    n = 0
    n += _reg(registry, "code.format", "Format source code file.",
              _obj(("path", "string", "File to format"), required=["path"]),
              code_format_tool)
    n += _reg(registry, "code.replace_function", "Replace a function body in a file.",
              _obj(("path", "string", "File path"), ("name", "string", "Function name"),
                   ("new_body", "string", "New function body"),
                   required=["path", "name", "new_body"]),
              code_replace_function_tool, risk="high", confirm=True)
    n += _reg(registry, "project.info", "Get project information (language, deps, structure).",
              _obj(("path", "string", "Project root (optional)")),
              project_info_tool)
    n += _reg(registry, "project.tree", "Show project directory tree.",
              _obj(("path", "string", "Root path"), ("depth", "integer", "Max depth")),
              project_tree_tool)
    n += _reg(registry, "project.symbols", "List symbols (functions, classes) in a file.",
              _obj(("path", "string", "File to analyze"), required=["path"]),
              project_symbols_tool)
    n += _reg(registry, "project.search_symbol", "Search for a symbol across the project.",
              _obj(("name", "string", "Symbol or pattern to search"),
                   ("path", "string", "Base directory"),
                   required=["name"]),
              project_search_symbol_tool)
    return n


# ── Gmail base (6) ──────────────────────────────────────────────────

def _register_gmail(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.gmail_tools import (gmail_get_message_tool,
                                             gmail_list_categories_tool,
                                             gmail_list_messages_tool,
                                             gmail_send_tool,
                                             gmail_smart_search_tool,
                                             gmail_unread_count_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] gmail import: {e}")
        return 0

    n = 0
    n += _reg(registry, "gmail.unread_count", "Get unread email count.",
              _obj(), gmail_unread_count_tool)
    n += _reg(registry, "gmail.list_messages", "List recent emails.",
              _obj(("max_results", "integer", "Max results (default 10)"),
                   ("label", "string", "Label filter"),
                   ("query", "string", "Search query")),
              gmail_list_messages_tool)
    n += _reg(registry, "gmail.get_message", "Get full email content.",
              _obj(("message_id", "string", "Gmail message ID"), required=["message_id"]),
              gmail_get_message_tool)
    n += _reg(registry, "gmail.send", "Send an email.",
              _obj(("to", "string", "Recipient email"),
                   ("subject", "string", "Email subject"),
                   ("body", "string", "Email body"),
                   required=["to", "subject", "body"]),
              gmail_send_tool, risk="high", confirm=True)
    n += _reg(registry, "gmail.smart_search", "Smart Gmail search.",
              _obj(("natural_query", "string", "Search query in natural language"), required=["natural_query"]),
              gmail_smart_search_tool)
    n += _reg(registry, "gmail.list_categories", "List Gmail categories with counts.",
              _obj(), gmail_list_categories_tool)
    return n


# ── Gmail extended (14) ─────────────────────────────────────────────

def _register_gmail_extended(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.gmail_extended_tools import (
            gmail_add_label_tool, gmail_archive_tool, gmail_batch_modify_tool,
            gmail_create_draft_tool, gmail_delete_draft_tool,
            gmail_download_attachment_tool, gmail_generate_reply_tool,
            gmail_list_drafts_tool, gmail_list_labels_tool,
            gmail_mark_read_tool, gmail_mark_unread_tool,
            gmail_remove_label_tool, gmail_send_draft_tool,
            gmail_update_draft_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] gmail_extended import: {e}")
        return 0

    n = 0
    n += _reg(registry, "gmail.list_labels", "List Gmail labels.", _obj(), gmail_list_labels_tool)
    n += _reg(registry, "gmail.add_label", "Add label to message.",
              _obj(("message_id", "string", "Message ID"), ("label", "string", "Label name"),
                   required=["message_id", "label"]),
              gmail_add_label_tool)
    n += _reg(registry, "gmail.remove_label", "Remove label from message.",
              _obj(("message_id", "string", "Message ID"), ("label", "string", "Label name"),
                   required=["message_id", "label"]),
              gmail_remove_label_tool)
    n += _reg(registry, "gmail.mark_read", "Mark email as read.",
              _obj(("message_id", "string", "Message ID"), required=["message_id"]),
              gmail_mark_read_tool)
    n += _reg(registry, "gmail.mark_unread", "Mark email as unread.",
              _obj(("message_id", "string", "Message ID"), required=["message_id"]),
              gmail_mark_unread_tool)
    n += _reg(registry, "gmail.archive", "Archive email (remove from inbox).",
              _obj(("message_id", "string", "Message ID"), required=["message_id"]),
              gmail_archive_tool, risk="medium", confirm=True)
    n += _reg(registry, "gmail.batch_modify", "Batch add/remove labels.",
              _obj(("message_ids", "array", "List of message IDs"),
                   ("add_labels", "array", "Labels to add"),
                   ("remove_labels", "array", "Labels to remove"),
                   required=["message_ids"]),
              gmail_batch_modify_tool, risk="medium", confirm=True)
    n += _reg(registry, "gmail.download_attachment", "Download attachment.",
              _obj(("message_id", "string", "Message ID"),
                   ("attachment_id", "string", "Attachment ID"),
                   ("save_path", "string", "Path to save file"),
                   required=["message_id", "attachment_id", "save_path"]),
              gmail_download_attachment_tool, risk="medium", confirm=True)
    n += _reg(registry, "gmail.create_draft", "Create email draft.",
              _obj(("to", "string", "Recipient"), ("subject", "string", "Subject"),
                   ("body", "string", "Body"), required=["to", "subject", "body"]),
              gmail_create_draft_tool)
    n += _reg(registry, "gmail.list_drafts", "List email drafts.",
              _obj(("max_results", "integer", "Max results")), gmail_list_drafts_tool)
    n += _reg(registry, "gmail.update_draft", "Update an existing draft.",
              _obj(("draft_id", "string", "Draft ID"),
                   ("updates", "object", "Fields to update (to, subject, body)"),
                   required=["draft_id"]),
              gmail_update_draft_tool)
    n += _reg(registry, "gmail.send_draft", "Send a draft email.",
              _obj(("draft_id", "string", "Draft ID"), required=["draft_id"]),
              gmail_send_draft_tool, risk="high", confirm=True)
    n += _reg(registry, "gmail.delete_draft", "Delete a draft.",
              _obj(("draft_id", "string", "Draft ID"), required=["draft_id"]),
              gmail_delete_draft_tool, risk="medium", confirm=True)
    n += _reg(registry, "gmail.generate_reply", "Generate a reply to an email.",
              _obj(("message_id", "string", "Message ID"),
                   ("user_intent", "string", "Desired reply intent"),
                   required=["message_id", "user_intent"]),
              gmail_generate_reply_tool)
    return n


# ── Contacts (4) ────────────────────────────────────────────────────

def _register_contacts(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.contacts_tools import (contacts_add_tool,
                                                contacts_get_tool,
                                                contacts_list_tool,
                                                contacts_search_tool)
    except ImportError as e:
        logger.warning(f"[ToolGap] contacts import: {e}")
        return 0

    n = 0
    n += _reg(registry, "contacts.search", "Search contacts by name or email.",
              _obj(("query", "string", "Search query"), required=["query"]),
              contacts_search_tool)
    n += _reg(registry, "contacts.get", "Resolve a name to email address.",
              _obj(("name", "string", "Contact name"), required=["name"]),
              contacts_get_tool)
    n += _reg(registry, "contacts.list", "List all contacts.",
              _obj(("limit", "integer", "Max results")),
              contacts_list_tool)
    n += _reg(registry, "contacts.add", "Add or update a contact.",
              _obj(("name", "string", "Contact name"), ("email", "string", "Email address"),
                   required=["name", "email"]),
              contacts_add_tool)
    return n


# ── Coding Skill (3) ────────────────────────────────────────────────

def _register_coding_skill(registry: "ToolRegistry") -> int:
    try:
        from bantz.skills.coding_skill import register_coding_skill_tools
        register_coding_skill_tools(registry)
        return 3
    except ImportError as e:
        logger.warning(f"[ToolGap] coding_skill import: {e}")
        return 0


# ── Calendar ─────────────────────────────────────────────────────────

def _register_calendar(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.calendar_tools import (calendar_create_event_tool,
                                                calendar_delete_event_tool,
                                                calendar_list_events_tool,
                                                calendar_update_event_tool)
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "calendar.list_events", "List upcoming calendar events.",
              _obj(("date", "string", "Date to query (YYYY-MM-DD or natural language)"),
                   ("window_hint", "string", "Time window hint (e.g. morning, afternoon)"),
                   ("query", "string", "Search query to filter events"),
                   ("max_results", "integer", "Max events (default 10)")),
              calendar_list_events_tool)
    n += _reg(registry, "calendar.create_event", "Create a calendar event.",
              _obj(("title", "string", "Event title"),
                   ("date", "string", "Event date (YYYY-MM-DD or natural language)"),
                   ("time", "string", "Event time (HH:MM)"),
                   ("duration", "integer", "Duration in minutes (default 60)"),
                   ("window_hint", "string", "Time window hint (e.g. morning, afternoon)"),
                   required=["title"]),
              calendar_create_event_tool, risk="medium", confirm=True)
    n += _reg(registry, "calendar.update_event", "Update a calendar event.",
              _obj(("event_id", "string", "Event ID"),
                   ("title", "string", "New event title"),
                   ("date", "string", "New date (YYYY-MM-DD)"),
                   ("time", "string", "New time (HH:MM)"),
                   ("duration", "integer", "New duration in minutes"),
                   ("location", "string", "New location"),
                   ("description", "string", "New description"),
                   required=["event_id"]),
              calendar_update_event_tool, risk="medium", confirm=True)
    n += _reg(registry, "calendar.delete_event", "Delete a calendar event.",
              _obj(("event_id", "string", "Event ID"), required=["event_id"]),
              calendar_delete_event_tool, risk="high", confirm=True)
    return n


# ── System (3) ──────────────────────────────────────────────────────

def _register_system(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.system_tools import (system_notify_tool,
                                              system_screenshot_tool,
                                              system_status,
                                              system_volume_tool)
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "system.status", "Get system information (CPU, RAM, disk).",
              _obj(), system_status)
    n += _reg(registry, "system.notify", "Show desktop notification.",
              _obj(("message", "string", "Notification message"), required=["message"]),
              system_notify_tool)
    n += _reg(registry, "system.screenshot", "Take a screenshot.",
              _obj(("region", "string", "Screen region (optional)")),
              system_screenshot_tool, risk="low")
    n += _reg(registry, "system.volume",
              "Get or set system audio volume. action: get/set/up/down/mute/unmute.",
              _obj(("level", "integer", "Volume level 0-100"),
                   ("action", "string", "get|set|up|down|mute|unmute")),
              system_volume_tool, risk="low")
    return n


# ── Time (2) ────────────────────────────────────────────────────────

def _register_time(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.time_tools import time_now_tool
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "time.now", "Get current date and time.",
              _obj(("timezone", "string", "Timezone (default: local)")),
              time_now_tool)
    return n


# ── Google Suite Connectors (Issue #1292) ────────────────────────

def _register_google_connectors(registry: "ToolRegistry") -> int:
    """Register tools from all Google Suite connectors.

    Uses the unified ``GoogleAuthManager`` to provide Contacts, Tasks,
    Keep, and Classroom tools.  Fails gracefully if the auth manager
    or dependencies are not available.
    """
    try:
        from bantz.connectors.google.auth_manager import (get_auth_manager,
                                                          setup_auth_manager)
    except ImportError as e:
        logger.warning("[ToolGap] google connectors import: %s", e)
        return 0

    # Get or create the auth manager (non-interactive for tool registration)
    auth = get_auth_manager()
    if auth is None:
        try:
            auth = setup_auth_manager(interactive=False)
        except Exception as e:
            logger.warning("[ToolGap] google auth manager setup: %s", e)
            return 0

    n = 0

    # ── Contacts ────────────────────────────────────────────────
    try:
        from bantz.connectors.google.contacts import ContactsConnector

        connector = ContactsConnector(auth)
        for tool_schema in connector.get_tools():
            n += _reg(
                registry,
                tool_schema.name,
                tool_schema.description,
                tool_schema.parameters,
                tool_schema.handler,
                risk=tool_schema.risk,
                confirm=tool_schema.confirm,
            )
    except Exception as e:
        logger.warning("[ToolGap] google contacts connector: %s", e)

    # ── Tasks ───────────────────────────────────────────────────
    try:
        from bantz.connectors.google.tasks import TasksConnector

        connector = TasksConnector(auth)
        for tool_schema in connector.get_tools():
            n += _reg(
                registry,
                tool_schema.name,
                tool_schema.description,
                tool_schema.parameters,
                tool_schema.handler,
                risk=tool_schema.risk,
                confirm=tool_schema.confirm,
            )
    except Exception as e:
        logger.warning("[ToolGap] google tasks connector: %s", e)

    # ── Keep ────────────────────────────────────────────────────
    try:
        from bantz.connectors.google.keep import KeepConnector

        connector = KeepConnector(auth)
        for tool_schema in connector.get_tools():
            n += _reg(
                registry,
                tool_schema.name,
                tool_schema.description,
                tool_schema.parameters,
                tool_schema.handler,
                risk=tool_schema.risk,
                confirm=tool_schema.confirm,
            )
    except Exception as e:
        logger.warning("[ToolGap] google keep connector: %s", e)

    # ── Classroom ───────────────────────────────────────────────
    try:
        from bantz.connectors.google.classroom import ClassroomConnector

        connector = ClassroomConnector(auth)
        for tool_schema in connector.get_tools():
            n += _reg(
                registry,
                tool_schema.name,
                tool_schema.description,
                tool_schema.parameters,
                tool_schema.handler,
                risk=tool_schema.risk,
                confirm=tool_schema.confirm,
            )
    except Exception as e:
        logger.warning("[ToolGap] google classroom connector: %s", e)

    return n


# ── Proactive Secretary (#1293) ──────────────────────────────────────


def _register_proactive(registry: "ToolRegistry") -> int:
    """Register proactive secretary tools: on-demand brief + status."""
    n = 0

    # ── daily_brief tool ────────────────────────────────────────
    def _handle_daily_brief(**kwargs: Any) -> dict:
        """Generate and return the daily brief on demand."""
        import asyncio

        from bantz.proactive.engine import get_proactive_engine

        engine = get_proactive_engine()
        if engine is None or engine.brief_generator is None:
            return {"ok": False, "error": "Proactive Secretary henüz başlatılmadı."}

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    brief = pool.submit(
                        asyncio.run, engine.brief_generator.generate()
                    ).result(timeout=30)
            else:
                brief = asyncio.run(engine.brief_generator.generate())
            return {"ok": True, "brief": brief}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    n += _reg(
        registry,
        "proactive.daily_brief",
        (
            "Günlük brifing oluştur (sabah brief'i). "
            "Takvim, mail, hava durumu, görevler ve öneriler içerir. "
            "Kullanıcı 'brief'imi göster' dediğinde çağrılır."
        ),
        _obj(required=[]),
        _handle_daily_brief,
        risk="low",
    )

    # ── proactive.status tool ───────────────────────────────────
    def _handle_proactive_status(**kwargs: Any) -> dict:
        """Return the proactive engine status."""
        from bantz.proactive.engine import get_proactive_engine

        engine = get_proactive_engine()
        if engine is None:
            return {"ok": False, "error": "Proactive Engine başlatılmadı."}
        return {"ok": True, **engine.get_status()}

    n += _reg(
        registry,
        "proactive.status",
        "Proaktif motorun durumunu gösterir: çalışan kontroller, bildirimler, politika.",
        _obj(required=[]),
        _handle_proactive_status,
        risk="low",
    )

    return n


# ── Messaging Pipeline (#1294) ──────────────────────────────────────


def _register_messaging(registry: "ToolRegistry") -> int:
    """Register kontrollü mesajlaşma tools: read, draft, send, thread."""
    n = 0

    # ── messaging.read_inbox ────────────────────────────────────
    def _handle_read_inbox(
        *,
        channel: str = "email",
        query: str = "",
        max_results: int = 10,
        unread_only: bool = False,
        **_: Any,
    ) -> dict:
        """Read messages from a channel inbox."""
        import asyncio

        from bantz.messaging.gmail_channel import GmailChannel
        from bantz.messaging.pipeline import MessagingPipeline

        pipeline = MessagingPipeline()
        pipeline.register_channel(GmailChannel())

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    msgs = pool.submit(
                        asyncio.run,
                        pipeline.read_inbox(
                            channel,
                            filter_query=query or None,
                            max_results=int(max_results),
                            unread_only=bool(unread_only),
                        ),
                    ).result(timeout=30)
            else:
                msgs = asyncio.run(
                    pipeline.read_inbox(
                        channel,
                        filter_query=query or None,
                        max_results=int(max_results),
                        unread_only=bool(unread_only),
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "messages": [
                {
                    "id": m.id,
                    "from": m.sender,
                    "subject": m.subject,
                    "preview": m.preview,
                    "date": m.timestamp.isoformat(),
                    "unread": not m.is_read,
                    "channel": m.channel.value,
                }
                for m in msgs
            ],
            "count": len(msgs),
        }

    n += _reg(
        registry,
        "messaging.read_inbox",
        (
            "Mesajları oku — belirtilen kanaldan (email, telegram, slack) veya "
            "tüm kanallardan gelen mesajları listele. "
            "Filtre, okunmamış ve kanal parametreleri desteklenir."
        ),
        _obj(
            ("channel", "string", "Kanal: email, telegram, slack, all (varsayılan: email)"),
            ("query", "string", "Arama filtresi"),
            ("max_results", "integer", "Maks sonuç sayısı (varsayılan: 10)"),
            ("unread_only", "boolean", "Sadece okunmamış (varsayılan: false)"),
        ),
        _handle_read_inbox,
        risk="low",
    )

    # ── messaging.draft_reply ───────────────────────────────────
    def _handle_draft_reply(
        *,
        to: str = "",
        subject: str = "",
        body_context: str = "",
        instruction: str = "Kısa ve profesyonel yanıt yaz",
        channel: str = "email",
        **_: Any,
    ) -> dict:
        """Generate a draft reply for a message."""
        from bantz.messaging.models import ChannelType, Draft

        draft = Draft(
            channel=(
                ChannelType(channel)
                if channel in [e.value for e in ChannelType]
                else ChannelType.EMAIL
            ),
            to=to,
            subject=(
                f"Re: {subject}"
                if subject and not subject.startswith("Re:")
                else subject
            ),
            body=(
                f"Merhaba,\n\n"
                f"'{subject}' konulu mesajınız alındı. {body_context}\n\n"
                f"İyi günler."
            ),
            instruction=instruction,
        )
        return {
            "ok": True,
            "draft": draft.as_display(),
            "display_hint": (
                f"📝 Taslak hazır:\n"
                f"  Kime: {draft.to}\n"
                f"  Konu: {draft.subject}\n"
                f"  İçerik: {draft.body[:200]}"
            ),
        }

    n += _reg(
        registry,
        "messaging.draft_reply",
        (
            "Mesaj taslağı oluştur — belirtilen kişiye yanıt taslağı hazırla. "
            "LLM talimatına göre ton ve stil ayarlanır."
        ),
        _obj(
            ("to", "string", "Alıcı adresi"),
            ("subject", "string", "Konu"),
            ("body_context", "string", "Yanıt bağlamı"),
            ("instruction", "string", "LLM talimatı (ton, stil)"),
            ("channel", "string", "Kanal (varsayılan: email)"),
            required=["to", "subject"],
        ),
        _handle_draft_reply,
        risk="medium",
    )

    # ── messaging.send ──────────────────────────────────────────
    def _handle_messaging_send(
        *,
        to: str,
        subject: str,
        body: str,
        channel: str = "email",
        cc: str = "",
        bcc: str = "",
        **_: Any,
    ) -> dict:
        """Send a message through the messaging pipeline."""
        import asyncio

        from bantz.messaging.gmail_channel import GmailChannel
        from bantz.messaging.models import ChannelType, Draft
        from bantz.messaging.pipeline import MessagingPipeline

        pipeline = MessagingPipeline()
        pipeline.register_channel(GmailChannel())

        draft = Draft(
            channel=(
                ChannelType(channel)
                if channel in [e.value for e in ChannelType]
                else ChannelType.EMAIL
            ),
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
        )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        pipeline.send_single(draft),
                    ).result(timeout=30)
            else:
                result = asyncio.run(pipeline.send_single(draft))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.ok,
            "message_id": result.message_id,
            "error": result.error,
            "channel": result.channel.value,
            "display_hint": (
                f"✉️ Mesaj gönderildi: {to} — {subject}"
                if result.ok
                else f"❌ Gönderim başarısız: {result.error}"
            ),
        }

    n += _reg(
        registry,
        "messaging.send",
        (
            "Mesaj gönder — belirtilen kanaldan (email, telegram, slack) "
            "mesaj gönder. Policy engine onayı gerektirir."
        ),
        _obj(
            ("to", "string", "Alıcı"),
            ("subject", "string", "Konu"),
            ("body", "string", "Mesaj içeriği"),
            ("channel", "string", "Kanal (varsayılan: email)"),
            ("cc", "string", "CC"),
            ("bcc", "string", "BCC"),
            required=["to", "subject", "body"],
        ),
        _handle_messaging_send,
        risk="high",
        confirm=True,
    )

    # ── messaging.thread ────────────────────────────────────────
    def _handle_messaging_thread(
        *,
        contact: str,
        channel: str = "",
        **_: Any,
    ) -> dict:
        """Get conversation thread with a contact."""
        import asyncio

        from bantz.messaging.gmail_channel import GmailChannel
        from bantz.messaging.pipeline import MessagingPipeline

        pipeline = MessagingPipeline()
        pipeline.register_channel(GmailChannel())

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    conv = pool.submit(
                        asyncio.run,
                        pipeline.get_conversation(
                            contact,
                            channel=channel or None,
                        ),
                    ).result(timeout=30)
            else:
                conv = asyncio.run(
                    pipeline.get_conversation(
                        contact,
                        channel=channel or None,
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "contact": conv.contact,
            "message_count": conv.message_count,
            "summary": conv.summary,
            "messages": [
                {
                    "id": m.id,
                    "from": m.sender,
                    "subject": m.subject,
                    "preview": m.preview,
                    "date": m.timestamp.isoformat(),
                }
                for m in conv.messages[:20]
            ],
        }

    n += _reg(
        registry,
        "messaging.thread",
        (
            "Yazışma geçmişi — bir kişiyle olan tüm mesajlaşma geçmişini getir "
            "ve LLM ile özetle. Cross-channel destekler."
        ),
        _obj(
            ("contact", "string", "Kişi adı veya adresi"),
            ("channel", "string", "Kanal filtresi (boş → tümü)"),
            required=["contact"],
        ),
        _handle_messaging_thread,
        risk="low",
    )

    # ── messaging.status ────────────────────────────────────────
    def _handle_messaging_status(**_: Any) -> dict:
        """Return messaging pipeline status."""
        return {
            "ok": True,
            "available_channels": ["email"],
            "pipeline": "active",
            "features": [
                "read_inbox",
                "draft_reply",
                "send",
                "thread",
                "batch_draft",
            ],
        }

    n += _reg(
        registry,
        "messaging.status",
        "Mesajlaşma pipeline durumunu gösterir: aktif kanallar, özellikler.",
        _obj(required=[]),
        _handle_messaging_status,
        risk="low",
    )

    return n


# ── Sandbox Agents (Issue #1295) ─────────────────────────────────────

def _register_sandbox_agents(registry: "ToolRegistry") -> int:
    """Register sandbox execution, safety, PC agent, and coding agent tools."""
    n = 0

    # Lazy-initialised shared instances
    _instances: dict[str, Any] = {}

    def _get_sandbox() -> Any:
        if "sandbox" not in _instances:
            from bantz.agent.sandbox import SandboxExecutor

            _instances["sandbox"] = SandboxExecutor(mode="none")
        return _instances["sandbox"]

    def _get_guardrails() -> Any:
        if "guardrails" not in _instances:
            from bantz.agent.safety import SafetyGuardrails

            _instances["guardrails"] = SafetyGuardrails()
        return _instances["guardrails"]

    def _get_pc_agent() -> Any:
        if "pc_agent" not in _instances:
            from bantz.agent.pc_agent import PCAgent

            _instances["pc_agent"] = PCAgent(
                sandbox=_get_sandbox(),
                guardrails=_get_guardrails(),
            )
        return _instances["pc_agent"]

    def _get_coding_agent() -> Any:
        if "coding_agent" not in _instances:
            from bantz.agent.coding_agent import CodingAgent

            _instances["coding_agent"] = CodingAgent(
                sandbox=_get_sandbox(),
            )
        return _instances["coding_agent"]

    # ── sandbox.execute ─────────────────────────────────────────
    def _handle_sandbox_execute(
        *,
        command: str,
        workdir: str = "",
        timeout: int = 30,
        dry_run: bool = False,
        **_: Any,
    ) -> dict:
        """Execute a command in the sandbox."""
        import asyncio

        guardrails = _get_guardrails()
        decision = guardrails.check(command)
        if decision.blocked:
            return {"ok": False, "error": decision.reason, "action": "blocked"}

        if decision.action.value == "dry_run_first" and not dry_run:
            dry_run = True

        sandbox = _get_sandbox()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        sandbox.execute(
                            command,
                            workdir=workdir or None,
                            timeout=timeout,
                            dry_run=dry_run,
                        ),
                    ).result(timeout=timeout + 10)
            else:
                result = asyncio.run(
                    sandbox.execute(
                        command,
                        workdir=workdir or None,
                        timeout=timeout,
                        dry_run=dry_run,
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result.to_dict()

    n += _reg(
        registry,
        "sandbox.execute",
        (
            "Sandbox ortamında komut çalıştır — güvenlik kontrollü, "
            "zaman aşımlı, rollback destekli izole yürütme."
        ),
        _obj(
            ("command", "string", "Çalıştırılacak shell komutu"),
            ("workdir", "string", "Çalışma dizini (boş → home)"),
            ("timeout", "integer", "Zaman aşımı (saniye, varsayılan 30)"),
            ("dry_run", "boolean", "Sadece simülasyon (varsayılan false)"),
            required=["command"],
        ),
        _handle_sandbox_execute,
        risk="high",
        confirm=True,
    )

    # ── sandbox.dry_run ─────────────────────────────────────────
    def _handle_sandbox_dry_run(
        *,
        command: str,
        workdir: str = "",
        **_: Any,
    ) -> dict:
        """Dry-run simulation of a command."""
        import asyncio

        guardrails = _get_guardrails()
        decision = guardrails.check(command)
        if decision.blocked:
            return {"ok": False, "error": decision.reason, "action": "blocked"}

        sandbox = _get_sandbox()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        sandbox.execute(
                            command, workdir=workdir or None, dry_run=True
                        ),
                    ).result(timeout=15)
            else:
                result = asyncio.run(
                    sandbox.execute(
                        command, workdir=workdir or None, dry_run=True
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result.to_dict()

    n += _reg(
        registry,
        "sandbox.dry_run",
        "Komutu gerçekten çalıştırmadan simüle et — sonucu tahmin et.",
        _obj(
            ("command", "string", "Simüle edilecek komut"),
            ("workdir", "string", "Çalışma dizini"),
            required=["command"],
        ),
        _handle_sandbox_dry_run,
        risk="low",
    )

    # ── sandbox.rollback ────────────────────────────────────────
    def _handle_sandbox_rollback(
        *, checkpoint_id: str, **_: Any
    ) -> dict:
        """Rollback to a checkpoint."""
        import asyncio

        sandbox = _get_sandbox()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    ok = pool.submit(
                        asyncio.run, sandbox.rollback(checkpoint_id)
                    ).result(timeout=10)
            else:
                ok = asyncio.run(sandbox.rollback(checkpoint_id))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": ok, "checkpoint_id": checkpoint_id}

    n += _reg(
        registry,
        "sandbox.rollback",
        "Önceki bir checkpoint'e geri dön — yıkıcı işlemi geri al.",
        _obj(
            ("checkpoint_id", "string", "Geri dönülecek checkpoint ID"),
            required=["checkpoint_id"],
        ),
        _handle_sandbox_rollback,
        risk="medium",
        confirm=True,
    )

    # ── sandbox.checkpoints ─────────────────────────────────────
    def _handle_sandbox_checkpoints(**_: Any) -> dict:
        """List all sandbox checkpoints."""
        sandbox = _get_sandbox()
        return {
            "ok": True,
            "checkpoints": sandbox.get_checkpoints(),
        }

    n += _reg(
        registry,
        "sandbox.checkpoints",
        "Tüm sandbox checkpoint'lerini listele — rollback geçmişi.",
        _obj(required=[]),
        _handle_sandbox_checkpoints,
        risk="low",
    )

    # ── safety.check ────────────────────────────────────────────
    def _handle_safety_check(
        *, command: str, **_: Any
    ) -> dict:
        """Check command safety level."""
        guardrails = _get_guardrails()
        decision = guardrails.check(command)
        return {
            "ok": True,
            "command": command,
            "action": decision.action.value,
            "reason": decision.reason,
            "explanation": guardrails.explain(command),
        }

    n += _reg(
        registry,
        "safety.check",
        (
            "Komutun güvenlik seviyesini kontrol et — "
            "blocked/dry_run_first/confirm/allow."
        ),
        _obj(
            ("command", "string", "Kontrol edilecek komut"),
            required=["command"],
        ),
        _handle_safety_check,
        risk="low",
    )

    # ── pc.list_files ───────────────────────────────────────────
    def _handle_pc_list_files(
        *,
        path: str,
        pattern: str = "*",
        recursive: bool = False,
        include_hidden: bool = False,
        **_: Any,
    ) -> dict:
        """List files in a directory."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    files = pool.submit(
                        asyncio.run,
                        pc.list_files(
                            path,
                            pattern=pattern,
                            recursive=recursive,
                            include_hidden=include_hidden,
                        ),
                    ).result(timeout=15)
            else:
                files = asyncio.run(
                    pc.list_files(
                        path,
                        pattern=pattern,
                        recursive=recursive,
                        include_hidden=include_hidden,
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "count": len(files),
            "files": [f.to_dict() for f in files[:100]],
        }

    n += _reg(
        registry,
        "pc.list_files",
        "Dizindeki dosyaları listele — glob filtre, özyinelemeli arama.",
        _obj(
            ("path", "string", "Dizin yolu"),
            ("pattern", "string", "Glob deseni (varsayılan: *)"),
            ("recursive", "boolean", "Alt dizinlere in (varsayılan: false)"),
            ("include_hidden", "boolean", "Gizli dosyaları dahil et"),
            required=["path"],
        ),
        _handle_pc_list_files,
        risk="low",
    )

    # ── pc.search_files ─────────────────────────────────────────
    def _handle_pc_search_files(
        *,
        directory: str,
        query: str,
        max_results: int = 50,
        **_: Any,
    ) -> dict:
        """Search files matching a query."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    files = pool.submit(
                        asyncio.run,
                        pc.search_files(
                            directory, query, max_results=max_results
                        ),
                    ).result(timeout=20)
            else:
                files = asyncio.run(
                    pc.search_files(directory, query, max_results=max_results)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "count": len(files),
            "files": [f.to_dict() for f in files],
        }

    n += _reg(
        registry,
        "pc.search_files",
        "Dosya ara — dizinde ada göre dosya bul.",
        _obj(
            ("directory", "string", "Arama yapılacak dizin"),
            ("query", "string", "Arama sorgusu (dosya adı parçası)"),
            ("max_results", "integer", "Maksimum sonuç (varsayılan: 50)"),
            required=["directory", "query"],
        ),
        _handle_pc_search_files,
        risk="low",
    )

    # ── pc.file_info ────────────────────────────────────────────
    def _handle_pc_file_info(*, path: str, **_: Any) -> dict:
        """Get detailed file information."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    info = pool.submit(
                        asyncio.run, pc.file_info(path)
                    ).result(timeout=10)
            else:
                info = asyncio.run(pc.file_info(path))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return info

    n += _reg(
        registry,
        "pc.file_info",
        "Dosya detay bilgisi — boyut, izinler, değişiklik tarihi.",
        _obj(
            ("path", "string", "Dosya yolu"),
            required=["path"],
        ),
        _handle_pc_file_info,
        risk="low",
    )

    # ── pc.organize_files ───────────────────────────────────────
    def _handle_pc_organize_files(
        *,
        source_dir: str,
        by: str = "extension",
        dry_run: bool = True,
        **_: Any,
    ) -> dict:
        """Organize files in a directory."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        pc.organize_files(source_dir, by=by, dry_run=dry_run),
                    ).result(timeout=30)
            else:
                result = asyncio.run(
                    pc.organize_files(source_dir, by=by, dry_run=dry_run)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "pc.organize_files",
        (
            "Dosyaları düzenle — uzantı veya tarihe göre klasörlere ayır. "
            "Varsayılan: simülasyon modu."
        ),
        _obj(
            ("source_dir", "string", "Kaynak dizin"),
            ("by", "string", "Düzenleme kriteri: extension | date"),
            ("dry_run", "boolean", "Simülasyon modu (varsayılan: true)"),
            required=["source_dir"],
        ),
        _handle_pc_organize_files,
        risk="medium",
        confirm=True,
    )

    # ── pc.launch_app ───────────────────────────────────────────
    def _handle_pc_launch_app(
        *,
        app_name: str,
        args: str = "",
        **_: Any,
    ) -> dict:
        """Launch a desktop application."""
        import asyncio

        pc = _get_pc_agent()
        arg_list = args.split() if args else None
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        pc.launch_app(app_name, arg_list),
                    ).result(timeout=15)
            else:
                result = asyncio.run(pc.launch_app(app_name, arg_list))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "pc.launch_app",
        "Uygulama başlat — masaüstü uygulamasını aç/çalıştır.",
        _obj(
            ("app_name", "string", "Uygulama adı veya komutu"),
            ("args", "string", "Ek argümanlar (boşlukla ayrılmış)"),
            required=["app_name"],
        ),
        _handle_pc_launch_app,
        risk="medium",
        confirm=True,
    )

    # ── pc.clipboard_get ────────────────────────────────────────
    def _handle_pc_clipboard_get(**_: Any) -> dict:
        """Get clipboard content."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, pc.clipboard_get()
                    ).result(timeout=5)
            else:
                result = asyncio.run(pc.clipboard_get())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "pc.clipboard_get",
        "Pano içeriğini oku — mevcut clipboard içeriğini getir.",
        _obj(required=[]),
        _handle_pc_clipboard_get,
        risk="low",
    )

    # ── pc.clipboard_set ────────────────────────────────────────
    def _handle_pc_clipboard_set(
        *, content: str, **_: Any
    ) -> dict:
        """Set clipboard content."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, pc.clipboard_set(content)
                    ).result(timeout=5)
            else:
                result = asyncio.run(pc.clipboard_set(content))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "pc.clipboard_set",
        "Panoya yaz — verilen metni clipboard'a kopyala.",
        _obj(
            ("content", "string", "Panoya yazılacak metin"),
            required=["content"],
        ),
        _handle_pc_clipboard_set,
        risk="medium",
    )

    # ── pc.system_info ──────────────────────────────────────────
    def _handle_pc_system_info(**_: Any) -> dict:
        """Get system information."""
        import asyncio

        pc = _get_pc_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, pc.system_info()
                    ).result(timeout=10)
            else:
                result = asyncio.run(pc.system_info())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "pc.system_info",
        "Sistem bilgisi — CPU, RAM, disk, hostname, OS detayları.",
        _obj(required=[]),
        _handle_pc_system_info,
        risk="low",
    )

    # ── coding.generate ─────────────────────────────────────────
    def _handle_coding_generate(
        *,
        spec: str,
        language: str = "python",
        **_: Any,
    ) -> dict:
        """Generate code from a specification."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        agent.generate_code(spec, language=language),
                    ).result(timeout=60)
            else:
                result = asyncio.run(
                    agent.generate_code(spec, language=language)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.ok,
            "code": result.code[:8192],
            "language": result.language,
            "syntax_valid": result.syntax_valid,
            "error": result.error,
        }

    n += _reg(
        registry,
        "coding.generate",
        "Kod üret — LLM ile doğal dilde tarif edilen kodu oluştur.",
        _obj(
            ("spec", "string", "Kod tanımı (doğal dilde)"),
            ("language", "string", "Hedef dil (varsayılan: python)"),
            required=["spec"],
        ),
        _handle_coding_generate,
        risk="medium",
    )

    # ── coding.write_tests ──────────────────────────────────────
    def _handle_coding_write_tests(
        *,
        source_file: str,
        framework: str = "pytest",
        **_: Any,
    ) -> dict:
        """Generate tests for a source file."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        agent.write_tests(source_file, framework=framework),
                    ).result(timeout=60)
            else:
                result = asyncio.run(
                    agent.write_tests(source_file, framework=framework)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.ok,
            "code": result.code[:8192],
            "file_path": result.file_path,
            "syntax_valid": result.syntax_valid,
            "error": result.error,
        }

    n += _reg(
        registry,
        "coding.write_tests",
        "Test yaz — kaynak dosya için otomatik unit test üret.",
        _obj(
            ("source_file", "string", "Test yazılacak kaynak dosya yolu"),
            ("framework", "string", "Test framework: pytest | unittest"),
            required=["source_file"],
        ),
        _handle_coding_write_tests,
        risk="medium",
    )

    # ── coding.run_tests ────────────────────────────────────────
    def _handle_coding_run_tests(
        *,
        path: str = ".",
        verbose: bool = True,
        timeout: int = 120,
        **_: Any,
    ) -> dict:
        """Run tests in the sandbox."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        agent.run_tests(path, verbose=verbose, timeout=timeout),
                    ).result(timeout=timeout + 15)
            else:
                result = asyncio.run(
                    agent.run_tests(path, verbose=verbose, timeout=timeout)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.ok,
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
            "output": result.output[:4096],
            "duration_ms": result.duration_ms,
            "error": result.error,
        }

    n += _reg(
        registry,
        "coding.run_tests",
        "Test çalıştır — sandbox'ta pytest/unittest çalıştır ve sonuçları raporla.",
        _obj(
            ("path", "string", "Test dosya/dizin yolu (varsayılan: .)"),
            ("verbose", "boolean", "Detaylı çıktı (varsayılan: true)"),
            ("timeout", "integer", "Zaman aşımı saniye (varsayılan: 120)"),
        ),
        _handle_coding_run_tests,
        risk="medium",
    )

    # ── coding.git_status ───────────────────────────────────────
    def _handle_coding_git_status(**_: Any) -> dict:
        """Get git status."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, agent.git_status()
                    ).result(timeout=10)
            else:
                result = asyncio.run(agent.git_status())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "coding.git_status",
        "Git durumu — workspace'teki değişiklikleri göster.",
        _obj(required=[]),
        _handle_coding_git_status,
        risk="low",
    )

    # ── coding.git_diff ─────────────────────────────────────────
    def _handle_coding_git_diff(
        *, staged: bool = False, **_: Any
    ) -> dict:
        """Get git diff."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, agent.git_diff(staged=staged)
                    ).result(timeout=15)
            else:
                result = asyncio.run(agent.git_diff(staged=staged))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "coding.git_diff",
        "Git fark — değişiklikleri (unstaged veya staged) göster.",
        _obj(
            ("staged", "boolean", "Staged değişiklikleri göster (varsayılan: false)"),
        ),
        _handle_coding_git_diff,
        risk="low",
    )

    # ── coding.git_commit ───────────────────────────────────────
    def _handle_coding_git_commit(
        *,
        message: str,
        add_all: bool = True,
        **_: Any,
    ) -> dict:
        """Create a git commit."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        agent.git_commit(message, add_all=add_all),
                    ).result(timeout=15)
            else:
                result = asyncio.run(
                    agent.git_commit(message, add_all=add_all)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "coding.git_commit",
        "Git commit — değişiklikleri commit'le (mesaj ile).",
        _obj(
            ("message", "string", "Commit mesajı"),
            ("add_all", "boolean", "Önce tüm değişiklikleri stage'le (varsayılan: true)"),
            required=["message"],
        ),
        _handle_coding_git_commit,
        risk="high",
        confirm=True,
    )

    # ── coding.git_log ──────────────────────────────────────────
    def _handle_coding_git_log(
        *, count: int = 10, **_: Any
    ) -> dict:
        """Get recent git log."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, agent.git_log(count=count)
                    ).result(timeout=10)
            else:
                result = asyncio.run(agent.git_log(count=count))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "coding.git_log",
        "Git geçmişi — son commit'leri listele.",
        _obj(
            ("count", "integer", "Gösterilecek commit sayısı (varsayılan: 10)"),
        ),
        _handle_coding_git_log,
        risk="low",
    )

    # ── coding.review ───────────────────────────────────────────
    def _handle_coding_review(
        *, file_path: str, **_: Any
    ) -> dict:
        """Review code in a file."""
        import asyncio

        agent = _get_coding_agent()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, agent.code_review(file_path)
                    ).result(timeout=60)
            else:
                result = asyncio.run(agent.code_review(file_path))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": result.ok,
            "summary": result.summary,
            "suggestions": result.suggestions,
            "severity": result.severity,
            "error": result.error,
        }

    n += _reg(
        registry,
        "coding.review",
        "Kod inceleme — dosyayı analiz et, öneriler sun.",
        _obj(
            ("file_path", "string", "İncelenecek dosya yolu"),
            required=["file_path"],
        ),
        _handle_coding_review,
        risk="low",
    )

    return n


# ── Music (Issue #1296) ──────────────────────────────────────────────

def _register_music(registry: "ToolRegistry") -> int:
    """Register music playback, search, and suggestion tools."""
    n = 0

    _instances: dict[str, Any] = {}

    def _get_player() -> Any:
        if "player" not in _instances:
            import os

            from bantz.skills.music.local_player import LocalPlayer
            from bantz.skills.music.spotify_player import SpotifyPlayer
            from bantz.skills.music.ytmusic_player import YTMusicPlayer

            token = os.environ.get("BANTZ_SPOTIFY_TOKEN", "")
            spotify = SpotifyPlayer(access_token=token or None)
            ytmusic = YTMusicPlayer(
                auth_file=os.environ.get("BANTZ_YTMUSIC_AUTH"),
                browser_player=os.environ.get(
                    "BANTZ_YTMUSIC_BROWSER", "chromium",
                ),
            )
            local = LocalPlayer()

            if spotify.available:
                _instances["player"] = spotify
            elif ytmusic.available:
                _instances["player"] = ytmusic
            elif local.available:
                _instances["player"] = local
            else:
                # Default to ytmusic (may fail gracefully)
                _instances["player"] = ytmusic
        return _instances["player"]

    def _get_suggester() -> Any:
        if "suggester" not in _instances:
            from bantz.skills.music.suggester import MusicSuggester

            _instances["suggester"] = MusicSuggester()
        return _instances["suggester"]

    # ── music.play ──────────────────────────────────────────────
    def _handle_music_play(
        *,
        query: str = "",
        playlist: str = "",
        uri: str = "",
        **_: Any,
    ) -> dict:
        """Play music."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        player.play(
                            query or None,
                            playlist=playlist or None,
                            uri=uri or None,
                        ),
                    ).result(timeout=15)
            else:
                result = asyncio.run(
                    player.play(
                        query or None,
                        playlist=playlist or None,
                        uri=uri or None,
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.play",
        (
            "Play music — start a song/playlist by query, "
            "resume, or play by URI."
        ),
        _obj(
            ("query", "string", "Search query (genre, song name, artist)"),
            ("playlist", "string", "Playlist name"),
            ("uri", "string", "Direct Spotify/media URI"),
        ),
        _handle_music_play,
        risk="low",
    )

    # ── music.pause ─────────────────────────────────────────────
    def _handle_music_pause(**_: Any) -> dict:
        """Pause music."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.pause()
                    ).result(timeout=5)
            else:
                result = asyncio.run(player.pause())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.pause",
        "Pause music.",
        _obj(required=[]),
        _handle_music_pause,
        risk="low",
    )

    # ── music.resume ────────────────────────────────────────────
    def _handle_music_resume(**_: Any) -> dict:
        """Resume music."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.resume()
                    ).result(timeout=5)
            else:
                result = asyncio.run(player.resume())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.resume",
        "Resume music.",
        _obj(required=[]),
        _handle_music_resume,
        risk="low",
    )

    # ── music.next ──────────────────────────────────────────────
    def _handle_music_next(**_: Any) -> dict:
        """Skip to next track."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.next_track()
                    ).result(timeout=5)
            else:
                result = asyncio.run(player.next_track())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.next",
        "Skip to next track.",
        _obj(required=[]),
        _handle_music_next,
        risk="low",
    )

    # ── music.prev ──────────────────────────────────────────────
    def _handle_music_prev(**_: Any) -> dict:
        """Go to previous track."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.prev_track()
                    ).result(timeout=5)
            else:
                result = asyncio.run(player.prev_track())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.prev",
        "Go to previous track.",
        _obj(required=[]),
        _handle_music_prev,
        risk="low",
    )

    # ── music.stop ──────────────────────────────────────────────
    def _handle_music_stop(**_: Any) -> dict:
        """Stop playback."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.stop()
                    ).result(timeout=5)
            else:
                result = asyncio.run(player.stop())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.stop",
        "Stop music.",
        _obj(required=[]),
        _handle_music_stop,
        risk="low",
    )

    # ── music.volume ────────────────────────────────────────────
    def _handle_music_volume(
        *, level: int = -1, **_: Any
    ) -> dict:
        """Set or get volume."""
        import asyncio

        player = _get_player()
        try:
            if level < 0:
                # Get volume
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run, player.get_volume()
                        ).result(timeout=5)
                else:
                    result = asyncio.run(player.get_volume())
            else:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        result = pool.submit(
                            asyncio.run, player.set_volume(level)
                        ).result(timeout=5)
                else:
                    result = asyncio.run(player.set_volume(level))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.volume",
        "Set or show volume level (0-100).",
        _obj(
            ("level", "integer", "Volume level (0-100). Negative → show current level."),
        ),
        _handle_music_volume,
        risk="low",
    )

    # ── music.status ────────────────────────────────────────────
    def _handle_music_status(**_: Any) -> dict:
        """Get player status."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run, player.status()
                    ).result(timeout=10)
            else:
                result = asyncio.run(player.status())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return result

    n += _reg(
        registry,
        "music.status",
        "Current music status — track, artist, volume.",
        _obj(required=[]),
        _handle_music_status,
        risk="low",
    )

    # ── music.search ────────────────────────────────────────────
    def _handle_music_search(
        *, query: str, limit: int = 10, **_: Any
    ) -> dict:
        """Search for tracks."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    tracks = pool.submit(
                        asyncio.run,
                        player.search(query, limit=limit),
                    ).result(timeout=15)
            else:
                tracks = asyncio.run(
                    player.search(query, limit=limit)
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "count": len(tracks),
            "tracks": [t.to_dict() for t in tracks],
        }

    n += _reg(
        registry,
        "music.search",
        "Search for music — find tracks/artists/albums.",
        _obj(
            ("query", "string", "Search query"),
            ("limit", "integer", "Maximum results (default: 10)"),
            required=["query"],
        ),
        _handle_music_search,
        risk="low",
    )

    # ── music.playlists ─────────────────────────────────────────
    def _handle_music_playlists(**_: Any) -> dict:
        """List playlists."""
        import asyncio

        player = _get_player()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    playlists = pool.submit(
                        asyncio.run, player.list_playlists()
                    ).result(timeout=15)
            else:
                playlists = asyncio.run(player.list_playlists())
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "count": len(playlists),
            "playlists": [p.to_dict() for p in playlists],
        }

    n += _reg(
        registry,
        "music.playlists",
        "List playlists — get available playlists.",
        _obj(required=[]),
        _handle_music_playlists,
        risk="low",
    )

    # ── music.suggest ───────────────────────────────────────────
    def _handle_music_suggest(**_: Any) -> dict:
        """Get context-aware music suggestion."""
        suggester = _get_suggester()
        suggestion = suggester.suggest()
        return {
            "ok": True,
            **suggestion.to_dict(),
        }

    n += _reg(
        registry,
        "music.suggest",
        "Context-aware music suggestion — based on calendar and time of day.",
        _obj(required=[]),
        _handle_music_suggest,
        risk="low",
    )

    return n


# ── Health & Degradation (Issue #1298) ──────────────────────────────

def _register_health(registry: "ToolRegistry") -> int:
    """Register tools: system.health, system.health_service,
    system.circuit_breaker, system.fallback."""
    n = 0

    # ── system.health ───────────────────────────────────────────
    def _handle_health(**_: Any) -> dict:
        """Run all health checks and return aggregated report."""
        import asyncio

        from bantz.core.health_monitor import get_health_monitor

        monitor = get_health_monitor()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                report = pool.submit(
                    lambda: asyncio.run(monitor.check_all())
                ).result(timeout=30)
        else:
            report = asyncio.run(monitor.check_all())

        return {"ok": True, **report.to_dict()}

    n += _reg(
        registry,
        "system.health",
        "Run health checks on all services and return aggregated report.",
        _obj(required=[]),
        _handle_health,
        risk="low",
    )

    # ── system.health_service ───────────────────────────────────
    def _handle_health_service(*, service: str = "", **_: Any) -> dict:
        """Check health of a specific service."""
        import asyncio

        from bantz.core.health_monitor import get_health_monitor

        if not service:
            return {"ok": False, "error": "service parameter is required"}

        monitor = get_health_monitor()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                status = pool.submit(
                    lambda: asyncio.run(monitor.check_service(service))
                ).result(timeout=15)
        else:
            status = asyncio.run(monitor.check_service(service))

        return {"ok": True, **status.to_dict()}

    n += _reg(
        registry,
        "system.health_service",
        "Check health of a specific service.",
        _obj(
            ("service", "string", "Service name to check (sqlite, ollama, google)"),
            required=["service"],
        ),
        _handle_health_service,
        risk="low",
    )

    # ── system.circuit_breaker ──────────────────────────────────
    def _handle_circuit_breaker(**_: Any) -> dict:
        """Get circuit breaker states for all domains."""
        from bantz.agent.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        return {
            "ok": True,
            "domains": cb.to_dict(),
            "config": {
                "failure_threshold": cb.failure_threshold,
                "reset_timeout": cb.reset_timeout,
                "success_threshold": cb.success_threshold,
            },
        }

    n += _reg(
        registry,
        "system.circuit_breaker",
        "List circuit breaker states for all domains.",
        _obj(required=[]),
        _handle_circuit_breaker,
        risk="low",
    )

    # ── system.fallback ─────────────────────────────────────────
    def _handle_fallback(*, service: str = "", **_: Any) -> dict:
        """Execute fallback for a service or list all fallback configs."""
        from bantz.core.fallback_registry import get_fallback_registry

        fb = get_fallback_registry()

        if not service:
            return {
                "ok": True,
                "services": fb.list_services(),
                "configs": fb.to_dict(),
            }

        result = fb.execute_fallback(service)
        return {"ok": result.success, **result.to_dict()}

    n += _reg(
        registry,
        "system.fallback",
        "Query service fallback status or execute a fallback.",
        _obj(
            ("service", "string", "Service name for fallback execution (optional)"),
        ),
        _handle_fallback,
        risk="low",
    )

    return n


# ── Sync Search (10) ────────────────────────────────────────────────

def _register_sync_search(registry: "ToolRegistry") -> int:
    """Register DB-backed search tools for synced data (Gmail, Calendar, News)."""
    try:
        from bantz.tools.sync_search_tools import (
            inbox_search_tool,
            inbox_by_category_tool,
            inbox_categories_tool,
            inbox_summary_tool,
            calendar_upcoming_tool,
            calendar_search_tool,
            news_latest_tool,
            news_search_tool,
            sync_status_tool,
            sync_now_tool,
        )
    except Exception as e:
        logger.warning(f"[ToolGap] sync_search import: {e}")
        return 0

    n = 0

    n += _reg(
        registry,
        "inbox.search",
        "Search synced Gmail messages locally by keyword. Faster than live API — searches subject, sender, snippet in the local database.",
        _obj(
            ("query", "string", "Search keyword (subject, sender, snippet)"),
            ("limit", "integer", "Max results (default 20)"),
        ),
        inbox_search_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "inbox.by_category",
        "List synced messages by classification category (github, tubitak, linkedin, google, bank, newsletter, social, education, shopping, travel, etc.).",
        _obj(
            ("category", "string", "Category to filter: github, tubitak, linkedin, google, amazon, bank, newsletter, social, education, shopping, travel, uncategorized"),
            ("limit", "integer", "Max results (default 20)"),
            required=["category"],
        ),
        inbox_by_category_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "inbox.categories",
        "List all inbox classification categories with message counts.",
        _obj(),
        inbox_categories_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "inbox.summary",
        "Get inbox summary: total messages, top categories, top senders, recent subjects.",
        _obj(),
        inbox_summary_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "calendar.upcoming",
        "Get upcoming events from locally synced calendar. Faster than live API call.",
        _obj(
            ("days", "integer", "Days forward to look (default 7)"),
            ("limit", "integer", "Max events (default 20)"),
        ),
        calendar_upcoming_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "calendar.search",
        "Search synced calendar events by keyword (title, location).",
        _obj(
            ("query", "string", "Search keyword"),
            ("limit", "integer", "Max results (default 20)"),
            required=["query"],
        ),
        calendar_search_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "news.latest",
        "Get latest news articles from locally synced RSS feeds. Categories: ai, tech, turkey.",
        _obj(
            ("category", "string", "Filter by category: ai, tech, turkey (empty=all)"),
            ("limit", "integer", "Max articles (default 5)"),
        ),
        news_latest_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "news.search",
        "Search synced news articles by keyword across all categories.",
        _obj(
            ("query", "string", "Search keyword in title, source, summary"),
            ("limit", "integer", "Max results (default 10)"),
            required=["query"],
        ),
        news_search_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "sync.status",
        "Show data synchronization health: last sync times, stats, running state for Gmail/Calendar/News.",
        _obj(),
        sync_status_tool,
        risk="low",
    )

    n += _reg(
        registry,
        "sync.now",
        "Trigger immediate sync for a specific data source (gmail, calendar, news) or all sources.",
        _obj(
            ("source", "string", "Source to sync: gmail, calendar, news (empty=all)"),
        ),
        sync_now_tool,
        risk="low",
    )

    return n


# ── News (4) ─────────────────────────────────────────────────────────

def _register_news(registry: "ToolRegistry") -> int:
    """Register news tools (Issue #839)."""
    try:
        from bantz.tools.news_tools import (
            news_latest_tool,
            news_search_tool,
            news_briefing_tool,
            news_category_tool,
        )
    except ImportError as e:
        logger.warning("[ToolGap] news tools import: %s", e)
        return 0

    n = 0

    n += _reg(
        registry,
        "news.latest",
        "Get the latest news headlines from all configured categories.",
        _obj(
            ("max_items", "integer", "Maximum number of headlines to return (default: 5)"),
        ),
        news_latest_tool,
    )

    n += _reg(
        registry,
        "news.search",
        "Search news articles by keyword or topic.",
        _obj(
            ("query", "string", "Search query (e.g. 'artificial intelligence', 'Turkey economy')"),
            ("max_results", "integer", "Maximum results (default: 10)"),
            required=["query"],
        ),
        news_search_tool,
    )

    n += _reg(
        registry,
        "news.briefing",
        "Get a multi-category news briefing (AI, tech, world, Turkey, etc.).",
        _obj(
            ("categories", "string", "Comma-separated categories: ai,tech,world,turkey,science,business"),
            ("max_items", "integer", "Max articles per category (default: 3)"),
        ),
        news_briefing_tool,
    )

    n += _reg(
        registry,
        "news.category",
        "Get news for a specific category (ai, tech, world, turkey, science, business).",
        _obj(
            ("category", "string", "Category: ai, tech, world, turkey, science, business"),
            ("max_items", "integer", "Max articles (default: 5)"),
            required=["category"],
        ),
        news_category_tool,
    )

    return n
