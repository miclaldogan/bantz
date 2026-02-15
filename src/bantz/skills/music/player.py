"""Abstract music player interface + shared data models.

Issue #1296: Müzik Kontrolü — Player abstraction layer.

Provides:
- ``Track`` dataclass for track metadata
- ``PlayerState`` enum for playback state
- ``MusicPlayer`` ABC — common interface for all backends
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class PlayerState(str, enum.Enum):
    """Playback state."""

    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass
class Track:
    """Track metadata."""

    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    uri: str = ""
    art_url: str = ""
    source: str = ""  # "spotify", "local", etc.

    @property
    def duration_human(self) -> str:
        """Human-readable duration (m:ss)."""
        total_sec = self.duration_ms // 1000
        minutes = total_sec // 60
        seconds = total_sec % 60
        return f"{minutes}:{seconds:02d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration_human,
            "duration_ms": self.duration_ms,
            "uri": self.uri,
            "art_url": self.art_url,
            "source": self.source,
        }

    def __str__(self) -> str:
        if self.artist:
            return f"{self.artist} — {self.title}"
        return self.title or "(bilinmeyen parça)"


@dataclass
class Playlist:
    """Playlist metadata."""

    name: str
    id: str = ""
    track_count: int = 0
    uri: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "id": self.id,
            "track_count": self.track_count,
            "uri": self.uri,
            "source": self.source,
        }


class MusicPlayer(ABC):
    """Abstract music player interface.

    All player backends (Spotify, local MPRIS) implement this.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Player backend name (e.g., 'spotify', 'mpris')."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether this player backend is currently available."""

    @abstractmethod
    async def play(
        self,
        query: str | None = None,
        *,
        playlist: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Start playback.

        Args:
            query: Search query (e.g., "jazz", "lo-fi beats").
            playlist: Playlist name or ID.
            uri: Direct URI to play.

        Returns:
            Dict with ``ok``, ``track``, etc.
        """

    @abstractmethod
    async def pause(self) -> dict[str, Any]:
        """Pause playback."""

    @abstractmethod
    async def resume(self) -> dict[str, Any]:
        """Resume playback."""

    @abstractmethod
    async def next_track(self) -> dict[str, Any]:
        """Skip to next track."""

    @abstractmethod
    async def prev_track(self) -> dict[str, Any]:
        """Go to previous track."""

    @abstractmethod
    async def stop(self) -> dict[str, Any]:
        """Stop playback."""

    @abstractmethod
    async def set_volume(self, level: int) -> dict[str, Any]:
        """Set volume (0-100)."""

    @abstractmethod
    async def get_volume(self) -> dict[str, Any]:
        """Get current volume."""

    @abstractmethod
    async def current_track(self) -> Track | None:
        """Get currently playing track metadata."""

    @abstractmethod
    async def get_state(self) -> PlayerState:
        """Get current playback state."""

    @abstractmethod
    async def search(
        self, query: str, *, limit: int = 10
    ) -> list[Track]:
        """Search for tracks."""

    @abstractmethod
    async def list_playlists(self) -> list[Playlist]:
        """List available playlists."""

    # ── Convenience ──────────────────────────────────────────────

    async def toggle(self) -> dict[str, Any]:
        """Toggle play/pause."""
        state = await self.get_state()
        if state == PlayerState.PLAYING:
            return await self.pause()
        return await self.resume()

    async def status(self) -> dict[str, Any]:
        """Get full player status."""
        state = await self.get_state()
        track = await self.current_track()
        vol = await self.get_volume()

        return {
            "ok": True,
            "player": self.name,
            "state": state.value,
            "track": track.to_dict() if track else None,
            "volume": vol.get("level"),
        }
