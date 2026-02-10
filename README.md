# Movie Poster Display

A Raspberry Pi-powered movie poster display for home theaters. Shows what's currently playing on your media sources with a theater-style aesthetic.

## Features

- **Now Playing Mode**: Displays current movie poster with progress bar when watching via:
  - Kaleidescape (direct integration)
  - Plex on Nvidia Shield (via Plex API)
  - Apple TV (via pyatv)
  
- **Coming Soon Mode**: Rotates through random movie posters from your Plex library when nothing is playing

- **Streaming Mode**: Shows YouTube thumbnails and other streaming content

- **Smart Source Detection**: Monitors Atlona matrix switcher to detect which source is active

- **Web Admin UI**: Configure integrations and inputs via browser

## Hardware Requirements

- Raspberry Pi 4 (recommended) or Pi 3
- Display (27" portrait orientation recommended)
- HDMI cable
- Network connection to your media devices

## Supported Integrations

- **Atlona Matrix Switcher** - Source routing detection
- **Kaleidescape** - Movie playback with poster/progress
- **Plex Media Server** - Library for "Coming Soon" posters
- **Nvidia Shield** - ADB-based app detection
- **Apple TV** - Media detection via pyatv

## Installation

1. Flash Raspberry Pi OS (with Desktop) to your SD card
2. Enable SSH and configure WiFi
3. Boot the Pi and SSH in
4. Clone this project:

```bash
git clone https://github.com/yourusername/poster-display.git
cd poster-display
```

5. Create virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

6. Set up the systemd service:

```bash
sudo cp scripts/poster-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable poster-display
sudo systemctl start poster-display
```

7. Configure via the Admin UI at `http://<pi-ip>:8080/admin`

## Configuration

All configuration is done through the **Admin UI** at `http://<pi-ip>:8080/admin`:

1. **Network Discovery** - Scan your network to find devices
2. **Integrations** - View and manage connected devices
3. **Configurations** - Edit device settings and input mappings
4. **Debug** - View real-time logs

Configuration is stored in `config.json` and persists across restarts.

## Architecture

```
┌─────────────────────────────────────────┐
│  Frontend (Chromium Kiosk)              │
│  - Full-screen movie poster             │
│  - Progress bar with time remaining     │
│  - Theater-style gold/black theme       │
└─────────────────────────────────────────┘
              ▲ HTTP (localhost:8080)
              │
┌─────────────────────────────────────────┐
│  Backend (Python/aiohttp)               │
│  - Polls Atlona for routing status      │
│  - Queries Kaleidescape for now-playing │
│  - Queries Plex for Shield sessions     │
│  - Queries Apple TV for media state     │
│  - Serves poster URLs and progress      │
└─────────────────────────────────────────┘
```

## API Endpoints

- `GET /` - Frontend display
- `GET /admin` - Admin configuration UI
- `GET /api/state` - Current display state (JSON)
- `GET /api/config` - Get configuration
- `POST /api/config/{section}` - Update configuration section
- `POST /api/discover/scan` - Start network discovery
- `GET /api/discover/status` - Get discovery status

## Service Management

```bash
# Check status
systemctl status poster-display

# View logs
journalctl -u poster-display -f

# Restart
sudo systemctl restart poster-display
```

## Customization

### Display Orientation

The display is configured for portrait (1080x1920). To change:

1. Edit kiosk script and modify window size
2. Adjust CSS in `frontend/static/style.css`

### Theme

Modify `frontend/static/style.css` to customize:
- Colors (gold accent, background)
- Fonts
- Poster frame style
- Progress bar appearance

## Troubleshooting

### Poster not updating
- Check backend logs: `journalctl -u poster-display -f`
- Verify network connectivity to your devices
- Check `/api/state` endpoint in browser

### Black screen
- Ensure backend is running: `systemctl status poster-display`
- Check if Chromium started: `ps aux | grep chromium`

### Device not detected
- Use the Admin UI Network Discovery to scan for devices
- Check the Debug tab for connection errors
- Verify the device IP is reachable from the Pi

---

Built with ❤️ for the home theater
