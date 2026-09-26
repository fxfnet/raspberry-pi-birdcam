#!/usr/bin/env python3
"""
Exporte les captures dont l'espèce a été corrigée à la main dans l'admin
(suffixe _spconf1.00) en images d'entraînement : cadre de l'oiseau détecté par
MobileNetSSD, aux couleurs du JPEG enregistré, comme le voit le classifieur.
Sans cadre détecté (gros plan), l'image entière est exportée.

À lancer sur le Pi (modèles et captures y sont), puis copier le dossier de
sortie dans dataset/ sur le Mac avant training/train.py.

Usage :
    python3 training/export_captures.py --out /tmp/birdcam_captures_dataset
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import retag_history as rh  # noqa: E402  (mêmes réglages de détection et recadrage)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(rh.BASE_DIR / "captures"), help="Dossier captures")
    parser.add_argument("--out", required=True, help="Dossier de sortie (un sous-dossier par espèce)")
    args = parser.parse_args()

    detector = cv2.dnn.readNetFromCaffe(str(rh.PROTOTXT_PATH), str(rh.DETECTOR_PATH))
    out_dir = Path(args.out)
    exported = full_frame = 0

    for path in sorted(Path(args.dir).glob("*_spconf1.00*.jpg")):
        match = rh.re.search(r"_sp([a-z_]+?)_spconf1\.00", path.name)
        img_bgr = cv2.imread(str(path))
        if not match or img_bgr is None:
            continue

        raw = np.clip(img_bgr / rh.JPEG_GAINS_BGR, 0, 255).astype(np.uint8)
        crop = rh.find_bird_crop(detector, raw)
        if crop is None:
            image = img_bgr
            full_frame += 1
        else:
            image = np.clip(crop * rh.JPEG_GAINS_BGR, 0, 255).astype(np.uint8)

        species_dir = out_dir / match.group(1)
        species_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(species_dir / f"cap_{rh.capture_key(path.name)}.jpg"), image)
        exported += 1

    print(f"{exported} images exportées dans {out_dir} ({full_frame} sans cadre, image entière).")


if __name__ == "__main__":
    main()
