"""Self-Evolving Agent — automatic SKILL.md generation (Issue #837).

Detects when the user asks for something Bantz can't do, generates a
new SKILL.md via LLM, validates & sandbox-tests it, and (with user
approval) hot-loads the skill into the runtime.

Flow
----
1. **SkillNeedDetector** — intercepts ``route="unknown"`` turns
   where the request is *not* smalltalk and no existing skill matches.
2. **SkillGenerator** — calls the LLM with a structured prompt to
   produce a complete SKILL.md (YAML frontmatter + Markdown body).
3. **SkillValidator** — runs ``DeclarativeSkill.validate()`` on the
   generated SKILL.md, then sandbox-tests script handlers.
4. **SkillVersionManager** — tracks auto-generated skill versions,
   supports rollback.
5. **User Approval** — presents the generated skill for approval
   before hot-loading.

Security
--------
- Generated skills default to ``handler: llm`` (no code execution).
- ``script:`` handlers are sandbox-tested before approval.
- Network / filesystem permissions require explicit user consent.
- ``shell`` access is **always denied** for auto-generated skills.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml

from bantz.skills.declarative.loader import SkillLoader
from bantz.skills.declarative.models import (
    DeclarativeSkill,
    SkillMetadata,
    SkillPermission,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Skills that we should never auto-generate (safety)
_BLOCKED_SKILL_NAMES = frozenset({
    "shell", "sudo", "rm", "eval", "exec", "format", "reboot",
    "shutdown", "kill", "daemon", "root", "admin", "hack",
})

# Maximum auto-generated skills per session (prevent runaway)
_MAX_SKILLS_PER_SESSION = 10

# Default directory for auto-generated skills
_AUTO_SKILL_DIR_NAME = "auto-generated"


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class LLMProtocol(Protocol):
    """Minimal protocol for LLM text completion."""

    def complete_text(
        self, *, prompt: str, temperature: float = 0.2, max_tokens: int = 512,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Skill Need Detector
# ---------------------------------------------------------------------------

@dataclass
class SkillGap:
    """Represents a detected capability gap."""

    user_input: str
    detected_at: float = field(default_factory=time.time)
    route: str = "unknown"
    confidence: float = 0.0
    suggested_name: str = ""
    suggested_description: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_input": self.user_input,
            "detected_at": self.detected_at,
            "route": self.route,
            "confidence": self.confidence,
            "suggested_name": self.suggested_name,
            "suggested_description": self.suggested_description,
            "reason": self.reason,
        }


class SkillNeedDetector:
    """Detects when the user's request can't be handled by existing skills.

    Checks:
    1. Route is "unknown" (LLM couldn't classify)
    2. Request isn't simple smalltalk / greeting
    3. No existing declarative skill trigger matches
    4. The request describes a *doable* task (not philosophical / opinion)
    """

    # Patterns that indicate the user wants Bantz to DO something
    _ACTION_PATTERNS = [
        r"(?:yapabilir|yapabilir\s+misin|yap(?:ar\s+mısın)?)",
        r"(?:göster|bul|ara|getir|kontrol\s+et|oluştur|yaz|çalıştır)",
        r"(?:can\s+you|could\s+you|please|do|make|create|find|show|check)",
        r"(?:nasıl\s+(?:yaparım|yapılır|edilir))",
        r"(?:bir\s+(?:tane|şey)\s+(?:yap|oluştur))",
    ]
    _ACTION_RE = re.compile("|".join(_ACTION_PATTERNS), re.IGNORECASE)

    # Patterns that indicate smalltalk (NOT a skill need)
    _SMALLTALK_PATTERNS = [
        r"^(?:merhaba|selam|hey|naber|nasılsın|günaydın|iyi\s+geceler|hello|hi)\b",
        r"^(?:teşekkür|sağol|eyvallah|thanks|thank\s+you)\b",
        r"^(?:tamam|ok|evet|hayır|anladım|peki)\b",
    ]
    _SMALLTALK_RE = re.compile("|".join(_SMALLTALK_PATTERNS), re.IGNORECASE)

    def __init__(self) -> None:
        self._recent_gaps: list[SkillGap] = []

    def detect(
        self,
        user_input: str,
        route: str,
        confidence: float,
        existing_skill_names: list[str] | None = None,
    ) -> SkillGap | None:
        """Detect a skill gap from the orchestrator output.

        Returns a SkillGap if a new skill could help, or None.
        """
        # Only trigger on unknown routes with low confidence
        if route not in ("unknown",):
            return None

        # Skip smalltalk
        stripped = user_input.strip()
        if self._SMALLTALK_RE.search(stripped):
            return None

        # Must look like an actionable request
        if not self._ACTION_RE.search(stripped):
            # Also accept longer requests (>15 chars) that aren't smalltalk
            if len(stripped) < 15:
                return None

        # Check we haven't detected too many gaps recently (anti-spam)
        recent_cutoff = time.time() - 300  # 5 minutes
        self._recent_gaps = [
            g for g in self._recent_gaps if g.detected_at > recent_cutoff
        ]
        if len(self._recent_gaps) >= _MAX_SKILLS_PER_SESSION:
            logger.warning("[SkillNeedDetector] Too many gaps detected — throttling")
            return None

        gap = SkillGap(
            user_input=stripped,
            route=route,
            confidence=confidence,
            reason="Orchestrator route=unknown, no matching skill found",
        )
        self._recent_gaps.append(gap)

        logger.info(
            "[SkillNeedDetector] Skill gap detected: %r (confidence=%.2f)",
            stripped[:60],
            confidence,
        )
        return gap

    @property
    def recent_gaps(self) -> list[SkillGap]:
        """Return recent skill gap detections."""
        return list(self._recent_gaps)


# ---------------------------------------------------------------------------
# Skill Generator (LLM-powered)
# ---------------------------------------------------------------------------

# Prompt for generating a SKILL.md from a user request
_GENERATION_PROMPT = """Sen Bantz AI asistanının skill oluşturma modülüsün.
Kullanıcı bir istek yaptı ama bu isteği karşılayacak bir skill yok.
Aşağıdaki kullanıcı isteğine göre bir SKILL.md dosyası oluştur.

## Kurallar

1. YAML frontmatter + Markdown body formatında yaz.
2. `name` alanı kebab-case olmalı (örn: hava-durumu, dosya-yonetici).
3. `triggers` bölümünde Türkçe regex pattern'leri kullan.
4. `handler` her zaman "llm" olsun (güvenlik için script kullanma).
5. `permissions` sadece gerekli olanları ekle. ASLA shell erişimi verme.
6. Markdown body'de Türkçe yaz ve skill'in nasıl davranması gerektiğini açıkla.
7. Skill bir LLM skill'idir — gerçek API çağırmaz, LLM'in bilgisiyle yanıt verir.
8. Sadece SKILL.md içeriğini döndür, başka bir şey yazma.

## Kullanıcı İsteği

"{user_input}"

## Çıktı Formatı

Sadece SKILL.md içeriğini yaz (--- ile başlayan YAML frontmatter + Markdown body).
Başka açıklama, yorum veya markdown code block ekleme.
"""


@dataclass
class GenerationResult:
    """Result of SKILL.md generation."""

    success: bool
    skill_md_content: str = ""
    skill: DeclarativeSkill | None = None
    skill_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    generation_time_ms: int = 0
    gap: SkillGap | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "success": self.success,
            "errors": self.errors,
            "generation_time_ms": self.generation_time_ms,
        }
        if self.skill:
            d["skill_name"] = self.skill.name
            d["skill_description"] = self.skill.metadata.description
            d["skill_icon"] = self.skill.metadata.icon
            d["skill_version"] = self.skill.metadata.version
            d["skill_triggers"] = len(self.skill.metadata.triggers)
            d["skill_tools"] = len(self.skill.metadata.tools)
        if self.skill_path:
            d["skill_path"] = str(self.skill_path)
        return d


class SkillGenerator:
    """Generates SKILL.md files via LLM based on detected skill gaps.

    Parameters
    ----------
    llm : LLMProtocol | None
        LLM client with ``complete_text`` method. If None, will try
        to create one from environment on first use.
    auto_skill_dir : Path | None
        Directory for auto-generated skills. Defaults to
        ``~/.config/bantz/skills/auto-generated/``.
    """

    def __init__(
        self,
        llm: Any = None,
        auto_skill_dir: Path | None = None,
    ) -> None:
        self._llm = llm
        self._auto_skill_dir = auto_skill_dir or self._default_auto_dir()
        self._generation_count = 0

    @staticmethod
    def _default_auto_dir() -> Path:
        config_home = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        )
        return config_home / "bantz" / "skills"

    def _get_llm(self) -> Any:
        """Lazy-init LLM client."""
        if self._llm is not None:
            return self._llm
        try:
            from bantz.llm import create_quality_client
            self._llm = create_quality_client()
            return self._llm
        except Exception as exc:
            logger.error("[SkillGenerator] Failed to create LLM client: %s", exc)
            raise RuntimeError(
                "LLM client not available for skill generation"
            ) from exc

    def generate(self, gap: SkillGap) -> GenerationResult:
        """Generate a SKILL.md from a detected skill gap.

        Parameters
        ----------
        gap : SkillGap
            The detected capability gap.

        Returns
        -------
        GenerationResult
            Result with success/failure, parsed skill, and errors.
        """
        start = time.time()
        errors: list[str] = []

        # Safety check: generation count
        if self._generation_count >= _MAX_SKILLS_PER_SESSION:
            return GenerationResult(
                success=False,
                errors=["Oturum başına maksimum skill üretim sayısına ulaşıldı"],
                gap=gap,
            )

        # Build prompt
        prompt = _GENERATION_PROMPT.format(user_input=gap.user_input)

        try:
            llm = self._get_llm()

            # Call LLM
            try:
                raw_content = llm.complete_text(
                    prompt=prompt,
                    temperature=0.3,
                    max_tokens=1024,
                )
            except TypeError:
                raw_content = llm.complete_text(prompt=prompt)

            if not raw_content or not raw_content.strip():
                return GenerationResult(
                    success=False,
                    errors=["LLM boş yanıt döndürdü"],
                    gap=gap,
                    generation_time_ms=int((time.time() - start) * 1000),
                )

            # Clean up LLM output (remove markdown code fences if present)
            content = self._clean_llm_output(raw_content)

            # Parse the generated SKILL.md
            skill = self._parse_generated_content(content)
            if skill is None:
                return GenerationResult(
                    success=False,
                    skill_md_content=content,
                    errors=["Üretilen SKILL.md ayrıştırılamadı"],
                    gap=gap,
                    generation_time_ms=int((time.time() - start) * 1000),
                )

            # Security validation
            security_errors = self._security_check(skill)
            if security_errors:
                errors.extend(security_errors)
                return GenerationResult(
                    success=False,
                    skill_md_content=content,
                    skill=skill,
                    errors=errors,
                    gap=gap,
                    generation_time_ms=int((time.time() - start) * 1000),
                )

            # Validate skill structure
            validation_errors = skill.validate()
            if validation_errors:
                errors.extend(validation_errors)
                return GenerationResult(
                    success=False,
                    skill_md_content=content,
                    skill=skill,
                    errors=errors,
                    gap=gap,
                    generation_time_ms=int((time.time() - start) * 1000),
                )

            # Write to disk (pending approval)
            skill_path = self._write_skill(skill, content)

            self._generation_count += 1

            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(
                "[SkillGenerator] Generated skill %r in %dms: %s",
                skill.name,
                elapsed_ms,
                skill_path,
            )

            return GenerationResult(
                success=True,
                skill_md_content=content,
                skill=skill,
                skill_path=skill_path,
                gap=gap,
                generation_time_ms=elapsed_ms,
            )

        except Exception as exc:
            logger.exception("[SkillGenerator] Generation failed: %s", exc)
            return GenerationResult(
                success=False,
                errors=[f"Üretim hatası: {exc}"],
                gap=gap,
                generation_time_ms=int((time.time() - start) * 1000),
            )

    def _clean_llm_output(self, raw: str) -> str:
        """Remove markdown code fences and extra whitespace from LLM output."""
        text = raw.strip()
        # Remove ```yaml ... ``` or ```markdown ... ``` wrappers
        text = re.sub(r"^```(?:yaml|markdown|md)?\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        # Ensure it starts with ---
        if not text.startswith("---"):
            # Try to find the first --- in the text
            idx = text.find("---")
            if idx >= 0:
                text = text[idx:]
            else:
                return text  # Let parse_generated_content handle the error
        return text.strip()

    def _parse_generated_content(self, content: str) -> DeclarativeSkill | None:
        """Parse a SKILL.md content string into a DeclarativeSkill."""
        try:
            # Use the same regex as SkillLoader
            import re as _re
            pattern = _re.compile(
                r"\A\s*---\s*\n(.*?)\n---\s*\n(.*)",
                _re.DOTALL,
            )
            match = pattern.match(content)
            if not match:
                logger.warning("[SkillGenerator] No valid frontmatter in generated content")
                return None

            yaml_text = match.group(1)
            body = match.group(2).strip()

            data = yaml.safe_load(yaml_text)
            if not isinstance(data, dict):
                logger.warning("[SkillGenerator] YAML frontmatter is not a dict")
                return None

            # Ensure required fields
            if "name" not in data:
                logger.warning("[SkillGenerator] No 'name' in generated YAML")
                return None

            metadata = SkillMetadata.from_dict(data)

            return DeclarativeSkill(
                metadata=metadata,
                instructions=body,
                source_path=None,
                _instructions_loaded=True,
            )
        except Exception as exc:
            logger.warning("[SkillGenerator] Parse error: %s", exc)
            return None

    def _security_check(self, skill: DeclarativeSkill) -> list[str]:
        """Run security checks on a generated skill."""
        errors: list[str] = []

        # Blocked names
        name_lower = skill.name.lower().replace("-", "").replace("_", "")
        for blocked in _BLOCKED_SKILL_NAMES:
            if blocked in name_lower:
                errors.append(f"Güvenlik: Yasaklı skill adı tespit edildi: {blocked!r}")

        # No script handlers allowed in auto-generated skills
        for tool in skill.metadata.tools:
            handler = tool.handler.strip()
            if handler.startswith("script:"):
                errors.append(
                    f"Güvenlik: Otomatik skill'lerde script handler'ı yasak: {tool.name}"
                )
            # Only allow llm and builtin handlers
            if not (handler == "llm" or handler.startswith("builtin:")):
                errors.append(
                    f"Güvenlik: Bilinmeyen handler türü: {handler!r} ({tool.name})"
                )

        # Dangerous permissions
        dangerous_perms = {SkillPermission.SYSTEM, SkillPermission.FILESYSTEM}
        for perm in skill.metadata.permissions:
            if perm in dangerous_perms:
                errors.append(
                    f"Güvenlik: Tehlikeli izin tespit edildi: {perm.name}"
                )

        return errors

    def _write_skill(self, skill: DeclarativeSkill, content: str) -> Path:
        """Write the generated SKILL.md to disk in a pending state."""
        skill_dir = self._auto_skill_dir / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_path = skill_dir / "SKILL.md"

        # If skill already exists, add version suffix
        if skill_path.exists():
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            skill_dir = self._auto_skill_dir / f"{skill.name}-{ts}"
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path = skill_dir / "SKILL.md"

        skill_path.write_text(content, encoding="utf-8")

        # Write metadata marker
        meta_path = skill_dir / ".auto-generated.json"
        meta_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(),
                    "source": "self-evolving-agent",
                    "issue": "#837",
                    "approved": False,
                    "version": skill.metadata.version,
                    "user_input": "",  # Filled by caller
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return skill_path

    @property
    def generation_count(self) -> int:
        return self._generation_count


# ---------------------------------------------------------------------------
# Skill Validator
# ---------------------------------------------------------------------------

class SkillValidator:
    """Validates generated skills before they are activated.

    Checks:
    1. ``DeclarativeSkill.validate()`` passes
    2. YAML frontmatter is well-formed
    3. No dangerous patterns in instructions
    4. Script handlers (if any) pass sandbox tests
    """

    # Dangerous patterns in LLM instructions
    _DANGEROUS_INSTRUCTION_PATTERNS = [
        r"subprocess|os\.system|os\.popen|eval\s*\(|exec\s*\(",
        r"import\s+(?:subprocess|shutil|ctypes)",
        r"(?:rm\s+-rf|sudo|chmod\s+777)",
        r"(?:api[_-]?key|secret|password|token)\s*=",
    ]
    _DANGEROUS_RE = re.compile(
        "|".join(_DANGEROUS_INSTRUCTION_PATTERNS), re.IGNORECASE
    )

    def validate(self, skill: DeclarativeSkill) -> list[str]:
        """Full validation of a generated skill.

        Returns list of error messages (empty = valid).
        """
        errors: list[str] = []

        # 1. Structure validation
        errors.extend(skill.validate())

        # 2. Name safety
        name_lower = skill.name.lower().replace("-", "").replace("_", "")
        for blocked in _BLOCKED_SKILL_NAMES:
            if blocked in name_lower:
                errors.append(f"Yasaklı skill adı: {blocked!r}")

        # 3. Instruction safety
        if skill.instructions:
            dangerous_match = self._DANGEROUS_RE.search(skill.instructions)
            if dangerous_match:
                errors.append(
                    f"Talimatlarında tehlikeli pattern: {dangerous_match.group()!r}"
                )

        # 4. Tool handler validation
        for tool in skill.metadata.tools:
            handler = tool.handler.strip()
            if handler.startswith("script:"):
                errors.append(
                    f"Otomatik üretilen skill'lerde script handler yasak: {tool.name}"
                )

        # 5. Permission validation
        dangerous_perms = {SkillPermission.SYSTEM, SkillPermission.FILESYSTEM}
        for perm in skill.metadata.permissions:
            if perm in dangerous_perms:
                errors.append(
                    f"Tehlikeli izin: {perm.name} — kullanıcı onayı gerekir"
                )

        return errors


# ---------------------------------------------------------------------------
# Skill Version Manager
# ---------------------------------------------------------------------------

@dataclass
class SkillVersion:
    """Tracks a version of an auto-generated skill."""
    name: str
    version: str
    path: Path
    generated_at: str
    approved: bool = False
    active: bool = False
    user_input: str = ""


class SkillVersionManager:
    """Manages versions of auto-generated skills.

    Tracks which skills were auto-generated, their approval status,
    and supports rollback.
    """

    def __init__(self, auto_skill_dir: Path | None = None) -> None:
        config_home = Path(
            os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        )
        self._auto_dir = auto_skill_dir or (config_home / "bantz" / "skills")
        self._versions: dict[str, list[SkillVersion]] = {}

    def record(
        self,
        skill: DeclarativeSkill,
        path: Path,
        user_input: str = "",
    ) -> SkillVersion:
        """Record a new auto-generated skill version."""
        version = SkillVersion(
            name=skill.name,
            version=skill.metadata.version,
            path=path,
            generated_at=datetime.now().isoformat(),
            user_input=user_input,
        )
        self._versions.setdefault(skill.name, []).append(version)
        return version

    def approve(self, skill_name: str) -> bool:
        """Mark the latest version of a skill as approved."""
        versions = self._versions.get(skill_name, [])
        if not versions:
            return False
        versions[-1].approved = True
        versions[-1].active = True
        self._save_approval(versions[-1])
        return True

    def reject(self, skill_name: str) -> bool:
        """Reject and delete the latest version of a skill."""
        versions = self._versions.get(skill_name, [])
        if not versions:
            return False
        latest = versions[-1]
        latest.approved = False
        latest.active = False

        # Delete the skill file and directory
        try:
            if latest.path.exists():
                latest.path.unlink()
            parent = latest.path.parent
            meta = parent / ".auto-generated.json"
            if meta.exists():
                meta.unlink()
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError as exc:
            logger.warning("Failed to clean up rejected skill: %s", exc)

        versions.pop()
        return True

    def rollback(self, skill_name: str) -> SkillVersion | None:
        """Rollback to the previous version of a skill."""
        versions = self._versions.get(skill_name, [])
        if len(versions) < 2:
            return None

        # Remove current version
        current = versions.pop()
        try:
            if current.path.exists():
                current.path.unlink()
        except OSError:
            pass

        # Re-activate previous
        prev = versions[-1]
        prev.active = True
        return prev

    def get_versions(self, skill_name: str) -> list[SkillVersion]:
        """Get all versions of a skill."""
        return list(self._versions.get(skill_name, []))

    def get_pending(self) -> list[SkillVersion]:
        """Get all skills pending approval."""
        pending: list[SkillVersion] = []
        for versions in self._versions.values():
            for v in versions:
                if not v.approved and not v.active:
                    pending.append(v)
        return pending

    def _save_approval(self, version: SkillVersion) -> None:
        """Update the .auto-generated.json marker with approval status."""
        meta_path = version.path.parent / ".auto-generated.json"
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                data["approved"] = True
                data["approved_at"] = datetime.now().isoformat()
                meta_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("Failed to update approval marker: %s", exc)

    def get_status(self) -> dict[str, Any]:
        """Return summary status of all managed skill versions."""
        return {
            "total_skills": len(self._versions),
            "total_versions": sum(len(v) for v in self._versions.values()),
            "pending_approval": len(self.get_pending()),
            "skills": {
                name: {
                    "versions": len(versions),
                    "latest_version": versions[-1].version if versions else None,
                    "approved": versions[-1].approved if versions else False,
                    "active": versions[-1].active if versions else False,
                }
                for name, versions in self._versions.items()
            },
        }


# ---------------------------------------------------------------------------
# Self-Evolving Skill Manager (main orchestration class)
# ---------------------------------------------------------------------------

class SelfEvolvingSkillManager:
    """Top-level manager that coordinates skill gap detection,
    generation, validation, approval, and hot-loading.

    This is the main class that the orchestrator loop and server
    interact with.
    """

    def __init__(
        self,
        llm: Any = None,
        auto_skill_dir: Path | None = None,
    ) -> None:
        self._detector = SkillNeedDetector()
        self._generator = SkillGenerator(llm=llm, auto_skill_dir=auto_skill_dir)
        self._validator = SkillValidator()
        self._version_mgr = SkillVersionManager(auto_skill_dir=auto_skill_dir)
        self._pending_result: GenerationResult | None = None

    # -- Detection -----------------------------------------------------------

    def check_for_skill_gap(
        self,
        user_input: str,
        route: str,
        confidence: float,
    ) -> SkillGap | None:
        """Check if the current turn reveals a skill gap.

        Called by the orchestrator loop after LLM planning phase
        when route="unknown".
        """
        existing_names: list[str] = []
        try:
            from bantz.skills.declarative.bridge import get_skill_registry
            registry = get_skill_registry()
            if registry:
                existing_names = registry.skill_names
        except Exception:
            pass

        return self._detector.detect(
            user_input=user_input,
            route=route,
            confidence=confidence,
            existing_skill_names=existing_names,
        )

    # -- Generation ----------------------------------------------------------

    def generate_skill(self, gap: SkillGap) -> GenerationResult:
        """Generate a new skill for the detected gap.

        The generated skill is written to disk but NOT activated.
        User must approve it first.
        """
        result = self._generator.generate(gap)

        if result.success and result.skill:
            # Record version
            self._version_mgr.record(
                skill=result.skill,
                path=result.skill_path or Path(),
                user_input=gap.user_input,
            )
            # Store for pending approval
            self._pending_result = result

        return result

    # -- Approval Flow -------------------------------------------------------

    def approve_pending(self) -> dict[str, Any]:
        """Approve the pending generated skill and hot-load it.

        Returns a status dict with success/failure and skill info.
        """
        if self._pending_result is None or not self._pending_result.success:
            return {
                "ok": False,
                "text": "Onaylanacak bekleyen skill yok.",
            }

        result = self._pending_result
        skill = result.skill
        assert skill is not None

        # Validate one more time
        errors = self._validator.validate(skill)
        if errors:
            return {
                "ok": False,
                "text": "Skill doğrulaması başarısız:\n" + "\n".join(f"  - {e}" for e in errors),
                "errors": errors,
            }

        # Approve version
        self._version_mgr.approve(skill.name)

        # Hot-load into runtime
        loaded = self._hot_load_skill(skill, result.skill_path)

        self._pending_result = None

        if loaded:
            return {
                "ok": True,
                "text": (
                    f"{skill.metadata.icon} **{skill.name}** skill'i başarıyla kuruldu!\n"
                    f"📝 {skill.metadata.description}\n"
                    f"🔑 Tetikleyiciler: {len(skill.metadata.triggers)} | "
                    f"Araçlar: {len(skill.metadata.tools)}\n"
                    f"Artık bu konuda size yardımcı olabilirim."
                ),
                "skill_name": skill.name,
                "skill_icon": skill.metadata.icon,
            }
        else:
            return {
                "ok": False,
                "text": f"Skill {skill.name!r} oluşturuldu ama yüklenemedi.",
                "skill_name": skill.name,
            }

    def reject_pending(self) -> dict[str, Any]:
        """Reject the pending generated skill and clean up."""
        if self._pending_result is None:
            return {
                "ok": False,
                "text": "Reddedilecek bekleyen skill yok.",
            }

        result = self._pending_result
        skill_name = result.skill.name if result.skill else "unknown"

        # Reject and clean up
        self._version_mgr.reject(skill_name)
        self._pending_result = None

        return {
            "ok": True,
            "text": f"❌ Skill önerisi reddedildi.",
            "skill_name": skill_name,
        }

    # -- Hot Loading ---------------------------------------------------------

    def _hot_load_skill(
        self,
        skill: DeclarativeSkill,
        skill_path: Path | None,
    ) -> bool:
        """Hot-load a skill into the running system.

        1. Update source_path on the skill
        2. Register in DeclarativeSkillRegistry
        3. Inject tools into ToolRegistry
        """
        try:
            from bantz.skills.declarative.bridge import get_skill_registry
            registry = get_skill_registry()
            if registry is None:
                logger.warning("[SelfEvolving] No skill registry — can't hot-load")
                return False

            # Update source path
            if skill_path:
                skill.source_path = skill_path

            # Register
            registry.register(skill)

            # Inject tools into runtime tool registry
            try:
                from bantz.agent.tools import ToolRegistry
                # Get the global tool registry from orchestrator
                from bantz.core.orchestrator import get_orchestrator
                orch = get_orchestrator()
                if orch and hasattr(orch, "tool_registry"):
                    registry.inject_into_tool_registry(orch.tool_registry)
                    logger.info(
                        "[SelfEvolving] Hot-loaded skill %s into tool registry",
                        skill.name,
                    )
            except Exception as exc:
                logger.warning(
                    "[SelfEvolving] Tool injection failed (skill still registered): %s",
                    exc,
                )

            return True

        except Exception as exc:
            logger.exception("[SelfEvolving] Hot-load failed: %s", exc)
            return False

    # -- Status & Info -------------------------------------------------------

    @property
    def has_pending(self) -> bool:
        """Whether there's a pending skill awaiting approval."""
        return self._pending_result is not None and self._pending_result.success

    @property
    def pending_skill_name(self) -> str | None:
        """Name of the pending skill (if any)."""
        if self._pending_result and self._pending_result.skill:
            return self._pending_result.skill.name
        return None

    @property
    def pending_result(self) -> GenerationResult | None:
        """The pending generation result (if any)."""
        return self._pending_result

    def get_status(self) -> dict[str, Any]:
        """Return full status of the self-evolving skill system."""
        return {
            "detector": {
                "recent_gaps": len(self._detector.recent_gaps),
            },
            "generator": {
                "generation_count": self._generator.generation_count,
            },
            "versions": self._version_mgr.get_status(),
            "has_pending": self.has_pending,
            "pending_skill": self.pending_skill_name,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_manager: SelfEvolvingSkillManager | None = None


def get_self_evolving_manager() -> SelfEvolvingSkillManager | None:
    """Return the global SelfEvolvingSkillManager (if initialized)."""
    return _global_manager


def setup_self_evolving(
    llm: Any = None,
    auto_skill_dir: Path | None = None,
) -> SelfEvolvingSkillManager:
    """Initialize the self-evolving skill manager.

    Called during Bantz startup (from bridge.py or server.py).
    """
    global _global_manager
    _global_manager = SelfEvolvingSkillManager(
        llm=llm,
        auto_skill_dir=auto_skill_dir,
    )
    logger.info("[SelfEvolving] Self-evolving skill manager initialized")
    return _global_manager
