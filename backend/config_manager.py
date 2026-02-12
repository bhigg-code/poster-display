"""Configuration manager with persistence and runtime updates."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


CONFIG_FILE = Path(__file__).parent.parent / "config.json"

# Default configuration (blank - user configures via admin UI)
DEFAULT_CONFIG = {
    "atlona": {
        "name": "Atlona Matrix",
        "host": "",
        "port": 23,
        "media_room_output": 1,
        "enabled": False,
        "use_broker": False,
        "broker_host": "localhost",
        "broker_port": 2323,
    },
    "inputs": {},
    "kaleidescape": {
        "name": "Kaleidescape",
        "host": "",
        "port": 10000,
        "enabled": False,
    },
    "plex": {
        "name": "Plex Server",
        "host": "",
        "port": 32400,
        "token": "",
        "libraries": [],
        "enabled": False,
    },
    "display": {
        "coming_soon_interval": 15,
        "poll_interval": 3,
        "orientation": "portrait",
    },
}


class ConfigManager:
    """Manages configuration with file persistence."""
    
    def __init__(self, config_file: Path = CONFIG_FILE):
        self.config_file = config_file
        self._config: dict = {}
        self._callbacks: list = []
        self.load()
    
    def load(self) -> dict:
        """Load config from file, or create default."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self._config = json.load(f)
                print(f"Loaded config from {self.config_file}")
            except Exception as e:
                print(f"Error loading config: {e}, using defaults")
                self._config = DEFAULT_CONFIG.copy()
        else:
            self._config = DEFAULT_CONFIG.copy()
            self.save()
        return self._config
    
    def save(self) -> bool:
        """Save current config to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self._config, f, indent=2)
            print(f"Saved config to {self.config_file}")
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def get(self, section: Optional[str] = None) -> dict:
        """Get config section or full config."""
        if section:
            return self._config.get(section, {})
        return self._config
    
    def update(self, section: str, data: dict) -> bool:
        """Update a config section."""
        if section not in self._config:
            self._config[section] = {}
        
        self._config[section].update(data)
        success = self.save()
        
        if success:
            self._notify_callbacks(section)
        
        return success
    
    def set_input(self, input_num: str, data: dict) -> bool:
        """Set or update an input configuration."""
        if "inputs" not in self._config:
            self._config["inputs"] = {}
        
        self._config["inputs"][input_num] = data
        return self.save()
    
    def remove_input(self, input_num: str) -> bool:
        """Remove an input configuration."""
        if "inputs" in self._config and input_num in self._config["inputs"]:
            del self._config["inputs"][input_num]
            return self.save()
        return False
    
    def on_change(self, callback):
        """Register a callback for config changes."""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, section: str):
        """Notify all registered callbacks of a change."""
        for callback in self._callbacks:
            try:
                callback(section, self._config)
            except Exception as e:
                print(f"Config callback error: {e}")
    
    # Convenience properties
    @property
    def atlona_host(self) -> str:
        return self._config.get("atlona", {}).get("host", "")
    
    @property
    def atlona_port(self) -> int:
        return self._config.get("atlona", {}).get("port", 23)
    
    @property
    def atlona_use_broker(self) -> bool:
        return self._config.get("atlona", {}).get("use_broker", False)
    
    @property
    def atlona_broker_host(self) -> str:
        return self._config.get("atlona", {}).get("broker_host", "localhost")
    
    @property
    def atlona_broker_port(self) -> int:
        return self._config.get("atlona", {}).get("broker_port", 2323)
    
    @property
    def media_room_output(self) -> int:
        return self._config.get("atlona", {}).get("media_room_output", 9)
    
    @property
    def kaleidescape_host(self) -> str:
        return self._config.get("kaleidescape", {}).get("host", "")
    
    @property
    def kaleidescape_port(self) -> int:
        return self._config.get("kaleidescape", {}).get("port", 10000)
    
    @property
    def plex_host(self) -> str:
        return self._config.get("plex", {}).get("host", "")
    
    @property
    def plex_port(self) -> int:
        return self._config.get("plex", {}).get("port", 32400)
    
    @property
    def plex_token(self) -> str:
        return self._config.get("plex", {}).get("token", "")
    
    @property
    def plex_libraries(self) -> list:
        return self._config.get("plex", {}).get("libraries", [])
    
    @property
    def plex_include_players(self) -> bool:
        return self._config.get("plex", {}).get("include_players_in_discovery", False)
    
    @property
    def inputs(self) -> dict:
        return self._config.get("inputs", {})
    
    @property
    def kaleidescape_input(self) -> Optional[int]:
        """Find which input is configured as Kaleidescape."""
        for num, cfg in self.inputs.items():
            if cfg.get("type") == "kaleidescape":
                return int(num)
        return None
    
    @property
    def plex_inputs(self) -> list[int]:
        """Get list of inputs configured for Plex."""
        return [int(num) for num, cfg in self.inputs.items() if cfg.get("type") == "plex"]
    
    @property
    def poll_interval(self) -> int:
        return self._config.get("display", {}).get("poll_interval", 3)
    
    @property
    def atlona_poll_interval(self) -> int:
        """Separate poll interval for Atlona (to avoid exhausting connections)."""
        return self._config.get("atlona", {}).get("poll_interval", 15)
    
    @property
    def coming_soon_interval(self) -> int:
        return self._config.get("display", {}).get("coming_soon_interval", 15)
    
    @property
    def atlona_enabled(self) -> bool:
        """Check if Atlona is configured and enabled."""
        atlona = self._config.get("atlona", {})
        return bool(atlona.get("host")) and atlona.get("enabled", False)
    
    @property
    def kaleidescape_enabled(self) -> bool:
        """Check if Kaleidescape is configured and enabled."""
        kscape = self._config.get("kaleidescape", {})
        return bool(kscape.get("host")) and kscape.get("enabled", False)
    
    @property
    def default_display(self) -> Optional[str]:
        """Get the default display device type (used when no Atlona)."""
        return self._config.get("display", {}).get("default_display")
    
    @property
    def default_input(self) -> Optional[str]:
        """Get the default input number (used when no Atlona)."""
        return self._config.get("display", {}).get("default_input")
    
    def set_default_display(self, device_type: str) -> bool:
        """Set the default display device."""
        if "display" not in self._config:
            self._config["display"] = {}
        self._config["display"]["default_display"] = device_type
        return self.save()


# Global instance
config = ConfigManager()
