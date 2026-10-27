#!/usr/bin/env python3
"""
Teste les mesures de forme journalisées à chaque déclenchement.
Usage : python3 scripts/test_motion_metrics.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from motion_metrics import motion_metrics


def check(name, ok):
    print(("OK   " if ok else "ECHEC"), name)
    return ok


empty = np.zeros((480, 640), np.uint8)
results = []

# Aucun mouvement.
results.append(check("rien -> (0, 0, 0)", motion_metrics(empty, empty, empty) == (0, 0, 0.0)))

# Une tache pleine de 20x20 : la tache et ses pixels changés valent 400.
thr = empty.copy()
thr[100:120, 100:120] = 255
blob, blob_px, shift = motion_metrics(thr, empty, empty)
results.append(check("tache pleine : blob >= 400", blob >= 400))
results.append(check("tache pleine : blob_px == 400", blob_px == 400))
results.append(check("pas de saut de luminosité", shift == 0.0))

# Feuilles : beaucoup de petits points éloignés -> aucune grosse tache.
leaves = empty.copy()
for y in range(20, 460, 60):
    for x in range(20, 620, 60):
        leaves[y:y + 3, x:x + 3] = 255
blob, blob_px, _ = motion_metrics(leaves, empty, empty)
results.append(check("feuilles : tache bien plus petite que le total", blob_px < int(np.count_nonzero(leaves)) // 4))

# Soleil : toute l'image s'éclaircit.
bright = np.full((480, 640), 40, np.uint8)
_, _, shift = motion_metrics(empty, empty, bright)
results.append(check("soleil : saut de luminosité == 40", abs(shift - 40.0) < 1e-6))

sys.exit(0 if all(results) else 1)
