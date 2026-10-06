#!/usr/bin/env bash
set -euo pipefail

# Avant birdcam : l'arrêt du clip relance birdcam (ExecStopPost).
sudo systemctl stop birdcam-clip || true
sudo systemctl stop birdcam || true
sudo systemctl stop birdcam-gallery || true

echo "Birdcam services stopped."
