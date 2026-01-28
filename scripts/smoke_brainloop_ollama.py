from __future__ import annotations

# ruff: noqa: E402

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

# Allow running directly from repo root without an editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.brain.json_repair import RepairLLM, validate_or_repair_action
from bantz.llm.ollama_client import LLMMessage, OllamaClient


class OllamaTextLLM(RepairLLM):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ):
        self._client = OllamaClient(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        self.calls = 0

    @property
    def base_url(self) -> str:
        return self._client.base_url

    @property
    def model(self) -> str:
        return self._client.model

    def is_available(self) -> bool:
        return self._client.is_available()

    def complete_text(self, *, prompt: str) -> str:
        self.calls += 1
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "Sadece tek bir JSON object döndür. "
                    "Markdown/backtick/açıklama yazma. "
                    "JSON dışı hiçbir şey üretme."
                ),
            ),
            LLMMessage(role="user", content=prompt),
        ]
        return self._client.chat(
            messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )


class RepairingLLMAdapter:
    """Adapter that turns text LLM output into strict JSON actions using #86 repair loop."""

    def __init__(self, *, llm: RepairLLM, tools: ToolRegistry, max_attempts: int = 2):
        self._llm = llm
        self._tools = tools
        self._max_attempts = max_attempts

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict[str, Any]:
        conversation_tail = "\n".join(
            [
                f"{m.get('role','')}: {m.get('content','')}"
                for m in messages[-6:]
                if isinstance(m, dict)
            ]
        )

        prompt = (
            "Görev: Aşağıdaki şemaya uygun şekilde yalnızca tek bir JSON object döndür.\n"
            "Kurallar: Output sadece JSON object; ekstra alan yok; Markdown yok.\n"
            "Zorunlu: 'type' alanını birebir kullan. type ∈ {SAY, CALL_TOOL, ASK_USER, FAIL}.\n"
            "Not: type='SAY' ise 'text' kısa ve doğal Türkçe olmalı; JSON dump veya observation ham metni kopyalama.\n"
            "Kontrol kuralı: Eğer CONVERSATION_TAIL içinde 'Observation (tool sonucu)' görüyorsan, artık CALL_TOOL yapma; FINAL olarak SAY döndür.\n"
            "Şekil örnekleri:\n"
            "- SAY => {\"type\":\"SAY\",\"text\":\"...\"}\n"
            "- CALL_TOOL => {\"type\":\"CALL_TOOL\",\"name\":\"echo\",\"params\":{\"text\":\"merhaba\"}}\n\n"
            f"SCHEMA_HINT:\n{schema_hint}\n\n"
            f"CONVERSATION_TAIL:\n{conversation_tail}\n"
        )

        raw_text = self._llm.complete_text(prompt=prompt)
        return validate_or_repair_action(
            llm=self._llm,
            raw_text=raw_text,
            tool_registry=self._tools,
            max_attempts=self._max_attempts,
        )


def _build_tools() -> ToolRegistry:
    tools = ToolRegistry()

    def echo(text: str) -> dict[str, Any]:
        return {"ok": True, "echo": text}

    tools.register(
        Tool(
            name="echo",
            description="Echo tool",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            function=echo,
        )
    )

    return tools


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual BrainLoop smoke test using Ollama")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-model", default="qwen2.5:3b-instruct")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    tools = _build_tools()

    llm = OllamaTextLLM(
        base_url=args.ollama_url,
        model=args.ollama_model,
        timeout_seconds=args.timeout,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    if not llm.is_available():
        print(f"Ollama erişilemedi: {llm.base_url}")
        print("- Başlat: ollama serve")
        print(f"- Model indir: ollama pull {args.ollama_model}")
        return 2

    adapter = RepairingLLMAdapter(llm=llm, tools=tools)
    loop = BrainLoop(llm=adapter, tools=tools, config=BrainLoopConfig(max_steps=args.max_steps, debug=bool(args.debug)))

    turn_input = (
        "echo toolunu CALL_TOOL ile çağır. params: {text: 'merhaba'}. "
        "Observation geldikten sonra sonucu SAY ile kısa Türkçe bir cümleyle özetle."
    )

    result = loop.run(turn_input=turn_input, session_context={"user": "demo"})

    print("Ollama:", llm.base_url, "/", llm.model)
    print("LLM calls:", llm.calls)
    print("FINAL kind:", result.kind)
    print("FINAL text:", result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
