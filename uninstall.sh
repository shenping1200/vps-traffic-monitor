#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vps-traffic-monitor"
SERVICE_FILE="/etc/systemd/system/vps-traffic-monitor.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: sudo bash uninstall.sh"
  exit 1
fi

systemctl disable --now vps-traffic-monitor 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl daemon-reload
rm -rf "$APP_DIR"

echo "vps-traffic-monitor has been uninstalled."
