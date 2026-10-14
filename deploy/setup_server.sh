#!/usr/bin/env bash
# One-time server setup for Ubuntu or Debian (also Raspberry Pi OS). Run as root:
#   sudo bash setup_server.sh
# Optional: JOBBOT_APP_DIR (default /opt/job-alert-bot) and JOBBOT_USER (default jobbot).
set -euo pipefail

APP="${JOBBOT_APP_DIR:-/opt/job-alert-bot}"
RUN_USER="${JOBBOT_USER:-jobbot}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y python3-venv unattended-upgrades

# Security updates install automatically (Ubuntu default, made explicit).
dpkg-reconfigure -f noninteractive unattended-upgrades

# A system user with no login shell runs the bot.
id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$APP/data"
chown -R "$RUN_USER:$RUN_USER" "$APP"

# Keep logs from filling the disk.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size.conf <<'EOF'
[Journal]
SystemMaxUse=200M
EOF
systemctl restart systemd-journald

echo "server ready: $APP, user $RUN_USER"
