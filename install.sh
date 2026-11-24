#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh"; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/slipstream-panel
CONF=/etc/slipstream-panel
BIN="${SLIPSTREAM_BIN:-/usr/local/bin/slipstream-client}"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-flask openssl
install -d -m 0750 "$APP" "$CONF"

# Create the unprivileged account used by per-tunnel systemd services.
if ! getent group slipstream >/dev/null; then
  groupadd --system slipstream
fi
if ! id -u slipstream >/dev/null 2>&1; then
  useradd --system --gid slipstream --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin slipstream
fi
install -d -o slipstream -g slipstream -m 0750 /var/log/slipstream-panel

# Keep existing settings when reinstalling; prompt for new values only when needed.
DEFAULT_PORT="$(cat "$CONF/panel.port" 2>/dev/null || echo 18080)"
read -r -p "Panel port [${DEFAULT_PORT}]: " PANEL_PORT
PANEL_PORT="${PANEL_PORT:-$DEFAULT_PORT}"
[[ "$PANEL_PORT" =~ ^[0-9]+$ ]] && (( PANEL_PORT >= 1 && PANEL_PORT <= 65535 )) || { echo "Invalid TCP port."; exit 1; }
if [[ "$PANEL_PORT" != "$DEFAULT_PORT" ]] && command -v ss >/dev/null 2>&1 && ss -lntH "sport = :$PANEL_PORT" | grep -q .; then
  echo "Port $PANEL_PORT is already in use."; exit 1
fi

SUGGESTED_PATH="$(openssl rand -hex 8)"
DEFAULT_PATH="$(cat "$CONF/base-path" 2>/dev/null | sed 's#^/##' || true)"
DEFAULT_PATH="${DEFAULT_PATH:-$SUGGESTED_PATH}"
echo "Suggested private URL path: /$SUGGESTED_PATH"
read -r -p "Panel URL path (letters, numbers, _ or -) [${DEFAULT_PATH}]: " PANEL_PATH
PANEL_PATH="${PANEL_PATH:-$DEFAULT_PATH}"
[[ "$PANEL_PATH" =~ ^[A-Za-z0-9_-]{4,64}$ ]] || { echo "Path must be 4-64 characters: letters, numbers, _ or -. Do not include slashes."; exit 1; }

if [[ -s "$CONF/admin.password" ]]; then
  read -r -p "Keep existing admin password? [Y/n]: " KEEP_PASSWORD
else
  KEEP_PASSWORD="n"
fi
if [[ "${KEEP_PASSWORD:-Y}" =~ ^[Nn]$ ]]; then
  while true; do
    read -r -s -p "Choose admin password (min 12 characters; leave empty for a random password): " ADMIN_PASSWORD; echo
    if [[ -z "$ADMIN_PASSWORD" ]]; then
      ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '\n')"
      GENERATED_PASSWORD=1
      break
    fi
    (( ${#ADMIN_PASSWORD} >= 12 )) || { echo "Password must be at least 12 characters."; continue; }
    read -r -s -p "Confirm admin password: " ADMIN_PASSWORD_CONFIRM; echo
    [[ "$ADMIN_PASSWORD" == "$ADMIN_PASSWORD_CONFIRM" ]] && break
    echo "Passwords do not match. Try again."
  done
  umask 077
  printf '%s' "$ADMIN_PASSWORD" > "$CONF/admin.password"
  chmod 600 "$CONF/admin.password"
fi

install -m 0750 "$SCRIPT_DIR/app.py" "$APP/app.py"

# Install the bundled Slipstream executable from the repository root.
if [[ -f "$SCRIPT_DIR/slipstream" ]]; then
  install -m 0755 "$SCRIPT_DIR/slipstream" "$BIN"
  echo "Installed Slipstream client to $BIN"
else
  echo "NOTICE: bundled file '$SCRIPT_DIR/slipstream' was not found."
  echo "The panel will install, but scanner features need the Slipstream client."
fi

chown -R root:root "$APP"
printf '%s' "$PANEL_PORT" > "$CONF/panel.port"
printf '/%s' "$PANEL_PATH" > "$CONF/base-path"
chmod 600 "$CONF/panel.port" "$CONF/base-path"

[[ -f "$CONF/secret.key" ]] || {
  openssl rand -hex 32 > "$CONF/secret.key"
  chmod 600 "$CONF/secret.key"
}

cat > /etc/systemd/system/slipstream-panel.service <<EOF2
[Unit]
Description=Slipstream Web Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP
Environment=PANEL_HOST=0.0.0.0
Environment=PANEL_PORT=$PANEL_PORT
ExecStart=/usr/bin/python3 $APP/app.py
Restart=always
RestartSec=3
User=root
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF2

systemctl daemon-reload
systemctl enable slipstream-panel
systemctl restart slipstream-panel || systemctl start slipstream-panel

echo
echo "Slipstream Panel installed."
echo "URL: http://SERVER_IP:${PANEL_PORT}/${PANEL_PATH}/"
if [[ "${GENERATED_PASSWORD:-0}" == 1 ]]; then
  echo "Generated admin password: $ADMIN_PASSWORD"
else
  echo "Admin password: configured (stored in $CONF/admin.password)"
fi
echo "Panel port: $PANEL_PORT (stored in $CONF/panel.port)"
echo "URL path: /$PANEL_PATH/ (stored in $CONF/base-path)"
if [[ ! -x "$BIN" ]]; then
  echo "NOTICE: Slipstream client binary was not found at $BIN."
  echo "Install the Slipstream client separately to use tunnel-management features."
fi
echo "IMPORTANT: Restrict TCP/$PANEL_PORT to trusted IP addresses in your firewall and use HTTPS through a reverse proxy when exposing it publicly."
