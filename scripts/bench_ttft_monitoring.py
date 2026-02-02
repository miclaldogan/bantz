"""Enhanced LLM Benchmark with TTFT Monitoring (Issue #158).

Comprehensive benchmarking with:
- TTFT measurement (p50, p95, p99)
- Streaming vs non-streaming comparison
- Threshold enforcement
- Real-time dashboard data
- Performance regression detection
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, asdict

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.ttft_monitor import TTFTMonitor
from bantz.llm.base import LLMMessage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# Test prompts (varying lengths for comprehensive TTFT testing)
TEST_PROMPTS = [
    # Short prompts (smalltalk)
    "merhaba",
    "nasılsın",
    "teşekkürler",
    "görüşürüz",
    "bugün hava nasıl",
    
    # Medium prompts (calendar queries)
    "bugün ne işlerim var",
    "bu akşam neler yapacağız",
    "yarın toplantım var mı",
    "bu hafta önemli işler var mı",
    "önümüzdeki pazartesi ne yapmam gerek",
    
    # Long prompts (complex queries)
    "bu hafta en yoğun gün hangisi ve o gün ne gibi işler var detaylı anlat",
    "gelecek ay kaç toplantım var ve bunların hangiler önemli hangiler rutin",
    "bugünden itibaren önümüzdeki 2 hafta içinde boş saatlerim hangi günlerde var",
    
    # Calendar creates (structured)
    "yarın saat 2 için toplantı ayarla başlığı ekip sync olsun",
    "bu akşam saat 7de yemek randevusu oluştur",
    "gelecek hafta cuma kahve buluşması ekle saat 10da",
]


@dataclass
class BenchmarkResult:
    """Single benchmark test result."""
    
    test_id: int
    prompt: str
    prompt_length: int
    
    # Timing
    ttft_ms: int
    total_ms: int
    
    # Response
    response: str
    response_length: int
    tokens_used: int
    
    # Metadata
    model: str
    backend: str
    phase: str
    stream_mode: bool


def run_benchmark_non_streaming(
    client: VLLMOpenAIClient,
    test_id: int,
    prompt: str,
    phase: str = "router",
) -> BenchmarkResult:
    """Run benchmark in non-streaming mode."""
    
    logger.info(f"[NON-STREAM] Test {test_id}: {prompt[:50]}...")
    
    messages = [LLMMessage(role="user", content=prompt)]
    
    t0 = time.perf_counter()
    response = client.chat_detailed(messages, temperature=0.0, max_tokens=256)
    total_ms = int((time.perf_counter() - t0) * 1000)
    
    # TTFT approximation for non-streaming (total time)
    ttft_ms = total_ms
    
    result = BenchmarkResult(
        test_id=test_id,
        prompt=prompt,
        prompt_length=len(prompt),
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        response=response.content,
        response_length=len(response.content),
        tokens_used=response.tokens_used,
        model=client.model_name,
        backend=client.backend_name,
        phase=phase,
        stream_mode=False,
    )
    
    logger.info(f"  → TTFT={ttft_ms}ms, Total={total_ms}ms, Tokens={result.tokens_used}")
    return result


def run_benchmark_streaming(
    client: VLLMOpenAIClient,
    test_id: int,
    prompt: str,
    phase: str = "router",
) -> BenchmarkResult:
    """Run benchmark in streaming mode with accurate TTFT."""
    
    logger.info(f"[STREAM] Test {test_id}: {prompt[:50]}...")
    
    messages = [LLMMessage(role="user", content=prompt)]
    
    t0 = time.perf_counter()
    ttft_ms = None
    response_parts = []
    
    for chunk in client.chat_stream(messages, temperature=0.0, max_tokens=256):
        if chunk.is_first_token and chunk.ttft_ms is not None:
            ttft_ms = chunk.ttft_ms
            logger.debug(f"  [FIRST TOKEN] TTFT={ttft_ms}ms")
        
        response_parts.append(chunk.content)
    
    total_ms = int((time.perf_counter() - t0) * 1000)
    response = "".join(response_parts)
    
    # Fallback if TTFT not measured
    if ttft_ms is None:
        ttft_ms = total_ms
    
    result = BenchmarkResult(
        test_id=test_id,
        prompt=prompt,
        prompt_length=len(prompt),
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        response=response,
        response_length=len(response),
        tokens_used=len(response_parts),  # Approximate
        model=client.model_name,
        backend=client.backend_name,
        phase=phase,
        stream_mode=True,
    )
    
    logger.info(f"  → TTFT={ttft_ms}ms, Total={total_ms}ms, Tokens≈{result.tokens_used}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Enhanced LLM Benchmark with TTFT Monitoring")
    parser.add_argument(
        "--url",
        default=os.getenv("BANTZ_VLLM_URL", "http://localhost:8001"),
        help="vLLM server URL (default: localhost:8001)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
        help="Model name",
    )
    parser.add_argument(
        "--phase",
        default="router",
        choices=["router", "finalizer"],
        help="Phase name for TTFT tracking",
    )
    parser.add_argument(
        "--mode",
        default="both",
        choices=["stream", "non-stream", "both"],
        help="Test mode: streaming, non-streaming, or both",
    )
    parser.add_argument(
        "--num-tests",
        type=int,
        default=len(TEST_PROMPTS),
        help=f"Number of test prompts to use (max {len(TEST_PROMPTS)})",
    )
    parser.add_argument(
        "--output",
        default="artifacts/results/bench_ttft.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        help="TTFT p95 threshold in ms (default: 300 for router, 500 for finalizer)",
    )
    
    args = parser.parse_args()
    
    # Set threshold
    if args.threshold:
        threshold_ms = args.threshold
    else:
        threshold_ms = 300 if args.phase == "router" else 500
    
    logger.info(f"Benchmark configuration:")
    logger.info(f"  URL: {args.url}")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  Phase: {args.phase}")
    logger.info(f"  Mode: {args.mode}")
    logger.info(f"  TTFT p95 Threshold: {threshold_ms}ms")
    
    # Initialize TTFT monitor
    monitor = TTFTMonitor.get_instance()
    monitor.set_threshold(args.phase, threshold_ms)
    
    # Create client
    client = VLLMOpenAIClient(
        base_url=args.url,
        model=args.model,
        track_ttft=True,
        ttft_phase=args.phase,
    )
    
    # Check availability
    if not client.is_available():
        logger.error(f"vLLM server not available: {args.url}")
        sys.exit(1)
    
    logger.info(f"✅ vLLM server available")
    
    # Run benchmarks
    results_stream = []
    results_non_stream = []
    
    prompts = TEST_PROMPTS[:args.num_tests]
    
    for i, prompt in enumerate(prompts, start=1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Test {i}/{len(prompts)}")
        logger.info(f"{'='*80}")
        
        # Non-streaming mode
        if args.mode in ["non-stream", "both"]:
            try:
                result = run_benchmark_non_streaming(client, i, prompt, args.phase)
                results_non_stream.append(result)
            except Exception as e:
                logger.error(f"Non-streaming test failed: {e}")
        
        # Streaming mode
        if args.mode in ["stream", "both"]:
            try:
                result = run_benchmark_streaming(client, i, prompt, args.phase)
                results_stream.append(result)
            except Exception as e:
                logger.error(f"Streaming test failed: {e}")
    
    # Print summary
    print("\n" + "="*80)
    print("BENCHMARK RESULTS")
    print("="*80)
    
    if results_non_stream:
        ttfts = [r.ttft_ms for r in results_non_stream]
        avg_ttft = sum(ttfts) / len(ttfts)
        print(f"\nNon-Streaming: {len(results_non_stream)} tests")
        print(f"  Avg TTFT: {avg_ttft:.1f}ms")
    
    if results_stream:
        ttfts = [r.ttft_ms for r in results_stream]
        avg_ttft = sum(ttfts) / len(ttfts)
        print(f"\nStreaming: {len(results_stream)} tests")
        print(f"  Avg TTFT: {avg_ttft:.1f}ms")
    
    # TTFT statistics from monitor
    print("\n")
    monitor.print_summary()
    
    # Export results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get monitor statistics
    stats = monitor.get_statistics(args.phase)
    
    report = {
        "metadata": {
            "url": args.url,
            "model": args.model,
            "phase": args.phase,
            "mode": args.mode,
            "num_tests": len(prompts),
            "threshold_ms": threshold_ms,
        },
        "results_non_stream": [asdict(r) for r in results_non_stream],
        "results_stream": [asdict(r) for r in results_stream],
        "ttft_statistics": stats.summary() if stats else {},
        "monitor_report": monitor.export_report(),
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n✅ Results saved to: {output_path}")
    
    # Check thresholds
    if not monitor.check_thresholds():
        logger.error("❌ TTFT threshold violation detected!")
        sys.exit(1)
    else:
        logger.info("✅ All TTFT thresholds met!")


if __name__ == "__main__":
    main()
