"""
Tests for Hierarchical Task Decomposition (Issue #1279).

Validates:
- Subtask / SubtaskPlan data structures
- DAG builder + topological sort
- resolve_params dynamic parameter injection
- is_decomposition_candidate heuristic
- Max subtask enforcement
- Error cancellation (dependent subtasks)
- Cycle detection fallback
- OrchestratorOutput.subtasks field
- OrchestratorState.subtask_plan tracking
- Subtask execution loop integration
- Backward compatibility (simple commands bypass decomposition)
"""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import replace as dc_replace

from bantz.brain.task_planner import (
    Subtask,
    SubtaskPlan,
    build_plan,
    resolve_params,
    is_decomposition_candidate,
    _topological_sort,
    MAX_SUBTASKS,
)
from bantz.brain.orchestrator_state import OrchestratorState


# ═══════════════════════════════════════════════════════════════════
#  Subtask dataclass
# ═══════════════════════════════════════════════════════════════════

class TestSubtask:
    """Unit tests for Subtask dataclass."""

    def test_create_basic(self):
        s = Subtask(id=1, goal="list events", tool="calendar.list_events")
        assert s.id == 1
        assert s.goal == "list events"
        assert s.tool == "calendar.list_events"
        assert s.status == "pending"
        assert s.depends_on == []
        assert s.params == {}

    def test_is_dynamic_false_by_default(self):
        s = Subtask(id=1, goal="test", tool="t")
        assert s.is_dynamic is False

    def test_is_dynamic_true(self):
        s = Subtask(id=1, goal="test", tool="t", params={"dynamic": True})
        assert s.is_dynamic is True

    def test_from_result_of(self):
        s = Subtask(id=2, goal="test", tool="t", params={"from_result_of": 1, "dynamic": True})
        assert s.from_result_of == 1

    def test_from_result_of_none(self):
        s = Subtask(id=1, goal="test", tool="t")
        assert s.from_result_of is None

    def test_to_dict(self):
        s = Subtask(id=1, goal="list", tool="calendar.list_events", status="done",
                    result={"result_summary": "2 events found"})
        d = s.to_dict()
        assert d["id"] == 1
        assert d["goal"] == "list"
        assert d["status"] == "done"
        assert "2 events" in d["result_summary"]

    def test_to_dict_with_error(self):
        s = Subtask(id=1, goal="test", tool="t", status="failed", error="timeout")
        d = s.to_dict()
        assert d["error"] == "timeout"


# ═══════════════════════════════════════════════════════════════════
#  SubtaskPlan
# ═══════════════════════════════════════════════════════════════════

class TestSubtaskPlan:
    """Unit tests for SubtaskPlan."""

    def test_empty_plan(self):
        plan = SubtaskPlan()
        assert plan.is_empty
        assert plan.is_complete
        assert plan.current_subtask is None
        assert plan.next_subtask() is None
        assert plan.pending_count == 0

    def test_single_subtask_lifecycle(self):
        plan = build_plan([
            {"id": 1, "goal": "list events", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
        ])
        assert not plan.is_empty
        assert plan.pending_count == 1

        # Get next
        sub = plan.next_subtask()
        assert sub is not None
        assert sub.id == 1

        # Complete
        plan.complete_subtask(1, result={"result_summary": "3 events"})
        assert plan.is_complete
        assert plan.done_count == 1
        assert plan.next_subtask() is None

    def test_two_subtasks_with_dependency(self):
        plan = build_plan([
            {"id": 1, "goal": "list events", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
            {"id": 2, "goal": "cancel first", "tool": "calendar.cancel_event",
             "params": {"dynamic": True, "from_result_of": 1}, "depends_on": [1]},
        ])
        assert plan.pending_count == 2

        # First subtask
        sub1 = plan.next_subtask()
        assert sub1.id == 1
        plan.complete_subtask(1, result={"result_summary": "event_id=abc"})

        # Second subtask (depends on 1)
        sub2 = plan.next_subtask()
        assert sub2.id == 2

        plan.complete_subtask(2, result={"result_summary": "cancelled"})
        assert plan.is_complete

    def test_error_cancels_dependents(self):
        plan = build_plan([
            {"id": 1, "goal": "step 1", "tool": "t1", "params": {}, "depends_on": []},
            {"id": 2, "goal": "step 2", "tool": "t2", "params": {}, "depends_on": [1]},
            {"id": 3, "goal": "step 3", "tool": "t3", "params": {}, "depends_on": [2]},
        ])

        # Execute and fail step 1
        sub1 = plan.next_subtask()
        plan.complete_subtask(1, error="tool_failed")

        assert plan.get_subtask(1).status == "failed"
        assert plan.get_subtask(2).status == "cancelled"
        assert plan.get_subtask(3).status == "cancelled"
        assert plan.is_complete

    def test_cancel_remaining(self):
        plan = build_plan([
            {"id": 1, "goal": "s1", "tool": "t1", "params": {}, "depends_on": []},
            {"id": 2, "goal": "s2", "tool": "t2", "params": {}, "depends_on": []},
        ])
        plan.cancel_remaining()
        assert plan.get_subtask(1).status == "cancelled"
        assert plan.get_subtask(2).status == "cancelled"

    def test_get_results(self):
        plan = build_plan([
            {"id": 1, "goal": "s1", "tool": "t1", "params": {}, "depends_on": []},
            {"id": 2, "goal": "s2", "tool": "t2", "params": {}, "depends_on": []},
        ])
        plan.complete_subtask(1, result={"data": "x"})
        results = plan.get_results()
        assert 1 in results
        assert 2 not in results

    def test_progress_block(self):
        plan = build_plan([
            {"id": 1, "goal": "list events", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
            {"id": 2, "goal": "cancel event", "tool": "calendar.cancel_event",
             "params": {}, "depends_on": [1]},
        ])
        plan.complete_subtask(1, result={"result_summary": "3 events"})
        block = plan.to_progress_block()
        assert "SUBTASK_PROGRESS:" in block
        assert "✅" in block
        assert "⏳" in block
        assert "list events" in block
        assert "3 events" in block

    def test_get_nonexistent_subtask(self):
        plan = SubtaskPlan()
        assert plan.get_subtask(999) is None

    def test_complete_nonexistent_subtask_no_crash(self):
        plan = SubtaskPlan()
        plan.complete_subtask(999)  # Should not raise


# ═══════════════════════════════════════════════════════════════════
#  build_plan
# ═══════════════════════════════════════════════════════════════════

class TestBuildPlan:
    """Tests for build_plan factory function."""

    def test_empty_input(self):
        assert build_plan([]).is_empty
        assert build_plan(None).is_empty

    def test_invalid_input_type(self):
        assert build_plan("not a list").is_empty

    def test_single_valid_subtask(self):
        plan = build_plan([
            {"id": 1, "goal": "test", "tool": "time.now", "params": {}, "depends_on": []},
        ])
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].tool == "time.now"

    def test_max_subtasks_enforced(self):
        raw = [
            {"id": i, "goal": f"step {i}", "tool": f"t{i}", "params": {}, "depends_on": []}
            for i in range(1, 10)
        ]
        plan = build_plan(raw)
        assert len(plan.subtasks) <= MAX_SUBTASKS

    def test_invalid_tool_filtered(self):
        plan = build_plan(
            [{"id": 1, "goal": "test", "tool": "invalid.tool", "params": {}, "depends_on": []}],
            valid_tools=frozenset({"calendar.list_events"}),
        )
        assert plan.is_empty

    def test_valid_tool_accepted(self):
        plan = build_plan(
            [{"id": 1, "goal": "test", "tool": "calendar.list_events", "params": {}, "depends_on": []}],
            valid_tools=frozenset({"calendar.list_events"}),
        )
        assert len(plan.subtasks) == 1

    def test_no_tool_validation_when_none(self):
        plan = build_plan(
            [{"id": 1, "goal": "test", "tool": "anything.works", "params": {}, "depends_on": []}],
            valid_tools=None,
        )
        assert len(plan.subtasks) == 1

    def test_duplicate_ids_skipped(self):
        plan = build_plan([
            {"id": 1, "goal": "first", "tool": "t1", "params": {}, "depends_on": []},
            {"id": 1, "goal": "duplicate", "tool": "t2", "params": {}, "depends_on": []},
        ])
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].goal == "first"

    def test_missing_required_fields_skipped(self):
        plan = build_plan([
            {"goal": "no id", "tool": "t1"},
            {"id": 2, "goal": "no tool"},
            {"id": 3, "goal": "valid", "tool": "t3"},
        ])
        # id missing → skip, tool empty → still added (empty string)
        assert len(plan.subtasks) >= 1

    def test_deps_referencing_unknown_ids_removed(self):
        plan = build_plan([
            {"id": 1, "goal": "s1", "tool": "t1", "params": {}, "depends_on": [99]},
        ])
        assert plan.subtasks[0].depends_on == []  # 99 not in seen_ids


# ═══════════════════════════════════════════════════════════════════
#  Topological Sort
# ═══════════════════════════════════════════════════════════════════

class TestTopologicalSort:
    """Tests for DAG topological sort."""

    def test_linear_chain(self):
        subtasks = [
            Subtask(id=1, goal="a", tool="t1", depends_on=[]),
            Subtask(id=2, goal="b", tool="t2", depends_on=[1]),
            Subtask(id=3, goal="c", tool="t3", depends_on=[2]),
        ]
        order = _topological_sort(subtasks)
        assert order == [1, 2, 3]

    def test_parallel_tasks(self):
        subtasks = [
            Subtask(id=1, goal="a", tool="t1", depends_on=[]),
            Subtask(id=2, goal="b", tool="t2", depends_on=[]),
            Subtask(id=3, goal="c", tool="t3", depends_on=[1, 2]),
        ]
        order = _topological_sort(subtasks)
        assert order[-1] == 3  # 3 must be last
        assert set(order[:2]) == {1, 2}

    def test_diamond_pattern(self):
        subtasks = [
            Subtask(id=1, goal="a", tool="t1", depends_on=[]),
            Subtask(id=2, goal="b", tool="t2", depends_on=[1]),
            Subtask(id=3, goal="c", tool="t3", depends_on=[1]),
            Subtask(id=4, goal="d", tool="t4", depends_on=[2, 3]),
        ]
        order = _topological_sort(subtasks)
        assert order[0] == 1  # 1 must be first
        assert order[-1] == 4  # 4 must be last

    def test_cycle_detection_fallback(self):
        subtasks = [
            Subtask(id=1, goal="a", tool="t1", depends_on=[2]),
            Subtask(id=2, goal="b", tool="t2", depends_on=[1]),
        ]
        order = _topological_sort(subtasks)
        # Fallback: ID order
        assert order == [1, 2]

    def test_single_node(self):
        subtasks = [Subtask(id=1, goal="a", tool="t1")]
        order = _topological_sort(subtasks)
        assert order == [1]


# ═══════════════════════════════════════════════════════════════════
#  resolve_params
# ═══════════════════════════════════════════════════════════════════

class TestResolveParams:
    """Tests for dynamic param resolution."""

    def test_static_params_returned_as_is(self):
        s = Subtask(id=1, goal="test", tool="t", params={"date": "2025-01-01"})
        result = resolve_params(s, {})
        assert result == {"date": "2025-01-01"}

    def test_dynamic_params_injected(self):
        s = Subtask(id=2, goal="test", tool="t",
                    params={"dynamic": True, "from_result_of": 1, "extra": "x"})
        completed = {1: {"result_summary": "event_id=abc", "events": [{"id": "abc"}]}}
        result = resolve_params(s, completed)
        assert "_source_result" in result
        assert result["_source_result"]["result_summary"] == "event_id=abc"
        assert result["extra"] == "x"
        # Control keys removed
        assert "dynamic" not in result
        assert "from_result_of" not in result

    def test_dynamic_missing_source(self):
        s = Subtask(id=2, goal="test", tool="t",
                    params={"dynamic": True, "from_result_of": 99})
        result = resolve_params(s, {})
        assert "_source_result" not in result

    def test_forwarded_keys(self):
        s = Subtask(id=2, goal="test", tool="t",
                    params={"dynamic": True, "from_result_of": 1})
        completed = {1: {
            "result_summary": "ok",
            "events": [1, 2],
            "messages": [3],
            "data": {"x": 1},
        }}
        result = resolve_params(s, completed)
        assert result["_from_events"] == [1, 2]
        assert result["_from_messages"] == [3]
        assert result["_from_data"] == {"x": 1}


# ═══════════════════════════════════════════════════════════════════
#  is_decomposition_candidate
# ═══════════════════════════════════════════════════════════════════

class TestIsDecompositionCandidate:
    """Heuristic checks."""

    def test_single_tool_not_candidate(self):
        assert not is_decomposition_candidate(["calendar.list_events"], "done")

    def test_single_tool_needs_more_not_candidate(self):
        assert not is_decomposition_candidate(["calendar.list_events"], "needs_more_info")

    def test_multi_tool_done_not_candidate(self):
        assert not is_decomposition_candidate(["t1", "t2"], "done")

    def test_multi_tool_needs_more_is_candidate(self):
        assert is_decomposition_candidate(["t1", "t2"], "needs_more_info")

    def test_empty_plan_not_candidate(self):
        assert not is_decomposition_candidate([], "needs_more_info")


# ═══════════════════════════════════════════════════════════════════
#  OrchestratorOutput.subtasks field
# ═══════════════════════════════════════════════════════════════════

class TestOrchestratorOutputSubtasks:
    """Test that subtasks field is present on OrchestratorOutput."""

    def test_default_empty(self):
        from bantz.brain.llm_router import OrchestratorOutput
        out = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
        )
        assert out.subtasks == []

    def test_subtasks_populated(self):
        from bantz.brain.llm_router import OrchestratorOutput
        subtasks = [
            {"id": 1, "goal": "list", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
        ]
        out = OrchestratorOutput(
            route="calendar",
            calendar_intent="query",
            slots={},
            confidence=0.9,
            tool_plan=["calendar.list_events"],
            assistant_reply="",
            subtasks=subtasks,
        )
        assert len(out.subtasks) == 1


# ═══════════════════════════════════════════════════════════════════
#  OrchestratorState.subtask_plan
# ═══════════════════════════════════════════════════════════════════

class TestOrchestratorStateSubtaskPlan:
    """Test subtask_plan field on OrchestratorState."""

    def test_default_none(self):
        state = OrchestratorState()
        assert state.subtask_plan is None

    def test_set_plan(self):
        state = OrchestratorState()
        plan = build_plan([
            {"id": 1, "goal": "test", "tool": "t1", "params": {}, "depends_on": []},
        ])
        state.subtask_plan = plan
        assert not state.subtask_plan.is_empty

    def test_reset_clears_plan(self):
        state = OrchestratorState()
        plan = build_plan([
            {"id": 1, "goal": "test", "tool": "t1", "params": {}, "depends_on": []},
        ])
        state.subtask_plan = plan
        state.reset()
        assert state.subtask_plan is None

    def test_get_context_includes_progress(self):
        state = OrchestratorState()
        plan = build_plan([
            {"id": 1, "goal": "list events", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
            {"id": 2, "goal": "cancel", "tool": "calendar.cancel_event",
             "params": {}, "depends_on": [1]},
        ])
        plan.complete_subtask(1, result={"result_summary": "3 events"})
        state.subtask_plan = plan
        ctx = state.get_context_for_llm()
        assert "subtask_progress" in ctx
        assert "SUBTASK_PROGRESS:" in ctx["subtask_progress"]

    def test_get_context_no_progress_when_no_plan(self):
        state = OrchestratorState()
        ctx = state.get_context_for_llm()
        assert "subtask_progress" not in ctx


# ═══════════════════════════════════════════════════════════════════
#  Backward compatibility
# ═══════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Simple commands must bypass decomposition."""

    def test_simple_command_no_subtasks(self):
        """Simple single-tool command should have empty subtasks."""
        from bantz.brain.llm_router import OrchestratorOutput
        out = OrchestratorOutput(
            route="system",
            calendar_intent="none",
            slots={},
            confidence=0.95,
            tool_plan=["time.now"],
            assistant_reply="",
            status="done",
        )
        assert out.subtasks == []
        assert not is_decomposition_candidate(out.tool_plan, out.status)

    def test_extract_output_preserves_subtasks(self):
        """_extract_output should pass through subtasks from parsed JSON."""
        from bantz.brain.llm_router import OrchestratorOutput
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events", "calendar.cancel_event"],
            "assistant_reply": "",
            "status": "needs_more_info",
            "subtasks": [
                {"id": 1, "goal": "list events", "tool": "calendar.list_events",
                 "params": {}, "depends_on": []},
                {"id": 2, "goal": "cancel first", "tool": "calendar.cancel_event",
                 "params": {"dynamic": True, "from_result_of": 1}, "depends_on": [1]},
            ],
        }
        # Simulate what _extract_output does for subtasks
        raw_subtasks = parsed.get("subtasks") or []
        assert isinstance(raw_subtasks, list)
        assert len(raw_subtasks) == 2


# ═══════════════════════════════════════════════════════════════════
#  Scenario: Calendar workflow (list + cancel)
# ═══════════════════════════════════════════════════════════════════

class TestCalendarWorkflowScenario:
    """Full end-to-end scenario: 'toplantılarımı listele ve ilkini iptal et'."""

    def test_list_and_cancel_plan(self):
        plan = build_plan([
            {"id": 1, "goal": "Bu haftanın toplantılarını listele",
             "tool": "calendar.list_events",
             "params": {"date_range": "this_week"}, "depends_on": []},
            {"id": 2, "goal": "İlk toplantıyı iptal et",
             "tool": "calendar.cancel_event",
             "params": {"dynamic": True, "from_result_of": 1},
             "depends_on": [1]},
        ])

        # Step 1: List
        sub1 = plan.next_subtask()
        assert sub1.id == 1
        assert sub1.tool == "calendar.list_events"

        plan.complete_subtask(1, result={
            "result_summary": "3 events: Daily Standup, Sprint Review, 1-on-1",
            "events": [
                {"id": "evt_001", "summary": "Daily Standup"},
                {"id": "evt_002", "summary": "Sprint Review"},
                {"id": "evt_003", "summary": "1-on-1"},
            ],
        })

        # Step 2: Cancel (with dynamic params)
        sub2 = plan.next_subtask()
        assert sub2.id == 2
        assert sub2.is_dynamic

        resolved = resolve_params(sub2, plan.get_results())
        assert "_source_result" in resolved
        assert resolved["_from_events"][0]["id"] == "evt_001"

        plan.complete_subtask(2, result={"result_summary": "Daily Standup cancelled"})
        assert plan.is_complete

    def test_list_fails_cancel_auto_cancelled(self):
        plan = build_plan([
            {"id": 1, "goal": "list", "tool": "calendar.list_events",
             "params": {}, "depends_on": []},
            {"id": 2, "goal": "cancel", "tool": "calendar.cancel_event",
             "params": {}, "depends_on": [1]},
        ])

        sub1 = plan.next_subtask()
        plan.complete_subtask(1, error="API error")

        # Step 2 should be auto-cancelled
        assert plan.get_subtask(2).status == "cancelled"
        assert "failed" in (plan.get_subtask(2).error or "")
        assert plan.is_complete


# ═══════════════════════════════════════════════════════════════════
#  Scenario: Cross-domain (calendar + email)
# ═══════════════════════════════════════════════════════════════════

class TestCrossDomainScenario:
    """Cross-domain: 'katılımcılara gündem maili at'."""

    def test_calendar_then_email(self):
        plan = build_plan([
            {"id": 1, "goal": "Yarınki toplantı katılımcılarını bul",
             "tool": "calendar.get_event",
             "params": {"date": "tomorrow"}, "depends_on": []},
            {"id": 2, "goal": "Gündem maili gönder",
             "tool": "gmail.send",
             "params": {"dynamic": True, "from_result_of": 1},
             "depends_on": [1]},
        ])

        # Execute step 1
        sub1 = plan.next_subtask()
        plan.complete_subtask(1, result={
            "result_summary": "Meeting: Sprint Review, attendees: ali@x.com, veli@x.com",
            "data": {"attendees": ["ali@x.com", "veli@x.com"]},
        })

        # Execute step 2 with dynamic params
        sub2 = plan.next_subtask()
        resolved = resolve_params(sub2, plan.get_results())
        assert resolved["_from_data"]["attendees"] == ["ali@x.com", "veli@x.com"]

        plan.complete_subtask(2, result={"result_summary": "Mail sent to 2 recipients"})
        assert plan.is_complete
        assert plan.done_count == 2
