#!/bin/bash
# Poster Display Kiosk Mode

# Wait for X to be ready
sleep 5

# Disable screen blanking and power management
xset s off
xset s noblank
xset -dpms

# Hide cursor after 0.5 seconds of inactivity
unclutter -idle 0.5 -root &

# Start Chromium in kiosk mode
chromium-browser     --kiosk     --noerrdialogs     --disable-infobars     --disable-session-crashed-bubble     --disable-restore-session-state     --no-first-run     --start-fullscreen     --window-position=0,0     --check-for-update-interval=31536000     --disable-features=TranslateUI     --overscroll-history-navigation=0     http://localhost:8080
