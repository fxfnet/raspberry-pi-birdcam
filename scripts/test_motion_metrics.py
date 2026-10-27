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
results.append(check("tache pleine : blob == 400", blob == 400))
results.append(check("tache pleine : blob_px == 400", blob_px == 400))
results.append(check("pas de saut de luminosité", shift == 0.0))

# Deux carrés de 20 px : écart de 10 px (fusionnés) puis de 20 px (séparés).
for gap, expected in ((10, (1000, 800)), (20, (400, 400))):
    two = empty.copy()
    two[100:120, 100:120] = 255
    two[100:120, 120 + gap:140 + gap] = 255
    got = motion_metrics(two, empty, empty)[:2]
    results.append(check(f"deux taches à {gap} px : {expected}", got == expected))

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

# Dans la boucle de capture, l'appel est protégé par un try et précède previous_gray = None.
import ast
tree = ast.parse((Path(__file__).resolve().parent.parent / "birdcam_motion.py").read_text())
call = None
for node in ast.walk(tree):
    if isinstance(node, ast.Try):
        for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "motion_metrics":
                call = (node, sub)
if call is None:
    results.append(check("appel motion_metrics dans un try", False))
else:
    node, sub = call
    args = [a.id for a in sub.args]
    reraises = any(isinstance(n, ast.Raise) for h in node.handlers for n in ast.walk(h))
    results.append(check("appel dans un try qui ne relance pas", bool(node.handlers) and not reraises))
    results.append(check("arguments threshold_image, previous_gray, gray", args == ["threshold_image", "previous_gray", "gray"]))
    reset = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "previous_gray" for t in n.targets)
             and isinstance(n.value, ast.Constant) and n.value.value is None]
    results.append(check("appel avant previous_gray = None", any(node.lineno < r for r in reset)))

sys.exit(0 if all(results) else 1)
