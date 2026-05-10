#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop birdcam || true
sudo systemctl stop birdcam-gallery || true

echo "Birdcam services stopped."
