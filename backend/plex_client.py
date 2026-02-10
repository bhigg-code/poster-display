"""Plex server integration."""

import asyncio
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

import aiohttp


@dataclass
class PlexMovie:
    """Represents a movie from Plex."""
    title: str
    year: Optional[str]
    poster_url: str
    duration_ms: int = 0
    position_ms: int = 0
    player_name: Optional[str] = None
    rating_key: Optional[str] = None
    synopsis: Optional[str] = None


class PlexClient:
    """Plex server client."""
    
    # High-res poster dimensions (portrait 2:3 aspect ratio)
    POSTER_WIDTH = 1000
    POSTER_HEIGHT = 1500
    
    def __init__(self, host: str, port: int, token: str):
        self.base_url = f"http://{host}:{port}"
        self.token = token
        self._library_keys: dict[str, str] = {}  # name -> key
    
    def _url(self, path: str) -> str:
        """Build URL with token."""
        sep = "&" if "?" in path else "?"
        return f"{self.base_url}{path}{sep}X-Plex-Token={self.token}"
    
    def _poster_url(self, thumb_path: str) -> str:
        """Build high-resolution poster URL using Plex's photo transcoder."""
        if not thumb_path:
            return ""
        # Use Plex's photo transcoder for high-res images
        import urllib.parse
        encoded_thumb = urllib.parse.quote(thumb_path, safe='')
        return (f"{self.base_url}/photo/:/transcode"
                f"?width={self.POSTER_WIDTH}&height={self.POSTER_HEIGHT}"
                f"&minSize=1&upscale=1"
                f"&url={encoded_thumb}"
                f"&X-Plex-Token={self.token}")
    
    async def _get(self, path: str) -> Optional[ET.Element]:
        """Make GET request and parse XML response."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._url(path), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        return ET.fromstring(text)
        except Exception as e:
            print(f"Plex request error: {e}")
        return None
    
    async def get_libraries(self) -> dict[str, str]:
        """Get library names and keys."""
        if self._library_keys:
            return self._library_keys
            
        root = await self._get("/library/sections")
        if root is None:
            return {}
        
        for directory in root.findall(".//Directory"):
            name = directory.get("title", "")
            key = directory.get("key", "")
            if name and key:
                self._library_keys[name] = key
        
        return self._library_keys
    
    async def get_active_sessions(self) -> list[PlexMovie]:
        """Get currently playing sessions."""
        root = await self._get("/status/sessions")
        if root is None:
            return []
        
        sessions = []
        for video in root.findall(".//Video"):
            if video.get("type") != "movie":
                continue
                
            # Get player info
            player = video.find(".//Player")
            player_name = player.get("title") if player else None
            
            # Build high-res poster URL
            thumb = video.get("thumb", "")
            poster_url = self._poster_url(thumb)
            
            movie = PlexMovie(
                title=video.get("title", "Unknown"),
                year=video.get("year"),
                poster_url=poster_url,
                duration_ms=int(video.get("duration", 0)),
                position_ms=int(video.get("viewOffset", 0)),
                player_name=player_name,
                rating_key=video.get("ratingKey"),
                    synopsis=video.get("summary"),
            )
            sessions.append(movie)
        
        return sessions
    
    async def get_random_movies(self, library_names: list[str], count: int = 20) -> list[PlexMovie]:
        """Get random movies from specified libraries for 'Coming Soon' display."""
        libraries = await self.get_libraries()
        all_movies = []
        
        for lib_name in library_names:
            key = libraries.get(lib_name)
            if not key:
                continue
            
            # Get all movies from library
            root = await self._get(f"/library/sections/{key}/all")
            if root is None:
                continue
            
            for video in root.findall(".//Video"):
                thumb = video.get("thumb", "")
                if not thumb:
                    continue
                    
                movie = PlexMovie(
                    title=video.get("title", "Unknown"),
                    year=video.get("year"),
                    poster_url=self._poster_url(thumb),
                    rating_key=video.get("ratingKey"),
                    synopsis=video.get("summary"),
                )
                all_movies.append(movie)
        
        # Return random selection
        if len(all_movies) <= count:
            return all_movies
        return random.sample(all_movies, count)
    
    async def get_shield_session(self) -> Optional[PlexMovie]:
        """Get currently playing session on any Shield device."""
        sessions = await self.get_active_sessions()
        for session in sessions:
            if session.player_name and "SHIELD" in session.player_name.upper():
                return session
        return None
    
    async def get_players(self) -> list[dict]:
        """Get all registered players/clients from Plex."""
        players = []
        seen_ids = set()
        
        # Query plex.tv for registered devices (this has local IPs)
        try:
            import aiohttp
            url = f"https://plex.tv/api/resources?includeHttps=1&X-Plex-Token={self.token}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        root = ET.fromstring(text)
                        
                        for device in root.findall(".//Device"):
                            provides = device.get("provides", "")
                            # Only include player devices
                            if "player" not in provides:
                                continue
                            
                            machine_id = device.get("clientIdentifier", "")
                            if machine_id in seen_ids:
                                continue
                            
                            # Get local connection IP
                            local_ip = ""
                            local_port = ""
                            for conn in device.findall(".//Connection"):
                                if conn.get("local") == "1":
                                    local_ip = conn.get("address", "")
                                    local_port = conn.get("port", "")
                                    break
                            
                            if local_ip:
                                player = {
                                    "name": device.get("name", "Unknown"),
                                    "host": local_ip,
                                    "address": local_ip,
                                    "port": local_port,
                                    "machine_id": machine_id,
                                    "product": device.get("product", ""),
                                    "platform": device.get("platform", ""),
                                    "device": device.get("device", ""),
                                    "device_class": "",
                                    "presence": device.get("presence", "0"),
                                    "last_seen": device.get("lastSeenAt", ""),
                                }
                                players.append(player)
                                seen_ids.add(machine_id)
        except Exception as e:
            print(f"Error querying plex.tv resources: {e}")
        
        # Also check local /clients endpoint (currently connected)
        root = await self._get("/clients")
        if root is not None:
            for server in root.findall(".//Server"):
                machine_id = server.get("machineIdentifier", "")
                if machine_id in seen_ids:
                    continue
                
                player = {
                    "name": server.get("name", "Unknown"),
                    "host": server.get("host", ""),
                    "address": server.get("address", ""),
                    "port": server.get("port", ""),
                    "machine_id": machine_id,
                    "product": server.get("product", ""),
                    "platform": server.get("platform", ""),
                    "device": server.get("device", ""),
                    "device_class": server.get("deviceClass", ""),
                }
                if player["address"] or player["host"]:
                    players.append(player)
                    seen_ids.add(machine_id)
        
        # Also check active sessions for additional player info
        sessions_root = await self._get("/status/sessions")
        if sessions_root is not None:
            for video in sessions_root.findall(".//Video"):
                player_elem = video.find(".//Player")
                if player_elem is not None:
                    machine_id = player_elem.get("machineIdentifier", "")
                    if machine_id not in seen_ids:
                        player = {
                            "name": player_elem.get("title", "Unknown"),
                            "host": "",
                            "address": player_elem.get("address", ""),
                            "port": "",
                            "machine_id": machine_id,
                            "product": player_elem.get("product", ""),
                            "platform": player_elem.get("platform", ""),
                            "device": player_elem.get("device", ""),
                            "device_class": player_elem.get("deviceClass", ""),
                        }
                        if player["address"]:
                            players.append(player)
                            seen_ids.add(machine_id)
        
        return players
    
    def is_android_device(self, player: dict) -> bool:
        """Check if a player is an Android/Shield device."""
        platform = (player.get("platform") or "").lower()
        product = (player.get("product") or "").lower()
        device = (player.get("device") or "").lower()
        name = (player.get("name") or "").lower()
        
        android_indicators = ["android", "shield", "nvidia"]
        for indicator in android_indicators:
            if indicator in platform or indicator in product or indicator in device or indicator in name:
                return True
        return False
    
    def is_appletv_device(self, player: dict) -> bool:
        """Check if a player is an Apple TV device."""
        platform = (player.get("platform") or "").lower()
        product = (player.get("product") or "").lower()
        device = (player.get("device") or "").lower()
        name = (player.get("name") or "").lower()
        
        appletv_indicators = ["apple tv", "appletv", "tvos"]
        for indicator in appletv_indicators:
            if indicator in platform or indicator in product or indicator in device or indicator in name:
                return True
        return False
    
    async def get_session_for_player(self, player_name: str = None, player_ip: str = None) -> Optional[PlexMovie]:
        """Get currently playing session for a specific player by name or IP."""
        sessions = await self.get_active_sessions()
        root = await self._get("/status/sessions")
        if root is None:
            return None
        
        for video in root.findall(".//Video"):
            if video.get("type") != "movie":
                continue
            
            player_elem = video.find(".//Player")
            if player_elem is None:
                continue
            
            # Match by name or IP address
            p_title = player_elem.get("title", "")
            p_address = player_elem.get("address", "")
            
            name_match = player_name and player_name.lower() in p_title.lower()
            ip_match = player_ip and player_ip == p_address
            
            if name_match or ip_match:
                thumb = video.get("thumb", "")
                return PlexMovie(
                    title=video.get("title", "Unknown"),
                    year=video.get("year"),
                    poster_url=self._poster_url(thumb),
                    duration_ms=int(video.get("duration", 0)),
                    position_ms=int(video.get("viewOffset", 0)),
                    player_name=p_title,
                    rating_key=video.get("ratingKey"),
                    synopsis=video.get("summary"),
                )
        
        return None
