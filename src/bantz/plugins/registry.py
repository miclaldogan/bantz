"""
Skill Registry.

Online registry interface for discovering and installing plugins:
- Search for plugins
- Install from registry
- Update installed plugins
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
from datetime import datetime
from enum import Enum, auto

from bantz.plugins.base import PluginMetadata, PluginPermission

logger = logging.getLogger(__name__)


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
    Online registry of available plugins.
    
    Provides:
    - Search for plugins
    - Install from registry
    - Update installed plugins
    - Check for updates
    
    Example:
        registry = SkillRegistry()
        
        # Search for plugins
        results = registry.search("music")
        
        # Install a plugin
        registry.install("spotify")
        
        # Update a plugin
        registry.update("spotify")
    
    Note: Currently uses mock data. In production, this would
    connect to an actual registry server.
    """
    
    # Future: Real registry URL
    REGISTRY_URL = "https://registry.bantz.dev/api/v1"
    
    def __init__(
        self,
        install_dir: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
    ):
        """
        Initialize skill registry.
        
        Args:
            install_dir: Directory to install plugins
            cache_dir: Directory to cache registry data
        """
        import os
        
        if install_dir is None:
            config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
            install_dir = Path(config_home) / "bantz" / "plugins"
        
        if cache_dir is None:
            cache_home = os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
            cache_dir = Path(cache_home) / "bantz" / "registry"
        
        self.install_dir = Path(install_dir)
        self.cache_dir = Path(cache_dir)
        
        self._mock_entries = self._create_mock_entries()
    
    def _create_mock_entries(self) -> List[RegistryEntry]:
        """Create mock registry entries for development."""
        return [
            RegistryEntry(
                name="spotify",
                version="1.0.0",
                author="Bantz",
                description="Spotify müzik kontrolü - oynat, duraklat, sonraki/önceki şarkı",
                source=RegistrySource.OFFICIAL,
                repository="https://github.com/bantz/plugin-spotify",
                downloads=1523,
                rating=4.5,
                ratings_count=42,
                tags=["music", "spotify", "media"],
                permissions=[PluginPermission.NETWORK],
                icon="🎵",
                verified=True,
            ),
            RegistryEntry(
                name="notion",
                version="1.2.0",
                author="Bantz",
                description="Notion entegrasyonu - not oluştur, düzenle, ara",
                source=RegistrySource.OFFICIAL,
                repository="https://github.com/bantz/plugin-notion",
                downloads=892,
                rating=4.3,
                ratings_count=28,
                tags=["notes", "notion", "productivity"],
                permissions=[PluginPermission.NETWORK],
                icon="📝",
                verified=True,
            ),
            RegistryEntry(
                name="home-assistant",
                version="2.0.0",
                author="Community",
                description="Home Assistant akıllı ev kontrolü",
                source=RegistrySource.COMMUNITY,
                repository="https://github.com/community/bantz-ha",
                downloads=567,
                rating=4.7,
                ratings_count=19,
                tags=["smart-home", "iot", "automation"],
                permissions=[PluginPermission.NETWORK],
                icon="🏠",
                verified=False,
            ),
            RegistryEntry(
                name="calendar",
                version="1.1.0",
                author="Bantz",
                description="Takvim yönetimi - etkinlik oluştur, hatırlat",
                source=RegistrySource.OFFICIAL,
                repository="https://github.com/bantz/plugin-calendar",
                downloads=1245,
                rating=4.6,
                ratings_count=35,
                tags=["calendar", "events", "productivity"],
                permissions=[PluginPermission.CALENDAR],
                icon="📅",
                verified=True,
            ),
            RegistryEntry(
                name="todoist",
                version="1.0.0",
                author="Community",
                description="Todoist görev yönetimi",
                source=RegistrySource.COMMUNITY,
                repository="https://github.com/user/bantz-todoist",
                downloads=234,
                rating=4.1,
                ratings_count=8,
                tags=["tasks", "todoist", "productivity"],
                permissions=[PluginPermission.NETWORK],
                icon="✅",
                verified=False,
            ),
            RegistryEntry(
                name="weather",
                version="1.0.0",
                author="Bantz",
                description="Hava durumu sorgulama",
                source=RegistrySource.OFFICIAL,
                repository="https://github.com/bantz/plugin-weather",
                downloads=2156,
                rating=4.8,
                ratings_count=67,
                tags=["weather", "forecast"],
                permissions=[PluginPermission.NETWORK, PluginPermission.LOCATION],
                icon="🌤️",
                verified=True,
            ),
        ]
    
    def search(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        verified_only: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> RegistrySearchResult:
        """
        Search for plugins in the registry.
        
        Args:
            query: Search query
            tags: Filter by tags
            verified_only: Only show verified plugins
            page: Page number
            per_page: Results per page
            
        Returns:
            Search results
        """
        results = self._mock_entries.copy()
        
        # Filter by query
        if query:
            query_lower = query.lower()
            results = [
                e for e in results
                if query_lower in e.name.lower() or
                   query_lower in e.description.lower() or
                   any(query_lower in tag.lower() for tag in e.tags)
            ]
        
        # Filter by tags
        if tags:
            tags_lower = [t.lower() for t in tags]
            results = [
                e for e in results
                if any(t.lower() in tags_lower for t in e.tags)
            ]
        
        # Filter verified
        if verified_only:
            results = [e for e in results if e.verified]
        
        # Sort by downloads
        results.sort(key=lambda e: e.downloads, reverse=True)
        
        # Paginate
        total = len(results)
        start = (page - 1) * per_page
        end = start + per_page
        results = results[start:end]
        
        return RegistrySearchResult(
            entries=results,
            total=total,
            page=page,
            per_page=per_page,
            query=query,
        )
    
    def get(self, name: str) -> Optional[RegistryEntry]:
        """
        Get a specific plugin from the registry.
        
        Args:
            name: Plugin name
            
        Returns:
            Registry entry or None
        """
        for entry in self._mock_entries:
            if entry.name == name:
                return entry
        return None
    
    def install(self, name: str, version: Optional[str] = None) -> bool:
        """
        Install a plugin from the registry.
        
        Args:
            name: Plugin name
            version: Specific version (or latest)
            
        Returns:
            True if installed successfully
        """
        entry = self.get(name)
        if not entry:
            logger.error(f"Plugin not found: {name}")
            return False
        
        # In production, this would:
        # 1. Download plugin from repository/URL
        # 2. Verify signatures
        # 3. Extract to install_dir
        # 4. Run post-install hooks
        
        logger.info(f"Would install {name} v{entry.version} to {self.install_dir}")
        
        # Mock: Create plugin directory
        plugin_dir = self.install_dir / name
        plugin_dir.mkdir(parents=True, exist_ok=True)
        
        return True
    
    def uninstall(self, name: str) -> bool:
        """
        Uninstall a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if uninstalled successfully
        """
        plugin_dir = self.install_dir / name
        
        if not plugin_dir.exists():
            logger.warning(f"Plugin not installed: {name}")
            return False
        
        # In production, this would:
        # 1. Run pre-uninstall hooks
        # 2. Remove plugin directory
        # 3. Clean up config
        
        import shutil
        shutil.rmtree(plugin_dir)
        
        logger.info(f"Uninstalled plugin: {name}")
        return True
    
    def update(self, name: str) -> bool:
        """
        Update an installed plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if updated successfully
        """
        entry = self.get(name)
        if not entry:
            logger.error(f"Plugin not found: {name}")
            return False
        
        # Check if installed
        plugin_dir = self.install_dir / name
        if not plugin_dir.exists():
            logger.error(f"Plugin not installed: {name}")
            return False
        
        # In production, this would:
        # 1. Check for newer version
        # 2. Download new version
        # 3. Backup current version
        # 4. Install new version
        # 5. Run migration hooks
        
        logger.info(f"Would update {name} to v{entry.version}")
        return True
    
    def check_updates(self) -> List[RegistryEntry]:
        """
        Check for available updates.
        
        Returns:
            List of plugins with available updates
        """
        updates = []
        
        # Check each installed plugin
        if self.install_dir.exists():
            for plugin_dir in self.install_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue
                
                name = plugin_dir.name
                entry = self.get(name)
                
                if entry:
                    # In production, compare versions
                    # For now, just return all as having updates
                    updates.append(entry)
        
        return updates
    
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
    
    def get_popular(self, limit: int = 10) -> List[RegistryEntry]:
        """Get most popular plugins."""
        entries = self._mock_entries.copy()
        entries.sort(key=lambda e: e.downloads, reverse=True)
        return entries[:limit]
    
    def get_recent(self, limit: int = 10) -> List[RegistryEntry]:
        """Get recently updated plugins."""
        entries = [e for e in self._mock_entries if e.updated_at]
        entries.sort(key=lambda e: e.updated_at, reverse=True)
        return entries[:limit]
    
    def get_by_tag(self, tag: str) -> List[RegistryEntry]:
        """Get plugins by tag."""
        return [
            e for e in self._mock_entries
            if tag.lower() in [t.lower() for t in e.tags]
        ]


class MockSkillRegistry(SkillRegistry):
    """Mock registry for testing."""
    
    def __init__(self, entries: Optional[List[RegistryEntry]] = None):
        super().__init__()
        if entries is not None:
            self._mock_entries = entries
    
    def add_entry(self, entry: RegistryEntry) -> None:
        """Add an entry to the mock registry."""
        self._mock_entries.append(entry)
    
    def clear(self) -> None:
        """Clear all entries."""
        self._mock_entries.clear()
