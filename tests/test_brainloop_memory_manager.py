from __future__ import annotations

import pytest
import asyncio


class CapturingRouter:
    """Router stub that captures prompt content via MockLLM-like behavior."""

    def __init__(self):
        self.last_retrieved_memory: str | None = None
        self.called = False

    def route(self, *, user_input: str, dialog_summary=None, retrieved_memory=None, session_context=None):
        self.called = True
        self.last_retrieved_memory = retrieved_memory
        # Return a smalltalk reply so BrainLoop returns immediately.
        from bantz.brain.llm_router import OrchestratorOutput

        return OrchestratorOutput(
            route="smalltalk",
            calendar_intent="none",
            slots={},
            confidence=1.0,
            tool_plan=[],
            assistant_reply="Tamam efendim.",
            raw_output={},
        )


def test_brainloop_injects_retrieved_memory_into_router_prompt():
    from bantz.agent.tools import ToolRegistry
    from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
    from bantz.memory.snippet_manager import create_memory_manager
    from bantz.memory.snippet_store import InMemoryStore

    mm = create_memory_manager(
        session_store=InMemoryStore(),
        profile_store=InMemoryStore(),
        episodic_store=InMemoryStore(),
    )

    # Seed a profile memory that should be recalled.
    asyncio.run(mm.remember_profile("Kullanıcı kısa cevap ister", source="test"))

    # Sanity: recall should find it.
    recalled = asyncio.run(mm.recall(query="kısa cevap", limit=5))
    assert len(recalled) >= 1

    router = CapturingRouter()

    class _SayingLLM:
        def complete_json(self, *, messages, schema_hint):
            _ = messages
            _ = schema_hint
            return {"type": "SAY", "text": "Tamam efendim."}

    loop = BrainLoop(
        llm=_SayingLLM(),
        tools=ToolRegistry(),
        router=router,
        config=BrainLoopConfig(enable_memory_manager=False),
        memory_manager=mm,
    )

    res = loop.run(
        turn_input="kısa cevap",
        session_context={"session_id": "t1", "deterministic_render": True},
        context={},
    )

    assert res.kind == "say"
    assert router.called is True
    assert router.last_retrieved_memory is not None
    assert "PROFILE" in router.last_retrieved_memory
