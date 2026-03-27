#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ve-vote-monitor}"
ENV_FILE="${ENV_FILE:-/etc/ve-vote-monitor.env}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "App directory $APP_DIR does not exist. Sync the repo to the Pi first."
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip chromium git rsync

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

if [[ ! -f "$ENV_FILE" ]]; then
  sudo install -m 0644 deploy/ve-vote-monitor.env.example "$ENV_FILE"
fi

if ! sudo grep -q '^VE_MONITOR_CHROMIUM_EXECUTABLE=' "$ENV_FILE"; then
  echo 'VE_MONITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium' | sudo tee -a "$ENV_FILE" >/dev/null
fi

sudo install -m 0644 deploy/systemd/ve-vote-monitor.service /etc/systemd/system/ve-vote-monitor.service
sudo install -m 0644 deploy/systemd/ve-vote-monitor-collector.service /etc/systemd/system/ve-vote-monitor-collector.service
sudo install -m 0644 deploy/systemd/ve-vote-monitor-collector.timer /etc/systemd/system/ve-vote-monitor-collector.timer

sudo systemctl daemon-reload
sudo systemctl enable --now ve-vote-monitor.service
sudo systemctl enable --now ve-vote-monitor-collector.timer

echo "Installed ve-vote-monitor on $(hostname)"
echo "Health: curl http://127.0.0.1:8787/api/health"
echo "Digest: source $APP_DIR/.venv/bin/activate && ve-vote-monitor digest --format telegram"
