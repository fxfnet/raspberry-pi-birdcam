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
# Le modèle est utilisé via OpenCV DNN (cv2.dnn.readNetFromONNX) — aucun package
# Python supplémentaire requis.
#
# Le fichier ONNX doit être généré une fois sur une machine de développement :
#
#   pip install tflite2onnx kaggle
#   # Télécharger via Kaggle (compte gratuit requis, clé API dans ~/.kaggle/kaggle.json) :
#   cd /tmp && kaggle models instances versions download google/aiy/tfLite/vision-classifier-birds-v1/3 --untar
#   # Convertir en ONNX et patcher pour OpenCV DNN :
#   python3 -c "import tflite2onnx; tflite2onnx.convert('/tmp/3.tflite', '/tmp/aiy_birds_V1.onnx')"
#   python3 scripts/patch_onnx.py   # corrige la couche Gemm pour OpenCV 4.10
#   scp /tmp/aiy_birds_V1.onnx <pi>:~/birdcam/model/
#
# Le fichier de labels, lui, se télécharge directement :
echo "Downloading species labels..."
wget -O aiy_birds_V1_labelmap.csv \
  "https://www.gstatic.com/aihub/tfhub/labelmaps/aiy_birds_V1_labelmap.csv"

if [ ! -f "aiy_birds_V1.onnx" ]; then
  echo "ATTENTION : aiy_birds_V1.onnx manquant."
  echo "  Générer sur le Mac avec tflite2onnx puis copier via scp (voir commentaire ci-dessus)."
fi

echo "Model files installed in ${MODEL_DIR}"
ls -lh "${MODEL_DIR}"
