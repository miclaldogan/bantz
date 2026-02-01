#!/usr/bin/env python3
"""Benchmark script for LLM Orchestrator (Issue #138).

Measures latency, throughput, and token usage for the vLLM backend.

Scenarios:
- Router: 10 different prompts, 50 repetitions each
- Orchestrator: 5 calendar scenarios (smalltalk, list, create, evening, week)
- Chat: 5 smalltalk scenarios

Metrics:
- Latency: p50, p95, p99 (ms)
- Throughput: tokens/sec
- JSON validity rate: How often JSON parsing succeeds
- Error rate: Failed requests

Usage:
    python3 scripts/bench_llm_orchestrator.py --backend vllm --iterations 50
    python3 scripts/bench_llm_orchestrator.py --quick  # 10 iterations (faster)
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import re
import requests

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.base import create_client, LLMMessage, LLMClient
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.agent.tools import Tool, ToolRegistry
from bantz.core.events import EventBus


# =============================================================================
# Benchmark Prompt Profile
# =============================================================================

# vLLM instances on small GPUs are commonly started with low --max-model-len (e.g. 2048)
# to keep KV cache memory bounded. The production SYSTEM_PROMPT is intentionally verbose
# (examples, rules, etc.) and can exceed small context windows.
BENCH_SYSTEM_PROMPT = """Sen BANTZ'sın. USER Türkçe konuşur. Türkçe cevapla ve 'Efendim' hitabını kullan.

Sadece tek bir JSON object döndür (Markdown/açıklama yok).

Şema:
{
  \"route\": \"calendar|smalltalk|unknown\",
  \"calendar_intent\": \"create|modify|cancel|query|none\",
  \"slots\": {\"date\": null, \"time\": null, \"duration\": null, \"title\": null, \"window_hint\": null},
  \"confidence\": 0.0,
  \"tool_plan\": [],
  \"assistant_reply\": \"\",
  \"ask_user\": false,
  \"question\": \"\",
  \"requires_confirmation\": false,
  \"confirmation_prompt\": \"\",
  \"memory_update\": \"\",
  \"reasoning_summary\": []
}

Kurallar:
- confidence < 0.7 ise tool_plan boş, ask_user=true ve question doldur.
- route=smalltalk ise assistant_reply zorunlu.
- modify/cancel gibi işlemler için requires_confirmation=true ve confirmation_prompt doldur.
"""


def _make_orchestrator(llm_client: LLMClient, *, prompt_profile: str) -> JarvisLLMOrchestrator:
    if prompt_profile == "bench":
        return JarvisLLMOrchestrator(llm=llm_client, system_prompt=BENCH_SYSTEM_PROMPT)
    return JarvisLLMOrchestrator(llm=llm_client)


class _TokenEstimator:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self._tokenizer = None

    def _get_tokenizer(self):
        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer

                try:
                    self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=False)
                except Exception:
                    self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
            except Exception:
                self._tokenizer = None
        return self._tokenizer

    def count(self, text: str) -> Optional[int]:
        tok = self._get_tokenizer()
        if tok is None:
            return None
        try:
            return len(tok.encode(text))
        except Exception:
            return None


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class BenchmarkResult:
    """Single benchmark measurement."""
    scenario: str
    backend: str
    latency_ms: float
    ttft_ms: Optional[float] = None  # Time-To-First-Token (Jarvis feeling!)
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tokens_total: Optional[int] = None
    vram_peak_mb: Optional[int] = None  # Peak VRAM usage
    success: bool = True
    json_valid: bool = True
    error: Optional[str] = None


@dataclass
class BenchmarkStats:
    """Aggregated statistics for a scenario."""
    scenario: str
    backend: str
    iterations: int
    latency_p50: float
    latency_p95: float
    latency_p99: float
    latency_mean: float
    latency_std: float
    ttft_p50: float = 0  # Time-To-First-Token p50
    ttft_p95: float = 0  # Time-To-First-Token p95
    throughput_tokens_per_sec: float = 0
    success_rate: float = 0
    json_validity_rate: float = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_duration_sec: float = 0
    vram_peak_mb: int = 0  # Peak VRAM across all iterations


# =============================================================================
# VRAM Monitoring
# =============================================================================

def get_gpu_memory_usage() -> Optional[int]:
    """Get current GPU memory usage in MB using nvidia-smi.
    
    Returns:
        Peak VRAM usage in MB, or None if nvidia-smi not available
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            # Parse first GPU's memory (MB)
            memory_mb = int(result.stdout.strip().split("\n")[0])
            return memory_mb
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


class _VRAMSampler:
    """Poll GPU VRAM usage during an operation and report peak MB."""

    def __init__(self, *, interval_sec: float = 0.25):
        self._interval_sec = float(interval_sec)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.peak_mb: Optional[int] = None

    def __enter__(self) -> "_VRAMSampler":
        self._stop.clear()
        self.peak_mb = None

        def _run():
            while not self._stop.is_set():
                mb = get_gpu_memory_usage()
                if mb is not None:
                    if self.peak_mb is None or mb > self.peak_mb:
                        self.peak_mb = mb
                self._stop.wait(self._interval_sec)

        self._thread = threading.Thread(target=_run, name="vram-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def _try_create_openai_client(*, base_url: str, timeout_seconds: float):
    """Create an OpenAI client pointing at vLLM's OpenAI-compatible endpoint."""
    try:
        from openai import OpenAI

        return OpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="EMPTY",
            timeout=float(timeout_seconds),
        )
    except Exception:
        return None


# =============================================================================
# Benchmark Scenarios
# =============================================================================

ROUTER_SCENARIOS = [
    "hey bantz nasılsın",
    "bugün neler yapacağız bakalım",
    "saat 4 için bir toplantı oluştur",
    "bu akşam neler yapacağız",
    "bu hafta planımda önemli işler var mı",
    "yarın sabah 9'da doktor randevum var",
    "cumartesi günü ne yapıyoruz",
    "takvimimi göster",
    "bugün hava nasıl",
    "kendini tanıt",
]

# Qualitative conversation test scenarios (Issue #153)
QUALITATIVE_CONVERSATIONS = [
    {
        "name": "Haftalık Takvim Sorgusu",
        "turns": [
            "merhaba bantz",
            "bu hafta neler planladık bakalım",
            "cumartesi ne yapıyoruz",
        ],
        "expected_behavior": "Greeting → calendar query → follow-up query with memory"
    },
    {
        "name": "Toplantı Oluşturma",
        "turns": [
            "yarın saat 14'te bir toplantı oluştur",
            "toplantı başlığı: Proje Review olsun",
            "teşekkürler",
        ],
        "expected_behavior": "Create event → add details → confirmation"
    },
    {
        "name": "Smalltalk ve Anımsama",
        "turns": [
            "nasılsın bantz",
            "az önce ne yaptık",
            "peki bu akşam planımız var mı",
        ],
        "expected_behavior": "Smalltalk → memory query → calendar query"
    },
    {
        "name": "Karmaşık Takvim",
        "turns": [
            "bugünün programını göster",
            "akşam 7'ye randevu ekle doktor için",
            "şimdi toplam kaç etkinliğim var bugün",
        ],
        "expected_behavior": "List → create → count (requires memory)"
    },
    {
        "name": "Hava Durumu ve Takvim",
        "turns": [
            "bugün hava nasıl",
            "peki dışarı çıkma planım var mı",
            "varsa saat kaçta",
        ],
        "expected_behavior": "Smalltalk → calendar check → detail query"
    },
]

ORCHESTRATOR_SCENARIOS = [
    ("smalltalk", "hey bantz nasılsın"),
    ("calendar_list_today", "bugün neler yapacağız bakalım"),
    ("calendar_create", "saat 4 için bir toplantı oluştur"),
    ("calendar_list_evening", "bu akşam neler yapacağız"),
    ("calendar_list_week", "bu hafta planımda önemli işler var mı"),
]

CHAT_SCENARIOS = [
    "merhaba",
    "nasılsın",
    "ne yapıyorsun",
    "kim yarattı seni",
    "saat kaç",
]


# =============================================================================
# Mock Tools
# =============================================================================

def create_mock_tools() -> ToolRegistry:
    """Create mock tool registry for benchmarking."""
    registry = ToolRegistry()
    
    # Calendar list tool
    registry.register(Tool(
        name="calendar.list_events",
        description="List calendar events",
        parameters={
            "type": "object",
            "properties": {
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
        },
        function=lambda **kwargs: {"status": "success", "events": []},
    ))
    
    # Calendar create tool
    registry.register(Tool(
        name="calendar.create_event",
        description="Create calendar event",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
            },
            "required": ["title", "start"],
        },
        function=lambda **kwargs: {"status": "success", "event_id": "evt_123"},
    ))
    
    return registry


# =============================================================================
# Helper Functions for Verbose Mode
# =============================================================================

def get_router_response(llm_client: LLMClient, prompt: str) -> str:
    """Get a single router response for display."""
    try:
        orchestrator = _make_orchestrator(llm_client, prompt_profile="bench")
        output = orchestrator.route(user_input=prompt)
        return f"route={output.route}, intent={output.calendar_intent}, reply={output.assistant_reply[:100] if output.assistant_reply else 'None'}"
    except Exception as e:
        return f"Error: {str(e)}"


def get_orchestrator_response(llm_client: LLMClient, user_input: str) -> str:
    """Get a single orchestrator response for display."""
    try:
        orchestrator = _make_orchestrator(llm_client, prompt_profile="bench")
        tools = create_mock_tools()
        event_bus = EventBus()
        config = OrchestratorConfig(enable_safety_guard=False)
        loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
        output, state = loop.process_turn(user_input)
        return f"route={output.route}, tools={len(output.tool_plan)}, reply={output.assistant_reply[:100] if output.assistant_reply else 'None'}"
    except Exception as e:
        return f"Error: {str(e)}"


def get_chat_response(llm_client: LLMClient, prompt: str) -> str:
    """Get a single chat response for display."""
    try:
        messages = [LLMMessage(role="user", content=prompt)]
        response = llm_client.chat(messages, temperature=0.7, max_tokens=100)
        return response
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# Benchmark Functions
# =============================================================================

def benchmark_router(
    llm_client: LLMClient,
    prompt: str,
    backend: str,
    *,
    prompt_profile: str,
) -> BenchmarkResult:
    """Benchmark a single router prompt."""
    orchestrator = _make_orchestrator(llm_client, prompt_profile=prompt_profile)
    
    start = time.perf_counter()
    try:
        with _VRAMSampler() as vram:
            output = orchestrator.route(user_input=prompt)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Treat fallback outputs (raw_output contains "error") as invalid JSON/success=False
        raw = getattr(output, "raw_output", None) or {}
        json_valid = not (isinstance(raw, dict) and raw.get("error"))
        success = bool(json_valid)
        
        # Estimate tokens (fallback if client doesn't expose usage)
        # Router prompt is typically: system prompt (~200 words) + user input
        prompt_tokens = len(orchestrator.SYSTEM_PROMPT.split()) + len(prompt.split())
        completion_tokens = len(json.dumps(output.raw_output).split()) if output else 0
        
        return BenchmarkResult(
            scenario=f"router:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=success,
            json_valid=json_valid,
            tokens_input=prompt_tokens,
            tokens_output=completion_tokens,
            tokens_total=prompt_tokens + completion_tokens,
            vram_peak_mb=vram.peak_mb,
            error=str(raw.get("error")) if isinstance(raw, dict) and raw.get("error") else None,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"router:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=False,
            json_valid=False,
            error=str(e),
        )


def benchmark_orchestrator(
    llm_client: LLMClient,
    finalizer_llm_client: Optional[LLMClient],
    scenario_name: str,
    user_input: str,
    backend: str,
    *,
    prompt_profile: str,
) -> BenchmarkResult:
    """Benchmark a single orchestrator cycle."""
    orchestrator = _make_orchestrator(llm_client, prompt_profile=prompt_profile)
    tools = create_mock_tools()
    event_bus = EventBus()
    config = OrchestratorConfig(enable_safety_guard=False)
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config, finalizer_llm=finalizer_llm_client)
    
    start = time.perf_counter()
    try:
        with _VRAMSampler() as vram:
            output, state = loop.process_turn(user_input)
        elapsed_ms = (time.perf_counter() - start) * 1000

        raw = getattr(output, "raw_output", None) or {}
        json_valid = not (isinstance(raw, dict) and raw.get("error"))
        success = bool(json_valid)
        
        # Estimate tokens (system prompt + user input + output JSON)
        prompt_tokens = len(orchestrator.SYSTEM_PROMPT.split()) + len(user_input.split())
        completion_tokens = len(json.dumps(output.raw_output).split()) if output else 0
        
        return BenchmarkResult(
            scenario=f"orchestrator:{scenario_name}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=success,
            json_valid=json_valid,
            tokens_input=prompt_tokens,
            tokens_output=completion_tokens,
            tokens_total=prompt_tokens + completion_tokens,
            vram_peak_mb=vram.peak_mb,
            error=str(raw.get("error")) if isinstance(raw, dict) and raw.get("error") else None,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"orchestrator:{scenario_name}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=False,
            json_valid=False,
            error=str(e),
        )


def benchmark_chat(
    llm_client: LLMClient,
    prompt: str,
    backend: str,
    *,
    token_estimator: Optional[_TokenEstimator] = None,
) -> BenchmarkResult:
    """Benchmark a single chat completion."""
    messages = [LLMMessage(role="user", content=prompt)]
    
    start = time.perf_counter()
    ttft = None
    
    try:
        with _VRAMSampler() as vram:
            response = llm_client.chat_detailed(
                messages,
                temperature=0.0,
                max_tokens=200,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Estimate TTFT as ~5-10% of total time (mock estimate since no streaming)
        # In real streaming, this would be measured from first token callback
        ttft = elapsed_ms * 0.08  # Assume TTFT is ~8% of total latency
        
        vram_peak = vram.peak_mb
        
        # Extract token counts if available
        tokens_input = None
        tokens_output = None
        tokens_total = None

        # Our internal LLMResponse doesn't expose OpenAI-style usage.
        # Estimate via tokenizer when available so throughput isn't always 0.
        if token_estimator is not None:
            tokens_input = token_estimator.count(prompt)
            tokens_output = token_estimator.count(getattr(response, "content", "") or "")
            if tokens_input is not None and tokens_output is not None:
                tokens_total = tokens_input + tokens_output
        
        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            ttft_ms=ttft,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_total=tokens_total,
            vram_peak_mb=vram_peak,
            success=True,
            json_valid=True,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            ttft_ms=ttft,
            success=False,
            json_valid=False,
            error=str(e),
        )


def benchmark_chat_vllm_stream(
    *,
    base_url: str,
    model: str,
    prompt: str,
    backend: str,
    timeout_seconds: float,
    max_tokens: int,
    token_estimator: Optional[_TokenEstimator],
) -> BenchmarkResult:
    """Benchmark chat with real TTFT via vLLM streaming."""
    client = _try_create_openai_client(base_url=base_url, timeout_seconds=timeout_seconds)
    if client is None:
        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=0.0,
            ttft_ms=None,
            success=False,
            json_valid=False,
            error="openai client not available for streaming",
        )

    messages = [{"role": "user", "content": prompt}]

    start = time.perf_counter()
    first_token_time: Optional[float] = None
    content_parts: list[str] = []
    usage_prompt_tokens: Optional[int] = None
    usage_completion_tokens: Optional[int] = None
    usage_total_tokens: Optional[int] = None

    try:
        with _VRAMSampler() as vram:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=int(max_tokens),
                stream=True,
                # vLLM may ignore this; we still try.
                stream_options={"include_usage": True},
            )

            for event in stream:
                if first_token_time is None:
                    first_token_time = time.perf_counter()

                # New SDK objects expose attributes; be defensive.
                try:
                    if getattr(event, "usage", None) is not None:
                        usage = event.usage
                        usage_prompt_tokens = getattr(usage, "prompt_tokens", None)
                        usage_completion_tokens = getattr(usage, "completion_tokens", None)
                        usage_total_tokens = getattr(usage, "total_tokens", None)
                except Exception:
                    pass

                try:
                    choices = getattr(event, "choices", None) or []
                    if choices:
                        delta = getattr(choices[0], "delta", None)
                        piece = getattr(delta, "content", None) if delta is not None else None
                        if piece:
                            content_parts.append(piece)
                except Exception:
                    pass

        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        ttft_ms = ((first_token_time - start) * 1000) if first_token_time is not None else None

        content = "".join(content_parts).strip()

        tokens_input = usage_prompt_tokens
        tokens_output = usage_completion_tokens
        tokens_total = usage_total_tokens

        # Fallback to tokenizer-based estimates when server usage isn't available.
        if token_estimator is not None:
            if tokens_input is None:
                tokens_input = token_estimator.count(prompt)
            if tokens_output is None:
                tokens_output = token_estimator.count(content)
            if tokens_total is None and tokens_input is not None and tokens_output is not None:
                tokens_total = tokens_input + tokens_output

        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_total=tokens_total,
            vram_peak_mb=vram.peak_mb,
            success=True,
            json_valid=True,
            error=None,
        )

    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=latency_ms,
            ttft_ms=None,
            success=False,
            json_valid=False,
            error=str(e),
        )


# =============================================================================
# Statistics
# =============================================================================

def calculate_stats(
    results: List[BenchmarkResult],
    scenario: str,
    backend: str,
) -> BenchmarkStats:
    """Calculate statistics from benchmark results."""
    latencies = [r.latency_ms for r in results if r.success]
    ttfts = [r.ttft_ms for r in results if r.success and r.ttft_ms is not None]
    successes = sum(1 for r in results if r.success)
    vram_values = [r.vram_peak_mb for r in results if r.vram_peak_mb is not None]
    
    if not latencies:
        return BenchmarkStats(
            scenario=scenario,
            backend=backend,
            iterations=len(results),
            latency_p50=0,
            latency_p95=0,
            latency_p99=0,
            latency_mean=0,
            latency_std=0,
            ttft_p50=0,
            ttft_p95=0,
            throughput_tokens_per_sec=0,
            success_rate=0,
            json_validity_rate=0,
            total_tokens_input=0,
            total_tokens_output=0,
            total_duration_sec=0,
            vram_peak_mb=0,
        )
    
    # Calculate percentiles
    latencies_sorted = sorted(latencies)
    p50_idx = int(len(latencies_sorted) * 0.50)
    p95_idx = int(len(latencies_sorted) * 0.95)
    p99_idx = int(len(latencies_sorted) * 0.99)
    
    p50 = latencies_sorted[p50_idx]
    p95 = latencies_sorted[p95_idx]
    p99 = latencies_sorted[p99_idx]
    mean = statistics.mean(latencies)
    std = statistics.stdev(latencies) if len(latencies) > 1 else 0
    
    # TTFT percentiles
    ttft_p50 = 0
    ttft_p95 = 0
    if ttfts:
        ttfts_sorted = sorted(ttfts)
        ttft_p50 = ttfts_sorted[int(len(ttfts_sorted) * 0.50)]
        ttft_p95 = ttfts_sorted[int(len(ttfts_sorted) * 0.95)]
    
    # VRAM peak
    vram_peak = max(vram_values) if vram_values else 0
    
    # Token statistics
    total_tokens_input = sum(r.tokens_input or 0 for r in results if r.success)
    total_tokens_output = sum(r.tokens_output or 0 for r in results if r.success)
    total_duration_sec = sum(r.latency_ms for r in results if r.success) / 1000
    
    # Throughput (tokens/sec)
    throughput = 0
    if total_duration_sec > 0 and total_tokens_output > 0:
        throughput = total_tokens_output / total_duration_sec
    
    # Success rates
    success_rate = successes / len(results) if results else 0
    json_validity_rate = (
        sum(1 for r in results if r.json_valid) / len(results)
        if results else 0
    )
    
    return BenchmarkStats(
        scenario=scenario,
        backend=backend,
        iterations=len(results),
        latency_p50=p50,
        latency_p95=p95,
        latency_p99=p99,
        latency_mean=mean,
        latency_std=std,
        ttft_p50=ttft_p50,
        ttft_p95=ttft_p95,
        throughput_tokens_per_sec=throughput,
        success_rate=success_rate,
        json_validity_rate=json_validity_rate,
        total_tokens_input=total_tokens_input,
        total_tokens_output=total_tokens_output,
        total_duration_sec=total_duration_sec,
        vram_peak_mb=vram_peak,
    )


# =============================================================================
# Reporting
# =============================================================================

def print_stats(stats: BenchmarkStats):
    """Print benchmark statistics in a readable format."""
    print(f"\n{'='*80}")
    print(f"Scenario: {stats.scenario}")
    print(f"Backend: {stats.backend}")
    print(f"Iterations: {stats.iterations}")
    print(f"{'='*80}")
    
    print(f"\n📊 Latency (ms):")
    print(f"  p50:  {stats.latency_p50:>8.2f} ms")
    print(f"  p95:  {stats.latency_p95:>8.2f} ms")
    print(f"  p99:  {stats.latency_p99:>8.2f} ms")
    print(f"  mean: {stats.latency_mean:>8.2f} ms (±{stats.latency_std:.2f})")
    
    if stats.ttft_p50 > 0:
        print(f"\n⚡ TTFT - Time-To-First-Token (Jarvis Feeling!):")
        print(f"  p50:  {stats.ttft_p50:>8.2f} ms")
        print(f"  p95:  {stats.ttft_p95:>8.2f} ms")
        jarvis_feeling = "😊 FAST" if stats.ttft_p95 < 300 else "🤔 OK" if stats.ttft_p95 < 500 else "😐 SLOW"
        print(f"  Feel: {jarvis_feeling}")
    
    print(f"\n🚀 Throughput:")
    print(f"  {stats.throughput_tokens_per_sec:.2f} tokens/sec")
    
    print(f"\n📈 Success Rates:")
    print(f"  Success:       {stats.success_rate*100:>6.2f}%")
    print(f"  JSON validity: {stats.json_validity_rate*100:>6.2f}%")
    
    print(f"\n🔢 Token Usage:")
    print(f"  Input:  {stats.total_tokens_input:>8} tokens")
    print(f"  Output: {stats.total_tokens_output:>8} tokens")
    print(f"  Total:  {stats.total_tokens_input + stats.total_tokens_output:>8} tokens")
    
    if stats.vram_peak_mb > 0:
        print(f"\n💾 VRAM Peak: {stats.vram_peak_mb} MB")


def generate_markdown_report(
    all_stats: List[BenchmarkStats],
    output_file: Path,
):
    """Generate markdown report comparing backends."""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# LLM Orchestrator Benchmark Results\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## Measurement Notes\n\n")
        f.write("- **Latency** is measured wall-clock end-to-end.\n")
        f.write("- **TTFT** is **measured via streaming** only when `--vllm-stream-ttft` is enabled for vLLM chat scenarios.\n")
        f.write("- **VRAM Peak** is measured by polling `nvidia-smi` during each iteration (best-effort).\n")
        f.write("- **Tokens/sec** depends on token counting:\n")
        f.write("  - If the vLLM streaming API returns usage, we use that.\n")
        f.write("  - Otherwise, we fall back to tokenizer-based estimates (not server-authoritative).\n\n")
        
        # Group by scenario
        scenarios = {}
        for stat in all_stats:
            if stat.scenario not in scenarios:
                scenarios[stat.scenario] = []
            scenarios[stat.scenario].append(stat)
        
        for scenario, stats_list in scenarios.items():
            f.write(f"## {scenario}\n\n")
            
            # Table header
            f.write("| Backend | p50 (ms) | p95 (ms) | p99 (ms) | TTFT p50 (ms) | TTFT p95 (ms) | VRAM Peak (MB) | Throughput (tok/s) | Success Rate | JSON Validity |\n")
            f.write("|---------|----------|----------|----------|--------------|--------------|---------------|--------------------|-------------|-------------|\n")
            
            for stat in stats_list:
                f.write(
                    "| {backend} | {p50:.2f} | {p95:.2f} | {p99:.2f} | {ttft50:.2f} | {ttft95:.2f} | {vram} | {tps:.2f} | {sr:.1f}% | {jv:.1f}% |\n".format(
                        backend=stat.backend,
                        p50=stat.latency_p50,
                        p95=stat.latency_p95,
                        p99=stat.latency_p99,
                        ttft50=stat.ttft_p50 or 0.0,
                        ttft95=stat.ttft_p95 or 0.0,
                        vram=int(stat.vram_peak_mb) if stat.vram_peak_mb else 0,
                        tps=stat.throughput_tokens_per_sec,
                        sr=stat.success_rate * 100,
                        jv=stat.json_validity_rate * 100,
                    )
                )
            
            f.write("\n")
            
            # Comparison
            if len(stats_list) == 2:
                stat1, stat2 = stats_list[0], stats_list[1]
                speedup_p50 = stat1.latency_p50 / stat2.latency_p50 if stat2.latency_p50 > 0 else 0
                speedup_p95 = stat1.latency_p95 / stat2.latency_p95 if stat2.latency_p95 > 0 else 0
                
                faster_backend = stat1.backend if speedup_p50 > 1 else stat2.backend
                f.write(f"**Winner:** {faster_backend} ")
                f.write(f"({abs(speedup_p50):.2f}x faster p50, {abs(speedup_p95):.2f}x faster p95)\n\n")


def save_json_results(all_stats: List[BenchmarkStats], output_file: Path):
    """Save benchmark results as JSON."""
    data = {
        "generated_at": datetime.now().isoformat(),
        "results": [asdict(stat) for stat in all_stats],
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# Main Benchmark Runner
# =============================================================================

def run_benchmark(
    backend: str,
    iterations: int = 50,
    scenarios: str = "all",
    verbose: bool = False,
    vllm_base_url: str = "http://127.0.0.1:8001",
    vllm_model: str = "Qwen/Qwen2.5-3B-Instruct",
    vllm_final_base_url: str = "",
    vllm_final_model: str = "",
    prompt_profile: str = "bench",
    vllm_stream_ttft: bool = True,
    vllm_timeout_seconds: float = 120.0,
    vllm_chat_max_tokens: int = 200,
) -> List[BenchmarkStats]:
    """Run benchmarks for a backend."""
    print(f"\n{'='*80}")
    print(f"Running benchmarks for: {backend}")
    print(f"Iterations: {iterations}")
    print(f"Scenarios: {scenarios}")
    print(f"{'='*80}\n")
    
    def resolve_vllm_model_id(base_url: str, preferred_model: str) -> str:
        """Pick a model ID that actually exists on the vLLM server.

        This is important for quantized repos like *-AWQ / *-GPTQ which have
        different model IDs than the default "Qwen/Qwen2.5-3B-Instruct".
        """
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=2)
            resp.raise_for_status()
            data = resp.json()
            model_ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            if not model_ids:
                return preferred_model
            if preferred_model in model_ids:
                return preferred_model
            return model_ids[0]
        except Exception:
            return preferred_model

    if backend != "vllm":
        raise ValueError(f"Unsupported backend: {backend} (expected 'vllm')")

    # Create LLM client(s)
    finalizer_client: Optional[LLMClient] = None
    resolved_model = resolve_vllm_model_id(vllm_base_url, vllm_model)
    if resolved_model != vllm_model:
        print(f"ℹ️ vLLM model override: '{vllm_model}' → '{resolved_model}'")
    client = create_client(
        "vllm",
        base_url=vllm_base_url,
        model=resolved_model,
        timeout=vllm_timeout_seconds,
    )

    if str(vllm_final_base_url or "").strip():
        resolved_final_model = resolve_vllm_model_id(vllm_final_base_url, vllm_final_model or resolved_model)
        if vllm_final_model and resolved_final_model != vllm_final_model:
            print(f"ℹ️ vLLM finalizer model override: '{vllm_final_model}' → '{resolved_final_model}'")
        finalizer_client = create_client(
            "vllm",
            base_url=vllm_final_base_url,
            model=resolved_final_model,
            timeout=vllm_timeout_seconds,
        )

    token_estimator: Optional[_TokenEstimator] = None
    if backend == "vllm":
        # vLLM chat responses via our internal client don't include usage;
        # create a tokenizer-based estimator for throughput.
        try:
            token_estimator = _TokenEstimator(getattr(client, "model_name", "") or vllm_model)
        except Exception:
            token_estimator = None
    
    # Check if backend is available
    if not client.is_available():
        print(f"❌ {backend} server is not available. Skipping.")
        return []
    if finalizer_client is not None and not finalizer_client.is_available():
        print("❌ vLLM finalizer server is not available. Disabling hybrid finalizer.")
        finalizer_client = None
    
    all_stats = []
    
    # Router benchmarks
    if scenarios in ("all", "router"):
        print(f"\n📍 Benchmarking Router scenarios...")
        for prompt in ROUTER_SCENARIOS:
            print(f"  Running: {prompt[:40]}...")
            results = []
            for i in range(iterations):
                result = benchmark_router(client, prompt, backend, prompt_profile=prompt_profile)
                results.append(result)
                # Show first response in verbose mode
                if verbose and i == 0:
                    response = get_router_response(client, prompt)
                    print(f"    🤖 Response: {response[:200]}...")
            
            stats = calculate_stats(results, f"router:{prompt[:30]}", backend)
            all_stats.append(stats)
            print(f"    ✓ p50: {stats.latency_p50:.2f} ms, success: {stats.success_rate*100:.1f}%")
    
    # Orchestrator benchmarks
    if scenarios in ("all", "orchestrator"):
        print(f"\n🎯 Benchmarking Orchestrator scenarios...")
        for scenario_name, user_input in ORCHESTRATOR_SCENARIOS:
            print(f"  Running: {scenario_name}...")
            results = []
            for i in range(iterations):
                result = benchmark_orchestrator(client, finalizer_client, scenario_name, user_input, backend, prompt_profile=prompt_profile)
                results.append(result)
                # Show first response in verbose mode
                if verbose and i == 0:
                    response = get_orchestrator_response(client, user_input)
                    print(f"    🤖 Response: {response[:200]}...")
            
            stats = calculate_stats(results, f"orchestrator:{scenario_name}", backend)
            all_stats.append(stats)
            print(f"    ✓ p50: {stats.latency_p50:.2f} ms, success: {stats.success_rate*100:.1f}%")
    
    # Chat benchmarks
    if scenarios in ("all", "chat"):
        print(f"\n💬 Benchmarking Chat scenarios...")
        chat_client = finalizer_client or client
        chat_base_url = getattr(chat_client, "base_url", None) or vllm_base_url
        chat_model = getattr(chat_client, "model_name", "") or vllm_model
        for prompt in CHAT_SCENARIOS:
            print(f"  Running: {prompt}...")
            results = []
            for i in range(iterations):
                if backend == "vllm" and vllm_stream_ttft:
                    result = benchmark_chat_vllm_stream(
                        base_url=chat_base_url,
                        model=chat_model,
                        prompt=prompt,
                        backend=backend,
                        timeout_seconds=vllm_timeout_seconds,
                        max_tokens=vllm_chat_max_tokens,
                        token_estimator=token_estimator,
                    )
                else:
                    result = benchmark_chat(
                        chat_client,
                        prompt,
                        backend,
                        token_estimator=token_estimator,
                    )
                results.append(result)
                # Show first response in verbose mode
                if verbose and i == 0:
                    response = get_chat_response(chat_client, prompt)
                    print(f"    🤖 Response: {response[:200]}...")
            
            stats = calculate_stats(results, f"chat:{prompt}", backend)
            all_stats.append(stats)
            print(f"    ✓ p50: {stats.latency_p50:.2f} ms, throughput: {stats.throughput_tokens_per_sec:.2f} tok/s")
    
    return all_stats


# =============================================================================
# Qualitative Test Mode (Issue #153)
# =============================================================================

def run_qualitative_tests(backend: str) -> None:
    """Run qualitative conversation tests for manual evaluation.
    
    This mode runs predefined multi-turn conversations to assess:
    - Memory continuity (\"az önce ne yaptık?\")
    - Natural Turkish responses
    - Context awareness across turns
    - Tool selection accuracy
    """
    print(f"\n{'='*80}")
    print(f"🎭 QUALITATIVE CONVERSATION TEST MODE")
    print(f"Backend: {backend}")
    print(f"{'='*80}\n")
    
    def resolve_vllm_model_id(base_url: str, preferred_model: str) -> str:
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=2)
            resp.raise_for_status()
            data = resp.json()
            model_ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            if not model_ids:
                return preferred_model
            if preferred_model in model_ids:
                return preferred_model
            return model_ids[0]
        except Exception:
            return preferred_model

    if backend != "vllm":
        raise ValueError(f"Unsupported backend: {backend} (expected 'vllm')")

    # Create LLM client
    base_url = "http://127.0.0.1:8001"
    preferred_model = "Qwen/Qwen2.5-3B-Instruct"
    resolved_model = resolve_vllm_model_id(base_url, preferred_model)
    if resolved_model != preferred_model:
        print(f"ℹ️ vLLM model override: '{preferred_model}' → '{resolved_model}'")
    client = create_client("vllm", base_url=base_url, model=resolved_model)
    
    if not client.is_available():
        print(f"❌ {backend} server is not available.")
        return
    
    # Use short prompt to avoid context-length errors on small vLLM max-model-len.
    orchestrator = _make_orchestrator(client, prompt_profile="bench")
    tools = create_mock_tools()
    event_bus = EventBus()
    config = OrchestratorConfig(enable_safety_guard=False)
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    for conv in QUALITATIVE_CONVERSATIONS:
        print(f"\n{'─'*80}")
        print(f"🎬 Conversation: {conv['name']}")
        print(f"Expected Behavior: {conv['expected_behavior']}")
        print(f"{'─'*80}\n")
        
        for turn_idx, user_input in enumerate(conv['turns'], 1):
            print(f"\n👤 User (Turn {turn_idx}): {user_input}")
            
            start = time.perf_counter()
            try:
                output, state = loop.process_turn(user_input)
                elapsed_ms = (time.perf_counter() - start) * 1000
                
                print(f"🤖 Bantz: {output.assistant_reply}")
                print(f"   Route: {output.route}")
                if output.tool_plan:
                    print(f"   Tools: {[t['tool_name'] for t in output.tool_plan]}")
                print(f"   Latency: {elapsed_ms:.0f} ms")
                print(f"   Memory turns: {len(loop.memory.summaries) if hasattr(loop, 'memory') else 'N/A'}")
                
            except Exception as e:
                print(f"❌ Error: {e}")
        
        print(f"\n{'─'*80}")
        print("📊 Evaluation Prompts:")
        print("  1. Konuşma doğal ve akıcı mı?")
        print("  2. Memory-lite çalıştı mı? ('az önce ne yaptık' sorusunu cevaplayabilir mi?)")
        print("  3. Tool seçimleri mantıklı mı?")
        print("  4. Türkçe kalitesi iyi mi?")
        print("  5. Jarvis hissi var mı?")
        print("\n👉 Your rating (1-10): _____\n")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Benchmark LLM Orchestrator (Issue #138, #153)")
    parser.add_argument("--backend", choices=["vllm"], default="vllm", help="LLM backend to benchmark")
    parser.add_argument("--iterations", type=int, default=50, help="Number of iterations per scenario")
    parser.add_argument("--quick", action="store_true", help="Quick benchmark (10 iterations)")
    parser.add_argument("--scenarios", choices=["all", "router", "orchestrator", "chat"], default="all", help="Which scenarios to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show LLM responses")
    parser.add_argument("--output-json", type=Path, help="Save results as JSON")
    parser.add_argument("--output-md", type=Path, help="Save markdown report")
    parser.add_argument("--qualitative", action="store_true", help="Run qualitative conversation tests (Issue #153)")
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:8001", help="vLLM OpenAI-compatible server base URL")
    parser.add_argument("--vllm-model", default="Qwen/Qwen2.5-3B-Instruct", help="Preferred vLLM model id (auto-falls back to server model)")
    parser.add_argument("--vllm-final-base-url", default="", help="Optional vLLM base URL for hybrid finalizer (8B reply model server)")
    parser.add_argument("--vllm-final-model", default="", help="Optional vLLM model id for hybrid finalizer (8B reply model)")
    parser.add_argument(
        "--prompt-profile",
        choices=["bench", "default"],
        default="bench",
        help="Prompt size profile for router/orchestrator (bench keeps prompts short for small context windows)",
    )
    parser.add_argument(
        "--vllm-stream-ttft",
        action="store_true",
        help="For vLLM chat benchmarks, measure real TTFT via streaming",
    )
    parser.add_argument(
        "--no-vllm-stream-ttft",
        action="store_true",
        help="Disable vLLM streaming TTFT (falls back to non-stream chat benchmark)",
    )
    parser.add_argument(
        "--vllm-timeout-seconds",
        type=float,
        default=120.0,
        help="Timeout for vLLM requests (seconds)",
    )
    parser.add_argument(
        "--vllm-chat-max-tokens",
        type=int,
        default=200,
        help="max_tokens for vLLM chat benchmarks",
    )
    
    args = parser.parse_args()
    
    # Qualitative test mode
    if args.qualitative:
        run_qualitative_tests("vllm")
        return 0
    
    # Set iterations
    iterations = 10 if args.quick else args.iterations
    
    # Run benchmarks
    all_stats = []

    vllm_stream_ttft = True
    if args.no_vllm_stream_ttft:
        vllm_stream_ttft = False
    elif args.vllm_stream_ttft:
        vllm_stream_ttft = True
    
    stats = run_benchmark(
        "vllm",
        iterations,
        args.scenarios,
        verbose=args.verbose,
        vllm_base_url=args.vllm_base_url,
        vllm_model=args.vllm_model,
        vllm_final_base_url=args.vllm_final_base_url,
        vllm_final_model=args.vllm_final_model,
        prompt_profile=args.prompt_profile,
        vllm_stream_ttft=vllm_stream_ttft,
        vllm_timeout_seconds=args.vllm_timeout_seconds,
        vllm_chat_max_tokens=args.vllm_chat_max_tokens,
    )
    all_stats.extend(stats)
    
    # Print all stats
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    for stat in all_stats:
        print_stats(stat)
    
    # Save results
    if args.output_json:
        save_json_results(all_stats, args.output_json)
        print(f"\n✓ Results saved to: {args.output_json}")
    
    if args.output_md:
        generate_markdown_report(all_stats, args.output_md)
        print(f"\n✓ Markdown report saved to: {args.output_md}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
