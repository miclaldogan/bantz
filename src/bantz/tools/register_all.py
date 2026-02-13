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
from typing import Any, TYPE_CHECKING

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
    logger.info(f"[ToolGap] Total tools registered: {count}")
    return count


# ── helpers ──────────────────────────────────────────────────────────

def _reg(registry: "ToolRegistry", name: str, desc: str, params: dict,
         fn, *, risk: str = "low", confirm: bool = False) -> bool:
    """Register a single tool, returning True on success."""
    from bantz.agent.tools import Tool
    try:
        registry.register(Tool(
            name=name,
            description=desc,
            parameters=params,
            function=fn,
            risk_level=risk,
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
        from bantz.tools.browser_tools import (
            browser_open_tool, browser_scan_tool, browser_click_tool,
            browser_type_tool, browser_back_tool, browser_info_tool,
            browser_detail_tool, browser_wait_tool, browser_search_tool,
            browser_scroll_down_tool, browser_scroll_up_tool,
        )
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
              _obj(("selector", "string", "CSS selector or element index"), required=["selector"]),
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
              _obj(("selector", "string", "CSS selector"), required=["selector"]),
              browser_detail_tool)
    n += _reg(registry, "browser.wait", "Wait for a page element to appear.",
              _obj(("selector", "string", "CSS selector to wait for"),
                   ("timeout", "integer", "Timeout in ms (default 5000)")),
              browser_wait_tool)
    n += _reg(registry, "browser.extract", "Extract structured data from page.",
              _obj(("selector", "string", "CSS selector for extraction")),
              browser_detail_tool)  # reuse detail handler
    return n


# ── PC Control (5 + clipboard) ──────────────────────────────────────

def _register_pc(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.pc_tools import (
            pc_hotkey_tool, pc_type_tool, pc_mouse_move_tool, pc_mouse_click_tool,
            pc_mouse_scroll_tool, clipboard_set_tool, clipboard_get_tool,
        )
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
        from bantz.tools.file_tools import (
            file_read_tool, file_write_tool, file_edit_tool,
            file_create_tool, file_undo_tool, file_search_tool,
        )
    except ImportError as e:
        logger.warning(f"[ToolGap] file import: {e}")
        return 0

    n = 0
    n += _reg(registry, "file.read", "Read file contents.",
              _obj(("path", "string", "File path"), ("lines", "string", "Line range e.g. '1-50'"),
                   required=["path"]),
              file_read_tool)
    n += _reg(registry, "file.write", "Write content to a file.",
              _obj(("path", "string", "File path"), ("content", "string", "File content"),
                   required=["path", "content"]),
              file_write_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.edit", "Edit a specific part of a file.",
              _obj(("path", "string", "File path"), ("old", "string", "Text to replace"),
                   ("new", "string", "Replacement text"), required=["path", "old", "new"]),
              file_edit_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.create", "Create a new file.",
              _obj(("path", "string", "File path"), ("content", "string", "Initial content"),
                   required=["path"]),
              file_create_tool, risk="medium", confirm=True)
    n += _reg(registry, "file.undo", "Undo last file edit (restore from backup).",
              _obj(("path", "string", "File path"), required=["path"]),
              file_undo_tool, risk="medium")
    n += _reg(registry, "file.search", "Search for files or text patterns.",
              _obj(("query", "string", "Search pattern"), ("path", "string", "Base directory"),
                   required=["query"]),
              file_search_tool)
    return n


# ── Terminal (4) ─────────────────────────────────────────────────────

def _register_terminal(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.terminal_tools import (
            terminal_run_tool, terminal_background_tool,
            terminal_background_list_tool, terminal_background_kill_tool,
        )
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
              _obj(("pid", "integer", "Process ID to kill"), required=["pid"]),
              terminal_background_kill_tool, risk="medium", confirm=True)
    return n


# ── Code (6) ─────────────────────────────────────────────────────────

def _register_code(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.code_tools import (
            code_format_tool, code_replace_function_tool,
            project_info_tool, project_tree_tool,
            project_symbols_tool, project_search_symbol_tool,
        )
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
        from bantz.tools.gmail_tools import (
            gmail_unread_count_tool, gmail_list_messages_tool,
            gmail_get_message_tool, gmail_send_tool,
            gmail_smart_search_tool, gmail_list_categories_tool,
        )
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
              _obj(("query", "string", "Search query"), required=["query"]),
              gmail_smart_search_tool)
    n += _reg(registry, "gmail.list_categories", "List Gmail categories with counts.",
              _obj(), gmail_list_categories_tool)
    return n


# ── Gmail extended (14) ─────────────────────────────────────────────

def _register_gmail_extended(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.gmail_extended_tools import (
            gmail_list_labels_tool, gmail_add_label_tool,
            gmail_remove_label_tool, gmail_mark_read_tool,
            gmail_mark_unread_tool, gmail_archive_tool,
            gmail_batch_modify_tool, gmail_download_attachment_tool,
            gmail_create_draft_tool, gmail_list_drafts_tool,
            gmail_update_draft_tool, gmail_send_draft_tool,
            gmail_delete_draft_tool, gmail_generate_reply_tool,
        )
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
              _obj(("draft_id", "string", "Draft ID"), required=["draft_id"]),
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
        from bantz.tools.contacts_tools import (
            contacts_search_tool, contacts_get_tool,
            contacts_list_tool, contacts_add_tool,
        )
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
        from bantz.tools.calendar_tools import (
            calendar_list_events_tool,
            calendar_create_event_tool,
            calendar_update_event_tool,
            calendar_delete_event_tool,
        )
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "calendar.list_events", "List upcoming calendar events.",
              _obj(("days", "integer", "Days ahead to look (default 7)"),
                   ("max_results", "integer", "Max events")),
              calendar_list_events_tool)
    n += _reg(registry, "calendar.create_event", "Create a calendar event.",
              _obj(("title", "string", "Event title"),
                   ("start", "string", "Start datetime ISO"),
                   ("end", "string", "End datetime ISO"),
                   ("description", "string", "Event description"),
                   required=["title", "start"]),
              calendar_create_event_tool, risk="medium", confirm=True)
    n += _reg(registry, "calendar.update_event", "Update a calendar event.",
              _obj(("event_id", "string", "Event ID"), required=["event_id"]),
              calendar_update_event_tool, risk="medium", confirm=True)
    n += _reg(registry, "calendar.delete_event", "Delete a calendar event.",
              _obj(("event_id", "string", "Event ID"), required=["event_id"]),
              calendar_delete_event_tool, risk="high", confirm=True)
    return n


# ── System (3) ──────────────────────────────────────────────────────

def _register_system(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.system_tools import (
            system_status,
            system_notify_tool,
            system_screenshot_tool,
        )
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "system.info", "Get system information (CPU, RAM, disk).",
              _obj(), system_status)
    n += _reg(registry, "system.notify", "Show desktop notification.",
              _obj(("message", "string", "Notification message"), required=["message"]),
              system_notify_tool)
    n += _reg(registry, "system.screenshot", "Take a screenshot.",
              _obj(("region", "string", "Screen region (optional)")),
              system_screenshot_tool, risk="low")
    return n


# ── Time (2) ────────────────────────────────────────────────────────

def _register_time(registry: "ToolRegistry") -> int:
    try:
        from bantz.tools.time_tools import (
            time_now_tool,
            time_convert_tool,
        )
    except ImportError:
        return 0

    n = 0
    n += _reg(registry, "time.now", "Get current date and time.",
              _obj(("timezone", "string", "Timezone (default: local)")),
              time_now_tool)
    n += _reg(registry, "time.convert", "Convert time between timezones.",
              _obj(("time", "string", "Time to convert"),
                   ("from_tz", "string", "Source timezone"),
                   ("to_tz", "string", "Target timezone"),
                   required=["time"]),
              time_convert_tool)
    return n
