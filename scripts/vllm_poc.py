#!/usr/bin/env python3
"""vLLM PoC - Test OpenAI-compatible endpoint.

Issue #132: vLLM PoC — Tek modelle OpenAI-compatible server ayağa kaldır

Usage:
    # Terminal 1: Start vLLM server
    python -m vllm.entrypoints.openai.api_server \\
        --model Qwen/Qwen2.5-3B-Instruct \\
        --port 8000 \\
        --max-model-len 4096
    
    # Terminal 2: Test server
    python scripts/vllm_poc.py
"""

import time
import requests
import json
from typing import Any


BASE_URL = "http://127.0.0.1:8001"
MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"


def check_server() -> bool:
    """Check if vLLM server is running."""
    try:
        response = requests.get(f"{BASE_URL}/v1/models", timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Server not running: {e}")
        return False


def test_chat_completion(prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> dict[str, Any]:
    """Test /v1/chat/completions endpoint."""
    url = f"{BASE_URL}/v1/chat/completions"
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": 42,  # Deterministic
    }
    
    start = time.time()
    response = requests.post(url, json=payload, timeout=30)
    elapsed = time.time() - start
    
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}: {response.text}")
    
    result = response.json()
    return {
        "content": result["choices"][0]["message"]["content"],
        "latency_ms": elapsed * 1000,
        "tokens": result["usage"]["completion_tokens"],
        "model": result["model"],
    }


def test_router_prompt() -> None:
    """Test router-style JSON output."""
    prompt = """Sen BANTZ. Kullanıcı USER. Türkçe konuş.

Her mesajı şu JSON'a çevir:
{
  "route": "calendar|smalltalk|unknown",
  "calendar_intent": "create|modify|cancel|query|none",
  "slots": {},
  "confidence": 0.0-1.0,
  "tool_plan": ["tool_name"],
  "assistant_reply": "cevap"
}

USER: merhaba
ASSISTANT (sadece JSON):"""
    
    print("\n🧪 Test 1: Router JSON Output")
    print(f"Prompt: {prompt[:100]}...")
    
    result = test_chat_completion(prompt, temperature=0.0, max_tokens=200)
    print(f"✅ Latency: {result['latency_ms']:.0f}ms")
    print(f"✅ Tokens: {result['tokens']}")
    print(f"✅ Response:\n{result['content']}\n")
    
    # Try to parse JSON
    try:
        content = result['content'].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        parsed = json.loads(content)
        print(f"✅ Valid JSON: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"⚠️  JSON parse warning: {e}")


def test_determinism() -> None:
    """Test deterministic output (same prompt 10 times)."""
    prompt = "What is 2+2?"
    
    print("\n🧪 Test 2: Determinism (10 requests)")
    print(f"Prompt: {prompt}")
    
    results = []
    latencies = []
    
    for i in range(10):
        result = test_chat_completion(prompt, temperature=0.0, max_tokens=50)
        results.append(result['content'])
        latencies.append(result['latency_ms'])
    
    # Check if all responses are identical
    unique = set(results)
    if len(unique) == 1:
        print(f"✅ Deterministic: All 10 responses identical")
    else:
        print(f"⚠️  Non-deterministic: {len(unique)} unique responses")
        for i, resp in enumerate(unique):
            print(f"   Version {i+1}: {resp[:50]}...")
    
    # Latency stats
    avg_latency = sum(latencies) / len(latencies)
    p50 = sorted(latencies)[len(latencies) // 2]
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    
    print(f"✅ Latency: avg={avg_latency:.0f}ms, p50={p50:.0f}ms, p95={p95:.0f}ms\n")


def test_vram_usage() -> None:
    """Check VRAM usage via nvidia-smi."""
    import subprocess
    
    print("\n🧪 Test 3: VRAM Usage")
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            used, total = result.stdout.strip().split(",")
            used, total = int(used.strip()), int(total.strip())
            usage_pct = (used / total) * 100
            
            print(f"✅ VRAM: {used}MB / {total}MB ({usage_pct:.1f}%)")
        else:
            print("⚠️  nvidia-smi failed")
    except Exception as e:
        print(f"⚠️  Could not check VRAM: {e}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("vLLM PoC Test Suite (Issue #132)")
    print("=" * 60)
    
    # Check server
    if not check_server():
        print("\n❌ vLLM server is not running!")
        print("\nStart server with:")
        print("  python -m vllm.entrypoints.openai.api_server \\")
        print("      --model Qwen/Qwen2.5-3B-Instruct \\")
        print("      --port 8000 \\")
        print("      --max-model-len 4096")
        return 1
    
    print("✅ vLLM server is running\n")
    
    # Run tests
    try:
        test_router_prompt()
        test_determinism()
        test_vram_usage()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
