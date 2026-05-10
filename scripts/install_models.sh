#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${HOME}/birdcam"
MODEL_DIR="${BASE_DIR}/model"

mkdir -p "${MODEL_DIR}"

cd "${MODEL_DIR}"

echo "Downloading MobileNet SSD model..."

wget -O MobileNetSSD_deploy.prototxt \
  https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt

wget -O MobileNetSSD_deploy.caffemodel \
  https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel

echo "Model files installed in ${MODEL_DIR}"
ls -lh "${MODEL_DIR}"
