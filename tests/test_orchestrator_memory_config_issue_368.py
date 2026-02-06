from __future__ import annotations

from unittest.mock import Mock

from bantz.brain.orchestrator_loop import OrchestratorConfig, OrchestratorLoop


def test_memory_lite_config_defaults():
    config = OrchestratorConfig()

    assert config.memory_max_tokens == 1000
    assert config.memory_max_turns == 10
    assert config.memory_pii_filter is True


def test_memory_lite_config_override_applied():
    planner_llm = Mock()
    planner_llm.complete_text = Mock(return_value="{}")
    tools = Mock()

    config = OrchestratorConfig(
        memory_max_tokens=1500,
        memory_max_turns=12,
        memory_pii_filter=False,
        enable_safety_guard=False,
    )

    loop = OrchestratorLoop(
        orchestrator=Mock(),
        tools=tools,
        config=config,
    )

    assert loop.memory.max_tokens == 1500
    assert loop.memory.max_turns == 12
    assert loop.memory.pii_filter_enabled is False
