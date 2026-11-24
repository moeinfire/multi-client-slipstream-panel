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

During installation, the installer interactively asks you to:

- Choose the TCP port used by the web panel (default: `18080`).
- Choose a private URL path. A random path is suggested automatically; you can accept it or enter your own 4-64 character path using letters, numbers, `_` or `-`.
- Set your own administrator password (minimum 12 characters), or leave it empty to generate a strong random password.

The panel URL will look like this:

```text
http://SERVER_IP:YOUR_PORT/YOUR_PRIVATE_PATH/
```

The selected port, URL path, and administrator password are stored under `/etc/slipstream-panel/`. On reinstall, existing settings are preserved by default; you can choose a new password when prompted. The private URL path is an additional obscurity measure, not a replacement for authentication, firewall restrictions, or HTTPS.

The administrator password is stored in:

```text
/etc/slipstream-panel/admin.password
```

The selected port is stored in `/etc/slipstream-panel/panel.port`, and the private URL path is stored in `/etc/slipstream-panel/base-path`.

The application secret is stored in:

```text
/etc/slipstream-panel/secret.key
```

Keep both files private. Back them up securely. Do not publish them.

## Firewall

Do not expose the panel to the whole internet unless you understand the risk. Prefer allowing only your selected panel TCP port from your own management IP, or put the panel behind a properly configured HTTPS reverse proxy and authentication layer.

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
