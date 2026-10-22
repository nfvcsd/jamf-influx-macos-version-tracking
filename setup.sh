#!/usr/bin/env bash
# Run on the target Debian/Ubuntu system as root. Does not enable collection.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo bash setup.sh on the target Linux server." >&2
  exit 1
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
apt-get update
apt-get install -y python3 python3-venv
if ! id jamfinflux >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --shell /usr/sbin/nologin jamfinflux
fi
install -d -o root -g root -m 0755 /opt/jamf-influx
install -d -o jamfinflux -g jamfinflux -m 0700 /var/lib/jamf-influx
install -o root -g root -m 0644 "$SOURCE_DIR/jamf_influx.py" "$SOURCE_DIR/requirements.txt" /opt/jamf-influx/
python3 -m venv /opt/jamf-influx/venv
/opt/jamf-influx/venv/bin/python -m pip install -r /opt/jamf-influx/requirements.txt
if [[ ! -e /etc/jamf-influx.env ]]; then
  install -o root -g root -m 0600 "$SOURCE_DIR/jamf-influx.env.example" /etc/jamf-influx.env
fi
install -o root -g root -m 0644 "$SOURCE_DIR/systemd/jamf-influx.service" "$SOURCE_DIR/systemd/jamf-influx.timer" /etc/systemd/system/
systemctl daemon-reload
echo "Installed. Configure /etc/jamf-influx.env, then follow docs/deployment.md."
