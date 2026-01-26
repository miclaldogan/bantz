from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .types import Intent

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class Parsed:
    intent: Intent
    slots: dict


_TURKISH_QUOTES = "'\"""''"

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

    # Queue control commands (highest priority)
    if t in {"duraklat", "bekle", "dur bir"}:
        return Parsed(intent="queue_pause", slots={})
    if t in {"devam et", "devam", "sürdür"}:
        return Parsed(intent="queue_resume", slots={})
    if t in {"iptal et", "tümünü iptal", "kuyruğu iptal", "zinciri iptal"}:
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
    m = re.search(r"\b(instagram|twitter|facebook|youtube|github|linkedin|reddit|twitch|spotify|netflix|whatsapp|telegram|discord|wikipedia|vikipedi|amazon|ebay|stackoverflow|stack\s*overflow|duck|duckduckgo|chatgpt|claude|gemini|perplexity)\b['\s]*(ı|i|'?y[ıi])?\s*(aç|başlat)?", t)
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

    # dev mode placeholder
    if re.search(r"\b(repo|test|build|branch|commit|pull request|pr|ci)\b", t):
        return Parsed(intent="dev_task", slots={"text": text})

    # Risky system commands (will be caught by confirm policy)
    if re.search(r"\b(kill|pkill|killall|systemctl|service)\b", t):
        return Parsed(intent="unknown", slots={"text": text, "risky": True})

    return Parsed(intent="unknown", slots={"text": text})
