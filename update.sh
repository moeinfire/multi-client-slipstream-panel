#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash update.sh"; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "\${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/slipstream-panel
CONF=/etc/slipstream-panel

[[ -d "$APP" ]] || { echo "Panel not installed at $APP"; exit 1; }
[[ -s "$CONF/secret.key" && -s "$CONF/admin.password" ]] || {
  echo "Panel configuration or credentials are missing; refusing to update."
  exit 1
}
[[ -s "$SCRIPT_DIR/app.py" ]] || { echo "Repository app.py is missing."; exit 1; }

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
if "candidates=list(resolvers)" not in source or "ICMP is informational only" not in source:
    raise SystemExit("ERROR: app.py is missing the ICMP-independent DNS scanner implementation.")
print("Python, Flask, and app.py validation passed.")
PY

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$APP/app.py.bak.$STAMP"
TEMP="$APP/.app.py.new"
cp -a "$APP/app.py" "$BACKUP"
install -m 0750 "$SCRIPT_DIR/app.py" "$TEMP"
chown root:root "$TEMP"
python3 - "$TEMP" <<'PY'
import ast, sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"), filename=sys.argv[1])
PY
mv -f "$TEMP" "$APP/app.py"

if ! systemctl restart slipstream-panel || ! systemctl is-active --quiet slipstream-panel; then
  echo "Panel restart failed; restoring the previous app.py."
  cp -a "$BACKUP" "$APP/app.py"
  systemctl restart slipstream-panel || true
  echo "Previous file restored from $BACKUP"
  journalctl -u slipstream-panel -n 60 --no-pager || true
  exit 1
fi

echo "Panel updated successfully."
echo "Backup: $BACKUP"
systemctl --no-pager --full status slipstream-panel
