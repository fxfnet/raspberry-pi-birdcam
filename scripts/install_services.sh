#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HOME}/birdcam"
USER_NAME="$(whoami)"

echo "Installing systemd services for user: ${USER_NAME}"

sed "s/User=fx/User=${USER_NAME}/g; s|/home/fx|${HOME}|g" \
  "${PROJECT_DIR}/systemd/birdcam.service" \
  | sudo tee /etc/systemd/system/birdcam.service >/dev/null

sed "s/User=fx/User=${USER_NAME}/g; s|/home/fx|${HOME}|g" \
  "${PROJECT_DIR}/systemd/birdcam-gallery.service" \
  | sudo tee /etc/systemd/system/birdcam-gallery.service >/dev/null

sudo systemctl daemon-reload

sudo systemctl enable birdcam
sudo systemctl enable birdcam-gallery

echo "Services installed and enabled."
echo
echo "Start them with:"
echo "  sudo systemctl start birdcam"
echo "  sudo systemctl start birdcam-gallery"
