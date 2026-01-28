from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, Optional

from bantz.core.events import EventBus, EventType, get_event_bus
from bantz.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Minimal adapter interface for BrainLoop.

    Implementations should return a JSON-serializable object that matches the
    BrainLoop protocol (see `LLMOutput`).
    """

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class BrainLoopConfig:
    max_steps: int = 8
    debug: bool = False


@dataclass(frozen=True)
class BrainResult:
    kind: str  # say | ask_user | fail
    text: str
    steps_used: int
    metadata: dict[str, Any]


def _extract_first_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from text.

    This is intentionally lightweight for the skeleton milestone (#84). The
    robust validator/repair loop is tracked in #86.
    """

    text = (text or "").strip()
    if not text:
        raise ValueError("empty_output")

    if text.startswith("{"):
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise ValueError("json_not_object")

    start = text.find("{")
    if start < 0:
        raise ValueError("no_json_object")

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
                raise ValueError("json_not_object")

    raise ValueError("unbalanced_json")


class BrainLoop:
    """LLM-first brain loop.

    Contract:
    - Uses `ToolRegistry` as the tool catalog and executor.
    - Emits minimal events (ACK/PROGRESS/FOUND/RESULT) via EventBus.
    - Stops on SAY / ASK_USER / FAIL or on max_steps.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        event_bus: Optional[EventBus] = None,
        config: Optional[BrainLoopConfig] = None,
    ):
        self._llm = llm
        self._tools = tools
        self._events = event_bus or get_event_bus()
        self._config = config or BrainLoopConfig()

    def run(self, *, turn_input: str, context: Optional[dict[str, Any]] = None) -> BrainResult:
        user_text = (turn_input or "").strip()
        if not user_text:
            return BrainResult(kind="fail", text="empty_input", steps_used=0, metadata={})

        ctx = dict(context or {})

        # Conversation messages for the adapter.
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Sen Bantz'sın. Türkçe konuş. Tool çağırman gerekirse STRICT JSON döndür. "
                    "İzin/onay gerektiren işlerde kullanıcıdan soru sor."
                ),
            },
            {"role": "user", "content": user_text},
        ]

        observations: list[dict[str, Any]] = []

        # Emit quick ACK.
        try:
            self._events.publish(EventType.ACK.value, {"text": "Anladım efendim."}, source="brain")
        except Exception:
            pass

        for step_idx in range(1, int(self._config.max_steps) + 1):
            schema_hint = json.dumps(
                {
                    "protocol": {
                        "type": "SAY|CALL_TOOL|ASK_USER|FAIL",
                        "SAY": {"text": "..."},
                        "ASK_USER": {"question": "..."},
                        "CALL_TOOL": {"name": "tool_name", "params": {}},
                        "FAIL": {"error": "..."},
                    },
                    "tools": self._tools.as_schema(),
                    "context": ctx,
                    "observations": observations[-6:],
                },
                ensure_ascii=False,
            )

            out = self._llm.complete_json(messages=messages, schema_hint=schema_hint)
            if not isinstance(out, dict):
                return BrainResult(kind="fail", text="llm_output_not_object", steps_used=step_idx, metadata={})

            typ = str(out.get("type") or "").strip().upper()
            if typ == "SAY":
                text = str(out.get("text") or "").strip()
                try:
                    self._events.publish(EventType.RESULT.value, {"text": text}, source="brain")
                except Exception:
                    pass
                return BrainResult(kind="say", text=text, steps_used=step_idx, metadata={"raw": out})

            if typ == "ASK_USER":
                q = str(out.get("question") or "").strip()
                try:
                    self._events.publish(EventType.QUESTION.value, {"question": q}, source="brain")
                except Exception:
                    pass
                return BrainResult(kind="ask_user", text=q, steps_used=step_idx, metadata={"raw": out})

            if typ == "FAIL":
                err = str(out.get("error") or "unknown_error").strip()
                try:
                    self._events.publish(EventType.ERROR.value, {"error": err}, source="brain")
                except Exception:
                    pass
                return BrainResult(kind="fail", text=err, steps_used=step_idx, metadata={"raw": out})

            if typ == "CALL_TOOL":
                name = str(out.get("name") or "").strip()
                params = out.get("params")
                if not isinstance(params, dict):
                    params = {}

                ok, why = self._tools.validate_call(name, params)
                if not ok:
                    observations.append({"tool": name, "ok": False, "error": why})
                    messages.append(
                        {
                            "role": "assistant",
                            "content": json.dumps(out, ensure_ascii=False),
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Tool çağrısı geçersiz: {why}. Geçerli JSON ile tekrar dene.",
                        }
                    )
                    continue

                try:
                    self._events.publish(
                        EventType.PROGRESS.value,
                        {"message": f"Tool çalıştırılıyor: {name}", "step": step_idx},
                        source="brain",
                    )
                except Exception:
                    pass

                tool = self._tools.get(name)
                if tool is None or tool.function is None:
                    observations.append({"tool": name, "ok": False, "error": "tool_not_executable"})
                else:
                    try:
                        result = tool.function(**params)
                        observations.append({"tool": name, "ok": True, "result": result})
                    except Exception as e:
                        observations.append({"tool": name, "ok": False, "error": str(e)})

                try:
                    self._events.publish(EventType.FOUND.value, {"tool": name}, source="brain")
                except Exception:
                    pass

                messages.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Observation (tool sonucu): "
                            + json.dumps(observations[-1], ensure_ascii=False)
                        ),
                    }
                )
                continue

            # Unknown type: ask LLM to restate.
            messages.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
            messages.append(
                {
                    "role": "user",
                    "content": "Geçersiz type. Sadece SAY|CALL_TOOL|ASK_USER|FAIL döndür.",
                }
            )

        return BrainResult(kind="fail", text="max_steps_exceeded", steps_used=self._config.max_steps, metadata={})
