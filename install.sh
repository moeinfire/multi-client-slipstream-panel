#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh"; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# When installing from a Git checkout, fast-forward to the latest main before
# using any bundled files. Refuse dirty/non-main checkouts rather than
# overwriting local work or installing an unintended branch.
if [[ -d "$SCRIPT_DIR/.git" && "${SLIPSTREAM_INSTALLER_UPDATED:-0}" != "1" ]]; then
  command -v git >/dev/null 2>&1 || { echo "ERROR: git is required to update this checkout."; exit 1; }
  GIT_SAFE=(git -c "safe.directory=$SCRIPT_DIR" -C "$SCRIPT_DIR")
  if [[ -n "$("${GIT_SAFE[@]}" status --porcelain)" ]]; then
    echo "ERROR: repository has local changes; commit/stash them before installing."
    exit 1
  fi
  CURRENT_BRANCH="$("${GIT_SAFE[@]}" branch --show-current)"
  if [[ "$CURRENT_BRANCH" != "main" ]]; then
    echo "ERROR: installer checkout is on '$CURRENT_BRANCH', not 'main'."
    echo "Switch to main and run the installer again."
    exit 1
  fi
  "${GIT_SAFE[@]}" fetch --quiet origin main || { echo "ERROR: could not fetch latest main from origin."; exit 1; }
  "${GIT_SAFE[@]}" pull --ff-only --quiet origin main || { echo "ERROR: could not fast-forward to origin/main."; exit 1; }
  export SLIPSTREAM_INSTALLER_UPDATED=1
  exec bash "$SCRIPT_DIR/install.sh" "$@"
fi

APP=/opt/slipstream-panel
CONF=/etc/slipstream-panel
BIN="${SLIPSTREAM_BIN:-/usr/local/bin/slipstream-client}"
[[ "$BIN" == /* && "$BIN" != *[[:space:]]* ]] || { echo "SLIPSTREAM_BIN must be an absolute path without whitespace."; exit 1; }

# Refuse to install an outdated or incomplete scanner implementation.
# ICMP is informational only; every submitted resolver must reach the
# Slipstream + authenticated SOCKS5 + Google HTTPS test stage.
if ! grep -Fq 'candidates=list(resolvers)' "$SCRIPT_DIR/app.py" ||
   ! grep -Fq 'ICMP is informational only' "$SCRIPT_DIR/app.py"; then
  echo "ERROR: app.py does not contain the ICMP-independent DNS scanner fix."
  echo "Please download/clone the latest repository version and run install.sh again."
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-flask openssl iputils-ping ca-certificates
python3 - "$SCRIPT_DIR/app.py" <<'PY'
import ast, sys
from pathlib import Path
if sys.version_info < (3, 9):
    raise SystemExit("ERROR: Python 3.9 or newer is required.")
try:
    import flask
except Exception as exc:
    raise SystemExit(f"ERROR: Flask is not importable by the system Python: {exc}")
source = Path(sys.argv[1]).read_text(encoding="utf-8")
ast.parse(source, filename=sys.argv[1])
print(f"Python {sys.version.split()[0]} and Flask are ready; app.py syntax is valid.")
PY
install -d -m 0750 "$APP" "$CONF"

install -d -m 0755 "$(dirname "$BIN")"

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

# Always deploy the app.py shipped beside this installer (including scanner fixes).
install -m 0750 "$SCRIPT_DIR/app.py" "$APP/app.py"
echo "Installed DNS scanner: ICMP-independent resolver testing enabled."

# Install the bundled Slipstream executable from the repository root.
if [[ -f "$SCRIPT_DIR/slipstream" ]]; then
  install -D -m 0755 "$SCRIPT_DIR/slipstream" "$BIN"
  echo "Installed Slipstream client to $BIN"
else
  echo "NOTICE: bundled file '$SCRIPT_DIR/slipstream' was not found."
  echo "The panel will install, but scanner features need the Slipstream client."
fi

# Install the standalone Slipstream manager and its systemd unit.
install -m 0750 "$SCRIPT_DIR/slip-manager.py" "$APP/slip-manager.py"
install -d -m 0755 /etc/systemd/system
install -m 0644 "$SCRIPT_DIR/systemd/slip.service" /etc/systemd/system/slip.service
install -d -m 0755 /var/log/slipstream

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
Environment=SLIPSTREAM_BIN=$BIN
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

if [[ "${SLIPSTREAM_ENABLE_STANDALONE:-0}" == "1" ]]; then
  if [[ -x "$BIN" ]]; then
    systemctl enable --now slip.service
    echo "Standalone Slipstream service enabled and started. Review its target in slip.service first."
  else
    echo "ERROR: standalone service requested, but $BIN is missing or not executable."
    exit 1
  fi
else
  echo "Standalone slip.service was installed but left disabled; the panel does not require it."
  echo "Review systemd/slip.service and its target before enabling it manually."
fi

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
