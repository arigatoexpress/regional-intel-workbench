#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-rari1}"
REMOTE_DIR="${REMOTE_DIR:-/opt/ve-vote-monitor}"

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  ./ "${TARGET}:${REMOTE_DIR}/"

ssh "${TARGET}" "cd ${REMOTE_DIR} && bash deploy/pi/install_on_pi.sh"
