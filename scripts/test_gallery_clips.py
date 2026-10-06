#!/usr/bin/env python3
"""
Teste la section Clips de la galerie et le bouton « vidéo du prochain mouvement »,
sans caméra, sans OpenCV ni systemd (sudo systemctl est simulé).
Usage : python3 scripts/test_gallery_clips.py   (Flask requis)
"""
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)
os.environ["BIRDCAM_ADMIN"] = "1"
(HOME / "birdcam" / "captures").mkdir(parents=True)
sys.modules["cv2"] = types.ModuleType("cv2")

spec = importlib.util.spec_from_file_location(
    "gallery_app", Path(__file__).resolve().parent.parent / "gallery" / "app.py"
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

FAILURES = []


def check(label, condition):
    print(("ok    : " if condition else "ECHEC : ") + label)
    if not condition:
        FAILURES.append(label)


active = {"birdcam": True, app.CLIP_SERVICE: False}
calls = []


def fake_status(name):
    return {"name": name, "active": active.get(name, False), "status": "x"}


def fake_run(cmd, **_kwargs):
    calls.append(cmd)
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


app.service_status = fake_status
app.subprocess.run = fake_run
client = app.app.test_client()

NAME = "clip_20261006_092717.mp4"
check("clips/ est à côté de captures/", app.CLIPS_DIR == (HOME / "birdcam").resolve() / "clips")

check("sans clip : /clips répond 200 et le dit", "Aucun clip" in client.get("/clips").get_data(as_text=True))

app.CLIPS_DIR.mkdir()
(app.CLIPS_DIR / NAME).write_bytes(b"0123456789")
(app.CLIPS_DIR / "autre.mp4").write_bytes(b"x")
page = client.get("/clips").get_data(as_text=True)
check("le clip est listé avec sa date", NAME in page and "2026-10-06 09:27:17" in page)
check("un fichier au nom étranger n'est pas listé", "autre.mp4" not in page)
check("lien Clips dans la galerie", 'href="/clips"' in client.get("/").get_data(as_text=True))

response = client.get(f"/clip/{NAME}", headers={"Range": "bytes=2-4"})
check("lecture partielle (Range) : 206 et les bons octets", response.status_code == 206 and response.data == b"234")
check("type video/mp4", response.mimetype == "video/mp4")
check("nom étranger refusé : 404", client.get("/clip/autre.mp4").status_code == 404)
check("traversée de dossier refusée : 404", client.get("/clip/..%2Fcorrections.json").status_code == 404)

# Bouton : proposé quand la caméra tourne, lance le service sans bloquer.
check("bouton proposé", "/clip/request" in client.get("/").get_data(as_text=True))
client.post("/clip/request")
check("la demande lance birdcam-clip sans bloquer",
      calls == [["sudo", "systemctl", "start", "--no-block", app.CLIP_SERVICE]])

# Déjà en attente : pas de second lancement, bouton Annuler à la place.
calls.clear()
active[app.CLIP_SERVICE] = True
client.post("/clip/request")
check("déjà en attente : pas de relance", calls == [])
page = client.get("/").get_data(as_text=True)
check("Annuler proposé, pas le bouton de demande", "/clip/cancel" in page and "/clip/request" not in page)
client.post("/clip/cancel")
check("l'annulation arrête birdcam-clip", calls == [["sudo", "systemctl", "stop", app.CLIP_SERVICE]])

# Caméra arrêtée volontairement : pas de clip (il la redémarrerait).
calls.clear()
active[app.CLIP_SERVICE] = False
active["birdcam"] = False
client.post("/clip/request")
check("caméra arrêtée : pas de lancement", calls == [])
check("caméra arrêtée : bouton absent", "/clip/request" not in client.get("/").get_data(as_text=True))

# Pendant l'attente : ni Start ni Test Camera (le clip tient la caméra), refus côté serveur aussi.
calls.clear()
active[app.CLIP_SERVICE] = True
active["birdcam"] = False
page = client.get("/").get_data(as_text=True)
check("attente : ni Start Camera ni Test Camera", "Start Camera" not in page and "/camera/test" not in page)
client.post("/camera/toggle")
client.post("/camera/test")
check("attente : toggle et test sans effet", calls == [])
active[app.CLIP_SERVICE] = False
active["birdcam"] = True

# Échec du lancement (unité absente) : message visible, pas de redirection silencieuse.
app.subprocess.run = lambda cmd, **_kw: types.SimpleNamespace(returncode=5, stdout="", stderr="Unit birdcam-clip.service not found.")
response = client.post("/clip/request")
check("lancement en échec : 502 avec le motif", response.status_code == 502 and "not found" in response.get_data(as_text=True))


def timeout(cmd, **_kw):
    raise app.subprocess.TimeoutExpired(cmd, 30)


app.subprocess.run = timeout
check("annulation trop lente : pas d'erreur 500", client.post("/clip/cancel").status_code == 302)
check("lancement trop lent : 504", client.post("/clip/request").status_code == 504)
app.subprocess.run = fake_run

# Suppression.
check("suppression d'un nom étranger : 404", client.post("/clip/delete/autre.mp4").status_code == 404)
client.post(f"/clip/delete/{NAME}")
check("suppression du clip", not (app.CLIPS_DIR / NAME).exists())

# Mode public : aucune action, mais la liste reste visible.
app.ADMIN_MODE = False
(app.CLIPS_DIR / NAME).write_bytes(b"0123456789")
active["birdcam"] = True
calls.clear()
check("public : demande refusée (403)", client.post("/clip/request").status_code == 403)
check("public : annulation refusée (403)", client.post("/clip/cancel").status_code == 403)
check("public : suppression refusée (403)", client.post(f"/clip/delete/{NAME}").status_code == 403)
check("public : aucun appel systemctl", calls == [])
page = client.get("/clips").get_data(as_text=True)
check("public : clips visibles, sans bouton Supprimer", NAME in page and "Supprimer" not in page)
check("public : pas de bouton de demande", "/clip/request" not in client.get("/").get_data(as_text=True))

print("Tous les tests passent." if not FAILURES else f"{len(FAILURES)} échec(s).")
sys.exit(1 if FAILURES else 0)
