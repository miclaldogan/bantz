"""Google Service Consent Wizard — Guided OAuth permission flow (Issue #1260).

First-run experience: asks user which Google services to connect,
explains requested scopes in plain Turkish, and triggers OAuth consent
for each service individually.

Design:
- Each service is a ``ServiceDefinition`` with scopes, icon, description.
- Registry is extensible (WhatsApp, Classroom, Drive can be added later).
- Status tracking via ``~/.config/bantz/google/services.json``.
- ``bantz connect`` CLI command.
- Integration with onboard.py for first-run.

Usage:
    from bantz.google.consent_wizard import ConsentWizard
    wizard = ConsentWizard()
    wizard.run_interactive()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ConsentWizard",
    "ServiceDefinition",
    "ServiceStatus",
    "get_service_registry",
    "get_service_status",
]


# ═══════════════════════════════════════════════════════════════════
# ANSI colors
# ═══════════════════════════════════════════════════════════════════

class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    WHITE = "\033[37m"


# ═══════════════════════════════════════════════════════════════════
# Service Definitions
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ServiceDefinition:
    """A Google service that Bantz can connect to."""

    id: str                    # e.g. "gmail", "calendar", "contacts"
    name: str                  # Human-readable: "Gmail"
    icon: str                  # Emoji icon
    description_tr: str        # Turkish description of what we'll do
    scopes: list[str]          # OAuth2 scopes to request
    permissions_tr: list[str]  # Turkish explanation of each permission
    token_path_key: str        # Env var or default path key
    default_token_path: str    # Default token file path
    auth_module: str           # Module.function to call for auth
    optional: bool = True      # Can skip?
    requires: list[str] = field(default_factory=list)  # Dependencies


# ── Service Registry ────────────────────────────────────────────

_SERVICE_REGISTRY: list[ServiceDefinition] = [
    ServiceDefinition(
        id="calendar",
        name="Google Calendar",
        icon="📅",
        description_tr="Takvim etkinliklerini okuma, oluşturma ve düzenleme",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
        permissions_tr=[
            "Takvim etkinliklerinizi okuma",
            "Yeni etkinlik oluşturma",
            "Etkinlik güncelleme ve silme",
        ],
        token_path_key="BANTZ_GOOGLE_TOKEN_PATH",
        default_token_path="~/.config/bantz/google/token.json",
        auth_module="bantz.google.auth",
    ),
    ServiceDefinition(
        id="gmail",
        name="Gmail",
        icon="📧",
        description_tr="E-postaları okuma, arama ve gönderme",
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
        permissions_tr=[
            "E-postalarınızı okuma ve arama",
            "E-posta gönderme",
            "Taslak oluşturma ve düzenleme",
            "Etiket yönetimi (yıldız, arşiv vb.)",
        ],
        token_path_key="BANTZ_GMAIL_TOKEN_PATH",
        default_token_path="~/.config/bantz/google/gmail_token.json",
        auth_module="bantz.google.gmail_auth",
    ),
    ServiceDefinition(
        id="contacts",
        name="Google Contacts",
        icon="👤",
        description_tr="Kişi arama (isimden e-posta bulma)",
        scopes=[
            "https://www.googleapis.com/auth/contacts.readonly",
        ],
        permissions_tr=[
            "Rehberinizdeki kişileri arama",
            "İsimden e-posta adresi çözümleme",
        ],
        token_path_key="BANTZ_GOOGLE_TOKEN_PATH",
        default_token_path="~/.config/bantz/google/token.json",
        auth_module="bantz.google.auth",
    ),
    # ── Issue #1292: New Google Suite connectors ──────────────
    ServiceDefinition(
        id="tasks",
        name="Google Tasks",
        icon="✅",
        description_tr="Görev oluşturma, listeleme ve tamamlama",
        scopes=[
            "https://www.googleapis.com/auth/tasks",
        ],
        permissions_tr=[
            "Görevlerinizi okuma ve listeleme",
            "Yeni görev oluşturma",
            "Görev tamamlama ve silme",
        ],
        token_path_key="BANTZ_GOOGLE_UNIFIED_TOKEN_PATH",
        default_token_path="~/.config/bantz/google/google_unified_token.json",
        auth_module="bantz.google.auth_manager",
    ),
    ServiceDefinition(
        id="classroom",
        name="Google Classroom",
        icon="🎓",
        description_tr="Ders, ödev ve teslim durumu takibi",
        scopes=[
            "https://www.googleapis.com/auth/classroom.courses.readonly",
            "https://www.googleapis.com/auth/classroom.coursework.me",
        ],
        permissions_tr=[
            "Derslerinizi görüntüleme",
            "Ödev listesini okuma",
            "Teslim durumlarınızı kontrol etme",
        ],
        token_path_key="BANTZ_GOOGLE_UNIFIED_TOKEN_PATH",
        default_token_path="~/.config/bantz/google/google_unified_token.json",
        auth_module="bantz.google.auth_manager",
        optional=True,
    ),
]

# Future services (shown as "coming soon")
_FUTURE_SERVICES: list[dict[str, str]] = [
    {"id": "keep", "name": "Google Keep", "icon": "📝", "desc": "Not oluşturma ve arama (Workspace hesabı gerekir)"},
    {"id": "drive", "name": "Google Drive", "icon": "📁", "desc": "Dosya arama ve paylaşım"},
    {"id": "whatsapp", "name": "WhatsApp", "icon": "💬", "desc": "Mesaj gönderme ve okuma"},
    {"id": "youtube", "name": "YouTube", "icon": "🎬", "desc": "Video arama ve özetleme"},
]


def get_service_registry() -> list[ServiceDefinition]:
    """Return the current service registry."""
    return list(_SERVICE_REGISTRY)


# ═══════════════════════════════════════════════════════════════════
# Service Status Tracking
# ═══════════════════════════════════════════════════════════════════

_STATUS_FILE = "~/.config/bantz/google/services.json"


@dataclass
class ServiceStatus:
    """Tracks connection status for each service."""

    service_id: str
    connected: bool = False
    connected_at: Optional[str] = None
    scopes_granted: list[str] = field(default_factory=list)
    skipped: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "connected": self.connected,
            "connected_at": self.connected_at,
            "scopes_granted": self.scopes_granted,
            "skipped": self.skipped,
            "error": self.error,
        }


def _status_path() -> Path:
    return Path(os.path.expanduser(_STATUS_FILE)).resolve()


def get_service_status() -> dict[str, ServiceStatus]:
    """Load service status from disk."""
    p = _status_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, ServiceStatus] = {}
        for sid, info in data.items():
            if not isinstance(info, dict):
                continue
            out[sid] = ServiceStatus(
                service_id=sid,
                connected=bool(info.get("connected")),
                connected_at=info.get("connected_at"),
                scopes_granted=info.get("scopes_granted", []),
                skipped=bool(info.get("skipped")),
                error=info.get("error"),
            )
        return out
    except Exception as exc:
        logger.warning("Failed to read services.json: %s", exc)
        return {}


def _save_service_status(statuses: dict[str, ServiceStatus]) -> None:
    """Persist service status to disk."""
    p = _status_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {sid: s.to_dict() for sid, s in statuses.items()}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def is_service_connected(service_id: str) -> bool:
    """Check if a specific service is connected."""
    statuses = get_service_status()
    s = statuses.get(service_id)
    return bool(s and s.connected)


# ═══════════════════════════════════════════════════════════════════
# Consent Wizard
# ═══════════════════════════════════════════════════════════════════

class ConsentWizard:
    """Interactive OAuth consent wizard for Google services.

    Guides user through connecting services one-by-one with clear
    Turkish explanations of what permissions are requested.
    """

    def __init__(self, *, non_interactive: bool = False):
        self.non_interactive = non_interactive
        self._statuses = get_service_status()
        self._detect_existing_tokens()

    def _detect_existing_tokens(self) -> None:
        """Auto-detect already connected services from existing token files."""
        for svc in _SERVICE_REGISTRY:
            if svc.id in self._statuses and self._statuses[svc.id].connected:
                continue  # Already known

            token_path_str = os.getenv(svc.token_path_key) or svc.default_token_path
            token_path = Path(os.path.expanduser(token_path_str)).resolve()
            if not token_path.exists():
                continue

            try:
                data = json.loads(token_path.read_text(encoding="utf-8"))
                if data.get("refresh_token"):
                    granted = data.get("scopes") or data.get("scope") or []
                    if isinstance(granted, str):
                        granted = granted.split()
                    self._statuses[svc.id] = ServiceStatus(
                        service_id=svc.id,
                        connected=True,
                        connected_at=data.get("_connected_at", "önceden"),
                        scopes_granted=granted,
                    )
            except Exception:
                continue

        _save_service_status(self._statuses)

    def _ask(self, prompt: str, default: str = "e", choices: Optional[list[str]] = None) -> str:
        """Ask user for input."""
        if self.non_interactive:
            return default
        opts = "/".join(choices) if choices else "e/h"
        try:
            answer = input(f"{prompt} [{opts}] ({default}): ").strip().lower()
            if not answer:
                return default
            return answer
        except (EOFError, KeyboardInterrupt):
            print()
            return "h"

    def _check_client_secret(self) -> bool:
        """Verify client_secret.json exists."""
        from bantz.google.auth import get_google_auth_config

        cfg = get_google_auth_config()
        if cfg.client_secret_path.exists():
            return True

        print(f"\n{_C.RED}  ✗ Google OAuth client_secret.json bulunamadı.{_C.RESET}")
        print(f"  {_C.DIM}Beklenen konum: {cfg.client_secret_path}{_C.RESET}")
        print()
        print(f"  {_C.YELLOW}Nasıl alınır:{_C.RESET}")
        print(f"  1. {_C.CYAN}https://console.cloud.google.com/apis/credentials{_C.RESET} adresine gidin")
        print(f"  2. OAuth 2.0 Client ID oluşturun (Desktop Application)")
        print(f"  3. JSON'u indirin ve şu konuma koyun:")
        print(f"     {_C.GREEN}{cfg.client_secret_path}{_C.RESET}")
        print()
        return False

    def _print_banner(self) -> None:
        """Print welcome banner."""
        print(f"""
{_C.BOLD}{_C.CYAN}╔══════════════════════════════════════════════════════════╗
║           🚀 Bantz Servis Bağlantı Sihirbazı            ║
╚══════════════════════════════════════════════════════════╝{_C.RESET}

{_C.DIM}Bantz'ın Google servislerinize erişebilmesi için izin
isteyeceğiz. Her servis ayrı ayrı bağlanır ve istediğiniz
zaman iptal edebilirsiniz.{_C.RESET}
""")

    def _print_service_card(self, svc: ServiceDefinition, status: Optional[ServiceStatus]) -> None:
        """Print a service info card."""
        connected = status and status.connected
        marker = f"{_C.GREEN}✓ Bağlı{_C.RESET}" if connected else f"{_C.DIM}○ Bağlı değil{_C.RESET}"

        print(f"\n  {svc.icon} {_C.BOLD}{svc.name}{_C.RESET}  {marker}")
        print(f"  {_C.DIM}→ {svc.description_tr}{_C.RESET}")
        print(f"  {_C.DIM}İstenen izinler:{_C.RESET}")
        for perm in svc.permissions_tr:
            print(f"    {_C.CYAN}•{_C.RESET} {perm}")

    def _connect_service(self, svc: ServiceDefinition) -> bool:
        """Attempt to connect a single service via OAuth."""
        try:
            if svc.id == "gmail":
                from bantz.google.gmail_auth import authenticate_gmail
                authenticate_gmail(scopes=svc.scopes, interactive=True)
            else:
                from bantz.google.auth import get_credentials
                get_credentials(scopes=svc.scopes, interactive=True)

            self._statuses[svc.id] = ServiceStatus(
                service_id=svc.id,
                connected=True,
                connected_at=datetime.now().isoformat(),
                scopes_granted=svc.scopes,
            )
            _save_service_status(self._statuses)
            print(f"  {_C.GREEN}✓ {svc.name} başarıyla bağlandı!{_C.RESET}")
            return True

        except FileNotFoundError as e:
            print(f"  {_C.RED}✗ client_secret.json bulunamadı: {e}{_C.RESET}")
            self._statuses[svc.id] = ServiceStatus(
                service_id=svc.id, error=str(e),
            )
            _save_service_status(self._statuses)
            return False
        except Exception as e:
            print(f"  {_C.RED}✗ Bağlantı başarısız: {e}{_C.RESET}")
            self._statuses[svc.id] = ServiceStatus(
                service_id=svc.id, error=str(e),
            )
            _save_service_status(self._statuses)
            return False

    def _disconnect_service(self, svc: ServiceDefinition) -> bool:
        """Disconnect (revoke) a service by deleting its token."""
        try:
            token_path_str = os.getenv(svc.token_path_key) or svc.default_token_path
            token_path = Path(os.path.expanduser(token_path_str)).resolve()
            if token_path.exists():
                token_path.unlink()
                print(f"  {_C.YELLOW}Token silindi: {token_path}{_C.RESET}")

            self._statuses[svc.id] = ServiceStatus(service_id=svc.id)
            _save_service_status(self._statuses)
            print(f"  {_C.GREEN}✓ {svc.name} bağlantısı kaldırıldı.{_C.RESET}")
            return True
        except Exception as e:
            print(f"  {_C.RED}✗ Bağlantı kaldırma başarısız: {e}{_C.RESET}")
            return False

    def run_interactive(self) -> int:
        """Run the full interactive consent wizard.

        Returns:
            0 on success, 1 on failure/cancel.
        """
        self._print_banner()

        if not self._check_client_secret():
            return 1

        connected_count = 0
        skipped_count = 0

        for svc in _SERVICE_REGISTRY:
            status = self._statuses.get(svc.id)
            self._print_service_card(svc, status)

            if status and status.connected:
                print(f"  {_C.GREEN}(Zaten bağlı — atlanıyor){_C.RESET}")
                connected_count += 1
                continue

            if svc.optional:
                choice = self._ask(
                    f"  {svc.name} bağlansın mı?",
                    default="e",
                    choices=["e", "h"],
                )
                if choice not in ("e", "evet", "y", "yes"):
                    print(f"  {_C.DIM}→ Şimdilik atlandı. Sonra 'bantz connect {svc.id}' ile bağlayabilirsiniz.{_C.RESET}")
                    self._statuses[svc.id] = ServiceStatus(
                        service_id=svc.id, skipped=True,
                    )
                    _save_service_status(self._statuses)
                    skipped_count += 1
                    continue

            print(f"\n  {_C.CYAN}OAuth sayfası açılıyor...{_C.RESET}")
            if self._connect_service(svc):
                connected_count += 1
            print()

        # Show future services
        if _FUTURE_SERVICES:
            print(f"\n{_C.DIM}{'─' * 58}{_C.RESET}")
            print(f"  {_C.BOLD}Yakında gelecek servisler:{_C.RESET}")
            for fs in _FUTURE_SERVICES:
                print(f"    {fs['icon']} {_C.DIM}{fs['name']} — {fs['desc']}{_C.RESET}")
            print()

        # Summary
        total = len(_SERVICE_REGISTRY)
        print(f"\n{_C.BOLD}{'─' * 58}{_C.RESET}")
        print(f"  {_C.GREEN}✓ {connected_count}/{total} servis bağlandı{_C.RESET}", end="")
        if skipped_count:
            print(f"  {_C.DIM}({skipped_count} atlandı){_C.RESET}")
        else:
            print()

        if connected_count > 0:
            print(f"\n  {_C.CYAN}Sonraki adım:{_C.RESET} python3 -m bantz")
        elif skipped_count == total:
            print(f"\n  {_C.YELLOW}Tüm servisler atlandı.{_C.RESET}")
            print(f"  Sonra bağlamak için: {_C.GREEN}bantz connect gmail{_C.RESET}")

        print()
        return 0

    def connect_single(self, service_id: str) -> int:
        """Connect a single service by ID.

        Usage: ``bantz connect gmail``
        """
        svc = None
        for s in _SERVICE_REGISTRY:
            if s.id == service_id:
                svc = s
                break

        if svc is None:
            print(f"{_C.RED}✗ Bilinmeyen servis: '{service_id}'{_C.RESET}")
            print(f"  Mevcut servisler: {', '.join(s.id for s in _SERVICE_REGISTRY)}")
            return 1

        if not self._check_client_secret():
            return 1

        status = self._statuses.get(svc.id)
        self._print_service_card(svc, status)

        if status and status.connected:
            reconnect = self._ask("  Zaten bağlı. Tekrar bağlanmak ister misiniz?", "h", ["e", "h"])
            if reconnect not in ("e", "evet"):
                return 0

        print(f"\n  {_C.CYAN}OAuth sayfası açılıyor...{_C.RESET}")
        if self._connect_service(svc):
            return 0
        return 1

    def disconnect_single(self, service_id: str) -> int:
        """Disconnect (revoke) a single service.

        Usage: ``bantz revoke gmail``
        """
        svc = None
        for s in _SERVICE_REGISTRY:
            if s.id == service_id:
                svc = s
                break

        if svc is None:
            print(f"{_C.RED}✗ Bilinmeyen servis: '{service_id}'{_C.RESET}")
            return 1

        return 0 if self._disconnect_service(svc) else 1

    def show_status(self) -> int:
        """Show current connection status for all services.

        Usage: ``bantz permissions``
        """
        print(f"\n{_C.BOLD}  Bantz Servis Durumu{_C.RESET}")
        print(f"  {'─' * 50}")

        for svc in _SERVICE_REGISTRY:
            status = self._statuses.get(svc.id)
            if status and status.connected:
                when = status.connected_at or "?"
                print(f"  {svc.icon} {_C.GREEN}✓{_C.RESET} {svc.name:<20} {_C.DIM}bağlandı: {when}{_C.RESET}")
            elif status and status.skipped:
                print(f"  {svc.icon} {_C.YELLOW}○{_C.RESET} {svc.name:<20} {_C.DIM}atlandı{_C.RESET}")
            elif status and status.error:
                print(f"  {svc.icon} {_C.RED}✗{_C.RESET} {svc.name:<20} {_C.DIM}hata: {status.error[:40]}{_C.RESET}")
            else:
                print(f"  {svc.icon} {_C.DIM}–{_C.RESET} {svc.name:<20} {_C.DIM}henüz bağlanmadı{_C.RESET}")

        print(f"\n  {_C.DIM}Bağlamak: bantz connect <servis>{_C.RESET}")
        print(f"  {_C.DIM}Kaldırmak: bantz revoke <servis>{_C.RESET}")
        print()
        return 0


# ═══════════════════════════════════════════════════════════════════
# First-run detection
# ═══════════════════════════════════════════════════════════════════

def should_show_wizard() -> bool:
    """Check if the consent wizard should be shown on startup.

    Returns True if:
    - No services.json exists (first run)
    - OR no services are connected
    """
    p = _status_path()
    if not p.exists():
        return True

    statuses = get_service_status()
    if not statuses:
        return True

    # If all services are either skipped or not configured, show wizard
    connected = sum(1 for s in statuses.values() if s.connected)
    return connected == 0


def run_first_time_wizard_if_needed() -> None:
    """Called at startup — shows wizard if first run.

    Non-blocking: if user is in --once mode, skip.
    """
    if not should_show_wizard():
        return

    # Check if client_secret exists at all
    try:
        from bantz.google.auth import get_google_auth_config
        cfg = get_google_auth_config()
        if not cfg.client_secret_path.exists():
            # No client secret — can't run wizard, skip silently
            return
    except Exception:
        return

    wizard = ConsentWizard()
    wizard.run_interactive()
