"""BluOS (Bluesound) player integration."""

import asyncio
import aiohttp
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
import logging

log = logging.getLogger(__name__)


@dataclass
class BluOSTrack:
    """Represents currently playing track on BluOS."""
    title: str
    artist: str
    album: str
    album_art_url: str
    duration_seconds: int
    position_seconds: int
    is_playing: bool
    service: str = ""


class BluOSClient:
    """BluOS player client for Bluesound NODE."""

    def __init__(self, host: str, port: int = 11000):
        self.host = host
        self.port = port
        self._session: Optional[aiohttp.ClientSession] = None
        self._connected = False
        self._last_etag: Optional[str] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def connect(self) -> bool:
        """Connect to BluOS device."""
        try:
            self._session = aiohttp.ClientSession()
            async with self._session.get(
                f"{self.base_url}/SyncStatus", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    self._connected = True
                    log.info(f"Connected to BluOS at {self.host}:{self.port}")
                    return True
        except Exception as e:
            log.warning(f"BluOS connection failed: {e}")
        self._connected = False
        return False

    async def disconnect(self):
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    async def get_status(self) -> Optional[BluOSTrack]:
        """Fetch current playback status."""
        if not self._session:
            return None
        try:
            async with self._session.get(
                f"{self.base_url}/Status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()

            root = ET.fromstring(text)

            state = root.findtext("state", "")
            is_playing = state in ("stream", "play")

            title = root.findtext("title1", "") or root.findtext("song", "")
            artist = root.findtext("title2", "") or root.findtext("artist", "")
            album = root.findtext("title3", "") or root.findtext("album", "")
            album_art = root.findtext("image", "") or root.findtext("currentImage", "")
            service = root.findtext("serviceName", "")

            try:
                duration = int(root.findtext("totlen", "0"))
            except ValueError:
                duration = 0

            try:
                position = int(root.findtext("secs", "0"))
            except ValueError:
                position = 0

            return BluOSTrack(
                title=title,
                artist=artist,
                album=album,
                album_art_url=album_art,
                duration_seconds=duration,
                position_seconds=position,
                is_playing=is_playing,
                service=service,
            )

        except Exception as e:
            log.warning(f"BluOS status fetch failed: {e}")
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected
