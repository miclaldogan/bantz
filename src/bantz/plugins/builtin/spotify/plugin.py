"""
Spotify Plugin for Bantz.

Provides Spotify music control:
- Play/pause music
- Skip tracks
- Search and play
- Volume control
- Get current track info
"""

from typing import Any, Dict, List, Optional
import logging

from bantz.plugins.base import (
    BantzPlugin,
    PluginMetadata,
    PluginPermission,
    Tool,
    ToolParameter,
    IntentPattern,
)

logger = logging.getLogger(__name__)


class SpotifyPlugin(BantzPlugin):
    """
    Spotify music control plugin.
    
    Provides intents and tools for controlling Spotify playback.
    Requires Spotify API credentials in config.
    """
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="spotify",
            version="1.0.0",
            author="Bantz",
            description="Spotify müzik kontrolü - oynat, duraklat, sonraki/önceki şarkı",
            permissions=[PluginPermission.NETWORK],
            tags=["music", "spotify", "media", "entertainment"],
            homepage="https://bantz.dev/plugins/spotify",
            repository="https://github.com/bantz/plugin-spotify",
            icon="🎵",
        )
    
    def get_intents(self) -> List[IntentPattern]:
        return [
            # Play music
            IntentPattern(
                pattern=r"müzik (aç|çal|başlat|oynat)",
                intent="play",
                priority=60,
                examples=["müzik aç", "müzik çal", "müziği başlat"],
            ),
            IntentPattern(
                pattern=r"spotify'[ıi] (aç|başlat)",
                intent="play",
                priority=70,
                examples=["spotify'ı aç", "spotify'ı başlat"],
            ),
            # Pause music
            IntentPattern(
                pattern=r"müziği (durdur|duraklat|kapat)",
                intent="pause",
                priority=60,
                examples=["müziği durdur", "müziği duraklat"],
            ),
            IntentPattern(
                pattern=r"(pause|duraklat)",
                intent="pause",
                priority=50,
                examples=["pause", "duraklat"],
            ),
            # Next track
            IntentPattern(
                pattern=r"(sonraki|next) (şarkı|parça|track)",
                intent="next",
                priority=60,
                examples=["sonraki şarkı", "next track"],
            ),
            IntentPattern(
                pattern=r"şarkıyı (geç|atla)",
                intent="next",
                priority=55,
                examples=["şarkıyı geç", "şarkıyı atla"],
            ),
            # Previous track
            IntentPattern(
                pattern=r"(önceki|previous) (şarkı|parça|track)",
                intent="previous",
                priority=60,
                examples=["önceki şarkı", "previous track"],
            ),
            # Search and play
            IntentPattern(
                pattern=r"(.+) (çal|oynat)$",
                intent="search_play",
                priority=40,
                examples=["coldplay çal", "rock müzik oynat"],
                slots={"query": "string"},
            ),
            IntentPattern(
                pattern=r"(çal|oynat) (.+)",
                intent="search_play",
                priority=45,
                examples=["çal metallica", "oynat jazz"],
                slots={"query": "string"},
            ),
            # Volume
            IntentPattern(
                pattern=r"ses(i)? (aç|yükselt|arttır)",
                intent="volume_up",
                priority=55,
                examples=["sesi aç", "sesi yükselt"],
            ),
            IntentPattern(
                pattern=r"ses(i)? (kıs|azalt|düşür)",
                intent="volume_down",
                priority=55,
                examples=["sesi kıs", "sesi azalt"],
            ),
            IntentPattern(
                pattern=r"ses(i)? (%?\d+)",
                intent="set_volume",
                priority=60,
                examples=["sesi 50", "ses %80"],
                slots={"volume": "number"},
            ),
            # Current track info
            IntentPattern(
                pattern=r"(şu an|şimdi) (ne|hangi) (çalıyor|çalan)",
                intent="current_track",
                priority=50,
                examples=["şu an ne çalıyor", "şimdi hangi şarkı çalan"],
            ),
            IntentPattern(
                pattern=r"bu şarkı (ne|nedir|kim)",
                intent="current_track",
                priority=55,
                examples=["bu şarkı ne", "bu şarkı kim"],
            ),
            # Shuffle
            IntentPattern(
                pattern=r"karıştır|shuffle",
                intent="shuffle",
                priority=50,
                examples=["karıştır", "shuffle"],
            ),
            # Repeat
            IntentPattern(
                pattern=r"tekrarla|repeat",
                intent="repeat",
                priority=50,
                examples=["tekrarla", "repeat"],
            ),
            # Like
            IntentPattern(
                pattern=r"(bu şarkıyı )?(beğen|favori|kaydet)",
                intent="like",
                priority=55,
                examples=["beğen", "bu şarkıyı kaydet"],
            ),
        ]
    
    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="play",
                description="Spotify'da müzik çalmaya başla",
                function=self.play,
                parameters=[
                    ToolParameter(
                        name="query",
                        description="Aranacak şarkı/artist/playlist (opsiyonel)",
                        required=False,
                    ),
                    ToolParameter(
                        name="uri",
                        description="Spotify URI (opsiyonel)",
                        required=False,
                    ),
                ],
                examples=["müzik aç", "coldplay çal"],
            ),
            Tool(
                name="pause",
                description="Müziği duraklat",
                function=self.pause,
                examples=["müziği durdur", "pause"],
            ),
            Tool(
                name="next_track",
                description="Sonraki şarkıya geç",
                function=self.next_track,
                examples=["sonraki şarkı", "şarkıyı geç"],
            ),
            Tool(
                name="previous_track",
                description="Önceki şarkıya dön",
                function=self.previous_track,
                examples=["önceki şarkı"],
            ),
            Tool(
                name="get_current_track",
                description="Şu an çalan şarkı bilgisini getir",
                function=self.get_current_track,
                examples=["şu an ne çalıyor", "bu şarkı ne"],
            ),
            Tool(
                name="search",
                description="Spotify'da arama yap",
                function=self.search,
                parameters=[
                    ToolParameter(
                        name="query",
                        description="Arama sorgusu",
                        required=True,
                    ),
                    ToolParameter(
                        name="type",
                        description="Arama tipi",
                        enum=["track", "artist", "album", "playlist"],
                        default="track",
                    ),
                    ToolParameter(
                        name="limit",
                        description="Sonuç limiti",
                        type="number",
                        default=5,
                    ),
                ],
            ),
            Tool(
                name="set_volume",
                description="Ses seviyesini ayarla",
                function=self.set_volume,
                parameters=[
                    ToolParameter(
                        name="volume",
                        description="Ses seviyesi (0-100)",
                        type="number",
                        required=True,
                    ),
                ],
            ),
            Tool(
                name="toggle_shuffle",
                description="Karıştırmayı aç/kapat",
                function=self.toggle_shuffle,
            ),
            Tool(
                name="toggle_repeat",
                description="Tekrarlamayı aç/kapat",
                function=self.toggle_repeat,
            ),
            Tool(
                name="like_track",
                description="Şu anki şarkıyı beğen/kaydet",
                function=self.like_track,
            ),
        ]
    
    def on_load(self) -> None:
        """Initialize Spotify connection."""
        self._logger.info("Spotify plugin loading...")
        
        # Get credentials from config
        self._client_id = self.config.get("client_id", "")
        self._client_secret = self.config.get("client_secret", "")
        self._redirect_uri = self.config.get("redirect_uri", "http://localhost:8888/callback")
        
        # Mock: In real implementation, would initialize spotipy client
        self._sp = None  # Would be spotipy.Spotify(...)
        self._connected = False
        
        if self._client_id and self._client_secret:
            self._logger.info("Spotify credentials found, ready to connect")
        else:
            self._logger.warning("Spotify credentials not configured")
    
    def on_unload(self) -> None:
        """Cleanup Spotify connection."""
        self._sp = None
        self._connected = False
        self._logger.info("Spotify plugin unloaded")
    
    def on_config_change(self, key: str, value: Any) -> None:
        """Handle config changes."""
        if key in ("client_id", "client_secret"):
            self._logger.info("Spotify credentials changed, reconnecting...")
            self.on_load()
    
    # ==========================================================================
    # Tool Implementations
    # ==========================================================================
    
    def play(self, query: Optional[str] = None, uri: Optional[str] = None) -> Dict[str, Any]:
        """Start or resume playback."""
        self._ensure_connected()
        
        if uri:
            # Play specific URI
            return {
                "success": True,
                "action": "play",
                "uri": uri,
                "message": f"Çalıyor: {uri}",
            }
        elif query:
            # Search and play
            results = self.search(query, type="track", limit=1)
            if results.get("tracks"):
                track = results["tracks"][0]
                return {
                    "success": True,
                    "action": "play",
                    "track": track,
                    "message": f"Çalıyor: {track['name']} - {track['artist']}",
                }
            else:
                return {
                    "success": False,
                    "error": f"'{query}' bulunamadı",
                }
        else:
            # Resume playback
            return {
                "success": True,
                "action": "resume",
                "message": "Çalmaya devam ediyor",
            }
    
    def pause(self) -> Dict[str, Any]:
        """Pause playback."""
        self._ensure_connected()
        
        return {
            "success": True,
            "action": "pause",
            "message": "Müzik duraklatıldı",
        }
    
    def next_track(self) -> Dict[str, Any]:
        """Skip to next track."""
        self._ensure_connected()
        
        # Mock: Would call sp.next_track()
        return {
            "success": True,
            "action": "next",
            "message": "Sonraki şarkıya geçildi",
        }
    
    def previous_track(self) -> Dict[str, Any]:
        """Skip to previous track."""
        self._ensure_connected()
        
        return {
            "success": True,
            "action": "previous",
            "message": "Önceki şarkıya dönüldü",
        }
    
    def get_current_track(self) -> Dict[str, Any]:
        """Get currently playing track info."""
        self._ensure_connected()
        
        # Mock data
        return {
            "success": True,
            "playing": True,
            "track": {
                "name": "Bohemian Rhapsody",
                "artist": "Queen",
                "album": "A Night at the Opera",
                "duration_ms": 354000,
                "progress_ms": 120000,
                "uri": "spotify:track:7tFiyTwD0nx5a1eklYtX2J",
            },
            "message": "Şu an çalan: Bohemian Rhapsody - Queen",
        }
    
    def search(
        self,
        query: str,
        type: str = "track",
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Search Spotify."""
        self._ensure_connected()
        
        # Mock data
        if type == "track":
            return {
                "success": True,
                "type": type,
                "query": query,
                "tracks": [
                    {
                        "name": f"Track result for '{query}'",
                        "artist": "Artist Name",
                        "album": "Album Name",
                        "uri": "spotify:track:xxx",
                    },
                ],
            }
        elif type == "artist":
            return {
                "success": True,
                "type": type,
                "query": query,
                "artists": [
                    {
                        "name": f"Artist result for '{query}'",
                        "uri": "spotify:artist:xxx",
                    },
                ],
            }
        else:
            return {
                "success": True,
                "type": type,
                "query": query,
                "results": [],
            }
    
    def set_volume(self, volume: int) -> Dict[str, Any]:
        """Set playback volume."""
        self._ensure_connected()
        
        volume = max(0, min(100, volume))
        
        return {
            "success": True,
            "action": "volume",
            "volume": volume,
            "message": f"Ses seviyesi: %{volume}",
        }
    
    def toggle_shuffle(self) -> Dict[str, Any]:
        """Toggle shuffle mode."""
        self._ensure_connected()
        
        return {
            "success": True,
            "action": "shuffle",
            "shuffle": True,  # Would toggle actual state
            "message": "Karıştırma açıldı",
        }
    
    def toggle_repeat(self) -> Dict[str, Any]:
        """Toggle repeat mode."""
        self._ensure_connected()
        
        return {
            "success": True,
            "action": "repeat",
            "repeat": "track",  # off, track, context
            "message": "Tekrarlama: Şarkı",
        }
    
    def like_track(self) -> Dict[str, Any]:
        """Like/save current track."""
        self._ensure_connected()
        
        current = self.get_current_track()
        if not current.get("playing"):
            return {
                "success": False,
                "error": "Şu an çalan şarkı yok",
            }
        
        return {
            "success": True,
            "action": "like",
            "track": current["track"],
            "message": f"'{current['track']['name']}' beğenildi",
        }
    
    # ==========================================================================
    # Intent Handlers
    # ==========================================================================
    
    def handle_play(self, **slots) -> str:
        """Handle play intent."""
        result = self.play(query=slots.get("query"))
        return result.get("message", "Müzik başlatıldı")
    
    def handle_pause(self, **slots) -> str:
        """Handle pause intent."""
        result = self.pause()
        return result.get("message", "Müzik duraklatıldı")
    
    def handle_next(self, **slots) -> str:
        """Handle next intent."""
        result = self.next_track()
        return result.get("message", "Sonraki şarkı")
    
    def handle_previous(self, **slots) -> str:
        """Handle previous intent."""
        result = self.previous_track()
        return result.get("message", "Önceki şarkı")
    
    def handle_search_play(self, query: str = "", **slots) -> str:
        """Handle search and play intent."""
        if not query:
            query = slots.get("query", "")
        result = self.play(query=query)
        return result.get("message", f"'{query}' çalınıyor")
    
    def handle_volume_up(self, **slots) -> str:
        """Handle volume up intent."""
        # Would get current volume and increase
        result = self.set_volume(80)
        return "Ses açıldı"
    
    def handle_volume_down(self, **slots) -> str:
        """Handle volume down intent."""
        result = self.set_volume(40)
        return "Ses kısıldı"
    
    def handle_set_volume(self, volume: int = 50, **slots) -> str:
        """Handle set volume intent."""
        result = self.set_volume(volume)
        return result.get("message", f"Ses: %{volume}")
    
    def handle_current_track(self, **slots) -> str:
        """Handle current track intent."""
        result = self.get_current_track()
        if result.get("playing"):
            track = result["track"]
            return f"Şu an çalan: {track['name']} - {track['artist']}"
        return "Şu an çalan bir şarkı yok"
    
    def handle_shuffle(self, **slots) -> str:
        """Handle shuffle intent."""
        result = self.toggle_shuffle()
        return result.get("message", "Karıştırma ayarlandı")
    
    def handle_repeat(self, **slots) -> str:
        """Handle repeat intent."""
        result = self.toggle_repeat()
        return result.get("message", "Tekrarlama ayarlandı")
    
    def handle_like(self, **slots) -> str:
        """Handle like intent."""
        result = self.like_track()
        return result.get("message", "Şarkı beğenildi")
    
    # ==========================================================================
    # Private Methods
    # ==========================================================================
    
    def _ensure_connected(self) -> None:
        """Ensure Spotify is connected."""
        if not self._connected:
            # Mock: Would actually connect
            self._connected = True
            self._logger.debug("Spotify connection established (mock)")
    
    def _format_duration(self, ms: int) -> str:
        """Format milliseconds to mm:ss."""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
