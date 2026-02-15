"""Music control package — Spotify, local MPRIS players, context-aware suggestions.

Issue #1296: Müzik Kontrolü — Spotify/Local Player + Context-Aware Suggestions.
"""

from bantz.skills.music.local_player import LocalPlayer
from bantz.skills.music.player import MusicPlayer, PlayerState, Track
from bantz.skills.music.spotify_player import SpotifyPlayer
from bantz.skills.music.suggester import MusicSuggester

__all__ = [
    "MusicPlayer",
    "PlayerState",
    "Track",
    "SpotifyPlayer",
    "LocalPlayer",
    "MusicSuggester",
]
