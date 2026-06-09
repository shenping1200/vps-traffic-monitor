#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vps-traffic-monitor"
SERVICE_FILE="/etc/systemd/system/vps-traffic-monitor.service"

apt update
apt install -y python3 python3-venv
mkdir -p "$APP_DIR"
cp -r ./* "$APP_DIR"/
python3 -m venv "$APP_DIR/.venv"
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
echo "VPS Traffic Monitor ???? http://?????IP:9090"
