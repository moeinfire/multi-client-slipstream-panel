#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash update.sh"; exit 1; }
APP=/opt/slipstream-panel
[[ -d "$APP" ]] || { echo "Panel not installed at $APP"; exit 1; }
[[ -f /etc/slipstream-panel/secret.key ]] || { echo "Panel config missing; aborting."; exit 1; }

install -m 0750 app.py "$APP/app.py"
chown root:root "$APP/app.py"
systemctl restart slipstream-panel
systemctl --no-pager --full status slipstream-panel
