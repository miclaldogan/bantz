"""
Skill Registry.

Real registry interface for discovering and installing plugins:
- Install from Git URL (clone)
- Update installed plugins (git pull / checkout tag)
- Version control via git tags
- Local manifest (skill.yaml) based discovery
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from enum import Enum, auto

from bantz.plugins.base import PluginMetadata, PluginPermission

logger = logging.getLogger(__name__)

# Manifest filename expected inside each skill repository
SKILL_MANIFEST = "skill.yaml"


class RegistrySource(Enum):
    """Plugin registry sources."""
    
    OFFICIAL = auto()     # Official Bantz registry
    COMMUNITY = auto()    # Community registry
    LOCAL = auto()        # Local file
    GIT = auto()          # Git repository
    URL = auto()          # Direct URL


@dataclass
class RegistryEntry:
    """
    Entry in the skill registry.
    
    Contains metadata and installation info for a plugin.
    """
    
    name: str
    version: str
    author: str
    description: str
    source: RegistrySource = RegistrySource.COMMUNITY
    url: str = ""
    repository: str = ""
    downloads: int = 0
    rating: float = 0.0
    ratings_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    permissions: List[PluginPermission] = field(default_factory=list)
    min_bantz_version: str = "0.1.0"
    icon: str = "🔌"
    verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "source": self.source.name,
            "url": self.url,
            "repository": self.repository,
            "downloads": self.downloads,
            "rating": self.rating,
            "ratings_count": self.ratings_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "tags": self.tags,
            "permissions": [p.name for p in self.permissions],
            "min_bantz_version": self.min_bantz_version,
            "icon": self.icon,
            "verified": self.verified,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegistryEntry":
        """Create from dictionary."""
        permissions = []
        for p in data.get("permissions", []):
            try:
                permissions.append(PluginPermission[p.upper()])
            except KeyError:
                pass
        
        source = RegistrySource.COMMUNITY
        if "source" in data:
            try:
                source = RegistrySource[data["source"].upper()]
            except KeyError:
                pass
        
        created_at = None
        if data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(data["created_at"])
            except ValueError:
                pass
        
        updated_at = None
        if data.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(data["updated_at"])
            except ValueError:
                pass
        
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
            author=data.get("author", "unknown"),
            description=data.get("description", ""),
            source=source,
            url=data.get("url", ""),
            repository=data.get("repository", ""),
            downloads=data.get("downloads", 0),
            rating=data.get("rating", 0.0),
            ratings_count=data.get("ratings_count", 0),
            created_at=created_at,
            updated_at=updated_at,
            tags=data.get("tags", []),
            permissions=permissions,
            min_bantz_version=data.get("min_bantz_version", "0.1.0"),
            icon=data.get("icon", "🔌"),
            verified=data.get("verified", False),
        )
    
    def to_metadata(self) -> PluginMetadata:
        """Convert to PluginMetadata."""
        return PluginMetadata(
            name=self.name,
            version=self.version,
            author=self.author,
            description=self.description,
            permissions=self.permissions,
            tags=self.tags,
            repository=self.repository,
            min_bantz_version=self.min_bantz_version,
            icon=self.icon,
        )


@dataclass
class RegistrySearchResult:
    """Search result from registry."""
    
    entries: List[RegistryEntry]
    total: int
    page: int = 1
    per_page: int = 20
    query: str = ""
    
    @property
    def has_more(self) -> bool:
        """Check if there are more results."""
        return self.page * self.per_page < self.total


class SkillRegistry:
    """
    Git-based skill registry.

    Provides real plugin installation via ``git clone``, version pinning
    through git tags, and update via ``git pull`` / ``git checkout``.

    Example::

        registry = SkillRegistry()

        # Install from Git URL
        registry.install_from_git(
            "https://github.com/bantz/plugin-spotify",
            version="v1.0.0",
        )

        # Update to latest
        registry.update("plugin-spotify")

        # List installed
        print(registry.get_installed())
    """

    # Future: Real registry URL for online catalogue
    REGISTRY_URL = "https://registry.bantz.dev/api/v1"

    # Index file that caches installed-plugin metadata locally
    _INDEX_FILE = "installed.json"

    def __init__(
        self,
        install_dir: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
    ):
        config_home = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        cache_home = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))

        self.install_dir = Path(install_dir) if install_dir else Path(config_home) / "bantz" / "plugins"
        self.cache_dir = Path(cache_dir) if cache_dir else Path(cache_home) / "bantz" / "registry"

        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()

    # ── index persistence ────────────────────────────────────────

    def _index_path(self) -> Path:
        return self.install_dir / self._INDEX_FILE

    def _load_index(self) -> None:
        path = self._index_path()
        if path.exists():
            try:
                self._index = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def _save_index(self) -> None:
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(self._index, indent=2, default=str))

    # ── git helpers ──────────────────────────────────────────────

    @staticmethod
    def _run_git(args: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        """Run a git command and return the result."""
        cmd = ["git"] + args
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )

    @staticmethod
    def _repo_name_from_url(url: str) -> str:
        """Extract repository name from a Git URL."""
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name

    def _resolve_version(self, plugin_dir: Path, version: Optional[str]) -> Optional[str]:
        """Checkout a specific tag/version if requested."""
        if not version:
            return None
        result = self._run_git(["checkout", version], cwd=plugin_dir)
        if result.returncode != 0:
            logger.warning("Could not checkout version %s: %s", version, result.stderr.strip())
            return None
        return version

    # ── public API ───────────────────────────────────────────────

    def install_from_git(
        self,
        url: str,
        version: Optional[str] = None,
        name: Optional[str] = None,
    ) -> bool:
        """
        Install a skill by cloning its Git repository.

        Args:
            url: Git remote URL (https or ssh).
            version: Git tag / branch to pin (e.g. ``"v1.0.0"``).
            name: Override directory name (default: derived from URL).

        Returns:
            ``True`` on success.
        """
        repo_name = name or self._repo_name_from_url(url)
        plugin_dir = self.install_dir / repo_name

        if plugin_dir.exists():
            logger.warning("Plugin already installed at %s — use update() instead", plugin_dir)
            return False

        self.install_dir.mkdir(parents=True, exist_ok=True)

        result = self._run_git(["clone", url, str(plugin_dir)])
        if result.returncode != 0:
            logger.error("git clone failed: %s", result.stderr.strip())
            return False

        resolved = self._resolve_version(plugin_dir, version)

        # Read manifest if available
        metadata = self._read_manifest(plugin_dir)

        self._index[repo_name] = {
            "url": url,
            "version": resolved or "latest",
            "installed_at": datetime.utcnow().isoformat(),
            "source": RegistrySource.GIT.name,
            "metadata": metadata,
        }
        self._save_index()

        logger.info("Installed %s from %s (version=%s)", repo_name, url, resolved or "latest")
        return True

    def install(self, name: str, version: Optional[str] = None) -> bool:
        """
        Install a plugin by name.

        Looks up the name in the local index or known entries.
        Falls back to ``install_from_git`` if a repository URL is found.
        """
        entry = self.get(name)
        if entry and entry.repository:
            return self.install_from_git(entry.repository, version=version, name=name)

        logger.error("No repository URL found for plugin: %s", name)
        return False

    def uninstall(self, name: str) -> bool:
        """Remove an installed plugin."""
        plugin_dir = self.install_dir / name
        if not plugin_dir.exists():
            logger.warning("Plugin not installed: %s", name)
            return False

        shutil.rmtree(plugin_dir)
        self._index.pop(name, None)
        self._save_index()

        logger.info("Uninstalled plugin: %s", name)
        return True

    def update(self, name: str, version: Optional[str] = None) -> bool:
        """
        Update an installed plugin via ``git pull`` or tag checkout.

        Args:
            name: Plugin directory name.
            version: Pin a specific tag, or ``None`` to pull latest.
        """
        plugin_dir = self.install_dir / name
        if not plugin_dir.exists():
            logger.error("Plugin not installed: %s", name)
            return False

        if version:
            result = self._run_git(["fetch", "--tags"], cwd=plugin_dir)
            if result.returncode != 0:
                logger.error("git fetch failed: %s", result.stderr.strip())
                return False
            result = self._run_git(["checkout", version], cwd=plugin_dir)
        else:
            result = self._run_git(["pull", "--ff-only"], cwd=plugin_dir)

        if result.returncode != 0:
            logger.error("git update failed for %s: %s", name, result.stderr.strip())
            return False

        # Refresh metadata
        metadata = self._read_manifest(plugin_dir)
        if name in self._index:
            self._index[name]["version"] = version or "latest"
            self._index[name]["metadata"] = metadata
            self._save_index()

        logger.info("Updated %s to %s", name, version or "latest")
        return True

    def check_updates(self) -> List[str]:
        """
        Return names of installed plugins that have upstream changes.

        Performs ``git fetch`` + ``git rev-list`` comparison.
        """
        outdated: List[str] = []

        if not self.install_dir.exists():
            return outdated

        for name in list(self._index):
            plugin_dir = self.install_dir / name
            if not plugin_dir.exists():
                continue

            fetch = self._run_git(["fetch"], cwd=plugin_dir)
            if fetch.returncode != 0:
                continue

            diff = self._run_git(
                ["rev-list", "HEAD..@{u}", "--count"],
                cwd=plugin_dir,
            )
            if diff.returncode == 0 and diff.stdout.strip() not in ("0", ""):
                outdated.append(name)

        return outdated

    def get_installed(self) -> List[str]:
        """Get list of installed plugin names."""
        installed = []
        if self.install_dir.exists():
            for item in self.install_dir.iterdir():
                if item.is_dir() and (item / "plugin.py").exists():
                    installed.append(item.name)
        return installed

    def is_installed(self, name: str) -> bool:
        """Check if a plugin is installed."""
        return (self.install_dir / name / "plugin.py").exists()

    def get_installed_version(self, name: str) -> Optional[str]:
        """Return the pinned version of an installed plugin, or None."""
        info = self._index.get(name)
        return info["version"] if info else None

    def list_versions(self, name: str) -> List[str]:
        """
        List available git tags for an installed plugin.

        Returns:
            Sorted list of tag names (newest first).
        """
        plugin_dir = self.install_dir / name
        if not plugin_dir.exists():
            return []

        self._run_git(["fetch", "--tags"], cwd=plugin_dir)
        result = self._run_git(
            ["tag", "--sort=-creatordate"],
            cwd=plugin_dir,
        )
        if result.returncode != 0:
            return []

        return [t.strip() for t in result.stdout.splitlines() if t.strip()]

    # ── manifest / metadata ──────────────────────────────────────

    @staticmethod
    def _read_manifest(plugin_dir: Path) -> Optional[Dict[str, Any]]:
        """Read skill.yaml from a plugin directory if present."""
        manifest = plugin_dir / SKILL_MANIFEST
        if not manifest.exists():
            return None

        try:
            import yaml  # optional dep
            return yaml.safe_load(manifest.read_text())
        except ImportError:
            logger.debug("PyYAML not installed — skipping manifest parsing")
            return None
        except Exception as exc:
            logger.warning("Failed to read manifest %s: %s", manifest, exc)
            return None

    # ── catalogue / search (uses local index + cached entries) ───

    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        verified_only: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> RegistrySearchResult:
        """
        Search installed & cached catalogue entries.

        Currently operates on installed plugins only.
        When ``registry.bantz.dev`` is live, this will also query the API.
        """
        entries = self._build_entries_from_index()

        if query:
            q = query.lower()
            entries = [
                e for e in entries
                if q in e.name.lower() or q in e.description.lower()
                or any(q in t.lower() for t in e.tags)
            ]
        if tags:
            tl = [t.lower() for t in tags]
            entries = [e for e in entries if any(t.lower() in tl for t in e.tags)]
        if verified_only:
            entries = [e for e in entries if e.verified]

        total = len(entries)
        start = (page - 1) * per_page
        entries = entries[start:start + per_page]

        return RegistrySearchResult(
            entries=entries, total=total, page=page, per_page=per_page, query=query,
        )

    def get(self, name: str) -> Optional[RegistryEntry]:
        """Look up a specific entry from the local index."""
        info = self._index.get(name)
        if not info:
            return None

        meta = info.get("metadata") or {}
        return RegistryEntry(
            name=name,
            version=info.get("version", "0.0.0"),
            author=meta.get("author", "unknown"),
            description=meta.get("description", ""),
            source=RegistrySource.GIT,
            repository=info.get("url", ""),
            tags=meta.get("tags", []),
        )

    def _build_entries_from_index(self) -> List[RegistryEntry]:
        entries = []
        for name, info in self._index.items():
            meta = info.get("metadata") or {}
            entries.append(RegistryEntry(
                name=name,
                version=info.get("version", "0.0.0"),
                author=meta.get("author", "unknown"),
                description=meta.get("description", ""),
                source=RegistrySource.GIT,
                repository=info.get("url", ""),
                tags=meta.get("tags", []),
            ))
        return entries


class MockSkillRegistry(SkillRegistry):
    """Mock registry for testing — pre-seeds an in-memory index."""

    def __init__(
        self,
        entries: Optional[List[RegistryEntry]] = None,
        install_dir: Optional[Path] = None,
    ):
        import tempfile

        _dir = install_dir or Path(tempfile.mkdtemp(prefix="bantz_mock_reg_"))
        super().__init__(install_dir=_dir, cache_dir=_dir / ".cache")

        if entries:
            for e in entries:
                self._index[e.name] = {
                    "url": e.repository,
                    "version": e.version,
                    "installed_at": datetime.utcnow().isoformat(),
                    "source": e.source.name,
                    "metadata": {
                        "author": e.author,
                        "description": e.description,
                        "tags": e.tags,
                    },
                }

    def add_entry(self, entry: RegistryEntry) -> None:
        self._index[entry.name] = {
            "url": entry.repository,
            "version": entry.version,
            "installed_at": datetime.utcnow().isoformat(),
            "source": entry.source.name,
            "metadata": {
                "author": entry.author,
                "description": entry.description,
                "tags": entry.tags,
            },
        }

    def clear(self) -> None:
        self._index.clear()
