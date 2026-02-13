from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_watchdog_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "vllm" / "watchdog.py"
    spec = importlib.util.spec_from_file_location("bantz_watchdog_script", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Dataclasses can require sys.modules entry (similar to bench_vllm tests).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_detect_oom_true_for_common_markers():
    wd = _load_watchdog_module()
    assert wd._detect_oom("CUDA out of memory") is True
    assert wd._detect_oom("RuntimeError: out of memory") is True


def test_detect_oom_false_for_empty():
    wd = _load_watchdog_module()
    assert wd._detect_oom("") is False
    assert wd._detect_oom("all good") is False


def test_health_result_dataclass_exists():
    wd = _load_watchdog_module()
    assert hasattr(wd, "HealthResult")


@pytest.mark.parametrize(
    "env_key,env_val,expected",
    [
        ("BANTZ_QOS_DEFAULT_FAST_MAX_TOKENS", "64", 64),
        ("BANTZ_QOS_FAST_MAX_TOKENS", "96", 96),
    ],
)
def test_get_qos_env_overrides(monkeypatch, env_key: str, env_val: str, expected: int):
    from bantz.llm.tiered import get_qos

    monkeypatch.setenv(env_key, env_val)
    qos = get_qos(use_quality=False, profile="default")
    assert qos.max_tokens == expected
