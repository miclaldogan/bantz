"""Benchmark Hybrid Quality: 3B-only vs 3B+7B (Issue #157).

Compares response quality between:
- Baseline: 3B-only (router + finalizer both 3B)
- Hybrid: 3B router + 7B finalizer

Metrics:
- Naturalness score (manual rating 1-5)
- Response length (chars)
- Turkish quality
- Context retention
- TTFT latency
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.flexible_hybrid_orchestrator import (
    FlexibleHybridOrchestrator,
    FlexibleHybridConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Single benchmark result."""
    
    test_id: int
    user_input: str
    mode: str  # "3b_only" or "hybrid_7b"
    
    # Outputs
    route: str
    intent: str
    response: str
    response_length: int
    
    # Timing
    ttft_ms: int
    total_ms: int
    
    # Quality (manual rating)
    naturalness_score: int = 0  # 1-5 (set manually)
    turkish_quality: str = ""  # good/ok/poor (set manually)
    context_retention: str = ""  # good/ok/poor (set manually)


# Test cases (Issue #126 scenarios + new ones)
TEST_CASES = [
    # Smalltalk
    "hey bantz nasılsın",
    "merhaba iyi günler",
    "bugün hava nasıl",
    "teşekkür ederim",
    "görüşürüz",
    
    # Calendar queries
    "bugün neler yapacağız",
    "bu akşam neler yapacağız",
    "bu hafta önemli işler var mı",
    "yarın toplantım var mı",
    "önümüzdeki pazartesi ne yapmam gerek",
    
    # Calendar create
    "yarın saat 2 için toplantı ayarla",
    "bu akşam yemek randevusu oluştur",
    "gelecek hafta cuma kahve buluşması ekle",
    "önümüzdeki salı saat 10'da doktor randevusu",
    
    # Calendar modify
    "yarınki toplantıyı saat 3'e al",
    "bu akşamki randevuyu iptal et",
    
    # Complex queries
    "bu hafta en yoğun gün hangisi",
    "gelecek ay kaç toplantım var",
    "bugün boş saatlerim var mı",
    
    # Follow-up scenarios
    "evet ayarla",
    "hayır iptal et",
    "daha fazla detay ver",
    "tamam onaylıyorum",
    
    # Edge cases
    "anlayamadım tekrar söyler misin",
    "başka bir önerim var",
    "bu konuda yardım lazım",
]


def run_benchmark_3b_only(
    router_client: VLLMOpenAIClient,
    test_id: int,
    user_input: str,
) -> BenchmarkResult:
    """Run benchmark with 3B-only (no hybrid)."""
    
    logger.info(f"[3B-ONLY] Test {test_id}: {user_input}")
    
    # Create 3B-only orchestrator
    orchestrator = JarvisLLMOrchestrator(llm_client=router_client)
    
    # Run
    start = time.perf_counter()
    output = orchestrator.plan(user_input=user_input)
    total_ms = int((time.perf_counter() - start) * 1000)
    
    result = BenchmarkResult(
        test_id=test_id,
        user_input=user_input,
        mode="3b_only",
        route=output.route,
        intent=output.calendar_intent,
        response=output.assistant_reply,
        response_length=len(output.assistant_reply),
        ttft_ms=total_ms,  # No separate TTFT for 3B-only
        total_ms=total_ms,
    )
    
    logger.info(f"  → Response ({total_ms}ms): {output.assistant_reply[:80]}...")
    return result


def run_benchmark_hybrid_7b(
    router_client: VLLMOpenAIClient,
    finalizer_client: VLLMOpenAIClient,
    test_id: int,
    user_input: str,
) -> BenchmarkResult:
    """Run benchmark with 3B+7B hybrid."""
    
    logger.info(f"[HYBRID-7B] Test {test_id}: {user_input}")
    
    # Create hybrid orchestrator
    config = FlexibleHybridConfig(
        finalizer_type="vllm_7b",
        finalizer_temperature=0.6,
    )
    
    jarvis_router = JarvisLLMOrchestrator(llm_client=router_client)
    
    orchestrator = FlexibleHybridOrchestrator(
        router_orchestrator=jarvis_router,
        finalizer=finalizer_client,
        config=config,
    )
    
    # Run (measure TTFT separately)
    start = time.perf_counter()
    output = orchestrator.plan(user_input=user_input)
    total_ms = int((time.perf_counter() - start) * 1000)
    
    result = BenchmarkResult(
        test_id=test_id,
        user_input=user_input,
        mode="hybrid_7b",
        route=output.route,
        intent=output.calendar_intent,
        response=output.assistant_reply,
        response_length=len(output.assistant_reply),
        ttft_ms=total_ms,  # Simplified: total time
        total_ms=total_ms,
    )
    
    logger.info(f"  → Response ({total_ms}ms): {output.assistant_reply[:80]}...")
    return result


def main():
    parser = argparse.ArgumentParser(description="Benchmark 3B-only vs 3B+7B hybrid")
    parser.add_argument(
        "--router-url",
        default=os.getenv("BANTZ_ROUTER_URL", "http://localhost:8001"),
        help="3B router vLLM URL (default: localhost:8001)",
    )
    parser.add_argument(
        "--finalizer-url",
        default=os.getenv("BANTZ_FINALIZER_URL", "http://localhost:8002"),
        help="7B finalizer vLLM URL (default: localhost:8002)",
    )
    parser.add_argument(
        "--router-model",
        default="Qwen/Qwen2.5-3B-Instruct",
        help="3B router model",
    )
    parser.add_argument(
        "--finalizer-model",
        default="Qwen/Qwen2.5-7B-Instruct",
        help="7B finalizer model",
    )
    parser.add_argument(
        "--output",
        default="artifacts/results/bench_hybrid_quality.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--num-tests",
        type=int,
        default=len(TEST_CASES),
        help=f"Number of test cases to run (max {len(TEST_CASES)})",
    )
    
    args = parser.parse_args()
    
    # Create clients
    logger.info(f"Router: {args.router_url} ({args.router_model})")
    logger.info(f"Finalizer: {args.finalizer_url} ({args.finalizer_model})")
    
    router_client = VLLMOpenAIClient(
        base_url=args.router_url,
        model=args.router_model,
    )
    
    finalizer_client = VLLMOpenAIClient(
        base_url=args.finalizer_url,
        model=args.finalizer_model,
    )
    
    # Check availability
    if not router_client.is_available():
        logger.error(f"Router not available: {args.router_url}")
        sys.exit(1)
    
    if not finalizer_client.is_available():
        logger.error(f"Finalizer not available: {args.finalizer_url}")
        logger.warning("Will skip hybrid tests")
        finalizer_available = False
    else:
        finalizer_available = True
    
    # Run benchmarks
    results_3b = []
    results_hybrid = []
    
    test_cases = TEST_CASES[:args.num_tests]
    
    for i, test_input in enumerate(test_cases, start=1):
        logger.info(f"\n{'='*80}")
        logger.info(f"Test {i}/{len(test_cases)}: {test_input}")
        logger.info(f"{'='*80}")
        
        # 3B-only
        try:
            result_3b = run_benchmark_3b_only(router_client, i, test_input)
            results_3b.append(result_3b)
        except Exception as e:
            logger.error(f"3B-only test failed: {e}")
        
        # Hybrid 7B
        if finalizer_available:
            try:
                result_hybrid = run_benchmark_hybrid_7b(
                    router_client,
                    finalizer_client,
                    i,
                    test_input,
                )
                results_hybrid.append(result_hybrid)
            except Exception as e:
                logger.error(f"Hybrid test failed: {e}")
    
    # Compute statistics
    logger.info(f"\n{'='*80}")
    logger.info("BENCHMARK RESULTS")
    logger.info(f"{'='*80}")
    
    if results_3b:
        avg_ttft_3b = sum(r.ttft_ms for r in results_3b) / len(results_3b)
        avg_length_3b = sum(r.response_length for r in results_3b) / len(results_3b)
        logger.info(f"3B-only: {len(results_3b)} tests")
        logger.info(f"  Avg TTFT: {avg_ttft_3b:.0f}ms")
        logger.info(f"  Avg Response Length: {avg_length_3b:.0f} chars")
    
    if results_hybrid:
        avg_ttft_hybrid = sum(r.ttft_ms for r in results_hybrid) / len(results_hybrid)
        avg_length_hybrid = sum(r.response_length for r in results_hybrid) / len(results_hybrid)
        logger.info(f"\nHybrid 7B: {len(results_hybrid)} tests")
        logger.info(f"  Avg TTFT: {avg_ttft_hybrid:.0f}ms")
        logger.info(f"  Avg Response Length: {avg_length_hybrid:.0f} chars")
        
        if results_3b:
            improvement = ((avg_length_hybrid - avg_length_3b) / avg_length_3b) * 100
            logger.info(f"  Response Length Improvement: {improvement:+.1f}%")
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "metadata": {
                    "router_url": args.router_url,
                    "router_model": args.router_model,
                    "finalizer_url": args.finalizer_url,
                    "finalizer_model": args.finalizer_model,
                    "num_tests": len(test_cases),
                },
                "results_3b_only": [asdict(r) for r in results_3b],
                "results_hybrid_7b": [asdict(r) for r in results_hybrid],
                "statistics": {
                    "3b_only": {
                        "count": len(results_3b),
                        "avg_ttft_ms": avg_ttft_3b if results_3b else 0,
                        "avg_response_length": avg_length_3b if results_3b else 0,
                    },
                    "hybrid_7b": {
                        "count": len(results_hybrid),
                        "avg_ttft_ms": avg_ttft_hybrid if results_hybrid else 0,
                        "avg_response_length": avg_length_hybrid if results_hybrid else 0,
                    } if results_hybrid else {},
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    
    logger.info(f"\n✅ Results saved to: {output_path}")
    logger.info("\n📝 Next steps:")
    logger.info("1. Manually review responses in JSON file")
    logger.info("2. Add naturalness_score (1-5) for each result")
    logger.info("3. Add turkish_quality (good/ok/poor)")
    logger.info("4. Add context_retention (good/ok/poor)")
    logger.info("5. Compute final quality metrics")


if __name__ == "__main__":
    main()
