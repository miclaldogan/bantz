from __future__ import annotations

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


class FakeTextLLM(RepairLLM):
    """Fake text LLM that intentionally breaks JSON once, then repairs, then finalizes.

    Call flow:
    - Step-1: returns broken JSON (markdown + trailing comma)
    - Repair: returns valid CALL_TOOL JSON
    - Step-2: returns SAY JSON
    """

    def __init__(self):
        self.calls = 0

    def complete_text(self, *, prompt: str) -> str:
        self.calls += 1

        # If this is the repair prompt, return fixed JSON.
        if "Hata özeti:" in prompt and "Orijinal metin:" in prompt:
            return '{"type":"CALL_TOOL","name":"echo","params":{"text":"merhaba"}}'

        # First normal call: broken JSON
        if self.calls == 1:
            return (
                "Sure!\n"
                "```json\n"
                "{\"type\": \"CALL_TOOL\", \"name\": \"echo\", \"params\": {\"text\": \"merhaba\",}, }\n"
                "```\n"
            )

        # Second BrainLoop step: finalize
        return '{"type":"SAY","text":"Efendim: echo sonucu alındı ✅"}'


class RepairingLLMAdapter:
    """Adapter that turns text LLM output into strict JSON actions using #86 repair loop."""

    def __init__(self, *, llm: RepairLLM, tools: ToolRegistry, max_attempts: int = 2):
        self._llm = llm
        self._tools = tools
        self._max_attempts = max_attempts

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict[str, Any]:
        # In the real system we'd format a proper prompt. For smoke test, a minimal prompt is enough.
        user_tail = messages[-1]["content"] if messages else ""
        prompt = f"SCHEMA_HINT:\n{schema_hint}\n\nUSER:\n{user_tail}\n"

        raw_text = self._llm.complete_text(prompt=prompt)
        return validate_or_repair_action(
            llm=self._llm,
            raw_text=raw_text,
            tool_registry=self._tools,
            max_attempts=self._max_attempts,
        )


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

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

    fake = FakeTextLLM()
    adapter = RepairingLLMAdapter(llm=fake, tools=tools)

    loop = BrainLoop(llm=adapter, tools=tools, config=BrainLoopConfig(max_steps=4, debug=True))

    result = loop.run(turn_input="hey bantz test", session_context={"user": "demo"})

    print("LLM calls:", fake.calls)
    print("FINAL kind:", result.kind)
    print("FINAL text:", result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
