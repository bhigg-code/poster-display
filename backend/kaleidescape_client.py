"""Kaleidescape player integration."""

import asyncio
from dataclasses import dataclass
from typing import Optional

from kaleidescape import Device


@dataclass
class KaleidescapeMovie:
    """Represents currently playing movie on Kaleidescape."""
    title: str
    cover_url: str
    duration_seconds: int
    position_seconds: int
    is_playing: bool
    play_status: str
    synopsis: str = ""


class KaleidescapeClient:
    """Kaleidescape player client."""
    
    def __init__(self, host: str, port: int = 10000):
        self.host = host
        self.port = port
        self._device: Optional[Device] = None
        self._connected = False
    
    async def connect(self):
        """Connect to Kaleidescape device."""
        # Check if truly connected (both our flag AND the device's state)
        if self._device and self._device.is_connected:
            self._connected = True
            return
        
        # Disconnect old device if it exists but isn't connected
        if self._device:
            try:
                await self._device.disconnect()
            except Exception:
                pass
            self._device = None
        
        try:
            self._device = Device(self.host, timeout=10, reconnect=True, reconnect_delay=5)
            await self._device.connect()
            await self._device.refresh()  # Required to populate movie state
            self._connected = True
            print(f"Connected to Kaleidescape: {self._device.system.friendly_name}")
        except Exception as e:
            print(f"Kaleidescape connection error: {e}")
            self._connected = False
            self._device = None
    
    async def disconnect(self):
        """Disconnect from Kaleidescape device."""
        if self._device:
            await self._device.disconnect()
            self._connected = False
    
    async def get_now_playing(self) -> Optional[KaleidescapeMovie]:
        """Get currently playing movie info."""
        # Always verify connection state before querying
        if not self.is_connected:
            await self.connect()
        
        if not self._device or not self.is_connected:
            print("Kaleidescape not connected, cannot get now playing")
            return None
        
        try:
            await self._device.refresh()
            movie = self._device.movie
            
            # Check if something is actually playing
            if not movie.title:
                print(f"Kaleidescape: No title (play_status={movie.play_status})")
                return None
            
            playing_states = ["playing", "forward", "reverse"]
            is_playing = movie.play_status in playing_states
            
            print(f"Kaleidescape: {movie.title} ({movie.play_status})")
            
            return KaleidescapeMovie(
                title=movie.title,
                cover_url=movie.cover_hires or movie.cover or "",
                duration_seconds=movie.title_length or 0,
                position_seconds=movie.title_location or 0,
                is_playing=is_playing,
                play_status=movie.play_status or "none",
                synopsis=movie.synopsis or "",
            )
        except Exception as e:
            print(f"Kaleidescape query error: {e}")
            self._connected = False
            return None
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._device is not None and self._device.is_connected
