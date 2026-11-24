# Slipstream Panel

A self-hosted web panel for managing Slipstream client instances on Linux.

## What's included

- `app.py` — panel application source
- `install.sh` — fresh installation
- `update.sh` — application update while preserving local configuration

This repository intentionally contains **no preconfigured tunnels, tunnel service units, private domains, server addresses, credentials, databases, or user-specific deployment data**. Each administrator configures their own environment.

## Requirements

- Ubuntu/Debian-based Linux server
- Root access
- Python 3 and Flask (installed by `install.sh`)
- Slipstream client binary installed separately for tunnel-management features

## Install

Upload or clone this project to your server, enter its directory, then run:

```bash
sudo bash install.sh
```

The panel listens on TCP port `18080` by default:

```text
http://SERVER_IP:18080
```

The installer generates an initial random admin password and stores it in:

```text
/etc/slipstream-panel/admin.password
```

The application secret is stored in:

```text
/etc/slipstream-panel/secret.key
```

Keep both files private. Back them up securely. Do not publish them.

## Firewall

Do not expose the panel to the whole internet unless you understand the risk. Prefer allowing TCP/18080 only from your own management IP, or put the panel behind a properly configured HTTPS reverse proxy and authentication layer.

## Update

From the project directory:

```bash
sudo bash update.sh
```

The updater replaces only the application source and restarts the panel. It preserves `/etc/slipstream-panel`.

## Service management

```bash
systemctl status slipstream-panel
journalctl -u slipstream-panel -f
systemctl restart slipstream-panel
```

## Notes

- The Slipstream client binary is not bundled.
- Tunnel instances and their systemd units are not bundled.
- Review the source and firewall policy before exposing the panel.
- Contributions, bug reports, and security reports are welcome.
