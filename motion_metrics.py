"""
Mesures de forme d'un déclenchement de mouvement, pour le journal de la
capture : elles servent à rejouer plus tard des filtres contre les fausses
alarmes (feuilles, soleil) sans rien changer au déclenchement lui-même.
"""

import cv2
import numpy as np

CLOSE_KERNEL = np.ones((15, 15), np.uint8)


def motion_metrics(threshold_image, previous_gray, gray):
    """
    Renvoie (blob, blob_px, luma_shift) :
    blob       surface de la plus grande tache de mouvement (taches proches fusionnées)
    blob_px    pixels réellement changés dans cette tache
    luma_shift écart de luminosité moyenne entre les deux images (soleil, nuage)
    """
    closed = cv2.morphologyEx(threshold_image, cv2.MORPH_CLOSE, CLOSE_KERNEL)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(closed)
    blob = blob_px = 0
    if count > 1:
        biggest = 1 + int(stats[1:, cv2.CC_STAT_AREA].argmax())
        blob = int(stats[biggest, cv2.CC_STAT_AREA])
        blob_px = int(cv2.countNonZero(threshold_image * (labels == biggest).astype(np.uint8)))
    luma_shift = abs(float(gray.mean()) - float(previous_gray.mean()))
    return blob, blob_px, luma_shift
