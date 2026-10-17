#!/usr/bin/env python3
"""
Teste le veilleur de la birdcam (scripts/ntfy/surveillant_birdcam.py), sans réseau : la galerie et ntfy sont simulés.
Usage : python3 scripts/test_surveillant_birdcam.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("veilleur", ROOT / "scripts" / "ntfy" / "surveillant_birdcam.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

FAILURES = []


def check(label, condition):
    print(("ok    : " if condition else "ECHEC : ") + label)
    if not condition:
        FAILURES.append(label)


class Reponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b""


class Reseau:
    """urlopen simulé : `galerie` = 'ok' | 'hs' | code HTTP ; `ntfy` = 'ok' | 'hs' | 'delai' (message pris puis réponse perdue)."""

    def __init__(self, galerie="ok", ntfy="ok"):
        self.galerie, self.ntfy, self.envois = galerie, ntfy, []

    def __call__(self, req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if "ntfy" in url:
            if self.ntfy == "hs":
                raise OSError("ntfy hs")
            self.envois.append(json.loads(req.data.decode()))
            if self.ntfy == "delai":
                raise TimeoutError("réponse perdue")
            return Reponse(200)
        if self.galerie == "hs":
            raise OSError("injoignable")
        return Reponse(200 if self.galerie == "ok" else self.galerie)


tmp = tempfile.mkdtemp()
CFG = {"gallery": "http://g", "url": "https://ntfy.sh", "topic": "birdcam-test", "token": None}
_n = [0]


def nouvel_etat():
    _n[0] += 1
    return os.path.join(tmp, "e%d" % _n[0], "veilleur.json")


def minutes(cfg, reseau, etat, debut, n):
    for i in range(n):
        v.run_once(cfg, reseau, now=debut + 60 * i, state_path=etat)


# --- sonde ---------------------------------------------------------------------------------------------------
check("sonde : 200 -> joignable", v.probe("http://g", Reseau("ok")) is True)
check("sonde : exception -> injoignable", v.probe("http://g", Reseau("hs")) is False)
check("sonde : HTTP 500 -> injoignable", v.probe("http://g", Reseau(500)) is False)
check("sonde : la page statique existe dans la galerie", v.PROBE.startswith("/static/")
      and (ROOT / "gallery" / "static" / v.PROBE.split("/")[-1]).is_file())

# --- machine à états -----------------------------------------------------------------------------------------
e, envois = dict(v.EMPTY), []
for i in range(v.CONFIRMATIONS - 1):
    e, kind = v.advance(False, e, 1000 + 60 * i)
    envois.append(kind)
check("quatre échecs : rien", envois == [None] * (v.CONFIRMATIONS - 1))
e, kind = v.advance(False, e, 2000)
check("cinquième échec : alarme", kind == "alarm" and e["in_alarm"] == 1)
e, kind = v.advance(False, e, 2060)
check("échec suivant : pas de doublon", kind is None)
e, kind = v.advance(False, e, 2000 + v.REMINDER_S - 60)
check("pas de rappel avant 6 h", kind is None)
e, kind = v.advance(False, e, 2000 + v.REMINDER_S)
check("rappel après 6 h", kind == "reminder")
e, kind = v.advance(True, e, 5000)
check("un seul succès : pas encore de retour", kind is None and e["in_alarm"] == 1)
e, kind = v.advance(True, e, 5060)
check("deux succès : retour", kind == "recovered" and e["in_alarm"] == 0)
e2, _ = v.advance(False, dict(v.EMPTY), 0)
e2, _ = v.advance(True, e2, 60)
e2, _ = v.advance(False, e2, 120)
check("un succès isolé remet le compte d'échecs à zéro", e2["fails"] == 1)
_, kind = v.advance(True, dict(v.EMPTY), 0)
check("tout va bien : aucun envoi", kind is None)

# --- passage complet ------------------------------------------------------------------------------------------
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 1000, v.CONFIRMATIONS)
check("passage : une seule alerte après 5 échecs", len(reseau.envois) == 1)
check("passage : titre, sujet et priorité", reseau.envois and reseau.envois[0]["topic"] == "birdcam-test"
      and reseau.envois[0]["title"].startswith("[Birdcam]") and reseau.envois[0]["priority"] == 4)
reseau = Reseau("ok")
minutes(CFG, reseau, etat, 5000, v.RECOVERY)
check("passage : message de retour", len(reseau.envois) == 1 and reseau.envois[0]["title"].startswith("[Rétabli]"))

# ntfy en panne : l'alerte est reprise, avec une attente croissante (pas un essai par minute)
etat = nouvel_etat()
reseau = Reseau("hs", "hs")
minutes(CFG, reseau, etat, 1000, v.CONFIRMATIONS + 30)
tentatives = len(reseau.envois)
check("ntfy en panne : aucun message n'a pu partir", tentatives == 0)
reseau.ntfy = "ok"
minutes(CFG, reseau, etat, 1000 + 60 * (v.CONFIRMATIONS + 30), 10)
check("ntfy revenu : l'alerte part, une seule fois", len(reseau.envois) == 1 and reseau.envois[0]["title"].startswith("[Birdcam]"))

# ntfy prend le message mais la réponse est perdue : l'envoi n'est pas rejoué à chaque minute
etat = nouvel_etat()
reseau = Reseau("hs", "delai")
minutes(CFG, reseau, etat, 1000, 24 * 60)
check("réponse ntfy perdue pendant 24 h : au plus 55 envois (attente croissante puis toutes les 30 min, contre 1 436 sans attente)", 1 <= len(reseau.envois) <= 55)

# état illisible ou aux types faux : repart de zéro, sans exception, et l'alerte part
for contenu in ('{"fails": null}', '{"fails": "4"}', '{"last_sent": "x", "in_alarm": 1}', '[1]', '{"fails": true}', "pas du json"):
    etat = nouvel_etat()
    os.makedirs(os.path.dirname(etat))
    with open(etat, "w") as f:
        f.write(contenu)
    reseau = Reseau("hs")
    try:
        minutes(CFG, reseau, etat, 1000, v.CONFIRMATIONS)
        check("état %s : l'alerte part" % contenu, len(reseau.envois) == 1)
    except Exception as exc:
        check("état %s : aucune exception (%r)" % (contenu, exc), False)

# état impossible à écrire (disque plein) : rien n'est envoyé, l'erreur remonte au journal
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 1000, v.CONFIRMATIONS - 1)
ecrire = v.write_state


def disque_plein(*a, **k):
    raise OSError(28, "No space left on device")


v.write_state = disque_plein
try:
    v.run_once(CFG, reseau, now=1000 + 60 * v.CONFIRMATIONS, state_path=etat)
    check("disque plein : l'erreur remonte", False)
except OSError:
    check("disque plein : l'erreur remonte, rien n'est envoyé", reseau.envois == [])
finally:
    v.write_state = ecrire

# galerie qui oscille (Pi qui redémarre en boucle) : le quota ntfy.sh partagé est protégé
for cycle, label in (((5, 2), "5 échecs / 2 succès"), ((6, 3), "6 échecs / 3 succès"), ((30, 2), "30 échecs / 2 succès"),
                     ((12, 12), "12 échecs / 12 succès")):
    etat = nouvel_etat()
    reseau = Reseau("ok")
    n = 0
    for minute in range(24 * 60):
        reseau.galerie = "hs" if (minute % sum(cycle)) < cycle[0] else "ok"
        v.run_once(CFG, reseau, now=1000 + 60 * minute, state_path=etat)
    check("galerie qui oscille (%s) : au plus 100 messages en 24 h (%d)" % (label, len(reseau.envois)), len(reseau.envois) <= 100)
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 1000, 24 * 60)
check("panne continue de 24 h : une alerte et au plus 4 rappels (%d)" % len(reseau.envois), 1 <= len(reseau.envois) <= 5)

# retour de l'alarme moins de 30 min après le retour : déclarée, annoncée seulement si elle dure
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 0, v.CONFIRMATIONS)                         # alarme annoncée
reseau.galerie = "ok"
minutes(CFG, reseau, etat, 600, v.RECOVERY)                             # retour annoncé
n0 = len(reseau.envois)
reseau.galerie = "hs"
minutes(CFG, reseau, etat, 1200, v.CONFIRMATIONS)                       # revient 10 min plus tard : retenue
check("retour de la panne pendant la retenue : pas d'annonce tout de suite", len(reseau.envois) == n0)
minutes(CFG, reseau, etat, 1200 + 60 * v.CONFIRMATIONS, 30)             # dure : annoncée à la fin de la retenue
check("panne qui dure après la retenue : annoncée", len(reseau.envois) == n0 + 1 and reseau.envois[-1]["title"].startswith("[Birdcam]"))
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 0, v.CONFIRMATIONS)
reseau.galerie = "ok"
minutes(CFG, reseau, etat, 600, v.RECOVERY)
n0 = len(reseau.envois)
reseau.galerie = "hs"
minutes(CFG, reseau, etat, 1200, v.CONFIRMATIONS)
reseau.galerie = "ok"
minutes(CFG, reseau, etat, 1200 + 60 * v.CONFIRMATIONS, 5)              # revient et repart pendant la retenue : silence
check("panne brève pendant la retenue : aucun message, ni alerte ni retour", len(reseau.envois) == n0)

# « Rétabli » pris par ntfy mais réponse perdue, puis le Pi retombe : une nouvelle alerte doit partir
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 0, v.CONFIRMATIONS)                          # alerte livrée
reseau.galerie = "ok"
minutes(CFG, reseau, etat, 600, 1)
reseau.ntfy = "delai"
minutes(CFG, reseau, etat, 660, 1)                                      # « Rétabli » pris, réponse perdue
reseau.ntfy, reseau.galerie = "ok", "hs"
minutes(CFG, reseau, etat, 720, 40)
alertes = [e for e in reseau.envois if e["title"].startswith("[Birdcam]")]
check("faux « Rétabli » puis vraie panne : une nouvelle alerte part dans les 40 min", len(alertes) >= 2)

# compteur d'échecs d'envoi d'un ancien épisode : il ne retarde pas l'alerte suivante
etat = nouvel_etat()
os.makedirs(os.path.dirname(etat))
with open(etat, "w") as f:
    json.dump(dict(v.EMPTY, send_failures=8, retry_at=1000 + 1800, seen=1000), f)
reseau = Reseau("ok")
minutes(CFG, reseau, etat, 1060, 3)                                     # le Pi va bien : plus rien en attente
reseau.galerie = "hs"
minutes(CFG, reseau, etat, 1060 + 180, v.CONFIRMATIONS)
check("ancien compteur d'envois ratés oublié : alerte à la 5e minute", len(reseau.envois) == 1)

# états hors bornes : NaN, infini, futur lointain, horloge en avance
for contenu in ('{"retry_at": Infinity}', '{"retry_at": 1e300}', '{"last_sent": NaN, "in_alarm": 1, "announced": 1}',
                '{"retry_at": 99999999999, "seen": 1000}'):
    etat = nouvel_etat()
    os.makedirs(os.path.dirname(etat))
    with open(etat, "w") as f:
        f.write(contenu)
    reseau = Reseau("hs")
    minutes(CFG, reseau, etat, 2000, v.CONFIRMATIONS + 1)
    check("état hors bornes %s : l'alerte part" % contenu, len(reseau.envois) == 1)

# macaron arrêté longtemps avec des échecs comptés : pas d'alerte au redémarrage sur un seul échec
etat = nouvel_etat()
reseau = Reseau("hs")
minutes(CFG, reseau, etat, 1000, v.CONFIRMATIONS - 1)
minutes(CFG, reseau, etat, 1000 + 5 * 86400, 1)
check("macaron arrêté 5 jours : les 4 échecs anciens sont oubliés", reseau.envois == [])
minutes(CFG, reseau, etat, 1000 + 5 * 86400 + 60, v.CONFIRMATIONS - 1)
check("... et l'alerte part bien après 5 échecs récents", len(reseau.envois) == 1)

# l'état est écrit sur disque (fsync) avant remplacement
appels = []
vrai_fsync = os.fsync
os.fsync = lambda fd: (appels.append(fd), vrai_fsync(fd))[1]
try:
    v.write_state(dict(v.EMPTY), nouvel_etat())
finally:
    os.fsync = vrai_fsync
check("état écrit avec fsync", len(appels) == 1)

# --- configuration --------------------------------------------------------------------------------------------
def config(contenu):
    chemin = os.path.join(tmp, "cfg.json")
    with open(chemin, "w") as f:
        json.dump(contenu, f)
    return v.load_config(chemin)


ok = {"gallery": "http://192.168.1.40:5000/", "url": "https://ntfy.sh/", "topic": "birdcam-ab12"}
check("config valide, barres finales retirées", config(ok) == {"gallery": "http://192.168.1.40:5000", "url": "https://ntfy.sh",
                                                               "topic": "birdcam-ab12", "token": None})
for mauvais in (dict(ok, gallery="ftp://x"), dict(ok, url="ntfy.sh"), dict(ok, topic="a b"), dict(ok, topic="a/../b"),
                dict(ok, topic="x" * 65), dict(ok, token="tk bad"), {"gallery": "http://g"}, [1]):
    check("config refusée : %s" % json.dumps(mauvais)[:60], config(mauvais) is None)
check("config absente : None", v.load_config(os.path.join(tmp, "absent.json")) is None)

print("Tous les tests passent." if not FAILURES else f"{len(FAILURES)} échec(s).")
sys.exit(1 if FAILURES else 0)
