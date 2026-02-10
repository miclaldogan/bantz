"""SKILL.md file parser and skill directory scanner (Issue #833).

Discovers and loads declarative skills from the filesystem.

Skill Directory Layout::

    ~/.config/bantz/skills/
    ├── weather/
    │   └── SKILL.md
    ├── greeting/
    │   └── SKILL.md
    └── news/
        ├── SKILL.md
        └── scripts/
            └── fetch_rss.py

SKILL.md Format::

    ---
    name: weather
    version: 0.1.0
    description: Hava durumu sorgulama ve takvim çapraz analizi.
    icon: 🌤️
    triggers:
      - pattern: "hava.*(durumu|nasıl)"
        intent: weather.current
        examples: ["bugün hava nasıl", "hava durumu"]
    tools:
      - name: weather.get_current
        description: Mevcut hava durumunu getirir
        parameters:
          - name: location
            type: string
            description: Şehir adı
    permissions:
      - network
    ---

    # Weather Skill

    Sen bir hava durumu asistanısın. Kullanıcı hava durumu sorduğunda...
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

import yaml

from bantz.skills.declarative.models import DeclarativeSkill, SkillMetadata

logger = logging.getLogger(__name__)

# Frontmatter separator pattern: lines of exactly "---"
_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)

# Default skill directories (XDG-compliant)
_DEFAULT_SKILL_DIRS: list[Path] = []


def _get_default_skill_dirs() -> list[Path]:
    """Return the default skill discovery directories."""
    config_home = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )

    # Also check BANTZ_SKILLS_DIR env var
    extra_dir = os.environ.get("BANTZ_SKILLS_DIR")

    dirs = [
        config_home / "bantz" / "skills",
        data_home / "bantz" / "skills",
    ]
    if extra_dir:
        dirs.insert(0, Path(extra_dir))

    return dirs


class SkillLoader:
    """Discovers and loads SKILL.md files from the filesystem.

    Parameters
    ----------
    skill_dirs : list[Path] | None
        Directories to scan for skill folders. Each subfolder with a
        ``SKILL.md`` file is treated as a skill. Defaults to
        ``~/.config/bantz/skills/`` and ``~/.local/share/bantz/skills/``.
    lazy : bool
        If True (default), only parse the YAML frontmatter during
        discovery — the Markdown body is loaded lazily on first use
        (progressive loading).
    """

    SKILL_FILENAME = "SKILL.md"

    def __init__(
        self,
        skill_dirs: Optional[list[Path]] = None,
        *,
        lazy: bool = True,
    ) -> None:
        self.skill_dirs = skill_dirs or _get_default_skill_dirs()
        self.lazy = lazy
        self._discovered: dict[str, DeclarativeSkill] = {}

    def discover(self) -> list[DeclarativeSkill]:
        """Scan all skill directories and return discovered skills.

        Scans each directory for subdirectories containing a SKILL.md file.
        Invalid or duplicate skills are logged and skipped.
        """
        self._discovered.clear()
        skills: list[DeclarativeSkill] = []

        for skill_dir in self.skill_dirs:
            if not skill_dir.is_dir():
                logger.debug("Skill directory does not exist: %s", skill_dir)
                continue

            for entry in sorted(skill_dir.iterdir()):
                if not entry.is_dir():
                    continue
                skill_file = entry / self.SKILL_FILENAME
                if not skill_file.is_file():
                    continue

                try:
                    skill = self._load_one(skill_file)
                    if skill.name in self._discovered:
                        logger.warning(
                            "Duplicate skill %r — skipping %s (already loaded from %s)",
                            skill.name,
                            skill_file,
                            self._discovered[skill.name].source_path,
                        )
                        continue

                    errors = skill.validate()
                    if errors:
                        logger.warning(
                            "Skill %r has validation errors: %s — skipping",
                            skill.name,
                            "; ".join(errors),
                        )
                        continue

                    self._discovered[skill.name] = skill
                    skills.append(skill)
                    logger.info(
                        "Discovered skill: %s %s v%s (%d triggers, %d tools)",
                        skill.metadata.icon,
                        skill.name,
                        skill.metadata.version,
                        len(skill.metadata.triggers),
                        len(skill.metadata.tools),
                    )
                except Exception:
                    logger.exception(
                        "Failed to load skill from %s — skipping", skill_file
                    )

        return skills

    def _load_one(self, skill_file: Path) -> DeclarativeSkill:
        """Load a single SKILL.md file.

        In lazy mode, only the YAML frontmatter is parsed; the Markdown
        body is deferred until :meth:`DeclarativeSkill.load_instructions`
        is called.
        """
        if self.lazy:
            return self.parse_frontmatter_only(skill_file)
        return self.parse_skill_file(skill_file)

    @staticmethod
    def parse_skill_file(path: Path) -> DeclarativeSkill:
        """Parse a complete SKILL.md file (frontmatter + body).

        Parameters
        ----------
        path : Path
            Path to the SKILL.md file.

        Returns
        -------
        DeclarativeSkill
            Fully parsed skill with instructions loaded.

        Raises
        ------
        ValueError
            If the file doesn't contain valid YAML frontmatter.
        """
        content = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError(
                f"No valid YAML frontmatter found in {path}. "
                f"SKILL.md must start with '---' delimiters."
            )

        yaml_text = match.group(1)
        body = match.group(2).strip()

        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML frontmatter in {path} must be a mapping, got {type(data).__name__}"
            )

        metadata = SkillMetadata.from_dict(data)

        return DeclarativeSkill(
            metadata=metadata,
            instructions=body,
            source_path=path,
            _instructions_loaded=True,
        )

    @staticmethod
    def parse_frontmatter_only(path: Path) -> DeclarativeSkill:
        """Parse only the YAML frontmatter (for lazy / progressive loading).

        The instructions body is NOT loaded — call
        :meth:`DeclarativeSkill.load_instructions` to load it later.
        """
        content = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError(
                f"No valid YAML frontmatter found in {path}. "
                f"SKILL.md must start with '---' delimiters."
            )

        yaml_text = match.group(1)

        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML frontmatter in {path} must be a mapping, got {type(data).__name__}"
            )

        metadata = SkillMetadata.from_dict(data)

        return DeclarativeSkill(
            metadata=metadata,
            instructions="",
            source_path=path,
            _instructions_loaded=False,
        )

    @staticmethod
    def create_skill_scaffold(
        name: str,
        target_dir: Optional[Path] = None,
        *,
        description: str = "",
        author: str = "",
    ) -> Path:
        """Create a new skill scaffold with SKILL.md template.

        Parameters
        ----------
        name : str
            Skill name (will also be the directory name).
        target_dir : Path | None
            Parent directory. Defaults to ``~/.config/bantz/skills/``.
        description : str
            Short description for the skill.
        author : str
            Author name.

        Returns
        -------
        Path
            Path to the created SKILL.md file.
        """
        if target_dir is None:
            config_home = Path(
                os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
            )
            target_dir = config_home / "bantz" / "skills"

        skill_dir = target_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            raise FileExistsError(f"Skill already exists: {skill_file}")

        desc = description or f"{name} skill for Bantz"
        auth = author or os.environ.get("USER", "unknown")

        template = f"""---
name: {name}
version: 0.1.0
author: {auth}
description: "{desc}"
icon: 🔧
tags:
  - custom

triggers:
  - pattern: "{name}"
    intent: {name}.default
    examples:
      - "{name} çalıştır"
    priority: 50

tools:
  - name: {name}.run
    description: "{desc}"
    handler: llm
    parameters:
      - name: query
        type: string
        description: "Kullanıcı isteği"
        required: true

permissions: []

config:
  enabled: true
---

# {name.title()} Skill

Sen Bantz asistanının **{name}** yeteneğisin.

## Görevin

Kullanıcının {name} ile ilgili isteklerini yerine getir.

## Kurallar

1. Her zaman Türkçe yanıt ver.
2. Net ve öz ol.
3. Emin olmadığın bilgiyi uydurma.

## Örnek Diyalog

**Kullanıcı:** {name} çalıştır
**Sen:** {name.title()} yeteneği aktif. Size nasıl yardımcı olabilirim?
"""

        skill_file.write_text(template, encoding="utf-8")
        logger.info("Created skill scaffold: %s", skill_file)
        return skill_file

    @property
    def discovered_skills(self) -> dict[str, DeclarativeSkill]:
        """Return all discovered skills (name → skill mapping)."""
        return dict(self._discovered)
