#!/usr/bin/env python3
"""
Applique le classifieur d'espèces aux captures bird_*.jpg existantes
et renomme les fichiers avec le suffixe _sp{espèce}_spconf{score}.

Usage :
    python3 scripts/retag_history.py [--dry-run] [--retag] [--best] [--dir /chemin/captures]

    --retag : re-traite aussi les fichiers déjà tagués (pour corriger les
              espèces nord-américaines avec le filtre Paris)
    --best  : réécrit _conf/_best des captures étiquetées dog/cow/horse/sheep
              avec le détecteur actuel (préfixe et espèce inchangés)
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
SPECIES_CONFIDENCE_THRESHOLD = 0.3

# Détecteur d'oiseau, mêmes réglages que birdcam_motion.py : l'espèce est
# classée sur le cadre de l'oiseau, pas sur l'image entière.
PROTOTXT_PATH = MODEL_DIR / "MobileNetSSD_deploy.prototxt"
DETECTOR_PATH = MODEL_DIR / "MobileNetSSD_deploy.caffemodel"
CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse", "motorbike",
    "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]
# Comme FEEDER_BIRD_ALIASES dans birdcam_motion.py : un gros plan d'oiseau
# sort souvent en "dog" ou "cow", compté ici comme "bird".
FEEDER_BIRD_ALIASES = {"dog", "cow", "horse", "sheep"}

# Gains couleur de save_rgb_jpeg() (R, G, B), dans l'ordre BGR de cv2.imread.
# Les diviser redonne l'image brute que voit le détecteur pendant la capture.
JPEG_GAINS_BGR = np.array((0.754, 0.883, 0.831), dtype=np.float32)
BIRD_CONFIDENCE_THRESHOLD = 0.45
CROP_PAD = 0.08
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


def detector_label(detection):
    class_id = int(detection[1])
    if class_id < 0 or class_id >= len(CLASSES):
        return None
    label = CLASSES[class_id]
    return "bird" if label in FEEDER_BIRD_ALIASES else label


def relabel_best(detector, capture_dir, thumb_dir, dry_run):
    """
    Réécrit la partie _conf{score}_best{label} du nom des captures étiquetées
    dog/cow/horse/sheep (FEEDER_BIRD_ALIASES) avec le détecteur actuel. Les
    autres captures ne sont pas touchées, ni le préfixe (bird_/motion_/star_,
    qui peut venir d'un tri manuel dans l'admin), ni l'étiquette d'espèce.
    """
    files = sorted(capture_dir.glob("*.jpg"))
    print(f"{len(files)} fichiers à traiter.\n")
    changed = unchanged = errors = 0

    for path in files:
        match = re.search(r"_conf[0-9.]+_best([a-z]+)", path.stem)
        if not match or match.group(1) not in FEEDER_BIRD_ALIASES:
            unchanged += 1
            continue
        img_bgr = cv2.imread(str(path))
        if img_bgr is None:
            print(f"  SKIP (illisible) : {path.name}")
            errors += 1
            continue

        raw = np.clip(img_bgr / JPEG_GAINS_BGR, 0, 255).astype(np.uint8)
        detector.setInput(cv2.dnn.blobFromImage(raw, 0.007843, (300, 300), 127.5))
        best_label, best_score = "none", 0.0
        for d in detector.forward()[0, 0]:
            label = detector_label(d)
            if label is not None and float(d[2]) > best_score:
                best_label, best_score = label, float(d[2])

        new_stem = re.sub(
            r"_conf[0-9.]+_best[a-z]+",
            f"_conf{best_score:.2f}_best{best_label}",
            path.stem,
            count=1,
        )
        new_path = path.with_name(new_stem + ".jpg")
        if new_path == path:
            unchanged += 1
            continue
        if new_path.exists():
            print(f"  SKIP (existe déjà) : {new_path.name}")
            errors += 1
            continue

        if dry_run:
            print(f"  DRY  {path.name}\n    →  {new_path.name}")
        else:
            path.rename(new_path)
            _rename_thumb(path, new_path, thumb_dir)
            print(f"  OK   {new_path.name}")
        changed += 1

    print(f"\nTerminé — {changed} modifiés, {unchanged} inchangés, {errors} erreurs.")
    if dry_run:
        print("(dry-run : aucun fichier modifié)")


def find_bird_crop(detector, img_bgr):
    """
    Retourne le cadre (BGR) du meilleur oiseau détecté, ou None.
    img_bgr est l'image brute reconstituée (voir JPEG_GAINS_BGR), comme la
    frame vue par birdcam_motion.py ; même recadrage que classify_species().
    """
    blob = cv2.dnn.blobFromImage(img_bgr, 0.007843, (300, 300), 127.5)
    detector.setInput(blob)
    detections = detector.forward()[0, 0]

    birds = [
        d for d in detections
        if detector_label(d) == "bird" and float(d[2]) >= BIRD_CONFIDENCE_THRESHOLD
    ]
    if not birds:
        return None
    bbox = max(birds, key=lambda d: float(d[2]))[3:7]

    h, w = img_bgr.shape[:2]
    x1 = max(0, int((float(bbox[0]) - CROP_PAD) * w))
    y1 = max(0, int((float(bbox[1]) - CROP_PAD) * h))
    x2 = min(w, int((float(bbox[2]) + CROP_PAD) * w))
    y2 = min(h, int((float(bbox[3]) + CROP_PAD) * h))
    crop = img_bgr[y1:y2, x1:x2]
    return crop if crop.size else None


def classify(net, labels, crop_bgr):
    # scalefactor=1.0 : le modèle reçoit [0,255] et divise lui-même par 255.
    # swapRB=True : cv2.imread donne du BGR, le modèle attend du RGB.
    blob = cv2.dnn.blobFromImage(
        crop_bgr,
        scalefactor=1.0,
        size=(224, 224),
        mean=(0, 0, 0),
        swapRB=True,
    )
    net.setInput(blob)
    # garden_birds sort déjà des probabilités (softmax intégré à l'export,
    # voir training/export_onnx.py) : ne pas réappliquer de softmax.
    output = net.forward()[0]

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
    parser.add_argument("--best", action="store_true",
                        help="Réécrit _conf/_best des captures dog/cow/horse/sheep (au lieu des espèces)")
    args = parser.parse_args()

    capture_dir = Path(args.dir)

    for path in (SPECIES_MODEL_PATH, SPECIES_LABELS_PATH, PROTOTXT_PATH, DETECTOR_PATH):
        if not path.exists():
            print(f"Fichier manquant : {path}")
            sys.exit(1)

    print(f"Modèle : {SPECIES_MODEL_PATH.name}")
    print(f"Filtre Paris : {len(PARIS_SPECIES)} espèces")
    print("Chargement du modèle...")
    net = cv2.dnn.readNetFromONNX(str(SPECIES_MODEL_PATH))
    detector = cv2.dnn.readNetFromCaffe(str(PROTOTXT_PATH), str(DETECTOR_PATH))
    labels = load_labels(SPECIES_LABELS_PATH)
    print(f"{len(labels)} espèces chargées.\n")

    thumb_dir = Path.home() / "birdcam" / "gallery" / "thumbs"

    if args.best:
        relabel_best(detector, capture_dir, thumb_dir, args.dry_run)
        return

    patterns = ["bird_*.jpg", "star_bird_*.jpg"]
    if args.retag:
        # spconf1.00 = espèce corrigée à la main dans l'admin : ne jamais l'écraser.
        files = sorted(
            f for pat in patterns for f in capture_dir.glob(pat)
            if "_spconf1.00" not in f.name
        )
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

        raw = np.clip(img_bgr / JPEG_GAINS_BGR, 0, 255).astype(np.uint8)
        crop = find_bird_crop(detector, raw)
        species, score = classify(net, labels, crop) if crop is not None else (None, 0.0)

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
