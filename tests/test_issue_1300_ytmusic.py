"""Tests for Issue #1300 — YouTube Music Player Backend.

Coverage:
- YTMusicPlayer properties (name, available)
- Playback controls via mocked playerctl (play, pause, next, prev, stop)
- Volume get/set via mocked playerctl
- current_track metadata parsing
- get_state MPRIS status parsing
- search via mocked ytmusicapi
- list_playlists via mocked ytmusicapi
- _open_url fallback
- _parse_duration helper
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bantz.skills.music.player import PlayerState
from bantz.skills.music.ytmusic_player import YTMusicPlayer, _parse_duration


# ═══════════════════════════════════════════════════════════════════
# _parse_duration helper
# ═══════════════════════════════════════════════════════════════════


class TestParseDuration:
    """Duration string → ms conversion."""

    def test_mm_ss(self):
        assert _parse_duration("3:45") == 225_000

    def test_hh_mm_ss(self):
        assert _parse_duration("1:02:30") == 3_750_000

    def test_empty(self):
        assert _parse_duration("") == 0

    def test_invalid(self):
        assert _parse_duration("abc") == 0

    def test_zero(self):
        assert _parse_duration("0:00") == 0


# ═══════════════════════════════════════════════════════════════════
# YTMusicPlayer properties
# ═══════════════════════════════════════════════════════════════════


class TestYTMusicPlayerInit:
    """Constructor & property tests."""

    def test_name(self):
        player = YTMusicPlayer()
        assert player.name == "ytmusic"

    @patch("shutil.which", return_value="/usr/bin/playerctl")
    def test_available_with_playerctl(self, _mock_which):
        player = YTMusicPlayer()
        assert player.available is True

    @patch("shutil.which", return_value=None)
    def test_not_available_without_anything(self, _mock_which):
        player = YTMusicPlayer()
        # Force ytmusic check fail
        player._ytmusic_checked = True
        player._ytmusic = None
        assert player.available is False


# ═══════════════════════════════════════════════════════════════════
# Playback controls (mocked playerctl)
# ═══════════════════════════════════════════════════════════════════

def _make_player() -> YTMusicPlayer:
    """Create a player with playerctl available."""
    with patch("shutil.which", return_value="/usr/bin/playerctl"):
        return YTMusicPlayer(browser_player="chromium")


def _mock_subprocess(stdout: str = "", returncode: int = 0):
    """Create a mock for asyncio.create_subprocess_exec."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        stdout.encode(), b"",
    )
    mock_proc.returncode = returncode
    return mock_proc


class TestPlaybackControls:
    """playerctl-based playback commands."""

    @pytest.mark.asyncio
    async def test_pause(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.pause()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_resume(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.resume()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_next_track(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.next_track()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_prev_track(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.prev_track()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_stop(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.stop()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_play_resume(self):
        """play() without args resumes current track."""
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.play()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_play_with_uri(self):
        """play(uri=...) opens URL via xdg-open."""
        player = _make_player()
        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("shutil.which", return_value="/usr/bin/xdg-open"):
            result = await player.play(uri="https://music.youtube.com/watch?v=xyz")
        assert result["ok"] is True
        assert result["url"] == "https://music.youtube.com/watch?v=xyz"

    @pytest.mark.asyncio
    async def test_playerctl_not_installed(self):
        """Commands fail gracefully without playerctl."""
        with patch("shutil.which", return_value=None):
            player = YTMusicPlayer()
        result = await player.pause()
        assert result["ok"] is False
        assert "not installed" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# Volume
# ═══════════════════════════════════════════════════════════════════


class TestVolume:
    """Volume get/set via playerctl."""

    @pytest.mark.asyncio
    async def test_set_volume(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.set_volume(75)
        assert result["ok"] is True
        assert result["level"] == 75

    @pytest.mark.asyncio
    async def test_set_volume_clamped(self):
        player = _make_player()
        mock_proc = _mock_subprocess()
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.set_volume(150)
        assert result["ok"] is True
        assert result["level"] == 100

    @pytest.mark.asyncio
    async def test_get_volume(self):
        player = _make_player()
        mock_proc = _mock_subprocess(stdout="0.65\n")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await player.get_volume()
        assert result["ok"] is True
        assert result["level"] == 65


# ═══════════════════════════════════════════════════════════════════
# current_track & get_state
# ═══════════════════════════════════════════════════════════════════


class TestMetadata:
    """Track metadata from MPRIS."""

    @pytest.mark.asyncio
    async def test_current_track(self):
        metadata = json.dumps({
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "url": "ytmusic:track:abc",
        })
        player = _make_player()
        mock_proc = _mock_subprocess(stdout=metadata)
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            track = await player.current_track()

        assert track is not None
        assert track.title == "Bohemian Rhapsody"
        assert track.artist == "Queen"
        assert track.source == "ytmusic"

    @pytest.mark.asyncio
    async def test_current_track_none_on_failure(self):
        player = _make_player()
        mock_proc = _mock_subprocess(returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            track = await player.current_track()
        assert track is None

    @pytest.mark.asyncio
    async def test_get_state_playing(self):
        player = _make_player()
        mock_proc = _mock_subprocess(stdout="Playing\n")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            state = await player.get_state()
        assert state == PlayerState.PLAYING

    @pytest.mark.asyncio
    async def test_get_state_paused(self):
        player = _make_player()
        mock_proc = _mock_subprocess(stdout="Paused\n")
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            state = await player.get_state()
        assert state == PlayerState.PAUSED

    @pytest.mark.asyncio
    async def test_get_state_unknown_on_error(self):
        player = _make_player()
        mock_proc = _mock_subprocess(returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            state = await player.get_state()
        assert state == PlayerState.UNKNOWN


# ═══════════════════════════════════════════════════════════════════
# Search via ytmusicapi
# ═══════════════════════════════════════════════════════════════════


class TestSearch:
    """Search functionality via ytmusicapi."""

    @pytest.mark.asyncio
    async def test_search_returns_tracks(self):
        player = _make_player()
        mock_yt = MagicMock()
        mock_yt.search.return_value = [
            {
                "videoId": "abc123",
                "title": "Stairway to Heaven",
                "artists": [{"name": "Led Zeppelin"}],
                "album": {"name": "Led Zeppelin IV"},
                "duration": "8:02",
            },
            {
                "videoId": "def456",
                "title": "Kashmir",
                "artists": [{"name": "Led Zeppelin"}],
                "album": None,
                "duration": "8:37",
            },
        ]
        player._ytmusic = mock_yt
        player._ytmusic_checked = True

        tracks = await player.search("led zeppelin", limit=5)

        assert len(tracks) == 2
        assert tracks[0].title == "Stairway to Heaven"
        assert tracks[0].artist == "Led Zeppelin"
        assert tracks[0].album == "Led Zeppelin IV"
        assert "abc123" in tracks[0].uri
        assert tracks[0].duration_ms == 482_000
        assert tracks[1].album == ""

    @pytest.mark.asyncio
    async def test_search_no_ytmusic(self):
        """Search returns empty when ytmusicapi is not available."""
        player = _make_player()
        player._ytmusic = None
        player._ytmusic_checked = True

        tracks = await player.search("test query")
        assert tracks == []

    @pytest.mark.asyncio
    async def test_search_exception(self):
        """Search returns empty on API error."""
        player = _make_player()
        mock_yt = MagicMock()
        mock_yt.search.side_effect = RuntimeError("API error")
        player._ytmusic = mock_yt
        player._ytmusic_checked = True

        tracks = await player.search("test")
        assert tracks == []


# ═══════════════════════════════════════════════════════════════════
# Playlists
# ═══════════════════════════════════════════════════════════════════


class TestPlaylists:
    """Playlist listing via ytmusicapi."""

    @pytest.mark.asyncio
    async def test_list_playlists(self):
        player = _make_player()
        mock_yt = MagicMock()
        mock_yt.get_library_playlists.return_value = [
            {
                "playlistId": "RDCLAK5uy_k",
                "title": "My Mix",
                "count": 25,
            },
        ]
        player._ytmusic = mock_yt
        player._ytmusic_checked = True

        playlists = await player.list_playlists()

        assert len(playlists) == 1
        assert playlists[0].name == "My Mix"
        assert playlists[0].track_count == 25
        assert "RDCLAK5uy_k" in playlists[0].uri
        assert playlists[0].source == "ytmusic"

    @pytest.mark.asyncio
    async def test_list_playlists_no_ytmusic(self):
        player = _make_player()
        player._ytmusic = None
        player._ytmusic_checked = True

        playlists = await player.list_playlists()
        assert playlists == []


# ═══════════════════════════════════════════════════════════════════
# Play with query (integration-ish)
# ═══════════════════════════════════════════════════════════════════


class TestPlayWithQuery:
    """play(query=...) searches and opens the first result."""

    @pytest.mark.asyncio
    async def test_play_query_opens_first_result(self):
        player = _make_player()
        mock_yt = MagicMock()
        mock_yt.search.return_value = [
            {
                "videoId": "vid1",
                "title": "Test Song",
                "artists": [{"name": "Test Artist"}],
                "album": None,
                "duration": "3:00",
            },
        ]
        player._ytmusic = mock_yt
        player._ytmusic_checked = True

        mock_proc = AsyncMock()
        mock_proc.wait.return_value = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("shutil.which", return_value="/usr/bin/xdg-open"):
            result = await player.play(query="test song")

        assert result["ok"] is True
        assert "vid1" in result["url"]

    @pytest.mark.asyncio
    async def test_play_query_no_results(self):
        player = _make_player()
        mock_yt = MagicMock()
        mock_yt.search.return_value = []
        player._ytmusic = mock_yt
        player._ytmusic_checked = True

        result = await player.play(query="nonexistent")
        assert result["ok"] is False
        assert "No results" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# _get_player integration — YTMusic in priority chain
# ═══════════════════════════════════════════════════════════════════


class TestPlayerFactoryIntegration:
    """_get_player() includes YTMusicPlayer in the priority chain."""

    def test_ytmusic_player_importable(self):
        """YTMusicPlayer is properly exported from the music package."""
        from bantz.skills.music import YTMusicPlayer

        player = YTMusicPlayer()
        assert player.name == "ytmusic"

    def test_player_abc_compliance(self):
        """YTMusicPlayer fully implements MusicPlayer ABC."""
        from bantz.skills.music.player import MusicPlayer

        assert issubclass(YTMusicPlayer, MusicPlayer)
        # If any abstract method is missing, instantiation would fail
        player = YTMusicPlayer()
        assert player is not None
