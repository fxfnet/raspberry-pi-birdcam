#!/usr/bin/env python3
"""
Filme un clip vidéo MP4 au prochain mouvement devant la mangeoire, puis rend
la caméra à la capture photo.

La caméra ne sert qu'à un programme à la fois : le script arrête
birdcam.service, guette le mouvement (mêmes seuils que birdcam_motion.py,
ramenés à une image de 320x240), enregistre CLIP_SECONDS secondes précédées
de PRE_ROLL_MS de tampon circulaire, puis relance birdcam.service dans tous
les cas (clip pris, délai dépassé, erreur, SIGTERM ou déconnexion SSH).
Pendant l'attente, aucune photo n'est prise.

Lancé par le bouton de la galerie admin, via birdcam-clip.service :
    sudo systemctl start --no-block birdcam-clip
Annulation : sudo systemctl stop birdcam-clip (la capture photo repart).
"""
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import CircularOutput2, PyavOutput

# Même règle que gallery/app.py : à côté des captures, sur la clé USB.
CLIPS_DIR = (Path.home() / "birdcam" / "captures").resolve().parent / "clips"
CLIP_SECONDS = 10
PRE_ROLL_MS = 2000
MAX_WAIT_SECONDS = 3600
WARMUP_SECONDS = 3

VIDEO_SIZE = (1280, 960)
FRAME_RATE = 25
BITRATE = 5_000_000

# birdcam_motion.py : 640x480, flou 21, écart de 30, 1200 pixels.
# Ici 320x240 : quatre fois moins de pixels, flou réduit de moitié.
MOTION_SIZE = (320, 240)
MOTION_BLUR = (11, 11)
PIXEL_DIFF_THRESHOLD = 30
MOTION_THRESHOLD = 300


def log(message):
    print(f"{datetime.now():%H:%M:%S} {message}", flush=True)


def systemctl(action):
    subprocess.run(["sudo", "systemctl", action, "birdcam"], check=False)


def stop_on_signal(signum, _frame):
    # Fait passer par le finally, donc par la relance de la capture photo.
    raise SystemExit(f"signal {signum}")


def motion_gray(picam2):
    yuv = picam2.capture_array("lores")
    width, height = MOTION_SIZE
    return cv2.GaussianBlur(yuv[:height, :width], MOTION_BLUR, 0)


def main():
    signal.signal(signal.SIGTERM, stop_on_signal)
    signal.signal(signal.SIGHUP, stop_on_signal)
    CLIPS_DIR.mkdir(exist_ok=True)

    log("Arrêt de la capture photo")
    systemctl("stop")
    picam2 = None
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(
            main={"size": VIDEO_SIZE, "format": "YUV420"},
            lores={"size": MOTION_SIZE, "format": "YUV420"},
            controls={"FrameRate": FRAME_RATE},
        ))
        circular = CircularOutput2(buffer_duration_ms=PRE_ROLL_MS)
        picam2.start_recording(H264Encoder(bitrate=BITRATE), circular)
        time.sleep(WARMUP_SECONDS)

        log(f"En attente d'un mouvement ({MAX_WAIT_SECONDS // 60} min au plus)")
        previous = motion_gray(picam2)
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        while time.monotonic() < deadline:
            gray = motion_gray(picam2)
            delta = cv2.threshold(cv2.absdiff(previous, gray), PIXEL_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
            score = cv2.countNonZero(delta)
            previous = gray
            if score > MOTION_THRESHOLD:
                path = CLIPS_DIR / f"clip_{datetime.now():%Y%m%d_%H%M%S}.mp4"
                log(f"Mouvement (score {score}), enregistrement de {CLIP_SECONDS} s : {path}")
                circular.open_output(PyavOutput(str(path)))
                time.sleep(CLIP_SECONDS)
                circular.close_output()
                log(f"Clip enregistré : {path} ({path.stat().st_size // 1024} Ko)")
                return 0

        log("Aucun mouvement dans le délai, pas de clip")
        return 1
    finally:
        if picam2 is not None:
            try:
                picam2.stop_recording()
                picam2.close()
            except Exception as error:
                log(f"Arrêt de la caméra : {error}")
        log("Relance de la capture photo")
        systemctl("start")


if __name__ == "__main__":
    sys.exit(main())
