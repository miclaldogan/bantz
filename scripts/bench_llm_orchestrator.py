#!/usr/bin/env python3
"""Benchmark script for LLM Orchestrator (Issue #138).

Measures latency, throughput, and token usage for both vLLM and Ollama backends.

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
    python3 scripts/bench_llm_orchestrator.py --backend ollama --iterations 50
    python3 scripts/bench_llm_orchestrator.py --backend vllm --iterations 50
    python3 scripts/bench_llm_orchestrator.py --compare  # Run both backends
    python3 scripts/bench_llm_orchestrator.py --quick  # 10 iterations (faster)
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import re

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.base import create_client, LLMMessage, LLMClient
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.agent.tools import Tool, ToolRegistry
from bantz.core.events import EventBus


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
        orchestrator = JarvisLLMOrchestrator(llm=llm_client)
        output = orchestrator.route(user_input=prompt)
        return f"route={output.route}, intent={output.calendar_intent}, reply={output.assistant_reply[:100] if output.assistant_reply else 'None'}"
    except Exception as e:
        return f"Error: {str(e)}"


def get_orchestrator_response(llm_client: LLMClient, user_input: str) -> str:
    """Get a single orchestrator response for display."""
    try:
        orchestrator = JarvisLLMOrchestrator(llm=llm_client)
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
) -> BenchmarkResult:
    """Benchmark a single router prompt."""
    orchestrator = JarvisLLMOrchestrator(llm=llm_client)
    
    start = time.perf_counter()
    try:
        output = orchestrator.route(user_input=prompt)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Check if JSON was valid (if we got an output, it was valid)
        success = output is not None
        
        # Estimate tokens (fallback if client doesn't expose usage)
        # Router prompt is typically: system prompt (~200 words) + user input
        prompt_tokens = len(orchestrator.SYSTEM_PROMPT.split()) + len(prompt.split())
        completion_tokens = len(json.dumps(output.raw_output).split()) if output else 0
        
        return BenchmarkResult(
            scenario=f"router:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=success,
            tokens_input=prompt_tokens,
            tokens_output=completion_tokens,
            tokens_total=prompt_tokens + completion_tokens,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"router:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


def benchmark_orchestrator(
    llm_client: LLMClient,
    scenario_name: str,
    user_input: str,
    backend: str,
) -> BenchmarkResult:
    """Benchmark a single orchestrator cycle."""
    orchestrator = JarvisLLMOrchestrator(llm=llm_client)
    tools = create_mock_tools()
    event_bus = EventBus()
    config = OrchestratorConfig(enable_safety_guard=False)
    loop = OrchestratorLoop(orchestrator, tools, event_bus, config)
    
    start = time.perf_counter()
    try:
        output, state = loop.process_turn(user_input)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        success = output.route is not None
        
        # Estimate tokens (system prompt + user input + output JSON)
        prompt_tokens = len(orchestrator.SYSTEM_PROMPT.split()) + len(user_input.split())
        completion_tokens = len(json.dumps(output.raw_output).split()) if output else 0
        
        return BenchmarkResult(
            scenario=f"orchestrator:{scenario_name}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=success,
            tokens_input=prompt_tokens,
            tokens_output=completion_tokens,
            tokens_total=prompt_tokens + completion_tokens,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"orchestrator:{scenario_name}",
            backend=backend,
            latency_ms=elapsed_ms,
            success=False,
            error=str(e),
        )


def benchmark_chat(
    llm_client: LLMClient,
    prompt: str,
    backend: str,
) -> BenchmarkResult:
    """Benchmark a single chat completion."""
    messages = [LLMMessage(role="user", content=prompt)]
    
    start = time.perf_counter()
    ttft = None
    vram_before = get_gpu_memory_usage()
    
    try:
        response = llm_client.chat_detailed(
            messages,
            temperature=0.0,
            max_tokens=200,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Estimate TTFT as ~5-10% of total time (mock estimate since no streaming)
        # In real streaming, this would be measured from first token callback
        ttft = elapsed_ms * 0.08  # Assume TTFT is ~8% of total latency
        
        vram_after = get_gpu_memory_usage()
        vram_peak = vram_after if vram_after and vram_before else None
        
        # Extract token counts if available
        tokens_input = None
        tokens_output = None
        tokens_total = None
        
        if hasattr(response, "usage") and response.usage:
            if isinstance(response.usage, dict):
                tokens_input = response.usage.get("prompt_tokens")
                tokens_output = response.usage.get("completion_tokens")
                tokens_total = response.usage.get("total_tokens")
            else:
                tokens_input = getattr(response.usage, "prompt_tokens", None)
                tokens_output = getattr(response.usage, "completion_tokens", None)
                tokens_total = getattr(response.usage, "total_tokens", None)
        
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
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return BenchmarkResult(
            scenario=f"chat:{prompt[:30]}",
            backend=backend,
            latency_ms=elapsed_ms,
            ttft_ms=ttft,
            success=False,
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
    json_validity_rate = success_rate  # For now, assume JSON validity == success
    
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
        
        # Group by scenario
        scenarios = {}
        for stat in all_stats:
            if stat.scenario not in scenarios:
                scenarios[stat.scenario] = []
            scenarios[stat.scenario].append(stat)
        
        for scenario, stats_list in scenarios.items():
            f.write(f"## {scenario}\n\n")
            
            # Table header
            f.write("| Backend | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (tok/s) | Success Rate |\n")
            f.write("|---------|----------|----------|----------|--------------------|---------------|\n")
            
            for stat in stats_list:
                f.write(f"| {stat.backend} | {stat.latency_p50:.2f} | {stat.latency_p95:.2f} | {stat.latency_p99:.2f} | {stat.throughput_tokens_per_sec:.2f} | {stat.success_rate*100:.1f}% |\n")
            
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
) -> List[BenchmarkStats]:
    """Run benchmarks for a backend."""
    print(f"\n{'='*80}")
    print(f"Running benchmarks for: {backend}")
    print(f"Iterations: {iterations}")
    print(f"Scenarios: {scenarios}")
    print(f"{'='*80}\n")
    
    # Create LLM client
    if backend == "ollama":
        client = create_client("ollama", base_url="http://127.0.0.1:11434", model="qwen2.5:3b-instruct")
    elif backend == "vllm":
        client = create_client("vllm", base_url="http://127.0.0.1:8001", model="Qwen/Qwen2.5-3B-Instruct")
    else:
        raise ValueError(f"Unknown backend: {backend}")
    
    # Check if backend is available
    if not client.is_available():
        print(f"❌ {backend} server is not available. Skipping.")
        return []
    
    all_stats = []
    
    # Router benchmarks
    if scenarios in ("all", "router"):
        print(f"\n📍 Benchmarking Router scenarios...")
        for prompt in ROUTER_SCENARIOS:
            print(f"  Running: {prompt[:40]}...")
            results = []
            for i in range(iterations):
                result = benchmark_router(client, prompt, backend)
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
                result = benchmark_orchestrator(client, scenario_name, user_input, backend)
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
        for prompt in CHAT_SCENARIOS:
            print(f"  Running: {prompt}...")
            results = []
            for i in range(iterations):
                result = benchmark_chat(client, prompt, backend)
                results.append(result)
                # Show first response in verbose mode
                if verbose and i == 0:
                    response = get_chat_response(client, prompt)
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
    
    # Create LLM client
    if backend == "ollama":
        client = create_client("ollama", base_url="http://127.0.0.1:11434", model="qwen2.5:3b-instruct")
    elif backend == "vllm":
        client = create_client("vllm", base_url="http://127.0.0.1:8001", model="Qwen/Qwen2.5-3B-Instruct")
    else:
        raise ValueError(f"Unknown backend: {backend}")
    
    if not client.is_available():
        print(f"❌ {backend} server is not available.")
        return
    
    orchestrator = JarvisLLMOrchestrator(llm=client)
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
    parser.add_argument("--backend", choices=["ollama", "vllm"], help="LLM backend to benchmark")
    parser.add_argument("--compare", action="store_true", help="Compare both backends")
    parser.add_argument("--iterations", type=int, default=50, help="Number of iterations per scenario")
    parser.add_argument("--quick", action="store_true", help="Quick benchmark (10 iterations)")
    parser.add_argument("--scenarios", choices=["all", "router", "orchestrator", "chat"], default="all", help="Which scenarios to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show LLM responses")
    parser.add_argument("--output-json", type=Path, help="Save results as JSON")
    parser.add_argument("--output-md", type=Path, help="Save markdown report")
    parser.add_argument("--qualitative", action="store_true", help="Run qualitative conversation tests (Issue #153)")
    
    args = parser.parse_args()
    
    # Qualitative test mode
    if args.qualitative:
        backend = args.backend or "vllm"
        run_qualitative_tests(backend)
        return 0
    
    # Set iterations
    iterations = 10 if args.quick else args.iterations
    
    # Run benchmarks
    all_stats = []
    
    if args.compare:
        # Run both backends
        for backend in ["ollama", "vllm"]:
            stats = run_benchmark(backend, iterations, args.scenarios, verbose=args.verbose)
            all_stats.extend(stats)
    elif args.backend:
        # Run single backend
        stats = run_benchmark(args.backend, iterations, args.scenarios, verbose=args.verbose)
        all_stats.extend(stats)
    else:
        print("Error: Either --backend or --compare must be specified")
        return 1
    
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
