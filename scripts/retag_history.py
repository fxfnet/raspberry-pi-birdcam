#!/usr/bin/env python3
"""
Applique le classifieur d'espèces aux captures bird_*.jpg existantes
et renomme les fichiers avec le suffixe _sp{espèce}_spconf{score}.

Usage :
    python3 scripts/retag_history.py [--dry-run] [--retag] [--dir /chemin/captures]

    --retag : re-traite aussi les fichiers déjà tagués (pour corriger les
              espèces nord-américaines avec le filtre Paris)
"""

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path.home() / "birdcam"
MODEL_DIR = BASE_DIR / "model"
SPECIES_CONFIDENCE_THRESHOLD = 0.05
TOP_K = 10

# Même logique de sélection de modèle que birdcam_motion.py
_GARDEN       = MODEL_DIR / "garden_birds.onnx"
_GARDEN_LABELS = MODEL_DIR / "garden_birds_labels.csv"
_AIY          = MODEL_DIR / "aiy_birds_V1.onnx"
_AIY_LABELS   = MODEL_DIR / "aiy_birds_V1_labelmap.csv"

if _GARDEN.exists() and _GARDEN_LABELS.exists():
    SPECIES_MODEL_PATH  = _GARDEN
    SPECIES_LABELS_PATH = _GARDEN_LABELS
else:
    SPECIES_MODEL_PATH  = _AIY
    SPECIES_LABELS_PATH = _AIY_LABELS

# Filtre Paris
_SPECIES_JSON = Path(__file__).parent.parent / "training" / "species.json"
PARIS_SPECIES: set[str] = set()
if _SPECIES_JSON.exists():
    for _sp in json.loads(_SPECIES_JSON.read_text()):
        PARIS_SPECIES.add(_sp["scientific"].lower())


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


def softmax(x):
    e = np.exp(x - x.max())
    return e / e.sum()


def classify(net, labels, image_rgb):
    # scalefactor=1.0 : le modèle reçoit [0,255] et divise lui-même par 255.
    blob = cv2.dnn.blobFromImage(
        image_rgb,
        scalefactor=1.0,
        size=(224, 224),
        mean=(0, 0, 0),
        swapRB=False,
    )
    net.setInput(blob)
    # Appliquer softmax : garden_birds émet des logits bruts (pas de softmax dans l'archi).
    output = softmax(net.forward()[0])

    top_indices = np.argsort(output)[::-1][:TOP_K]
    for idx in top_indices:
        score = float(output[idx])
        if score < SPECIES_CONFIDENCE_THRESHOLD:
            break
        name = labels.get(int(idx), "unknown")
        if not PARIS_SPECIES or name.lower() in PARIS_SPECIES:
            return name, score

    return None, float(output[top_indices[0]])


def strip_species_suffix(stem: str) -> str:
    """Retire _sp..._spconf... du nom de fichier pour re-tagger."""
    return re.sub(r"_sp[a-zA-Z0-9_-]+?_spconf[0-9.]+$", "", stem)


def already_tagged(name):
    return bool(re.search(r"_sp[a-zA-Z0-9_-]+_spconf[0-9.]+", name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans renommer")
    parser.add_argument("--retag",   action="store_true", help="Re-traite les fichiers déjà tagués")
    parser.add_argument("--dir", default=str(BASE_DIR / "captures"), help="Dossier captures")
    args = parser.parse_args()

    capture_dir = Path(args.dir)

    for path in (SPECIES_MODEL_PATH, SPECIES_LABELS_PATH):
        if not path.exists():
            print(f"Fichier manquant : {path}")
            sys.exit(1)

    print(f"Modèle : {SPECIES_MODEL_PATH.name}")
    print(f"Filtre Paris : {len(PARIS_SPECIES)} espèces")
    print("Chargement du modèle...")
    net = cv2.dnn.readNetFromONNX(str(SPECIES_MODEL_PATH))
    labels = load_labels(SPECIES_LABELS_PATH)
    print(f"{len(labels)} espèces chargées.\n")

    thumb_dir = Path.home() / "birdcam" / "gallery" / "thumbs"

    patterns = ["bird_*.jpg", "star_bird_*.jpg"]
    if args.retag:
        files = sorted(f for pat in patterns for f in capture_dir.glob(pat))
    else:
        files = sorted(
            f for pat in patterns for f in capture_dir.glob(pat)
            if not already_tagged(f.name)
        )

    print(f"{len(files)} fichiers à traiter.\n")

    tagged = skipped = errors = unchanged = 0

    for path in files:
        img_bgr = cv2.imread(str(path))
        if img_bgr is None:
            print(f"  SKIP (illisible) : {path.name}")
            errors += 1
            continue

        image_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        species, score = classify(net, labels, image_rgb)

        # Construire le nouveau nom en retirant l'ancien suffixe espèce
        clean_stem = strip_species_suffix(path.stem)
        sp_suffix = f"_sp{safe_label(species)}_spconf{score:.2f}" if species else ""
        new_path = path.parent / (clean_stem + sp_suffix + ".jpg")

        if new_path == path:
            unchanged += 1
            continue

        if not species:
            if not already_tagged(path.name):
                skipped += 1
            else:
                # Retirer l'ancien tag (espèce hors filtre)
                if args.dry_run:
                    print(f"  DRY  {path.name}\n    →  {new_path.name}  (tag retiré)")
                else:
                    path.rename(new_path)
                    _rename_thumb(path, new_path, thumb_dir)
                    print(f"  CLEAR {new_path.name}")
                tagged += 1
            continue

        if args.dry_run:
            print(f"  DRY  {path.name}\n    →  {new_path.name}")
        else:
            path.rename(new_path)
            _rename_thumb(path, new_path, thumb_dir)
            print(f"  OK   {new_path.name}  ({species}, {score:.3f})")

        tagged += 1

    print(f"\nTerminé — {tagged} modifiés, {skipped} sous seuil, {unchanged} inchangés, {errors} erreurs.")
    if args.dry_run:
        print("(dry-run : aucun fichier modifié)")


def _rename_thumb(old_path, new_path, thumb_dir):
    old_thumb = thumb_dir / old_path.name.replace("/", "_")
    new_thumb = thumb_dir / new_path.name.replace("/", "_")
    if old_thumb.exists():
        old_thumb.rename(new_thumb)


if __name__ == "__main__":
    main()
