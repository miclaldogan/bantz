from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .types import Intent

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class Parsed:
    intent: Intent
    slots: dict


@dataclass(frozen=True)
class ContextualParsed:
    """Context-aware parse result for conversation flow."""
    intent: str
    slots: dict
    requires_context: bool = False  # True if this makes sense only in conversation


_TURKISH_QUOTES = "'\"""''"

# ─────────────────────────────────────────────────────────────────
# Context-aware patterns for Jarvis Conversation Flow (Issue #20)
# These patterns match short responses that only make sense when
# the user is already engaged in a conversation.
# ─────────────────────────────────────────────────────────────────

# Confirmation patterns
_CONTEXT_CONFIRM_PATTERNS = [
    r"^(evet|ehe|olur|tamam|ok|okey|tabii|tabi|elbette|kesinlikle|ay[nı]en|do[ğg]ru)$",
    r"^(evet\s+evet|tamam\s+tamam|elbette\s+efendim)$",
]

# Rejection patterns
_CONTEXT_REJECT_PATTERNS = [
    r"^(hay[ıi]r|yok|olmaz|istemiyorum|gerek\s+yok|vazge[çc]|iptal)$",
    r"^(hay[ıi]r\s+te[şs]ekk[üu]rler|yok\s+gerek\s+yok)$",
]

# Number selection patterns
_CONTEXT_NUMBER_PATTERNS = [
    r"^(\d+)$",  # Just a number: "3"
    r"^(\d+)\.\s*(sonu[çc]|[şs]ey|madde|se[çc]enek)?$",  # "3. sonuç" or "3."
    r"^(birinci|ikinci|[üu][çc][üu]nc[üu]|d[öo]rd[üu]nc[üu]|be[şs]inci|alt[ıi]nc[ıi]|yedinci|sekizinci|dokuzuncu|onuncu)$",
    r"^(ilk|son)$",  # "ilk" = 1, "son" = -1 (last)
    r"^(ilkini|sonuncuyu|birincisini|ikincisini|[üu][çc][üu]nc[üu]s[üu]n[üu])$",
]

# Navigation patterns (within results/lists)
_CONTEXT_NAV_PATTERNS = [
    r"^(sonraki|[ıi]leri|devam|next|ilerle|bir\s+sonraki)$",
    r"^([öo]nceki|geri|back|previous|geriye|bir\s+[öo]nceki)$",
    r"^(a[şs]a[ğg][ıi]|yukar[ıi]|down|up)$",
]

# Follow-up question patterns
_CONTEXT_FOLLOWUP_PATTERNS = [
    r"^(peki|ya|bir\s+de|ayr[ıi]ca|hem\s+de)$",
    r"^(ba[şs]ka)(\s+bir\s+[şs]ey)?$",
    r"^(bunu|[şs]unu|onu)(\s+da)?$",
]

# Goodbye/thanks patterns
_CONTEXT_GOODBYE_PATTERNS = [
    r"^(te[şs]ekk[üu]rler|sa[ğg]\s*ol|mersi|eyvallah)$",
    r"^(tamam\s+bu\s+kadar|yeter|bu\s+kadar|bitti|tamamd[ıi]r)$",
    r"^(g[öo]r[üu][şs][üu]r[üu]z|ho[şs][çc]a\s*kal|bay\s*bay|bye)$",
    r"^(iyi\s+geceler|iyi\s+g[üu]nler|iyi\s+ak[şs]amlar)$",
]

# Compiled context patterns
_COMPILED_CONTEXT_PATTERNS: dict[str, list[re.Pattern]] = {}


def _compile_context_patterns() -> None:
    """Compile context patterns once."""
    global _COMPILED_CONTEXT_PATTERNS
    if _COMPILED_CONTEXT_PATTERNS:
        return
    
    _COMPILED_CONTEXT_PATTERNS = {
        "context_confirm": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_CONFIRM_PATTERNS],
        "context_reject": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_REJECT_PATTERNS],
        "context_select_number": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_NUMBER_PATTERNS],
        "context_navigate": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_NAV_PATTERNS],
        "context_followup": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_FOLLOWUP_PATTERNS],
        "context_goodbye": [re.compile(p, re.IGNORECASE) for p in _CONTEXT_GOODBYE_PATTERNS],
    }


def parse_contextual_intent(text: str) -> Optional[ContextualParsed]:
    """Parse short responses that only make sense in conversation context.
    
    This is used by ConversationManager to detect quick responses
    when the user is already engaged.
    
    Args:
        text: User's utterance
        
    Returns:
        ContextualParsed if a context pattern matches, None otherwise
    """
    _compile_context_patterns()
    t = text.strip()
    
    # Skip if too long - context responses are short
    if len(t.split()) > 6:
        return None
    
    for intent, patterns in _COMPILED_CONTEXT_PATTERNS.items():
        for pattern in patterns:
            m = pattern.match(t)
            if m:
                slots: dict = {}
                
                # Extract number for selection
                if intent == "context_select_number":
                    num = _extract_number_from_text(t)
                    if num is not None:
                        slots["number"] = num
                
                # Extract navigation direction
                if intent == "context_navigate":
                    direction = _extract_nav_direction(t)
                    if direction:
                        slots["direction"] = direction
                
                return ContextualParsed(
                    intent=intent,
                    slots=slots,
                    requires_context=True
                )
    
    return None


def _extract_number_from_text(text: str) -> Optional[int]:
    """Extract a number from text, handling Turkish ordinals."""
    t = text.strip().lower()
    
    # Direct digit
    m = re.match(r"^(\d+)", t)
    if m:
        return int(m.group(1))
    
    # Turkish ordinals
    ordinals = {
        "birinci": 1, "ilk": 1, "ilkini": 1, "birincisini": 1,
        "ikinci": 2, "ikincisini": 2,
        "üçüncü": 3, "ucuncu": 3, "üçüncüsünü": 3,
        "dördüncü": 4, "dorduncu": 4,
        "beşinci": 5, "besinci": 5,
        "altıncı": 6, "altinci": 6,
        "yedinci": 7,
        "sekizinci": 8,
        "dokuzuncu": 9,
        "onuncu": 10,
        "son": -1, "sonuncu": -1, "sonuncuyu": -1,
    }
    
    for word, num in ordinals.items():
        if word in t:
            return num
    
    return None


def _extract_nav_direction(text: str) -> Optional[str]:
    """Extract navigation direction from text."""
    t = text.strip().lower()
    
    next_words = ["sonraki", "ileri", "devam", "next", "aşağı", "asagi", "down"]
    prev_words = ["önceki", "onceki", "geri", "back", "previous", "yukarı", "yukari", "up"]
    
    for word in next_words:
        if word in t:
            return "next"
    
    for word in prev_words:
        if word in t:
            return "prev"
    
    return None


def is_contextual_response(text: str) -> bool:
    """Check if text looks like a contextual response (short, likely needs context)."""
    return parse_contextual_intent(text) is not None

# Bağlaçlar: cümleyi adımlara bölmek için
# Not: "X dakika sonra" gibi zaman ifadelerini ayırmamalı, bu yüzden
# "sonra" tek başına zincir ayırıcı DEĞİL, sadece "ve sonra", "ardından" vb.
_CHAIN_DELIMITERS = re.compile(
    r"\s+(?:ve\s+sonra|ardından|sonrasında|daha\s+sonra|ondan\s+sonra)\s+",
    flags=re.IGNORECASE,
)

# Pattern to detect reminder/checkin sentences (should NOT be split)
_REMINDER_PATTERN = re.compile(
    r"\b(?:hat[ıi]rlat|yokla|check-?in)\b.*\b(?:dakika|dk|saat|sa|saniye|sn)\s*sonra\b",
    flags=re.IGNORECASE,
)
_TIME_SONRA_PATTERN = re.compile(
    r"\b(?:\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz)\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra\b",
    flags=re.IGNORECASE,
)


def _is_reminder_sentence(text: str) -> bool:
    """Check if text contains a reminder-like time expression that shouldn't be split."""
    return bool(_REMINDER_PATTERN.search(text)) or (
        bool(_TIME_SONRA_PATTERN.search(text)) and 
        re.search(r"\bhat[ıi]rlat", text, re.IGNORECASE)
    )


def _make_search_result(site: str, query: str) -> Parsed:
    """Create a browser_open result for site search."""
    from urllib.parse import quote_plus
    search_urls = {
        "wikipedia": f"https://tr.wikipedia.org/w/index.php?search={quote_plus(query)}",
        "vikipedi": f"https://tr.wikipedia.org/w/index.php?search={quote_plus(query)}",
        "youtube": f"https://www.youtube.com/results?search_query={quote_plus(query)}",
        "amazon": f"https://www.amazon.com.tr/s?k={quote_plus(query)}",
        "google": f"https://www.google.com/search?q={quote_plus(query)}",
        "instagram": f"https://www.instagram.com/explore/tags/{quote_plus(query.replace(' ', ''))}",
    }
    url = search_urls.get(site, f"https://www.google.com/search?q={quote_plus(query)}")
    return Parsed(intent="browser_open", slots={"url": url})


def _clean(text: str) -> str:
    return text.strip()


def split_chain(text: str) -> list[str]:
    """Split a command into chain steps by Turkish connectors.
    
    IMPORTANT: Reminder sentences with "X dakika sonra" should NOT be split,
    even if they contain chain delimiters.
    """
    # If this looks like a reminder with time expression, don't split
    if _is_reminder_sentence(text):
        return [text.strip()]
    
    parts = _CHAIN_DELIMITERS.split(text)
    return [p.strip() for p in parts if p.strip()]


def parse_intent(text: str) -> Parsed:
    t = _clean(text).lower()

    # ─────────────────────────────────────────────────────────────────
    # Greeting / Conversational intents (Basic Jarvis interaction)
    # ─────────────────────────────────────────────────────────────────
    
    # Greeting: "merhaba", "selam", "selam jarvis", "hey", "naber"
    if re.search(r"^(merhaba|selam(\s+jarvis)?|hey(\s+jarvis)?|naber|nas[ıi]ls[ıi]n|g[üu]nayd[ıi]n|iyi\s+ak[şs]amlar|iyi\s+g[üu]nler)$", t):
        return Parsed(intent="greeting", slots={})
    
    # Help: "yardım", "help", "ne yapabilirsin", "komutlar"
    if re.search(r"^(yard[ıi]m|help|ne\s+yapabilirsin|komutlar|yard[ıi]m\s+et|nas[ıi]l\s+kullan[ıi]r[ıi]m)$", t):
        return Parsed(intent="help", slots={})
    
    # Time query: "saat kaç", "ne zaman", "bugün günlerden ne"
    if re.search(r"^(saat\s+ka[çc]|saati?\s+s[öo]yle(r\s+misin)?|[şs]u\s+an(ki)?\s+saat)$", t):
        return Parsed(intent="time_query", slots={})
    
    # Date query: "bugün ne", "hangi gün", "tarih ne"
    if re.search(r"^(bug[üu]n\s+ne|hangi\s+g[üu]n|tarih\s+ne|bug[üu]n\s+g[üu]nlerden\s+ne)$", t):
        return Parsed(intent="date_query", slots={})
    
    # Thanks/Goodbye: "teşekkürler", "sağ ol", "hoşça kal"
    if re.search(r"^(te[şs]ekk[üu]rler|te[şs]ekk[üu]r\s+ederim|sa[ğg]\s*ol|eyvallah|ho[şs][çc]a\s*kal|g[öo]r[üu][şs][üu]r[üu]z|bay\s*bay|bye|iyi\s+geceler)$", t):
        return Parsed(intent="goodbye", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Job Control intents (Issue #31 - V2-1: Agent OS Core)
    # These have high priority as they control running jobs
    # ─────────────────────────────────────────────────────────────────
    
    # Job pause: "bekle", "dur", "bir saniye", "durakla"
    if re.search(r"^(bekle|dur|bir\s*san[ıi]ye|durakla|pause|durdur|bekler\s*misin)$", t):
        return Parsed(intent="job_pause", slots={})
    
    # Job resume: "devam et", "devam", "sürdür", "continue"
    if re.search(r"^(devam(\s*et)?|s[üu]rd[üu]r|continue|devam\s*edelim|kald[ıi][ğg][ıi]n\s*yerden)$", t):
        return Parsed(intent="job_resume", slots={})
    
    # Job cancel: "iptal", "vazgeç", "cancel", "bırak", "boşver"
    if re.search(r"^([ıi]ptal|vazge[çc]|cancel|b[ıi]rak|bo[şs]ver|g[ıi]t|unut)$", t):
        return Parsed(intent="job_cancel", slots={})
    
    # Job status: "ne yapıyorsun", "durum", "neredesin", "status"
    # If the user explicitly says "agent ...", route to agent_status instead.
    if re.search(r"\b(agent\s+durum(u)?|agent\s+status|agent\s+ne\s+yap[ıi]yor|agent\s+ne\s+yap[ıi]yorsun)\b", t):
        return Parsed(intent="agent_status", slots={})

    if re.search(r"\b(ne\s+yap[ıi]yorsun|durum(un)?|neredesin|status|ne\s+i[şs]\s+yap[ıi]yorsun|hangi\s+a[şs]amaday[ıi]z)\b", t):
        return Parsed(intent="job_status", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Agent mode (Issue #3)
    # Explicit prefix to avoid changing existing behavior.
    # Examples:
    #   "agent: YouTube'a git, Coldplay ara, ilk videoyu aç"    (preview gösterir)
    #   "agent!: Instagram'a git"                                (direkt çalıştırır)
    #   "planla: instagram'a git ve hikayeler'e bak"            (preview gösterir)
    # ─────────────────────────────────────────────────────────────────
    # Immediate mode (skip preview): agent!: / planla!:
    m = re.search(r"^\s*(agent|planla|cok\s*adimli|çok\s*adıml[ıi])!\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        req = m.group(2).strip()
        return Parsed(intent="agent_run", slots={"request": req, "skip_preview": True})

    # Standard mode (show preview first): agent: / planla:
    m = re.search(r"^\s*(agent|planla|cok\s*adimli|çok\s*adıml[ıi])\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        req = m.group(2).strip()
        return Parsed(intent="agent_run", slots={"request": req, "skip_preview": False})

    # Agent confirm after preview
    if re.search(r"\b(plan[ıi]?\s+(tamam|onayla|ba[sş]lat)|agent[ıi]?\s+ba[sş]lat|plan[ıi]?\s+[cç]al[ıi][sş]t[ıi]r)\b", t):
        return Parsed(intent="agent_confirm_plan", slots={})

    # Agent status (handled earlier to avoid conflict with generic "durum")

    # Agent history / plan listing
    m = re.search(r"\bson\s+(\d+)\s+(agent|ajan)\b", t)
    if m:
        return Parsed(intent="agent_history", slots={"n": int(m.group(1))})

    if re.search(r"\b(agent\s+ge[cç]mi[sş]i|agent\s+history|son\s+agent\s+plan[ıi]|plan[ıi]m[ıi]\s+g[oö]ster|agent\s+plan[ıi]n[ıi]\s+g[oö]ster)\b", t):
        return Parsed(intent="agent_history", slots={})

    # Agent retry - son başarısız task'ı tekrar çalıştır
    if re.search(r"\b(agent\s+tekrar|agent\s+retry|tekrar\s+dene\s+agent|son\s+agent[ıi]?\s+tekrar)\b", t):
        return Parsed(intent="agent_retry", slots={})

    # Agent cancel/abort mid-task
    if re.search(r"\b(agent[ıi]?\s+iptal|agent\s+durdur|agent[ıi]?\s+bitir)\b", t):
        return Parsed(intent="queue_abort", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Overlay / UI commands (highest priority)
    # ─────────────────────────────────────────────────────────────────
    
    # Move overlay: "sağ üste geç", "ortaya dön", "bantz sol alta git"
    m = re.search(r"\b(sa[gğ]\s*[uü]st|[uü]st\s*sa[gğ]|sol\s*[uü]st|[uü]st\s*sol|orta(ya)?|merkez|sa[gğ]\s*alt|alt\s*sa[gğ]|sol\s*alt|alt\s*sol|[uü]st\s*orta|orta\s*[uü]st|alt\s*orta|orta\s*alt|sol\s*orta|orta\s*sol|sa[gğ]\s*orta|orta\s*sa[gğ])([ea])?\s*(ge[cç]|git|ta[şs][ıi]n|d[oö]n|koy|yerle[şs])\b", t)
    if m:
        position = m.group(1).strip()
        return Parsed(intent="overlay_move", slots={"position": position})
    
    # Alternative: "bantz bana engel oluyorsun sağ üste geç"
    m = re.search(r"\bengel\s+ol[uı]yorsun\s+(.+?)\s*(ge[cç]|git)\b", t)
    if m:
        position = m.group(1).strip()
        return Parsed(intent="overlay_move", slots={"position": position})
    
    # Hide overlay: "bantz kapat", "overlay'i kapat", "gizlen"
    if re.search(r"\b(gizlen|overlay.*kapat|kendini\s+kapat|ekrandan\s+[cç][ıi]k)\b", t):
        return Parsed(intent="overlay_hide", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Jarvis Panel control (Issue #19)
    # Note: These are specific panel commands that require "panel" keyword
    # Generic pagination like "sonraki", "önceki" are handled later
    # ─────────────────────────────────────────────────────────────────
    
    # Panel move: "paneli sağa taşı", "paneli sol üste götür", "paneli ortaya al"
    m = re.search(r"\bpanel[ie]?\s*(sa[ğg](a)?|sol(a)?|sa[ğg]\s*[üu]st(e)?|sol\s*[üu]st(e)?|orta(ya)?|merkez(e)?|sa[ğg]\s*alt(a)?|sol\s*alt(a)?)\s*(ta[şs][ıi]|g[oö]t[üu]r|al|git|ge[çc]|koy)\b", t)
    if m:
        position = m.group(1).strip()
        return Parsed(intent="panel_move", slots={"position": position})
    
    # Alternative: "sağa taşı paneli", "sol üste al paneli"
    m = re.search(r"\b(sa[ğg](a)?|sol(a)?|sa[ğg]\s*[üu]st(e)?|sol\s*[üu]st(e)?|orta(ya)?|merkez(e)?)\s*(ta[şs][ıi]|g[oö]t[üu]r|al)\s*panel[ie]?\b", t)
    if m:
        position = m.group(1).strip()
        return Parsed(intent="panel_move", slots={"position": position})
    
    # Panel hide: "paneli kapat", "paneli gizle", "sonuçları kapat"
    if re.search(r"\b(panel[ie]?\s*(kapat|gizle|hide)|sonu[çc]lar[ıi]?\s*kapat)\b", t):
        return Parsed(intent="panel_hide", slots={})
    
    # Panel minimize: "paneli küçült", "paneli minimize et"
    if re.search(r"\b(panel[ie]?\s*(k[üu][çc][üu]lt|minimize)|k[üu][çc][üu]lt\s*panel[ie]?)\b", t):
        return Parsed(intent="panel_minimize", slots={})
    
    # Panel maximize/restore: "paneli büyüt", "paneli aç", "paneli göster"
    if re.search(r"\b(panel[ie]?\s*(b[üu]y[üu]t|g[oö]ster|maximize|restore)|b[üu]y[üu]t\s*panel[ie]?)\b", t):
        return Parsed(intent="panel_maximize", slots={})
    
    # Panel pagination: ONLY with explicit "panel" or "sayfa" keyword
    # "panelde sonraki", "sonraki sayfa"
    if re.search(r"\b(panel(de)?\s+sonraki|sonraki\s+sayfa)\b", t):
        return Parsed(intent="panel_next_page", slots={})
    
    # Panel prev: ONLY with explicit "panel" or "sayfa" keyword
    # "panelde önceki", "önceki sayfa"
    if re.search(r"\b(panel(de)?\s+[öo]nceki|[öo]nceki\s+sayfa)\b", t):
        return Parsed(intent="panel_prev_page", slots={})
    
    # Panel select item: "panelde 3. sonucu aç", "panelden 2. sonucu seç"
    # Note: Without "panel" keyword, these go to news_open_result
    m = re.search(r"\bpanel(de|den|deki)?\s*(\d+)\.\s*sonu[çc][uü]?\s*(a[çc]|se[çc]|g[öo]ster)?\b", t)
    if m:
        return Parsed(intent="panel_select_item", slots={"index": int(m.group(2))})
    
    # Alternative: "3. paneldeki sonucu aç"
    m = re.search(r"\b(\d+)\.\s*panel(de|den|deki)\s*sonu[çc][uü]?\s*(a[çc]|se[çc]|g[öo]ster)?\b", t)
    if m:
        return Parsed(intent="panel_select_item", slots={"index": int(m.group(1))})

    # Queue control commands (highest priority)
    if t in {"duraklat", "bekle", "dur bir"}:
        return Parsed(intent="queue_pause", slots={})
    if t in {"devam et", "devam", "sürdür", "tekrar dene", "yeniden dene", "retry"}:
        return Parsed(intent="queue_resume", slots={})
    if t in {"iptal et", "tümünü iptal", "kuyruğu iptal", "zinciri iptal", "agent iptal", "agent'i iptal"}:
        return Parsed(intent="queue_abort", slots={})
    if t in {"sıradaki", "atla", "bunu atla", "sonrakine geç"}:
        return Parsed(intent="queue_skip", slots={})
    if re.search(r"\b(kuyruk|s[ıi]ra)\s+(ne|nedir|durumu?)\b", t):
        return Parsed(intent="queue_status", slots={})

    # Dev mode transitions
    if re.search(r"\b(dev\s+mod(a|u)\s+ge(ç|c)|dev\s+mode\s+on|dev\s+mode\s+aktif|dev\s+mod\s+a(ç|c))\b", t):
        return Parsed(intent="enter_dev_mode", slots={})
    if re.search(
        r"\b(normal\s+mod(a|u)\s+d(ö|o)n|dev\s+moddan\s+c(ı|i)k|dev\s+moddan\s+ç(ı|i)k|dev\s+mode\s+off)\b",
        t,
    ):
        return Parsed(intent="exit_dev_mode", slots={})

    # Confirmation / cancellation short replies
    if t in {"evet", "e", "onayla"}:
        return Parsed(intent="confirm_yes", slots={})
    if t in {"hayır", "hayir", "h", "yok", "vazgeç", "vazgec"}:
        return Parsed(intent="confirm_no", slots={})
    if t in {"iptal", "boşver", "bosver", "kapat", "dur", "geç", "gec", "boş ver", "bos ver", "tamam"}:
        return Parsed(intent="cancel", slots={})

    # Debug: show last N log entries
    m = re.search(r"\bson\s+(\d+)\s+komutu\s+g(ö|o)ster\b", t)
    if m:
        return Parsed(intent="debug_tail_logs", slots={"n": int(m.group(1))})
    if re.search(r"\b(logları|loglari)\s+g(ö|o)ster\b", t):
        return Parsed(intent="debug_tail_logs", slots={"n": 20})

    # Event history: "son olaylar", "olayları göster", "eventler"
    m = re.search(r"\bson\s+(\d+)\s+olay[ıi]?\b", t)
    if m:
        return Parsed(intent="show_events", slots={"n": int(m.group(1))})
    if re.search(r"\b(son\s+olaylar|olaylar[ıi]?\s+g[oö]ster|eventler|event\s+history)\b", t):
        return Parsed(intent="show_events", slots={"n": 10})

    # ─────────────────────────────────────────────────────────────────
    # PC Control / App commands
    # ─────────────────────────────────────────────────────────────────
    
    # App list: "uygulamalar", "pencereler", "açık pencereler"
    if re.search(r"\b(uygulamalar[ıi]?|pencereler[ıi]?|a[çc][ıi]k\s+pencereler|windows?)\b.*(g[oö]ster|listele)?", t):
        if re.search(r"\b(listele|g[oö]ster|neler?)\b", t) or t in {"uygulamalar", "pencereler", "açık pencereler"}:
            return Parsed(intent="app_list", slots={})
    
    # App close: "discord kapat", "spotify'ı kapat", "uygulamayı kapat"
    m = re.search(r"\b([a-zA-ZğüşıöçĞÜŞİÖÇ0-9_-]+)['\s]*(ı|i|u|ü|y[ıiuü])?\s*kapat\b", t)
    if m:
        app = m.group(1).lower()
        if app not in {"pencere", "dosya", "sekme", "tab", "browser", "tarayıcı"}:
            return Parsed(intent="app_close", slots={"app": app})
    
    # App focus/switch: "discord'a geç", "spotify'a odaklan", "firefox öne al"
    m = re.search(r"\b([a-zA-ZğüşıöçĞÜŞİÖÇ0-9_-]+)['\s]*(a|e|'a|'e)?\s*(ge[çc]|odaklan|[oö]ne\s+al|fokusla)\b", t)
    if m:
        app = m.group(1).lower()
        if app not in {"geri", "ileri", "sonraki", "önceki"}:
            return Parsed(intent="app_focus", slots={"app": app})
    
    # App open: "discord aç", "spotify'ı aç", "vscode başlat" (CHECK AFTER browser_open!)
    # This is more specific than browser site patterns
    m = re.search(r"\b([a-zA-ZğüşıöçĞÜŞİÖÇ0-9_-]+)['\s]*(ı|i|u|ü|y[ıiuü])?\s*(a[çc]|ba[şs]lat|[çc]al[ıi][şs]t[ıi]r)\b", t)
    if m:
        app = m.group(1).lower()
        # Exclude browser-related keywords that should be handled by browser_open
        browser_keywords = {
            "google", "tarayıcı", "browser", "sayfa", "site", "url", "link",
            # Social media / web sites -> browser_open, not app_open
            "instagram", "youtube", "twitter", "facebook", "github", "linkedin",
            "reddit", "twitch", "netflix", "whatsapp", "telegram",
            "wikipedia", "vikipedi", "amazon", "ebay", "stackoverflow",
            # AI chat services
            "duck", "duckduckgo", "chatgpt", "claude", "gemini", "perplexity",
            # Browser action keywords (not apps) - video/link variants
            "video", "videoyu", "videosunu", "videosuna", "videosu",
            "sonuç", "sonucu", "sonucunu", "link", "linki", "linkini",
            "ilk", "birinci", "ikinci", "üçüncü", "şu", "bu",
            # Music/media words that are usually browser targets
            "müzik", "müziği", "müziğini", "kanal", "kanalı", "kanalını", "playlist",
            # News-related keywords - handled by news intents
            "haber", "haberi", "haberin", "haberini", "haberleri",
        }
        if app not in browser_keywords:
            return Parsed(intent="app_open", slots={"app": app})
    
    # App type: "yaz: merhaba", "şunu yaz: test" (in app context)
    m = re.search(r"\b(yaz|type)\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        text_to_type = m.group(2).strip()
        return Parsed(intent="app_type", slots={"text": text_to_type})
    
    # App submit: "gönder", "enter bas", "yolla"
    if re.search(r"\b(g[oö]nder|enter\s*bas|yolla|submit)\b", t):
        return Parsed(intent="app_submit", slots={})
    
    # App session exit: "uygulamadan çık", "normal moda dön", "bitti"
    if re.search(r"\b(uygulama(dan)?\s*[çc][ıi]k|app\s*session\s*[çc][ıi]k|normal\s*moda?\s*d[oö]n|bitti|tamam\s*bitti)\b", t):
        return Parsed(intent="app_session_exit", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Advanced desktop input (Issue #2)
    # Explicit prefixes to avoid clashing with browser intents.
    # ─────────────────────────────────────────────────────────────────

    # Clipboard set: "panoya kopyala: ...", "clipboard set: ..."
    m = re.search(r"\b(panoya\s+kopyala|clipboard\s+set)\b\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="clipboard_set", slots={"text": m.group(2).strip()})

    # Clipboard get: "panoda ne var", "panoyu oku", "clipboard getir"
    if re.search(r"\b(panoda\s+ne\s+var|panoyu\s+oku|clipboard\s+(getir|oku|get))\b", t):
        return Parsed(intent="clipboard_get", slots={})

    # Mouse click: "mouse 500 300 sol tıkla", "fare sağ tıkla", "mouse çift tık"
    m = re.search(
        r"\b(mouse|fare)\b(?:[^\d]*(\d{1,5})\s*[, ]\s*(\d{1,5}))?[^\n]*?\b(?:(sol|sa[ğg]|orta)\s*)?(çift\s*)?(t[ıi]kla|click)\b",
        t,
    )
    if m:
        x = int(m.group(2)) if m.group(2) else None
        y = int(m.group(3)) if m.group(3) else None
        btn_raw = (m.group(4) or "sol").lower()
        button = "left"
        if btn_raw.startswith("sa"):
            button = "right"
        elif btn_raw.startswith("or"):
            button = "middle"
        double = m.group(5) is not None or "çift" in t
        return Parsed(intent="pc_mouse_click", slots={"x": x, "y": y, "button": button, "double": double})

    # Mouse scroll: "mouse aşağı 5 kaydır", "fare yukarı kaydır"
    m = re.search(r"\b(mouse|fare)\b.*\b(a[şs]a[gğ][ıi]|yukar[ıi])\b(?:\s*(\d+))?\s*(kayd[ıi]r|scroll)\b", t)
    if m:
        dword = (m.group(2) or "").lower()
        direction = "down" if re.search(r"a[şs]a", dword) else "up"
        amount = int(m.group(3) or 3)
        return Parsed(intent="pc_mouse_scroll", slots={"direction": direction, "amount": amount})

    # Mouse move: "mouse 500 300 git", "imleç 800,400 götür" (requires explicit move verb)
    m = re.search(
        r"\b(mouse|fare|imle[çc])\b[^\d]*(\d{1,5})\s*[, ]\s*(\d{1,5})\b(?:[^\d]*(\d{1,5})\s*(ms|saniye|sn))?[^\n]*(git|g[oö]t[üu]r|ta[şs][ıi]|move)\b",
        t,
    )
    if m:
        x = int(m.group(2))
        y = int(m.group(3))
        dur_n = m.group(4)
        dur_unit = (m.group(5) or "").lower()
        duration_ms = 0
        if dur_n:
            n = int(dur_n)
            duration_ms = n if dur_unit == "ms" else int(n * 1000)
        return Parsed(intent="pc_mouse_move", slots={"x": x, "y": y, "duration_ms": duration_ms})

    # Hotkey: "kısayol: ctrl alt t", "hotkey: ctrl+shift+esc"
    m = re.search(r"\b(k[ıi]sayol|hotkey)\b\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        raw = m.group(2).strip()
        raw = re.sub(r"\b(bas|press|g[öo]nder)\b", "", raw, flags=re.IGNORECASE).strip()
        combo = raw.replace(" ", "+")
        combo = re.sub(r"\+{2,}", "+", combo)
        combo = combo.replace("control", "ctrl").replace("win", "super").replace("meta", "super")
        return Parsed(intent="pc_hotkey", slots={"combo": combo})

    # ─────────────────────────────────────────────────────────────────
    # Browser Agent commands
    # ─────────────────────────────────────────────────────────────────
    
    # AI chat: "duck'a sor: ...", "chatgpt'ye sor: ...", "claude'a sor: ..."
    m = re.search(r"\b(duck|chatgpt|claude|gemini|perplexity)['\s]*(a|e|'a|'e|'ya|'ye)?\s*(sor|yaz)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        service = m.group(1).lower()
        prompt = m.group(4).strip().strip(_TURKISH_QUOTES)
        return Parsed(intent="ai_chat", slots={"service": service, "prompt": prompt})
    
    # browser_search: Multiple patterns for search
    # Pattern 1: "youtube'da ara: kakshi amv" or "youtube'da ara kakshi amv"
    # Pattern 2: "youtube'da kakshi amv ara" (query before "ara")
    # Pattern 3: "youtube kakshi amv ara" (no 'da/de)
    # Pattern 4: "X ara" (simple search - defaults to YouTube if context is YouTube)
    # Pattern 5: "şunu ara: X", "bunu ara: X"
    
    # Pattern 1: "site'da ara: query" or "site'da ara query"
    m = re.search(r"\b(wikipedia|vikipedi|youtube|amazon|google|instagram)['\s]*(da|de|'da|'de)?\s*(ara|arat|bul)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        site = m.group(1).lower()
        query = m.group(4).strip().strip(_TURKISH_QUOTES)
        return _make_search_result(site, query)
    
    # Pattern 2: "site'da query ara" (query before ara)
    m = re.search(r"\b(wikipedia|vikipedi|youtube|amazon|google|instagram)['\s]*(da|de|'da|'de)\s+(.+?)\s+(ara|arat|bul)\b", text, flags=re.IGNORECASE)
    if m:
        site = m.group(1).lower()
        query = m.group(3).strip().strip(_TURKISH_QUOTES)
        return _make_search_result(site, query)
    
    # Pattern 3: "site query ara" (no 'da/de, query before ara)
    m = re.search(r"\b(youtube|google)['\s]+(.+?)\s+(ara|arat)\b", text, flags=re.IGNORECASE)
    if m:
        site = m.group(1).lower()
        query = m.group(2).strip().strip(_TURKISH_QUOTES)
        return _make_search_result(site, query)
    
    # Pattern 4: "X'i ara", "X'u ara", "X ara" (simple search - context-aware, defaults to YouTube)
    # Must be at least 2 words or end with ara and have a query
    m = re.search(r"^(.+?)['\s]*(yi|y[ıiuü]|[ıiuü])\s*(ara|arat)$", t)
    if m:
        query = m.group(1).strip().strip(_TURKISH_QUOTES)
        if len(query) >= 2 and query not in {"sayfa", "google", "youtube", "video", "link"}:
            # This will use browser_search intent which checks current site context
            return Parsed(intent="browser_search", slots={"query": query})
    
    # Pattern 5: "şunu ara: X", "bunu ara: X", "şunu ara X"
    m = re.search(r"\b([şs]unu|bunu)\s*(ara|arat)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        query = m.group(3).strip().strip(_TURKISH_QUOTES)
        return Parsed(intent="browser_search", slots={"query": query})
    
    # Pattern 6: "X ara" at end of sentence (e.g., "naruto ara", "lofi music ara")
    m = re.search(r"^([a-zA-ZğüşıöçĞÜŞİÖÇ0-9\s]+)\s+(ara|arat)$", t)
    if m:
        query = m.group(1).strip()
        # Must be at least 3 chars and not a common word
        if len(query) >= 3 and query not in {"sayfa", "sayfayı", "google", "youtube", "video", "link", "bunu", "şunu", "onu"}:
            return Parsed(intent="browser_search", slots={"query": query})

    # browser_open: "instagram'ı aç", "twitter aç", "github.com aç", "wikipedia aç", "duck aç"
    # Issue #1058: action verb (aç|başlat) is now REQUIRED — just mentioning
    # a site name (e.g. "instagram güzel") must NOT trigger browser_open.
    m = re.search(r"\b(instagram|twitter|facebook|youtube|github|linkedin|reddit|twitch|spotify|netflix|whatsapp|telegram|discord|wikipedia|vikipedi|amazon|ebay|stackoverflow|stack\s*overflow|duck|duckduckgo|chatgpt|claude|gemini|perplexity)\b['\s]*(ı|i|'?y[ıi])?\s*(aç|başlat)", t)
    if m:
        site = m.group(1).lower().replace(" ", "")
        urls = {
            "instagram": "instagram.com",
            "twitter": "twitter.com",
            "facebook": "facebook.com",
            "youtube": "youtube.com",
            "github": "github.com",
            "linkedin": "linkedin.com",
            "reddit": "reddit.com",
            "twitch": "twitch.tv",
            "spotify": "open.spotify.com",
            "netflix": "netflix.com",
            "whatsapp": "web.whatsapp.com",
            "telegram": "web.telegram.org",
            "discord": "discord.com",
            "wikipedia": "tr.wikipedia.org",
            "vikipedi": "tr.wikipedia.org",
            "amazon": "amazon.com",
            "ebay": "ebay.com",
            "stackoverflow": "stackoverflow.com",
            # AI Chat services
            "duck": "duck.ai",
            "duckduckgo": "duckduckgo.com",
            "chatgpt": "chat.openai.com",
            "claude": "claude.ai",
            "gemini": "gemini.google.com",
            "perplexity": "perplexity.ai",
        }
        return Parsed(intent="browser_open", slots={"url": urls.get(site, site + ".com")})

    # browser_scan: "sayfayı tara", "yeniden tara", "linkleri göster", "öğeleri listele"
    if re.search(r"\b(sayfay[ıi]\s+tara|sayfay[ıi]\s+taray|yeniden\s+tara|tekrar\s+tara|linkleri\s+g[oö]ster|[oö][gğ]eleri\s+(g[oö]ster|listele)|elemanlari\s+g[oö]ster|bu\s+sayfada\s+ne\s+var)\b", t):
        return Parsed(intent="browser_scan", slots={})

    # browser_detail: "detay 5", "[5] detay", "5 hakkında bilgi"
    m = re.search(r"\b(detay|bilgi|info)\s*:?\s*(\d+)\b", t)
    if m:
        return Parsed(intent="browser_detail", slots={"index": int(m.group(2))})
    m = re.search(r"\[?(\d+)\]?\s*(hakk[ıi]nda\s+bilgi|detay[ıi]?|info)", t)
    if m:
        return Parsed(intent="browser_detail", slots={"index": int(m.group(1))})

    # browser_wait: "bekle 3 saniye", "3 saniye bekle"
    m = re.search(r"\b(bekle|wait)\s*:?\s*(\d+)\s*(saniye|sn|s)?\b", t)
    if m:
        return Parsed(intent="browser_wait", slots={"seconds": int(m.group(2))})
    m = re.search(r"\b(\d+)\s*(saniye|sn|s)\s+(bekle|wait)\b", t)
    if m:
        return Parsed(intent="browser_wait", slots={"seconds": int(m.group(1))})

    # Smart click: "şu videoyu aç", "ilk videoyu aç", "birinci sonuca tıkla" (BEFORE numeric click!)
    m = re.search(r"\b(ilk|birinci|first)\s+(video|sonu[cç]|link)[uıiy]?(yu|u|y[ıi])?\s*(a[cç]|t[ıi]kla|se[cç]|oynat|izle)", t)
    if m:
        return Parsed(intent="browser_click", slots={"index": 1})
    m = re.search(r"\b(ikinci|second)\s+(video|sonu[cç]|link)[uıiy]?(yu|u|y[ıi])?\s*(a[cç]|t[ıi]kla|se[cç]|oynat|izle)", t)
    if m:
        return Parsed(intent="browser_click", slots={"index": 2})
    m = re.search(r"\b([üu][cç][üu]nc[üu]|third)\s+(video|sonu[cç]|link)[uıiy]?(yu|u|y[ıi])?\s*(a[cç]|t[ıi]kla|se[cç]|oynat|izle)", t)
    if m:
        return Parsed(intent="browser_click", slots={"index": 3})
    
    # "şu videoyu aç", "bu sonucu aç" - click first
    if re.search(r"\b([şs]u|bu)\s+(video|sonu[cç])[uıiy]?(yu|u|y[ıi])?\s*(a[cç]|t[ıi]kla|oynat|izle)", t):
        return Parsed(intent="browser_click", slots={"index": 1})

    # browser_click by index: "12'ye tıkla", "3'e bas", "[5] tıkla"
    m = re.search(r"(\d+)['\s]*(ye|e|a|ya)?\s*(t[ıi]kla|bas|se[cç])", t)
    if m:
        return Parsed(intent="browser_click", slots={"index": int(m.group(1))})
    m = re.search(r"\[(\d+)\]", t)
    if m and re.search(r"(t[ıi]kla|bas|se[cç])", t):
        return Parsed(intent="browser_click", slots={"index": int(m.group(1))})

    # browser_click by text: "'Log in' yazana tıkla", "giriş yap butonuna tıkla"
    m = re.search(r"['\"]([^'\"]+)['\"]\s*(yazan[ae]?|button[ua]?|[oö][gğ]esine)?\s*(t[ıi]kla|bas)", text)
    if m:
        return Parsed(intent="browser_click", slots={"text": m.group(1)})
    m = re.search(r"([a-zA-ZğüşıöçĞÜŞİÖÇ\s]+)\s+(butonuna|linkine|[oö][gğ]esine)\s+(t[ıi]kla|bas)", t)
    if m:
        return Parsed(intent="browser_click", slots={"text": m.group(1).strip()})
    
    # browser_click by name: "lofi girl videosunu aç", "study with me videoyu oynat"
    # Pattern: <isim> + video/link/müzik suffix + action
    m = re.search(r"(.+?)\s+(video|link|kanal|m[uü]zi[kğ])[suıiüğ]*(n[uıiü]|y[ıiuü])?\s*(aç|a[çc]|tıkla|oynat|izle|başlat|dinle)", t)
    if m:
        name = m.group(1).strip()
        # Skip if starts with ordinal or demonstrative
        if not re.match(r"^(ilk|birinci|ikinci|üçüncü|bu|şu|\d)", name):
            return Parsed(intent="browser_click", slots={"text": name})
    
    # browser_click by name: "<isim>'e tıkla", "<isim>'i aç" (apostrophe patterns)  
    m = re.search(r"(.+?)['\']?[eyia]?\s+(tıkla|aç|oynat|izle|başlat)$", t)
    if m:
        name = m.group(1).strip()
        # Must be long enough and not a common word/command
        if len(name) > 5 and not re.match(r"^(ilk|birinci|ikinci|üçüncü|bu|şu|bunu|şunu|video|link|sayfa|\d)", name):
            return Parsed(intent="browser_click", slots={"text": name})

    # browser_type: "şunu yaz: ...", "[3] alanına yaz: ..."
    m = re.search(r"\[(\d+)\]\s*(alan[ıi]na)?\s*yaz\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="browser_type", slots={"index": int(m.group(1)), "text": m.group(3).strip()})
    m = re.search(r"\b(şunu\s+yaz|yaz)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="browser_type", slots={"text": m.group(2).strip()})

    # browser_scroll
    if re.search(r"\b(a[şs]a[gğ][ıi](ya)?\s+kayd[ıi]r|sayfay[ıi]\s+a[şs]a[gğ][ıi]\s+kayd[ıi]r|scroll\s+down|a[şs]a[gğ][ıi]\s+in)\b", t):
        return Parsed(intent="browser_scroll_down", slots={})
    if re.search(r"\b(yukar[ıi](ya)?\s+kayd[ıi]r|sayfay[ıi]\s+yukar[ıi]\s+kayd[ıi]r|scroll\s+up|yukar[ıi]\s+c[ıi]k)\b", t):
        return Parsed(intent="browser_scroll_up", slots={})

    # browser_back
    if re.search(r"\b(geri\s+d[oö]n|geri\s+git|[oö]nceki\s+sayfa|back)\b", t):
        return Parsed(intent="browser_back", slots={})

    # browser_info: "bu sayfa ne", "neredeyim"
    if re.search(r"\b(bu\s+sayfa\s+ne|neredeyim|hangi\s+sayfa)\b", t):
        return Parsed(intent="browser_info", slots={})

    # ─────────────────────────────────────────────────────────────────
    # News Briefing Commands (Jarvis-style news)
    # Check specific patterns FIRST, then general patterns
    # ─────────────────────────────────────────────────────────────────
    
    # Open news result by index: "3. haberi aç", "3. haberi göster", "2. sonucu aç"
    # MUST be checked BEFORE general "haberi göster" pattern
    m = re.search(r"\b(\d+)\.\s*(haber|sonu[çc])([uıiü])?([yn][uıiü])?\s*(a[çc]|g[öo]ster|oku)\b", t)
    if m:
        return Parsed(intent="news_open_result", slots={"index": int(m.group(1))})
    
    # Open by ordinal: "birinci haberi aç", "ikinci haberi aç", "üçüncü haberi aç"
    m = re.search(r"\b(birinci|ilk)\s*(haber|sonu[çc])([uıiü])?([yn][uıiü])?\s*(a[çc]|g[öo]ster)\b", t)
    if m:
        return Parsed(intent="news_open_result", slots={"index": 1})
    m = re.search(r"\b(ikinci|second)\s*(haber|sonu[çc])([uıiü])?([yn][uıiü])?\s*(a[çc]|g[öo]ster)\b", t)
    if m:
        return Parsed(intent="news_open_result", slots={"index": 2})
    m = re.search(r"\b([üu][çc][üu]nc[üu]|third)\s*(haber|sonu[çc])([uıiü])?([yn][uıiü])?\s*(a[çc]|g[öo]ster)\b", t)
    if m:
        return Parsed(intent="news_open_result", slots={"index": 3})
    
    # Open current news: "bu haberi aç", "şu haberi aç"
    if re.search(r"\b([şs]u|bu)\s*(haber|sonu[çc])([uıiü])?([yn][uıiü])?\s*(a[çc]|g[öo]ster)\b", t):
        return Parsed(intent="news_open_current", slots={})
    
    # More news: "daha fazla haber", "devamını göster", "diğer haberler"
    if re.search(r"\b(daha\s+fazla\s+haber|devam[ıi]n[ıi]\s+g[öo]ster|di[ğg]er\s+haberler|sonraki\s+haberler)\b", t):
        return Parsed(intent="news_more", slots={})
    
    # News briefing: "bugünkü haberlerde ne var", "günlük haberleri göster", "gündem ne"
    if re.search(r"\b(bug[üu]nk[üu]|g[üu]nl[üu]k|son)?\s*(haberlerde?|g[üu]ndem)\s*(de|da)?\s*(ne\s+var|neler?\s+var|ne)\b", t):
        return Parsed(intent="news_briefing", slots={"query": "gündem"})
    
    # News with topic: "teknoloji haberleri", "ekonomi haberi", "spor haberleri"
    m = re.search(r"\b(teknoloji|ekonomi|spor|siyaset|sa[ğg]l[ıi]k|e[ğg]itim|k[üu]lt[üu]r|magazin|d[üu]nya|t[üu]rkiye)\s*(haber(ler)?i?)\b", t)
    if m:
        topic = m.group(1).strip()
        return Parsed(intent="news_briefing", slots={"query": topic})
    
    # News search: "haberleri göster", "haberler oku", "haberleri getir", "haberleri aç"
    # Only matches plural forms to avoid matching "X haberi aç"
    if re.search(r"\bhaber(ler)[iı]?\s*(g[öo]ster|oku|getir|a[çc]|ver)\b", t):
        return Parsed(intent="news_briefing", slots={"query": "gündem"})

    # ─────────────────────────────────────────────────────────────────
    # Page Summarization Commands (Jarvis-style)
    # ─────────────────────────────────────────────────────────────────
    
    # Question about page content: "Bu CEO kim?", "Fiyatı ne?", "Kim yazmış?"
    # Must check BEFORE general summarize patterns
    m = re.search(r"\b(bu|şu|o)\s+(.+?)(\s+kim|\s+ne\s+zaman|\s+neden|\s+nas[ıi]l|\s+nerede)\b.*\?", t)
    if m:
        question = text.strip()
        return Parsed(intent="page_question", slots={"question": question})
    
    # Direct questions: "CEO kim?", "Fiyatı ne?", "Kaç para?", "Ne zaman?"
    # Guard: only match if the question references page/content context
    # (bu/şu/sayfa/site/makale/içerik) to avoid hijacking calendar/gmail queries.
    if re.search(r"\b(kim|ne|neden|nas[ıi]l|nerede|ka[çc])\b.*\?$", t):
        if re.search(r"\b(bu|şu|sayfa|site|makale|i[çc]erik|yaz[ıi]|paragraf)\b", t):
            question = text.strip()
            return Parsed(intent="page_question", slots={"question": question})
    
    # Detailed summarize: "detaylı anlat", "tam anlat", "daha detaylı özetle"
    if re.search(r"\b(tam|daha\s+)?(detayl[ıi]|uzun)\s*(anlat|[öo]zetle|a[çc][ıi]kla)\b", t):
        return Parsed(intent="page_summarize_detailed", slots={})
    
    # Detailed summarize: "detaylı olarak anlat", "ayrıntılı açıkla"
    if re.search(r"\b(detayl[ıi]\s+olarak|ayr[ıi]nt[ıi]l[ıi])\s*(anlat|[öo]zetle|a[çc][ıi]kla)\b", t):
        return Parsed(intent="page_summarize_detailed", slots={})
    
    # Short summarize: "bu sayfayı özetle", "bu haberi anlat", "şu makaleyi oku"
    # Note: Turkish suffixes can be -ı/-i/-u/-ü or -yı/-yi/-yu/-yü or -nı/-ni/-nu/-nü
    # içerik -> içeriği (k->ğ mutation)
    if re.search(r"\b(bu|[şs]u)\s*(sayfa|haber|i[çc]eri[gğk]|makale|yaz[ıi])([yniıuü]+)?\s+([öo]zetle|anlat|a[çc][ıi]kla|oku)\b", t):
        return Parsed(intent="page_summarize", slots={})
    
    # Short summarize: "bunu özetle", "şunu anlat"
    if re.search(r"\b(bunu|[şs]unu)\s*([öo]zetle|anlat|a[çc][ıi]kla)\b", t):
        return Parsed(intent="page_summarize", slots={})
    
    # Short summarize: "özetle", "anlat bakalım", "ne anlatıyor", "ne yazıyor"
    if re.search(r"\b(ne\s+anlat[ıi]yor|ne\s+yaz[ıi]yor|ne\s+diyor|neler\s+var)\b", t):
        return Parsed(intent="page_summarize", slots={})
    
    # Short summarize: "anlayamadım anlat", "anlamadım açıkla"
    if re.search(r"\b(anlaya?mad[ıi]m|anlamad[ıi]m).*(anlat|a[çc][ıi]kla|[öo]zetle)\b", t):
        return Parsed(intent="page_summarize", slots={})
    
    # Summarize with question marker: "bu ne anlatıyor bana?"
    if re.search(r"\b(bu|[şs]u)\s+(ne\s+anlat|ne\s+yaz|ne\s+di)\b", t):
        return Parsed(intent="page_summarize", slots={})

    # ─────────────────────────────────────────────────────────────────
    # Original skills
    # ─────────────────────────────────────────────────────────────────

    # btop
    if re.search(r"\bbtop\b", t):
        return Parsed(intent="open_btop", slots={})

    # browser open (legacy - opens google via xdg-open)
    if re.search(r"\b(google'?ı|google|tarayıcıyı|browser)\b.*\b(aç|başlat)\b", t) or t in {"google", "google aç"}:
        return Parsed(intent="open_browser", slots={})

    # open_url: "şu sayfayı aç: ...", "şu url'i aç: ...", "aç: https://..."
    m = re.search(
        r"\b(şu\s+sayfay[ıi]|şu\s+url'?[iı]?|şu\s+linki?|bu\s+sayfay[ıi]|url)\s*(aç|a[çc])\s*:?\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        url = m.group(3).strip().strip(_TURKISH_QUOTES)
        return Parsed(intent="browser_open", slots={"url": url})
    # Fallback: direct URL pattern
    m = re.search(r"\b(aç|open)\s*:?\s*(https?://\S+)", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="browser_open", slots={"url": m.group(2).strip()})

    # notify
    m = re.search(r"\b(bildirim|notify)\b.*?:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="notify", slots={"message": m.group(2).strip()})

    # open path (must come after open_url checks)
    m = re.search(r"\b(aç|open)\b\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        target = m.group(2).strip().strip(_TURKISH_QUOTES)
        # Eğer 'google'da ara' gibi bir şey değilse ve URL değilse
        if not re.search(r"google.*\bara\b", t) and not re.match(r"https?://", target):
            return Parsed(intent="open_path", slots={"target": target})

    # google search
    m = re.search(r"\b(google'?da|google)\b.*\b(ara|arama)\b\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        q = m.group(3).strip().strip(_TURKISH_QUOTES)
        return Parsed(intent="google_search", slots={"query": q})

    m = re.search(r"\bşunu ara\b\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        q = m.group(1).strip().strip(_TURKISH_QUOTES)
        return Parsed(intent="google_search", slots={"query": q})

    # ─────────────────────────────────────────────────────────────────
    # Reminder / Scheduler commands (check specific patterns BEFORE generic "hatırlat")
    # ─────────────────────────────────────────────────────────────────

    # reminder_list: "hatırlatmalarım", "hatırlatmaları listele", "hatırlatmaları göster"
    if re.search(r"\bhat[ıi]rlat(ma|ıcı)?(lar)?[ıi]?(m[ıi])?\b.*(listele|g[oö]ster|neler?|ne\s+var)", t):
        return Parsed(intent="reminder_list", slots={})
    if re.search(r"\bhat[ıi]rlat(ma|ıcı)?lar[ıi]m\b", t):
        return Parsed(intent="reminder_list", slots={})
    if t in {"hatırlatmalar", "hatırlatmalarım", "hatırlatıcılar", "reminders"}:
        return Parsed(intent="reminder_list", slots={})

    # reminder_delete: "hatırlatma 3'ü sil", "3 numaralı hatırlatmayı sil", "#3 sil"
    m = re.search(r"\bhat[ıi]rlat(ma|ıcı)?\s*#?(\d+)['\s]*(ü|u|i|ı|yi|yı|yu|yü|y[ıi])?\s*sil", t)
    if m:
        return Parsed(intent="reminder_delete", slots={"id": int(m.group(2))})
    m = re.search(r"#(\d+)\s*(numaral[ıi])?\s*(hat[ıi]rlat(ma)?)?\s*sil", t)
    if m:
        return Parsed(intent="reminder_delete", slots={"id": int(m.group(1))})
    m = re.search(r"(\d+)\s*(numara(l[ıi])?)?\s*hat[ıi]rlat(ma|ıcı)?(y[ıi])?\s*sil", t)
    if m:
        return Parsed(intent="reminder_delete", slots={"id": int(m.group(1))})

    # reminder_snooze: "hatırlatma 3'ü ertele", "#3 10 dakika ertele"
    m = re.search(r"\bhat[ıi]rlat(ma|ıcı)?\s*#?(\d+)['\s]*(ü|u|i|ı|y[ıi])?\s*(\d+)?\s*(dakika|dk)?\s*ertele", t)
    if m:
        reminder_id = int(m.group(2))
        minutes = int(m.group(4)) if m.group(4) else 10
        return Parsed(intent="reminder_snooze", slots={"id": reminder_id, "minutes": minutes})
    m = re.search(r"#(\d+)\s*(\d+)?\s*(dakika|dk)?\s*ertele", t)
    if m:
        reminder_id = int(m.group(1))
        minutes = int(m.group(2)) if m.group(2) else 10
        return Parsed(intent="reminder_snooze", slots={"id": reminder_id, "minutes": minutes})

    # reminder_add: Check various patterns
    # Turkish number words to digits mapping
    _TR_NUMBERS = {
        "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
        "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9", 
        "on bir": "11", "on iki": "12", "on üç": "13", "on dört": "14", "on beş": "15",
        "on altı": "16", "on yedi": "17", "on sekiz": "18", "on dokuz": "19", 
        "yirmi beş": "25", "kırk beş": "45",
        "on": "10", "yirmi": "20", "otuz": "30",
    }
    
    def _normalize_time(time_str: str) -> str:
        """Convert Turkish number words to digits in time expressions."""
        result = time_str.lower()
        # Sort by length descending to match "on beş" before "on"
        for word, digit in sorted(_TR_NUMBERS.items(), key=lambda x: -len(x[0])):
            # Use word boundaries to avoid partial matches
            result = re.sub(r'\b' + re.escape(word) + r'\b', digit, result)
        return result
    
    # Pattern: "5 dakika sonra hatırlat: toplantı" or "5 dakika sonra hatırlat toplantı"
    m = re.search(r"(\d+\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra)\s*hat[ıi]rlat\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(2).strip()})
    
    # Pattern: "hatırlat 2 dakika sonra switch" (time after hatırlat, no colon) - supports both digits and words
    m = re.search(r"\bhat[ıi]rlat\s+((?:\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on(?:\s+(?:bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz))?|yirmi(?:\s+beş)?|otuz|kırk(?:\s+beş)?)\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": _normalize_time(m.group(1).strip()), "message": m.group(2).strip()})
    
    # Pattern: "yarın 9:00 hatırlat: toplantı"
    m = re.search(r"(yar[ıi]n\s*\d{1,2}[:.]\d{2})\s*hat[ıi]rlat\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(2).strip()})
    
    # Pattern: "saat 20:00'da hatırlat: çöp" 
    m = re.search(r"\bsaat\s+(\d{1,2}[:.]\d{2})['\s]*(da|de|'da|'de)?\s*hat[ıi]rlat\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(3).strip()})
    
    # Pattern: "hatırlat: 20:00 çöpü çıkar" - Time then message
    m = re.search(r"\bhat[ıi]rlat\s*:\s*(\d{1,2}[:.]\d{2})\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(2).strip()})
    
    # Pattern: "hatırlat: yarın 9:00 toplantı"
    m = re.search(r"\bhat[ıi]rlat\s*:\s*(yar[ıi]n\s*\d{1,2}[:.]\d{2})\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(2).strip()})
    
    # Pattern: "hatırlat: 5 dakika sonra çay"
    m = re.search(r"\bhat[ıi]rlat\s*:\s*(\d+\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(2).strip()})
    
    # Pattern: "hatırlat: yarın 10'da toplantı" (informal time with 'da/'de suffix)
    m = re.search(r"\bhat[ıi]rlat\s*:\s*(yar[ıi]n\s*\d{1,2}['\s]*(da|de|'da|'de)?)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": m.group(1).strip(), "message": m.group(3).strip()})
    
    # Pattern: "hatırlat: message" (fallback - just message, no time specified = immediate/soon)
    m = re.search(r"\bhat[ıi]rlat\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="reminder_add", slots={"time": "5 dakika sonra", "message": m.group(1).strip()})

    # ─────────────────────────────────────────────────────────────────
    # Check-in commands (Bantz proactive conversations)
    # ─────────────────────────────────────────────────────────────────

    # checkin_list: "check-in'leri göster", "yoklamaları listele"
    if re.search(r"\b(check-?in|yoklama)(ler|lar)?[ıi]?\b.*(g[oö]ster|listele|neler?)", t):
        return Parsed(intent="checkin_list", slots={})
    if t in {"check-inler", "checkinler", "yoklamalar", "check-ins"}:
        return Parsed(intent="checkin_list", slots={})

    # checkin_delete: "check-in 3 sil", "#3 check-in sil"
    m = re.search(r"\b(check-?in|yoklama)\s*#?(\d+)['\s]*(ü|u|i|ı|y[ıi])?\s*sil", t)
    if m:
        return Parsed(intent="checkin_delete", slots={"id": int(m.group(2))})
    m = re.search(r"#(\d+)\s*(check-?in|yoklama)\s*sil", t)
    if m:
        return Parsed(intent="checkin_delete", slots={"id": int(m.group(1))})

    # checkin_pause: "check-in 3 durdur", "#3 check-in durdur"
    m = re.search(r"\b(check-?in|yoklama)\s*#?(\d+)['\s]*(ü|u|i|ı|y[ıi])?\s*(durdur|kapat|pause)", t)
    if m:
        return Parsed(intent="checkin_pause", slots={"id": int(m.group(2))})
    
    # checkin_resume: "check-in 3 başlat", "#3 check-in aktif"
    m = re.search(r"\b(check-?in|yoklama)\s*#?(\d+)['\s]*(ü|u|i|ı|y[ıi])?\s*(ba[şs]lat|a[çc]|aktif|resume|devam)", t)
    if m:
        return Parsed(intent="checkin_resume", slots={"id": int(m.group(2))})

    # checkin_add: Various patterns
    # "5 dakika sonra beni yokla: ..." or "5 dakika sonra yokla: ..."
    m = re.search(r"(\d+\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra)\s*(?:beni\s*)?(yokla|check-?in)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="checkin_add", slots={"schedule": m.group(1).strip(), "prompt": m.group(3).strip()})
    
    # "her gün 21:00'de yokla: ..." or "daily 21:00 check-in: ..."
    m = re.search(r"((?:her\s*g[uü]n|daily)\s*\d{1,2}[:.]\d{2})['\s]*(da|de|'da|'de)?\s*(?:beni\s*)?(yokla|check-?in)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="checkin_add", slots={"schedule": m.group(1).strip(), "prompt": m.group(4).strip()})
    
    # "yarın 9:00 yokla: ..." 
    m = re.search(r"(yar[ıi]n\s*\d{1,2}[:.]\d{2})\s*(?:beni\s*)?(yokla|check-?in)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="checkin_add", slots={"schedule": m.group(1).strip(), "prompt": m.group(3).strip()})
    
    # "yokla: 20:00 mesaj" or "check-in: 5 dakika sonra mesaj"
    m = re.search(r"\b(?:beni\s*)?(yokla|check-?in)\s*:\s*(\d{1,2}[:.]\d{2}|\d+\s*(?:dakika|dk|saat|sa|saniye|sn)\s*sonra)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="checkin_add", slots={"schedule": m.group(2).strip(), "prompt": m.group(3).strip()})

    # ─────────────────────────────────────────────────────────────────
    # Coding Agent Commands (Issue #4)
    # File operations, terminal, code editing via natural language
    # ─────────────────────────────────────────────────────────────────
    
    # File read: "dosya oku: path", "oku: file.py", "file.py dosyasını oku"
    m = re.search(r"(dosya|file)\s*(oku|okuyabilir\s+misin|göster)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="file_read", slots={"path": m.group(3).strip()})
    m = re.search(r"oku\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="file_read", slots={"path": m.group(1).strip()})
    m = re.search(r"(.+?)\s+dosyas[ıi]n[ıi]\s+(oku|göster)", t)
    if m:
        return Parsed(intent="file_read", slots={"path": m.group(1).strip()})
    
    # File write/create: "dosya yaz: path", "oluştur: file.py"
    m = re.search(r"(dosya|file)\s*(yaz|oluştur|olu[sş]tur|create)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="file_create", slots={"path": m.group(3).strip()})
    m = re.search(r"olu[sş]tur\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="file_create", slots={"path": m.group(1).strip()})
    
    # File list/tree: "dosyaları listele", "proje yapısı", "tree", "ls"
    if re.search(r"\b(dosyalar[ıi]?\s+(listele|g[öo]ster)|proje\s+yap[ıi]s[ıi]|tree|file\s+tree|klasör\s+yap[ıi]s[ıi])\b", t):
        return Parsed(intent="project_tree", slots={})
    
    # File search: "dosya ara: *.py", "ara: config"
    m = re.search(r"(dosya|file)?\s*ara\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m and m.group(2).strip():
        return Parsed(intent="file_search", slots={"pattern": m.group(2).strip()})
    
    # Undo: "geri al", "undo", "son değişikliği geri al"
    if re.search(r"\b(geri\s+al|undo|son\s+de[ğg]i[şs]ikli[ğg]i\s+geri\s+al)\b", t):
        return Parsed(intent="file_undo", slots={})
    
    # Terminal run: "terminal: ls -la", "çalıştır: npm run dev", "run: pytest"
    m = re.search(r"(terminal|[çc]al[ıi][şs]t[ıi]r|run|shell|exec)\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="terminal_run", slots={"command": m.group(2).strip()})
    
    # Background process: "arka planda: npm run dev", "background: python server.py"
    m = re.search(r"(arka\s*planda?|background|bg)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="terminal_background", slots={"command": m.group(2).strip()})
    
    # Background list/kill: "arka plan işlemleri", "bg kill 1"
    if re.search(r"\b(arka\s*plan\s*i[şs]lemleri?|background\s*processes?|bg\s+list)\b", t):
        return Parsed(intent="terminal_background_list", slots={})
    m = re.search(r"\b(bg\s+kill|arka\s*plan\s*kapat)\s+(\d+)\b", t)
    if m:
        return Parsed(intent="terminal_background_kill", slots={"id": int(m.group(2))})
    
    # Code format: "formatla: file.py", "format: src/", "kodu formatla"
    m = re.search(r"(formatla|format|düzenle)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="code_format", slots={"path": m.group(2).strip()})
    
    # Project info: "proje bilgisi", "dependencies", "bağımlılıklar"
    if re.search(r"\b(proje\s+bilgi(si)?|project\s+info|ba[ğg][ıi]ml[ıi]l[ıi]klar|dependencies)\b", t):
        return Parsed(intent="project_info", slots={})
    
    # Symbol search: "fonksiyon bul: parse", "class ara: Router"
    m = re.search(r"(fonksiyon|function|class|sembol|symbol)\s*(bul|ara)\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        symbol_type = "function" if "fonk" in m.group(1).lower() or "func" in m.group(1).lower() else "class" if "class" in m.group(1).lower() else None
        return Parsed(intent="project_search_symbol", slots={"name": m.group(3).strip(), "type": symbol_type})
    
    # Symbols in file: "semboller: file.py", "fonksiyonlar: engine.py"
    m = re.search(r"(sembol|symbol|fonksiyon|function|class)ler[ıi]?\s*:?\s*(.+)$", text, flags=re.IGNORECASE)
    if m:
        return Parsed(intent="project_symbols", slots={"path": m.group(2).strip()})

    # dev mode placeholder
    if re.search(r"\b(repo|test|build|branch|commit|pull request|pr|ci)\b", t):
        return Parsed(intent="dev_task", slots={"text": text})

    # Risky system commands (will be caught by confirm policy)
    if re.search(r"\b(kill|pkill|killall|systemctl|service)\b", t):
        return Parsed(intent="unknown", slots={"text": text, "risky": True})

    # ─────────────────────────────────────────────────────────────────
    # Vague Search Detection (Issue #21)
    # "şurada kaza olmuş", "geçenlerde birşey olmuş orada"
    # These should trigger clarification flow
    # ─────────────────────────────────────────────────────────────────
    
    # Vague location indicators
    VAGUE_LOCATION = r"\b([şs]urada|orada|burada|burda|[şs]urda|bir\s*yerde|[şs]uradaki|oradaki|o\s*taraf(ta|lar)?)\b"
    
    # Vague time indicators  
    VAGUE_TIME = r"\b(ge[çc]enlerde|ge[çc]en\s*g[üu]n(lerde)?|d[üu]n|[şs]imdi|demin|az\s*[öo]nce|biraz\s*[öo]nce|son\s*zamanlarda)\b"
    
    # Vague subject indicators
    VAGUE_SUBJECT = r"\b(bir\s*[şs]ey(ler)?|bi'?\s*[şs]i|neler|birisi|biri|adam|kad[ıi]n|bir\s*tip|kimse)\b"
    
    # Event patterns that may be vague
    EVENT_WORDS = r"\b(kaza|yang[ıi]n|deprem|olay|sald[ıi]r[ıi]|patlama|sel|kavga|cinayet|h[ıi]rs[ıi]zl[ıi]k|olmu[şs]|ya[şs]an[ıi]yor)\b"
    
    # Check for vague patterns
    has_vague_location = bool(re.search(VAGUE_LOCATION, t))
    has_vague_time = bool(re.search(VAGUE_TIME, t))
    has_vague_subject = bool(re.search(VAGUE_SUBJECT, t))
    has_event = bool(re.search(EVENT_WORDS, t))
    
    # If there's an event with vague indicators, mark as vague_search
    if has_event and (has_vague_location or has_vague_time or has_vague_subject):
        vague_slots = {
            "text": text,
            "has_vague_location": has_vague_location,
            "has_vague_time": has_vague_time,
            "has_vague_subject": has_vague_subject,
        }
        return Parsed(intent="vague_search", slots=vague_slots)
    
    # Generic "neler olmuş" patterns
    if re.search(r"\b(neler\s+olmu[şs]|ne\s+olmu[şs]|ne\s+var\s+ne\s+yok)\b", t):
        if has_vague_location:
            return Parsed(intent="vague_search", slots={"text": text, "has_vague_location": True})

    return Parsed(intent="unknown", slots={"text": text})

