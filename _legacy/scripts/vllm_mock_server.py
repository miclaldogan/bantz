#!/usr/bin/env python3
"""vLLM PoC - Mock server for testing without GPU.

Issue #132: vLLM PoC — Spin up OpenAI-compatible server with a single model

This mock server simulates vLLM responses for testing purposes when:
- GPU not available
- vLLM not installed
- Development on CPU-only machine

Usage:
    # Terminal 1: Start mock server
    python scripts/vllm_mock_server.py
    
    # Terminal 2: Test server
    python scripts/vllm_poc.py
"""

from flask import Flask, request, jsonify
import time
import json
import sys
import json

app = Flask(__name__)

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct-AWQ"


@app.route("/v1/models", methods=["GET"])
def list_models():
    """List available models."""
    return jsonify({
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mock-vllm"
            }
        ]
    })


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """Handle chat completion requests."""
    data = request.json
    messages = data.get("messages", [])
    temperature = data.get("temperature", 0.0)
    
    # Extract last user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    # Generate mock response based on prompt
    response_content = generate_mock_response(user_message, temperature)
    
    # Simulate processing time
    time.sleep(0.1)  # Mock latency
    
    # FIX: Token estimation - use full messages for prompt length
    # Construct approximate prompt from all messages
    full_prompt = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages])
    
    # Realistic token estimation (rough approximation: 1 token ≈ 4 chars for Turkish)
    prompt_tokens = max(len(full_prompt.split()), len(full_prompt) // 4)
    completion_tokens = max(len(response_content.split()), len(response_content) // 4)
    
    return jsonify({
        "id": f"chatcmpl-mock-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    })


def generate_mock_response(prompt: str, temperature: float) -> str:
    """Generate mock response based on prompt pattern."""
    
    prompt_lower = prompt.lower()
    
    # Extract user input from router prompt (after "USER:")
    user_input = prompt_lower
    if "user:" in prompt_lower:
        # Get the last line after "USER:" marker
        user_lines = prompt_lower.split("user:")
        if len(user_lines) > 1:
            # Take the last "USER:" occurrence and extract just that line
            last_user_section = user_lines[-1].strip()
            # Get first line (before "ASSISTANT" if present)
            user_input = last_user_section.split("\n")[0].strip()
            user_input = user_input.split("assistant")[0].strip()
    
    # Pattern matching on extracted user input
    # Greeting - check FIRST (more specific)
    if any(word in user_input for word in ["merhaba", "selam", "hey"]) and \
       any(word in user_input for word in ["nasılsın", "iyi misin", "bantz"]):
        return json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "Merhaba efendim! Nasıl yardımcı olabilirim?"
        }, ensure_ascii=False, indent=2)
    
    # Self introduction
    elif any(word in user_input for word in ["kendini tanıt", "kimsin", "nesin"]):
        return json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 1.0,
            "tool_plan": [],
            "assistant_reply": "Ben Bantz, senin kişisel asistanınım! Takvim yönetimi, hatırlatıcılar ve daha fazlası için buradayım."
        }, ensure_ascii=False, indent=2)
    
    # Weather query
    elif "hava" in user_input and ("nasıl" in user_input or "durumu" in user_input):
        return json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "Hava durumu servisi henüz aktif değil, ama sana yardımcı olmak isterim!"
        }, ensure_ascii=False, indent=2)
    
    # Calendar queries - check for time words + action words
    elif any(word in user_input for word in ["bugün", "bu akşam", "yarın", "hafta", "cumartesi"]) and \
         any(word in user_input for word in ["neler", "yapacağız", "yapıyoruz", "planımda", "randevum"]):
        return json.dumps({
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today" if "bugün" in user_input else "week"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": ""
        }, ensure_ascii=False, indent=2)
    
    # Calendar create
    elif any(word in user_input for word in ["toplantı", "randevu", "etkinlik"]) and \
         any(word in user_input for word in ["oluştur", "ekle", "koy", "yap"]):
        return json.dumps({
            "route": "calendar",
            "calendar_intent": "create",
            "slots": {"time": "16:00", "title": "toplantı"},
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": ""
        }, ensure_ascii=False, indent=2)
    
    # Calendar list/show
    elif any(word in user_input for word in ["takvim", "program", "ajanda"]) and \
         any(word in user_input for word in ["göster", "bak", "listele"]):
        return json.dumps({
            "route": "calendar",
            "calendar_intent": "query",
            "slots": {"window_hint": "today"},
            "confidence": 0.9,
            "tool_plan": ["calendar.list_events"],
            "assistant_reply": ""
        }, ensure_ascii=False, indent=2)
    
    # Default smalltalk for unrecognized input
    else:
        return json.dumps({
            "route": "smalltalk",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.7,
            "tool_plan": [],
            "assistant_reply": "Anlayamadım, daha açık bir şekilde söyler misin?"
        }, ensure_ascii=False, indent=2)

    
    # Simple math prompt
    if "2+2" in prompt or "2 + 2" in prompt:
        return "4"
    
    # Default chat response
    if len(prompt) < 100:  # Short prompts are likely direct chat
        return f"İlginç bir soru! '{prompt[:50]}' hakkında düşünüyorum..."
    
    # Default response
    return f"Mock response to: {prompt[:50]}..."


def main():
    """Start mock server."""
    print("=" * 60)
    print("vLLM Mock Server (Issue #132)")
    print("=" * 60)
    print("\n⚠️  This is a MOCK server for testing without GPU")
    print("Real vLLM server provides actual LLM inference\n")
    print("Server running on: http://127.0.0.1:8001")
    print("Press Ctrl+C to stop\n")
    
    app.run(host="127.0.0.1", port=8001, debug=False)


if __name__ == "__main__":
    main()
