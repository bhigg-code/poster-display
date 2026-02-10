#!/bin/bash
# Movie Poster Display - Raspberry Pi Installation Script

set -e

echo "=================================="
echo "Movie Poster Display Installer"
echo "=================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./install.sh)"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-pi}
INSTALL_DIR="/home/$ACTUAL_USER/poster-display"

echo "Installing for user: $ACTUAL_USER"
echo "Install directory: $INSTALL_DIR"

# Update system
echo ""
echo "[1/7] Updating system packages..."
apt-get update
apt-get upgrade -y

# Install dependencies
echo ""
echo "[2/7] Installing system dependencies..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    chromium-browser \
    unclutter \
    xdotool \
    xserver-xorg \
    xinit \
    x11-xserver-utils

# Create install directory
echo ""
echo "[3/7] Setting up application directory..."
mkdir -p "$INSTALL_DIR"
cp -r backend frontend requirements.txt "$INSTALL_DIR/"
chown -R "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR"

# Create Python virtual environment
echo ""
echo "[4/7] Creating Python virtual environment..."
sudo -u "$ACTUAL_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$ACTUAL_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$ACTUAL_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Create systemd service for the backend
echo ""
echo "[5/7] Creating systemd service..."
cat > /etc/systemd/system/poster-display.service << EOF
[Unit]
Description=Movie Poster Display Backend
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$INSTALL_DIR/backend
ExecStart=$INSTALL_DIR/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create kiosk startup script
echo ""
echo "[6/7] Creating kiosk startup script..."
cat > "$INSTALL_DIR/start-kiosk.sh" << 'EOF'
#!/bin/bash

# Wait for the backend to be ready
sleep 5

# Disable screen blanking
xset s off
xset s noblank
xset -dpms

# Hide cursor
unclutter -idle 0.1 -root &

# Start Chromium in kiosk mode
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --no-first-run \
    --start-fullscreen \
    --window-size=1080,1920 \
    --window-position=0,0 \
    http://localhost:8080
EOF
chmod +x "$INSTALL_DIR/start-kiosk.sh"
chown "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR/start-kiosk.sh"

# Configure auto-login and kiosk startup
echo ""
echo "[7/7] Configuring auto-start..."

# Create .xinitrc for the user
cat > "/home/$ACTUAL_USER/.xinitrc" << EOF
#!/bin/bash
exec $INSTALL_DIR/start-kiosk.sh
EOF
chown "$ACTUAL_USER:$ACTUAL_USER" "/home/$ACTUAL_USER/.xinitrc"
chmod +x "/home/$ACTUAL_USER/.xinitrc"

# Auto-login to console
mkdir -p /etc/systemd/system/getty@tty1.service.d/
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $ACTUAL_USER --noclear %I \$TERM
EOF

# Start X on login
cat >> "/home/$ACTUAL_USER/.bash_profile" << 'EOF'

# Start X if on tty1 and not already running
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    startx
fi
EOF
chown "$ACTUAL_USER:$ACTUAL_USER" "/home/$ACTUAL_USER/.bash_profile"

# Enable and start the service
systemctl daemon-reload
systemctl enable poster-display.service
systemctl start poster-display.service

echo ""
echo "=================================="
echo "Installation complete!"
echo "=================================="
echo ""
echo "The poster display service is now running."
echo "The system will auto-start in kiosk mode on next boot."
echo ""
echo "Commands:"
echo "  systemctl status poster-display   - Check backend status"
echo "  systemctl restart poster-display  - Restart backend"
echo "  journalctl -u poster-display -f   - View logs"
echo ""
echo "Reboot to start the full kiosk display, or run:"
echo "  sudo -u $ACTUAL_USER startx"
echo ""
