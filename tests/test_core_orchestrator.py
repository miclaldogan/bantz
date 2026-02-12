"""Orchestrator unit tests (Issue #853).

Tests OrchestratorConfig, ComponentStatus, BantzOrchestrator state machine.
No real audio or browser — everything mocked.
"""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from bantz.core.orchestrator import (
    BantzOrchestrator,
    ComponentState,
    ComponentStatus,
    OrchestratorConfig,
    SystemState,
)


# ─────────────────────────────────────────────────────────────────
# OrchestratorConfig
# ─────────────────────────────────────────────────────────────────

class TestOrchestratorConfig:

    def test_defaults(self):
        cfg = OrchestratorConfig()
        assert cfg.session_name == "default"
        assert cfg.enable_wake_word is True
        assert cfg.enable_tts is True
        assert cfg.language == "tr"

    def test_custom_values(self):
        cfg = OrchestratorConfig(
            session_name="test",
            enable_wake_word=False,
            language="en",
            vllm_url="http://localhost:9000",
        )
        assert cfg.session_name == "test"
        assert cfg.enable_wake_word is False
        assert cfg.language == "en"
        assert cfg.vllm_url == "http://localhost:9000"

    def test_from_env(self):
        env = {
            "BANTZ_SESSION": "env_session",
            "BANTZ_WAKE_WORD": "0",
            "BANTZ_TTS": "0",
            "BANTZ_LANGUAGE": "en",
            "BANTZ_VLLM_MODEL": "custom-model",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = OrchestratorConfig.from_env()
            assert cfg.session_name == "env_session"
            assert cfg.enable_wake_word is False
            assert cfg.enable_tts is False
            assert cfg.language == "en"
            assert cfg.vllm_model == "custom-model"

    def test_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ["BANTZ_SESSION", "BANTZ_WAKE_WORD", "BANTZ_TTS"]:
                os.environ.pop(key, None)
            cfg = OrchestratorConfig.from_env()
            assert cfg.session_name == "default"
            assert cfg.enable_wake_word is True
            assert cfg.enable_tts is True

    def test_wake_words_default(self):
        cfg = OrchestratorConfig()
        assert "hey_jarvis" in cfg.wake_words


# ─────────────────────────────────────────────────────────────────
# ComponentStatus
# ─────────────────────────────────────────────────────────────────

class TestComponentStatus:

    def test_initial_state(self):
        cs = ComponentStatus(name="server")
        assert cs.state == ComponentState.STOPPED
        assert cs.is_running is False
        assert cs.error is None

    def test_running_state(self):
        cs = ComponentStatus(name="tts", state=ComponentState.RUNNING, started_at=time.time())
        assert cs.is_running is True
        assert cs.uptime_seconds >= 0

    def test_error_state(self):
        cs = ComponentStatus(name="asr", state=ComponentState.ERROR, error="mic not found")
        assert cs.is_running is False
        assert cs.error == "mic not found"

    def test_uptime_zero_when_not_started(self):
        cs = ComponentStatus(name="overlay")
        assert cs.uptime_seconds == 0.0

    def test_to_dict(self):
        cs = ComponentStatus(name="server", state=ComponentState.RUNNING, started_at=time.time())
        d = cs.to_dict()
        assert d["name"] == "server"
        assert d["state"] == "running"
        assert "uptime" in d


# ─────────────────────────────────────────────────────────────────
# BantzOrchestrator — State & Properties
# ─────────────────────────────────────────────────────────────────

class TestOrchestratorState:

    def test_initial_state(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        assert orch.state == SystemState.OFFLINE
        assert orch.is_running is False
        assert orch.is_ready is False

    def test_get_status(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        status = orch.get_status()
        assert status["state"] == "offline"
        assert status["running"] is False
        assert "components" in status
        assert "server" in status["components"]

    def test_set_state(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        orch._set_state(SystemState.BOOTING)
        assert orch.state == SystemState.BOOTING

    def test_set_state_callback(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        states = []
        orch._on_state_change.append(lambda s: states.append(s))
        orch._set_state(SystemState.BOOTING)
        orch._set_state(SystemState.READY)
        assert states == [SystemState.BOOTING, SystemState.READY]

    def test_set_state_no_duplicate(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        states = []
        orch._on_state_change.append(lambda s: states.append(s))
        orch._set_state(SystemState.READY)
        orch._set_state(SystemState.READY)
        assert len(states) == 1

    def test_set_component_state(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        orch._set_component_state("server", ComponentState.RUNNING)
        assert orch._component_status["server"].state == ComponentState.RUNNING
        assert orch._component_status["server"].started_at is not None

    def test_set_component_state_error(self):
        orch = BantzOrchestrator(config=OrchestratorConfig())
        orch._set_component_state("asr", ComponentState.ERROR, error="mic fail")
        assert orch._component_status["asr"].error == "mic fail"


# ─────────────────────────────────────────────────────────────────
# SystemState & ComponentState enums
# ─────────────────────────────────────────────────────────────────

class TestEnums:

    def test_system_states(self):
        assert SystemState.OFFLINE.name == "OFFLINE"
        assert SystemState.BOOTING.name == "BOOTING"
        assert SystemState.READY.name == "READY"
        assert SystemState.LISTENING.name == "LISTENING"
        assert SystemState.PROCESSING.name == "PROCESSING"
        assert SystemState.SPEAKING.name == "SPEAKING"
        assert SystemState.ERROR.name == "ERROR"

    def test_component_states(self):
        assert ComponentState.STOPPED.name == "STOPPED"
        assert ComponentState.STARTING.name == "STARTING"
        assert ComponentState.RUNNING.name == "RUNNING"
        assert ComponentState.ERROR.name == "ERROR"
        assert ComponentState.STOPPING.name == "STOPPING"
