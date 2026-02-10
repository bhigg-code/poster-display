"""Apple TV client for media detection via pyatv."""

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable
import os

# pyatv imports - will be None if not installed
try:
    import pyatv
    from pyatv.const import Protocol, DeviceState, MediaType
    PYATV_AVAILABLE = True
except ImportError:
    PYATV_AVAILABLE = False
    pyatv = None


@dataclass
class AppleTVMedia:
    """Currently playing media on Apple TV."""
    title: str
    artist: str = ""
    album: str = ""
    media_type: str = "unknown"  # video, music, tv, unknown
    state: str = "idle"  # idle, playing, paused, loading
    position: int = 0  # seconds
    duration: int = 0  # seconds
    app_name: str = ""
    app_id: str = ""  # e.g., com.google.ios.youtube
    artwork_url: str = ""


# Log callback type
LogCallback = Callable[[str, str, str, str], None]


class AppleTVClient:
    """Client for connecting to and monitoring Apple TV."""
    
    def __init__(self, host: str, name: str = "Apple TV"):
        self.host = host
        self.name = name
        self._atv = None
        self._config = None
        self._log_callback: Optional[LogCallback] = None
        self._credentials_dir = os.path.expanduser("~/.pyatv")
        
    def set_logger(self, callback: LogCallback):
        """Set logging callback."""
        self._log_callback = callback
        
    def _log(self, action: str, details: str = "", level: str = "info"):
        """Log activity."""
        if self._log_callback:
            self._log_callback("appletv", action, details, level)
        print(f"[appletv] {action}: {details}" if details else f"[appletv] {action}")
    
    @property
    def is_available(self) -> bool:
        """Check if pyatv is installed."""
        return PYATV_AVAILABLE
    
    async def scan_for_device(self) -> bool:
        """Scan for the Apple TV and get its configuration with credentials from storage."""
        if not PYATV_AVAILABLE:
            self._log("pyatv not installed", "pip install pyatv", "error")
            return False
            
        try:
            self._log(f"Scanning for Apple TV", f"Looking for {self.host}")
            
            loop = asyncio.get_event_loop()
            
            # Get the storage to load credentials
            storage = None
            try:
                from pyatv.storage.file_storage import FileStorage
                storage = FileStorage.default_storage(loop)
                await storage.load()
            except Exception as e:
                self._log(f"Could not load storage", str(e), "warning")
            
            # Scan with storage to automatically load credentials
            atvs = await pyatv.scan(loop, hosts=[self.host], timeout=5, storage=storage)
            
            if not atvs:
                self._log(f"Apple TV not found", f"No device at {self.host}", "warning")
                return False
            
            self._config = atvs[0]
            self.name = self._config.name
            
            # Check if credentials were loaded
            companion = self._config.get_service(Protocol.Companion)
            if companion and companion.credentials:
                self._log(f"Credentials loaded", "Companion protocol ready")
            else:
                self._log(f"No credentials found", "Pairing may be required", "warning")
            
            self._log(f"Found Apple TV", f"{self.name} at {self.host}")
            return True
            
        except Exception as e:
            self._log(f"Scan failed", str(e), "error")
            return False
    
    async def connect(self) -> bool:
        """Connect to the Apple TV."""
        if not PYATV_AVAILABLE:
            return False
            
        if not self._config:
            if not await self.scan_for_device():
                return False
        
        try:
            self._log(f"Connecting to {self.name}", self.host)
            self._atv = await pyatv.connect(self._config, asyncio.get_event_loop())
            self._log(f"Connected to {self.name}", "Ready", "success")
            return True
        except Exception as e:
            self._log(f"Connection failed", str(e), "error")
            self._atv = None
            return False
    
    async def disconnect(self):
        """Disconnect from Apple TV."""
        if self._atv:
            self._atv.close()
            self._atv = None
            self._log(f"Disconnected from {self.name}")
    
    async def get_playing(self) -> Optional[AppleTVMedia]:
        """Get currently playing media."""
        if not PYATV_AVAILABLE:
            return None
            
        # Connect if needed
        if not self._atv:
            if not await self.connect():
                return None
        
        try:
            playing = await self._atv.metadata.playing()
            
            # Map media type
            media_type_map = {
                MediaType.Unknown: "unknown",
                MediaType.Video: "video",
                MediaType.Music: "music",
                MediaType.TV: "tv",
            } if PYATV_AVAILABLE else {}
            
            # Map device state
            state_map = {
                DeviceState.Idle: "idle",
                DeviceState.Playing: "playing",
                DeviceState.Paused: "paused",
                DeviceState.Loading: "loading",
                DeviceState.Seeking: "playing",
                DeviceState.Stopped: "idle",
            } if PYATV_AVAILABLE else {}
            
            media_type = media_type_map.get(playing.media_type, "unknown")
            state = state_map.get(playing.device_state, "idle")
            
            # Get app name if available
            app_name = ""
            app_id = ""
            try:
                app_info = self._atv.metadata.app
                if app_info:
                    # Parse "App: AppName (com.bundle.id)" format
                    app_str = str(app_info)
                    # Strip "App: " prefix if present
                    if app_str.startswith("App: "):
                        app_str = app_str[5:]
                    # Parse "AppName (com.bundle.id)"
                    if " (" in app_str and app_str.endswith(")"):
                        app_name = app_str.split(" (")[0]
                        app_id = app_str.split("(")[1].rstrip(")")
                    else:
                        app_name = app_str
            except:
                pass
            
            return AppleTVMedia(
                title=playing.title or "",
                artist=playing.artist or "",
                album=playing.album or "",
                media_type=media_type,
                state=state,
                position=playing.position or 0,
                duration=playing.total_time or 0,
                app_name=app_name,
                app_id=app_id,
            )
            
        except Exception as e:
            self._log(f"Failed to get playing status", str(e), "error")
            # Reset connection on error
            await self.disconnect()
            return None
    
    async def is_playing(self) -> bool:
        """Check if something is currently playing."""
        media = await self.get_playing()
        return media is not None and media.state == "playing"
    
    async def start_pairing(self, protocol_name: str = "companion") -> dict:
        """
        Start pairing process for a protocol.
        Returns dict with status and instructions.
        """
        if not PYATV_AVAILABLE:
            return {"success": False, "error": "pyatv not installed"}
            
        if not self._config:
            if not await self.scan_for_device():
                return {"success": False, "error": "Could not find Apple TV"}
        
        protocol_map = {
            "airplay": Protocol.AirPlay,
            "companion": Protocol.Companion,
            "raop": Protocol.RAOP,
        }
        
        protocol = protocol_map.get(protocol_name.lower())
        if not protocol:
            return {"success": False, "error": f"Unknown protocol: {protocol_name}"}
        
        # Check if already paired (has credentials for this protocol)
        service = self._config.get_service(protocol)
        if service and service.credentials:
            self._log(f"Already paired for {protocol_name}", f"{self.name} has existing credentials")
            return {
                "success": True,
                "already_paired": True,
                "message": f"Already paired for {protocol_name}. No action needed.",
                "protocol": protocol_name,
            }
        
        try:
            self._pairing = await pyatv.pair(self._config, protocol, asyncio.get_running_loop())
            self._current_protocol = protocol_name  # Track which protocol we're pairing
            await self._pairing.begin()
            
            self._log(f"Pairing started for {self.name}", f"Protocol: {protocol_name}")
            
            return {
                "success": True,
                "device_provides_pin": self._pairing.device_provides_pin,
                "message": "Enter the 4-digit PIN shown on your Apple TV" if self._pairing.device_provides_pin 
                          else "A PIN will be displayed. Enter it to complete pairing.",
                "protocol": protocol_name,
            }
                
        except Exception as e:
            error_msg = str(e) or f"Connection failed - {protocol_name} pairing timed out"
            self._log(f"Pairing start failed", error_msg, "error")
            return {"success": False, "error": error_msg}
    
    async def finish_pairing(self, pin: str, next_protocol: str = None) -> dict:
        """
        Complete pairing with the provided PIN.
        Optionally start pairing the next protocol after success.
        """
        if not PYATV_AVAILABLE:
            return {"success": False, "error": "pyatv not installed"}
        
        if not hasattr(self, '_pairing') or not self._pairing:
            return {"success": False, "error": "No pairing in progress. Start pairing first."}
        
        current_protocol = getattr(self, '_current_protocol', 'unknown')
        
        try:
            self._pairing.pin(pin)
            await self._pairing.finish()
            
            # Check if pairing succeeded
            if self._pairing.has_paired:
                # Get credentials from the pairing session
                credentials = self._pairing.service.credentials
                protocol = self._pairing.service.protocol
                
                # Save credentials to storage
                try:
                    from pyatv.storage.file_storage import FileStorage
                    import json
                    import os
                    
                    loop = asyncio.get_running_loop()
                    storage = FileStorage.default_storage(loop)
                    
                    # Initialize storage file if empty or invalid
                    storage_path = os.path.expanduser("~/.pyatv.conf")
                    try:
                        await storage.load()
                    except Exception as load_err:
                        self._log(f"Initializing storage file", str(load_err), "warning")
                        # Create valid empty storage
                        with open(storage_path, 'w') as f:
                            json.dump({"version": 1, "devices": []}, f)
                        await storage.load()
                    
                    # Get the service on our config and apply the credentials
                    if self._config and credentials:
                        service = self._config.get_service(protocol)
                        if service:
                            # Get current settings, set credentials, apply back
                            settings = service.settings()
                            settings['credentials'] = credentials
                            service.apply(settings)
                            
                            # Save updated config to storage
                            await storage.update_settings(self._config)
                            await storage.save()
                            self._log(f"{current_protocol} credentials saved to storage", f"Device: {self.name}", "success")
                        else:
                            self._log(f"Warning: Service not found for protocol {protocol}", "", "warning")
                    else:
                        self._log(f"Warning: No config or credentials to save", "", "warning")
                except Exception as save_err:
                    self._log(f"Warning: Could not save credentials to storage", str(save_err), "warning")
                    import traceback
                    traceback.print_exc()
                
                self._log(f"{current_protocol} pairing completed for {self.name}", f"Credentials: {credentials[:20]}..." if credentials else "No credentials", "success")
                await self._pairing.close()
                self._pairing = None
                
                # Rescan to pick up new credentials
                await self.scan_for_device()
                
                # If there's a next protocol to pair, start it
                if next_protocol:
                    next_result = await self.start_pairing(next_protocol)
                    if next_result.get("success"):
                        return {
                            "success": True,
                            "partial": True,
                            "message": f"{current_protocol.title()} paired! Now enter PIN for {next_protocol}.",
                            "next_protocol": next_protocol,
                            "device_provides_pin": next_result.get("device_provides_pin", True),
                        }
                    else:
                        # Next protocol failed to start, but current one succeeded
                        return {
                            "success": True,
                            "message": f"{current_protocol.title()} paired! (Could not start {next_protocol} pairing)",
                        }
                
                return {
                    "success": True,
                    "message": "Pairing successful! Apple TV is now configured for media detection.",
                }
            else:
                await self._pairing.close()
                self._pairing = None
                return {"success": False, "error": "Pairing failed - incorrect PIN or connection issue"}
                
        except Exception as e:
            self._log(f"Pairing failed", str(e), "error")
            if hasattr(self, '_pairing') and self._pairing:
                await self._pairing.close()
                self._pairing = None
            return {"success": False, "error": str(e)}
    
    async def cancel_pairing(self):
        """Cancel any in-progress pairing."""
        if hasattr(self, '_pairing') and self._pairing:
            await self._pairing.close()
            self._pairing = None
            self._log(f"Pairing cancelled for {self.name}")
    
    async def check_pairing_status(self) -> dict:
        """Check which protocols are paired."""
        if not PYATV_AVAILABLE:
            return {"available": False, "error": "pyatv not installed"}
            
        if not self._config:
            if not await self.scan_for_device():
                return {"available": False, "error": "Device not found"}
        
        status = {
            "available": True,
            "device": self.name,
            "protocols": {}
        }
        
        for service in self._config.services:
            proto_name = service.protocol.name.lower()
            status["protocols"][proto_name] = {
                "port": service.port,
                "paired": service.credentials is not None,
                "requires_password": service.requires_password,
            }
        
        return status


# Convenience function for quick status check
async def get_appletv_status(host: str) -> Optional[AppleTVMedia]:
    """Quick function to get Apple TV status without persistent connection."""
    client = AppleTVClient(host)
    try:
        return await client.get_playing()
    finally:
        await client.disconnect()
