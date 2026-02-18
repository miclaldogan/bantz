"""
Tests for RunTracker — observability layer.
Covers: schema, run tracking, tool call tracking, artifacts,
metrics queries, error handling, CLI reporter.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from bantz.data.run_tracker import (
    Artifact,
    Run,
    RunTracker,
    ToolCall,
    ToolCallHandle,
)
from bantz.data.metrics_reporter import MetricsReporter, _parse_period


@pytest.fixture
def tracker():
    t = RunTracker(db_path=":memory:")
    asyncio.get_event_loop().run_until_complete(t.initialise())
    yield t
    asyncio.get_event_loop().run_until_complete(t.close())


# ── Schema & Init ─────────────────────────────────────────────────

class TestInit:
    @pytest.mark.asyncio
    async def test_initialise_creates_tables(self, tracker):
        conn = tracker._ensure_conn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "runs" in tables
        assert "tool_calls" in tables
        assert "artifacts" in tables

    @pytest.mark.asyncio
    async def test_double_initialise_is_safe(self, tracker):
        await tracker.initialise()  # second call should not raise

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self):
        """WAL is set on file-based DBs; :memory: returns 'memory'."""
        import tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "test.db")
        t = RunTracker(db_path=path)
        await t.initialise()
        conn = t._ensure_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        await t.close()


# ── Run Tracking ──────────────────────────────────────────────────

class TestRunTracking:
    @pytest.mark.asyncio
    async def test_basic_run_tracking(self, tracker):
        async with tracker.track_run("merhaba") as run:
            run.route = "greeting"
            run.final_output = "Merhaba!"
            run.model = "qwen2.5-3b"

        saved = await tracker.get_run(run.run_id)
        assert saved is not None
        assert saved.user_input == "merhaba"
        assert saved.route == "greeting"
        assert saved.final_output == "Merhaba!"
        assert saved.status == "success"
        assert saved.latency_ms is not None
        assert saved.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_run_captures_latency(self, tracker):
        async with tracker.track_run("test") as run:
            await asyncio.sleep(0.05)  # 50ms

        saved = await tracker.get_run(run.run_id)
        assert saved.latency_ms >= 40  # allow some tolerance

    @pytest.mark.asyncio
    async def test_run_error_status(self, tracker):
        with pytest.raises(ValueError):
            async with tracker.track_run("fail") as run:
                raise ValueError("boom")

        saved = await tracker.get_run(run.run_id)
        assert saved.status == "error"
        assert "boom" in saved.error

    @pytest.mark.asyncio
    async def test_run_with_session_id(self, tracker):
        async with tracker.track_run("hi", session_id="sess-1") as run:
            pass

        saved = await tracker.get_run(run.run_id)
        assert saved.session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_run_tokens(self, tracker):
        async with tracker.track_run("count tokens") as run:
            run.total_tokens = 150
            run.model = "gemini-flash"

        saved = await tracker.get_run(run.run_id)
        assert saved.total_tokens == 150
        assert saved.model == "gemini-flash"


# ── Tool Call Tracking ────────────────────────────────────────────

class TestToolCallTracking:
    @pytest.mark.asyncio
    async def test_basic_tool_call(self, tracker):
        async with tracker.track_run("search email") as run:
            async with run.track_tool("gmail.search", {"query": "test"}) as tc:
                tc.set_result({"messages": [{"id": "m1"}]})

        calls = await tracker.get_tool_calls(run.run_id)
        assert len(calls) == 1
        assert calls[0].tool_name == "gmail.search"
        assert calls[0].status == "success"
        assert calls[0].result_hash is not None
        assert calls[0].result_summary is not None
        assert calls[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_tool_call_params_stored_as_json(self, tracker):
        async with tracker.track_run("test") as run:
            params = {"date": "2026-02-14", "count": 5}
            async with run.track_tool("calendar.list", params) as tc:
                tc.set_result([])

        calls = await tracker.get_tool_calls(run.run_id)
        stored_params = json.loads(calls[0].params)
        assert stored_params["date"] == "2026-02-14"
        assert stored_params["count"] == 5

    @pytest.mark.asyncio
    async def test_tool_call_error_via_exception(self, tracker):
        async with tracker.track_run("test") as run:
            try:
                async with run.track_tool("web.search", {"q": "test"}) as tc:
                    raise ConnectionError("timeout")
            except ConnectionError:
                pass

        calls = await tracker.get_tool_calls(run.run_id)
        assert calls[0].status == "error"
        assert "timeout" in calls[0].error

    @pytest.mark.asyncio
    async def test_tool_call_manual_error(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.send") as tc:
                tc.set_error("OAuth expired")

        calls = await tracker.get_tool_calls(run.run_id)
        assert calls[0].status == "error"
        assert calls[0].error == "OAuth expired"

    @pytest.mark.asyncio
    async def test_tool_call_skipped(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.send") as tc:
                tc.set_skipped("user denied")

        calls = await tracker.get_tool_calls(run.run_id)
        assert calls[0].status == "skipped"
        assert calls[0].error == "user denied"

    @pytest.mark.asyncio
    async def test_tool_call_confirmation(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.send") as tc:
                tc.set_confirmation("user_approved")
                tc.set_result("sent")

        calls = await tracker.get_tool_calls(run.run_id)
        assert calls[0].confirmation == "user_approved"

    @pytest.mark.asyncio
    async def test_tool_call_retry_count(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("web.fetch") as tc:
                tc.increment_retry()
                tc.increment_retry()
                tc.set_result("ok")

        calls = await tracker.get_tool_calls(run.run_id)
        assert calls[0].retry_count == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_run(self, tracker):
        async with tracker.track_run("complex query") as run:
            async with run.track_tool("gmail.search", {"q": "a"}) as tc1:
                tc1.set_result({"messages": []})
            async with run.track_tool("calendar.list") as tc2:
                tc2.set_result({"events": []})
            async with run.track_tool("web.search", {"q": "b"}) as tc3:
                tc3.set_result("results")

        calls = await tracker.get_tool_calls(run.run_id)
        assert len(calls) == 3
        names = [c.tool_name for c in calls]
        assert "gmail.search" in names
        assert "calendar.list" in names
        assert "web.search" in names

    @pytest.mark.asyncio
    async def test_result_hash_dedup(self, tracker):
        """Same result should produce the same hash."""
        result = {"messages": [{"id": "m1", "subject": "Test"}]}
        hashes = []
        async with tracker.track_run("test") as run:
            for _ in range(2):
                async with run.track_tool("gmail.search") as tc:
                    tc.set_result(result)
                    hashes.append(tc._tc.result_hash)

        assert hashes[0] == hashes[1]

    @pytest.mark.asyncio
    async def test_large_result_summary_truncated(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("web.fetch") as tc:
                big_result = "x" * 2000
                tc.set_result(big_result)

        calls = await tracker.get_tool_calls(run.run_id)
        assert len(calls[0].result_summary) <= 500


# ── Artifacts ─────────────────────────────────────────────────────

class TestArtifacts:
    @pytest.mark.asyncio
    async def test_save_and_get_artifact(self, tracker):
        async with tracker.track_run("summarize") as run:
            pass

        art = await tracker.save_artifact(
            run_id=run.run_id,
            artifact_type="summary",
            content="Bu bir özet.",
            title="Haftalık Rapor",
            mime_type="text/plain",
        )
        assert art.artifact_id is not None
        assert art.size_bytes == len("Bu bir özet.".encode())

        artifacts = await tracker.get_artifacts(run.run_id)
        assert len(artifacts) == 1
        assert artifacts[0].title == "Haftalık Rapor"
        assert artifacts[0].type == "summary"

    @pytest.mark.asyncio
    async def test_multiple_artifact_types(self, tracker):
        async with tracker.track_run("test") as run:
            pass

        await tracker.save_artifact(run.run_id, "summary", "Özet")
        await tracker.save_artifact(run.run_id, "transcript", "Konuşma kaydı")
        await tracker.save_artifact(run.run_id, "draft", "Taslak email")

        artifacts = await tracker.get_artifacts(run.run_id)
        assert len(artifacts) == 3
        types = {a.type for a in artifacts}
        assert types == {"summary", "transcript", "draft"}

    @pytest.mark.asyncio
    async def test_artifact_without_run(self, tracker):
        art = await tracker.save_artifact(
            run_id=None,
            artifact_type="report",
            content="Standalone report",
        )
        assert art.run_id is None


# ── Metrics: run_stats ────────────────────────────────────────────

class TestRunStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, tracker):
        stats = await tracker.run_stats()
        assert stats["total"] == 0
        assert stats["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_with_runs(self, tracker):
        for i in range(5):
            async with tracker.track_run(f"query {i}") as run:
                run.total_tokens = 100

        stats = await tracker.run_stats()
        assert stats["total"] == 5
        assert stats["success"] == 5
        assert stats["success_rate"] == 100.0
        assert stats["total_tokens"] == 500

    @pytest.mark.asyncio
    async def test_stats_with_errors(self, tracker):
        async with tracker.track_run("good") as run:
            pass
        try:
            async with tracker.track_run("bad") as run:
                raise RuntimeError("fail")
        except RuntimeError:
            pass

        stats = await tracker.run_stats()
        assert stats["total"] == 2
        assert stats["success"] == 1
        assert stats["errors"] == 1
        assert stats["success_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_stats_since_filter(self, tracker):
        async with tracker.track_run("old") as run:
            pass

        future_since = time.time() + 100
        stats = await tracker.run_stats(since=future_since)
        assert stats["total"] == 0


# ── Metrics: tool_stats ──────────────────────────────────────────

class TestToolStats:
    @pytest.mark.asyncio
    async def test_tool_stats(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.search") as tc:
                tc.set_result("ok")
            async with run.track_tool("gmail.search") as tc:
                tc.set_result("ok2")
            async with run.track_tool("calendar.list") as tc:
                tc.set_result("ok3")

        stats = await tracker.tool_stats()
        assert len(stats) == 2
        gmail = next(s for s in stats if s["tool_name"] == "gmail.search")
        assert gmail["calls"] == 2

    @pytest.mark.asyncio
    async def test_tool_error_rate(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("web.search") as tc:
                tc.set_result("ok")
            async with run.track_tool("web.search") as tc:
                tc.set_error("fail")

        stats = await tracker.tool_stats()
        web = stats[0]
        assert web["error_rate"] == 50.0


# ── Metrics: slow_tools ──────────────────────────────────────────

class TestSlowTools:
    @pytest.mark.asyncio
    async def test_no_slow_tools(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("fast.tool") as tc:
                tc.set_result("ok")

        slow = await tracker.slow_tools(threshold_ms=2000)
        assert slow == []


# ── Metrics: error_breakdown ──────────────────────────────────────

class TestErrorBreakdown:
    @pytest.mark.asyncio
    async def test_error_breakdown(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.send") as tc:
                tc.set_error("OAuth expired")
            async with run.track_tool("web.fetch") as tc:
                tc.set_error("Timeout")

        errors = await tracker.error_breakdown()
        assert len(errors) == 2
        tools = {e["tool_name"] for e in errors}
        assert "gmail.send" in tools
        assert "web.fetch" in tools

    @pytest.mark.asyncio
    async def test_error_breakdown_filter_by_tool(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.send") as tc:
                tc.set_error("err1")
            async with run.track_tool("web.fetch") as tc:
                tc.set_error("err2")

        errors = await tracker.error_breakdown(tool_name="gmail.send")
        assert len(errors) == 1
        assert errors[0]["tool_name"] == "gmail.send"


# ── Metrics: artifact_stats ──────────────────────────────────────

class TestArtifactStats:
    @pytest.mark.asyncio
    async def test_artifact_stats(self, tracker):
        await tracker.save_artifact(None, "summary", "a")
        await tracker.save_artifact(None, "summary", "b")
        await tracker.save_artifact(None, "transcript", "c")

        stats = await tracker.artifact_stats()
        assert stats["summary"] == 2
        assert stats["transcript"] == 1


# ── Listing ───────────────────────────────────────────────────────

class TestListing:
    @pytest.mark.asyncio
    async def test_list_runs(self, tracker):
        for i in range(3):
            async with tracker.track_run(f"q{i}", session_id="s1") as run:
                pass

        runs = await tracker.list_runs()
        assert len(runs) == 3

    @pytest.mark.asyncio
    async def test_list_runs_by_session(self, tracker):
        async with tracker.track_run("a", session_id="s1") as run:
            pass
        async with tracker.track_run("b", session_id="s2") as run:
            pass

        runs = await tracker.list_runs(session_id="s1")
        assert len(runs) == 1
        assert runs[0].session_id == "s1"

    @pytest.mark.asyncio
    async def test_list_runs_by_status(self, tracker):
        async with tracker.track_run("good") as run:
            pass
        try:
            async with tracker.track_run("bad") as run:
                raise RuntimeError("x")
        except RuntimeError:
            pass

        errors = await tracker.list_runs(status="error")
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_list_runs_pagination(self, tracker):
        for i in range(5):
            async with tracker.track_run(f"q{i}") as run:
                pass

        page1 = await tracker.list_runs(limit=2, offset=0)
        page2 = await tracker.list_runs(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].run_id != page2[0].run_id

    @pytest.mark.asyncio
    async def test_list_tool_calls_by_name(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("gmail.search") as tc:
                tc.set_result("ok")
            async with run.track_tool("calendar.list") as tc:
                tc.set_result("ok")

        gmail_calls = await tracker.list_tool_calls_by_name("gmail.search")
        assert len(gmail_calls) == 1
        assert gmail_calls[0].tool_name == "gmail.search"


# ── Data Classes ──────────────────────────────────────────────────

class TestDataClasses:
    def test_run_to_dict(self):
        run = Run(run_id="r1", user_input="test", status="success")
        d = run.to_dict()
        assert d["run_id"] == "r1"
        assert d["status"] == "success"

    def test_tool_call_to_dict(self):
        tc = ToolCall(call_id="c1", run_id="r1", tool_name="gmail.send")
        d = tc.to_dict()
        assert d["call_id"] == "c1"
        assert d["tool_name"] == "gmail.send"

    def test_artifact_to_dict(self):
        art = Artifact(artifact_id="a1", type="summary", content="hello")
        d = art.to_dict()
        assert d["artifact_id"] == "a1"
        assert d["type"] == "summary"


# ── MetricsReporter ──────────────────────────────────────────────

class TestMetricsReporter:
    @pytest.mark.asyncio
    async def test_empty_report(self, tracker):
        reporter = MetricsReporter(tracker)
        text = await reporter.generate_report(period_hours=24)
        assert "Bantz Metrics" in text
        assert "Total" in text

    @pytest.mark.asyncio
    async def test_report_with_data(self, tracker):
        async with tracker.track_run("hello") as run:
            run.model = "qwen2.5"
            run.total_tokens = 100
            async with run.track_tool("gmail.search", {"q": "test"}) as tc:
                tc.set_result({"messages": []})

        await tracker.save_artifact(run.run_id, "summary", "Özet")

        reporter = MetricsReporter(tracker)
        text = await reporter.generate_report(period_hours=24)
        assert "gmail.search" in text
        assert "Successful" in text

    @pytest.mark.asyncio
    async def test_report_with_errors(self, tracker):
        async with tracker.track_run("test") as run:
            async with run.track_tool("web.fetch") as tc:
                tc.set_error("Timeout")

        reporter = MetricsReporter(tracker)
        text = await reporter.generate_report(period_hours=24)
        assert "Errors" in text or "Recent Errors" in text


# ── Period Parsing ────────────────────────────────────────────────

class TestPeriodParsing:
    def test_parse_hours(self):
        assert _parse_period("24h") == 24.0

    def test_parse_days(self):
        assert _parse_period("7d") == 168.0

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            _parse_period("abc")
