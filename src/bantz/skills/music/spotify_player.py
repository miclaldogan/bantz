"""Spotify player backend — Spotify Web API + local CLI.

Issue #1296: Music Control — Spotify Web API integration.

Uses ``spotify`` (spotify-cli) or ``playerctl`` for control,
and the Spotify Web API for search/playlists when credentials
are available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from typing import Any

from bantz.skills.music.player import MusicPlayer, PlayerState, Playlist, Track

logger = logging.getLogger(__name__)

# Spotify Web API base (used if we have a token)
_SPOTIFY_API = "https://api.spotify.com/v1"


class SpotifyPlayer(MusicPlayer):
    """Spotify player backend.

    Control path priority:
    1. ``playerctl -p spotify`` (D-Bus MPRIS — fast, local)
    2. ``spotify`` CLI (spotify-tui or spotify-player)
    3. Spotify Web API (requires OAuth token)
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
    ) -> None:
        self._token = access_token
        self._playerctl = shutil.which("playerctl")
        self._spotify_cli = shutil.which("spotify")

    @property
    def name(self) -> str:
        return "spotify"

    @property
    def available(self) -> bool:
        """Spotify is available if playerctl can reach it or CLI exists."""
        if self._playerctl:
            try:
                result = subprocess.run(
                    ["playerctl", "-p", "spotify", "status"],
                    capture_output=True, text=True, timeout=3,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return self._spotify_cli is not None

    # ── Playback ─────────────────────────────────────────────────

    async def play(
        self,
        query: str | None = None,
        *,
        playlist: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        if uri:
            return await self._dbus_cmd("open", uri)

        if query:
            # Search and play first result
            tracks = await self.search(query, limit=1)
            if tracks and tracks[0].uri:
                return await self._dbus_cmd("open", tracks[0].uri)
            # Fallback: just hit play (resumes or starts)
            return await self._dbus_cmd("play")

        if playlist:
            playlists = await self.list_playlists()
            for pl in playlists:
                if playlist.lower() in pl.name.lower():
                    return await self._dbus_cmd("open", pl.uri)
            return {"ok": False, "error": f"Playlist not found: {playlist}"}

        return await self._dbus_cmd("play")

    async def pause(self) -> dict[str, Any]:
        return await self._dbus_cmd("pause")

    async def resume(self) -> dict[str, Any]:
        return await self._dbus_cmd("play")

    async def next_track(self) -> dict[str, Any]:
        return await self._dbus_cmd("next")

    async def prev_track(self) -> dict[str, Any]:
        return await self._dbus_cmd("previous")

    async def stop(self) -> dict[str, Any]:
        return await self._dbus_cmd("stop")

    async def set_volume(self, level: int) -> dict[str, Any]:
        clamped = max(0, min(100, level))
        vol_float = clamped / 100.0
        return await self._dbus_cmd("volume", str(vol_float))

    async def get_volume(self) -> dict[str, Any]:
        result = await self._dbus_cmd("volume")
        if result["ok"] and result.get("stdout"):
            try:
                vol = float(result["stdout"].strip())
                return {"ok": True, "level": int(vol * 100)}
            except ValueError:
                pass
        return {"ok": True, "level": -1}

    async def current_track(self) -> Track | None:
        try:
            meta = await self._get_metadata()
            if not meta:
                return None
            return Track(
                title=meta.get("title", ""),
                artist=meta.get("artist", ""),
                album=meta.get("album", ""),
                duration_ms=meta.get("length_us", 0) // 1000,
                uri=meta.get("url", ""),
                art_url=meta.get("artUrl", ""),
                source="spotify",
            )
        except Exception as exc:
            logger.debug("[Spotify] Failed to get track: %s", exc)
            return None

    async def get_state(self) -> PlayerState:
        result = await self._dbus_cmd("status")
        if result["ok"]:
            status = result.get("stdout", "").strip().lower()
            if status == "playing":
                return PlayerState.PLAYING
            if status == "paused":
                return PlayerState.PAUSED
            if status == "stopped":
                return PlayerState.STOPPED
        return PlayerState.UNKNOWN

    async def search(
        self, query: str, *, limit: int = 10
    ) -> list[Track]:
        """Search Spotify for tracks.

        Uses Spotify Web API if token available, otherwise returns empty.
        """
        if not self._token:
            logger.debug("[Spotify] No API token — search unavailable")
            return []

        try:
            import urllib.parse
            import urllib.request

            encoded = urllib.parse.quote(query)
            url = f"{_SPOTIFY_API}/search?q={encoded}&type=track&limit={limit}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
            )

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10),
            )
            data = json.loads(response.read().decode("utf-8"))

            tracks: list[Track] = []
            for item in data.get("tracks", {}).get("items", []):
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                tracks.append(Track(
                    title=item.get("name", ""),
                    artist=artists,
                    album=item.get("album", {}).get("name", ""),
                    duration_ms=item.get("duration_ms", 0),
                    uri=item.get("uri", ""),
                    art_url=(item.get("album", {}).get("images", [{}])[0].get("url", "")
                             if item.get("album", {}).get("images") else ""),
                    source="spotify",
                ))
            return tracks

        except Exception as exc:
            logger.warning("[Spotify] Search failed: %s", exc)
            return []

    async def list_playlists(self) -> list[Playlist]:
        """List user's Spotify playlists (requires API token)."""
        if not self._token:
            return []

        try:
            import urllib.request

            url = f"{_SPOTIFY_API}/me/playlists?limit=50"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
            )

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=10),
            )
            data = json.loads(response.read().decode("utf-8"))

            playlists: list[Playlist] = []
            for item in data.get("items", []):
                playlists.append(Playlist(
                    name=item.get("name", ""),
                    id=item.get("id", ""),
                    track_count=item.get("tracks", {}).get("total", 0),
                    uri=item.get("uri", ""),
                    source="spotify",
                ))
            return playlists

        except Exception as exc:
            logger.warning("[Spotify] Playlist fetch failed: %s", exc)
            return []

    # ── Internal ─────────────────────────────────────────────────

    async def _dbus_cmd(self, command: str, *args: str) -> dict[str, Any]:
        """Execute a playerctl command targeting Spotify."""
        if not self._playerctl:
            return {"ok": False, "error": "playerctl is not installed."}

        cmd = ["playerctl", "-p", "spotify", command, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5
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

    async def _get_metadata(self) -> dict[str, str] | None:
        """Get track metadata via playerctl."""
        fields = {
            "title": "xesam:title",
            "artist": "xesam:artist",
            "album": "xesam:album",
            "url": "xesam:url",
            "artUrl": "mpris:artUrl",
            "length_us": "mpris:length",
        }

        metadata: dict[str, Any] = {}
        for key, mpris_key in fields.items():
            result = await self._dbus_cmd(
                "metadata", mpris_key
            )
            if result["ok"]:
                val = result.get("stdout", "").strip()
                if key == "length_us":
                    try:
                        metadata[key] = int(val)
                    except ValueError:
                        metadata[key] = 0
                else:
                    metadata[key] = val

        return metadata if metadata.get("title") else None
