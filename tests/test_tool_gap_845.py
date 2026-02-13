"""Tests for Issue #845 — Planner-Runtime Tool Gap Closure.

Verifies that all 52 previously missing runtime handlers now exist
and function correctly. Tests are organized by tool category:

  1. Registry completeness — all 69 tools with real handlers
  2. Browser tools — mock ExtensionBridge
  3. PC control tools — mock xdotool/xclip
  4. File system tools — sandboxed, real filesystem
  5. Terminal tools — policy enforcement
  6. Code/project tools — AST-based
  7. Gmail extended tools — mock gmail module
  8. Contacts tools — from store
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# 1. Registry Completeness
# ═══════════════════════════════════════════════════════════════════

class TestRegistryCompleteness:
    """Verify the runtime registry has all expected tools."""

    def test_runtime_registry_has_at_least_40_tools(self):
        """Acceptance criteria: ≥40/69 tools with runtime handlers."""
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        assert len(reg.names()) >= 40

    def test_runtime_registry_has_69_tools(self):
        """Full coverage: 69 runtime tools."""
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        assert len(reg.names()) == 69

    def test_no_null_handlers(self):
        """Every registered tool must have a real function handler."""
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        for name in reg.names():
            tool = reg.get(name)
            fn = getattr(tool, "function", None) or getattr(tool, "handler", None)
            assert fn is not None, f"{name} has no function handler"

    def test_browser_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "browser_open", "browser_scan", "browser_click", "browser_type",
            "browser_back", "browser_info", "browser_detail", "browser_wait",
            "browser_search", "browser_scroll_down", "browser_scroll_up",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing browser tool: {t}"

    def test_pc_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "pc_hotkey", "pc_mouse_move", "pc_mouse_click",
            "pc_mouse_scroll", "clipboard_set", "clipboard_get",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing PC tool: {t}"

    def test_file_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "file_read", "file_write", "file_edit",
            "file_create", "file_undo", "file_search",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing file tool: {t}"

    def test_terminal_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "terminal_run", "terminal_background",
            "terminal_background_list", "terminal_background_kill",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing terminal tool: {t}"

    def test_code_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "code_format", "code_replace_function",
            "project_info", "project_tree",
            "project_symbols", "project_search_symbol",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing code tool: {t}"

    def test_gmail_extended_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "gmail.list_labels", "gmail.add_label", "gmail.remove_label",
            "gmail.mark_read", "gmail.mark_unread", "gmail.archive",
            "gmail.batch_modify", "gmail.download_attachment",
            "gmail.create_draft", "gmail.list_drafts", "gmail.update_draft",
            "gmail.send_draft", "gmail.delete_draft", "gmail.generate_reply",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing Gmail tool: {t}"

    def test_contacts_tools_registered(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()
        expected = [
            "contacts.upsert", "contacts.resolve",
            "contacts.list", "contacts.delete",
        ]
        names = reg.names()
        for t in expected:
            assert t in names, f"Missing contacts tool: {t}"


# ═══════════════════════════════════════════════════════════════════
# 2. Browser Tools
# ═══════════════════════════════════════════════════════════════════

class TestBrowserTools:
    """Test browser tool handlers with mocked ExtensionBridge."""

    def _mock_bridge(self, **overrides):
        bridge = MagicMock()
        bridge.has_client.return_value = True
        bridge.request_navigate.return_value = True
        bridge.request_scan.return_value = {
            "elements": [{"tag": "a", "text": "Link 1", "type": "link"}],
            "url": "https://example.com",
            "title": "Example",
        }
        bridge.request_click.return_value = True
        bridge.request_type.return_value = True
        bridge.request_go_back.return_value = True
        bridge.request_scroll.return_value = True
        bridge.get_current_page.return_value = {"url": "https://example.com", "title": "Example"}
        bridge.get_page_elements.return_value = [{"tag": "a", "text": "Link 1"}]
        for k, v in overrides.items():
            setattr(bridge, k, v)
        return bridge

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_open(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_open_tool
        result = browser_open_tool(url="youtube")
        assert result["ok"] is True
        assert "youtube" in result["url"]

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_open_no_url(self, mock_get_bridge):
        from bantz.tools.browser_tools import browser_open_tool
        result = browser_open_tool()
        assert result["ok"] is False
        assert "url_required" in result["error"]

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_scan(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_scan_tool
        result = browser_scan_tool()
        assert result["ok"] is True
        assert result["element_count"] == 1

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_click(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_click_tool
        result = browser_click_tool(index=0)
        assert result["ok"] is True

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_type(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_type_tool
        result = browser_type_tool(text="hello")
        assert result["ok"] is True

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_back(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_back_tool
        result = browser_back_tool()
        assert result["ok"] is True

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_info(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_info_tool
        result = browser_info_tool()
        assert result["ok"] is True
        assert "url" in result

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_detail(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_detail_tool
        result = browser_detail_tool(index=0)
        assert result["ok"] is True

    def test_browser_wait(self):
        from bantz.tools.browser_tools import browser_wait_tool
        result = browser_wait_tool(seconds=1)
        assert result["ok"] is True
        assert result["waited_seconds"] == 1

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_search(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_search_tool
        result = browser_search_tool(query="test")
        assert result["ok"] is True

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_scroll_down(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_scroll_down_tool
        result = browser_scroll_down_tool()
        assert result["ok"] is True

    @patch("bantz.tools.browser_tools._get_bridge")
    def test_browser_scroll_up(self, mock_get_bridge):
        mock_get_bridge.return_value = self._mock_bridge()
        from bantz.tools.browser_tools import browser_scroll_up_tool
        result = browser_scroll_up_tool()
        assert result["ok"] is True

    def test_browser_no_bridge(self):
        """When bridge is unavailable, return graceful error."""
        with patch("bantz.tools.browser_tools._get_bridge", return_value=None):
            from bantz.tools.browser_tools import browser_scan_tool
            result = browser_scan_tool()
            assert result["ok"] is False
            assert "unavailable" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# 3. PC Control Tools
# ═══════════════════════════════════════════════════════════════════

class TestPCTools:
    """Test PC control tools with mocked subprocess."""

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xdotool")
    @patch("bantz.tools.pc_tools._run_cmd")
    def test_pc_hotkey(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from bantz.tools.pc_tools import pc_hotkey_tool
        result = pc_hotkey_tool(combo="alt+tab")
        assert result["ok"] is True
        assert result["sent"] is True

    def test_pc_hotkey_blocked(self):
        from bantz.tools.pc_tools import pc_hotkey_tool
        result = pc_hotkey_tool(combo="ctrl+alt+delete")
        assert result["ok"] is False
        assert "blocked" in result["error"]

    def test_pc_hotkey_empty(self):
        from bantz.tools.pc_tools import pc_hotkey_tool
        result = pc_hotkey_tool()
        assert result["ok"] is False

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xdotool")
    @patch("bantz.tools.pc_tools._run_cmd")
    def test_pc_mouse_move(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from bantz.tools.pc_tools import pc_mouse_move_tool
        result = pc_mouse_move_tool(x=100, y=200)
        assert result["ok"] is True
        assert result["x"] == 100
        assert result["y"] == 200

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xdotool")
    @patch("bantz.tools.pc_tools._run_cmd")
    def test_pc_mouse_click(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from bantz.tools.pc_tools import pc_mouse_click_tool
        result = pc_mouse_click_tool(button="left")
        assert result["ok"] is True

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xdotool")
    @patch("bantz.tools.pc_tools._run_cmd")
    def test_pc_mouse_scroll(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from bantz.tools.pc_tools import pc_mouse_scroll_tool
        result = pc_mouse_scroll_tool(direction="down", amount=5)
        assert result["ok"] is True

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xclip")
    @patch("bantz.tools.pc_tools.subprocess.run")
    def test_clipboard_set(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        from bantz.tools.pc_tools import clipboard_set_tool
        result = clipboard_set_tool(text="test")
        assert result["ok"] is True
        assert result["length"] == 4

    @patch("bantz.tools.pc_tools._check_tool", return_value="/usr/bin/xclip")
    @patch("bantz.tools.pc_tools.subprocess.run")
    def test_clipboard_get(self, mock_run, mock_check):
        mock_run.return_value = MagicMock(returncode=0, stdout="clipboard content", stderr="")
        from bantz.tools.pc_tools import clipboard_get_tool
        result = clipboard_get_tool()
        assert result["ok"] is True
        assert result["text"] == "clipboard content"


# ═══════════════════════════════════════════════════════════════════
# 4. File System Tools
# ═══════════════════════════════════════════════════════════════════

class TestFileTools:
    """Test file tools with real filesystem in tmp directory."""

    @pytest.fixture(autouse=True)
    def setup_workspace(self, tmp_path):
        """Set up a temp workspace for each test."""
        from bantz.tools import file_tools
        file_tools.configure_workspace(tmp_path)
        self.ws = tmp_path

    def test_file_create_and_read(self):
        from bantz.tools.file_tools import file_create_tool, file_read_tool
        # Create
        fpath = str(self.ws / "test.txt")
        result = file_create_tool(path=fpath, content="hello world")
        assert result["ok"] is True
        assert result["created"] is True

        # Read
        result = file_read_tool(path=fpath)
        assert result["ok"] is True
        assert "hello world" in result["content"]

    def test_file_read_line_range(self):
        from bantz.tools.file_tools import file_create_tool, file_read_tool
        fpath = str(self.ws / "lines.txt")
        file_create_tool(path=fpath, content="line1\nline2\nline3\nline4\nline5")
        result = file_read_tool(path=fpath, start_line=2, end_line=4)
        assert result["ok"] is True
        assert "line2" in result["content"]
        assert "line4" in result["content"]
        assert "line1" not in result["content"]

    def test_file_write_with_backup(self):
        from bantz.tools.file_tools import file_create_tool, file_write_tool
        fpath = str(self.ws / "write_test.txt")
        file_create_tool(path=fpath, content="original")
        result = file_write_tool(path=fpath, content="updated")
        assert result["ok"] is True
        assert result["backup"] is not None

    def test_file_edit(self):
        from bantz.tools.file_tools import file_create_tool, file_edit_tool, file_read_tool
        fpath = str(self.ws / "edit_test.txt")
        file_create_tool(path=fpath, content="foo bar baz")
        result = file_edit_tool(path=fpath, old_string="bar", new_string="qux")
        assert result["ok"] is True
        content = file_read_tool(path=fpath)
        assert "foo qux baz" in content["content"]

    def test_file_edit_not_found(self):
        from bantz.tools.file_tools import file_edit_tool
        result = file_edit_tool(path=str(self.ws / "nope.txt"), old_string="x", new_string="y")
        assert result["ok"] is False

    def test_file_create_already_exists(self):
        from bantz.tools.file_tools import file_create_tool
        fpath = str(self.ws / "dup.txt")
        file_create_tool(path=fpath, content="first")
        result = file_create_tool(path=fpath, content="second")
        assert result["ok"] is False
        assert "already_exists" in result["error"]

    def test_file_undo(self):
        from bantz.tools.file_tools import file_create_tool, file_write_tool, file_undo_tool, file_read_tool
        fpath = str(self.ws / "undo_test.txt")
        file_create_tool(path=fpath, content="original")
        file_write_tool(path=fpath, content="changed")
        result = file_undo_tool(path=fpath)
        assert result["ok"] is True
        content = file_read_tool(path=fpath)
        assert "original" in content["content"]

    def test_file_search(self):
        from bantz.tools.file_tools import file_create_tool, file_search_tool
        (self.ws / "subdir").mkdir()
        file_create_tool(path=str(self.ws / "subdir" / "test.py"), content="import os")
        file_create_tool(path=str(self.ws / "subdir" / "data.txt"), content="hello")
        result = file_search_tool(pattern="*.py", path=str(self.ws))
        assert result["ok"] is True
        assert result["count"] >= 1

    def test_file_search_with_content(self):
        from bantz.tools.file_tools import file_create_tool, file_search_tool
        file_create_tool(path=str(self.ws / "a.py"), content="import os\nprint('hello')")
        file_create_tool(path=str(self.ws / "b.py"), content="import sys")
        result = file_search_tool(pattern="*.py", content="hello", path=str(self.ws))
        assert result["ok"] is True
        assert result["count"] == 1

    def test_file_path_traversal_blocked(self):
        from bantz.tools.file_tools import file_read_tool
        result = file_read_tool(path="/etc/shadow")
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
# 5. Terminal Tools
# ═══════════════════════════════════════════════════════════════════

class TestTerminalTools:
    """Test terminal tools with policy enforcement."""

    def test_terminal_run_echo(self):
        from bantz.tools.terminal_tools import terminal_run_tool
        result = terminal_run_tool(command="echo hello")
        assert result["ok"] is True
        assert "hello" in result["output"]

    def test_terminal_run_deny_rm_rf(self):
        from bantz.tools.terminal_tools import terminal_run_tool
        result = terminal_run_tool(command="rm -rf /")
        assert result["ok"] is False
        assert "denied" in result["error"]

    def test_terminal_run_deny_dd(self):
        from bantz.tools.terminal_tools import terminal_run_tool
        result = terminal_run_tool(command="dd if=/dev/zero of=/dev/sda")
        assert result["ok"] is False
        assert "denied" in result["error"]

    def test_terminal_run_deny_shutdown(self):
        from bantz.tools.terminal_tools import terminal_run_tool
        result = terminal_run_tool(command="shutdown now")
        assert result["ok"] is False

    def test_terminal_run_empty(self):
        from bantz.tools.terminal_tools import terminal_run_tool
        result = terminal_run_tool()
        assert result["ok"] is False

    def test_terminal_background_list_empty(self):
        from bantz.tools.terminal_tools import terminal_background_list_tool
        result = terminal_background_list_tool()
        assert result["ok"] is True
        assert isinstance(result["processes"], list)

    def test_terminal_background_kill_not_found(self):
        from bantz.tools.terminal_tools import terminal_background_kill_tool
        result = terminal_background_kill_tool(id=99999)
        assert result["ok"] is False

    def test_terminal_background_start_and_kill(self):
        from bantz.tools.terminal_tools import (
            terminal_background_tool,
            terminal_background_kill_tool,
            terminal_background_list_tool,
        )
        # Start a background sleep
        result = terminal_background_tool(command="sleep 60")
        assert result["ok"] is True
        bg_id = result["id"]

        # List — should show it
        listing = terminal_background_list_tool()
        assert any(p["id"] == bg_id for p in listing["processes"])

        # Kill it
        kill_result = terminal_background_kill_tool(id=bg_id)
        assert kill_result["ok"] is True


# ═══════════════════════════════════════════════════════════════════
# 6. Code / Project Tools
# ═══════════════════════════════════════════════════════════════════

class TestCodeTools:
    """Test code and project tools."""

    def test_project_info(self):
        from bantz.tools.code_tools import project_info_tool
        result = project_info_tool()
        assert result["ok"] is True
        assert "workspace_root" in result

    def test_project_tree(self):
        from bantz.tools.code_tools import project_tree_tool
        result = project_tree_tool(max_depth=2)
        assert result["ok"] is True
        assert "tree" in result

    def test_project_symbols(self, tmp_path):
        from bantz.tools.code_tools import project_symbols_tool
        # Create a temp Python file
        py_file = tmp_path / "sample.py"
        py_file.write_text(textwrap.dedent("""\
            def hello():
                pass

            class MyClass:
                def method(self):
                    pass
        """))
        result = project_symbols_tool(path=str(py_file))
        assert result["ok"] is True
        names = [s["name"] for s in result["symbols"]]
        assert "hello" in names
        assert "MyClass" in names

    def test_project_search_symbol(self):
        from bantz.tools.code_tools import project_search_symbol_tool
        result = project_search_symbol_tool(name="build_default_registry")
        assert result["ok"] is True
        assert result["count"] >= 1

    def test_code_format_not_found(self):
        from bantz.tools.code_tools import code_format_tool
        result = code_format_tool(path="/nonexistent/file.py")
        assert result["ok"] is False

    def test_code_replace_function(self, tmp_path):
        from bantz.tools.code_tools import code_replace_function_tool
        py_file = tmp_path / "funcs.py"
        py_file.write_text(textwrap.dedent("""\
            def old_func():
                return 1

            def keep_func():
                return 2
        """))
        result = code_replace_function_tool(
            path=str(py_file),
            function_name="old_func",
            new_code="def old_func():\n    return 42",
        )
        assert result["ok"] is True
        content = py_file.read_text()
        assert "return 42" in content
        assert "return 2" in content  # keep_func preserved


# ═══════════════════════════════════════════════════════════════════
# 7. Gmail Extended Tools
# ═══════════════════════════════════════════════════════════════════

class TestGmailExtendedTools:
    """Test Gmail extended tools with mocked gmail module."""

    @patch("bantz.tools.gmail_extended_tools.gmail_list_labels", create=True)
    def test_list_labels(self, mock_fn):
        # We need to mock at import time
        with patch.dict("sys.modules", {}):
            from bantz.tools.gmail_extended_tools import gmail_list_labels_tool
        # Mock the lazy import
        with patch("bantz.google.gmail.gmail_list_labels", return_value={"ok": True, "labels": []}, create=True):
            result = gmail_list_labels_tool()
            assert result["ok"] is True

    def test_add_label_missing_params(self):
        from bantz.tools.gmail_extended_tools import gmail_add_label_tool
        result = gmail_add_label_tool()
        assert result["ok"] is False
        assert "required" in result["error"]

    def test_mark_read_missing_id(self):
        from bantz.tools.gmail_extended_tools import gmail_mark_read_tool
        result = gmail_mark_read_tool()
        assert result["ok"] is False

    def test_archive_missing_id(self):
        from bantz.tools.gmail_extended_tools import gmail_archive_tool
        result = gmail_archive_tool()
        assert result["ok"] is False

    def test_create_draft_missing_params(self):
        from bantz.tools.gmail_extended_tools import gmail_create_draft_tool
        result = gmail_create_draft_tool()
        assert result["ok"] is False

    def test_send_draft_missing_id(self):
        from bantz.tools.gmail_extended_tools import gmail_send_draft_tool
        result = gmail_send_draft_tool()
        assert result["ok"] is False

    def test_generate_reply_missing_params(self):
        from bantz.tools.gmail_extended_tools import gmail_generate_reply_tool
        result = gmail_generate_reply_tool()
        assert result["ok"] is False

    def test_download_attachment_missing_params(self):
        from bantz.tools.gmail_extended_tools import gmail_download_attachment_tool
        result = gmail_download_attachment_tool()
        assert result["ok"] is False

    def test_batch_modify_missing_ids(self):
        from bantz.tools.gmail_extended_tools import gmail_batch_modify_tool
        result = gmail_batch_modify_tool()
        assert result["ok"] is False


# ═══════════════════════════════════════════════════════════════════
# 8. Risk Classification
# ═══════════════════════════════════════════════════════════════════

class TestRiskClassification:
    """Verify destructive tools require confirmation."""

    def test_write_tools_require_confirmation(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()

        must_confirm = [
            "gmail.send", "gmail.archive", "gmail.batch_modify",
            "gmail.send_draft", "gmail.download_attachment",
            "gmail.generate_reply", "gmail.send_to_contact",
            "calendar.create_event", "calendar.update_event",
            "calendar.delete_event",
            "terminal_run", "file_write",
            "pc_hotkey", "pc_mouse_click", "clipboard_set",
        ]

        for name in must_confirm:
            tool = reg.get(name)
            assert tool is not None, f"Tool {name} not found"
            assert tool.requires_confirmation, f"{name} should require confirmation"

    def test_readonly_tools_no_confirmation(self):
        from bantz.agent.registry import build_default_registry
        reg = build_default_registry()

        no_confirm = [
            "browser_scan", "browser_info", "browser_detail",
            "file_read", "file_search",
            "gmail.list_labels", "gmail.list_drafts",
            "gmail.mark_read", "gmail.mark_unread",
            "contacts.list", "contacts.resolve",
            "project_info", "project_tree",
            "terminal_background_list",
        ]

        for name in no_confirm:
            tool = reg.get(name)
            assert tool is not None, f"Tool {name} not found"
            assert not tool.requires_confirmation, f"{name} should NOT require confirmation"
