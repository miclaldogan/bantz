"""Tests for Issue #1385: system tools crash fixes.

Covers:
1. system.status naming (was system.info) — registration, TOOL_REMAP
2. system.volume tool — get/set/up/down/mute/unmute + error handling
3. time_now_tool defensive exception handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── 1. system.status  naming alignment ──────────────────────────────

class TestSystemStatusNaming:
    """system.info → system.status rename (Issue #1385)."""

    def test_system_status_registered_not_info(self):
        """system.status is registered; system.info is NOT."""
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import register_all_tools
        reg = ToolRegistry()
        register_all_tools(reg)
        assert reg.get("system.status") is not None, "system.status should be registered"
        assert reg.get("system.info") is None, "system.info should NOT be registered"

    def test_tool_remap_maps_info_to_status(self):
        """TOOL_REMAP bridges legacy system.info → system.status."""
        from bantz.brain.tool_plan_sanitizer import TOOL_REMAP
        assert ("system.info", "*") in TOOL_REMAP
        assert TOOL_REMAP[("system.info", "*")] == "system.status"

    def test_valid_tools_contains_system_status(self):
        """_VALID_TOOLS includes system.status."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert "system.status" in JarvisLLMOrchestrator._VALID_TOOLS

    def test_valid_tools_contains_system_volume(self):
        """_VALID_TOOLS includes system.volume."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert "system.volume" in JarvisLLMOrchestrator._VALID_TOOLS

    def test_tool_lookup_has_system_volume(self):
        """_TOOL_LOOKUP maps (system, volume) → system.volume."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        assert JarvisLLMOrchestrator._TOOL_LOOKUP[("system", "volume")] == "system.volume"


# ── 2. system.volume tool ───────────────────────────────────────────

class TestSystemVolumeTool:
    """system_volume_tool tests (Issue #1385)."""

    def test_no_pactl_returns_error(self):
        """Returns error when pactl is not installed."""
        from bantz.tools.system_tools import system_volume_tool
        with patch("bantz.tools.system_tools.shutil.which", return_value=None):
            result = system_volume_tool()
            assert result["ok"] is False
            assert "pactl" in result["error"]

    def test_get_volume_parses_output(self):
        """Parses pactl get-sink-volume output correctly."""
        from bantz.tools.system_tools import system_volume_tool
        vol_output = "Volume: front-left: 42000 /  64% / -11.74 dB,   front-right: 42000 /  64% / -11.74 dB"
        mute_output = "Mute: no"

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 0
            if "get-sink-volume" in cmd:
                result.stdout = vol_output
            elif "get-sink-mute" in cmd:
                result.stdout = mute_output
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run):
                result = system_volume_tool(action="get")
                assert result["ok"] is True
                assert result["volume"] == 64
                assert result["muted"] is False

    def test_set_volume_calls_pactl(self):
        """set action calls pactl with correct percentage."""
        from bantz.tools.system_tools import system_volume_tool

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            if "get-sink-volume" in cmd:
                result.stdout = "Volume: front-left: 32768 /  50% / -18.06 dB"
            elif "get-sink-mute" in cmd:
                result.stdout = "Mute: no"
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run) as mock_run:
                result = system_volume_tool(action="set", level=75)
                assert result["ok"] is True
                # Check that set-sink-volume was called with 75%
                set_calls = [c for c in mock_run.call_args_list
                             if "set-sink-volume" in c[0][0]]
                assert len(set_calls) == 1
                assert "75%" in set_calls[0][0][0]

    def test_set_volume_clamps_high(self):
        """Clamps volume to max 150%."""
        from bantz.tools.system_tools import system_volume_tool

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            if "get-sink-volume" in cmd:
                result.stdout = "Volume: front-left: 65536 / 100% / 0.00 dB"
            elif "get-sink-mute" in cmd:
                result.stdout = "Mute: no"
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run) as mock_run:
                result = system_volume_tool(action="set", level=200)
                assert result["ok"] is True
                set_calls = [c for c in mock_run.call_args_list
                             if "set-sink-volume" in c[0][0]]
                assert "150%" in set_calls[0][0][0]

    def test_mute_action(self):
        """mute action calls pactl set-sink-mute 1."""
        from bantz.tools.system_tools import system_volume_tool

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            if "get-sink-volume" in cmd:
                result.stdout = "Volume: front-left: 42000 /  64% / -11.74 dB"
            elif "get-sink-mute" in cmd:
                result.stdout = "Mute: yes"
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run) as mock_run:
                result = system_volume_tool(action="mute")
                assert result["ok"] is True
                mute_calls = [c for c in mock_run.call_args_list
                              if "set-sink-mute" in c[0][0]]
                assert len(mute_calls) == 1

    def test_unknown_action_returns_error(self):
        """Unknown action returns error, doesn't crash."""
        from bantz.tools.system_tools import system_volume_tool
        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            result = system_volume_tool(action="explode")
            assert result["ok"] is False
            assert "Unknown action" in result["error"]

    def test_subprocess_error_handled(self):
        """CalledProcessError is caught gracefully."""
        import subprocess as sp
        from bantz.tools.system_tools import system_volume_tool

        def fake_run(cmd, **kw):
            if "set-sink-volume" in cmd:
                raise sp.CalledProcessError(1, cmd, stderr="Connection refused")
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run):
                result = system_volume_tool(action="set", level=50)
                assert result["ok"] is False
                assert "pactl failed" in result["error"]

    def test_timeout_handled(self):
        """TimeoutExpired is caught gracefully."""
        import subprocess as sp
        from bantz.tools.system_tools import system_volume_tool

        def fake_run(cmd, **kw):
            if "set-sink-volume" in cmd:
                raise sp.TimeoutExpired(cmd, 5)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("bantz.tools.system_tools.shutil.which", return_value="/usr/bin/pactl"):
            with patch("bantz.tools.system_tools.subprocess.run", side_effect=fake_run):
                result = system_volume_tool(action="set", level=50)
                assert result["ok"] is False
                assert "timeout" in result["error"]


# ── 3. time_now_tool defensive handling ──────────────────────────────

class TestTimeNowDefensive:
    """time_now_tool should never crash even on broken timezone config."""

    def test_time_now_returns_ok(self):
        from bantz.tools.time_tools import time_now_tool
        result = time_now_tool()
        assert result["ok"] is True
        assert "now_iso" in result
        assert "epoch" in result

    def test_time_now_handles_exception(self):
        """If datetime raises, function returns error dict instead of crashing."""
        from bantz.tools.time_tools import time_now_tool
        with patch("bantz.tools.time_tools.datetime") as mock_dt:
            mock_dt.now.side_effect = OSError("timezone broken")
            result = time_now_tool()
            assert result["ok"] is False
            assert "error" in result


# ── 4. system.volume in policy & metadata ────────────────────────────

class TestSystemVolumePolicy:
    """system.volume should be safe in all policy layers."""

    def test_policy_json_has_system_volume(self):
        import json
        from pathlib import Path
        policy_path = Path(__file__).resolve().parent.parent / "config" / "policy.json"
        policy = json.loads(policy_path.read_text())
        tools = policy.get("tool_levels", {})
        assert tools.get("system.volume") == "safe"

    def test_metadata_has_system_volume(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("system.volume") == ToolRisk.SAFE

    def test_capability_model_has_system_volume(self):
        from bantz.security.capability_model import _TOOL_CAPABILITIES
        assert "system.volume" in _TOOL_CAPABILITIES
        cap = _TOOL_CAPABILITIES["system.volume"]
        assert cap.risk_level == "safe"


# ── 5. system.status in register_all ─────────────────────────────────

class TestSystemStatusRegistration:
    """system.status handler returns valid output."""

    def test_system_status_returns_ok(self):
        from bantz.tools.system_tools import system_status
        result = system_status()
        assert result["ok"] is True
        assert "loadavg" in result
        assert "memory" in result

    def test_system_volume_registered(self):
        """system.volume is registered in the tool registry."""
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import register_all_tools
        reg = ToolRegistry()
        register_all_tools(reg)
        assert reg.get("system.volume") is not None
