#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HOME}/birdcam"
USER_NAME="$(whoami)"

echo "Installing systemd services for user: ${USER_NAME}"

sed "s/^User=.*/User=${USER_NAME}/; s|/home/fxf/|${HOME}/|g" \
  "${PROJECT_DIR}/systemd/birdcam.service" \
  | sudo tee /etc/systemd/system/birdcam.service >/dev/null

sed "s/^User=.*/User=${USER_NAME}/; s|/home/fxf/|${HOME}/|g" \
  "${PROJECT_DIR}/systemd/birdcam-gallery.service" \
  | sudo tee /etc/systemd/system/birdcam-gallery.service >/dev/null

sed "s/^User=.*/User=${USER_NAME}/; s|/home/fxf/|${HOME}/|g" \
  "${PROJECT_DIR}/systemd/birdcam-gallery-admin.service" \
  | sudo tee /etc/systemd/system/birdcam-gallery-admin.service >/dev/null

sed "s/^User=.*/User=${USER_NAME}/; s|/home/fxf/|${HOME}/|g" \
  "${PROJECT_DIR}/systemd/birdcam-purge.service" \
  | sudo tee /etc/systemd/system/birdcam-purge.service >/dev/null

sudo cp "${PROJECT_DIR}/systemd/birdcam-purge.timer" /etc/systemd/system/birdcam-purge.timer

sudo systemctl daemon-reload

sudo systemctl enable birdcam
sudo systemctl enable birdcam-gallery
sudo systemctl enable birdcam-gallery-admin

sudo systemctl enable --now birdcam-purge.timer

echo "Services installed and enabled."
echo
echo "Start them with:"
echo "  sudo systemctl start birdcam"
echo "  sudo systemctl start birdcam-gallery"
echo "  sudo systemctl start birdcam-gallery-admin"
echo
echo "birdcam-purge.timer is enabled and started (daily purge of old motion pictures)."
