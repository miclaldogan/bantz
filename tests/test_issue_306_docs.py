"""Tests for Issue #306 — Boot Jarvis setup guide.

Verifies the documentation file exists and contains all required sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = ROOT / "docs" / "setup" / "boot-jarvis.md"


class TestBootJarvisGuide:
    """Verify Boot Jarvis setup guide completeness."""

    def test_file_exists(self):
        assert DOC_PATH.is_file(), "docs/setup/boot-jarvis.md missing"

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = DOC_PATH.read_text(encoding="utf-8")

    def test_has_prerequisites(self):
        assert "Gereksinimler" in self.content

    def test_has_vllm_setup(self):
        assert "vLLM Kurulumu" in self.content

    def test_has_vllm_gpu(self):
        assert "GPU ile" in self.content

    def test_has_vllm_cpu(self):
        assert "CPU ile" in self.content

    def test_has_gemini_setup(self):
        assert "Gemini Kurulumu" in self.content

    def test_has_api_key_instructions(self):
        assert "GEMINI_API_KEY" in self.content

    def test_has_audio_device(self):
        assert "Ses Cihazı" in self.content

    def test_has_device_listing(self):
        assert "sounddevice" in self.content or "arecord" in self.content

    def test_has_systemd_services(self):
        assert "systemd Servisleri" in self.content

    def test_has_systemctl_commands(self):
        assert "systemctl --user" in self.content

    def test_has_privacy_section(self):
        assert "Gizlilik Ayarları" in self.content

    def test_has_local_only_mode(self):
        assert "Local-Only" in self.content or "local-only" in self.content

    def test_has_cloud_consent(self):
        assert "BANTZ_CLOUD_ENABLED" in self.content

    def test_has_troubleshooting(self):
        assert "Troubleshooting" in self.content

    def test_has_service_troubleshooting(self):
        assert "Servis Başlamıyor" in self.content or "başlamıyor" in self.content

    def test_has_vllm_troubleshooting(self):
        assert "vLLM Bağlanmıyor" in self.content

    def test_has_mic_troubleshooting(self):
        assert "Mikrofon Algılanmıyor" in self.content or "mikrofon" in self.content.lower()

    def test_has_wake_word_troubleshooting(self):
        assert "Wake Word" in self.content or "wake word" in self.content.lower()

    def test_has_smoke_test(self):
        assert "Smoke Test" in self.content

    def test_has_env_summary(self):
        assert "Ortam Değişkenleri" in self.content or ".env" in self.content

    def test_has_update_section(self):
        assert "Güncelleme" in self.content

    def test_mentions_pii_redaction(self):
        assert "BANTZ_REDACT_PII" in self.content or "redact" in self.content.lower()

    def test_mentions_morning_briefing(self):
        assert "BANTZ_MORNING_BRIEFING" in self.content

    def test_mentions_health_check(self):
        assert "health_check" in self.content or "run_health_check" in self.content
