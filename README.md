# Slipstream Panel

A self-hosted web-based management panel for running, monitoring, and managing multiple Slipstream client tunnels on Linux servers.

Slipstream Panel provides a centralized web interface for managing tunnel instances, configuring DNS resolvers, monitoring connection health, tracking traffic usage, and distributing SOCKS5 connections across healthy tunnels.

## ✨ Features

### 🚇 Tunnel Management
- Add and configure multiple Slipstream client instances.
- Automatically create and manage systemd services for tunnel instances.
- Start, stop, restart, and delete individual tunnels.
- Perform bulk operations to start, stop, or restart multiple tunnels.
- Configure a local listening port for each tunnel.
- Optional PEM certificate path configuration.
- View individual tunnel logs for troubleshooting.

### 🌐 DNS Management
- Configure multiple DNS resolvers for each tunnel.
- Set global default DNS resolvers for newly created tunnels.
- Apply DNS configuration to all existing tunnels.
- Edit DNS settings independently for each tunnel.
- Support multiple resolver entries in `IP:PORT` format.

### 🔍 Advanced DNS Scanner
- Two-stage DNS testing workflow.
- First-stage ICMP Ping testing for DNS resolver IPs.
- Second-stage end-to-end Slipstream tunnel testing.
- SOCKS5 Username/Password authentication during the test.
- HTTPS connectivity verification against Google.
- TLS certificate validation and HTTP 204 response verification.
- Measure end-to-end latency and sort successful DNS results.
- Configurable worker count and test timeout.
- Select and copy successful DNS resolver addresses.
- Temporary test tunnels do not modify or restart existing production tunnels.

### ⚖️ SOCKS5 Load Balancer
- Built-in SOCKS5 load balancer.
- Round Robin distribution for new connections.
- Automatically select healthy and active tunnel backends.
- Temporarily exclude unhealthy or unreachable tunnels.
- Reintroduce recovered tunnels after the cooldown period.
- Forward SOCKS5 authentication to the selected backend.

### 📊 Traffic Monitoring
- Monitor incoming and outgoing traffic for each tunnel.
- Display total traffic usage per instance.
- Calculate approximate transfer speeds using periodic sampling.
- Reset traffic counters for individual tunnels.
- Traffic accounting based on systemd per-service IP accounting.

### ❤️ Connection Health Monitoring
- Periodically inspect each tunnel's service logs.
- Detect connection-ready, connection-closed, and client-error events.
- Display connection status and failure information.
- Allow a recovery window before declaring a tunnel failed.
- Automatically restart failed tunnels after a cooldown period.
- Detect process exits and address-in-use errors.

### 🔐 Access and Deployment
- Password-protected web interface.
- CSRF protection for management actions.
- Automatically generated initial administrator password.
- Separate storage for application secrets and configuration.
- systemd service integration.
- Installation and update scripts for Ubuntu/Debian-based systems.

## 🧰 Requirements

- Ubuntu or Debian-based Linux server.
- Root or sudo access.
- Python 3.
- Flask.
- Slipstream client binary installed separately.

## 🚀 Quick Installation

```bash
git clone https://github.com/moeinfire/multi-slipstream-panel-with-load-balancer.git
cd slipstream-panel
sudo bash install.sh
```

After installation, access the panel at:

```text
http://SERVER_IP:18080
```

The installer generates an initial administrator password. See the installation instructions in this repository for details.

## ⚠️ Important Notes

- The Slipstream client binary is not included.
- Tunnel configurations and systemd tunnel services are not included.
- Each user must configure their own domains, DNS resolvers, certificates, and tunnel settings.
- The panel should not be exposed directly to the public internet without appropriate access restrictions and HTTPS protection.
- Review the source code and security configuration before deploying in production.

## 📄 License

MIT License
