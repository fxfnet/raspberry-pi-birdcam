#!/usr/bin/env python3
"""
Applique le classifieur d'espèces aux captures bird_*.jpg existantes
et renomme les fichiers avec le suffixe _sp{espèce}_spconf{score}.

Usage :
    python3 scripts/retag_history.py [--dry-run] [--dir /chemin/captures]
"""

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path.home() / "birdcam"
MODEL_DIR = BASE_DIR / "model"
SPECIES_MODEL_PATH = MODEL_DIR / "aiy_birds_V1.onnx"
SPECIES_LABELS_PATH = MODEL_DIR / "aiy_birds_V1_labelmap.csv"
SPECIES_CONFIDENCE_THRESHOLD = 0.05


def safe_label(label: str) -> str:
    label = label.lower().strip()
    label = re.sub(r"[^a-z0-9_-]+", "_", label)
    return label or "none"


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


def classify(net, labels, image_rgb):
    blob = cv2.dnn.blobFromImage(
        image_rgb,
        scalefactor=1 / 127.5,
        size=(224, 224),
        mean=(127.5, 127.5, 127.5),
        swapRB=False,
    )
    net.setInput(blob)
    output = net.forward()[0]
    top_idx = int(np.argmax(output))
    top_score = float(output[top_idx])
    return labels.get(top_idx, "unknown"), top_score


def already_tagged(name):
    return bool(re.search(r"_sp[a-zA-Z0-9_-]+_spconf[0-9.]+", name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans renommer")
    parser.add_argument("--dir", default=str(BASE_DIR / "captures"), help="Dossier captures")
    args = parser.parse_args()

    capture_dir = Path(args.dir)

    for path in (SPECIES_MODEL_PATH, SPECIES_LABELS_PATH):
        if not path.exists():
            print(f"Fichier manquant : {path}")
            print("Lancer : bash scripts/install_models.sh")
            sys.exit(1)

    print("Chargement du modèle...")
    net = cv2.dnn.readNetFromONNX(str(SPECIES_MODEL_PATH))
    labels = load_labels(SPECIES_LABELS_PATH)
    print(f"{len(labels)} espèces chargées.")

    files = sorted(f for f in capture_dir.glob("bird_*.jpg") if not already_tagged(f.name))
    print(f"{len(files)} fichiers à traiter (déjà tagués ignorés).\n")

    tagged = skipped = errors = 0

    for path in files:
        img_bgr = cv2.imread(str(path))
        if img_bgr is None:
            print(f"  SKIP (illisible) : {path.name}")
            errors += 1
            continue

        image_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        species, score = classify(net, labels, image_rgb)

        if score < SPECIES_CONFIDENCE_THRESHOLD:
            print(f"  -- {path.name}  →  {species} ({score:.3f}) sous seuil, ignoré")
            skipped += 1
            continue

        sp_suffix = f"_sp{safe_label(species)}_spconf{score:.2f}"
        stem = path.stem  # retire .jpg
        new_name = path.parent / (stem + sp_suffix + ".jpg")

        if args.dry_run:
            print(f"  DRY  {path.name}")
            print(f"    →  {new_name.name}")
        else:
            path.rename(new_name)
            print(f"  OK   {new_name.name}  ({species}, {score:.3f})")

        tagged += 1

    print(f"\nTerminé — {tagged} renommés, {skipped} sous seuil, {errors} erreurs.")
    if args.dry_run:
        print("(dry-run : aucun fichier modifié)")


if __name__ == "__main__":
    main()
