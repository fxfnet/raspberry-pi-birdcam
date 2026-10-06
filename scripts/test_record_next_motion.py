#!/usr/bin/env python3
"""
Teste que record_next_motion.py rend toujours la caméra à la capture photo,
et que l'unité systemd la rend aussi quand le script ne peut plus le faire.
Sans caméra ni OpenCV : picamera2, cv2 et systemctl sont simulés.
Usage : python3 scripts/test_record_next_motion.py
"""
import importlib.util
import os
import re
import signal
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["HOME"] = tempfile.mkdtemp()

class Anything:
    def __init__(self, *_args, **_kwargs):
        pass

    def close_output(self):
        pass


for name, attrs in {
    "cv2": {},
    "picamera2": {"Picamera2": Anything},
    "picamera2.encoders": {"H264Encoder": Anything},
    "picamera2.outputs": {"CircularOutput2": Anything, "PyavOutput": Anything},
}.items():
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module

spec = importlib.util.spec_from_file_location("record", ROOT / "scripts" / "record_next_motion.py")
record = importlib.util.module_from_spec(spec)
spec.loader.exec_module(record)

FAILURES = []


def check(label, condition):
    print(("ok    : " if condition else "ECHEC : ") + label)
    if not condition:
        FAILURES.append(label)


class FakeCamera:
    def __init__(self, events, on_stop_recording=None):
        self.events = events
        self.on_stop_recording = on_stop_recording

    def configure(self, *_):
        pass

    def create_video_configuration(self, **_):
        return {}

    def start_recording(self, *_):
        raise RuntimeError("fin de l'essai")  # sort de la boucle vers le finally

    def stop_recording(self):
        self.events.append("stop_recording")
        if self.on_stop_recording:
            self.on_stop_recording()

    def close(self):
        self.events.append("close")


def run(on_systemctl=None, on_stop_recording=None):
    events = []

    def fake_run(cmd, **_kw):
        events.append("systemctl " + cmd[2])
        if on_systemctl and cmd[2] == "stop":
            on_systemctl()

    record.subprocess.run = fake_run
    record.Picamera2 = lambda: FakeCamera(events, on_stop_recording)
    record.CLIPS_DIR = Path(os.environ["HOME"]) / "clips"
    try:
        record.main()
    except (RuntimeError, SystemExit):
        pass
    return events


def sigterm():
    os.kill(os.getpid(), signal.SIGTERM)


events = run()
check("erreur en cours de route : la capture photo repart", events[-1] == "systemctl start")

events = run(on_systemctl=sigterm)
check("SIGTERM pendant l'arrêt de birdcam : la capture photo repart", events[-1] == "systemctl start")

events = run(on_stop_recording=sigterm)
check("SIGTERM pendant le nettoyage : close et relance quand même",
      events[-2:] == ["close", "systemctl start"])

events = run(on_stop_recording=lambda: (_ for _ in ()).throw(RuntimeError("gel")))
check("stop_recording échoue : close est tout de même appelé", "close" in events and events[-1] == "systemctl start")

unit = (ROOT / "systemd" / "birdcam-clip.service").read_text()
check("l'unité relance birdcam quelle que soit la sortie",
      re.search(r"^ExecStopPost=\+?/usr/bin/systemctl start .*birdcam\.service", unit, re.M) is not None)
# Annulation pendant l'enregistrement : la sortie du clip est fermée, donc le MP4 est lisible.
closed = []


class FakeCircular(Anything):
    def open_output(self, *_):
        closed.append("open")

    def close_output(self):
        closed.append("close")


class StartableCamera(FakeCamera):
    def start_recording(self, *_):
        pass


record.CircularOutput2 = FakeCircular
record.Picamera2 = lambda: StartableCamera([])
record.motion_gray = lambda _camera: 0
record.cv2 = types.SimpleNamespace(
    absdiff=lambda a, b: 0, threshold=lambda *_: (0, 0), countNonZero=lambda _d: 10 ** 6, THRESH_BINARY=0)


def sleep(seconds):
    if seconds == record.CLIP_SECONDS:
        sigterm()


record.time = types.SimpleNamespace(sleep=sleep, monotonic=__import__("time").monotonic)
record.subprocess.run = lambda *_a, **_k: None
record.CLIPS_DIR = Path(os.environ["HOME"]) / "clips"
try:
    record.main()
except SystemExit:
    pass
check("annulation pendant le clip : la sortie est fermée", closed == ["open", "close"])

check("l'unité entre en conflit avec birdcam (un restart de birdcam annule le clip)",
      re.search(r"^Conflicts=.*birdcam\.service", unit, re.M) is not None)
limit = re.search(r"^RuntimeMaxSec=(\d+)", unit, re.M)
check("l'unité borne la durée au-delà de l'attente maximale du script",
      limit is not None and int(limit.group(1)) >= 90 + record.MAX_WAIT_SECONDS + record.WARMUP_SECONDS + record.CLIP_SECONDS + 60)

# L'arrêt du clip relance birdcam : il doit être demandé avant celui de birdcam.
for name in ("scripts/stop_services.sh", "RESTORE.md"):
    lines = (ROOT / name).read_text().splitlines()
    clip = next((i for i, l in enumerate(lines) if "systemctl stop birdcam-clip" in l), None)
    camera = next((i for i, l in enumerate(lines) if re.search(r"systemctl stop birdcam( |$)", l)), None)
    check(f"{name} : stop birdcam-clip avant stop birdcam", clip is not None and camera is not None and clip < camera)

print("Tous les tests passent." if not FAILURES else f"{len(FAILURES)} échec(s).")
sys.exit(1 if FAILURES else 0)
