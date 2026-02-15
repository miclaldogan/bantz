"""Local MPRIS player backend — VLC, mpv, Rhythmbox, etc.

Issue #1296: Müzik Kontrolü — D-Bus MPRIS protocol for local players.

Uses ``playerctl`` to communicate with any MPRIS2-compatible media player
on the Linux desktop (VLC, mpv, Rhythmbox, Audacious, Lollypop, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

from bantz.skills.music.player import MusicPlayer, PlayerState, Playlist, Track

logger = logging.getLogger(__name__)


class LocalPlayer(MusicPlayer):
    """MPRIS2-compatible local media player (via playerctl).

    Detects the first active player automatically, or can target
    a specific player via the ``player_name`` parameter.
    """

    def __init__(self, player_name: str | None = None) -> None:
        self._player_name = player_name
        self._playerctl = shutil.which("playerctl")

    @property
    def name(self) -> str:
        return self._player_name or "mpris"

    @property
    def available(self) -> bool:
        if not self._playerctl:
            return False
        try:
            import subprocess

            result = subprocess.run(
                ["playerctl", "--list-all"],
                capture_output=True, text=True, timeout=3,
            )
            players = result.stdout.strip().split("\n")
            players = [p.strip() for p in players if p.strip()]

            if self._player_name:
                return any(
                    self._player_name.lower() in p.lower() for p in players
                )
            # Any non-spotify player available?
            return any(
                "spotify" not in p.lower() for p in players
            )
        except (FileNotFoundError, Exception):
            return False

    # ── Playback ─────────────────────────────────────────────────

    async def play(
        self,
        query: str | None = None,
        *,
        playlist: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        if uri:
            return await self._cmd("open", uri)

        if query:
            # Local players can't search — just resume or show message
            result = await self._cmd("play")
            if result["ok"]:
                result["note"] = (
                    f"Yerel player aramayı desteklemiyor. "
                    f"Çalma devam ettiriliyor. Aranan: {query}"
                )
            return result

        return await self._cmd("play")

    async def pause(self) -> dict[str, Any]:
        return await self._cmd("pause")

    async def resume(self) -> dict[str, Any]:
        return await self._cmd("play")

    async def next_track(self) -> dict[str, Any]:
        return await self._cmd("next")

    async def prev_track(self) -> dict[str, Any]:
        return await self._cmd("previous")

    async def stop(self) -> dict[str, Any]:
        return await self._cmd("stop")

    async def set_volume(self, level: int) -> dict[str, Any]:
        clamped = max(0, min(100, level))
        vol_float = clamped / 100.0
        return await self._cmd("volume", str(vol_float))

    async def get_volume(self) -> dict[str, Any]:
        result = await self._cmd("volume")
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
                source=self.name,
            )
        except Exception as exc:
            logger.debug("[LocalPlayer] Failed to get track: %s", exc)
            return None

    async def get_state(self) -> PlayerState:
        result = await self._cmd("status")
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
        """Local MPRIS players don't support search."""
        return []

    async def list_playlists(self) -> list[Playlist]:
        """Local MPRIS players don't expose playlist APIs."""
        return []

    # ── Extra: List available players ────────────────────────────

    async def list_players(self) -> list[str]:
        """List all active MPRIS players on the system."""
        if not self._playerctl:
            return []
        try:
            proc = await asyncio.create_subprocess_exec(
                "playerctl", "--list-all",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            lines = stdout.decode("utf-8", errors="replace").strip().split("\n")
            return [p.strip() for p in lines if p.strip()]
        except Exception:
            return []

    # ── Internal ─────────────────────────────────────────────────

    async def _cmd(self, command: str, *args: str) -> dict[str, Any]:
        """Execute a playerctl command."""
        if not self._playerctl:
            return {"ok": False, "error": "playerctl kurulu değil."}

        cmd = ["playerctl"]
        if self._player_name:
            cmd.extend(["-p", self._player_name])
        cmd.append(command)
        cmd.extend(args)

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
                "error": stderr_str.strip() or f"playerctl {command} başarısız",
                "stdout": stdout_str,
            }
        except asyncio.TimeoutError:
            return {"ok": False, "error": "playerctl zaman aşımı"}
        except FileNotFoundError:
            return {"ok": False, "error": "playerctl bulunamadı"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _get_metadata(self) -> dict[str, Any] | None:
        """Get metadata via playerctl."""
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
            result = await self._cmd("metadata", mpris_key)
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
