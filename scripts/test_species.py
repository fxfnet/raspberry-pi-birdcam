#!/usr/bin/env python3
"""
Test autonome du classifieur d'espèces — ne nécessite pas la caméra.
Utilise OpenCV DNN pour charger le modèle ONNX, aucune dépendance supplémentaire.

Usage :
    python3 scripts/test_species.py
    python3 scripts/test_species.py --image /path/to/bird.jpg
"""

import sys
import argparse
import json
import numpy as np
import cv2
from pathlib import Path

BASE_DIR = Path.home() / "birdcam"
MODEL_DIR = BASE_DIR / "model"
SPECIES_MODEL_PATH = MODEL_DIR / "aiy_birds_V1.onnx"
SPECIES_LABELS_PATH = MODEL_DIR / "aiy_birds_V1_labelmap.csv"
SPECIES_THRESHOLD = 0.05
TOP_K = 10

_SPECIES_JSON = Path(__file__).parent.parent / "training" / "species.json"
PARIS_SPECIES: set[str] = set()
if _SPECIES_JSON.exists():
    for _sp in json.loads(_SPECIES_JSON.read_text()):
        PARIS_SPECIES.add(_sp["scientific"].lower())


def load_labels(path):
    labels = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("id"):
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                try:
                    labels[int(parts[0])] = parts[1].strip()
                except ValueError:
                    pass
    return labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", help="Chemin vers une image JPEG de test")
    args = parser.parse_args()

    print(f"\n--- Test classifieur d'espèces (OpenCV DNN + ONNX) ---")

    # 1. Fichiers modèle
    for path in (SPECIES_MODEL_PATH, SPECIES_LABELS_PATH):
        if not path.exists():
            print(f"✗ Fichier manquant : {path}")
            print("  → Lancer : bash scripts/install_models.sh")
            sys.exit(1)
        print(f"✓ {path.name} ({path.stat().st_size // 1024} Ko)")

    # 2. Chargement via OpenCV DNN
    print("Chargement du réseau...", end=" ", flush=True)
    net = cv2.dnn.readNetFromONNX(str(SPECIES_MODEL_PATH))
    print("OK")

    labels = load_labels(SPECIES_LABELS_PATH)
    print(f"✓ Labels chargés : {len(labels)} espèces")

    # 3. Préparation de l'image
    if args.image:
        img_bgr = cv2.imread(args.image)
        if img_bgr is None:
            print(f"✗ Impossible de lire : {args.image}")
            sys.exit(1)
        image_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        print(f"✓ Image chargée : {args.image}")
    else:
        # Image synthétique : fond vert + tache marron (simule un oiseau)
        image_rgb = np.full((480, 640, 3), (80, 120, 60), dtype=np.uint8)
        image_rgb[180:300, 270:370] = (120, 80, 40)
        print("✓ Image synthétique générée (résultat non significatif)")

    # 4. Inférence
    blob = cv2.dnn.blobFromImage(
        image_rgb,
        scalefactor=1 / 127.5,
        size=(224, 224),
        mean=(127.5, 127.5, 127.5),
        swapRB=False,
    )
    net.setInput(blob)
    output = net.forward()[0]

    top_all = np.argsort(output)[::-1][:TOP_K]
    print(f"\nTop {TOP_K} brut (toutes espèces) :")
    for rank, idx in enumerate(top_all, 1):
        score = float(output[idx])
        name = labels.get(int(idx), f"idx_{idx}")
        bar = "█" * int(score * 40)
        paris = "✓" if name.lower() in PARIS_SPECIES else " "
        print(f"  {paris} {rank:2d}. {name:<40s}  {score:.4f}  {bar}")

    print(f"\nFiltre Paris ({len(PARIS_SPECIES)} espèces) :")
    found = False
    for idx in top_all:
        score = float(output[idx])
        if score < SPECIES_THRESHOLD:
            break
        name = labels.get(int(idx), "unknown")
        if not PARIS_SPECIES or name.lower() in PARIS_SPECIES:
            print(f"  → {name}  ({score:.4f})")
            found = True
            break
    if not found:
        print("  → aucune espèce parisienne détectée au-dessus du seuil")

    print("\n✓ Test terminé avec succès.")


if __name__ == "__main__":
    main()
