from __future__ import annotations

from bantz.brain.prompt_engineering import (
    PromptBuilder,
    compute_prompt_metrics,
    estimate_tokens,
)


def test_ab_variant_deterministic_with_seed():
    builder = PromptBuilder(token_budget=3500, experiment="test_exp")

    r1 = builder.build_finalizer_prompt(
        route="calendar",
        user_input="bugün neler var?",
        planner_decision={"route": "calendar", "calendar_intent": "query"},
        seed="session-123",
        session_context={"current_datetime": "2026-02-04T10:00:00+03:00", "session_id": "session-123"},
    )
    r2 = builder.build_finalizer_prompt(
        route="calendar",
        user_input="bugün neler var?",
        planner_decision={"route": "calendar", "calendar_intent": "query"},
        seed="session-123",
        session_context={"current_datetime": "2026-02-04T10:00:00+03:00", "session_id": "session-123"},
    )

    assert r1.variant == r2.variant
    assert r1.prompt == r2.prompt


def test_context_injection_datetime_and_location_present():
    builder = PromptBuilder(token_budget=3500, experiment="test_ctx")

    result = builder.build_finalizer_prompt(
        route="smalltalk",
        user_input="selam",
        planner_decision={"route": "smalltalk", "calendar_intent": "none"},
        seed="seed",
        session_context={
            "current_datetime": "2026-02-04T10:00:00+03:00",
            "location": "Kadıköy",
            "session_id": "seed",
        },
        dialog_summary="Kullanıcı daha önce takvim sormuştu.",
    )

    assert "SESSION_CONTEXT" in result.prompt
    assert "2026-02-04T10:00:00+03:00" in result.prompt
    assert "Kadıköy" in result.prompt

    m = compute_prompt_metrics(result.prompt)
    assert m["has_session_context"] is True
    assert m["has_user"] is True
    assert m["has_assistant"] is True


def test_token_trimming_under_budget():
    builder = PromptBuilder(token_budget=3500, experiment="test_trim")

    huge_tool_results = [{"tool": "x", "result": "A" * 20000, "success": True}]
    huge_summary = "S" * 20000

    result = builder.build_finalizer_prompt(
        route="gmail",
        user_input="bu maile kibar bir cevap yaz",
        planner_decision={"route": "gmail", "calendar_intent": "none", "tool_plan": ["gmail.get_message"]},
        tool_results=huge_tool_results,
        dialog_summary=huge_summary,
        recent_turns=[
            {"user": "önceki mesaj 1" * 200, "assistant": "cevap 1" * 200},
            {"user": "önceki mesaj 2" * 200, "assistant": "cevap 2" * 200},
        ],
        session_context={"current_datetime": "2026-02-04T10:00:00+03:00", "session_id": "seed"},
        seed="seed",
    )

    assert result.trimmed is True
    assert result.estimated_tokens <= 3500
    assert estimate_tokens(result.prompt) <= 3500

    m = compute_prompt_metrics(result.prompt)
    assert m["has_planner_decision"] is True
    assert m["has_tool_results"] is True  # likely still present but truncated
