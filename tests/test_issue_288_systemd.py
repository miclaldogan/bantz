"""Tests for Issue #288 — systemd autostart services.

Verifies service files exist, have correct structure, and env template is present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYSTEMD = ROOT / "systemd" / "user"


class TestServiceFiles:
    """Verify systemd unit files."""

    def test_core_service_exists(self):
        assert (SYSTEMD / "bantz-core.service").is_file()

    def test_voice_service_exists(self):
        assert (SYSTEMD / "bantz-voice.service").is_file()

    def test_target_exists(self):
        assert (SYSTEMD / "bantz.target").is_file()

    def test_core_has_restart(self):
        content = (SYSTEMD / "bantz-core.service").read_text()
        assert "Restart=on-failure" in content

    def test_core_has_env_file(self):
        content = (SYSTEMD / "bantz-core.service").read_text()
        assert "EnvironmentFile" in content

    def test_voice_requires_core(self):
        content = (SYSTEMD / "bantz-voice.service").read_text()
        assert "Requires=bantz-core.service" in content

    def test_voice_after_core(self):
        content = (SYSTEMD / "bantz-voice.service").read_text()
        assert "After=bantz-core.service" in content

    def test_target_wants_all(self):
        content = (SYSTEMD / "bantz.target").read_text()
        assert "bantz-core.service" in content
        assert "bantz-voice.service" in content

    def test_core_has_start_limit(self):
        content = (SYSTEMD / "bantz-core.service").read_text()
        assert "StartLimitBurst" in content

    def test_voice_has_restart_sec(self):
        content = (SYSTEMD / "bantz-voice.service").read_text()
        assert "RestartSec=3" in content


class TestEnvTemplate:
    """Verify environment file template."""

    def test_env_example_exists(self):
        assert (ROOT / "config" / "bantz-env.example").is_file()

    def test_env_has_vllm(self):
        content = (ROOT / "config" / "bantz-env.example").read_text()
        assert "BANTZ_VLLM_URL" in content

    def test_env_has_privacy(self):
        content = (ROOT / "config" / "bantz-env.example").read_text()
        assert "BANTZ_REDACT_PII" in content

    def test_env_has_wake_words(self):
        content = (ROOT / "config" / "bantz-env.example").read_text()
        assert "BANTZ_WAKE_WORDS" in content


class TestInstallScript:
    """Verify install script exists."""

    def test_install_script_exists(self):
        assert (ROOT / "scripts" / "install_services.sh").is_file()

    def test_install_script_executable(self):
        import os
        assert os.access(ROOT / "scripts" / "install_services.sh", os.X_OK)
