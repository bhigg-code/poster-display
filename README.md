# Movie Poster Display

**Version 1.2.0**

A Raspberry Pi-powered movie poster display for home theaters. Shows what's currently playing on your media sources with a theater-style aesthetic.

## Features

- **Now Playing Mode**: Displays current movie poster with progress bar when watching via:
  - Kaleidescape (direct integration)
  - Plex on Nvidia Shield (via Plex API)
  - Apple TV (via pyatv)
  
- **Coming Soon Mode**: Rotates through random movie posters from your Plex library when nothing is playing

- **Streaming Mode**: Shows YouTube thumbnails and other streaming content

- **Smart Source Detection**: Monitors Atlona matrix switcher to detect which source is active

- **Atlona Broker Service**: Multiplexes Atlona connections to avoid connection limits

- **Mobile-Friendly Admin UI**: Configure integrations via browser on any device

## Hardware Requirements

- Raspberry Pi 4 (recommended) or Pi 3
- Display (27" portrait orientation recommended)
- HDMI cable
- Network connection to your media devices

## Supported Integrations

| Integration | Purpose |
|-------------|---------|
| **Atlona Matrix Switcher** | Source routing detection |
| **Kaleidescape** | Movie playback with poster/progress |
| **Plex Media Server** | Library for "Coming Soon" posters |
| **Nvidia Shield** | ADB-based media detection |
| **Apple TV** | Media detection via pyatv |

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/bhigg-code/poster-display.git
cd poster-display
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Create Configuration

```bash
cp config.json.example config.json
```

### 4. Start the Server

```bash
cd backend
python server.py
```

The server runs on `http://localhost:8080`

### 5. (Optional) Set Up Systemd Service

```bash
sudo cp scripts/poster-display.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable poster-display
sudo systemctl start poster-display
```

## Configuration

All configuration is done through the **Admin UI** at `http://<host>:8080/admin.html`:

1. **Integrations** - View and manage connected devices
2. **Network Discovery** - Scan your network to find devices
3. **Settings** - Configure display timing and system options

Configuration is stored in `config.json` (gitignored for security).

### Atlona Broker (Recommended)

If multiple services need to access your Atlona matrix switcher, use the broker to avoid connection limit issues:

```bash
# Start the broker
python backend/atlona_broker.py --host <ATLONA_IP> --port 23 --listen-port 2323

# In Admin UI, enable "Use Broker" and set broker host/port
```

## Architecture

```
┌─────────────────────────────────────────┐
│  Frontend (Browser/Kiosk)               │
│  - Full-screen movie poster             │
│  - Progress bar with time remaining     │
│  - Theater-style gold/black theme       │
└─────────────────────────────────────────┘
              ▲ HTTP (:8080)
              │
┌─────────────────────────────────────────┐
│  Backend (Python/aiohttp)               │
│  - Polls Atlona for routing status      │
│  - Queries Kaleidescape for now-playing │
│  - Queries Plex for sessions            │
│  - Queries Apple TV via pyatv           │
│  - Serves poster URLs and progress      │
└─────────────────────────────────────────┘
              ▲ (optional)
              │
┌─────────────────────────────────────────┐
│  Atlona Broker (atlona_broker.py)       │
│  - Single persistent Atlona connection  │
│  - Multiplexes requests from clients    │
└─────────────────────────────────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Frontend display |
| `/admin.html` | GET | Admin configuration UI |
| `/api/state` | GET | Current display state |
| `/api/config` | GET | Get configuration |
| `/api/config/{section}` | POST | Update configuration |
| `/api/integrations/status` | GET | Integration health check |
| `/api/discover/scan` | POST | Start network discovery |
| `/api/discover/status` | GET | Discovery progress |
| `/api/version` | GET | Server version |

## Service Management

```bash
# Check status
systemctl status poster-display

# View logs
journalctl -u poster-display -f

# Restart
sudo systemctl restart poster-display
```

## Security Notes

- `config.json` is gitignored (contains Plex tokens)
- Use `config.json.example` as a template
- Plex tokens are masked in API responses
- Admin UI has input validation
- See `SECURITY_SCAN.md` for full audit

## Troubleshooting

### Poster not updating
- Check backend logs: `journalctl -u poster-display -f`
- Verify network connectivity to devices
- Check Debug tab in Admin UI

### Atlona "No connections available"
- Enable broker mode in Admin UI
- Or restart the Atlona to clear stale connections

### Device not detected
- Use Network Discovery in Admin UI
- Check Debug tab for connection errors
- Verify device IP is reachable

## Changelog

### v1.2.0
- Added Atlona broker service for connection multiplexing
- Added broker configuration to Admin UI
- Mobile-friendly admin interface
- Security hardening (input validation, XSS protection)
- Added security scan report

### v1.1.0
- Added Apple TV support via pyatv
- Network discovery improvements
- Admin UI enhancements

### v1.0.0
- Initial release
- Kaleidescape, Plex, Shield support
- Web-based admin UI

---

Built with ❤️ for the home theater
