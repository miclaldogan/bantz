"""Music control package — Spotify, YouTube Music, local MPRIS players, context-aware suggestions.

Issue #1296: Music Control — Spotify/Local Player + Context-Aware Suggestions.
Issue #1300: YouTube Music Automation.
"""

from bantz.skills.music.local_player import LocalPlayer
from bantz.skills.music.player import MusicPlayer, PlayerState, Track
from bantz.skills.music.spotify_player import SpotifyPlayer
from bantz.skills.music.suggester import MusicSuggester
from bantz.skills.music.ytmusic_player import YTMusicPlayer

__all__ = [
    "MusicPlayer",
    "PlayerState",
    "Track",
    "SpotifyPlayer",
    "YTMusicPlayer",
    "LocalPlayer",
    "MusicSuggester",
]
