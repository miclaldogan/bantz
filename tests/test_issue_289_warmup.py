"""Tests for Issue #289 — LLM warmup pipeline.

Covers:
  - BackendStatus / WarmupResult dataclasses
  - check_vllm_health: success, timeout
  - warmup_vllm: success, error
  - check_gemini_preflight: skipped, success
  - run_warmup: full pipeline
  - is_ready / ready file
  - File existence
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parent.parent


class TestBackendStatus:
    def test_defaults(self):
        from bantz.llm.preflight import BackendStatus
        s = BackendStatus()
        assert s.status == "unknown"
        assert s.error is None

    def test_ready(self):
        from bantz.llm.preflight import BackendStatus
        s = BackendStatus(status="ready", model="test", warmup_ms=42.0)
        assert s.status == "ready"
        assert s.warmup_ms == 42.0


class TestWarmupResult:
    def test_defaults(self):
        from bantz.llm.preflight import WarmupResult
        r = WarmupResult()
        assert r.ready is False
        assert r.backends == {}

    def test_ready(self):
        from bantz.llm.preflight import WarmupResult
        r = WarmupResult(ready=True, boot_duration_ms=150.0)
        assert r.ready is True


class TestCheckVllmHealth:
    def test_success(self):
        from bantz.llm.preflight import check_vllm_health

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "Qwen/test"}]}

        with mock.patch("requests.get", return_value=mock_resp):
            result = check_vllm_health("http://localhost:8001", timeout=1)
        assert result.status == "ready"
        assert result.model == "Qwen/test"

    def test_timeout(self):
        from bantz.llm.preflight import check_vllm_health

        with mock.patch("requests.get", side_effect=ConnectionError("refused")):
            result = check_vllm_health("http://localhost:9999", timeout=0.1, retry_interval=0.05)
        assert result.status == "error"
        assert "timeout" in result.error.lower()


class TestWarmupVllm:
    def test_success(self):
        from bantz.llm.preflight import warmup_vllm

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200

        with mock.patch("requests.post", return_value=mock_resp):
            result = warmup_vllm("http://localhost:8001")
        assert result.status == "ready"
        assert result.warmup_ms > 0

    def test_error(self):
        from bantz.llm.preflight import warmup_vllm

        with mock.patch("requests.post", side_effect=ConnectionError):
            result = warmup_vllm("http://localhost:9999", timeout=1)
        assert result.status == "error"


class TestGeminiPreflight:
    def test_skipped_no_key(self):
        from bantz.llm.preflight import check_gemini_preflight

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "BANTZ_CLOUD_ENABLED": "false"}):
            result = check_gemini_preflight()
        assert result.status == "skipped"

    def test_skipped_cloud_disabled(self):
        from bantz.llm.preflight import check_gemini_preflight

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "BANTZ_CLOUD_ENABLED": "false"}):
            result = check_gemini_preflight()
        assert result.status == "skipped"

    def test_success(self):
        from bantz.llm.preflight import check_gemini_preflight

        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test", "BANTZ_CLOUD_ENABLED": "true"}):
            with mock.patch("requests.get", return_value=mock_resp):
                result = check_gemini_preflight()
        assert result.status == "ready"


class TestRunWarmup:
    def test_full_pipeline(self, tmp_path):
        from bantz.llm.preflight import run_warmup, READY_FILE

        mock_health = mock.MagicMock()
        mock_health.status_code = 200
        mock_health.json.return_value = {"data": [{"id": "test-model"}]}

        mock_warmup = mock.MagicMock()
        mock_warmup.status_code = 200

        ready_file = tmp_path / "ready.json"

        with mock.patch("bantz.llm.preflight.READY_FILE", ready_file):
            with mock.patch("requests.get", return_value=mock_health):
                with mock.patch("requests.post", return_value=mock_warmup):
                    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "BANTZ_CLOUD_ENABLED": "false"}):
                        result = run_warmup("http://localhost:8001", vllm_timeout=1)

        assert result.ready is True
        assert ready_file.exists()
        data = json.loads(ready_file.read_text())
        assert data["ready"] is True


class TestIsReady:
    def test_no_file(self, tmp_path):
        from bantz.llm.preflight import is_ready
        with mock.patch("bantz.llm.preflight.READY_FILE", tmp_path / "nonexistent.json"):
            assert is_ready() is False

    def test_ready_file(self, tmp_path):
        from bantz.llm.preflight import is_ready
        f = tmp_path / "ready.json"
        f.write_text('{"ready": true}')
        with mock.patch("bantz.llm.preflight.READY_FILE", f):
            assert is_ready() is True

    def test_not_ready_file(self, tmp_path):
        from bantz.llm.preflight import is_ready
        f = tmp_path / "ready.json"
        f.write_text('{"ready": false}')
        with mock.patch("bantz.llm.preflight.READY_FILE", f):
            assert is_ready() is False


class TestFileExistence:
    def test_preflight_module(self):
        assert (ROOT / "src" / "bantz" / "llm" / "preflight.py").is_file()
