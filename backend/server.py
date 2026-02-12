"""Main server for Movie Poster Display."""

import asyncio
import json
import os
import random
import signal
import sys
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from aiohttp import web

# Version
VERSION = "1.2.0"

# =============================================================================
# Input Validation
# =============================================================================

import re

def validate_ip(ip: str) -> bool:
    """Validate IPv4 address format."""
    if not ip:
        return True  # Empty is allowed (for deletion)
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    parts = ip.split('.')
    return all(0 <= int(p) <= 255 for p in parts)

def validate_port(port) -> bool:
    """Validate port number."""
    if port is None:
        return True
    try:
        p = int(port)
        return 1 <= p <= 65535
    except (ValueError, TypeError):
        return False

def validate_config_data(section: str, data: dict) -> tuple[bool, str]:
    """Validate config data before saving. Returns (valid, error_message)."""
    # Validate host IPs
    for key in ['host', 'shield_host', 'appletv_host']:
        if key in data and not validate_ip(data.get(key, '')):
            return False, f"Invalid IP address for {key}"
    
    # Validate ports
    if 'port' in data and not validate_port(data.get('port')):
        return False, "Invalid port number (must be 1-65535)"
    
    # Validate name length
    if 'name' in data and len(str(data.get('name', ''))) > 100:
        return False, "Name too long (max 100 characters)"
    
    return True, ""


# =============================================================================
# Debug Logging
# =============================================================================

class DebugLog:
    """In-memory debug log for UI display."""
    
    def __init__(self, max_entries: int = 200):
        self._entries = deque(maxlen=max_entries)
    
    def log(self, category: str, action: str, details: str = "", level: str = "info"):
        """Add a log entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "action": action,
            "details": details,
            "level": level,
        }
        self._entries.append(entry)
        # Also print to console
        print(f"[{category}] {action}: {details}" if details else f"[{category}] {action}")
    
    def get_entries(self, limit: int = 100, category: str = None) -> list:
        """Get recent log entries."""
        entries = list(self._entries)
        if category:
            entries = [e for e in entries if e["category"] == category]
        return list(reversed(entries))[:limit]
    
    def clear(self):
        """Clear all entries."""
        self._entries.clear()


# Global debug log
debug_log = DebugLog()

from atlona import AtlonaMatrix
from config_manager import config
from kaleidescape_client import KaleidescapeClient, KaleidescapeMovie
from plex_client import PlexClient, PlexMovie
from shield_client import ShieldClient
from appletv_client import AppleTVClient, AppleTVMedia, PYATV_AVAILABLE
from poster_lookup import poster_lookup
from discovery import discovery


class DisplayMode(str, Enum):
    KALEIDESCAPE = "kaleidescape"
    PLEX = "plex"
    COMING_SOON = "coming_soon"
    STREAMING = "streaming"
    IDLE = "idle"


@dataclass
class DisplayState:
    """Current state of the poster display."""
    mode: DisplayMode
    title: str = ""
    year: str = ""
    poster_url: str = ""
    duration_seconds: int = 0
    position_seconds: int = 0
    is_playing: bool = False
    play_status: str = ""
    synopsis: str = ""
    current_input: int = 0
    source_name: str = ""
    using_cached_input: bool = False


class PosterDisplayServer:
    """Main server coordinating all sources."""
    
    def __init__(self):
        self._init_clients()
        self._init_shield_clients()
        self._init_appletv_clients()
        self.current_state = DisplayState(mode=DisplayMode.IDLE)
        self.coming_soon_movies: list[PlexMovie] = []
        self.coming_soon_index = 0
        self._running = False
        self._last_known_input: Optional[int] = None  # Cache last known good input
        
        # Listen for config changes
        config.on_change(self._on_config_change)
    
    def _init_clients(self):
        """Initialize or reinitialize clients from config."""
        self.atlona = AtlonaMatrix(
            config.atlona_host, 
            config.atlona_port,
            use_broker=config.atlona_use_broker,
            broker_host=config.atlona_broker_host,
            broker_port=config.atlona_broker_port
        )
        self.kaleidescape = KaleidescapeClient(config.kaleidescape_host, config.kaleidescape_port)
        self.plex = PlexClient(config.plex_host, config.plex_port, config.plex_token)
        self._init_shield_clients()
        self._init_appletv_clients()
    
    def _init_shield_clients(self):
        """Initialize Shield clients for inputs with shield_host configured."""
        self.shield_clients = {}
        for input_num, input_config in config.inputs.items():
            shield_host = input_config.get('shield_host')
            if shield_host:
                self.shield_clients[int(input_num)] = ShieldClient(shield_host)
                print(f"Shield client initialized for input {input_num}: {shield_host}")
    
    def _init_appletv_clients(self):
        """Initialize Apple TV clients for inputs with appletv_host configured."""
        self.appletv_clients = {}
        for input_num, input_config in config.inputs.items():
            appletv_host = input_config.get('appletv_host')
            if appletv_host:
                client = AppleTVClient(appletv_host, input_config.get('name', 'Apple TV'))
                client.set_logger(debug_log.log)
                self.appletv_clients[int(input_num)] = client
                print(f"Apple TV client initialized for input {input_num}: {appletv_host}")
    
    def _on_config_change(self, section: str, new_config: dict):
        """Handle config changes."""
        print(f"Config section '{section}' changed, reinitializing clients...")
        self._init_clients()
        
        # Refresh coming soon if plex changed
        if section == "plex":
            asyncio.create_task(self._refresh_coming_soon())
    
    async def start(self):
        """Start the server and background tasks."""
        self._running = True
        
        # Connect to Kaleidescape
        await self.kaleidescape.connect()
        
        # Load initial coming soon movies
        await self._refresh_coming_soon()
        
        # Start background polling
        asyncio.create_task(self._poll_loop())
        asyncio.create_task(self._coming_soon_rotation())
    
    async def stop(self):
        """Stop the server."""
        self._running = False
        await self.kaleidescape.disconnect()
    
    async def _refresh_coming_soon(self):
        """Refresh the list of 'Coming Soon' movies."""
        libraries = config.plex_libraries
        if not libraries:
            libraries = ["Movies"]
        
        movies = await self.plex.get_random_movies(libraries, count=30)
        if movies:
            random.shuffle(movies)
            self.coming_soon_movies = movies
            print(f"Loaded {len(movies)} movies for 'Coming Soon' rotation")
    
    async def _poll_loop(self):
        """Main polling loop to check sources."""
        last_atlona_poll = 0
        import time
        
        while self._running:
            try:
                current_time = time.time()
                
                # Check if we should poll Atlona (separate interval to avoid connection exhaustion)
                should_poll_atlona = (current_time - last_atlona_poll) >= config.atlona_poll_interval
                
                await self._update_state(poll_atlona=should_poll_atlona)
                
                if should_poll_atlona:
                    last_atlona_poll = current_time
                    
            except Exception as e:
                print(f"Poll error: {e}")
            await asyncio.sleep(config.poll_interval)
    
    async def _coming_soon_rotation(self):
        """Rotate coming soon posters."""
        while self._running:
            await asyncio.sleep(config.coming_soon_interval)
            if self.current_state.mode == DisplayMode.COMING_SOON:
                self._next_coming_soon()
    
    def _next_coming_soon(self):
        """Advance to next coming soon poster."""
        if not self.coming_soon_movies:
            return
        
        self.coming_soon_index = (self.coming_soon_index + 1) % len(self.coming_soon_movies)
        movie = self.coming_soon_movies[self.coming_soon_index]
        
        self.current_state = DisplayState(
            mode=DisplayMode.COMING_SOON,
            title=movie.title,
            year=movie.year or "",
            poster_url=movie.poster_url,
            source_name="Coming Soon",
            synopsis=movie.synopsis or "",
        )
    
    async def _update_state_no_atlona(self):
        """Update display state when no Atlona matrix is configured.
        
        Polls the default display device directly.
        """
        # Check if ANY integrations are configured
        has_any_integration = (
            config.kaleidescape_enabled or 
            bool(self.appletv_clients) or 
            bool(self.shield_clients) or
            (config.plex_host and config.plex_token)
        )
        
        if not has_any_integration:
            # No integrations configured at all - show idle/setup state
            self.current_state = DisplayState(
                mode=DisplayMode.IDLE,
                title="Setup Required",
                synopsis="Add integrations in the admin panel to get started",
                source_name="Not Configured",
            )
            return
        
        default_display = config.default_display
        
        # If no default set, try Kaleidescape first, then first Apple TV
        if not default_display:
            if config.kaleidescape_enabled:
                default_display = "kaleidescape"
            elif self.appletv_clients:
                default_display = "appletv"
            elif self.shield_clients:
                default_display = "shield"
        
        if not default_display:
            # Has integrations but no default display - show coming soon if plex configured
            if config.plex_host and config.plex_token and self.coming_soon_movies:
                if self.current_state.mode != DisplayMode.COMING_SOON:
                    self._next_coming_soon()
            else:
                self.current_state = DisplayState(
                    mode=DisplayMode.IDLE,
                    title="Waiting",
                    synopsis="Configure a default display device",
                    source_name="Idle",
                )
            return
        
        debug_log.log("polling", "Direct Mode", f"Polling {default_display} (no Atlona)")
        
        # Poll Kaleidescape directly
        if default_display == "kaleidescape" and config.kaleidescape_enabled:
            debug_log.log("polling", "Kaleidescape", "Querying now playing (direct)")
            movie = await self.kaleidescape.get_now_playing()
            if movie and movie.title:
                debug_log.log("polling", "Kaleidescape", f"Playing: {movie.title} ({movie.play_status})", "success")
                self.current_state = DisplayState(
                    mode=DisplayMode.KALEIDESCAPE,
                    title=movie.title,
                    poster_url=movie.cover_url,
                    duration_seconds=movie.duration_seconds,
                    position_seconds=movie.position_seconds,
                    is_playing=movie.is_playing,
                    play_status=movie.play_status,
                    synopsis=movie.synopsis,
                    source_name="Kaleidescape",
                )
                return
        
        # Poll Apple TV directly
        if default_display == "appletv" and self.appletv_clients:
            # Get the specific default input, or fall back to first Apple TV
            default_input = config.default_input
            if default_input and int(default_input) in self.appletv_clients:
                input_num = int(default_input)
            else:
                input_num = next(iter(self.appletv_clients.keys()))
            atv = self.appletv_clients[input_num]
            input_config = config.inputs.get(str(input_num), {})
            input_name = input_config.get("name", "Apple TV")
            
            debug_log.log("polling", "Apple TV", f"Querying media state (direct: {input_name})")
            try:
                atv_media = await atv.get_playing()
                if atv_media and atv_media.state == "playing" and atv_media.title:
                    debug_log.log("polling", "Apple TV", f"Playing: {atv_media.title} on {atv_media.app_name}", "success")
                    
                    # Look up external poster (returns tuple: poster_url, description)
                    external_poster = ""
                    external_synopsis = ""
                    poster_result = await poster_lookup.find_poster(
                        atv_media.title, "", app_name=atv_media.app_name, app_id=atv_media.app_id
                    )
                    if poster_result:
                        external_poster = poster_result[0] or ""
                        external_synopsis = poster_result[1] or ""
                    
                    synopsis_parts = []
                    if atv_media.app_name:
                        synopsis_parts.append(f"Streaming on {atv_media.app_name}")
                    if atv_media.artist and atv_media.artist != 'null':
                        synopsis_parts.append(atv_media.artist)
                    if external_synopsis:
                        synopsis_parts.append(external_synopsis)
                    
                    self.current_state = DisplayState(
                        mode=DisplayMode.STREAMING,
                        title=atv_media.title,
                        poster_url=external_poster or atv_media.artwork_url or "",
                        is_playing=True,
                        synopsis=" • ".join(synopsis_parts) if synopsis_parts else "",
                        source_name=input_name,
                    )
                    return
            except Exception as e:
                debug_log.log("polling", "Apple TV", f"Error: {str(e)}", "error")
        
        # Poll Shield directly
        if default_display == "shield" and self.shield_clients:
            # Get the specific default input, or fall back to first shield
            default_input = config.default_input
            if default_input and int(default_input) in self.shield_clients:
                input_num = int(default_input)
            else:
                input_num = next(iter(self.shield_clients.keys()))
            shield = self.shield_clients[input_num]
            input_config = config.inputs.get(str(input_num), {})
            input_name = input_config.get("name", "Nvidia Shield")
            
            debug_log.log("polling", "Shield", f"Querying media state (direct: {input_name})")
            try:
                shield_state = shield.get_state()
                if shield_state.is_connected and shield_state.is_media_playing and shield_state.media_title:
                    debug_log.log("polling", "Shield", f"Playing: {shield_state.media_title} on {shield_state.app_name}", "success")
                    
                    # Look up external poster (returns tuple: poster_url, description)
                    external_poster = ""
                    external_synopsis = ""
                    poster_result = await poster_lookup.find_poster(
                        shield_state.media_title, "", app_name=shield_state.app_name
                    )
                    if poster_result:
                        external_poster = poster_result[0] or ""
                        external_synopsis = poster_result[1] or ""
                    
                    synopsis_parts = []
                    if shield_state.app_name:
                        synopsis_parts.append(f"Streaming on {shield_state.app_name}")
                    if shield_state.media_artist and shield_state.media_artist != 'null':
                        synopsis_parts.append(shield_state.media_artist)
                    if external_synopsis:
                        synopsis_parts.append(external_synopsis)
                    
                    self.current_state = DisplayState(
                        mode=DisplayMode.STREAMING,
                        title=shield_state.media_title,
                        poster_url=external_poster or "",
                        is_playing=True,
                        synopsis=" • ".join(synopsis_parts) if synopsis_parts else "",
                        source_name=input_name,
                    )
                    return
                elif shield_state.is_connected and shield_state.app_name:
                    debug_log.log("polling", "Shield", f"Idle on {shield_state.app_name}", "info")
            except Exception as e:
                debug_log.log("polling", "Shield", f"Error: {str(e)}", "error")
        
        # Nothing playing, show coming soon
        if self.current_state.mode != DisplayMode.COMING_SOON:
            self._next_coming_soon()
    
    async def _update_state(self, poll_atlona: bool = True):
        """Update display state based on current sources."""
        # Check if Atlona is enabled
        if not config.atlona_enabled:
            # No Atlona - poll default display directly
            await self._update_state_no_atlona()
            return
        
        # Get current routing (only poll Atlona when requested to avoid connection exhaustion)
        using_cache = False
        current_input = None
        
        if poll_atlona:
            debug_log.log("polling", "Atlona", f"Querying routing for output {config.media_room_output}")
            
            # Retry logic: 3 attempts with 3s delay between retries
            max_retries = 3
            retry_delay = 3
            current_input = None
            
            for attempt in range(1, max_retries + 1):
                current_input = await self.atlona.get_input_for_output(config.media_room_output)
                
                if current_input is not None:
                    # Success
                    self._last_known_input = current_input
                    debug_log.log("polling", "Atlona", f"Input {current_input} → Output {config.media_room_output}", "success")
                    break
                else:
                    # Failed - retry if we have attempts left
                    if attempt < max_retries:
                        debug_log.log("polling", "Atlona", f"Query failed (attempt {attempt}/{max_retries}), retrying in {retry_delay}s...", "warning")
                        await asyncio.sleep(retry_delay)
                    else:
                        debug_log.log("polling", "Atlona", f"Query failed after {max_retries} attempts", "error")
            
            if current_input is None:
                # All retries exhausted - use cached input if available
                if self._last_known_input is not None:
                    current_input = self._last_known_input
                    using_cache = True
                    debug_log.log("polling", "Atlona", f"Using cached input: {current_input}", "warning")
        else:
            # Use cached value when not polling Atlona
            current_input = self._last_known_input
            using_cache = True
        
        if current_input is None:
            # No cached input, fall back to coming soon
            if self.current_state.mode != DisplayMode.COMING_SOON:
                self._next_coming_soon()
            return
        
        # Check if Kaleidescape input is selected
        kscape_input = config.kaleidescape_input
        if kscape_input and current_input == kscape_input:
            debug_log.log("polling", "Kaleidescape", f"Querying now playing (input {current_input})")
            movie = await self.kaleidescape.get_now_playing()
            if movie and movie.title:
                debug_log.log("polling", "Kaleidescape", f"Playing: {movie.title} ({movie.play_status})", "success")
                self.current_state = DisplayState(
                    mode=DisplayMode.KALEIDESCAPE,
                    title=movie.title,
                    poster_url=movie.cover_url,
                    duration_seconds=movie.duration_seconds,
                    position_seconds=movie.position_seconds,
                    is_playing=movie.is_playing,
                    play_status=movie.play_status,
                    synopsis=movie.synopsis,
                    current_input=current_input,
                    source_name="Kaleidescape",
                    using_cached_input=using_cache,
                )
                return
        
        # Check if a Plex input is selected
        plex_inputs = config.plex_inputs
        if current_input in plex_inputs:
            debug_log.log("polling", "Plex", f"Querying active sessions (input {current_input})")
            session = await self.plex.get_shield_session()
            if session:
                debug_log.log("polling", "Plex", f"Playing: {session.title} on {session.player_name}", "success")
                self.current_state = DisplayState(
                    mode=DisplayMode.PLEX,
                    title=session.title,
                    year=session.year or "",
                    poster_url=session.poster_url,
                    duration_seconds=session.duration_ms // 1000,
                    position_seconds=session.position_ms // 1000,
                    is_playing=True,
                    current_input=current_input,
                    synopsis=session.synopsis or "",
                    source_name=f"Plex ({session.player_name})",
                    using_cached_input=using_cache,
                )
                return
            else:
                # Plex input active but no Plex session - check device-specific APIs
                input_config = config.inputs.get(str(current_input), {})
                input_name = input_config.get("name", f"Input {current_input}")
                
                # Try to detect running app and media
                app_name = ""
                app_id = ""
                media_title = ""
                media_source = ""
                is_media_playing = False
                
                # Check Shield via ADB first
                if current_input in self.shield_clients:
                    debug_log.log("polling", "Shield ADB", f"Querying media state (input {current_input})")
                    shield = self.shield_clients[current_input]
                    shield_state = shield.get_state()
                    if shield_state.is_connected:
                        app_name = shield_state.app_name
                        media_title = shield_state.media_title  # Only set if actively playing
                        media_source = shield_state.media_artist
                        is_media_playing = shield_state.is_media_playing
                        if media_title:
                            debug_log.log("polling", "Shield ADB", f"Playing: {media_title} on {app_name}", "success")
                        else:
                            debug_log.log("polling", "Shield ADB", f"App: {app_name}, no active media")
                    else:
                        debug_log.log("polling", "Shield ADB", "Not connected", "warning")
                
                # Check Apple TV via pyatv if no Shield data
                elif current_input in self.appletv_clients:
                    debug_log.log("polling", "Apple TV", f"Querying media state (input {current_input})")
                    atv = self.appletv_clients[current_input]
                    try:
                        atv_media = await atv.get_playing()
                        if atv_media:
                            app_name = atv_media.app_name
                            app_id = atv_media.app_id
                            media_title = atv_media.title if atv_media.state == "playing" else ""
                            media_source = atv_media.artist
                            is_media_playing = atv_media.state == "playing"
                            if media_title:
                                debug_log.log("polling", "Apple TV", f"Playing: {media_title} on {app_name}", "success")
                            elif app_name:
                                debug_log.log("polling", "Apple TV", f"App: {app_name}, state: {atv_media.state}")
                            else:
                                debug_log.log("polling", "Apple TV", f"State: {atv_media.state}")
                        else:
                            debug_log.log("polling", "Apple TV", "No media info available", "warning")
                    except Exception as e:
                        debug_log.log("polling", "Apple TV", f"Error: {str(e)}", "error")
                
                # If nothing is actively playing, show Coming Soon instead
                if not media_title and not is_media_playing:
                    # Fall through to Coming Soon
                    pass
                else:
                    # Build display title
                    display_title = media_title or app_name or "Now Streaming"
                    
                    # Build synopsis with app and source info
                    synopsis_parts = []
                    if media_title and app_name:
                        synopsis_parts.append(f"Streaming on {app_name}")
                    if media_source and media_source != 'null':
                        synopsis_parts.append(media_source)
                    synopsis = " • ".join(synopsis_parts) if synopsis_parts else ""
                    
                    # Look up external poster and description for the show
                    external_poster = ""
                    external_synopsis = ""
                    if media_title:
                        poster_result = await poster_lookup.find_poster(
                            media_title, synopsis, app_name=app_name, app_id=app_id
                        )
                        if poster_result:
                            external_poster = poster_result[0] or ""
                            external_synopsis = poster_result[1] or ""
                    
                    # Use external synopsis if we got one, otherwise use app/channel info
                    if external_synopsis:
                        synopsis = f"{synopsis} — {external_synopsis}" if synopsis else external_synopsis
                    
                    self.current_state = DisplayState(
                        mode=DisplayMode.STREAMING,
                        title=display_title,
                        current_input=current_input,
                        source_name=input_name,
                        synopsis=synopsis,
                        poster_url=external_poster,
                        is_playing=is_media_playing,
                    )
                    return
        
        # Nothing playing, show coming soon
        if self.current_state.mode != DisplayMode.COMING_SOON:
            self._next_coming_soon()
        
        # Update current input even in coming soon mode
        self.current_state.current_input = current_input
    
    def get_state(self) -> dict:
        """Get current state as dict for API."""
        state = asdict(self.current_state)
        state["mode"] = self.current_state.mode.value
        
        # Calculate time remaining
        if self.current_state.duration_seconds > 0:
            remaining = self.current_state.duration_seconds - self.current_state.position_seconds
            state["remaining_seconds"] = max(0, remaining)
            state["progress_percent"] = min(100, (self.current_state.position_seconds / self.current_state.duration_seconds) * 100)
        else:
            state["remaining_seconds"] = 0
            state["progress_percent"] = 0
        
        return state


# Global server instance
server: Optional[PosterDisplayServer] = None


# =============================================================================
# API Handlers
# =============================================================================

async def handle_state(request):
    """API endpoint: GET /api/state"""
    if server is None:
        return web.json_response({"error": "Server not initialized"}, status=500)
    return web.json_response(server.get_state())


async def handle_refresh(request):
    """API endpoint: POST /api/refresh - Force refresh coming soon movies"""
    if server is None:
        return web.json_response({"error": "Server not initialized"}, status=500)
    await server._refresh_coming_soon()
    return web.json_response({"status": "ok", "count": len(server.coming_soon_movies)})


def sanitize_config_for_client(cfg: dict) -> dict:
    """Remove sensitive data before sending config to client."""
    import copy
    safe = copy.deepcopy(cfg)
    # Mask Plex token
    if "plex" in safe and safe["plex"].get("token"):
        safe["plex"]["token"] = "***" if safe["plex"]["token"] else ""
    return safe

async def handle_config_get(request):
    """API endpoint: GET /api/config"""
    return web.json_response(sanitize_config_for_client(config.get()))


async def handle_config_section_get(request):
    """API endpoint: GET /api/config/{section}"""
    section = request.match_info.get("section")
    data = config.get(section)
    if not data:
        return web.json_response({"error": f"Section '{section}' not found"}, status=404)
    return web.json_response(data)


async def handle_config_section_update(request):
    """API endpoint: POST /api/config/{section}"""
    section = request.match_info.get("section")
    try:
        data = await request.json()
    except json.JSONDecodeError:
        debug_log.log("config", f"Update {section}", "Invalid JSON", "error")
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    # Validate input data
    valid, error = validate_config_data(section, data)
    if not valid:
        debug_log.log("config", f"Validation failed for {section}", error, "error")
        return web.json_response({"error": error}, status=400)
    
    # Check if this is from discovery (has source field)
    source = data.pop("_source", None)
    source_ip = data.pop("_source_ip", None)
    
    # Check if this is a deletion (enabled=false or empty host)
    is_deletion = data.get("enabled") == False or data.get("host") == ""
    
    if source == "discovery":
        debug_log.log("discovery", f"Adding {section} from discovery", f"Host: {data.get('host', source_ip)}")
    elif is_deletion:
        debug_log.log("integration", f"Deleting {section}", f"Host was: {config.get(section).get('host', 'Unknown')}", "warning")
    
    debug_log.log("config", f"Update {section}", json.dumps(data, default=str)[:200])
    
    if config.update(section, data):
        if source == "discovery":
            debug_log.log("discovery", f"{section.title()} added successfully", f"Host: {data.get('host', 'Unknown')}", "success")
        elif is_deletion:
            debug_log.log("integration", f"{section.title()} deleted", "", "success")
        debug_log.log("config", f"Saved {section}", "Success", "success")
        return web.json_response({"status": "ok"})
    
    if source == "discovery":
        debug_log.log("discovery", f"Failed to add {section}", "", "error")
    debug_log.log("config", f"Save {section}", "Failed", "error")
    return web.json_response({"error": "Failed to save"}, status=500)


async def handle_input_set(request):
    """API endpoint: POST /api/config/input/{num}"""
    input_num = request.match_info.get("num")
    
    # Validate input number
    try:
        num = int(input_num)
        if not (1 <= num <= 20):
            return web.json_response({"error": "Input number must be 1-20"}, status=400)
    except ValueError:
        return web.json_response({"error": "Invalid input number"}, status=400)
    
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    # Validate input data
    valid, error = validate_config_data("input", data)
    if not valid:
        debug_log.log("integration", f"Validation failed for input {input_num}", error, "error")
        return web.json_response({"error": error}, status=400)
    
    # Check if this is from discovery (has source field)
    source = data.pop("_source", None)
    source_ip = data.pop("_source_ip", None)
    
    if source == "discovery":
        debug_log.log("discovery", f"Adding device from discovery", f"Input {input_num}: {data.get('name', 'Unknown')} ({source_ip})")
    
    debug_log.log("integration", f"Add/Update Input {input_num}", json.dumps(data, default=str)[:200])
    
    if config.set_input(input_num, data):
        if source == "discovery":
            debug_log.log("discovery", f"Device added successfully", f"Input {input_num}: {data.get('name', 'Unknown')}", "success")
        debug_log.log("integration", f"Input {input_num} saved", f"Name: {data.get('name', 'Unknown')}", "success")
        return web.json_response({"status": "ok"})
    
    if source == "discovery":
        debug_log.log("discovery", f"Failed to add device", f"Input {input_num}", "error")
    debug_log.log("integration", f"Input {input_num} save failed", "", "error")
    return web.json_response({"error": "Failed to save"}, status=500)


async def handle_input_delete(request):
    """API endpoint: DELETE /api/config/input/{num}"""
    input_num = request.match_info.get("num")
    debug_log.log("integration", f"Delete Input {input_num}", "")
    
    if config.remove_input(input_num):
        debug_log.log("integration", f"Input {input_num} deleted", "", "success")
        return web.json_response({"status": "ok"})
    
    debug_log.log("integration", f"Input {input_num} not found", "", "error")
    return web.json_response({"error": "Input not found"}, status=404)


# =============================================================================
# Page Handlers
# =============================================================================

async def handle_index(request):
    """Serve the frontend."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return web.FileResponse(frontend_path)
    return web.Response(text="Frontend not found", status=404)


async def handle_admin(request):
    """Serve the admin page."""
    admin_path = Path(__file__).parent.parent / "frontend" / "admin.html"
    if admin_path.exists():
        return web.FileResponse(admin_path)
    return web.Response(text="Admin page not found", status=404)


# =============================================================================
# App Setup
# =============================================================================

async def on_startup(app):
    """Initialize server on startup."""
    global server
    server = PosterDisplayServer()
    await server.start()
    
    # Set up discovery logging
    discovery.set_logger(lambda cat, action, details, level: debug_log.log(cat, action, details, level))
    debug_log.log("server", "Server started", "Poster Display backend ready", "success")


async def on_cleanup(app):
    """Cleanup on shutdown."""
    global server
    if server:
        await server.stop()



# =============================================================================
# Discovery API Handlers
# =============================================================================

async def handle_discover_scan(request):
    """API endpoint: POST /api/discover/scan - Start network scan"""
    if discovery.is_scanning:
        debug_log.log("discovery", "Scan requested", "Already in progress", "warning")
        return web.json_response({"error": "Scan already in progress"}, status=409)
    
    data = await request.json() if request.body_exists else {}
    subnets = data.get("subnets", None)
    
    debug_log.log("discovery", "Network scan started", f"Subnets: {subnets or 'auto-detect'}")
    
    # Start scan in background
    asyncio.create_task(discovery.scan_all(subnets))
    
    return web.json_response({"status": "scanning", "message": "Scan started"})


async def handle_discover_status(request):
    """API endpoint: GET /api/discover/status - Get scan status"""
    progress, total = discovery.scan_progress
    phase = discovery.scan_phase
    
    # Get configured IPs to filter out
    configured_ips = []
    if config.atlona_host:
        configured_ips.append(config.atlona_host)
    if config.kaleidescape_host:
        configured_ips.append(config.kaleidescape_host)
    if config.plex_host:
        configured_ips.append(config.plex_host)
    for inp in config.inputs.values():
        if inp.get("shield_host"):
            configured_ips.append(inp["shield_host"])
        if inp.get("appletv_host"):
            configured_ips.append(inp["appletv_host"])
    
    # Get Kaleidescape system name if configured (to filter related devices like Terra servers)
    kscape_system_name = None
    if config.kaleidescape_host:
        kscape_system_name = await discovery.get_kaleidescape_system_name(config.kaleidescape_host)
    
    # Filter results
    all_devices = discovery.results
    filtered = []
    for d in all_devices:
        # Skip already configured IPs
        if d["ip"] in configured_ips:
            continue
        
        # Skip Kaleidescape devices that are part of the same system (same FRIENDLY_SYSTEM_NAME)
        if d["integration_type"] == "kaleidescape" and kscape_system_name:
            device_system_name = d.get("details", {}).get("system_name")
            if device_system_name and device_system_name == kscape_system_name:
                continue
        
        filtered.append(d)
    
    # Add Plex players if enabled - but only scan once per discovery cycle
    if config.plex_include_players and config.plex_host and config.plex_token:
        # Only run Plex scan once after network scan completes (not on every poll)
        if not discovery.is_scanning and not discovery.plex_scanned:
            debug_log.log("discovery", "Scanning Plex for players", "Querying plex.tv for registered devices")
            try:
                from plex_client import PlexClient
                plex = PlexClient(config.plex_host, config.plex_port, config.plex_token)
                players = await plex.get_players()
                
                debug_log.log("discovery", f"Plex returned {len(players)} player(s)", 
                             ", ".join(p.get("name", "?") for p in players) if players else "None found")
                
                added_count = 0
                for player in players:
                    ip = player.get("address") or player.get("host")
                    if not ip:
                        continue
                        
                    if ip in configured_ips:
                        debug_log.log("discovery", f"Skipping {player.get('name')}", f"{ip} already configured")
                        continue
                    
                    # Check if already found in network scan
                    if any(d["ip"] == ip for d in filtered):
                        debug_log.log("discovery", f"Skipping {player.get('name')}", f"{ip} already in network results")
                        continue
                    
                    from discovery import DiscoveredDevice, IntegrationType
                    
                    is_android = plex.is_android_device(player)
                    is_appletv = plex.is_appletv_device(player)
                    
                    if is_android:
                        device_type = "Shield/Android TV"
                        int_type = IntegrationType.SHIELD
                        port = 5555
                    elif is_appletv:
                        device_type = "Apple TV"
                        int_type = IntegrationType.APPLETV
                        port = 7000
                    else:
                        device_type = "Plex Player"
                        int_type = IntegrationType.UNKNOWN
                        port = 0
                    
                    debug_log.log("discovery", f"Found via Plex: {player.get('name')}", 
                                 f"{ip} - {device_type} ({player.get('platform', 'unknown')})", "success")
                    
                    # Add to discovery's plex results
                    plex_device = DiscoveredDevice(
                        ip=ip,
                        integration_type=int_type,
                        name=player.get("name", "Unknown Player"),
                        port=port,
                        verified=True,
                        details={
                            "platform": player.get("platform"),
                            "product": player.get("product"),
                            "device": player.get("device"),
                            "machine_id": player.get("machine_id"),
                        }
                    )
                    discovery.add_plex_device(plex_device)
                    added_count += 1
                
                discovery.mark_plex_scanned()
                if added_count > 0:
                    debug_log.log("discovery", "Plex player scan complete", f"Added {added_count} player(s)", "success")
                else:
                    debug_log.log("discovery", "Plex player scan complete", "No new players found")
            except Exception as e:
                debug_log.log("discovery", "Plex player scan failed", str(e), "error")
                discovery.mark_plex_scanned()  # Mark as scanned even on failure to prevent retry spam
    
    # Now rebuild filtered list from discovery.results which includes both sources
    all_devices = discovery.results
    filtered = []
    for d in all_devices:
        if d["ip"] not in configured_ips:
            # Skip Kaleidescape devices that are part of the same system
            if d["integration_type"] == "kaleidescape" and kscape_system_name:
                device_system_name = d.get("details", {}).get("system_name")
                if device_system_name and device_system_name == kscape_system_name:
                    continue
            filtered.append(d)
    
    return web.json_response({
        "scanning": discovery.is_scanning,
        "progress": progress,
        "total": total,
        "phase": phase,
        "devices": filtered,
        "configured_ips": configured_ips,
    })


async def handle_discover_probe(request):
    """API endpoint: POST /api/discover/probe - Probe specific IP"""
    data = await request.json()
    ip = data.get("ip")
    
    if not ip:
        return web.json_response({"error": "IP address required"}, status=400)
    
    debug_log.log("discovery", f"Manual probe: {ip}", "")
    
    devices = await discovery.probe_ip(ip)
    
    if devices:
        debug_log.log("discovery", f"Probe {ip} found", f"{len(devices)} device(s): {', '.join(d.name for d in devices)}", "success")
    else:
        debug_log.log("discovery", f"Probe {ip}", "No devices found", "warning")
    
    return web.json_response({
        "ip": ip,
        "devices": [d.to_dict() for d in devices],
    })


async def handle_discover_subnets(request):
    """API endpoint: GET /api/discover/subnets - Get local subnets"""
    subnets = discovery.get_local_subnets()
    return web.json_response({"subnets": subnets})


async def handle_plex_players(request):
    """API endpoint: GET /api/plex/players - Get players registered with Plex"""
    if not config.plex_host or not config.plex_token:
        return web.json_response({"error": "Plex not configured"}, status=400)
    
    from plex_client import PlexClient
    plex = PlexClient(config.plex_host, config.plex_port, config.plex_token)
    
    try:
        players = await plex.get_players()
        # Mark Android/Shield devices
        for player in players:
            player["is_android"] = plex.is_android_device(player)
        return web.json_response({"players": players})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_shield_enroll(request):
    """API endpoint: POST /api/shield/enroll - Attempt ADB enrollment with Shield"""
    data = await request.json()
    ip = data.get("ip")
    
    if not ip:
        return web.json_response({"error": "IP address required"}, status=400)
    
    debug_log.log("integration", f"Shield ADB enrollment: {ip}", "Connecting...")
    
    # Try to connect - this will trigger the authorization prompt on the Shield
    try:
        client = ShieldClient(ip, 5555)
        success = client.connect()
        
        if success:
            # Get some info to confirm it worked
            state = client.get_state()
            client.disconnect()
            debug_log.log("integration", f"Shield {ip} enrolled", f"Running: {state.app_name}", "success")
            return web.json_response({
                "status": "ok",
                "message": "ADB enrollment successful",
                "connected": True,
                "app_name": state.app_name,
            })
        else:
            debug_log.log("integration", f"Shield {ip} pending", "Check TV for auth prompt", "warning")
            return web.json_response({
                "status": "pending",
                "message": "Connection attempted. Check Shield for authorization prompt.",
                "connected": False,
            })
    except Exception as e:
        debug_log.log("integration", f"Shield {ip} failed", str(e), "error")
        return web.json_response({
            "status": "error",
            "message": str(e),
            "connected": False,
        }, status=500)


# Apple TV pairing state (temporary, per-IP)
_appletv_pairing_clients = {}


async def handle_appletv_pair_start(request):
    """API endpoint: POST /api/appletv/pair/start - Start Apple TV pairing"""
    data = await request.json()
    ip = data.get("ip")
    protocol = data.get("protocol", "companion")  # companion is best for media detection
    
    if not ip:
        return web.json_response({"error": "IP address required"}, status=400)
    
    debug_log.log("integration", f"Apple TV pairing: {ip}", f"Starting {protocol} pairing...")
    
    try:
        # Create or reuse client for this IP
        if ip not in _appletv_pairing_clients:
            client = AppleTVClient(ip)
            client.set_logger(debug_log.log)
            _appletv_pairing_clients[ip] = client
        else:
            client = _appletv_pairing_clients[ip]
        
        result = await client.start_pairing(protocol)
        
        if result.get("success"):
            debug_log.log("integration", f"Apple TV {ip}", "Waiting for PIN entry", "info")
        else:
            debug_log.log("integration", f"Apple TV {ip}", result.get("error", "Unknown error"), "error")
        
        return web.json_response(result)
        
    except Exception as e:
        debug_log.log("integration", f"Apple TV {ip} pairing failed", str(e), "error")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_appletv_pair_finish(request):
    """API endpoint: POST /api/appletv/pair/finish - Complete Apple TV pairing with PIN"""
    data = await request.json()
    ip = data.get("ip")
    pin = data.get("pin")
    next_protocol = data.get("next_protocol")  # Optional: chain to another protocol
    
    if not ip:
        return web.json_response({"error": "IP address required"}, status=400)
    if not pin:
        return web.json_response({"error": "PIN required"}, status=400)
    
    debug_log.log("integration", f"Apple TV {ip}", f"Completing pairing with PIN...")
    
    try:
        if ip not in _appletv_pairing_clients:
            return web.json_response({"success": False, "error": "No pairing in progress for this device"}, status=400)
        
        client = _appletv_pairing_clients[ip]
        result = await client.finish_pairing(pin, next_protocol)
        
        if result.get("success"):
            if result.get("partial"):
                # Still have another protocol to pair
                debug_log.log("integration", f"Apple TV {ip}", f"Companion paired, now pairing {next_protocol}...", "success")
            else:
                debug_log.log("integration", f"Apple TV {ip} paired", "Ready for media detection", "success")
                # Clean up only when fully done
                del _appletv_pairing_clients[ip]
        else:
            debug_log.log("integration", f"Apple TV {ip}", result.get("error", "Pairing failed"), "error")
        
        return web.json_response(result)
        
    except Exception as e:
        debug_log.log("integration", f"Apple TV {ip} pairing failed", str(e), "error")
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_appletv_pair_cancel(request):
    """API endpoint: POST /api/appletv/pair/cancel - Cancel Apple TV pairing"""
    data = await request.json()
    ip = data.get("ip")
    
    if ip and ip in _appletv_pairing_clients:
        client = _appletv_pairing_clients[ip]
        await client.cancel_pairing()
        del _appletv_pairing_clients[ip]
        debug_log.log("integration", f"Apple TV {ip}", "Pairing cancelled")
    
    return web.json_response({"success": True})


async def handle_appletv_status(request):
    """API endpoint: GET /api/appletv/status - Check Apple TV pairing status"""
    ip = request.query.get("ip")
    
    if not ip:
        return web.json_response({"error": "IP address required"}, status=400)
    
    try:
        client = AppleTVClient(ip)
        client.set_logger(debug_log.log)
        status = await client.check_pairing_status()
        return web.json_response(status)
    except Exception as e:
        return web.json_response({"available": False, "error": str(e)}, status=500)


async def handle_debug_logs(request):
    """API endpoint: GET /api/debug/logs - Get debug log entries"""
    limit = int(request.query.get("limit", 100))
    category = request.query.get("category", None)
    entries = debug_log.get_entries(limit=limit, category=category)
    return web.json_response({"entries": entries})


async def handle_debug_clear(request):
    """API endpoint: POST /api/debug/clear - Clear debug logs"""
    debug_log.clear()
    debug_log.log("debug", "Logs cleared", "", "info")
    return web.json_response({"status": "ok"})


async def handle_version(request):
    """API endpoint: GET /api/version - Get server version"""
    return web.json_response({"version": VERSION})


async def handle_restart(request):
    """API endpoint: POST /api/restart - Restart the server"""
    debug_log.log("server", "Restart requested", "Server will restart in 1 second", "info")
    
    async def delayed_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    asyncio.create_task(delayed_restart())
    return web.json_response({"status": "ok", "message": "Server restarting..."})


async def handle_integrations_status(request):
    """API endpoint: GET /api/integrations/status - Get status of configured integrations"""
    integrations = []
    
    debug_log.log("integration", "Verifying integrations", "Starting verification of configured integrations")
    
    # Atlona
    if config.atlona_host:
        debug_log.log("integration", f"Verifying Atlona", f"Host: {config.atlona_host}")
        device = await discovery.probe_atlona(config.atlona_host, log_details=True)
        status = "Online" if device else "Offline"
        debug_log.log("integration", f"Atlona status: {status}", config.atlona_host, "success" if device else "warning")
        integrations.append({
            "type": "atlona",
            "name": config._config.get("atlona", {}).get("name", "Atlona Matrix"),
            "host": config.atlona_host,
            "port": config.atlona_port,
            "verified": device is not None,
            "configured": True,
        })
    
    # Kaleidescape
    if config.kaleidescape_host:
        debug_log.log("integration", f"Verifying Kaleidescape", f"Host: {config.kaleidescape_host}")
        device = await discovery.probe_kaleidescape(config.kaleidescape_host, log_details=True)
        status = "Online" if device else "Offline"
        debug_log.log("integration", f"Kaleidescape status: {status}", config.kaleidescape_host, "success" if device else "warning")
        
        # Get current playback state
        now_playing = None
        playback_state = "idle"
        if server and server.kaleidescape:
            try:
                movie = await server.kaleidescape.get_now_playing()
                if movie and movie.title:
                    if movie.is_playing:
                        now_playing = movie.title
                        playback_state = "playing"
                    elif movie.play_status:
                        now_playing = f"{movie.play_status}: {movie.title}"
                        playback_state = movie.play_status.lower()
            except Exception as e:
                debug_log.log("integration", f"Kaleidescape playback check failed", str(e), "warning")
        
        integrations.append({
            "type": "kaleidescape",
            "name": device.name if device else config._config.get("kaleidescape", {}).get("name", "Kaleidescape"),
            "host": config.kaleidescape_host,
            "port": config.kaleidescape_port,
            "verified": device is not None,
            "configured": True,
            "playback_state": playback_state,
            "now_playing": now_playing,
        })
    
    # Plex
    if config.plex_host:
        debug_log.log("integration", f"Verifying Plex", f"Host: {config.plex_host}")
        device = await discovery.probe_plex(config.plex_host, log_details=True)
        status = "Online" if device else "Offline"
        debug_log.log("integration", f"Plex status: {status}", config.plex_host, "success" if device else "warning")
        integrations.append({
            "type": "plex",
            "name": device.name if device else config._config.get("plex", {}).get("name", "Plex"),
            "host": config.plex_host,
            "port": config.plex_port,
            "verified": device is not None,
            "configured": True,
        })
    
    # Shields from inputs
    for num, inp in config.inputs.items():
        if inp.get("shield_host"):
            debug_log.log("integration", f"Verifying Shield (Input {num})", f"Host: {inp['shield_host']}")
            device = await discovery.probe_shield(inp["shield_host"], log_details=True)
            status = "Online" if device else "Offline"
            debug_log.log("integration", f"Shield status: {status}", inp["shield_host"], "success" if device else "warning")
            
            # Get current playback state
            now_playing = None
            playback_state = "idle"
            if server and int(num) in server.shield_clients:
                try:
                    shield = server.shield_clients[int(num)]
                    state = shield.get_state()
                    if state.is_connected:
                        if state.is_media_playing and state.media_title:
                            now_playing = state.media_title
                            playback_state = "playing"
                            if state.app_name:
                                now_playing += f" ({state.app_name})"
                        elif state.app_name:
                            playback_state = "idle"
                            now_playing = f"On {state.app_name}"
                except Exception as e:
                    debug_log.log("integration", f"Shield playback check failed", str(e), "warning")
            
            integrations.append({
                "type": "shield",
                "name": inp.get("name", f"Shield (Input {num})"),
                "host": inp["shield_host"],
                "port": 5555,
                "input_num": num,
                "verified": device is not None,
                "configured": True,
                "playback_state": playback_state,
                "now_playing": now_playing,
            })
    
    # Apple TVs from inputs
    for num, inp in config.inputs.items():
        if inp.get("appletv_host"):
            debug_log.log("integration", f"Verifying Apple TV (Input {num})", f"Host: {inp['appletv_host']}")
            device = await discovery.probe_appletv(inp["appletv_host"], log_details=True)
            status = "Online" if device else "Offline"
            debug_log.log("integration", f"Apple TV status: {status}", inp["appletv_host"], "success" if device else "warning")
            
            # Check pairing status
            paired = False
            try:
                atv_client = AppleTVClient(inp["appletv_host"])
                pairing_status = await atv_client.check_pairing_status()
                if pairing_status.get("protocols"):
                    # Consider paired if companion protocol is paired (best for media detection)
                    companion = pairing_status["protocols"].get("companion", {})
                    paired = companion.get("paired", False)
            except:
                pass
            
            # Get current playback state
            now_playing = None
            playback_state = "idle"
            if server and int(num) in server.appletv_clients:
                try:
                    atv = server.appletv_clients[int(num)]
                    media = await atv.get_playing()
                    if media and media.title:
                        if media.state == "playing":
                            now_playing = media.title
                            playback_state = "playing"
                            if media.app_name:
                                now_playing += f" ({media.app_name})"
                        elif media.state == "paused":
                            now_playing = f"Paused: {media.title}"
                            playback_state = "paused"
                        else:
                            now_playing = f"On {media.app_name}" if media.app_name else None
                except Exception as e:
                    debug_log.log("integration", f"Apple TV playback check failed", str(e), "warning")
            
            integrations.append({
                "type": "appletv",
                "name": inp.get("name", f"Apple TV (Input {num})"),
                "host": inp["appletv_host"],
                "port": 7000,
                "input_num": num,
                "verified": device is not None,
                "paired": paired,
                "configured": True,
                "playback_state": playback_state,
                "now_playing": now_playing,
            })
    
    debug_log.log("integration", "Verification complete", f"{len(integrations)} integration(s) checked", "success")
    
    return web.json_response({"integrations": integrations})


def create_app() -> web.Application:
    """Create the web application."""
    app = web.Application()
    
    # API routes - state
    app.router.add_get("/api/state", handle_state)
    app.router.add_post("/api/refresh", handle_refresh)
    
    # API routes - config
    app.router.add_get("/api/config", handle_config_get)
    app.router.add_get("/api/config/{section}", handle_config_section_get)
    app.router.add_post("/api/config/{section}", handle_config_section_update)
    app.router.add_post("/api/config/input/{num}", handle_input_set)
    app.router.add_delete("/api/config/input/{num}", handle_input_delete)

    # API routes - discovery
    app.router.add_post("/api/discover/scan", handle_discover_scan)
    app.router.add_get("/api/discover/status", handle_discover_status)
    app.router.add_post("/api/discover/probe", handle_discover_probe)
    app.router.add_get("/api/discover/subnets", handle_discover_subnets)
    app.router.add_get("/api/integrations/status", handle_integrations_status)
    app.router.add_post("/api/shield/enroll", handle_shield_enroll)
    app.router.add_post("/api/appletv/pair/start", handle_appletv_pair_start)
    app.router.add_post("/api/appletv/pair/finish", handle_appletv_pair_finish)
    app.router.add_post("/api/appletv/pair/cancel", handle_appletv_pair_cancel)
    app.router.add_get("/api/appletv/status", handle_appletv_status)
    app.router.add_get("/api/plex/players", handle_plex_players)
    
    # Debug routes
    app.router.add_get("/api/debug/logs", handle_debug_logs)
    app.router.add_post("/api/debug/clear", handle_debug_clear)
    
    # System routes
    app.router.add_get("/api/version", handle_version)
    app.router.add_post("/api/restart", handle_restart)
    
    # Static files
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if (frontend_dir / "static").exists():
        app.router.add_static("/static", frontend_dir / "static", show_index=False)
    
    # Pages
    app.router.add_get("/", handle_index)
    app.router.add_get("/admin", handle_admin)
    
    # Lifecycle
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8080)
