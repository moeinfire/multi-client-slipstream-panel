#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh"; exit 1; }

APP=/opt/slipstream-panel
CONF=/etc/slipstream-panel
BIN="${SLIPSTREAM_BIN:-/usr/local/bin/slipstream-client}"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-flask openssl

install -d -m 0750 "$APP" "$CONF"
install -m 0750 app.py "$APP/app.py"
chown -R root:root "$APP"

[[ -f "$CONF/admin.password" ]] || {
  openssl rand -base64 32 > "$CONF/admin.password"
  chmod 600 "$CONF/admin.password"
}
[[ -f "$CONF/secret.key" ]] || {
  openssl rand -hex 32 > "$CONF/secret.key"
  chmod 600 "$CONF/secret.key"
}

cat > /etc/systemd/system/slipstream-panel.service <<EOF
[Unit]
Description=Slipstream Web Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP
Environment=PANEL_HOST=0.0.0.0
Environment=PANEL_PORT=18080
ExecStart=/usr/bin/python3 $APP/app.py
Restart=always
RestartSec=3
User=root
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now slipstream-panel

echo
echo "Slipstream Panel installed."
echo "URL: http://SERVER_IP:18080"
echo "Initial password: $(cat "$CONF/admin.password")"
echo "Password file: $CONF/admin.password"
if [[ ! -x "$BIN" ]]; then
  echo "NOTICE: Slipstream client binary was not found at $BIN."
  echo "Install the Slipstream client separately to use tunnel-management features."
fi
echo "IMPORTANT: Restrict TCP/18080 to trusted IP addresses in your firewall."
