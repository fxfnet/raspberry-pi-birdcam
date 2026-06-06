#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${HOME}/birdcam"
MODEL_DIR="${BASE_DIR}/model"

mkdir -p "${MODEL_DIR}"

cd "${MODEL_DIR}"

# --- Détecteur générique (MobileNet SSD, PASCAL VOC 21 classes) ---
echo "Downloading MobileNet SSD model..."

wget -O MobileNetSSD_deploy.prototxt \
  https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt

wget -O MobileNetSSD_deploy.caffemodel \
  https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel

# --- Classifieur d'espèces (Google AIY Vision Birds V1, iNaturalist, 964 espèces) ---
# Requis : pip install ai-edge-litert
echo "Downloading species classifier (Google AIY Vision Birds V1)..."

wget -O aiy_vision_classifier_birds_V1_3.tflite \
  "https://storage.googleapis.com/tfhub-lite-models/google/aiy/vision/classifier/birds_V1/3.tflite"

wget -O aiy_birds_V1_labelmap.csv \
  "https://www.gstatic.com/aihub/tfhub/labelmaps/aiy_birds_V1_labelmap.csv"

echo "Model files installed in ${MODEL_DIR}"
ls -lh "${MODEL_DIR}"
