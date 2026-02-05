#!/usr/bin/env python3
"""Terminal Jarvis prototype: greets on launch, chats immediately, prewarms models.

Goals (current milestone):
- Terminal-based assistant that starts talking immediately
- Background prewarm (local vLLM router + Gemini finalizer)
- LLM-first orchestration with tools (calendar/gmail/system/web)
- Standby mode to emulate wake-word behavior

Run:
  python scripts/terminal_jarvis.py

Env:
  BANTZ_VLLM_URL (default http://localhost:8001)
  BANTZ_VLLM_MODEL (default Qwen/Qwen2.5-3B-Instruct)
  GEMINI_API_KEY / GOOGLE_API_KEY / BANTZ_GEMINI_API_KEY (optional but recommended)
  BANTZ_GEMINI_MODEL (default gemini-1.5-flash)

Tip:
  .env is loaded automatically (Issue #216) via bantz.security.env_loader.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Add src to path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.agent.tools import Tool, ToolRegistry
from bantz.brain.llm_router import JarvisLLMOrchestrator
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.core.events import EventBus
from bantz.llm.gemini_client import GeminiClient
from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.security.env_loader import load_env
from bantz.tools.registry import register_web_tools

from bantz.tools.calendar_tools import (
    calendar_create_event_tool,
    calendar_find_free_slots_tool,
    calendar_list_events_tool,
)
from bantz.tools.gmail_tools import (
    gmail_get_message_tool,
    gmail_list_messages_tool,
    gmail_send_tool,
    gmail_unread_count_tool,
)
from bantz.tools.system_tools import system_status
from bantz.tools.time_tools import time_now_tool


ROUTER_SYSTEM_PROMPT = """Kimlik / Roller:
- Sen BANTZ'sın. Kullanıcı USER'dır.
- Rol: Jarvis-vari asistan.
- DİL: SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil karıştırma!
- 'Efendim' hitabını kullan.

Görev: Her kullanıcı mesajını şu şemaya göre sınıflandır ve **orkestra et**.

DÜŞÜNCE SÜRECİ (reasoning_summary'de göster):
1. Kullanıcı ne istiyor? (niyet analizi)
2. Hangi bilgiler var/eksik? (slot çıkarımı)
3. Hangi tool gerekli? (tool seçimi)
4. Onay gerekli mi? (güvenlik kontrolü)

OUTPUT SCHEMA (zorunlu):
{
  "route": "calendar | gmail | system | smalltalk | unknown",
  "calendar_intent": "create | modify | cancel | query | none",
  "slots": {
    "date": "YYYY-MM-DD veya null",
    "time": "HH:MM veya null",
    "duration": "süre (dk) veya null",
    "title": "başlık veya null",
    "window_hint": "evening|tomorrow|morning|today|week veya null"
  },
  "gmail": {
    "to": "email veya null",
    "subject": "konu veya null",
    "body": "metin veya null"
  },
  "confidence": 0.0-1.0,
  "tool_plan": ["tool_name", ...],
  "assistant_reply": "Kullanıcıya söyleyeceğin metin (SADECE TÜRKÇE!)",

  "ask_user": false,
  "question": "",
  "requires_confirmation": false,
  "confirmation_prompt": "",
  "memory_update": "",
  "reasoning_summary": ["niyet: X", "slot: Y", "tool: Z"]
}

KURALLAR (kritik):
1) Sadece tek bir JSON object döndür; Markdown yok; açıklama yok.
2) confidence < 0.7 → tool_plan boş, ask_user=true + question doldur.
3) route="smalltalk" ise assistant_reply mutlaka dolu olmalı.
4) Takvim oluşturma: title ve time belli ise → route="calendar", calendar_intent="create", tool_plan=["calendar.create_event"], requires_confirmation=true.
5) Takvim oluşturma için time yoksa → ask_user=true, question="Saat kaçta olsun efendim?".
6) Takvim oluşturma için requires_confirmation=true ZORUNLU!
7) memory_update her turda 1-2 satır doldur.
8) reasoning_summary 1-3 kısa madde - düşünce sürecini göster.
9) Asla saat/tarih/numara uydurma. Emin olmadığın sayısal detayı çıkarma.
10) "son mail" / "en son mail" → route="gmail", tool_plan=["gmail.get_message"].
11) "saat kaç" / "tarih ne" / "saat" → route="system", tool_plan=["time.now"].
12) "cpu" / "ram" / "sistem durumu" / "sistem" → route="system", tool_plan=["system.status"].
13) Mail gönderme: to+subject+body net ise → route="gmail", tool_plan=["gmail.send"], requires_confirmation=true.
14) "Ana sayfa" / uydurma link / web sitesi uydurmak KESİNLİKLE YASAK.
15) SADECE TÜRKÇE CEVAP VER. Asla başka dil kullanma!

KULLANILABILIR TOOLLAR (sadece bunlar):
- calendar.list_events (takvim sorgula)
- calendar.find_free_slots (boş slot bul)
- calendar.create_event (etkinlik oluştur - onay gerekli!)
- gmail.unread_count (okunmamış sayısı)
- gmail.list_messages (mail listele)
- gmail.get_message (mail oku)
- gmail.send (mail gönder - onay gerekli!)
- system.status (cpu/ram durumu)
- time.now (şu anki saat/tarih)

ÖRNEKLER:

Kullanıcı: "saat kaç"
→ {"route": "system", "calendar_intent": "none", "slots": {}, "confidence": 0.95, "tool_plan": ["time.now"], "assistant_reply": "", "reasoning_summary": ["niyet: saat sorgusu", "tool: time.now kullanılacak"]}

Kullanıcı: "cpu durumu"
→ {"route": "system", "calendar_intent": "none", "slots": {}, "confidence": 0.95, "tool_plan": ["system.status"], "assistant_reply": "", "reasoning_summary": ["niyet: sistem durumu", "tool: system.status kullanılacak"]}

Kullanıcı: "yarın üçe toplantı ekle"
→ {"route": "calendar", "calendar_intent": "create", "slots": {"date": "2026-02-05", "time": "15:00", "title": "toplantı", "window_hint": "tomorrow"}, "confidence": 0.9, "tool_plan": ["calendar.create_event"], "requires_confirmation": true, "confirmation_prompt": "Yarın 15:00'te 'toplantı' etkinliği eklensin mi?", "reasoning_summary": ["niyet: etkinlik ekleme", "slot: yarın=2026-02-05, üç=15:00", "onay gerekli"]}

Kullanıcı: "bugün planım var mı"
→ {"route": "calendar", "calendar_intent": "query", "slots": {"window_hint": "today"}, "confidence": 0.9, "tool_plan": ["calendar.list_events"], "assistant_reply": "", "reasoning_summary": ["niyet: takvim sorgusu", "slot: bugün", "tool: calendar.list_events"]}

Kullanıcı: "son maili oku"
→ {"route": "gmail", "calendar_intent": "none", "slots": {}, "confidence": 0.9, "tool_plan": ["gmail.get_message"], "assistant_reply": "", "reasoning_summary": ["niyet: mail okuma", "tool: gmail.get_message"]}

Kullanıcı: "nasılsın"
→ {"route": "smalltalk", "calendar_intent": "none", "slots": {}, "confidence": 1.0, "tool_plan": [], "assistant_reply": "İyiyim efendim, teşekkür ederim. Size nasıl yardımcı olabilirim?", "reasoning_summary": ["niyet: selamlaşma", "tool gerekmez"]}

TÜRKÇE SAAT ÖRNEKLERİ:
- "üçe" / "üçte" → "15:00" (iş saatlerinde varsayılan öğleden sonra)
- "on bire" / "on birde" → "11:00"
- "on bir buçuğa" → "11:30"
- "akşam yediye" → "19:00"
- "sabah dokuza" → "09:00"
"""


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    # Common orchestrator slots that may be passed through even for non-calendar tools.
    # Mark these as "known" fields so SafetyGuard doesn't warn, but keep them
    # untyped because orchestrator slots may pass None.
    common_slot_props = {
        "date": {},
        "time": {},
        "duration": {},
        "title": {},
        "window_hint": {},
    }

    # Calendar tools
    reg.register(
        Tool(
            name="calendar.list_events",
            description="Google Calendar: list upcoming events (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "window_hint": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "query": {"type": "string"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_list_events_tool,
        )
    )
    reg.register(
        Tool(
            name="calendar.find_free_slots",
            description="Google Calendar: find free time slots (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    "duration": {"type": "integer"},
                    "window_hint": {"type": "string"},
                    "date": {"type": "string"},
                    "suggestions": {"type": "integer"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=calendar_find_free_slots_tool,
        )
    )
    reg.register(
        Tool(
            name="calendar.create_event",
            description="Google Calendar: create an event (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "duration": {"type": "integer"},
                    "window_hint": {"type": "string"},
                },
                "required": ["time"],
                "additionalProperties": True,
            },
            function=calendar_create_event_tool,
            requires_confirmation=True,
        )
    )

    # Gmail tools (read-only)
    reg.register(
        Tool(
            name="gmail.unread_count",
            description="Gmail: unread count (read-only)",
            parameters={
                "type": "object",
                "properties": {**common_slot_props},
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_unread_count_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.list_messages",
            description="Gmail: list inbox messages (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "max_results": {"type": "integer"},
                    "unread_only": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_list_messages_tool,
        )
    )
    reg.register(
        Tool(
            name="gmail.get_message",
            description="Gmail: read a message by id, or the latest one if id missing (read-only)",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "message_id": {"type": "string"},
                    "prefer_unread": {"type": "boolean"},
                },
                "required": [],
                "additionalProperties": True,
            },
            function=gmail_get_message_tool,
        )
    )

    reg.register(
        Tool(
            name="gmail.send",
            description="Gmail: send an email (write). Requires confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    **common_slot_props,
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "bcc": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": True,
            },
            function=gmail_send_tool,
            requires_confirmation=True,
        )
    )

    # System status
    reg.register(
        Tool(
            name="system.status",
            description="System health: loadavg, CPU count, memory usage (best-effort)",
            parameters={
                "type": "object",
                "properties": {"include_env": {"type": "boolean"}},
                "required": [],
                "additionalProperties": True,
            },
            function=system_status,
        )
    )

    reg.register(
        Tool(
            name="time.now",
            description="Time: current local time/date (timezone-aware)",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": True,
            },
            function=time_now_tool,
        )
    )

    # Web tools
    register_web_tools(reg)

    return reg


def _auth_help_lines() -> list[str]:
    return [
        "  /auth                → Google (takvim+gmail) yetkilendirme durumu + nasıl kurulur",
        "  /auth calendar        → Takvim için readonly OAuth (interactive)",
        "  /auth calendar write  → Takvim için write OAuth (interactive)",
        "  /auth gmail           → Gmail readonly OAuth (interactive)",
        "  /auth gmail send      → Gmail send OAuth (interactive)",
        "  /auth gmail modify    → Gmail modify OAuth (interactive)",
        "",
        "Not: Asistan tool çağrılarında OAuth otomatik başlamaz; önce /auth ile kurun.",
    ]


def _present(*names: str) -> bool:
    for n in names:
        if str(os.getenv(n, "") or "").strip():
            return True
    return False


def _env_get_any(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def _looks_like_sleep(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(k in t for k in ["uyku", "bekle", "standby", "şimdilik dur", "gerek yok", "teşekkür"]) and any(
        k in t for k in ["mod", "geç", "dur", "bekle", "gerek yok", "teşekkür"]
    )


def _looks_like_wake(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("bantz") or t.startswith("jarvis") or t.startswith("hey bantz") or t.startswith("hey jarvis")


def _strip_wake_prefix(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    for prefix in ["hey bantz", "hey jarvis", "bantz", "jarvis"]:
        if low.startswith(prefix):
            return t[len(prefix) :].lstrip(" ,:;-\t")
    return t


def _looks_like_calendar_query(text: str) -> bool:
    t = (text or "").strip().lower()
    keys = [
        "takvim",
        "ajanda",
        "plan",
        "toplantı",
        "etkinlik",
        "program",
        "bugün",
        "yarın",
        "bu akşam",
        "bu hafta",
        "neler var",
        "ne var",
    ]
    return any(k in t for k in keys)


def _is_confirmation_yes(text: str) -> bool:
    """Detect natural language confirmation (yes/ok/confirm).
    
    Handles cases like:
    - "evet" → True
    - "evet ekle dostum" → True
    - "tamam yap" → True
    - "ok devam" → True
    
    Issue #283: Accept natural language confirmations.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    
    # Exact match for common confirmations
    yes_tokens = {"evet", "e", "ok", "tamam", "onay", "onaylıyorum", "kabul", "yes", "y", "olur", "peki"}
    if t in yes_tokens:
        return True
    
    # First word match (handles "evet ekle dostum", "tamam yap" etc.)
    words = t.split()
    if words and words[0] in yes_tokens:
        return True
    
    # Startswith patterns (handles "evet," "tamam." etc. with punctuation)
    yes_prefixes = ("evet", "tamam", "ok ", "onay", "kabul", "yes ", "olur")
    if t.startswith(yes_prefixes):
        return True
    
    return False


def _is_confirmation_no(text: str) -> bool:
    """Detect natural language rejection (no/cancel).
    
    Handles cases like:
    - "hayır" → True
    - "hayır vazgeç" → True
    - "iptal et lütfen" → True
    
    Issue #283: Accept natural language rejections.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    
    # Exact match for common rejections
    # Note: Include ASCII variants for Turkish uppercase issues (HAYIR.lower() = hayir)
    no_tokens = {"hayır", "hayir", "h", "no", "n", "iptal", "vazgeç", "vazgec", "reddet", "istemiyorum", "olmaz"}
    if t in no_tokens:
        return True
    
    # First word match (handles "hayır vazgeç", "iptal et" etc.)
    words = t.split()
    if words and words[0] in no_tokens:
        return True
    
    # Startswith patterns
    no_prefixes = ("hayır", "hayir", "iptal", "vazgeç", "vazgec", "no ", "reddet", "istemiyorum", "olmaz")
    if t.startswith(no_prefixes):
        return True
    
    return False


def _infer_window_hint(text: str) -> str:
    t = (text or "").strip().lower()
    if "bu akşam" in t or "akşam" in t:
        return "evening"
    if "yarın sabah" in t or ("yarın" in t and "sabah" in t):
        return "morning"
    if "yarın" in t:
        return "tomorrow"
    if "bu hafta" in t or "hafta" in t:
        return "week"
    if "bugün" in t:
        return "today"
    return "today"


class TerminalJarvis:
    def __init__(self):
        self._router_ready = threading.Event()
        self._gemini_ready = threading.Event()
        self._standby = False
        self._pending_action_user_input: Optional[str] = None
        self._trace_enabled: bool = False

        self._warm_started_at = time.monotonic()
        self._router_last_error: str = ""
        self._router_last_check_at: float = 0.0
        self._gemini_last_error: str = ""
        self._gemini_last_check_at: float = 0.0

        vllm_url = os.getenv("BANTZ_VLLM_URL", "http://localhost:8001")
        router_model = os.getenv("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")
        gemini_model = os.getenv("BANTZ_GEMINI_MODEL", "gemini-1.5-flash")
        gemini_key = _env_get_any("GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY")

        self.vllm_url = vllm_url
        self.router_model = router_model
        self.gemini_model = gemini_model
        self.gemini_configured = bool(gemini_key)

        self.router_client = VLLMOpenAIClient(base_url=vllm_url, model=router_model, timeout_seconds=30.0)

        self.gemini_client: Optional[GeminiClient] = None
        if gemini_key:
            self.gemini_client = GeminiClient(api_key=gemini_key, model=gemini_model, timeout_seconds=30.0)

        self.tools = _build_registry()

        self.event_bus = EventBus(history_size=200)
        self.event_bus.subscribe_all(self._on_event)

        orchestrator = JarvisLLMOrchestrator(llm_client=self.router_client, system_prompt=ROUTER_SYSTEM_PROMPT)

        # If Gemini isn't configured, still provide a finalizer so tool results
        # get turned into a natural-language answer (local-only).
        effective_finalizer = self.gemini_client or self.router_client
        self.loop = OrchestratorLoop(
            orchestrator,
            self.tools,
            event_bus=self.event_bus,
            config=OrchestratorConfig(debug=False),
            finalizer_llm=effective_finalizer,
        )
        self.state = OrchestratorState()

    def _on_event(self, event) -> None:
        if not self._trace_enabled:
            return
        et = str(getattr(event, "event_type", ""))
        data = getattr(event, "data", {}) or {}

        if et == "turn.start":
            ui = str(data.get("user_input") or "")
            print(f"[trace] ACK: Anlaşıldı efendim. Başlıyorum. (input={ui!r})")
            return
        if et == "llm.decision":
            route = data.get("route")
            intent = data.get("intent")
            conf = data.get("confidence")
            plan = data.get("tool_plan")
            reasoning = data.get("reasoning_summary") or []
            print(f"[trace] PLAN: route={route} intent={intent} confidence={conf} tools={plan}")
            if reasoning:
                print(f"[trace] REASON: {'; '.join(str(r) for r in reasoning)}")
            return
        if et == "tool.call":
            tool = data.get("tool")
            print(f"[trace] TOOL: {tool} çalıştırılıyor...")
            return
        if et == "turn.end":
            ms = data.get("elapsed_ms")
            print(f"[trace] DONE: {ms}ms")
            return

    def _maybe_autoselect_vllm_model(self) -> None:
        """If vLLM is reachable but the configured model id is wrong, auto-select.

        vLLM exposes the served model ids via /v1/models. If BANTZ_VLLM_MODEL
        doesn't match any id, we switch to the first returned id.
        """

        try:
            import json
            import urllib.request

            url = f"{self.vllm_url.rstrip('/')}/v1/models"
            with urllib.request.urlopen(url, timeout=1.5) as resp:  # nosec - local endpoint
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            models = data.get("data")
            if not isinstance(models, list) or not models:
                return

            ids: list[str] = []
            for m in models:
                if isinstance(m, dict) and m.get("id"):
                    ids.append(str(m.get("id")))
            if not ids:
                return

            wanted = (self.router_client.model or "").strip()
            if wanted and wanted in ids:
                return

            # Switch to the first model id.
            chosen = ids[0]
            self.router_client.model = chosen
            self.router_model = chosen
            self._router_last_error = f"Configured model not served; auto-selected '{chosen}'"
        except Exception:
            # Best-effort only.
            return

    def _refresh_router_ready(self) -> None:
        if self._router_ready.is_set():
            return

        try:
            if not self.router_client.is_available(timeout_seconds=1.0):
                self._router_last_error = "vLLM unreachable"
                return
            self._maybe_autoselect_vllm_model()
            _ = self.router_client.complete_text(prompt="Merhaba", temperature=0.0, max_tokens=4)
            self._router_ready.set()
            self._router_last_error = ""
        except Exception as e:
            self._router_last_error = str(e)[:200]

    def prewarm_async(self) -> None:
        def _prewarm():
            backoff = 1.0
            while True:
                # Router prewarm (keep retrying so the session recovers if vLLM starts later)
                if not self._router_ready.is_set():
                    self._router_last_check_at = time.monotonic()
                    try:
                        if self.router_client.is_available(timeout_seconds=1.0):
                            self._maybe_autoselect_vllm_model()
                            _ = self.router_client.complete_text(prompt="Merhaba", temperature=0.0, max_tokens=8)
                            self._router_ready.set()
                            self._router_last_error = ""
                        else:
                            self._router_last_error = "vLLM unreachable"
                    except Exception as e:
                        self._router_last_error = str(e)[:200]

                # Gemini prewarm (best-effort)
                if self.gemini_client and (not self._gemini_ready.is_set()):
                    self._gemini_last_check_at = time.monotonic()
                    try:
                        if self.gemini_client.is_available(timeout_seconds=2.0):
                            self._gemini_ready.set()
                            self._gemini_last_error = ""
                        else:
                            self._gemini_last_error = "Gemini not available"
                    except Exception as e:
                        self._gemini_last_error = str(e)[:200]

                # Once everything we can warm is warmed, slow down polling.
                if self._router_ready.is_set() and (self.gemini_client is None or self._gemini_ready.is_set()):
                    time.sleep(10.0)
                    continue

                time.sleep(backoff)
                backoff = min(10.0, backoff * 1.6)

        t = threading.Thread(target=_prewarm, name="bantz-prewarm", daemon=True)
        t.start()

    def greet(self) -> None:
        print()
        print("BANTZ Terminal Jarvis")
        print("────────────────────")
        print("Sizi tekrardan görmek güzel efendim. Dinliyorum.")
        print("Komutlar: /help  /status  /trace  /auth  /sleep  /wake  /exit")
        print()

    def help(self) -> None:
        print(
            "\n".join(
                [
                    "Kısayollar:",
                    "  /help   → bu yardım",
                    "  /status → model/bağlantı durumu",
                    "  /trace  → reasoning özeti + tool adımları (aç/kapat)",
                    "  /auth   → Google OAuth kurulum/yetkilendirme",
                    "  /sleep  → beklemeye al (wake-word emülasyonu)",
                    "  /wake   → beklemeden çık",
                    "  /exit   → çıkış",
                    "",
                    *_auth_help_lines(),
                    "Beklemede iken sadece 'bantz ...' / 'jarvis ...' ile uyandırabilirsiniz.",
                ]
            )
        )

    def auth(self, *, mode: str) -> str:
        """Run interactive OAuth consent flows on-demand.

        mode:
          - status|help
          - calendar|calendar_write
          - gmail
          - all
        """

        from bantz.security.secrets import mask_path

        lines: list[str] = []

        # Paths + presence
        from bantz.google.auth import get_google_auth_config
        from bantz.google.gmail_auth import get_gmail_auth_config

        cal_cfg = get_google_auth_config()
        gm_cfg = get_gmail_auth_config()

        # Best-effort: show token scopes (scopes are not secrets) to detect mix-ups.
        def _token_scopes(path: Path) -> list[str]:
            try:
                import json

                if not path.exists():
                    return []
                obj = json.loads(path.read_text(encoding="utf-8"))
                scopes = obj.get("scopes") or obj.get("scope")
                if isinstance(scopes, str):
                    return [s for s in scopes.split() if s]
                if isinstance(scopes, list):
                    return [str(s) for s in scopes if str(s).strip()]
            except Exception:
                return []
            return []

        cal_scopes = _token_scopes(cal_cfg.token_path)
        gm_scopes = _token_scopes(gm_cfg.token_path)

        gemini_present = _present("GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY")
        lines.extend(
            [
                "Google OAuth durum:",
                f"  calendar client_secret: {mask_path(str(cal_cfg.client_secret_path))} (exists={cal_cfg.client_secret_path.exists()})",
                f"  calendar token:         {mask_path(str(cal_cfg.token_path))} (exists={cal_cfg.token_path.exists()})",
                f"  gmail client_secret:    {mask_path(str(gm_cfg.client_secret_path))} (exists={gm_cfg.client_secret_path.exists()})",
                f"  gmail token:            {mask_path(str(gm_cfg.token_path))} (exists={gm_cfg.token_path.exists()})",
                f"  Gemini API key present: {bool(gemini_present)}",
                "",
            ]
        )

        if cal_scopes:
            lines.append(f"  calendar token scopes:  {', '.join(cal_scopes[:6])}{' ...' if len(cal_scopes) > 6 else ''}")
        if gm_scopes:
            lines.append(f"  gmail token scopes:     {', '.join(gm_scopes[:6])}{' ...' if len(gm_scopes) > 6 else ''}")

        # Spot common mix-up: calendar token accidentally contains only Gmail scopes.
        if cal_scopes and (not any("calendar" in s for s in cal_scopes)) and any("gmail" in s for s in cal_scopes):
            lines.append("UYARI: calendar token dosyanız Gmail scope'ları içeriyor gibi görünüyor. '/auth calendar' ile yeniden üretin.")

        lines.append("")

        if mode in {"status", "help"}:
            lines.extend(
                [
                    "Kurulum özeti:",
                    "  1) Google Cloud Console → OAuth Client (Desktop) oluştur",
                    "  2) İndirilen JSON'u belirtilen client_secret yoluna koy",
                    "  3) /auth calendar ve /auth gmail çalıştır (token yazılır)",
                ]
            )
            return "\n".join(lines).strip()

        # Interactive flows
        try:
            if mode in {"all", "calendar"}:
                from bantz.google.auth import get_credentials
                from bantz.google.calendar import READONLY_SCOPES

                lines.append("Takvim yetkilendirme başlıyor (readonly)...")
                _ = get_credentials(scopes=READONLY_SCOPES, interactive=True)
                lines.append("Takvim token yazıldı/yenilendi.")

            if mode in {"calendar_write"}:
                from bantz.google.auth import get_credentials
                from bantz.google.calendar import WRITE_SCOPES

                lines.append("Takvim yetkilendirme başlıyor (write)...")
                _ = get_credentials(scopes=WRITE_SCOPES, interactive=True)
                lines.append("Takvim write token yazıldı/yenilendi.")

            if mode in {"all", "gmail"}:
                from bantz.google.gmail_auth import get_gmail_credentials
                from bantz.google.gmail_auth import GMAIL_READONLY_SCOPES

                lines.append("Gmail yetkilendirme başlıyor (readonly)...")
                _ = get_gmail_credentials(scopes=GMAIL_READONLY_SCOPES, interactive=True)
                lines.append("Gmail token yazıldı/yenilendi.")

            if mode in {"gmail_send"}:
                from bantz.google.gmail_auth import get_gmail_credentials
                from bantz.google.gmail_auth import GMAIL_SEND_SCOPES

                lines.append("Gmail yetkilendirme başlıyor (send)...")
                _ = get_gmail_credentials(scopes=GMAIL_SEND_SCOPES, interactive=True)
                lines.append("Gmail send token yazıldı/yenilendi.")

            if mode in {"gmail_modify"}:
                from bantz.google.gmail_auth import get_gmail_credentials
                from bantz.google.gmail_auth import GMAIL_MODIFY_SCOPES

                lines.append("Gmail yetkilendirme başlıyor (modify)...")
                _ = get_gmail_credentials(scopes=GMAIL_MODIFY_SCOPES, interactive=True)
                lines.append("Gmail modify token yazıldı/yenilendi.")
        except Exception as e:
            lines.append(f"Hata: {e}")
            return "\n".join(lines).strip()

        return "\n".join(lines).strip()

    def status(self) -> None:
        # Make status actionable: refresh readiness on-demand.
        self._refresh_router_ready()
        elapsed = int(time.monotonic() - self._warm_started_at)
        router_state = "ready" if self._router_ready.is_set() else "warming"
        gem_state = "disabled"
        if self.gemini_client is not None:
            gem_state = "ready" if self._gemini_ready.is_set() else "warming"
        print(
            "\n".join(
                [
                    f"Warmup elapsed: {elapsed}s",
                    f"Router (vLLM): {router_state}",
                    f"  url={self.vllm_url}",
                    f"  model={self.router_model}",
                    (f"  last_error={self._router_last_error}" if self._router_last_error else ""),
                    f"Finalizer (Gemini): {gem_state}",
                    f"  model={self.gemini_model}",
                    ("  api_key=configured" if self.gemini_configured else "  api_key=missing"),
                    (f"  last_error={self._gemini_last_error}" if (self._gemini_last_error and self.gemini_client and not self._gemini_ready.is_set()) else ""),
                    "",
                    "If router stays warming:",
                    "  - Start vLLM: ./scripts/vllm/start_3b.sh",
                    "  - Or set BANTZ_VLLM_URL to your server",
                    "  - Quick check: python3 scripts/health_check_vllm.py",
                ]
            ).strip()
        )

    def _fallback_smalltalk(self, user_input: str) -> str:
        # If Gemini is configured but router isn't ready yet, keep the user engaged.
        if self.gemini_client and self._gemini_ready.is_set():
            try:
                return self.gemini_client.complete_text(
                    prompt=(
                        "Sen Jarvis tarzı Türkçe asistansın. Kısa, samimi, 'Efendim' hitabı kullan. "
                        f"Kullanıcı: {user_input}\nAsistan:"
                    ),
                    temperature=0.4,
                    max_tokens=96,
                ).strip()
            except Exception:
                pass

        elapsed = int(time.monotonic() - self._warm_started_at)

        # If vLLM is unreachable, give an actionable hint instead of an indefinite wait.
        if self._router_last_error and "unreachable" in self._router_last_error.lower():
            return (
                "vLLM router'a ulaşamıyorum efendim; bu yüzden model hazırlığı bitmiyor. "
                f"(BANTZ_VLLM_URL={self.vllm_url})\n"
                "Başlatmak için: ./scripts/vllm/start_3b.sh\n"
                "Hızlı kontrol: python3 scripts/health_check_vllm.py\n"
                "İsterseniz /status yazın, durumu göstereyim."
            )

        return (
            f"Modeli hazırlıyorum efendim (geçen süre: {elapsed}s). "
            "Bu sırada isterseniz ne yapmak istediğinizi kısaca söyleyin "
            "(örn: 'bugün takvimimde ne var', 'okunmamış mail var mı', 'sistem durumu'). "
            "Durum için /status yazabilirsiniz."
        )

    def _finalize_from_tool_results(self, *, user_input: str, tool_name: str, tool_result: object) -> str:
        """Summarize a tool result into a user-facing answer using the finalizer."""

        import json

        payload = {
            "tool": tool_name,
            "result": tool_result,
        }
        prompt = (
            "Sen BANTZ'sın. Türkçe konuş ve 'Efendim' hitabını kullan.\n"
            "Sadece verilen TOOL_RESULT içindeki bilgilere dayan. Yeni saat/tarih/sayı uydurma.\n\n"
            f"USER: {user_input}\n\n"
            f"TOOL_RESULT(JSON):\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "ASSISTANT:"
        )

        try:
            # Prefer Gemini if configured; else use local vLLM.
            llm = self.gemini_client or self.router_client
            text = llm.complete_text(prompt=prompt, temperature=0.2, max_tokens=220)
            return str(text or "").strip() or "Tamamdır efendim."
        except Exception:
            # Minimal fallback.
            if isinstance(tool_result, dict) and tool_result.get("ok") is False:
                return f"Efendim, takvim aracından hata aldım: {tool_result.get('error') or 'unknown_error'}"
            return "Tamamdır efendim."

    def process(self, user_input: str) -> Optional[str]:
        text = (user_input or "").strip()
        if not text:
            return None

        if text in {"/exit", "/quit"}:
            raise SystemExit(0)
        if text in {"/help", "help"}:
            self.help()
            return None
        if text in {"/status", "status"}:
            self.status()
            return None

        if text.startswith("/auth"):
            parts = text.split()
            if len(parts) == 1:
                return self.auth(mode="status")
            sub = parts[1].strip().lower()
            if sub in {"calendar", "takvim"}:
                if len(parts) >= 3 and parts[2].strip().lower() in {"write", "yaz", "create", "events", "etkinlik"}:
                    return self.auth(mode="calendar_write")
                return self.auth(mode="calendar")
            if sub in {"gmail", "mail"}:
                if len(parts) >= 3:
                    sub2 = parts[2].strip().lower()
                    if sub2 in {"send", "gönder", "gonder"}:
                        return self.auth(mode="gmail_send")
                    if sub2 in {"modify", "duzenle", "düzenle"}:
                        return self.auth(mode="gmail_modify")
                return self.auth(mode="gmail")
            if sub in {"all", "hepsi"}:
                return self.auth(mode="all")
            return self.auth(mode="help")
        if text.startswith("/trace") or text.strip() == "trace":
            parts = text.split()
            if len(parts) >= 2:
                v = parts[1].strip().lower()
                self._trace_enabled = v in {"1", "on", "true", "yes", "aç"}
            else:
                self._trace_enabled = not self._trace_enabled
            return f"Trace {'ON' if self._trace_enabled else 'OFF'}"
        if text == "/sleep":
            self._standby = True
            return "Anlaşıldı efendim. Beklemedeyim. (Uyandırmak için: 'bantz ...')"
        if text in {"/wake", "wake"}:
            self._standby = False
            return "Buyurun efendim, dinliyorum."

        # Natural language sleep trigger
        if _looks_like_sleep(text):
            self._standby = True
            return "Pekala efendim. Beklemedeyim. İhtiyacınız olursa 'bantz' diye seslenin."

        if self._standby:
            if not _looks_like_wake(text):
                return None
            text = _strip_wake_prefix(text)
            self._standby = False
            if not text:
                return "Buyurun efendim."

        # Pending confirmation handling: if a tool is waiting for confirmation,
        # and the user types a confirmation token, run the prior action.
        # Issue #283: Accept natural language confirmations like "evet ekle dostum"
        if self.state.has_pending_confirmation():
            pending = self.state.pending_confirmation or {}
            prompt = str(pending.get("prompt") or "").strip()
            
            if _is_confirmation_yes(text):
                # User confirmed - run the pending action
                if self._pending_action_user_input:
                    trace = self.loop.run_full_cycle(
                        self._pending_action_user_input,
                        confirmation_token="evet",  # Normalize to simple token
                        state=self.state,
                    )
                    out = trace.get("final_output") or {}
                    reply = str(out.get("assistant_reply") or "").strip()
                    self._pending_action_user_input = None
                    return reply or "Tamamdır efendim."
            elif _is_confirmation_no(text):
                # User rejected - clear pending confirmation
                self.state.clear_pending_confirmation()
                self._pending_action_user_input = None
                return "Anlaşıldı efendim, iptal ettim."
            else:
                # Unknown response - keep showing the pending prompt
                return prompt or "Efendim, devam etmek için 'evet' veya 'hayır' diyebilir misiniz?"

        # If router isn't ready yet, provide an engaging fallback.
        if not self._router_ready.is_set():
            # Best-effort foreground hinting (background thread does the real work).
            try:
                if self.router_client.is_available(timeout_seconds=0.7):
                    self._maybe_autoselect_vllm_model()
                    self._router_last_error = ""
                    # Try a fast foreground warmup so the user isn't stuck.
                    self._refresh_router_ready()
                else:
                    self._router_last_error = "vLLM unreachable"
            except Exception as e:
                self._router_last_error = str(e)[:200]

        if not self._router_ready.is_set():
            return self._fallback_smalltalk(text)

        # Normal LLM-first orchestration
        output, self.state = self.loop.process_turn(text, self.state)

        if self._trace_enabled and getattr(output, "reasoning_summary", None):
            rs = output.reasoning_summary
            if isinstance(rs, list) and rs:
                compact = "; ".join([str(x) for x in rs if x])
                if compact:
                    print(f"[trace] REASON: {compact}")

        # If a confirmation is now pending, remember the initiating input.
        if self.state.has_pending_confirmation():
            self._pending_action_user_input = text
            pending = self.state.pending_confirmation or {}
            prompt = str(pending.get("prompt") or "").strip()
            return prompt or (output.confirmation_prompt or "Efendim, onay verir misiniz?")

        # Pragmatic fallback: the 3B router sometimes fails to emit tool_plan even when
        # it correctly routes to calendar. If the user is clearly asking about schedule,
        # run calendar.list_events directly and summarize.
        if (
            str(getattr(output, "route", "") or "") == "calendar"
            and not getattr(output, "tool_plan", None)
            and _looks_like_calendar_query(text)
        ):
            hint = _infer_window_hint(text)
            if self._trace_enabled:
                print(f"[trace] FALLBACK: calendar.list_events window_hint={hint}")
            else:
                print("Takviminizi tarıyorum efendim...")
            try:
                res = calendar_list_events_tool(window_hint=hint, max_results=10)
            except Exception as e:
                return f"Efendim, takvimi kontrol ederken hata aldım: {e}"
            return self._finalize_from_tool_results(
                user_input=text,
                tool_name="calendar.list_events",
                tool_result=res,
            )

        return (output.assistant_reply or "").strip() or "Buyurun efendim."


def main() -> int:
    load_env()

    assistant = TerminalJarvis()
    assistant.prewarm_async()
    assistant.greet()

    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\nGörüşmek üzere efendim.")
            return 0

        try:
            reply = assistant.process(user_input)
        except SystemExit:
            print("Görüşmek üzere efendim.")
            return 0
        except Exception as e:
            print(f"Efendim, bir hata oluştu: {e}")
            continue

        if reply:
            print(reply)


if __name__ == "__main__":
    raise SystemExit(main())
