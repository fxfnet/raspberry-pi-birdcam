#!/usr/bin/env python3
"""
Teste le regroupement des rafales de la galerie, sans caméra ni OpenCV.
Usage : python3 scripts/test_gallery_bursts.py   (Flask requis)
"""
import importlib.util
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)
CAPTURES = HOME / "birdcam" / "captures"
CAPTURES.mkdir(parents=True)
sys.modules["cv2"] = types.ModuleType("cv2")  # seules les miniatures en ont besoin

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


def burst(prefix, hhmmss, motion, mtime=None, start_ms=0, step_ms=120):
    """Écrit une rafale de 8 photos, dans le désordre, et rend leurs noms dans l'ordre de prise."""
    names = []
    for index in range(8):
        ms = start_ms + index * step_ms
        seconds, millis = divmod(ms, 1000)
        stamp = f"{hhmmss[:4]}{int(hhmmss[4:]) + seconds:02d}_{millis:03d}"
        names.append(f"{prefix}_20261001_{stamp}_burst{index}_motion{motion}_conf0.90_bestbird.jpg")
    for name in reversed(names):
        path = CAPTURES / name
        path.write_bytes(b"jpg")
        stamp = mtime if mtime is not None else time.time()
        os.utime(path, (stamp, stamp))
    return names


def groups():
    return [[image["name"] for image in group["images"]] for group in app.group_bursts(app.get_all_images())]


def reset():
    for path in CAPTURES.iterdir():
        path.unlink()


# Deux déclenchements au même score, à 1 s d'écart : deux rafales, pas une.
first = burst("bird", "100000", 4800, mtime=1000)
second = burst("bird", "100002", 4800, mtime=1002)
check("même score à 1 s d'écart : deux rafales de 8", [len(g) for g in groups()] == [8, 8])
check("rafale la plus récente en premier", groups()[0] == second)

# Mtime identiques (copie qui arrondit les dates) : ordre de prise conservé.
reset()
names = burst("bird", "110000", 1500, mtime=2000)
check("mtime égales : burst0 à burst7 dans l'ordre", groups() == [names])

# Photo étoilée ou renommée (_1) dans la rafale : toujours dans le même groupe.
reset()
names = burst("bird", "120000", 2000, mtime=3000)
(CAPTURES / names[3]).rename(CAPTURES / ("star_" + names[3]))
(CAPTURES / names[5]).rename(CAPTURES / names[5].replace(".jpg", "_1.jpg"))
check("star_ et _1 restent dans la rafale", [len(g) for g in groups()] == [8])

# Nom à date impossible : pas d'erreur, la galerie et la visionneuse répondent.
reset()
burst("bird", "130000", 3000, mtime=4000)
bad = "bird_20261399_250000_000_burst0_motion1500_conf0.90_bestbird.jpg"
(CAPTURES / bad).write_bytes(b"jpg")
client = app.app.test_client()
check("date impossible : / répond 200", client.get("/?filter=all").status_code == 200)
check("date impossible : /view répond 200", client.get(f"/view/{bad}?filter=all").status_code == 200)

# Mode public (celui qu'expose Funnel) : les icônes sont servies et déclarées.
check("public : /static/mesange.svg répond 200", client.get("/static/mesange.svg").status_code == 200)
check("public : icône déclarée dans /", 'href="/static/mesange.svg"' in client.get("/?filter=all").get_data(as_text=True))

# Accueil public : logo, tuiles de chiffres, dernière visite, vignette « Latest star » nette.
reset()
star = "star_bird_20261001_100000_000_burst0_motion1500_conf0.90_bestbird_spparus_major_spconf0.88.jpg"
(CAPTURES / star).write_bytes(b"jpg")
recent = time.time() - 12 * 60
os.utime(CAPTURES / star, (recent, recent))
home = client.get("/").get_data(as_text=True)
check("accueil : logo dans l'en-tête", 'class="brand-logo" src="/static/mesange.svg"' in home)
check("accueil : tuiles de chiffres", len(re.findall(r'<div class="stat-tile( star| today)?">', home)) == 3)
check("accueil : dernière visite relative", "Last visit <strong>12 min ago</strong>" in home)
check("accueil : vignette « Latest star » en pleine résolution (/image), pas en miniature",
      re.search(r'<div class="latest-star-photo">\s*<img src="/image/' + re.escape(star), home) is not None)
check("accueil : espèce en titre de la vignette", '<div class="latest-star-title">Mésange charbonnière</div>' in home)
check("accueil : certitude affichée", "Certainty 88 %" in home)
admin_free = client.get("/?filter=all").get_data(as_text=True)
check("accueil : plus d'ancien décompte « affichées »", "affichées" not in admin_free)

# Mise en page : le texte de la vignette garde un minimum (sinon le titre est coupé à 700-880 px),
# l'en-tête compact masque toujours les nouveaux blocs.
check("vignette : la colonne texte garde un minimum de 260 px", "minmax(260px, 1fr)" in app.HTML_TEMPLATE)
check("en-tête compact : .public-info masqué (tuiles, visite, pastilles)",
      "header.compact .public-info" in app.HTML_TEMPLATE)

# « Last visit » : l'heure affichée est celle du dernier oiseau, pas celle d'un motion_ plus récent.
reset()
bird = "bird_20261001_050000_000_burst0_motion1500_conf0.90_bestbird.jpg"
motion = "motion_20261001_100000_000_burst0_motion1500_conf0.10_bestnone.jpg"
(CAPTURES / bird).write_bytes(b"jpg")
(CAPTURES / motion).write_bytes(b"jpg")
five_hours, one_minute = time.time() - 5 * 3600, time.time() - 60
os.utime(CAPTURES / bird, (five_hours, five_hours))
os.utime(CAPTURES / motion, (one_minute, one_minute))
page = client.get("/").get_data(as_text=True)
last_visit = re.search(r'<div class="last-visit">(.*?)</div>', page, re.S).group(1)
check("dernière visite : 5 h, avec l'heure de l'oiseau",
      "5 h ago" in last_visit and time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(five_hours)) in last_visit)
check("dernière visite : l'heure du motion_ n'est pas affichée",
      time.strftime("%H:%M:%S", time.localtime(one_minute)) not in last_visit)

# Cas limites de la vignette et de l'en-tête.
check("aucune étoile : pas de vignette", 'class="latest-star"' not in page)
reset()
check("aucun oiseau : pas de « Last visit »", "Last visit" not in client.get("/").get_data(as_text=True))
plain = "star_motion_20261001_100000_000_burst0_motion1500_conf0.30_bestperson.jpg"
(CAPTURES / plain).write_bytes(b"jpg")
page = client.get("/?filter=all").get_data(as_text=True)
check("étoile sans espèce : titre générique, pas de certitude",
      '<div class="latest-star-title">A favourite visitor</div>' in page and "Certainty" not in page)
reset()
unknown = "star_bird_20261001_100000_000_burst0_motion1500_conf0.90_bestbird_spzzz_unknown_spconf0.80.jpg"
(CAPTURES / unknown).write_bytes(b"jpg")
check("espèce sans nom français : retombe sur le nom du fichier",
      '<div class="latest-star-title">Zzz Unknown</div>' in client.get("/").get_data(as_text=True))

for seconds, label in ((5, "just now"), (59, "just now"), (60, "1 min ago"), (3599, "59 min ago"), (3600, "1 h ago"),
                       (86399, "23 h ago"), (86400, "yesterday"), (3 * 86400, "3 days ago"), (-30, "just now")):
    check(f"format_ago({seconds}) = {label}", app.format_ago(seconds) == label)

# X-Forwarded-Proto pris en compte, X-Forwarded-For ignoré.
page = client.get("/", headers={"X-Forwarded-Proto": "https"}).get_data(as_text=True)
check("og:url en https derrière le proxy", 'content="https://localhost/"' in page)
check("ProxyFix configuré avec x_for=0", app.app.wsgi_app.x_for == 0 and app.app.wsgi_app.x_proto == 1)

print("Tous les tests passent." if not FAILURES else f"{len(FAILURES)} échec(s).")
sys.exit(1 if FAILURES else 0)
