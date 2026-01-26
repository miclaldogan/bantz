"""Bantz CLI - Interactive assistant with live browser session.

Modes:
  - Interactive (default): `bantz` or `bantz --serve`
  - Session command: `bantz --session <name> --once "command"`
  - Stateless once: `bantz --once "command"` (no browser persistence)
"""
from __future__ import annotations

import argparse
import os
import socket
import os
import sys
import shutil
import threading
import queue as queue_module
from collections import deque
from datetime import datetime
from typing import Optional

from bantz.router.engine import Router
from bantz.router.policy import Policy
from bantz.router.context import ConversationContext
from bantz.logs.logger import JsonlLogger


# ANSI colors
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


# Pager settings
PAGER_ENABLED = True
PAGER_LINES = 15  # Max lines before paging


def get_terminal_size() -> tuple[int, int]:
    """Get terminal width and height."""
    try:
        size = shutil.get_terminal_size()
        return size.columns, size.lines
    except:
        return 80, 24


def paged_print(text: str, force_pager: bool = False) -> None:
    """Print text with paging for long outputs."""
    if not PAGER_ENABLED and not force_pager:
        print(text)
        return

    lines = text.split('\n')
    _, term_height = get_terminal_size()
    page_size = min(PAGER_LINES, term_height - 6)  # Leave room for HUD

    if len(lines) <= page_size:
        print(text)
        return

    # Paged output
    for i in range(0, len(lines), page_size):
        chunk = lines[i:i + page_size]
        print('\n'.join(chunk))

        # Check if more lines remain
        remaining = len(lines) - (i + page_size)
        if remaining > 0:
            try:
                prompt = f"{Colors.DIM}--- {remaining} satır daha. Devam için Enter, atla için 'q' ---{Colors.RESET}"
                user_input = input(prompt).strip().lower()
                if user_input in {'q', 'quit', 'skip', 'atla'}:
                    print(f"{Colors.DIM}(atlandı){Colors.RESET}")
                    break
            except (EOFError, KeyboardInterrupt):
                print()
                break


def print_hud(status: dict) -> None:
    """Print sticky HUD with current state."""
    c = Colors
    mode = status.get("mode", "normal")
    browser = status.get("browser", "kapalı")
    queue = "aktif" if status.get("queue_active") else "-"
    pending = "⚠️ ONAY BEKLİYOR" if status.get("pending") else "-"

    # Truncate long URLs
    if len(browser) > 50:
        browser = browser[:47] + "..."

    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    print(f"{c.DIM}│{c.RESET} {c.CYAN}Mode:{c.RESET} {mode:<8} {c.CYAN}Queue:{c.RESET} {queue:<8} {c.CYAN}Pending:{c.RESET} {pending}")
    print(f"{c.DIM}│{c.RESET} {c.CYAN}Browser:{c.RESET} {browser}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")


def print_welcome() -> None:
    """Print welcome banner."""
    c = Colors
    print(f"""
{c.BOLD}{c.CYAN}╔══════════════════════════════════════════════════════════╗
║                    🎤 BANTZ v0.3                          ║
║            Local Voice Assistant for Linux                ║
╚══════════════════════════════════════════════════════════╝{c.RESET}

{c.DIM}Komutlar:{c.RESET}
  • {c.GREEN}instagram aç{c.RESET} → Browser'da aç
  • {c.GREEN}sayfayı tara{c.RESET} → Tıklanabilir öğeleri listele
  • {c.GREEN}12'ye tıkla{c.RESET}  → Index ile tıkla
  • {c.GREEN}geri dön{c.RESET}     → Önceki sayfa
  • {c.GREEN}daha fazla{c.RESET}   → Sonraki 10 öğe
    • {c.GREEN}agent: ...{c.RESET}    → Çok-adımlı agent planla ve çalıştır (örn: agent: YouTube'a git, Coldplay ara)
    • {c.GREEN}agent durum{c.RESET}   → Agent progress göster
    • {c.GREEN}agent geçmişi{c.RESET} → Son agent planı + adım durumları
    • {c.GREEN}son 3 agent{c.RESET}   → Son N agent task listesi
  • {c.GREEN}clear{c.RESET}        → Ekranı temizle
  • {c.GREEN}exit{c.RESET}         → Çık

{c.DIM}Çıkmak için: exit | quit | Ctrl+C{c.RESET}
""")


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("clear" if os.name != "nt" else "cls")


def run_interactive_with_server(session_name: str, policy_path: str, log_path: str) -> int:
    """Run interactive mode with integrated server (browser stays alive)."""
    from bantz.server import BantzServer, get_socket_path
    from bantz.core.events import get_event_bus, Event

    # Check if server already running
    socket_path = get_socket_path(session_name)
    if socket_path.exists():
        print(f"{Colors.YELLOW}⚠️  Session '{session_name}' zaten çalışıyor.{Colors.RESET}")
        print(f"   Bağlanmak için: bantz --session {session_name} --once \"komut\"")
        print(f"   Kapatmak için:  bantz --session {session_name} --stop")
        return 1

    server = BantzServer(session_name=session_name, policy_path=policy_path, log_path=log_path)

    # ─────────────────────────────────────────────────────────────
    # Setup event bus subscription for proactive messages
    # (CLI is just a consumer; source-of-truth is daemon inbox)
    # ─────────────────────────────────────────────────────────────
    proactive_queue: queue_module.Queue[Event] = queue_module.Queue()

    def on_bantz_message(event: Event) -> None:
        """Handle proactive Bantz messages."""
        if event.data.get("proactive"):
            proactive_queue.put(event)
    
    event_bus = get_event_bus()
    event_bus.subscribe("bantz_message", on_bantz_message)

    clear_screen()
    print_welcome()

    # Initial HUD
    print_hud({"mode": "normal", "browser": "kapalı", "queue_active": False, "pending": False})

    while True:
        # Check for proactive messages before blocking on input
        while not proactive_queue.empty():
            try:
                event = proactive_queue.get_nowait()
                msg_text = event.data.get("text", "")

                # Read unread count from daemon inbox (best-effort)
                unread = None
                try:
                    snap = server.handle_command("__inbox__")
                    if snap.get("ok"):
                        unread = int(snap.get("unread", 0))
                except Exception:
                    unread = None

                # Print without blocking prompt
                suffix = "" if unread is None else f" (okunmamış: {unread})"
                print(f"\n{Colors.MAGENTA}🔔 (Inbox +1){Colors.RESET} {msg_text}{Colors.DIM}{suffix}{Colors.RESET}")
                print(f"{Colors.GREEN}>{Colors.RESET} ", end="", flush=True)
            except queue_module.Empty:
                break
        
        try:
            text = input(f"{Colors.GREEN}>{Colors.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.DIM}👋 Hoşça kal!{Colors.RESET}")
            break

        if not text:
            continue

        # Local commands
        if text.lower() in {"exit", "quit", ":q", "çık", "kapat"}:
            break

        # Proactive inbox commands (daemon source-of-truth)
        if text.lower() == "inbox":
            snap = server.handle_command("__inbox__")
            if not snap.get("ok"):
                print(f"\n{Colors.RED}✗{Colors.RESET} Inbox okunamadı: {snap.get('text','')}\n")
                continue
            items = snap.get("inbox") or []
            if not items:
                print(f"\n{Colors.DIM}📥 Inbox boş.{Colors.RESET}\n")
                continue

            unread = int(snap.get("unread", 0))
            lines = [f"📥 Inbox ({unread} okunmamış):"]
            for item in items:
                status = "●" if not item.get("read") else "○"
                kind = (item.get("kind") or "").strip()
                kind_prefix = f"[{kind}] " if kind else ""
                lines.append(f"  [{item.get('id')}] {status} {kind_prefix}{item.get('text','')}")
            paged_print("\n" + "\n".join(lines) + "\n")
            continue

        if text.lower().startswith("okundu "):
            parts = text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                print(f"\n{Colors.RED}✗{Colors.RESET} Kullanım: okundu 17\n")
                continue
            target_id = int(parts[1])
            res = server.handle_command(f"__inbox_mark__ {target_id}")
            if res.get("ok"):
                print(f"\n{Colors.GREEN}✓{Colors.RESET} OK (okundu {target_id})\n")
            else:
                print(f"\n{Colors.RED}✗{Colors.RESET} {res.get('text','Bulunamadı')}\n")
            continue

        if text.lower() in {"inbox temizle", "inbox clear"}:
            res = server.handle_command("__inbox_clear__")
            if res.get("ok"):
                print(f"\n{Colors.GREEN}✓{Colors.RESET} Inbox temizlendi.\n")
            else:
                print(f"\n{Colors.RED}✗{Colors.RESET} {res.get('text','')}\n")
            continue

        if text.lower() in {"clear", "temizle", "cls"}:
            clear_screen()
            print_welcome()
            status = server.handle_command("__status__").get("status", {})
            print_hud(status)
            continue

        if text.lower() in {"help", "yardım", "?"}:
            print_welcome()
            continue

        # Toggle pager
        if text.lower() in {"pager", "pager on", "pager aç"}:
            global PAGER_ENABLED
            PAGER_ENABLED = True
            print(f"{Colors.GREEN}✓{Colors.RESET} Pager açıldı.")
            continue

        if text.lower() in {"pager off", "pager kapat"}:
            PAGER_ENABLED = False
            print(f"{Colors.GREEN}✓{Colors.RESET} Pager kapatıldı.")
            continue

        # Process command through server
        response = server.handle_command(text)

        # Print response with pager for long outputs
        response_text = response.get('text', '')
        if response.get("ok"):
            paged_print(f"\n{Colors.GREEN}✓{Colors.RESET} {response_text}\n")
        else:
            paged_print(f"\n{Colors.RED}✗{Colors.RESET} {response_text}\n")

        # Check for shutdown
        if response.get("shutdown"):
            break

        # Update HUD
        status = server.handle_command("__status__").get("status", {})
        print_hud(status)

    # Cleanup
    event_bus.unsubscribe("bantz_message", on_bantz_message)
    try:
        from bantz.browser.controller import get_controller

        ctrl = get_controller()
        ctrl.close()
    except ModuleNotFoundError:
        pass
    except Exception:
        pass

    return 0


def run_stateless_once(command: str, policy_path: str, log_path: str) -> int:
    """Run single command without persistent browser (original behavior)."""
    policy = Policy.from_json_file(policy_path)
    logger = JsonlLogger(path=log_path)
    router = Router(policy=policy, logger=logger)
    ctx = ConversationContext(timeout_seconds=120)

    result = router.handle(text=command, ctx=ctx)
    print(result.user_text)

    # Note about stateless mode
    from bantz.router.nlu import parse_intent
    parsed = parse_intent(command)
    if parsed.intent.startswith("browser_"):
        print(f"\n{Colors.DIM}💡 Not: --once modunda tarayıcı kalıcı değil.")
        print(f"   Kalıcı oturum için: bantz --serve{Colors.RESET}")

    return 0 if result.ok else 1


def run_session_command(session_name: str, command: str) -> int:
    """Send command to running session."""
    from bantz.server import send_to_server

    response = send_to_server(command, session_name)

    if response.get("not_running"):
        print(f"{Colors.RED}✗{Colors.RESET} {response.get('text', '')}")
        print(f"\n{Colors.DIM}Başlatmak için: bantz --serve --session {session_name}{Colors.RESET}")
        return 1

    if response.get("ok"):
        print(f"{Colors.GREEN}✓{Colors.RESET} {response.get('text', '')}")
    else:
        print(f"{Colors.RED}✗{Colors.RESET} {response.get('text', '')}")

    return 0 if response.get("ok") else 1


def stop_session(session_name: str) -> int:
    """Stop a running session."""
    from bantz.server import send_to_server, is_server_running

    if not is_server_running(session_name):
        print(f"{Colors.YELLOW}⚠️{Colors.RESET} Session '{session_name}' zaten çalışmıyor.")
        return 0

    response = send_to_server("__shutdown__", session_name)
    if response.get("shutdown") or response.get("ok"):
        print(f"{Colors.GREEN}✓{Colors.RESET} Session '{session_name}' kapatıldı.")
        return 0
    else:
        print(f"{Colors.RED}✗{Colors.RESET} Kapatılamadı: {response.get('text', '')}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bantz",
        description="Bantz v0.3 - Local voice assistant with live browser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Kullanım örnekleri:
  bantz                          # Interactive mod (tarayıcı kalıcı)
  bantz --serve                  # Interactive mod (aynı)
  bantz --session work --serve   # 'work' adlı oturum başlat
  bantz --session work --once "instagram aç"  # Çalışan oturuma komut gönder
  bantz --session work --stop    # Oturumu kapat
  bantz --once "google aç"       # Tek seferlik (tarayıcı kalıcı değil)
""",
    )
    parser.add_argument("--policy", default="config/policy.json", help="Policy dosyası yolu")
    parser.add_argument("--log", default="bantz.log.jsonl", help="JSONL log dosyası")
    parser.add_argument("--session", default="default", help="Session adı (default: 'default')")
    parser.add_argument("--serve", action="store_true", help="Interactive server modu başlat")
    parser.add_argument("--once", default=None, metavar="CMD", help="Tek seferlik komut")
    parser.add_argument("--stop", action="store_true", help="Çalışan session'ı kapat")

    # Voice mode (PTT)
    parser.add_argument("--voice", action="store_true", help="Sesli mod (PTT: SPACE basılı tut)")
    parser.add_argument("--wake", action="store_true", help="Wake word modu ('Hey Jarvis' ile aktive)")
    parser.add_argument("--voice-warmup", action="store_true", help="ASR modelini önceden hazırla/indir (voice başlamaz)")
    parser.add_argument("--piper-model", default="", help="Piper .onnx model yolu (zorunlu: --voice)")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama base URL")
    parser.add_argument("--ollama-model", default="qwen2.5:3b-instruct", help="Ollama model adı")
    parser.add_argument("--whisper-model", default="base", help="faster-whisper model adı (tiny/base/small/...)")
    parser.add_argument("--asr-cache-dir", default=os.path.expanduser("~/.cache/bantz/whisper"), help="Whisper model cache klasörü")
    parser.add_argument("--asr-allow-download", action="store_true", help="Whisper model indirmeye izin ver (ilk kurulumda)")
    parser.add_argument("--no-tts", action="store_true", help="Sesli yanıtı kapat (Piper olmadan test için)")
    parser.add_argument("--no-llm", action="store_true", help="LLM fallback kapat (sadece daemon yanıtı)")
    parser.add_argument("--enter-ptt", action="store_true", help="SPACE yerine Enter tabanlı kayıt modu (Wayland için)"
    )

    args = parser.parse_args(argv)

    def _can_connect(host: str, port: int, timeout_s: float = 3.0) -> bool:
        try:
            sock = socket.create_connection((host, port), timeout=timeout_s)
        except OSError:
            return False
        else:
            try:
                sock.close()
            except Exception:
                pass
            return True

    # Voice mode runs as a client: ASR -> daemon -> TTS
    # Warmup is also handled here (no daemon needed).
    if args.voice or args.wake or args.voice_warmup:
        from bantz.voice.loop import VoiceLoopConfig, run_voice_loop, run_wake_word_loop
        from bantz.voice.asr import ASR, ASRConfig

        # Warmup mode: prepare the ASR model (download if allowed), then exit.
        if args.voice_warmup:
            cfg = ASRConfig(
                whisper_model=args.whisper_model,
                language=None,
                cache_dir=args.asr_cache_dir,
                allow_download=bool(args.asr_allow_download),
            )
            try:
                if cfg.allow_download:
                    # Avoid hanging on offline/blocked networks.
                    if not _can_connect("huggingface.co", 443, timeout_s=3.0):
                        print(
                            "❌ HuggingFace'e erişemiyorum (443). İnternet kapalı/engelli olabilir. "
                            "Offline için önce modeli başka yerden indirip cache'e koymalısın."
                        )
                        return 1
                    print("⏳ Whisper model indiriliyor/ hazırlanıyor... (ilk sefer uzun sürebilir)")
                _ = ASR(cfg)
            except KeyboardInterrupt:
                print("\n⚠️ Warmup iptal edildi.")
                return 130
            except Exception as e:
                print(f"❌ Warmup başarısız: {e}")
                return 1
            print("✅ Warmup tamam. Artık voice modunda indirmeye takılmaz.")
            return 0

        if not args.voice and not args.wake:
            print("❌ Voice modu için --voice veya --wake gerekli. (Sadece warmup için: --voice-warmup)")
            return 1

        # Wake word mode
        if args.wake:
            cfg = VoiceLoopConfig(
                session=args.session,
                piper_model_path=args.piper_model,
                ollama_url=args.ollama_url,
                ollama_model=args.ollama_model,
                whisper_model=args.whisper_model,
                enable_tts=not args.no_tts,
                enable_llm_fallback=not args.no_llm,
            )
            
            # Pass ASR stability settings via env vars
            os.environ["BANTZ_ASR_CACHE_DIR"] = args.asr_cache_dir
            os.environ["BANTZ_ASR_ALLOW_DOWNLOAD"] = "1" if args.asr_allow_download else "0"
            
            return run_wake_word_loop(cfg)

        # PTT Voice mode (original)
        # Wayland default: prefer Enter PTT for stability unless user explicitly chose.
        force_enter = bool(args.enter_ptt)
        if not force_enter and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            force_enter = True
            print("ℹ️ Wayland algılandı: daha stabil olduğu için Enter-PTT seçildi (--enter-ptt).")

        cfg = VoiceLoopConfig(
            session=args.session,
            piper_model_path=args.piper_model,
            ollama_url=args.ollama_url,
            ollama_model=args.ollama_model,
            whisper_model=args.whisper_model,
            enable_tts=not args.no_tts,
            enable_llm_fallback=not args.no_llm,
            force_enter_ptt=force_enter,
        )

        # Pass ASR stability settings via env vars consumed by ASRConfig defaults.
        os.environ["BANTZ_ASR_CACHE_DIR"] = args.asr_cache_dir
        os.environ["BANTZ_ASR_ALLOW_DOWNLOAD"] = "1" if args.asr_allow_download else "0"
        return run_voice_loop(cfg)

    # Stop session
    if args.stop:
        return stop_session(args.session)

    # --once: if a session server is running, prefer sending to it.
    # Otherwise, fall back to stateless once mode.
    if args.once and not args.serve:
        try:
            from bantz.server import is_server_running

            if is_server_running(args.session):
                return run_session_command(args.session, args.once)
        except Exception:
            pass
        return run_stateless_once(args.once, args.policy, args.log)

    # Interactive mode (default or --serve)
    return run_interactive_with_server(args.session, args.policy, args.log)


if __name__ == "__main__":
    raise SystemExit(main())
