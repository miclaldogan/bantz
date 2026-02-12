"""Daemon CLI tests (Issue #853)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


class TestDaemonCLI:
    """Test daemon argument parsing and startup flow."""

    def test_default_args(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            mock_instance = MockServer.return_value
            mock_instance.run.side_effect = KeyboardInterrupt()
            result = main(["--session", "test_session"])
            MockServer.assert_called_once()
            call_kw = MockServer.call_args
            assert call_kw[1]["session_name"] == "test_session"

    def test_custom_policy_and_log(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            mock_instance = MockServer.return_value
            mock_instance.run.side_effect = KeyboardInterrupt()
            main(["--policy", "custom/policy.json", "--log", "custom/log.jsonl"])
            call_kw = MockServer.call_args
            assert call_kw[1]["policy_path"] == "custom/policy.json"
            assert call_kw[1]["log_path"] == "custom/log.jsonl"

    def test_init_browser_flag(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            mock_instance = MockServer.return_value
            mock_instance.run.side_effect = KeyboardInterrupt()
            mock_instance._init_browser = MagicMock()
            main(["--init-browser"])
            mock_instance._init_browser.assert_called_once()

    def test_no_browser_flag_skips_init(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            mock_instance = MockServer.return_value
            mock_instance.run.side_effect = KeyboardInterrupt()
            mock_instance._init_browser = MagicMock()
            main(["--no-browser", "--init-browser"])
            mock_instance._init_browser.assert_not_called()

    def test_server_error_returns_1(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            MockServer.side_effect = RuntimeError("boot fail")
            result = main([])
            assert result == 1

    def test_keyboard_interrupt_returns_0(self):
        from bantz.daemon import main
        with patch("bantz.daemon.BantzServer") as MockServer:
            mock_instance = MockServer.return_value
            mock_instance.run.side_effect = KeyboardInterrupt()
            result = main([])
            assert result == 0
