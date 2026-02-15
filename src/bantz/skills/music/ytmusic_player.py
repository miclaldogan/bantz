"""YouTube Music player backend — ytmusicapi + browser automation.

Issue #1300: EN Localization + YouTube Music Automation.

Uses ``ytmusicapi`` for library/search operations and ``playerctl``
for playback control of YouTube Music in the browser.  Falls back
to opening URLs with ``xdg-open`` when no browser player is active.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any

from bantz.skills.music.player import MusicPlayer, PlayerState, Playlist, Track

logger = logging.getLogger(__name__)


class YTMusicPlayer(MusicPlayer):
    """YouTube Music player backend.

    Control path priority:
    1. ``playerctl -p chromium`` (D-Bus MPRIS — browser tab)
    2. ``ytmusicapi`` for search/library (headless API)
    3. ``xdg-open`` fallback (opens URL in default browser)

    Requires:
    - ytmusicapi: ``pip install ytmusicapi``
    - Optional: browser with MPRIS support (Chromium, Firefox w/ extension)
    - Optional: OAuth setup via ``ytmusicapi oauth``
    """

    def __init__(
        self,
        *,
        auth_file: str | None = None,
        browser_player: str = "chromium",
    ) -> None:
        self._auth_file = auth_file
        self._browser_player = browser_player
        self._playerctl = shutil.which("playerctl")
        self._ytmusic: Any | None = None
        self._ytmusic_checked = False

    @property
    def name(self) -> str:
        return "ytmusic"

    @property
    def available(self) -> bool:
        """Available if ytmusicapi is installed or playerctl can reach browser."""
        return self._get_ytmusic() is not None or self._playerctl is not None

    # ── Playback Control ─────────────────────────────────────────

    async def play(
        self,
        query: str | None = None,
        *,
        playlist: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Play music on YouTube Music."""
        if uri:
            return await self._open_url(uri)

        if query:
            results = await self.search(query, limit=1)
            if results:
                track = results[0]
                if track.uri:
                    return await self._open_url(track.uri)
                return {"ok": False, "error": "No playable URI found"}
            return {"ok": False, "error": f"No results for: {query}"}

        if playlist:
            playlists = await self.list_playlists()
            for pl in playlists:
                if playlist.lower() in pl.name.lower():
                    if pl.uri:
                        return await self._open_url(pl.uri)
                    return {"ok": False, "error": f"Playlist has no URI: {pl.name}"}
            return {"ok": False, "error": f"Playlist not found: {playlist}"}

        # Resume current playback
        return await self._browser_cmd("play")

    async def pause(self) -> dict[str, Any]:
        return await self._browser_cmd("pause")

    async def resume(self) -> dict[str, Any]:
        return await self._browser_cmd("play")

    async def next_track(self) -> dict[str, Any]:
        return await self._browser_cmd("next")

    async def prev_track(self) -> dict[str, Any]:
        return await self._browser_cmd("previous")

    async def stop(self) -> dict[str, Any]:
        return await self._browser_cmd("stop")

    async def set_volume(self, level: int) -> dict[str, Any]:
        level = max(0, min(100, level))
        vol_float = level / 100.0
        result = await self._browser_cmd("volume", str(vol_float))
        if result["ok"]:
            result["level"] = level
        return result

    async def get_volume(self) -> dict[str, Any]:
        result = await self._browser_cmd("volume")
        if result["ok"]:
            try:
                raw = result.get("stdout", "").strip()
                vol = float(raw) if raw else 0.0
                return {"ok": True, "level": int(vol * 100)}
            except (ValueError, TypeError):
                return {"ok": True, "level": -1}
        return result

    async def current_track(self) -> Track | None:
        """Get currently playing track from browser MPRIS metadata."""
        result = await self._browser_cmd(
            "metadata", "--format",
            '{"title":"{{title}}","artist":"{{artist}}",'
            '"album":"{{album}}","url":"{{mpris:trackid}}"}',
        )
        if not result["ok"]:
            return None

        try:
            raw = result.get("stdout", "").strip()
            if not raw:
                return None
            data = json.loads(raw)
            return Track(
                title=data.get("title", ""),
                artist=data.get("artist", ""),
                album=data.get("album", ""),
                uri=data.get("url", ""),
                source="ytmusic",
            )
        except (json.JSONDecodeError, KeyError):
            return None

    async def get_state(self) -> PlayerState:
        result = await self._browser_cmd("status")
        if not result["ok"]:
            return PlayerState.UNKNOWN

        status = result.get("stdout", "").strip().lower()
        state_map = {
            "playing": PlayerState.PLAYING,
            "paused": PlayerState.PAUSED,
            "stopped": PlayerState.STOPPED,
        }
        return state_map.get(status, PlayerState.UNKNOWN)

    # ── Search & Library ─────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[Track]:
        """Search YouTube Music using ytmusicapi."""
        yt = self._get_ytmusic()
        if yt is None:
            return []

        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: yt.search(query, filter="songs", limit=limit),
            )

            tracks: list[Track] = []
            for item in results[:limit]:
                video_id = item.get("videoId", "")
                artists = item.get("artists", [])
                artist_name = artists[0]["name"] if artists else ""
                album_info = item.get("album")
                album_name = album_info["name"] if album_info else ""
                duration_ms = _parse_duration(
                    item.get("duration", "")
                )

                tracks.append(
                    Track(
                        title=item.get("title", ""),
                        artist=artist_name,
                        album=album_name,
                        duration_ms=duration_ms,
                        uri=(
                            f"https://music.youtube.com/watch?v={video_id}"
                            if video_id else ""
                        ),
                        source="ytmusic",
                    )
                )
            return tracks
        except Exception as exc:
            logger.warning("[YTMusic] Search failed: %s", exc)
            return []

    async def list_playlists(self) -> list[Playlist]:
        """List user's YouTube Music playlists."""
        yt = self._get_ytmusic()
        if yt is None:
            return []

        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, yt.get_library_playlists,
            )

            playlists: list[Playlist] = []
            for item in raw:
                playlist_id = item.get("playlistId", "")
                playlists.append(
                    Playlist(
                        name=item.get("title", ""),
                        id=playlist_id,
                        track_count=item.get("count", 0) or 0,
                        uri=(
                            f"https://music.youtube.com/playlist?list={playlist_id}"
                            if playlist_id else ""
                        ),
                        source="ytmusic",
                    )
                )
            return playlists
        except Exception as exc:
            logger.warning("[YTMusic] Playlist fetch failed: %s", exc)
            return []

    # ── Internal ─────────────────────────────────────────────────

    def _get_ytmusic(self) -> Any | None:
        """Lazy-init ytmusicapi client."""
        if self._ytmusic is not None:
            return self._ytmusic
        if self._ytmusic_checked:
            return None

        self._ytmusic_checked = True
        try:
            from ytmusicapi import YTMusic  # type: ignore[import-untyped]

            if self._auth_file:
                self._ytmusic = YTMusic(self._auth_file)
            else:
                # Unauthenticated — search works, library doesn't
                self._ytmusic = YTMusic()
            return self._ytmusic
        except ImportError:
            logger.debug("[YTMusic] ytmusicapi not installed")
            return None
        except Exception as exc:
            logger.warning("[YTMusic] Init failed: %s", exc)
            return None

    async def _browser_cmd(
        self, command: str, *args: str
    ) -> dict[str, Any]:
        """Execute a playerctl command targeting the browser player."""
        if not self._playerctl:
            return {"ok": False, "error": "playerctl is not installed."}

        cmd = [
            "playerctl", "-p", self._browser_player,
            command, *args,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5,
            )
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                return {"ok": True, "stdout": stdout_str}
            return {
                "ok": False,
                "error": stderr_str.strip() or f"playerctl {command} failed",
                "stdout": stdout_str,
            }
        except asyncio.TimeoutError:
            return {"ok": False, "error": "playerctl timed out"}
        except FileNotFoundError:
            return {"ok": False, "error": "playerctl not found"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _open_url(self, url: str) -> dict[str, Any]:
        """Open a YouTube Music URL in the default browser."""
        try:
            xdg_open = shutil.which("xdg-open")
            if not xdg_open:
                return {"ok": False, "error": "xdg-open not found"}

            proc = await asyncio.create_subprocess_exec(
                "xdg-open", url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5)
            return {"ok": True, "action": "opened", "url": url}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def _parse_duration(duration_str: str) -> int:
    """Parse duration string like '3:45' or '1:02:30' to milliseconds."""
    if not duration_str:
        return 0
    try:
        parts = duration_str.split(":")
        if len(parts) == 2:
            minutes, seconds = int(parts[0]), int(parts[1])
            return (minutes * 60 + seconds) * 1000
        if len(parts) == 3:
            hours, minutes, seconds = (
                int(parts[0]),
                int(parts[1]),
                int(parts[2]),
            )
            return (hours * 3600 + minutes * 60 + seconds) * 1000
    except (ValueError, IndexError):
        pass
    return 0
