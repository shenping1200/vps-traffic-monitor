#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/shenping1200/vps-traffic-monitor.git}"
APP_DIR="${APP_DIR:-/opt/vps-traffic-monitor}"
SERVICE_FILE="/etc/systemd/system/vps-traffic-monitor.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: sudo bash install-remote.sh"
  exit 1
fi

apt update
apt install -y git python3 python3-venv

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VPS Traffic Monitor
After=network.target

[Service]
WorkingDirectory=$APP_DIR
Environment=MONITOR_USERNAME=admin
Environment=MONITOR_PASSWORD=admin
Environment=MONITOR_PORT=9090
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now vps-traffic-monitor

echo ""
echo "????"
echo "????: http://?????IP:9090"
echo "??: admin"
echo "??: admin"
