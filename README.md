# multi-client slipstream panel with load balancer

A self-hosted web panel for managing multiple Slipstream client tunnels on Linux servers. It provides tunnel lifecycle controls, DNS configuration, health monitoring, per-tunnel traffic accounting, a two-stage DNS scanner, and a SOCKS5 TCP load balancer.

## Features

### Tunnel management
- Add and manage multiple Slipstream client instances through systemd.
- Start, stop, restart, and delete individual tunnels or perform bulk operations.
- Configure local listener ports, DNS resolver lists, and optional PEM certificates.
- Inspect per-tunnel service logs.

### DNS management and scanner
- Configure per-tunnel DNS resolvers and a global default for new tunnels.
- Apply a DNS list to existing tunnels one at a time.
- Scan resolver IP addresses in two stages: ICMP ping information, then a real Slipstream + authenticated SOCKS5 + Google HTTPS test.
- ICMP is informational only. Every submitted resolver proceeds to the end-to-end test, even when it does not answer ping.
- Validate SOCKS5 username/password authentication, TLS, and Google's HTTP 204 response.
- Configure scan worker count and timeout, sort successful results, and copy selected resolvers.
- Scanner tests use temporary Slipstream processes and do not restart production tunnel services.

### SOCKS5 load balancer
- Round-robin selection across enabled tunnels reported as healthy.
- Temporarily quarantine a backend when its local TCP listener cannot be reached.
- Forward the client's SOCKS5 handshake, including authentication, unchanged to the selected backend.

### Traffic and health monitoring
- Read per-service IP accounting counters from systemd.
- Display cumulative received/sent bytes and approximate transfer rates.
- Detect Slipstream readiness, connection errors, process exits, and local port conflicts.
- Allow a recovery grace period and retry failed tunnels after a cooldown.

## Requirements

- Ubuntu or Debian-based Linux.
- Root access for installation and systemd management.
- Python 3.9 or newer and Flask. The installer installs the distro Flask package and checks the Python version and app syntax.
- systemd.
- A compatible Linux Slipstream client executable. This repository currently contains a file named slipstream; the installer copies it to /usr/local/bin/slipstream-client by default. Binary compatibility depends on the target server architecture. You may set SLIPSTREAM_BIN to an absolute executable path to use your own build.

## Installation

Clone the repository and run the installer as root:

    git clone https://github.com/moeinfire/multi-client-slipstream-panel.git
    cd multi-client-slipstream-panel
    sudo bash install.sh

The installer:
- Installs Python/Flask and the ICMP ping utility.
- Creates the slipstream system account used by per-tunnel services.
- Installs the panel under /opt/slipstream-panel.
- Creates configuration and secret files under /etc/slipstream-panel.
- Preserves an existing tunnels.db and existing panel credentials when reinstalling.
- Installs the bundled client when present and writes the selected client path into the panel systemd unit.
- Generates an administrator password when one does not already exist and prints a newly generated password once at the end of installation.
- Configures a private URL path and panel port.

Open the URL printed by the installer:

    http://SERVER_IP:18080/PRIVATE_PATH/

Restrict the panel port to trusted source IP addresses and use HTTPS through a reverse proxy when exposing it publicly. The private path is an additional URL-level barrier, not a replacement for authentication or firewall rules.

## Standalone manager (optional)

The repository also contains slip-manager.py and systemd/slip.service for a separate, standalone Slipstream process. The panel does not need this service. The installer therefore places the unit but leaves it disabled by default. The sample unit has a preset target of r.iooq.ir:20817; review and change that target before enabling it.

To opt in during installation, set SLIPSTREAM_ENABLE_STANDALONE=1 in the root installer's environment. Alternatively, after reviewing the unit, enable it manually with:

    systemctl enable --now slip.service

## Updating

From a clean checkout on the main branch:

    sudo bash update.sh

The updater validates the Python source, creates a timestamped backup of the current app.py, installs the new app atomically, and rolls back the file if the panel cannot restart.

## Important notes

- Tunnel definitions and their database are not published in this repository.
- Existing tunnel definitions are stored in /opt/slipstream-panel/tunnels.db; back it up before migrations or manual changes.
- Configure your own domains, DNS resolvers, certificates, and SOCKS5 credentials.
- Review firewall, reverse-proxy, and certificate settings before exposing the panel.

## License

MIT License
