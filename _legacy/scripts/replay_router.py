#!/usr/bin/env python3
"""Replay Router Misroutes.

Issue #238: Replay misroute dataset through router for accuracy testing.

Usage:
    python scripts/replay_router.py                    # Replay all
    python scripts/replay_router.py --limit 50         # Replay first 50
    python scripts/replay_router.py --stats            # Show stats only
    python scripts/replay_router.py --export out.json  # Export dataset
    python scripts/replay_router.py --format json      # Output as JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bantz.router.misroute_collector import (
    DEFAULT_DATASET_PATH,
    MisrouteDataset,
    ReplaySummary,
    get_dataset_stats,
    replay_dataset,
)


# ============================================================================
# MOCK ROUTER (for testing without vLLM)
# ============================================================================

def mock_router(user_text: str) -> dict:
    """Simple mock router for testing replay without LLM.
    
    This is a pattern-matching fallback router.
    """
    text = user_text.lower().strip()
    
    # Calendar patterns
    if any(w in text for w in ["takvim", "etkinlik", "toplantı", "randevu", "bugün", "yarın"]):
        if any(w in text for w in ["ekle", "oluştur", "ayarla"]):
            return {"route": "calendar", "intent": "create", "slots": {}, "confidence": 0.7}
        else:
            return {"route": "calendar", "intent": "query", "slots": {}, "confidence": 0.7}
    
    # Gmail patterns
    if any(w in text for w in ["mail", "e-posta", "email", "inbox"]):
        if any(w in text for w in ["gönder", "yaz"]):
            return {"route": "gmail", "intent": "send", "slots": {}, "confidence": 0.7}
        else:
            return {"route": "gmail", "intent": "read", "slots": {}, "confidence": 0.7}
    
    # System patterns
    if any(w in text for w in ["saat", "tarih", "cpu", "ram", "sistem"]):
        return {"route": "system", "intent": "query", "slots": {}, "confidence": 0.8}
    
    # Smalltalk patterns
    if any(w in text for w in ["merhaba", "selam", "nasılsın", "günaydın", "iyi geceler"]):
        return {"route": "smalltalk", "intent": "greeting", "slots": {}, "confidence": 0.9}
    
    return {"route": "unknown", "intent": "fallback", "slots": {}, "confidence": 0.3}


# ============================================================================
# vLLM ROUTER (actual router)
# ============================================================================

def create_vllm_router() -> Optional[callable]:
    """Create vLLM router function if available."""
    try:
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        # Check if vLLM is running
        import requests
        try:
            resp = requests.get(
                os.getenv("BANTZ_VLLM_BASE", "http://localhost:8001") + "/health",
                timeout=2,
            )
            if resp.status_code != 200:
                return None
        except Exception:
            return None
        
        # Create orchestrator
        orchestrator = JarvisLLMOrchestrator()
        
        def router_fn(user_text: str) -> dict:
            """Route using actual LLM."""
            result = orchestrator.route(user_text)
            return {
                "route": result.get("route", "unknown"),
                "intent": result.get("calendar_intent", result.get("intent", "")),
                "slots": result.get("slots", {}),
                "confidence": result.get("confidence", 0.0),
            }
        
        return router_fn
        
    except ImportError:
        return None


# ============================================================================
# MAIN
# ============================================================================

def show_stats(dataset_path: str, format_json: bool = False) -> None:
    """Show dataset statistics."""
    stats = get_dataset_stats(dataset_path)
    
    if format_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return
    
    print("=" * 60)
    print("Router Misroute Dataset Statistics")
    print("=" * 60)
    print(f"\nTotal Records: {stats['total']}")
    
    if stats["total"] == 0:
        print("\nNo records in dataset yet.")
        return
    
    print(f"\nTime Range:")
    print(f"  First: {stats.get('first_record', 'N/A')}")
    print(f"  Last:  {stats.get('last_record', 'N/A')}")
    
    print("\nBy Reason:")
    for reason, count in sorted(stats.get("by_reason", {}).items(), key=lambda x: -x[1]):
        pct = count / stats["total"] * 100
        print(f"  {reason}: {count} ({pct:.1f}%)")
    
    print("\nBy Route:")
    for route, count in sorted(stats.get("by_route", {}).items(), key=lambda x: -x[1]):
        pct = count / stats["total"] * 100
        print(f"  {route}: {count} ({pct:.1f}%)")
    
    print("\nBy Model:")
    for model, count in sorted(stats.get("by_model", {}).items(), key=lambda x: -x[1]):
        pct = count / stats["total"] * 100
        print(f"  {model}: {count} ({pct:.1f}%)")


def run_replay(
    dataset_path: str,
    use_mock: bool = False,
    limit: Optional[int] = None,
    format_json: bool = False,
) -> None:
    """Run replay and show results."""
    
    # Select router
    if use_mock:
        print("Using mock router (pattern matching)")
        router_fn = mock_router
    else:
        router_fn = create_vllm_router()
        if router_fn is None:
            print("vLLM not available, falling back to mock router")
            router_fn = mock_router
        else:
            print("Using vLLM router")
    
    # Run replay
    print(f"\nReplaying dataset: {dataset_path}")
    if limit:
        print(f"Limit: {limit} records")
    print("-" * 40)
    
    summary = replay_dataset(router_fn, dataset_path, limit)
    
    if format_json:
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(summary.format_markdown())


def export_dataset(dataset_path: str, output_path: str) -> None:
    """Export dataset to JSON."""
    dataset = MisrouteDataset(path=dataset_path, redact=False)
    count = dataset.export_json(output_path)
    print(f"Exported {count} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Replay router misroutes for accuracy testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET_PATH,
        help=f"Path to misroute dataset (default: {DEFAULT_DATASET_PATH})",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show dataset statistics only",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records to replay",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock router instead of vLLM",
    )
    parser.add_argument(
        "--export",
        metavar="PATH",
        help="Export dataset to JSON file",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    
    args = parser.parse_args()
    format_json = args.format == "json"
    
    # Check dataset exists
    dataset_path = args.dataset
    if not Path(dataset_path).exists():
        print(f"Dataset not found: {dataset_path}")
        print("No misroutes have been logged yet.")
        return 1
    
    # Handle commands
    if args.export:
        export_dataset(dataset_path, args.export)
        return 0
    
    if args.stats:
        show_stats(dataset_path, format_json)
        return 0
    
    # Default: run replay
    run_replay(
        dataset_path=dataset_path,
        use_mock=args.mock,
        limit=args.limit,
        format_json=format_json,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
