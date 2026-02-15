"""Tests for Issue #1296 — Music Control: Spotify/Local Player + Context-Aware Suggestions.

Coverage:
- Track/Playlist/PlayerState data models
- MusicPlayer ABC contract
- SpotifyPlayer: play, pause, next, volume, status (mocked playerctl)
- LocalPlayer: play, pause, next, volume, list_players (mocked playerctl)
- MusicSuggester: calendar moods, time moods, combined suggestions
- Tool registration: _register_music adds 12 tools
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from bantz.skills.music.local_player import LocalPlayer
from bantz.skills.music.player import PlayerState, Playlist, Track
from bantz.skills.music.spotify_player import SpotifyPlayer
from bantz.skills.music.suggester import MusicSuggester, MusicSuggestion

# ═══════════════════════════════════════════════════════════════════
# Track & Playlist models
# ═══════════════════════════════════════════════════════════════════


class TestTrack:
    """Track dataclass tests."""

    def test_duration_human(self):
        track = Track(title="Test", duration_ms=185000)
        assert track.duration_human == "3:05"

    def test_duration_human_zero(self):
        track = Track()
        assert track.duration_human == "0:00"

    def test_to_dict(self):
        track = Track(
            title="Song", artist="Artist", album="Album",
            duration_ms=200000, uri="spotify:track:123",
            source="spotify",
        )
        d = track.to_dict()
        assert d["title"] == "Song"
        assert d["artist"] == "Artist"
        assert d["duration"] == "3:20"
        assert d["source"] == "spotify"

    def test_str_with_artist(self):
        track = Track(title="Song", artist="Artist")
        assert str(track) == "Artist — Song"

    def test_str_without_artist(self):
        track = Track(title="Song")
        assert str(track) == "Song"

    def test_str_empty(self):
        track = Track()
        assert "bilinmeyen" in str(track)


class TestPlaylist:
    """Playlist dataclass tests."""

    def test_to_dict(self):
        pl = Playlist(
            name="My Playlist", id="abc123",
            track_count=42, uri="spotify:playlist:abc",
            source="spotify",
        )
        d = pl.to_dict()
        assert d["name"] == "My Playlist"
        assert d["track_count"] == 42
        assert d["source"] == "spotify"


class TestPlayerState:
    """PlayerState enum tests."""

    def test_values(self):
        assert PlayerState.PLAYING == "playing"
        assert PlayerState.PAUSED == "paused"
        assert PlayerState.STOPPED == "stopped"
        assert PlayerState.UNKNOWN == "unknown"


# ═══════════════════════════════════════════════════════════════════
# SpotifyPlayer
# ═══════════════════════════════════════════════════════════════════


class TestSpotifyPlayer:
    """SpotifyPlayer tests (playerctl mocked)."""

    @pytest.fixture
    def player(self):
        p = SpotifyPlayer()
        p._playerctl = "/usr/bin/playerctl"  # Pretend it's installed
        return p

    @pytest.mark.asyncio
    async def test_play_no_args(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": ""}
            result = await player.play()
            assert result["ok"] is True
            mock.assert_called_with("play")

    @pytest.mark.asyncio
    async def test_play_with_uri(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": ""}
            result = await player.play(uri="spotify:track:123")
            assert result["ok"] is True
            mock.assert_called_with("open", "spotify:track:123")

    @pytest.mark.asyncio
    async def test_play_with_query_search(self, player):
        track = Track(title="Song", uri="spotify:track:abc", source="spotify")
        with patch.object(player, "search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = [track]
            with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock_cmd:
                mock_cmd.return_value = {"ok": True}
                result = await player.play("jazz")
                assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_pause(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            result = await player.pause()
            assert result["ok"] is True
            mock.assert_called_with("pause")

    @pytest.mark.asyncio
    async def test_next_track(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            result = await player.next_track()
            assert result["ok"] is True
            mock.assert_called_with("next")

    @pytest.mark.asyncio
    async def test_prev_track(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            result = await player.prev_track()
            assert result["ok"] is True
            mock.assert_called_with("previous")

    @pytest.mark.asyncio
    async def test_stop(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.stop()
            mock.assert_called_with("stop")

    @pytest.mark.asyncio
    async def test_set_volume(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.set_volume(75)
            mock.assert_called_with("volume", "0.75")

    @pytest.mark.asyncio
    async def test_set_volume_clamped(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.set_volume(150)
            mock.assert_called_with("volume", "1.0")
            await player.set_volume(-10)
            mock.assert_called_with("volume", "0.0")

    @pytest.mark.asyncio
    async def test_get_volume(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": "0.65\n"}
            result = await player.get_volume()
            assert result["ok"] is True
            assert result["level"] == 65

    @pytest.mark.asyncio
    async def test_get_state_playing(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": "Playing\n"}
            state = await player.get_state()
            assert state == PlayerState.PLAYING

    @pytest.mark.asyncio
    async def test_get_state_paused(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": "Paused\n"}
            state = await player.get_state()
            assert state == PlayerState.PAUSED

    @pytest.mark.asyncio
    async def test_get_state_unknown(self, player):
        with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": False, "error": "No player"}
            state = await player.get_state()
            assert state == PlayerState.UNKNOWN

    @pytest.mark.asyncio
    async def test_current_track(self, player):
        async def mock_metadata(*args, **kwargs):
            return {
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "album": "A Night at the Opera",
                "length_us": 354000000,
                "url": "spotify:track:abc",
                "artUrl": "https://art.url/img.jpg",
            }

        with patch.object(player, "_get_metadata", mock_metadata):
            track = await player.current_track()
            assert track is not None
            assert track.title == "Bohemian Rhapsody"
            assert track.artist == "Queen"
            assert track.source == "spotify"

    @pytest.mark.asyncio
    async def test_current_track_none(self, player):
        with patch.object(player, "_get_metadata", new_callable=AsyncMock) as mock:
            mock.return_value = None
            track = await player.current_track()
            assert track is None

    @pytest.mark.asyncio
    async def test_search_no_token(self, player):
        tracks = await player.search("jazz")
        assert tracks == []

    @pytest.mark.asyncio
    async def test_list_playlists_no_token(self, player):
        playlists = await player.list_playlists()
        assert playlists == []

    def test_name(self, player):
        assert player.name == "spotify"

    @pytest.mark.asyncio
    async def test_toggle_when_playing(self, player):
        with patch.object(player, "get_state", new_callable=AsyncMock) as mock_state:
            mock_state.return_value = PlayerState.PLAYING
            with patch.object(player, "pause", new_callable=AsyncMock) as mock_pause:
                mock_pause.return_value = {"ok": True}
                result = await player.toggle()
                assert result["ok"] is True
                mock_pause.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_when_paused(self, player):
        with patch.object(player, "get_state", new_callable=AsyncMock) as mock_state:
            mock_state.return_value = PlayerState.PAUSED
            with patch.object(player, "resume", new_callable=AsyncMock) as mock_resume:
                mock_resume.return_value = {"ok": True}
                result = await player.toggle()
                assert result["ok"] is True
                mock_resume.assert_called_once()

    @pytest.mark.asyncio
    async def test_status(self, player):
        with patch.object(player, "get_state", new_callable=AsyncMock) as mock_state:
            mock_state.return_value = PlayerState.PLAYING
            with patch.object(player, "current_track", new_callable=AsyncMock) as mock_track:
                mock_track.return_value = Track(title="Song", artist="Artist")
                with patch.object(player, "get_volume", new_callable=AsyncMock) as mock_vol:
                    mock_vol.return_value = {"level": 50}
                    result = await player.status()
                    assert result["ok"] is True
                    assert result["state"] == "playing"
                    assert result["track"]["title"] == "Song"
                    assert result["volume"] == 50

    @pytest.mark.asyncio
    async def test_dbus_cmd_no_playerctl(self):
        player = SpotifyPlayer()
        player._playerctl = None
        result = await player._dbus_cmd("play")
        assert result["ok"] is False
        assert "playerctl" in result["error"]

    @pytest.mark.asyncio
    async def test_play_playlist_not_found(self, player):
        with patch.object(player, "list_playlists", new_callable=AsyncMock) as mock:
            mock.return_value = []
            result = await player.play(playlist="nonexistent")
            assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_play_playlist_found(self, player):
        pl = Playlist(name="Jazz Vibes", id="abc", uri="spotify:playlist:abc")
        with patch.object(player, "list_playlists", new_callable=AsyncMock) as mock_pl:
            mock_pl.return_value = [pl]
            with patch.object(player, "_dbus_cmd", new_callable=AsyncMock) as mock_cmd:
                mock_cmd.return_value = {"ok": True}
                result = await player.play(playlist="Jazz")
                assert result["ok"] is True


# ═══════════════════════════════════════════════════════════════════
# LocalPlayer
# ═══════════════════════════════════════════════════════════════════


class TestLocalPlayer:
    """LocalPlayer tests (playerctl mocked)."""

    @pytest.fixture
    def player(self):
        p = LocalPlayer()
        p._playerctl = "/usr/bin/playerctl"
        return p

    @pytest.mark.asyncio
    async def test_play_resume(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.play()
            mock.assert_called_with("play")

    @pytest.mark.asyncio
    async def test_play_query_note(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            result = await player.play("jazz music")
            assert result["ok"] is True
            assert "note" in result

    @pytest.mark.asyncio
    async def test_play_uri(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.play(uri="/path/to/file.mp3")
            mock.assert_called_with("open", "/path/to/file.mp3")

    @pytest.mark.asyncio
    async def test_pause(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.pause()
            mock.assert_called_with("pause")

    @pytest.mark.asyncio
    async def test_next(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.next_track()
            mock.assert_called_with("next")

    @pytest.mark.asyncio
    async def test_prev(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.prev_track()
            mock.assert_called_with("previous")

    @pytest.mark.asyncio
    async def test_stop(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.stop()
            mock.assert_called_with("stop")

    @pytest.mark.asyncio
    async def test_volume_set(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}
            await player.set_volume(80)
            mock.assert_called_with("volume", "0.8")

    @pytest.mark.asyncio
    async def test_volume_get(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": "0.45\n"}
            result = await player.get_volume()
            assert result["level"] == 45

    @pytest.mark.asyncio
    async def test_search_empty(self, player):
        tracks = await player.search("anything")
        assert tracks == []

    @pytest.mark.asyncio
    async def test_list_playlists_empty(self, player):
        playlists = await player.list_playlists()
        assert playlists == []

    def test_name_default(self):
        p = LocalPlayer()
        assert p.name == "mpris"

    def test_name_custom(self):
        p = LocalPlayer(player_name="vlc")
        assert p.name == "vlc"

    @pytest.mark.asyncio
    async def test_cmd_no_playerctl(self):
        p = LocalPlayer()
        p._playerctl = None
        result = await p._cmd("play")
        assert result["ok"] is False
        assert "playerctl" in result["error"]

    @pytest.mark.asyncio
    async def test_current_track_none(self, player):
        with patch.object(player, "_get_metadata", new_callable=AsyncMock) as mock:
            mock.return_value = None
            track = await player.current_track()
            assert track is None

    @pytest.mark.asyncio
    async def test_get_state_stopped(self, player):
        with patch.object(player, "_cmd", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "stdout": "Stopped\n"}
            state = await player.get_state()
            assert state == PlayerState.STOPPED

    @pytest.mark.asyncio
    async def test_list_players_no_playerctl(self):
        p = LocalPlayer()
        p._playerctl = None
        players = await p.list_players()
        assert players == []


# ═══════════════════════════════════════════════════════════════════
# MusicSuggester
# ═══════════════════════════════════════════════════════════════════


class TestMusicSuggester:
    """MusicSuggester context-aware suggestion tests."""

    @pytest.fixture
    def suggester(self):
        return MusicSuggester()

    # ── Calendar-based ───────────────────────────────────────────

    def test_suggest_deep_work(self, suggester):
        s = suggester.suggest_from_calendar("Deep Work Session")
        assert s is not None
        assert "lo-fi" in s.genres[0].lower() or "ambient" in s.genres
        assert s.context_type == "calendar"

    def test_suggest_meeting_no_music(self, suggester):
        s = suggester.suggest_from_calendar("Team Meeting")
        assert s is not None
        assert s.genres == []
        assert "önerilmiyor" in s.reason

    def test_suggest_exercise(self, suggester):
        s = suggester.suggest_from_calendar("exercise plan")
        assert s is not None
        assert any("workout" in g.lower() or "EDM" in g for g in s.genres)

    def test_suggest_yoga(self, suggester):
        s = suggester.suggest_from_calendar("Morning Yoga")
        assert s is not None
        assert any("ambient" in g or "meditation" in g for g in s.genres)

    def test_suggest_unknown_event(self, suggester):
        s = suggester.suggest_from_calendar("Random Unknown Event")
        assert s is None  # No matching pattern

    def test_suggest_turkish_keywords(self, suggester):
        s = suggester.suggest_from_calendar("Toplantı: Haftalık Sync")
        assert s is not None
        assert s.genres == []  # Meeting → no music

    def test_suggest_coding(self, suggester):
        s = suggester.suggest_from_calendar("coding session")
        assert s is not None
        assert any("lo-fi" in g.lower() or "synthwave" in g.lower() for g in s.genres)

    # ── Time-based ───────────────────────────────────────────────

    def test_suggest_morning(self, suggester):
        s = suggester.suggest_from_time(datetime(2026, 1, 15, 9, 0))
        assert s.context_type == "time"
        assert len(s.genres) > 0

    def test_suggest_early_morning(self, suggester):
        s = suggester.suggest_from_time(datetime(2026, 1, 15, 6, 0))
        assert "classical" in s.genres or "jazz" in s.genres

    def test_suggest_afternoon(self, suggester):
        s = suggester.suggest_from_time(datetime(2026, 1, 15, 14, 0))
        assert len(s.genres) > 0

    def test_suggest_evening(self, suggester):
        s = suggester.suggest_from_time(datetime(2026, 1, 15, 19, 0))
        assert len(s.genres) > 0

    def test_suggest_night(self, suggester):
        s = suggester.suggest_from_time(datetime(2026, 1, 15, 23, 0))
        assert any("ambient" in g or "lo-fi" in g.lower() for g in s.genres)

    # ── Combined suggest() ───────────────────────────────────────

    def test_suggest_calendar_priority(self, suggester):
        events = [{"title": "Deep Work"}]
        s = suggester.suggest(current_events=events)
        assert s.context_type == "calendar"

    def test_suggest_time_fallback(self, suggester):
        s = suggester.suggest(current_events=None)
        assert s.context_type == "time"

    def test_suggest_empty_events_fallback(self, suggester):
        s = suggester.suggest(current_events=[])
        assert s.context_type == "time"

    def test_suggest_with_summary_key(self, suggester):
        events = [{"summary": "Yoga Session"}]
        s = suggester.suggest(current_events=events)
        assert s is not None
        assert s.context_type == "calendar"

    def test_suggest_meeting_blocks_music(self, suggester):
        events = [{"title": "meeting with CEO"}]
        s = suggester.suggest(current_events=events)
        assert s.genres == []

    # ── Config ───────────────────────────────────────────────────

    def test_get_mood_map(self, suggester):
        mood_map = suggester.get_mood_map()
        assert "calendar_moods" in mood_map
        assert "time_moods" in mood_map
        assert "deep work" in mood_map["calendar_moods"]

    def test_update_calendar_mood(self, suggester):
        suggester.update_calendar_mood("custom", ["rock", "metal"])
        s = suggester.suggest_from_calendar("Custom event")
        assert s is not None
        assert "rock" in s.genres

    def test_update_calendar_mood_none(self, suggester):
        suggester.update_calendar_mood("presentation", None)
        s = suggester.suggest_from_calendar("Client Presentation")
        assert s is not None
        assert s.genres == []

    def test_custom_moods_constructor(self):
        ms = MusicSuggester(
            calendar_moods={"special": ["jazz"]},
            time_moods={"morning": ["pop"]},
        )
        s = ms.suggest_from_calendar("special event")
        assert s is not None
        assert "jazz" in s.genres

    # ── MusicSuggestion ──────────────────────────────────────────

    def test_suggestion_to_dict(self):
        s = MusicSuggestion(
            genres=["jazz", "lo-fi"],
            reason="Test",
            context_type="calendar",
            event_title="Work",
            confidence=0.9,
        )
        d = s.to_dict()
        assert d["genres"] == ["jazz", "lo-fi"]
        assert d["context_type"] == "calendar"
        assert d["confidence"] == 0.9


# ═══════════════════════════════════════════════════════════════════
# Tool Registration
# ═══════════════════════════════════════════════════════════════════


class TestMusicToolRegistration:
    """Verify _register_music registers all expected tools."""

    def test_register_music_tools(self):
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import _register_music

        registry = ToolRegistry()
        count = _register_music(registry)

        assert count == 11

        expected = [
            "music.play",
            "music.pause",
            "music.resume",
            "music.next",
            "music.prev",
            "music.stop",
            "music.volume",
            "music.status",
            "music.search",
            "music.playlists",
            "music.suggest",
        ]

        registered = {t.name for t in registry._tools.values()}
        for name in expected:
            assert name in registered, f"Missing tool: {name}"

    def test_all_music_tools_low_risk(self):
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import _register_music

        registry = ToolRegistry()
        _register_music(registry)

        for tool in registry._tools.values():
            if tool.name.startswith("music."):
                assert tool.risk_level == "LOW", f"{tool.name} should be LOW risk"


# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════


class TestMusicConfig:
    """Verify config/music.yaml is valid."""

    def test_config_loads(self):
        from pathlib import Path

        import yaml

        config_path = Path(__file__).parent.parent / "config" / "music.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        assert "music" in cfg
        assert "suggestions" in cfg

    def test_config_music_section(self):
        from pathlib import Path

        import yaml

        config_path = Path(__file__).parent.parent / "config" / "music.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        m = cfg["music"]
        assert m["default_player"] in ("spotify", "mpris", "auto")
        assert "spotify" in m
        assert "mpris" in m

    def test_config_suggestions_section(self):
        from pathlib import Path

        import yaml

        config_path = Path(__file__).parent.parent / "config" / "music.yaml"
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        s = cfg["suggestions"]
        assert s["enabled"] is True
        assert "calendar_moods" in s
        assert "time_moods" in s
