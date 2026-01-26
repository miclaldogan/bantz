from __future__ import annotations

import os
import shlex
import subprocess
import urllib.parse
from pathlib import Path
from typing import Tuple


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, ""
    except FileNotFoundError:
        return False, f"Komut bulunamadı: {cmd[0]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def open_browser() -> Tuple[bool, str]:
    ok, err = _run(["xdg-open", "https://www.google.com"]) 
    return (True, "Google'ı açtım.") if ok else (False, f"Açamıyorum: {err}")


def google_search(query: str) -> Tuple[bool, str]:
    q = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={q}"
    ok, err = _run(["xdg-open", url])
    return (True, f"Google'da aradım: {query}") if ok else (False, f"Arama açılamadı: {err}")


def open_path(target: str) -> Tuple[bool, str]:
    # Basit kısayollar
    t = target.strip()
    lowered = t.lower()
    if lowered in {"indirilenler", "downloads"}:
        t = str(Path.home() / "Downloads")
    elif lowered in {"masaüstü", "desktop"}:
        t = str(Path.home() / "Desktop")
    elif lowered in {"ev", "home"}:
        t = str(Path.home())

    # ~ genişletme
    t = os.path.expanduser(t)

    # Eğer kullanıcı "bu dosyayı aç: ..." gibi bir şey yazdıysa, iki nokta sonrası gelebilir
    # shell parsing yok: güvenli kalmak için xdg-open'a tek argüman veriyoruz
    if not t:
        return False, "Hangi dosya/klasörü açayım?"

    ok, err = _run(["xdg-open", t])
    # Kullanıcıya yolu aynen değil daha düzgün göster
    shown = t
    if len(shown) > 120:
        shown = shown[:117] + "..."
    return (True, f"Açtım: {shown}") if ok else (False, f"Açamıyorum: {err}")


def notify(message: str) -> Tuple[bool, str]:
    msg = message.strip() or "Bantz"
    # notify-send varsa kullan
    ok, err = _run(["notify-send", "Bantz", msg])
    if ok:
        return True, "Bildirim gönderdim."
    # Yoksa terminale düş
    return True, f"(notify-send yok) Bildirim: {msg}"


def open_btop() -> Tuple[bool, str]:
    # btop terminal uygulaması; ayrı process olarak açıyoruz
    ok, err = _run(["btop"])
    return (True, "btop'u açtım.") if ok else (False, f"btop açılamadı: {err}")


def open_url(url: str) -> Tuple[bool, str]:
    """Open an arbitrary URL in the default browser."""
    u = url.strip()
    if not u:
        return False, "Hangi URL'i açayım?"
    # Normalize: add https:// if missing scheme
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    ok, err = _run(["xdg-open", u])
    shown = u if len(u) <= 80 else u[:77] + "..."
    return (True, f"Sayfayı açtım: {shown}") if ok else (False, f"Açamıyorum: {err}")
