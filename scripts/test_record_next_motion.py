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
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REAL_RUN = subprocess.run  # les tests remplacent subprocess.run, partagé avec le script
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


COMMANDS = []


def run(on_systemctl=None, on_stop_recording=None):
    events = []
    COMMANDS.clear()

    def fake_run(cmd, **_kw):
        COMMANDS.append(cmd)
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
# Sans --no-block, le start de birdcam attendrait la fin du clip, qui attend la fin du script.
check("le start de birdcam est sans attente (--no-block)",
      COMMANDS[-1] == ["sudo", "systemctl", "start", "--no-block", "birdcam"])

events = run(on_systemctl=sigterm)
check("SIGTERM pendant l'arrêt de birdcam : la capture photo repart", events[-1] == "systemctl start")

events = run(on_stop_recording=sigterm)
check("SIGTERM pendant le nettoyage : close et relance quand même",
      events[-2:] == ["close", "systemctl start"])

events = run(on_stop_recording=lambda: (_ for _ in ()).throw(RuntimeError("gel")))
check("stop_recording échoue : close est tout de même appelé", "close" in events and events[-1] == "systemctl start")

unit = (ROOT / "systemd" / "birdcam-clip.service").read_text()
check("l'unité relance birdcam sans attente, quelle que soit la sortie",
      re.search(r"^ExecStopPost=\+?/usr/bin/systemctl start --no-block birdcam\.service", unit, re.M) is not None)
# Conflicts= n'ordonne rien : sans After=, birdcam démarrerait pendant l'arrêt du clip et boucler en échec.
check("l'unité est ordonnée après birdcam",
      re.search(r"^After=.*\bbirdcam\.service", unit, re.M) is not None)
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
fixed_clips = []
record.PyavOutput = lambda path: Path(path).write_bytes(b"mp4")  # crée le fichier du clip
record.fix_clip = fixed_clips.append
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
check("annulation pendant le clip : le clip fermé est tout de même corrigé pour iOS",
      len(fixed_clips) == 1 and fixed_clips[0].name.startswith("clip_"))

check("l'unité entre en conflit avec birdcam (un restart de birdcam annule le clip)",
      re.search(r"^Conflicts=.*birdcam\.service", unit, re.M) is not None)
limit = re.search(r"^RuntimeMaxSec=(\d+)", unit, re.M)
check("l'unité borne la durée au-delà de l'attente maximale du script",
      limit is not None and int(limit.group(1)) >= 90 + record.MAX_WAIT_SECONDS + record.WARMUP_SECONDS + record.CLIP_SECONDS + 60)

# fix_clip : conteneur reconstruit d'après le flux réel (iOS), clip d'origine gardé en cas d'échec.
spec2 = importlib.util.spec_from_file_location("record_real", ROOT / "scripts" / "record_next_motion.py")
real = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(real)
work = Path(tempfile.mkdtemp())
clip = work / "clip_20261007_100000.mp4"

calls = []


def fake_ffmpeg(cmd, **_kw):
    calls.append(cmd)
    Path(cmd[-1]).write_bytes(b"fixed" if cmd[-2] == "mp4" else b"ts")


clip.write_bytes(b"original")
real.subprocess.run = fake_ffmpeg
real.fix_clip(clip)
check("fix_clip : le clip est remplacé par la version reconstruite", clip.read_bytes() == b"fixed")
check("fix_clip : passage par un flux intermédiaire, sans ré-encodage, index au début",
      any("h264_mp4toannexb" in c for c in calls) and all("copy" in c for c in calls)
      and any("+faststart" in c for c in calls))
check("fix_clip : aucun fichier temporaire ne reste", sorted(p.name for p in work.iterdir()) == [clip.name])


def failing_ffmpeg(cmd, **_kw):
    Path(cmd[-1]).write_bytes(b"partial")
    raise real.subprocess.CalledProcessError(1, cmd)


clip.write_bytes(b"original")
real.subprocess.run = failing_ffmpeg
real.fix_clip(clip)
check("fix_clip : ffmpeg échoue, le clip d'origine est gardé", clip.read_bytes() == b"original")
check("fix_clip : échec, aucun fichier temporaire ne reste", sorted(p.name for p in work.iterdir()) == [clip.name])

import shutil
if shutil.which("ffmpeg"):
    real.subprocess.run = REAL_RUN
    REAL_RUN(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    before = REAL_RUN(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames",
                     "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout.strip()
    real.fix_clip(clip)
    after = REAL_RUN(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames",
                    "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout.strip()
    check("fix_clip avec le vrai ffmpeg : même nombre d'images, fichier lisible", before == after != "")
else:
    print("saut  : ffmpeg absent, test réel de fix_clip ignoré")

# L'arrêt du clip relance birdcam : il doit être demandé avant celui de birdcam.
for name in ("scripts/stop_services.sh", "RESTORE.md"):
    lines = (ROOT / name).read_text().splitlines()
    clip = next((i for i, l in enumerate(lines) if "systemctl stop birdcam-clip" in l), None)
    camera = next((i for i, l in enumerate(lines) if re.search(r"systemctl stop birdcam( |$)", l)), None)
    check(f"{name} : stop birdcam-clip avant stop birdcam", clip is not None and camera is not None and clip < camera)

print("Tous les tests passent." if not FAILURES else f"{len(FAILURES)} échec(s).")
sys.exit(1 if FAILURES else 0)
