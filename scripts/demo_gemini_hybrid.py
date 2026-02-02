#!/usr/bin/env python3
"""Demo: Gemini Hybrid Orchestrator (Issues #131, #134, #135).

Strategy:
- 3B Local Router (vLLM): Fast routing & slot extraction
- Gemini Flash: Natural language response generation

Run:
    python scripts/demo_gemini_hybrid.py

Environment:
    GEMINI_API_KEY or GOOGLE_API_KEY: Gemini API key
    BANTZ_VLLM_URL: vLLM server URL (default: http://localhost:8001)
    BANTZ_VLLM_MODEL: 3B model name (default: Qwen/Qwen2.5-3B-Instruct)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.brain.gemini_hybrid_orchestrator import (
    GeminiHybridOrchestrator,
    HybridOrchestratorConfig,
    create_gemini_hybrid_orchestrator,
)
from bantz.llm.vllm_openai_client import VLLMOpenAIClient


def main():
    print("=" * 80)
    print("GEMINI HYBRID ORCHESTRATOR DEMO")
    print("Issues #131, #134, #135: 3B Router + Gemini Finalizer")
    print("=" * 80)
    print()
    
    # Get Gemini API key
    gemini_api_key = (
        os.environ.get("GEMINI_API_KEY") or
        os.environ.get("GOOGLE_API_KEY") or
        os.environ.get("BANTZ_GEMINI_API_KEY") or
        ""
    ).strip()
    
    if not gemini_api_key:
        print("❌ ERROR: GEMINI_API_KEY environment variable not set")
        print()
        print("Please set one of:")
        print("  export GEMINI_API_KEY='your-api-key'")
        print("  export GOOGLE_API_KEY='your-api-key'")
        print()
        return 1
    
    print(f"✅ Gemini API key: {gemini_api_key[:10]}...{gemini_api_key[-4:]}")
    print()
    
    # Setup configuration
    vllm_url = os.environ.get("BANTZ_VLLM_URL", "http://localhost:8001")
    router_model = os.environ.get("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")
    gemini_model = os.environ.get("BANTZ_GEMINI_MODEL", "gemini-1.5-flash")
    
    config = HybridOrchestratorConfig(
        router_backend="vllm",
        router_model=router_model,
        gemini_model=gemini_model,
        router_temperature=0.0,
        gemini_temperature=0.4,
        confidence_threshold=0.7,
        enable_gemini_finalization=True,
    )
    
    print("Configuration:")
    print(f"  Router Backend: vLLM")
    print(f"  vLLM URL: {vllm_url}")
    print(f"  Router Model: {config.router_model}")
    print(f"  Gemini Model: {config.gemini_model}")
    print(f"  Confidence Threshold: {config.confidence_threshold}")
    print()
    
    # Create vLLM router client
    print("🔧 Initializing vLLM router...")
    router_client = VLLMOpenAIClient(
        base_url=vllm_url,
        model=router_model,
        timeout_seconds=30.0,
    )
    
    if not router_client.is_available():
        print(f"❌ ERROR: vLLM not available at {vllm_url}")
        print()
        print("Please ensure:")
        print("  1. vLLM server is running")
        print(f"  2. Server URL is correct: {vllm_url}")
        print()
        print("Start vLLM server:")
        print(f"  ./scripts/vllm/start_3b.sh")
        print()
        return 1
    
    print(f"✅ vLLM ready with {router_model}")
    print()
    
    # Create orchestrator
    print("🔧 Creating Gemini Hybrid Orchestrator...")
    orchestrator = create_gemini_hybrid_orchestrator(
        router_client=router_client,
        gemini_api_key=gemini_api_key,
        config=config,
    )
    print("✅ Orchestrator ready")
    print()
    
    # Test scenarios (from Issue #126)
    test_cases = [
        {
            "name": "Smalltalk",
            "input": "hey bantz nasılsın",
            "expected_route": "smalltalk",
        },
        {
            "name": "Calendar Query - Today",
            "input": "bugün neler yapacağız bakalım",
            "expected_route": "calendar",
            "expected_intent": "query",
        },
        {
            "name": "Calendar Create - Time",
            "input": "saat 4 için bir toplantı oluştur",
            "expected_route": "calendar",
            "expected_intent": "create",
        },
        {
            "name": "Calendar Query - Evening",
            "input": "bu akşam neler yapacağız",
            "expected_route": "calendar",
            "expected_intent": "query",
        },
        {
            "name": "Calendar Query - Week",
            "input": "bu hafta planımda önemli işler var mı?",
            "expected_route": "calendar",
            "expected_intent": "query",
        },
    ]
    
    print("=" * 80)
    print("TEST SCENARIOS")
    print("=" * 80)
    print()
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"[{i}/{len(test_cases)}] {test['name']}")
        print(f"Input: \"{test['input']}\"")
        print()
        
        try:
            output = orchestrator.orchestrate(
                user_input=test['input'],
                dialog_summary="",
                tool_results=None,
            )
            
            # Check expectations
            route_ok = output.route == test.get("expected_route", output.route)
            intent_ok = (
                "expected_intent" not in test or
                output.calendar_intent == test["expected_intent"]
            )
            
            status = "✅ PASS" if (route_ok and intent_ok) else "⚠️  PARTIAL"
            
            print(f"Status: {status}")
            print(f"  Route: {output.route} (expected: {test.get('expected_route', 'any')})")
            print(f"  Intent: {output.calendar_intent} (expected: {test.get('expected_intent', 'any')})")
            print(f"  Confidence: {output.confidence:.2f}")
            print(f"  Tool Plan: {output.tool_plan}")
            print(f"  Response: \"{output.assistant_reply}\"")
            
            if output.slots:
                print(f"  Slots: {output.slots}")
            
            if output.ask_user:
                print(f"  ❓ Question: {output.question}")
            
            if output.requires_confirmation:
                print(f"  ⚠️  Confirmation: {output.confirmation_prompt}")
            
            results.append({
                "name": test["name"],
                "status": status,
                "route": output.route,
                "intent": output.calendar_intent,
                "confidence": output.confidence,
            })
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "name": test["name"],
                "status": "❌ FAIL",
                "error": str(e),
            })
        
        print()
        print("-" * 80)
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    
    for result in results:
        status = result.get("status", "❌ FAIL")
        name = result["name"]
        print(f"{status} {name}")
        if "error" in result:
            print(f"    Error: {result['error']}")
        else:
            print(f"    Route: {result.get('route')}, Intent: {result.get('intent')}, Confidence: {result.get('confidence', 0):.2f}")
    
    print()
    
    pass_count = sum(1 for r in results if "✅" in r.get("status", ""))
    total_count = len(results)
    
    print(f"Results: {pass_count}/{total_count} passed")
    print()
    
    if pass_count == total_count:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests need attention")
        return 0  # Still return 0 for demo purposes


if __name__ == "__main__":
    sys.exit(main())
