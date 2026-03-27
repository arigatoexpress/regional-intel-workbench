#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/mnt/ssd/kimi-claw/ve-vote-monitor"
ENV_FILE="$HOME/.config/ve-vote-monitor.env"
USER_UNIT_DIR="$HOME/.config/systemd/user"
LOCAL_BIN_DIR="$HOME/.local/bin"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip chromium rsync
sudo loginctl enable-linger rari

mkdir -p "$USER_UNIT_DIR" "$LOCAL_BIN_DIR" "$APP_DIR"

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

install -m 0644 deploy/ve-vote-monitor.env.example "$ENV_FILE"
python3 - <<'PY'
from pathlib import Path

path = Path.home() / ".config" / "ve-vote-monitor.env"
entries = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            entries[key] = value
entries["VE_MONITOR_TIMEZONE"] = entries.get("VE_MONITOR_TIMEZONE", "America/Denver") or "America/Denver"
entries["VE_MONITOR_CHROMIUM_EXECUTABLE"] = "/usr/bin/chromium"
path.write_text("".join(f"{key}={value}\n" for key, value in sorted(entries.items())), encoding="utf-8")
PY

install -m 0644 deploy/systemd-user/ve-vote-monitor.service "$USER_UNIT_DIR/ve-vote-monitor.service"
install -m 0644 deploy/systemd-user/ve-vote-monitor-collector.service "$USER_UNIT_DIR/ve-vote-monitor-collector.service"
install -m 0644 deploy/systemd-user/ve-vote-monitor-collector.timer "$USER_UNIT_DIR/ve-vote-monitor-collector.timer"

cat > "$LOCAL_BIN_DIR/ve-vote-monitor-digest" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /mnt/ssd/kimi-claw/ve-vote-monitor
exec /mnt/ssd/kimi-claw/ve-vote-monitor/.venv/bin/ve-vote-monitor digest --format telegram "$@"
EOF
chmod +x "$LOCAL_BIN_DIR/ve-vote-monitor-digest"

cat > "$LOCAL_BIN_DIR/ve-vote-monitor-refresh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /mnt/ssd/kimi-claw/ve-vote-monitor
exec /mnt/ssd/kimi-claw/ve-vote-monitor/.venv/bin/ve-vote-monitor collect --force "$@"
EOF
chmod +x "$LOCAL_BIN_DIR/ve-vote-monitor-refresh"

systemctl --user daemon-reload
systemctl --user enable --now ve-vote-monitor.service
systemctl --user enable --now ve-vote-monitor-collector.timer

echo "Installed ve-vote-monitor on $(hostname)"
echo "Health: curl http://127.0.0.1:8787/api/health"
echo "Digest: ve-vote-monitor-digest --blackhole 15000 --supernova 8000 --fullsail 50000"
