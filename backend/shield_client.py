"""Nvidia Shield TV integration via ADB."""

import os
import re
from dataclasses import dataclass
from typing import Optional

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner


# Map package names to friendly app names
APP_NAMES = {
    # Google
    'com.google.android.youtube.tv': 'YouTube',
    'com.google.android.youtube.tvunplugged': 'YouTube TV',
    'com.google.android.tvlauncher': 'Home',
    'com.google.android.katniss': 'Google TV',
    'com.google.android.videos': 'Google Play Movies',
    # Streaming services
    'com.netflix.ninja': 'Netflix',
    'com.amazon.amazonvideo.livingroom': 'Prime Video', 
    'com.disney.disneyplus': 'Disney+',
    'com.hulu.livingroomplus': 'Hulu',
    'com.apple.atve.androidtv.appletv': 'Apple TV+',
    'com.hbo.hbonow': 'Max',
    'com.wbd.stream': 'Max',
    'com.peacocktv.peacockandroid': 'Peacock',
    'com.cbs.ott': 'Paramount+',
    'com.paramount.androidtv': 'Paramount+',
    'com.plexapp.android': 'Plex',
    'com.showtime.standalone': 'Showtime',
    'com.starz.starzplay.android': 'Starz',
    'com.crunchyroll.crunchyroid': 'Crunchyroll',
    'com.espn.score_center': 'ESPN',
    'com.bamnetworks.mlb.tv': 'MLB.TV',
    'com.nfl.android.league': 'NFL',
    'tv.twitch.android.app': 'Twitch',
    'com.vudu.vuduapp': 'Vudu',
    'com.fandangonow.android': 'Fandango at Home',
    'com.tubitv': 'Tubi',
    'com.pluto.tv': 'Pluto TV',
    'com.roku.web.trc': 'The Roku Channel',
    # Media players
    'com.mxtech.videoplayer.ad': 'MX Player',
    'org.videolan.vlc': 'VLC',
    'com.archos.mediacenter.videofree': 'Archos Video',
}


@dataclass
class ShieldState:
    """Current state of Shield TV."""
    is_connected: bool
    app_package: str = ''
    app_name: str = ''
    media_title: str = ''
    media_artist: str = ''
    is_media_playing: bool = False
    device_name: str = ''


class ShieldClient:
    """Nvidia Shield TV client using ADB."""
    
    def __init__(self, host: str, port: int = 5555):
        self.host = host
        self.port = port
        self._device: Optional[AdbDeviceTcp] = None
        self._signer: Optional[PythonRSASigner] = None
        self._connected = False
        self._init_keys()
    
    def _init_keys(self):
        """Initialize or load ADB keys."""
        keypath = os.path.expanduser('~/.android/adb_py_key')
        if not os.path.exists(keypath):
            os.makedirs(os.path.dirname(keypath), exist_ok=True)
            keygen(keypath)
        
        with open(keypath, 'rb') as f:
            priv = f.read()
        with open(keypath + '.pub', 'rb') as f:
            pub = f.read()
        self._signer = PythonRSASigner(pub, priv)
    
    def connect(self) -> bool:
        """Connect to Shield."""
        if self._connected and self._device:
            return True
        
        try:
            self._device = AdbDeviceTcp(self.host, self.port, default_transport_timeout_s=10)
            self._device.connect(rsa_keys=[self._signer], auth_timeout_s=10)
            self._connected = True
            return True
        except Exception as e:
            print(f'Shield connection error: {e}')
            self._connected = False
            return False
    
    def disconnect(self):
        """Disconnect from Shield."""
        if self._device:
            try:
                self._device.close()
            except:
                pass
        self._device = None
        self._connected = False
    
    def get_foreground_app(self) -> Optional[str]:
        """Get the package name of the foreground app."""
        if not self._connected:
            if not self.connect():
                return None
        
        try:
            result = self._device.shell('dumpsys window | grep mCurrentFocus')
            # Parse: mCurrentFocus=Window{... com.package.name/...}
            if 'mCurrentFocus' in result:
                parts = result.split()
                for part in parts:
                    if '/' in part and '}' in part:
                        package = part.split('/')[0]
                        return package
        except Exception as e:
            print(f'Shield foreground query error: {e}')
            self._connected = False
        return None
    
    def get_media_info(self) -> tuple[str, str, bool]:
        """Get current media title, artist, and whether it's actively playing from media session.
        
        Returns: (title, artist, is_playing)
        """
        if not self._connected:
            if not self.connect():
                return '', '', False
        
        try:
            result = self._device.shell('dumpsys media_session')
            
            # Check playback state - look for "state=3" (PLAYING) or "state=PLAYING"
            # States: 0=NONE, 1=STOPPED, 2=PAUSED, 3=PLAYING, 6=BUFFERING
            is_playing = False
            lines = result.split('\n')
            
            for line in lines:
                # Check for active playback state
                if 'state=3' in line or 'state=PLAYING' in line:
                    is_playing = True
                    break
                # Also check for PlaybackState with playing
                if 'PlaybackState' in line and ('state=3' in line or 'PLAYING' in line):
                    is_playing = True
                    break
            
            # Look for metadata line with description
            # Format: metadata: size=N, description=Title, Artist, Album
            title = ''
            artist = ''
            for line in lines:
                if 'metadata: size=' in line and 'description=' in line:
                    match = re.search(r'description=([^,]+)(?:,\s*([^,]+))?', line)
                    if match:
                        title = match.group(1).strip() if match.group(1) else ''
                        artist = match.group(2).strip() if match.group(2) else ''
                        if title and title != 'null':
                            break
            
            return title, artist, is_playing
        except Exception as e:
            print(f'Shield media query error: {e}')
            return '', '', False
    
    def get_state(self) -> ShieldState:
        """Get current Shield state."""
        if not self.connect():
            return ShieldState(is_connected=False)
        
        package = self.get_foreground_app()
        if not package:
            return ShieldState(is_connected=True)
        
        app_name = APP_NAMES.get(package, package.split('.')[-1].title())
        
        # Get media info (only returns title if actively playing)
        media_title, media_artist, is_playing = self.get_media_info()
        
        # Only report media title if it's actually playing
        # This prevents showing stale cached info
        if not is_playing:
            media_title = ''
            media_artist = ''
        
        return ShieldState(
            is_connected=True,
            app_package=package,
            app_name=app_name,
            media_title=media_title,
            media_artist=media_artist,
            is_media_playing=is_playing,
        )
