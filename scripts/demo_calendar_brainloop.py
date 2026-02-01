from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

# Allow running directly from repo root without an editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bantz.agent.tools import Tool, ToolRegistry
from bantz.agent.builtin_tools import build_default_registry
from bantz.brain.brain_loop import BrainLoop, BrainLoopConfig
from bantz.brain.json_repair import RepairLLM, validate_or_repair_action
from bantz.brain.llm_router import JarvisLLMRouter
from bantz.core.events import Event, EventBus, EventType
from bantz.llm.base import LLMMessage, create_client
from bantz.policy.engine import PolicyEngine
from bantz.policy.risk_map import RiskMap


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DemoConfig:
    session_id: str
    run: bool
    calendar_id: Optional[str]
    tz_name: str
    d: date


def _iso_now(tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        return datetime.now(tz).replace(microsecond=0).isoformat()
    except Exception:
        return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _normalize_tr(text: str) -> str:
    t = (text or "").lower()
    return (
        t.replace("ç", "c")
        .replace("ğ", "g")
        .replace("ı", "i")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ü", "u")
    )


def _detect_time_intent(user_text: str) -> Optional[str]:
    """Return one of: evening|tomorrow|morning|today|None."""

    t = _normalize_tr(user_text)
    has_evening = "aksam" in t
    has_tomorrow = "yarin" in t
    has_morning = "sabah" in t
    has_today = "bugun" in t

    # Precedence: explicit "yarın akşam" should map to tomorrow window, not tonight.
    if has_evening and has_tomorrow:
        return "tomorrow"
    if has_evening:
        return "evening"
    if has_tomorrow:
        return "tomorrow"
    if has_morning:
        return "morning"
    if has_today:
        return "today"
    return None


def _mask_params(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if isinstance(v, str):
            vv = v
            if len(vv) > 120:
                vv = vv[:119] + "…"
            out[str(k)] = vv
        else:
            out[str(k)] = v
    return out


def _compute_windows(*, now_local: datetime, tzinfo: Any) -> dict[str, dict[str, str]]:
    tomorrow = now_local.date() + timedelta(days=1)
    midnight_local = datetime.combine(tomorrow, time(0, 0), tzinfo=tzinfo).replace(microsecond=0)

    today_0730 = datetime.combine(now_local.date(), time(7, 30), tzinfo=tzinfo).replace(microsecond=0)
    today_1130 = datetime.combine(now_local.date(), time(11, 30), tzinfo=tzinfo).replace(microsecond=0)
    today_2230 = datetime.combine(now_local.date(), time(22, 30), tzinfo=tzinfo).replace(microsecond=0)

    tomorrow_0730 = datetime.combine(tomorrow, time(7, 30), tzinfo=tzinfo).replace(microsecond=0)
    tomorrow_1130 = datetime.combine(tomorrow, time(11, 30), tzinfo=tzinfo).replace(microsecond=0)
    tomorrow_2230 = datetime.combine(tomorrow, time(22, 30), tzinfo=tzinfo).replace(microsecond=0)

    # Avoid past/invalid ranges.
    today_max = today_2230 if now_local < today_2230 else midnight_local

    if now_local >= today_1130:
        # It's already past today's morning; expose tomorrow-morning window instead.
        morning_today_min = tomorrow_0730
        morning_today_max = tomorrow_1130
    else:
        morning_today_min = max(now_local, today_0730)
        morning_today_max = today_1130

    return {
        "evening_window": {"time_min": now_local.isoformat(), "time_max": midnight_local.isoformat()},
        "tomorrow_window": {"time_min": tomorrow_0730.isoformat(), "time_max": tomorrow_2230.isoformat()},
        "today_window": {"time_min": now_local.isoformat(), "time_max": today_max.isoformat()},
        "morning_today_window": {"time_min": morning_today_min.isoformat(), "time_max": morning_today_max.isoformat()},
        "morning_tomorrow_window": {"time_min": tomorrow_0730.isoformat(), "time_max": tomorrow_1130.isoformat()},
    }


def _override_time_params(
    *,
    tool_name: str,
    params: dict[str, Any],
    user_text: str,
    session_context: dict[str, Any],
    debug: bool,
) -> dict[str, Any]:
    """Deterministically override time_min/time_max for certain natural-language intents."""

    intent = _detect_time_intent(user_text)
    if debug:
        print(f"[debug] intent: {intent or 'none'}", file=sys.stderr)

    if tool_name not in {"calendar.list_events", "calendar.find_free_slots"}:
        return params

    windows = session_context or {}

    if intent is None:
        # Extra demo-only override: "önümüzdeki X saat" style queries.
        t = _normalize_tr(user_text)
        m = re.search(r"\b(onumuzdeki|sonraki)\s+(\d{1,2})\s+saat(?:te|ta)?\b", t)
        if m:
            try:
                hours = int(m.group(2))
                if 1 <= hours <= 48:
                    now_iso = str(windows.get("now_iso") or "")
                    now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else None
                    if now_dt is not None:
                        tmin = now_dt.replace(microsecond=0).isoformat()
                        tmax = (now_dt + timedelta(hours=hours)).replace(microsecond=0).isoformat()
                        params = dict(params)
                        params["time_min"] = tmin
                        params["time_max"] = tmax
                        if debug:
                            print(f"[debug] next-hours override: {tmin} .. {tmax}", file=sys.stderr)
                        return params
            except Exception:
                pass

        return params

    chosen: Optional[dict[str, str]] = None
    if intent == "evening":
        chosen = windows.get("evening_window")
    elif intent == "tomorrow":
        chosen = windows.get("tomorrow_window")
    elif intent == "today":
        chosen = windows.get("today_window")
    elif intent == "morning":
        now_iso = str(windows.get("now_iso") or "")
        # If it's already past today's morning, default to tomorrow morning.
        chosen = windows.get("morning_today_window")
        try:
            now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else None
            if now_dt is not None:
                today_1130 = windows.get("morning_today_window", {}).get("time_max")
                if today_1130:
                    max_dt = datetime.fromisoformat(str(today_1130).replace("Z", "+00:00"))
                    if now_dt >= max_dt:
                        chosen = windows.get("morning_tomorrow_window")
        except Exception:
            chosen = windows.get("morning_tomorrow_window")

    if not isinstance(chosen, dict):
        return params
    tmin = chosen.get("time_min")
    tmax = chosen.get("time_max")
    if not isinstance(tmin, str) or not isinstance(tmax, str) or not tmin or not tmax:
        return params

    original = dict(params)
    params = dict(params)
    params["time_min"] = tmin
    params["time_max"] = tmax

    if tool_name == "calendar.find_free_slots":
        # Provide human-hour defaults unless the LLM explicitly provided them.
        params.setdefault("preferred_start", "07:30")
        params.setdefault("preferred_end", "22:30")

    if debug:
        print(f"[debug] original params: {json.dumps(_mask_params(original), ensure_ascii=False)}", file=sys.stderr)
        print(f"[debug] override time_min/time_max: {tmin} .. {tmax}", file=sys.stderr)

    return params


def _print_event_stream(ev: Event) -> None:
    """Pretty, stable-ish event-stream lines for demos."""

    t = str(ev.event_type)
    data = ev.data or {}

    # Keep output single-line and scannable.
    if t == EventType.ACK.value:
        text = str(data.get("text") or "")
        if text:
            print(f"ACK: {text}")
        else:
            print("ACK")
        return

    if t == EventType.PROGRESS.value:
        msg = str(data.get("message") or "")
        if msg:
            print(f"PROGRESS: {msg}")
        else:
            print("PROGRESS")
        return

    if t == EventType.FOUND.value:
        tool = (data.get("tool") or data.get("name") or "").strip()
        print(f"FOUND: {tool}" if tool else "FOUND")
        return

    if t == EventType.QUESTION.value:
        q = str(data.get("question") or "")
        print(f"QUESTION: {q}" if q else "QUESTION")
        return

    if t == EventType.RESULT.value:
        text = str(data.get("text") or data.get("summary") or "")
        print(f"RESULT: {text}" if text else "RESULT")
        return

    if t == EventType.ERROR.value:
        msg = str(data.get("message") or data.get("error") or "")
        print(f"ERROR: {msg}" if msg else "ERROR")
        return

    # Fallback: JSON line.
    print("EVENT", json.dumps(ev.to_dict(), ensure_ascii=False))


def _extract_first_json_object(text: str) -> Optional[str]:
    """Best-effort extraction of the first JSON object from free-form text."""

    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None

    # Fast path: already a JSON object.
    if s.startswith("{") and s.endswith("}"):
        return s

    start = s.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
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
                return s[start : i + 1]

    return None


class VLLMTextLLM(RepairLLM):
    """Text-only vLLM client used by the JSON repair adapter."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float = 0.2,
        max_tokens: int = 768,
    ):
        self._client = create_client("vllm", base_url=base_url, model=model, timeout=timeout_seconds)
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        self.calls = 0

    @property
    def base_url(self) -> str:
        return self._client.base_url if hasattr(self._client, 'base_url') else "unknown"

    @property
    def model(self) -> str:
        return self._client.model_name

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


class JarvisRepairingLLMAdapter:
    """Adapter: free-form LLM -> strict BrainLoop JSON actions with repair.

    This is intentionally verbose in prompting to make the demo feel 'Jarvis-like':
    - Turkish
    - time-awareness
    - proposes options
    - policy confirmation respected (BrainLoop+PolicyEngine handles gating)
    """

    def __init__(self, *, llm: RepairLLM, tools: ToolRegistry, max_attempts: int = 2):
        self._llm = llm
        self._tools = tools
        self._max_attempts = max_attempts

    def complete_json(self, *, messages: list[dict[str, str]], schema_hint: str) -> dict[str, Any]:
        # BrainLoop uses the same complete_json() for:
        # 1) route classification (small schema)
        # 2) action planning/execution (rich schema)
        # This adapter supports both.
        try:
            schema_obj_any = json.loads(schema_hint)
        except Exception:
            schema_obj_any = None

        # Route classifier schema: {route, calendar_intent, confidence}
        if isinstance(schema_obj_any, dict) and {"route", "calendar_intent", "confidence"}.issubset(schema_obj_any.keys()):
            user_text = ""
            for m in reversed(messages or []):
                if isinstance(m, dict) and str(m.get("role") or "") == "user":
                    user_text = str(m.get("content") or "").strip()
                    break

            # Heuristic short-circuit: in the demo we prefer a deterministic router
            # to avoid small-context model parse failures.
            nt = _normalize_tr(user_text)
            calendar_markers = [
                "takvim",
                "ajanda",
                "calendar",
                "plan",
                "program",
                "toplanti",
                "toplantı",
                "bugun",
                "bugün",
                "yarin",
                "yarın",
                "aksam",
                "akşam",
                "sabah",
                "saat",
            ]
            if not any(k in nt for k in calendar_markers):
                return {"route": "smalltalk", "calendar_intent": "none", "confidence": 0.8}

            if any(k in nt for k in ["ekle", "olustur", "oluştur", "planla", "ayarla", "koy", "koyar misin", "hatirlat", "hatırlat"]):
                return {"route": "calendar", "calendar_intent": "create", "confidence": 0.7}
            if any(k in nt for k in ["iptal", "sil", "kaldir", "kaldır"]):
                return {"route": "calendar", "calendar_intent": "cancel", "confidence": 0.7}
            if any(k in nt for k in ["tasi", "taşı", "degistir", "değiştir", "ertele", "kaydir", "kaydır", "guncelle", "güncelle"]):
                return {"route": "calendar", "calendar_intent": "modify", "confidence": 0.7}
            if any(k in nt for k in ["bak", "listele", "goster", "göster", "var mi", "var mı"]):
                return {"route": "calendar", "calendar_intent": "query", "confidence": 0.7}

            prompt = (
                "ONLY JSON: {\"route\":\"calendar|smalltalk|unknown\",\"calendar_intent\":\"create|modify|cancel|query|none\",\"confidence\":0.0}"
                "\nKurallar: Ek alan ekleme; Markdown yok; tek satır JSON.\n"
                f"USER: {user_text}\n"
            )

            # Force strict routing parameters on small local models.
            llm_obj = self._llm
            old_temp = getattr(llm_obj, "_temperature", None)
            old_max = getattr(llm_obj, "_max_tokens", None)
            try:
                if old_temp is not None:
                    setattr(llm_obj, "_temperature", 0.0)
                if old_max is not None:
                    setattr(llm_obj, "_max_tokens", 64)
                raw_text = llm_obj.complete_text(prompt=prompt)
            finally:
                try:
                    if old_temp is not None:
                        setattr(llm_obj, "_temperature", old_temp)
                    if old_max is not None:
                        setattr(llm_obj, "_max_tokens", old_max)
                except Exception:
                    pass
            raw_json = _extract_first_json_object(raw_text)
            if raw_json:
                try:
                    out = json.loads(raw_json)
                    if isinstance(out, dict):
                        return out
                except Exception:
                    pass
            logger.info("[demo_router] parse_fail -> default smalltalk")
            return {"route": "smalltalk", "calendar_intent": "none", "confidence": 0.0}

        # Action planning schema: keep compact for small-context local demos.
        if isinstance(schema_obj_any, dict):
            def _compact_session_context(ctx_any: Any) -> dict[str, Any]:
                if not isinstance(ctx_any, dict):
                    return {}
                keep = [
                    "now_iso",
                    "tz_name",
                    "date",
                    "mode",
                    "dry_run",
                    "human_hours",
                    "_dialog_state",
                ]
                return {k: ctx_any.get(k) for k in keep if k in ctx_any}

            def _compact_tools(tools_any: Any) -> list[dict[str, Any]]:
                if not isinstance(tools_any, list):
                    return []
                compact: list[dict[str, Any]] = []
                for t in tools_any:
                    if not isinstance(t, dict):
                        continue
                    name = t.get("name")
                    if not name:
                        continue
                    args_schema = t.get("args_schema") if isinstance(t.get("args_schema"), dict) else {}
                    required = []
                    if isinstance(args_schema, dict):
                        req_any = args_schema.get("required")
                        if isinstance(req_any, list):
                            required = [str(x) for x in req_any if x is not None]
                    compact.append(
                        {
                            "name": str(name),
                            "requires_confirmation": bool(t.get("requires_confirmation")),
                            "risk_level": t.get("risk_level"),
                            "required": required,
                        }
                    )
                return compact

            schema_hint = json.dumps(
                {
                    "protocol": schema_obj_any.get("protocol"),
                    "tools": _compact_tools(schema_obj_any.get("tools")),
                    "session_context": _compact_session_context(schema_obj_any.get("session_context")),
                },
                ensure_ascii=False,
            )

        # Hard cap to avoid 1024-context blowups on small local models.
        if isinstance(schema_hint, str) and len(schema_hint) > 1600:
            schema_hint = schema_hint[:1600] + "…"

        # Keep prompts small: 3B demos often run with 1024 context.
        conversation_tail = "\n".join(
            [
                f"{m.get('role','')}: {m.get('content','')}"
                for m in messages[-4:]
                if isinstance(m, dict)
            ]
        )

        jarvis_system = (
            "Sen BANTZ'sın. Türkçe konuş; 'Efendim' hitabını kullan.\n"
            "Sadece tek bir JSON object döndür (Markdown/backtick/açıklama yok).\n"
            "type ∈ {SAY, CALL_TOOL, ASK_USER, FAIL}.\n"
            "Takvim sorularında calendar.list_events / calendar.find_free_slots kullan; yazma işlemleri (calendar.create_event) onay ister.\n"
            "'önümüzdeki X saat' => time_min=now, time_max=now+Xh.\n"
        )

        prompt = (
            "Görev: Aşağıdaki şemaya uygun şekilde yalnızca tek bir JSON object döndür.\n"
            "Kurallar: Output sadece JSON object; ekstra alan yok; Markdown yok.\n"
            "Zorunlu: 'type' alanını birebir kullan. type ∈ {SAY, CALL_TOOL, ASK_USER, FAIL}.\n\n"
            f"JARVIS_SYSTEM:\n{jarvis_system}\n\n"
            f"SCHEMA_HINT:\n{schema_hint}\n\n"
            f"CONVERSATION_TAIL:\n{conversation_tail}\n"
        )

        if len(prompt) > 3400:
            # Keep the header + tail; drop the middle if needed.
            head = prompt[:900]
            tail = prompt[-900:]
            prompt = head + "\n...\n" + tail

        raw_text = self._llm.complete_text(prompt=prompt)
        action = validate_or_repair_action(
            llm=self._llm,
            raw_text=raw_text,
            tool_registry=self._tools,
            max_attempts=self._max_attempts,
        )

        # Demo hardening: avoid redundant questions on obvious calendar queries.
        # If the model asks the user the same thing they just asked (common on 3B),
        # force a safe read-only tool call.
        try:
            last_user_text = ""
            for m in reversed(messages or []):
                if isinstance(m, dict) and str(m.get("role") or "") == "user":
                    last_user_text = str(m.get("content") or "").strip()
                    break
            nt = _normalize_tr(last_user_text)
            is_calendarish = any(
                k in nt
                for k in [
                    "takvim",
                    "ajanda",
                    "calendar",
                    "plan",
                    "program",
                    "toplanti",
                    "toplantı",
                ]
            ) or bool(re.search(r"\b(onumuzdeki|sonraki)\s+\d{1,2}\s+saat(?:te|ta)?\b", nt))
            if (
                isinstance(action, dict)
                and str(action.get("type") or "") == "ASK_USER"
                and is_calendarish
            ):
                q = _normalize_tr(str(action.get("question") or "").strip())
                if not q or q == nt:
                    return {"type": "CALL_TOOL", "name": "calendar.list_events", "params": {}}
        except Exception:
            pass

        return action


def _build_calendar_tools(
    *,
    calendar_id: Optional[str],
    dry_run: bool,
    runtime: Optional[dict[str, Any]] = None,
) -> ToolRegistry:
    full = build_default_registry()
    wanted = [
        "calendar.list_events",
        "calendar.find_free_slots",
        "calendar.create_event",
    ]

    tools = ToolRegistry()
    for name in wanted:
        t = full.get(name)
        if t is None:
            raise RuntimeError(f"Tool not found in default registry: {name}")

        fn = t.function

        # Default calendar_id injection if the tool supports it.
        def _wrap(fn, *, tool_name: str):
            def _call(**params):
                # Deterministic override hook (demo-only): fix LLM window mistakes.
                if runtime is not None and tool_name in {"calendar.list_events", "calendar.find_free_slots"}:
                    try:
                        user_text = str(runtime.get("last_user_text") or "")
                        session_context = runtime.get("session_context")
                        if not isinstance(session_context, dict):
                            session_context = {}
                        debug = bool(runtime.get("debug"))
                        params = _override_time_params(
                            tool_name=tool_name,
                            params=dict(params),
                            user_text=user_text,
                            session_context=session_context,
                            debug=debug,
                        )
                    except Exception:
                        pass

                # Demo guard: don't allow creating events in the past.
                if runtime is not None and tool_name == "calendar.create_event":
                    try:
                        start_raw = params.get("start")
                        if isinstance(start_raw, str) and start_raw.strip():
                            tzinfo = runtime.get("tzinfo")
                            now_local = datetime.now(tzinfo).replace(microsecond=0)
                            v = start_raw.strip()
                            if v.endswith("Z"):
                                v = v[:-1] + "+00:00"
                            start_dt = datetime.fromisoformat(v)
                            if start_dt.tzinfo is None:
                                start_dt = start_dt.replace(tzinfo=tzinfo)
                            if start_dt < now_local:
                                raise ValueError(
                                    "start_is_in_past (Bugün geçti efendim. Yarın mı, en erken uygun saat mi?)"
                                )
                    except Exception as e:
                        # If parsing fails, let the tool handle validation.
                        if isinstance(e, ValueError) and str(e).startswith("start_is_in_past"):
                            raise

                if calendar_id and "calendar_id" not in params:
                    params["calendar_id"] = calendar_id
                return fn(**params) if fn is not None else {"ok": False, "error": "tool_not_executable"}

            _call.__name__ = f"wrapped_{tool_name.replace('.', '_')}"
            return _call

        wrapped_fn = _wrap(fn, tool_name=name) if fn is not None else None

        # Safety: in dry-run, never hit the network for writes.
        if dry_run and name == "calendar.create_event":
            def _dry_run_create_event(**params):
                if calendar_id and "calendar_id" not in params:
                    params["calendar_id"] = calendar_id
                return {"ok": True, "dry_run": True, "would_create": dict(params)}

            wrapped_fn = _dry_run_create_event

        tools.register(
            Tool(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
                function=wrapped_fn,
                risk_level=t.risk_level,
                requires_confirmation=bool(t.requires_confirmation),
            )
        )

    return tools


def _iter_input_lines() -> Iterable[str]:
    """Yield user lines from stdin when piped.

    Empty lines are ignored. Lines starting with '#' are ignored.
    """

    for raw in sys.stdin:
        line = (raw or "").strip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        yield line.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis-like BrainLoop Calendar demo (Issue #100)")

    # LLM Configuration (vLLM-only)
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8000")
    parser.add_argument("--vllm-model", default="Qwen/Qwen2.5-3B-Instruct")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=768)

    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--debug", action="store_true")

    # Router controls route/intent classification before the BrainLoop planner.
    # On small-context local models (e.g., 1024), the router prompt can overflow.
    # This flag lets us run a clean end-to-end calendar scenario without router.
    parser.add_argument(
        "--no-router",
        action="store_true",
        help="Disable LLM Router (avoids context-length errors on small-context models)",
    )

    parser.add_argument("--session", default="demo")
    parser.add_argument("--calendar-id", default=None)
    parser.add_argument("--tz", default="Europe/Istanbul")
    parser.add_argument("--date", default=None, help="Override date YYYY-MM-DD (optional)")

    parser.add_argument("--dry-run", action="store_true", help="Never write; calendar.create_event is stubbed")
    parser.add_argument("--run", action="store_true", help="Allow real calendar writes (will ask confirmation)")

    # Interactive mode: read from file or pipe (avoids heredoc issues)
    parser.add_argument("--script", type=str, default=None, help="Read conversation from file (one line per user message)")
    parser.add_argument("--interactive", action="store_true", help="Force interactive mode even if stdin is piped")

    args = parser.parse_args()

    if args.dry_run and args.run:
        raise SystemExit("Choose only one: --dry-run or --run")

    run_mode = bool(args.run)
    dry_run = bool(args.dry_run) or not run_mode

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    tz_name = str(args.tz)
    d = date.fromisoformat(args.date) if args.date else datetime.now().date()

    try:
        from zoneinfo import ZoneInfo

        tzinfo = ZoneInfo(tz_name)
    except Exception:
        tzinfo = datetime.now().astimezone().tzinfo

    # Runtime state shared with tool wrappers (override hook).
    runtime: dict[str, Any] = {
        "debug": bool(args.debug),
        "tz_name": tz_name,
        "tzinfo": tzinfo,
        "last_user_text": "",
    }

    # Build initial session context (refreshed each turn).
    now_local = datetime.now(tzinfo).replace(microsecond=0)
    windows = _compute_windows(now_local=now_local, tzinfo=tzinfo)
    session_context: dict[str, Any] = {
        "user": "demo",
        "now_iso": now_local.isoformat(),
        "tz_name": tz_name,
        "date": d.isoformat(),
        "mode": "calendar_brainloop_demo",
        "human_hours": {"start": "07:30", "end": "22:30"},
        "dry_run": bool(dry_run),
        # Demo-only: render certain tool results deterministically (LLM can't hallucinate them).
        "deterministic_render": True,
        **windows,
    }
    runtime["session_context"] = session_context

    # Build tools + policy.
    tools = _build_calendar_tools(calendar_id=args.calendar_id, dry_run=dry_run, runtime=runtime)

    policy = PolicyEngine(
        risk_map=RiskMap({
            # Make sure create_event is treated as MED even if tool metadata changes.
            "calendar.create_event": "MED",
        })
    )

    llm_url = args.vllm_url
    llm_model = args.vllm_model
    print(f"[DEMO] Using vLLM backend: {llm_url} model={llm_model}")

    # LLM client.
    llm = VLLMTextLLM(
        base_url=llm_url,
        model=llm_model,
        timeout_seconds=float(args.timeout),
        temperature=float(args.temperature),
        max_tokens=int(args.max_tokens),
    )

    if not llm.is_available():
        print(f"LLM backend erişilemedi: {llm_url}")
        print(f"- Başlat: python -m vllm.entrypoints.openai.api_server --model {llm_model} --port 8000")
        print(f"- Veya mock server: python scripts/vllm_mock_server.py")
        return 2

    adapter = JarvisRepairingLLMAdapter(llm=llm, tools=tools)

    bus = EventBus()
    bus.subscribe_all(_print_event_stream)

    router = None
    if not args.no_router:
        # LLM Router: Always active (Issue #126)
        # Router uses same client for consistent backend
        class RouterLLMWrapper:
            def __init__(self, client, temperature: float = 0.0):
                self._client = client
                self._temperature = temperature
            
            def complete_text(self, prompt: str) -> str:
                """Simple text completion for router (no JSON mode)."""
                messages = [LLMMessage(role="user", content=prompt)]
                return self._client.chat(
                    messages=messages,
                    temperature=self._temperature,
                    max_tokens=200,  # Router JSON is small, 200 is plenty
                )
        
        router_llm = RouterLLMWrapper(client=llm._client, temperature=0.0)
        router = JarvisLLMRouter(llm=router_llm)
    
    # Warm-up LLM to speed up first real request
    if args.debug:
        print("[DEMO] Warming up vllm backend...")
    try:
        llm._client.chat(
            messages=[LLMMessage(role="user", content="test")],
            temperature=0.0,
            max_tokens=5,
        )
        if args.debug:
            print("[DEMO] vllm backend ready!")
    except Exception as e:
        if args.debug:
            print(f"[DEMO] Warm-up warning: {e}")
    
    if args.debug and router is not None:
        print("[DEMO] LLM Router: ALWAYS ACTIVE - every conversation goes through LLM")

    loop = BrainLoop(
        llm=adapter,
        tools=tools,
        event_bus=bus,
        config=BrainLoopConfig(max_steps=int(args.max_steps), debug=bool(args.debug)),
        router=router,
    )

    # Shared state across turns: keeps policy pending action + session confirmation memory.
    state: dict[str, Any] = {"session_id": str(args.session)}

    print("BANTZ (BrainLoop): Hazırım efendim.")
    if dry_run:
        print("BANTZ (BrainLoop): Not: dry-run modundayım; takvime yazma yapılmaz.")

    # Determine input source: --script file, stdin pipe, or interactive terminal
    scripted: Optional[Iterable[str]] = None
    if args.script:
        # Read from script file
        try:
            with open(args.script, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
            scripted = iter(lines)
            print(f"BANTZ: Script dosyasından okuyorum: {args.script} ({len(lines)} satır)")
        except Exception as e:
            print(f"BANTZ: Script dosyası okunamadı: {e}")
            return 1
    elif not sys.stdin.isatty() and not args.interactive:
        # Stdin is piped and not forced to interactive
        scripted = iter(_iter_input_lines())

    def _read_user(prompt: str) -> Optional[str]:
        if scripted is not None:
            try:
                line = next(scripted)
                # Echo scripted input for visibility
                print(f"{prompt}{line}")
                return line
            except StopIteration:
                return None
        try:
            return input(prompt)
        except EOFError:
            return None

    while True:
        user_text = _read_user("USER: ")
        if user_text is None:
            # End of scripted input.
            return 0

        user_text = (user_text or "").strip()
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit", "çık", "cik"}:
            print("BANTZ: Görüşürüz efendim.")
            return 0

        # Refresh time-aware session context each turn.
        now_local = datetime.now(tzinfo).replace(microsecond=0)
        session_context["now_iso"] = now_local.isoformat()
        session_context["date"] = (d.isoformat() if isinstance(d, date) else str(d))
        windows = _compute_windows(now_local=now_local, tzinfo=tzinfo)
        session_context.update(windows)
        runtime["session_context"] = session_context
        runtime["last_user_text"] = user_text

        result = loop.run(
            turn_input=user_text,
            session_context=session_context,
            policy=policy,
            context=state,
        )

        # Debug: Show LLM Router decision
        if args.debug and result.metadata:
            trace = result.metadata.get("trace")
            if isinstance(trace, dict) and "llm_router_route" in trace:
                print(f"\n[LLM ROUTER] Route: {trace.get('llm_router_route')} | "
                      f"Intent: {trace.get('llm_router_intent')} | "
                      f"Confidence: {trace.get('llm_router_confidence', 0):.2f}")
                if trace.get('llm_router_reply'):
                    print(f"[LLM ROUTER] Reply: {trace.get('llm_router_reply')}")
                print()

        if result.kind == "say":
            print(f"BANTZ: {result.text}")
            continue

        if result.kind == "ask_user":
            print(f"BANTZ: {result.text}")
            # Next loop iteration will read user input.
            continue

        # fail
        print(f"BANTZ: Üzgünüm efendim. {result.text}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
