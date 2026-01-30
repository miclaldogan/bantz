#!/usr/bin/env python3
"""Test LLM confirmation flow for calendar actions."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.brain.llm_router import JarvisLLMRouter
from bantz.llm.ollama_client import OllamaClient, LLMMessage
from bantz.agent.tools import ToolRegistry


class MockToolRegistry(ToolRegistry):
    """Mock tool registry for testing."""
    
    def call_tool(self, tool_name: str, **kwargs):
        print(f"[MOCK TOOL] {tool_name}({kwargs})")
        return {"status": "success", "message": "Mock tool call"}


class RouterLLMWrapper:
    """Wrapper for Ollama to match LLM Router protocol."""
    
    def __init__(self, client: OllamaClient, temperature: float = 0.0):
        self._client = client
        self._temperature = temperature
    
    def complete_text(self, prompt: str) -> str:
        """Simple text completion for router (no JSON mode)."""
        messages = [LLMMessage(role="user", content=prompt)]
        return self._client.chat(
            messages=messages,
            temperature=self._temperature,
            max_tokens=512,
        )


def test_confirmation_flow():
    """Test the confirmation flow with calendar actions."""
    
    print("[TEST] Initializing LLM Router...")
    ollama_client = OllamaClient(model="qwen2.5:3b-instruct")
    router_llm = RouterLLMWrapper(client=ollama_client, temperature=0.0)
    router = JarvisLLMRouter(llm=router_llm)
    
    print("[TEST] Initializing BrainLoop...")
    config = BrainLoopConfig(debug=True)
    tool_registry = MockToolRegistry()
    
    # Create a simple LLM wrapper for BrainLoop
    class SimpleLLM:
        def complete_json(self, messages, schema_hint=None):
            return {"route": "unknown", "calendar_intent": "none", "confidence": 0.0}
    
    brain = BrainLoop(llm=SimpleLLM(), tools=tool_registry, config=config, router=router)
    
    session_context = {
        "user": "test_user",
        "session_id": "test_session",
        "today_window": {"start": "2026-01-30T00:00:00", "end": "2026-01-30T23:59:59"},
        "tomorrow_window": {"start": "2026-01-31T00:00:00", "end": "2026-01-31T23:59:59"},
    }
    
    state = {}
    
    # Test 1: Request calendar action
    print("\n" + "="*60)
    print("[TEST 1] User: 'bu akşam sekize parti ekle'")
    print("="*60)
    
    result = brain.run(
        turn_input="bu akşam sekize parti ekle",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] kind={result.kind}")
    print(f"[RESULT] text={result.text}")
    print(f"[STATE] dialog_state={state.get('_dialog_state')}")
    
    if state.get("_dialog_state") != "PENDING_LLM_CONFIRMATION":
        print("\n❌ FAIL: Expected PENDING_LLM_CONFIRMATION state")
        return False
    
    print("\n✅ PASS: Confirmation requested")
    
    # Test 2a: User confirms with "evet"
    print("\n" + "="*60)
    print("[TEST 2a] User: 'evet'")
    print("="*60)
    
    result = brain.run(
        turn_input="evet",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] kind={result.kind}")
    print(f"[RESULT] text={result.text}")
    print(f"[STATE] dialog_state={state.get('_dialog_state')}")
    
    # Reset for next test
    state = {}
    
    # Test 2b: User rejects with "hayır"
    print("\n" + "="*60)
    print("[TEST 2b] User: 'hayır' (after new request)")
    print("="*60)
    
    result = brain.run(
        turn_input="yarın öğlene toplantı ekle",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] kind={result.kind}")
    print(f"[RESULT] text={result.text}")
    
    if state.get("_dialog_state") != "PENDING_LLM_CONFIRMATION":
        print("\n❌ FAIL: Expected PENDING_LLM_CONFIRMATION state")
        return False
    
    result = brain.run(
        turn_input="hayır",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] kind={result.kind}")
    print(f"[RESULT] text={result.text}")
    print(f"[STATE] dialog_state={state.get('_dialog_state')}")
    
    if state.get("_dialog_state") != "IDLE":
        print("\n❌ FAIL: Expected IDLE state after rejection")
        return False
    
    if "iptal" not in result.text.lower():
        print("\n❌ FAIL: Expected cancellation message")
        return False
    
    print("\n✅ PASS: Rejection handled correctly")
    
    # Test 3: Unclear response
    print("\n" + "="*60)
    print("[TEST 3] User: 'belki' (unclear response)")
    print("="*60)
    
    state = {}
    result = brain.run(
        turn_input="bu gece on bir buçukta uyku zamanı koy",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] text={result.text}")
    
    result = brain.run(
        turn_input="belki",
        session_context=session_context,
        context=state,
    )
    
    print(f"\n[RESULT] kind={result.kind}")
    print(f"[RESULT] text={result.text}")
    print(f"[STATE] dialog_state={state.get('_dialog_state')}")
    
    if state.get("_dialog_state") != "PENDING_LLM_CONFIRMATION":
        print("\n❌ FAIL: Expected to stay in PENDING_LLM_CONFIRMATION state")
        return False
    
    if "evet" not in result.text.lower() or "hayır" not in result.text.lower():
        print("\n❌ FAIL: Expected clarification question")
        return False
    
    print("\n✅ PASS: Unclear response handled with clarification")
    
    print("\n" + "="*60)
    print("✅ ALL TESTS PASSED")
    print("="*60)
    return True


if __name__ == "__main__":
    try:
        success = test_confirmation_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
