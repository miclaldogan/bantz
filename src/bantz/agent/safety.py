"""Safety guardrails — dangerous command detection and blocking.

Issue #1295: PC Agent + CodingAgent — Safety Guardrails.

Pattern-based command safety checker:
- BLOCKED patterns → immediately denied
- DRY_RUN_REQUIRED patterns → must run dry-run first
- Safe commands → allowed directly
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SafetyAction(str, enum.Enum):
    """Safety decision actions."""

    ALLOW = "allow"
    BLOCK = "block"
    DRY_RUN_FIRST = "dry_run_first"
    CONFIRM = "confirm"


@dataclass
class SafetyDecision:
    """Result of a safety check on a command."""

    action: SafetyAction
    reason: str = ""
    matched_pattern: str = ""

    @property
    def allowed(self) -> bool:
        return self.action in (SafetyAction.ALLOW, SafetyAction.DRY_RUN_FIRST)

    @property
    def blocked(self) -> bool:
        return self.action == SafetyAction.BLOCK


# ── Pattern definitions ─────────────────────────────────────────────

BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/\s*$", "Root dizin silme: rm -rf /"),
    (r"rm\s+-rf\s+/\*", "Root altı silme: rm -rf /*"),
    (r"rm\s+-rf\s+~\s*$", "Ev dizini silme: rm -rf ~"),
    (r"rm\s+-rf\s+\$HOME", "Ev dizini silme: rm -rf $HOME"),
    (r"dd\s+if=.*of=/dev/", "Disk üzerine yazma: dd"),
    (r"mkfs\.", "Dosya sistemi biçimlendirme: mkfs"),
    (r"chmod\s+(-R\s+)?777\s+/\s*$", "Root dizin izin değişikliği"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", "Fork bomb"),
    (r"curl.*\|\s*(?:ba)?sh", "Uzaktan kod çalıştırma: curl | sh"),
    (r"wget.*\|\s*(?:ba)?sh", "Uzaktan kod çalıştırma: wget | sh"),
    (r">\s*/dev/sd[a-z]", "Disk cihazına yazma"),
    (r"shutdown|reboot|poweroff|halt", "Sistem kapatma/yeniden başlatma"),
    (r"sudo\s+rm\s+-rf", "sudo ile toplu silme"),
    (r"nsenter\s+", "Namespace girişi: nsenter"),
    (r"pkexec\s+", "Ayrıcalık yükseltme: pkexec"),
]

DRY_RUN_REQUIRED_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+(-[rfi]+\s+)?", "Dosya silme — önce simülasyon"),
    (r"mv\s+", "Dosya taşıma — önce simülasyon"),
    (r"cp\s+-r", "Özyinelemeli kopyalama — önce simülasyon"),
    (r"git\s+push\s+.*--force", "Force push — dikkat"),
    (r"git\s+reset\s+--hard", "Hard reset — dikkat"),
    (r"find\s+.*-delete", "Toplu dosya silme — önce simülasyon"),
    (r"chmod\s+-R", "Özyinelemeli izin değişikliği"),
    (r"chown\s+-R", "Özyinelemeli sahiplik değişikliği"),
]

CONFIRM_REQUIRED_PATTERNS: list[tuple[str, str]] = [
    (r"sudo\s+", "sudo komutu — onay gerekli"),
    (r"apt\s+(install|remove|purge)", "Paket yönetimi — onay gerekli"),
    (r"pip\s+install", "Python paket kurulumu — onay gerekli"),
    (r"npm\s+install\s+-g", "Global npm kurulumu — onay gerekli"),
    (r"kill\s+(-9\s+)?", "Süreç sonlandırma — onay gerekli"),
    (r"systemctl\s+(start|stop|restart|enable|disable)", "Servis yönetimi — onay gerekli"),
]


class SafetyGuardrails:
    """Command safety checker with pattern-based threat detection.

    Three tiers:
    1. **BLOCKED** — absolute deny, never execute
    2. **DRY_RUN_FIRST** — must simulate before real execution
    3. **CONFIRM** — require user confirmation
    4. **ALLOW** — safe to execute directly
    """

    def __init__(
        self,
        *,
        extra_blocked: list[tuple[str, str]] | None = None,
        extra_dry_run: list[tuple[str, str]] | None = None,
        extra_confirm: list[tuple[str, str]] | None = None,
    ) -> None:
        self._blocked = list(BLOCKED_PATTERNS)
        self._dry_run = list(DRY_RUN_REQUIRED_PATTERNS)
        self._confirm = list(CONFIRM_REQUIRED_PATTERNS)

        if extra_blocked:
            self._blocked.extend(extra_blocked)
        if extra_dry_run:
            self._dry_run.extend(extra_dry_run)
        if extra_confirm:
            self._confirm.extend(extra_confirm)

    def check(self, command: str) -> SafetyDecision:
        """Evaluate a command against safety patterns.

        Returns:
            A :class:`SafetyDecision` indicating the action to take.
        """
        stripped = command.strip()

        # 1) Check BLOCKED
        for pattern, reason in self._blocked:
            if re.search(pattern, stripped, re.IGNORECASE):
                logger.warning(
                    "[Safety] BLOCKED command: %s (pattern: %s)",
                    stripped[:80],
                    pattern,
                )
                return SafetyDecision(
                    action=SafetyAction.BLOCK,
                    reason=f"Tehlikeli komut engellendi: {reason}",
                    matched_pattern=pattern,
                )

        # 2) Check DRY_RUN_REQUIRED
        for pattern, reason in self._dry_run:
            if re.search(pattern, stripped, re.IGNORECASE):
                return SafetyDecision(
                    action=SafetyAction.DRY_RUN_FIRST,
                    reason=reason,
                    matched_pattern=pattern,
                )

        # 3) Check CONFIRM_REQUIRED
        for pattern, reason in self._confirm:
            if re.search(pattern, stripped, re.IGNORECASE):
                return SafetyDecision(
                    action=SafetyAction.CONFIRM,
                    reason=reason,
                    matched_pattern=pattern,
                )

        # 4) Allow
        return SafetyDecision(action=SafetyAction.ALLOW)

    def is_safe(self, command: str) -> bool:
        """Quick check — True if the command is immediately safe."""
        return self.check(command).action == SafetyAction.ALLOW

    def explain(self, command: str) -> str:
        """Return a human-readable safety explanation (Turkish)."""
        decision = self.check(command)
        if decision.action == SafetyAction.ALLOW:
            return "✅ Güvenli — doğrudan çalıştırılabilir."
        if decision.action == SafetyAction.BLOCK:
            return f"🚫 ENGELLENDİ — {decision.reason}"
        if decision.action == SafetyAction.DRY_RUN_FIRST:
            return f"⚠️ Önce simülasyon gerekli — {decision.reason}"
        return f"⚠️ Onay gerekli — {decision.reason}"
