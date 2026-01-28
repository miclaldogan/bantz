from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, Optional, Literal, Union

from bantz.core.events import EventBus, EventType, get_event_bus
from bantz.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Minimal adapter interface for BrainLoop.

    Implementations should return a JSON-serializable object that matches the
    BrainLoop protocol (see `LLMOutput`).
    """

    def complete_json(
        self, *, messages: list[dict[str, str]], schema_hint: str
    ) -> dict[str, Any]: ...


# ─────────────────────────────────────────────────────────────────
# LLM protocol (Issue #84)
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Say:
    type: Literal["SAY"]
    text: str


@dataclass(frozen=True)
class AskUser:
    type: Literal["ASK_USER"]
    question: str


@dataclass(frozen=True)
class Fail:
    type: Literal["FAIL"]
    error: str


@dataclass(frozen=True)
class CallTool:
    type: Literal["CALL_TOOL"]
    name: str
    params: dict[str, Any]


LLMOutput = Union[Say, AskUser, Fail, CallTool]


def _parse_llm_output(raw: Any) -> tuple[Optional[LLMOutput], str]:
    if not isinstance(raw, dict):
        return None, "llm_output_not_object"

    typ = str(raw.get("type") or "").strip().upper()
    if typ == "SAY":
        return Say(type="SAY", text=str(raw.get("text") or "").strip()), "ok"
    if typ == "ASK_USER":
        return AskUser(
            type="ASK_USER", question=str(raw.get("question") or "").strip()
        ), "ok"
    if typ == "FAIL":
        err = str(raw.get("error") or "unknown_error").strip()
        return Fail(type="FAIL", error=err), "ok"
    if typ == "CALL_TOOL":
        name = str(raw.get("name") or "").strip()
        params = raw.get("params")
        if not isinstance(params, dict):
            params = {}
        return CallTool(type="CALL_TOOL", name=name, params=params), "ok"

    return None, "unknown_type"


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


@dataclass(frozen=True)
class BrainTranscriptTurn:
    step: int
    messages: list[dict[str, str]]
    schema: dict[str, Any]
    output: dict[str, Any]


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

    Minimal usage:

        tools = ToolRegistry()
        tools.register(Tool(name="add", description="...", parameters={...}, function=add))

        loop = BrainLoop(llm=my_llm_adapter, tools=tools, config=BrainLoopConfig(debug=True))
        result = loop.run(turn_input="2 ile 3 topla", session_context={...}, policy={...})

    Contract:
    - Uses `ToolRegistry` as the tool catalog and executor.
    - Emits minimal events (ACK/PROGRESS/FOUND/RESULT/QUESTION/ERROR) via EventBus.
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

    def run(
        self,
        *,
        turn_input: str,
        session_context: Optional[dict[str, Any]] = None,
        policy: Any = None,
        context: Optional[dict[str, Any]] = None,
    ) -> BrainResult:
        user_text = (turn_input or "").strip()
        if not user_text:
            return BrainResult(
                kind="fail", text="empty_input", steps_used=0, metadata={}
            )

        # Backward compatible alias: older callers may pass `context=`.
        ctx: dict[str, Any] = {}
        if isinstance(context, dict):
            ctx.update(context)
        if isinstance(session_context, dict):
            ctx.update(session_context)

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

        transcript: list[BrainTranscriptTurn] = []

        # Emit quick ACK.
        try:
            self._events.publish(
                EventType.ACK.value, {"text": "Anladım efendim."}, source="brain"
            )
        except Exception:
            pass

        for step_idx in range(1, int(self._config.max_steps) + 1):
            schema_obj = {
                "protocol": {
                    "type": "SAY|CALL_TOOL|ASK_USER|FAIL",
                    "SAY": {"text": "..."},
                    "ASK_USER": {"question": "..."},
                    "CALL_TOOL": {"name": "tool_name", "params": {}},
                    "FAIL": {"error": "..."},
                },
                "tools": self._tools.as_llm_catalog(format="short"),
                "policy_summary": _summarize_policy(policy),
                "session_context": _shorten_jsonable(ctx, max_chars=1200),
                "conversation_context": _short_conversation(
                    messages, max_messages=12, max_chars=1200
                ),
                "observations": observations[-6:],
            }
            schema_hint = json.dumps(schema_obj, ensure_ascii=False)

            out_raw = self._llm.complete_json(
                messages=messages, schema_hint=schema_hint
            )
            action, status = _parse_llm_output(out_raw)

            if self._config.debug:
                masked_turn = BrainTranscriptTurn(
                    step=step_idx,
                    messages=_mask_messages(messages[-12:]),
                    schema=_mask_jsonable(schema_obj),
                    output=_mask_jsonable(
                        out_raw if isinstance(out_raw, dict) else {"_raw": str(out_raw)}
                    ),
                )
                transcript.append(masked_turn)
                try:
                    logger.debug(
                        "[BrainLoop] turn=%s trace=%s",
                        step_idx,
                        json.dumps(
                            {
                                "step": masked_turn.step,
                                "messages": masked_turn.messages,
                                "schema": masked_turn.schema,
                                "output": masked_turn.output,
                            },
                            ensure_ascii=False,
                        ),
                    )
                except Exception:
                    pass

            if action is None:
                if status == "llm_output_not_object":
                    return BrainResult(
                        kind="fail",
                        text="llm_output_not_object",
                        steps_used=step_idx,
                        metadata=_meta(transcript),
                    )

                # Unknown type: ask LLM to restate.
                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(out_raw, ensure_ascii=False),
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Geçersiz type. Sadece SAY|CALL_TOOL|ASK_USER|FAIL döndür.",
                    }
                )
                continue

            if isinstance(action, Say):
                text = action.text
                try:
                    self._events.publish(
                        EventType.RESULT.value, {"text": text}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="say",
                    text=text,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, AskUser):
                q = action.question
                try:
                    self._events.publish(
                        EventType.QUESTION.value, {"question": q}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="ask_user",
                    text=q,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, Fail):
                err = action.error
                try:
                    self._events.publish(
                        EventType.ERROR.value, {"error": err}, source="brain"
                    )
                except Exception:
                    pass
                return BrainResult(
                    kind="fail",
                    text=err,
                    steps_used=step_idx,
                    metadata=_meta(transcript, raw=out_raw),
                )

            if isinstance(action, CallTool):
                name = action.name
                params = action.params

                ok, why = self._tools.validate_call(name, params)
                if not ok:
                    observations.append({"tool": name, "ok": False, "error": why})
                    messages.append(
                        {
                            "role": "assistant",
                            "content": json.dumps(out_raw, ensure_ascii=False),
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
                    observations.append(
                        {"tool": name, "ok": False, "error": "tool_not_executable"}
                    )
                else:
                    try:
                        result = tool.function(**params)
                        observations.append(
                            {"tool": name, "ok": True, "result": result}
                        )
                    except Exception as e:
                        observations.append(
                            {"tool": name, "ok": False, "error": str(e)}
                        )

                try:
                    self._events.publish(
                        EventType.FOUND.value, {"tool": name}, source="brain"
                    )
                except Exception:
                    pass

                messages.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(out_raw, ensure_ascii=False),
                    }
                )
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

        return BrainResult(
            kind="fail",
            text="max_steps_exceeded",
            steps_used=self._config.max_steps,
            metadata=_meta(transcript),
        )


def _summarize_policy(policy: Any) -> str:
    if policy is None:
        return ""
    try:
        summary = getattr(policy, "summary", None)
        if callable(summary):
            return str(summary())
    except Exception:
        pass
    try:
        if isinstance(policy, dict):
            return json.dumps(_mask_jsonable(policy), ensure_ascii=False)
    except Exception:
        pass
    return str(policy)


def _short_conversation(
    messages: list[dict[str, str]], *, max_messages: int, max_chars: int
) -> list[dict[str, str]]:
    tail = list(messages[-max_messages:])
    out: list[dict[str, str]] = []
    used = 0
    for m in tail:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        remaining = max(0, max_chars - used)
        if len(content) > remaining:
            content = content[: max(0, remaining - 1)] + "…"
        used += len(content)
        out.append({"role": role, "content": content})
        if used >= max_chars:
            break
    return out


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "set-cookie",
}


def _mask_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in _SENSITIVE_KEYS:
                masked[key] = "***"
            else:
                masked[key] = _mask_jsonable(v)
        return masked
    if isinstance(value, list):
        return [_mask_jsonable(v) for v in value]
    if isinstance(value, str):
        return value if len(value) <= 500 else (value[:499] + "…")
    return value


def _mask_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(m.get("role") or ""),
            "content": str(_mask_jsonable(m.get("content") or "")),
        }
        for m in messages
    ]


def _shorten_jsonable(value: Any, *, max_chars: int) -> Any:
    try:
        dumped = json.dumps(value, ensure_ascii=False)
    except Exception:
        dumped = str(value)
    if len(dumped) <= max_chars:
        return value
    return dumped[: max(0, max_chars - 1)] + "…"


def _meta(transcript: list[BrainTranscriptTurn], raw: Any = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if raw is not None:
        meta["raw"] = raw
    if transcript:
        meta["transcript"] = [
            {
                "step": t.step,
                "messages": t.messages,
                "schema": t.schema,
                "output": t.output,
            }
            for t in transcript
        ]
    return meta
