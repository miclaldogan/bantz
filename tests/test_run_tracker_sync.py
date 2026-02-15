"""
Tests for RunTracker sync API and orchestrator integration.

Covers:
- initialise_sync / start_run / end_run / record_tool_call
- OrchestratorLoop wiring (run_tracker param)
- process_turn observability hooks
"""

import asyncio
import json
import os
import tempfile
import time

import pytest

from bantz.data.run_tracker import RunTracker, Run, ToolCall


# ── Helpers ───────────────────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path):
    """Return a fresh RunTracker using a temp file DB."""
    db = str(tmp_path / "test_obs.db")
    t = RunTracker(db_path=db)
    t.initialise_sync()
    return t


# =====================================================================
# 1. Sync API unit tests
# =====================================================================


class TestInitialiseSync:
    def test_creates_db_and_tables(self, tmp_path):
        db = str(tmp_path / "obs.db")
        t = RunTracker(db_path=db)
        t.initialise_sync()
        conn = t._ensure_conn()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "runs" in tables
        assert "tool_calls" in tables
        assert "artifacts" in tables

    def test_wal_mode(self, tmp_path):
        db = str(tmp_path / "obs.db")
        t = RunTracker(db_path=db)
        t.initialise_sync()
        mode = t._ensure_conn().execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_double_init_idempotent(self, tmp_path):
        db = str(tmp_path / "obs.db")
        t = RunTracker(db_path=db)
        t.initialise_sync()
        t.initialise_sync()  # should not raise


class TestStartRun:
    def test_returns_run_with_pending_status(self, tracker):
        run = tracker.start_run("merhaba")
        assert isinstance(run, Run)
        assert run.status == "pending"
        assert run.user_input == "merhaba"
        assert run.run_id

    def test_run_persisted_in_db(self, tracker):
        run = tracker.start_run("test input")
        row = tracker._ensure_conn().execute(
            "SELECT status FROM runs WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "pending"

    def test_session_id_stored(self, tracker):
        run = tracker.start_run("hi", session_id="sess-42")
        assert run.session_id == "sess-42"
        row = tracker._ensure_conn().execute(
            "SELECT session_id FROM runs WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        assert row[0] == "sess-42"


class TestEndRun:
    def test_success_status(self, tracker):
        run = tracker.start_run("test")
        time.sleep(0.01)
        tracker.end_run(run)
        assert run.status == "success"
        assert run.latency_ms >= 0

    def test_explicit_error_status(self, tracker):
        run = tracker.start_run("test")
        run.error = "boom"
        tracker.end_run(run, status="error")
        assert run.status == "error"
        row = tracker._ensure_conn().execute(
            "SELECT status, error FROM runs WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        assert row[0] == "error"
        assert row[1] == "boom"

    def test_route_and_intent_persisted(self, tracker):
        run = tracker.start_run("yarın planlarım ne")
        run.route = "calendar"
        run.intent = "list_events"
        run.final_output = "Yarın 3 toplantın var."
        run.model = "qwen2.5-3b"
        tracker.end_run(run)
        row = tracker._ensure_conn().execute(
            "SELECT route, intent, final_output, model FROM runs WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()
        assert row[0] == "calendar"
        assert row[1] == "list_events"
        assert row[2] == "Yarın 3 toplantın var."
        assert row[3] == "qwen2.5-3b"


class TestRecordToolCall:
    def test_success_call(self, tracker):
        run = tracker.start_run("test")
        tc = tracker.record_tool_call(
            run_id=run.run_id,
            tool_name="calendar.list_events",
            params={"date": "tomorrow"},
            result={"events": [{"title": "standup"}]},
            latency_ms=123,
        )
        assert isinstance(tc, ToolCall)
        assert tc.status == "success"
        assert tc.tool_name == "calendar.list_events"
        assert tc.latency_ms == 123
        assert tc.result_hash is not None
        assert tc.result_summary is not None

    def test_error_call(self, tracker):
        run = tracker.start_run("test")
        tc = tracker.record_tool_call(
            run_id=run.run_id,
            tool_name="gmail.send",
            error="Connection refused",
            latency_ms=50,
        )
        assert tc.status == "error"
        assert tc.error == "Connection refused"
        assert tc.result_hash is None

    def test_persisted_in_db(self, tracker):
        run = tracker.start_run("test")
        tc = tracker.record_tool_call(
            run_id=run.run_id,
            tool_name="system.uptime",
            result="42 days",
            latency_ms=5,
        )
        row = tracker._ensure_conn().execute(
            "SELECT tool_name, status, latency_ms FROM tool_calls WHERE call_id = ?",
            (tc.call_id,),
        ).fetchone()
        assert row[0] == "system.uptime"
        assert row[1] == "success"
        assert row[2] == 5

    def test_confirmation_field(self, tracker):
        run = tracker.start_run("test")
        tc = tracker.record_tool_call(
            run_id=run.run_id,
            tool_name="calendar.delete_event",
            result="ok",
            confirmation="user_approved",
        )
        assert tc.confirmation == "user_approved"

    def test_params_serialised_as_json(self, tracker):
        run = tracker.start_run("test")
        tc = tracker.record_tool_call(
            run_id=run.run_id,
            tool_name="calendar.create_event",
            params={"title": "Standup", "date": "2025-01-15"},
            result="ok",
        )
        assert tc.params is not None
        parsed = json.loads(tc.params)
        assert parsed["title"] == "Standup"

    def test_multiple_tool_calls_for_one_run(self, tracker):
        run = tracker.start_run("composit query")
        tracker.record_tool_call(
            run_id=run.run_id, tool_name="calendar.list_events", result="ok"
        )
        tracker.record_tool_call(
            run_id=run.run_id, tool_name="gmail.unread_count", result="3"
        )
        tracker.record_tool_call(
            run_id=run.run_id, tool_name="system.uptime", result="5d"
        )
        rows = tracker._ensure_conn().execute(
            "SELECT COUNT(*) FROM tool_calls WHERE run_id = ?", (run.run_id,)
        ).fetchone()
        assert rows[0] == 3


class TestSyncAsyncParity:
    """Verify sync and async APIs write to the same DB."""

    def test_sync_run_readable_via_async(self, tracker):
        """start_run (sync) → get_run (async) should find the same row."""
        run = tracker.start_run("parity test", session_id="s1")
        run.route = "system"
        tracker.end_run(run)

        # Read via async API
        fetched = asyncio.get_event_loop().run_until_complete(
            tracker.get_run(run.run_id)
        )
        assert fetched is not None
        assert fetched.route == "system"
        assert fetched.status == "success"

    def test_sync_tool_call_readable_via_async(self, tracker):
        run = tracker.start_run("parity")
        tracker.record_tool_call(
            run_id=run.run_id, tool_name="test.tool", result="ok", latency_ms=10
        )
        calls = asyncio.get_event_loop().run_until_complete(
            tracker.get_tool_calls(run.run_id)
        )
        assert len(calls) == 1
        assert calls[0].tool_name == "test.tool"


# =====================================================================
# 2. OrchestratorLoop integration
# =====================================================================


class TestOrchestratorLoopWiring:
    """Verify OrchestratorLoop accepts and stores run_tracker."""

    def test_accepts_run_tracker_param(self, tracker):
        from unittest.mock import Mock
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        orch = Mock()
        tools = Mock()
        tools.names = Mock(return_value=[])
        loop = OrchestratorLoop(
            orchestrator=orch,
            tools=tools,
            run_tracker=tracker,
        )
        assert loop.run_tracker is tracker

    def test_none_by_default(self):
        from unittest.mock import Mock
        from bantz.brain.orchestrator_loop import OrchestratorLoop

        orch = Mock()
        tools = Mock()
        tools.names = Mock(return_value=[])
        loop = OrchestratorLoop(
            orchestrator=orch,
            tools=tools,
        )
        assert loop.run_tracker is None


class TestProcessTurnObservability:
    """Test that process_turn records runs and tool calls via RunTracker."""

    @pytest.fixture
    def loop_with_tracker(self, tracker):
        """Build a minimal OrchestratorLoop with a real RunTracker and mocked LLM."""
        from unittest.mock import Mock, patch, MagicMock
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_llm = Mock()
        mock_llm.complete_text = Mock(return_value="planned")
        orch = JarvisLLMOrchestrator(llm_client=mock_llm)

        tools = Mock()
        tools.names = Mock(return_value=[])

        loop = OrchestratorLoop(
            orchestrator=orch,
            tools=tools,
            run_tracker=tracker,
        )
        return loop

    def test_smalltalk_turn_records_run(self, loop_with_tracker, tracker):
        """A prerouted smalltalk turn should still record a run."""
        from unittest.mock import patch
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.orchestrator_loop import OrchestratorState

        preroute_output = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.99,
            tool_plan=[],
            assistant_reply="Merhaba efendim!",
            raw_output={"preroute_complete": True},
        )

        with patch.object(
            loop_with_tracker, "_llm_planning_phase", return_value=preroute_output
        ), patch.object(
            loop_with_tracker, "_update_state_phase"
        ):
            state = OrchestratorState()
            output, _ = loop_with_tracker.process_turn("merhaba", state)

        # Verify run was recorded
        conn = tracker._ensure_conn()
        runs = conn.execute("SELECT * FROM runs").fetchall()
        assert len(runs) == 1
        run_row = runs[0]
        assert run_row[1] == "merhaba"  # user_input
        assert run_row[2] == "smalltalk"  # route
        assert run_row[8] == "success"  # status

    def test_tool_turn_records_tool_calls(self, loop_with_tracker, tracker):
        """A turn with tool execution should record both run and tool calls."""
        from unittest.mock import patch, Mock
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.orchestrator_loop import OrchestratorState

        plan_output = OrchestratorOutput(
            route="calendar",
            calendar_intent="list_events",
            slots={"date": "tomorrow"},
            confidence=0.92,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            raw_output={},
        )

        tool_results = [
            {
                "tool": "calendar.list_events",
                "success": True,
                "raw_result": {"events": [{"title": "standup"}]},
                "result_summary": '{"events": [{"title": "standup"}]}',
                "error": None,
                "params": {"date": "tomorrow"},
                "elapsed_ms": 150,
            }
        ]

        final_output = OrchestratorOutput(
            route="calendar",
            calendar_intent="list_events",
            slots={"date": "tomorrow"},
            confidence=0.92,
            tool_plan=["calendar.list_events"],
            assistant_reply="Yarın 1 toplantın var: standup.",
            raw_output={},
        )

        with patch.object(
            loop_with_tracker, "_llm_planning_phase", return_value=plan_output
        ), patch.object(
            loop_with_tracker, "_react_execute_loop", return_value=tool_results
        ), patch.object(
            loop_with_tracker, "_reflection_phase"
        ), patch.object(
            loop_with_tracker, "_llm_finalization_phase", return_value=final_output
        ), patch.object(
            loop_with_tracker, "_update_state_phase"
        ):
            state = OrchestratorState()
            output, _ = loop_with_tracker.process_turn(
                "yarın toplantılarım ne", state
            )

        conn = tracker._ensure_conn()

        # Verify run
        runs = conn.execute("SELECT * FROM runs").fetchall()
        assert len(runs) == 1
        run_row = runs[0]
        assert run_row[2] == "calendar"  # route
        assert run_row[3] == "list_events"  # intent
        assert "toplantın var" in (run_row[4] or "")  # final_output
        assert run_row[8] == "success"  # status

        # Verify tool call
        tcs = conn.execute("SELECT * FROM tool_calls").fetchall()
        assert len(tcs) == 1
        tc_row = tcs[0]
        assert tc_row[2] == "calendar.list_events"  # tool_name
        assert tc_row[7] == "success"  # status
        assert tc_row[6] == 150  # latency_ms

    def test_error_turn_records_error_status(self, loop_with_tracker, tracker):
        """If process_turn raises, the run should be recorded with error status."""
        from unittest.mock import patch
        from bantz.brain.orchestrator_loop import OrchestratorState

        with patch.object(
            loop_with_tracker,
            "_llm_planning_phase",
            side_effect=RuntimeError("LLM down"),
        ), patch.object(
            loop_with_tracker, "_update_state_phase"
        ):
            state = OrchestratorState()
            output, _ = loop_with_tracker.process_turn("test", state)
            # Should return fallback, not raise
            assert output.route == "unknown"

        conn = tracker._ensure_conn()
        runs = conn.execute("SELECT status, error FROM runs").fetchall()
        assert len(runs) == 1
        assert runs[0][0] == "error"
        assert "LLM down" in runs[0][1]

    def test_pending_confirmation_skipped_in_tool_recording(
        self, loop_with_tracker, tracker
    ):
        """Tool results with pending_confirmation should NOT be recorded as tool calls."""
        from unittest.mock import patch
        from bantz.brain.llm_router import OrchestratorOutput
        from bantz.brain.orchestrator_loop import OrchestratorState

        plan_output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.create_event"],
            assistant_reply="",
            raw_output={},
        )

        tool_results = [
            {
                "tool": "calendar.create_event",
                "success": False,
                "pending_confirmation": True,
                "confirmation_prompt": "Etkinlik oluşturulsun mu?",
            }
        ]

        final_output = OrchestratorOutput(
            route="calendar",
            calendar_intent="create",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.create_event"],
            assistant_reply="Etkinlik oluşturulsun mu?",
            requires_confirmation=True,
            raw_output={},
        )

        with patch.object(
            loop_with_tracker, "_llm_planning_phase", return_value=plan_output
        ), patch.object(
            loop_with_tracker, "_react_execute_loop", return_value=tool_results
        ), patch.object(
            loop_with_tracker, "_reflection_phase"
        ), patch.object(
            loop_with_tracker, "_llm_finalization_phase", return_value=final_output
        ), patch.object(
            loop_with_tracker, "_update_state_phase"
        ):
            state = OrchestratorState()
            loop_with_tracker.process_turn("toplantı oluştur", state)

        conn = tracker._ensure_conn()
        tcs = conn.execute("SELECT * FROM tool_calls").fetchall()
        assert len(tcs) == 0  # No tool call recorded for pending confirmation

    def test_no_tracker_does_not_crash(self):
        """process_turn should work fine when run_tracker is None."""
        from unittest.mock import Mock, patch
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorState
        from bantz.brain.llm_router import JarvisLLMOrchestrator, OrchestratorOutput

        mock_llm = Mock()
        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        tools = Mock()
        tools.names = Mock(return_value=[])

        loop = OrchestratorLoop(
            orchestrator=orch,
            tools=tools,
            run_tracker=None,
        )

        preroute = OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=0.99,
            tool_plan=[],
            assistant_reply="OK",
            raw_output={"preroute_complete": True},
        )

        with patch.object(
            loop, "_llm_planning_phase", return_value=preroute
        ), patch.object(loop, "_update_state_phase"):
            state = OrchestratorState()
            output, _ = loop.process_turn("hey", state)
            assert output.assistant_reply == "OK"
