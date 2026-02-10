"""Configuration for the Movie Poster Display.

NOTE: These are legacy defaults. Actual configuration is loaded from config.json.
These values are only used as fallbacks if config.json is missing or incomplete.
"""

# Atlona Matrix
ATLONA_HOST = ""
ATLONA_PORT = 23
MEDIA_ROOM_OUTPUT = 1

# Input mapping (legacy - now configured via config.json inputs)
INPUT_KALEIDESCAPE = 2
INPUT_SHIELD_1 = 1
INPUT_SHIELD_4 = 4
SHIELD_INPUTS = [INPUT_SHIELD_1, INPUT_SHIELD_4]

# Kaleidescape
KALEIDESCAPE_HOST = ""
KALEIDESCAPE_PORT = 10000

# Plex
PLEX_HOST = ""
PLEX_PORT = 32400
PLEX_TOKEN = ""

# Display settings
COMING_SOON_INTERVAL = 15  # seconds between poster rotations
POLL_INTERVAL = 3  # seconds between status checks

# Plex libraries for "Coming Soon" posters (movie libraries only)
COMING_SOON_LIBRARIES = []
