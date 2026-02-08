"""Tests for Issue #520 + #588 — Runtime banner + turn trace.

Covers RuntimeBanner, format_banner, TurnTraceRecord, TurnTrace,
and boot-banner diagnostics (active path, vLLM URL, forced tier).
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest import mock

import pytest


# ── RuntimeBanner ─────────────────────────────────────────────

class TestRuntimeBanner:
    def test_defaults(self):
        from bantz.brain.runtime_banner import RuntimeBanner
        b = RuntimeBanner()
        assert b.mode == "orchestrator"
        assert b.active_path == "brain"
        assert b.memory_turns == 10
        assert b.memory_tokens == 1000
        assert b.forced_tier == ""
        assert b.debug is False

    def test_from_runtime(self):
        from bantz.brain.runtime_banner import RuntimeBanner

        @dataclass
        class FakeConfig:
            memory_max_turns: int = 8
            memory_max_tokens: int = 800
            debug: bool = True

        class FakeLoop:
            config = FakeConfig()

        class FakeRuntime:
            router_model = "Qwen/Qwen2.5-3B-Instruct"
            gemini_model = "gemini-2.0-flash"
            finalizer_is_gemini = True
            loop = FakeLoop()
            tools = None
            router_client = None

        banner = RuntimeBanner.from_runtime(FakeRuntime())
        assert banner.finalizer_type == "Gemini"
        assert banner.finalizer_model == "gemini-2.0-flash"
        assert banner.finalizer_ok is True
        assert banner.memory_turns == 8
        assert banner.memory_tokens == 800
        assert banner.debug is True
        assert banner.router_model == "Qwen/Qwen2.5-3B-Instruct"
        assert banner.active_path == "brain"

    def test_from_runtime_no_gemini(self):
        from bantz.brain.runtime_banner import RuntimeBanner

        class FakeRuntime:
            router_model = "Qwen/Qwen2.5-3B-Instruct"
            gemini_model = ""
            finalizer_is_gemini = False
            loop = None
            tools = None
            router_client = None

        banner = RuntimeBanner.from_runtime(FakeRuntime())
        assert banner.finalizer_type == "3B (local)"
        assert banner.finalizer_ok is False

    def test_from_runtime_forced_tier(self):
        from bantz.brain.runtime_banner import RuntimeBanner

        class FakeRuntime:
            router_model = "Qwen/Qwen2.5-3B-Instruct"
            gemini_model = ""
            finalizer_is_gemini = False
            loop = None
            tools = None
            router_client = None

        with mock.patch.dict("os.environ", {"BANTZ_FORCE_FINALIZER_TIER": "quality"}):
            banner = RuntimeBanner.from_runtime(FakeRuntime())
        assert banner.forced_tier == "quality"

    def test_from_runtime_router_url_extraction(self):
        from bantz.brain.runtime_banner import RuntimeBanner

        class FakeClient:
            base_url = "http://gpu-box:8001"

        class FakeRuntime:
            router_model = "Qwen/Qwen2.5-3B-Instruct"
            gemini_model = ""
            finalizer_is_gemini = False
            loop = None
            tools = None
            router_client = FakeClient()

        banner = RuntimeBanner.from_runtime(FakeRuntime())
        assert banner.router_url == "http://gpu-box:8001"


# ── format_banner ─────────────────────────────────────────────

class TestFormatBanner:
    def test_contains_box_chars(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(
            router_model="Qwen/Qwen2.5-3B-Instruct",
            finalizer_model="gemini-2.0-flash",
            finalizer_ok=True,
        )
        text = format_banner(b)
        assert "╭" in text
        assert "╰" in text
        assert "BANTZ Brain" in text

    def test_contains_all_fields(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(
            mode="orchestrator",
            active_path="brain",
            router_model="Qwen/Qwen2.5-3B-Instruct",
            router_url="http://localhost:8001",
            finalizer_model="gemini-2.0-flash",
            finalizer_type="Gemini",
            finalizer_ok=True,
            memory_turns=10,
            memory_tokens=1000,
            tools_registered=5,
        )
        text = format_banner(b)
        assert "orchestrator" in text
        assert "brain (default)" in text
        assert "Qwen2.5-3B-Instruct" in text
        assert "http://localhost:8001" in text
        assert "gemini-2.0-flash" in text
        assert "10 turns" in text
        assert "1000tok" in text
        assert "5 registered" in text

    def test_legacy_path(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(active_path="legacy", mode="router")
        text = format_banner(b)
        assert "legacy" in text
        assert "brain (default)" not in text

    def test_forced_tier(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(forced_tier="quality")
        text = format_banner(b)
        assert "quality (forced)" in text

    def test_no_forced_tier(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(forced_tier="")
        text = format_banner(b)
        assert "Tier:" not in text

    def test_vllm_url_displayed(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(router_url="http://gpu-box:8001")
        text = format_banner(b)
        assert "http://gpu-box:8001" in text

    def test_debug_flag(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(debug=True)
        text = format_banner(b)
        assert "Debug" in text
        assert "ON" in text

    def test_no_debug_flag(self):
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner
        b = RuntimeBanner(debug=False)
        text = format_banner(b)
        assert "Debug" not in text


# ── TurnTraceRecord ───────────────────────────────────────────

class TestTurnTraceRecord:
    def test_basic_trace_line(self):
        from bantz.brain.runtime_banner import TurnTraceRecord
        r = TurnTraceRecord(
            turn_number=1,
            route="calendar",
            intent="query",
            confidence=0.92,
            prompt_tokens=1340,
            finalizer="gemini",
            tools_called=["calendar.list_events"],
            tools_ok=1,
            elapsed_s=1.2,
        )
        line = r.to_trace_line()
        assert "route=calendar" in line
        assert "intent=query" in line
        assert "conf=0.92" in line
        assert "prompt=1340tok" in line
        assert "finalizer=gemini" in line
        assert "calendar.list_events" in line
        assert "elapsed=1.20s" in line

    def test_prerouted(self):
        from bantz.brain.runtime_banner import TurnTraceRecord
        r = TurnTraceRecord(turn_number=2, prerouted=True, elapsed_s=0.01)
        line = r.to_trace_line()
        assert "prerouted=true" in line
        assert "route=" not in line

    def test_memory_in_trace(self):
        from bantz.brain.runtime_banner import TurnTraceRecord
        r = TurnTraceRecord(
            turn_number=3,
            memory_injected=True,
            memory_tokens=142,
            elapsed_s=0.5,
        )
        line = r.to_trace_line()
        assert "mem=142tok" in line

    def test_failed_tools(self):
        from bantz.brain.runtime_banner import TurnTraceRecord
        r = TurnTraceRecord(tools_ok=2, tools_failed=1, elapsed_s=0.3)
        line = r.to_trace_line()
        assert "fail=1" in line

    def test_tier(self):
        from bantz.brain.runtime_banner import TurnTraceRecord
        r = TurnTraceRecord(tier="quality", elapsed_s=0.3)
        line = r.to_trace_line()
        assert "tier=quality" in line


# ── TurnTrace ─────────────────────────────────────────────────

class TestTurnTrace:
    def test_accumulate_and_record(self):
        from bantz.brain.runtime_banner import TurnTrace
        trace = TurnTrace(turn_number=5, finalizer_name="gemini")
        trace.set_route("calendar", "query", 0.85)
        trace.set_prompt_tokens(1200)
        trace.set_tools(["calendar.list_events"], ok=1, failed=0)
        trace.set_memory(injected=True, tokens=100)
        trace.set_tier("quality")
        rec = trace.record()
        assert rec.turn_number == 5
        assert rec.route == "calendar"
        assert rec.confidence == 0.85
        assert rec.prompt_tokens == 1200
        assert rec.tools_called == ["calendar.list_events"]
        assert rec.tools_ok == 1
        assert rec.memory_injected is True
        assert rec.memory_tokens == 100
        assert rec.elapsed_s >= 0.0

    def test_prerouted(self):
        from bantz.brain.runtime_banner import TurnTrace
        trace = TurnTrace(turn_number=1)
        trace.set_prerouted()
        rec = trace.record()
        assert rec.prerouted is True

    def test_elapsed_positive(self):
        import time
        from bantz.brain.runtime_banner import TurnTrace
        trace = TurnTrace()
        time.sleep(0.01)
        rec = trace.record()
        assert rec.elapsed_s > 0


# ── File existence ────────────────────────────────────────────

class TestFileExistence:
    def test_runtime_banner_exists(self):
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        assert (ROOT / "src" / "bantz" / "brain" / "runtime_banner.py").is_file()


# ── Issue #588: Banner printed at startup ─────────────────────

class TestBannerPrintedAtStartup:
    """Verify format_banner() is actually called from create_runtime()."""

    def test_create_runtime_prints_banner(self):
        """create_runtime() should print the ASCII banner box."""
        from unittest.mock import patch, MagicMock
        import builtins

        printed = []
        original_print = builtins.print

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=capture_print):
            with patch.dict("os.environ", {
                "BANTZ_VLLM_URL": "http://test:8001",
                "BANTZ_VLLM_MODEL": "test-model",
                "GEMINI_API_KEY": "",
            }):
                try:
                    from bantz.brain.runtime_factory import create_runtime
                    runtime = create_runtime()
                except Exception:
                    pytest.skip("create_runtime requires live dependencies")

        banner_output = "\n".join(printed)
        assert "╭" in banner_output or "BANTZ Brain" in banner_output

    def test_legacy_banner_shows_legacy_path(self):
        """Legacy path banner should say 'legacy' not 'brain (default)'."""
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner

        b = RuntimeBanner(active_path="legacy", mode="router")
        text = format_banner(b)
        assert "legacy" in text
        assert "brain (default)" not in text
        assert "╭" in text
        assert "╰" in text

    def test_brain_banner_shows_brain_path(self):
        """Brain path banner should say 'brain (default)'."""
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner

        b = RuntimeBanner(active_path="brain")
        text = format_banner(b)
        assert "brain (default)" in text
        assert "Path:" in text

    def test_banner_includes_vllm_url(self):
        """Banner should show vLLM URL for quick confirmation."""
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner

        b = RuntimeBanner(router_url="http://192.168.1.100:8001")
        text = format_banner(b)
        assert "http://192.168.1.100:8001" in text
        assert "vLLM:" in text

    def test_banner_forced_tier_visible(self):
        """If BANTZ_FORCE_FINALIZER_TIER is set, banner should show it."""
        from bantz.brain.runtime_banner import RuntimeBanner, format_banner

        b = RuntimeBanner(forced_tier="fast")
        text = format_banner(b)
        assert "fast (forced)" in text
        assert "Tier:" in text
