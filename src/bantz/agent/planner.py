from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from bantz.llm.ollama_client import LLMMessage, OllamaClient

from .tools import ToolRegistry


@dataclass(frozen=True)
class PlannedStep:
    action: str
    params: dict[str, Any]
    description: str


class Planner:
    """LLM-based planner that outputs a JSON list of tool calls."""

    SYSTEM_PROMPT = (
        "Sen Bantz asistanı için bir görev planlayıcısısın. "
        "Kullanıcının isteğini küçük, güvenli ve uygulanabilir adımlara böl.\n\n"
        "Kurallar:\n"
        "- SADECE verilen tool isimlerini kullan.\n"
        "- Tool parametreleri verilen şemaya uygun olmalı.\n"
        "- 2-10 adım arası tut (gerekmedikçe uzatma).\n"
        "- Her adım için kısa bir 'description' yaz (policy bu metni görecek).\n"
        "- Çıktı kesinlikle JSON olmalı, başka metin yazma.\n\n"
        "Mevcut tool'lar (JSON):\n{tools_schema}\n\n"
        "Çıktı formatı (JSON):\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\"action\": \"tool_name\", \"params\": {...}, \"description\": \"...\"}\n"
        "  ]\n"
        "}\n"
    )

    def __init__(
        self,
        llm: Optional[OllamaClient] = None,
        *,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ):
        self._llm = llm or OllamaClient()
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)

    def plan(self, request: str, tools: ToolRegistry) -> list[PlannedStep]:
        tools_schema = json.dumps(tools.as_schema(), ensure_ascii=False)
        system = self.SYSTEM_PROMPT.format(tools_schema=tools_schema)

        raw = self._llm.chat(
            [
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=request.strip()),
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        data = self._parse_json_object(raw)
        steps_raw = data.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("planner_no_steps")

        planned: list[PlannedStep] = []
        for i, item in enumerate(steps_raw, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"planner_step_not_object:{i}")
            action = str(item.get("action") or "").strip()
            desc = str(item.get("description") or "").strip()
            params = item.get("params")
            if not isinstance(params, dict):
                params = {}
            if not action:
                raise ValueError(f"planner_missing_action:{i}")
            if not desc:
                desc = action
            planned.append(PlannedStep(action=action, params=params, description=desc))

        return planned

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        """Parse first JSON object from LLM output."""
        text = (text or "").strip()
        if not text:
            raise ValueError("planner_empty")

        # Fast path
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

        # Extract first {...} block (balanced braces)
        start = text.find("{")
        if start < 0:
            raise ValueError("planner_no_json")

        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                    raise ValueError("planner_json_not_object")

        raise ValueError("planner_unbalanced_json")
