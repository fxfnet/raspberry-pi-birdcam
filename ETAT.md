# ETAT : Birdcam

> État partagé du projet. Toute session ou tout agent, quel que soit le modèle, le lit en premier et le met à jour en dernier (rôle de l'archiviste). La carte du projet est `AGENTS.md`. Ce dépôt n'a pas de `DECISIONS.md` : les décisions et leurs motifs sont dans les messages de commit.

Dernière mise à jour : 2026-10-06 par Claude (archiviste, bouton de clip sur `agent/clip-video`)

## Quel est l'objectif ?

Caméra de mangeoire sur Raspberry Pi 3B : détection d'oiseaux, identification d'espèce par modèle entraîné maison, galerie web.

## Qui porte quoi ?

| Sujet | Responsable |
|---|---|
| Décisions, fusions, déploiements, essais physiques, paris | FX |
| Production (code, docs) | Session principale, sur une branche `agent/<sujet>` |
| Relecture avant fusion et avant déploiement | Agent adversaire, contexte vierge |
| Mise à jour de ce fichier et des décisions | Agent archiviste |

Un agent n'est jamais responsable d'un arbitrage : il propose, FX tranche.

## Où en est-on ?

Le Pi est à jour avec `main` (HEAD `4b89298`). Déployé et vérifié depuis, tous fusionnés par accord explicite de FX :

- **2026-09-27** (604597b à c6fcd3d) : restauration depuis macaron (`RESTORE.md`), contrôle de `corrections.json` avant sauvegarde dans `scripts/backup_usb.sh`, copies quotidiennes. Déployé sur le Pi le matin même. `scripts/test_backup_usb.sh` passe sur le Pi (7/7). Sauvegarde vérifiée sur macaron (`corrections_2026-09-27.json` présent).
- **2026-09-27** (51784a0 + 4e3bc4f) : watchdog interne basé sur `SensorTimestamp` (l'ancien critère « aucun pixel changé 20 min » avait causé 25 relances à tort en 5 jours, la nuit et par temps calme). Angle mort accepté : images identiques avec horodatage qui avance.
- **2026-09-29** (714ba45 + 0a61eef) : visionneuse `/view` (précédente/suivante, retour galerie, actions admin) ; (365b852) latest star coupée sur mobile, corrigé ; (5c2cd47 + 18fa5b6) pose courte (courbe AGC « short » redéfinie via tuning Picamera2 : 1,1 ms gain 4 à 10 000 lux au lieu de 4,5 ms gain 1 ; lignes « Exposition: » toutes les 10 min dans `journalctl`). Un tuning refusé par libcamera rend la caméra introuvable jusqu'à la fin du processus, d'où la validation avant usage.
- **2026-10-01** (88c71cd + 4b89298) : rafales groupées dans la galerie avec case « Toute la rafale » en admin, légendes simplifiées (espèce, barre de certitude, heure), `og:url` et `og:image` en https derrière Tailscale Funnel (`ProxyFix` `x_proto`, `x_for=0`), barre d'actions groupées masquée sans sélection. Vérifié sur le site public https://oaso.dala-alhena.ts.net.

Chaque changement a été relu par l'agent adversaire avant fusion.

**Points ouverts** relevés en relecture de la sauvegarde (2026-09-27), toujours ouverts :
- croissance des copies quotidiennes de `corrections.json` (pas de purge) ;
- horloge du Pi au démarrage (time-sync) non traitée ;
- aucune alerte hors `systemctl status` en cas d'échec de sauvegarde ;
- rsync macOS (`openrsync`) non testé en réel, seulement contre une cible locale.

**Questions posées à FX, sans réponse à ce jour** :
- garder « Correct » sur l'espèce présélectionnée comme confirmation explicite ;
- fichiers `pending_*` visibles dans le filtre All ;
- l'aperçu `og:image` peut être une photo `star_motion`.

Fichier non suivi dans le repo : `training/garden_birds_captures.onnx`, doublon exact de `model/garden_birds.onnx`. Ne pas le supprimer sans accord de FX.

**Bouton de clip vidéo, sur la branche `agent/clip-video`** (commits e2b1daa, 7cac83c, 0d79263 ; non fusionné dans `main`, non poussé, **non déployé sur le Pi**, bouton jamais essayé sur le Pi). Le 2026-10-06, le script d'essai `scripts/record_next_motion.py` a été intégré à la galerie admin :
- bouton admin « Faire une vidéo du prochain mouvement détecté » : lance `birdcam-clip.service`, attente d'1 h au plus, clip de 10 s, retour à la capture photo ;
- bouton « Annuler le clip » pendant l'attente ; bouton absent si la caméra est arrêtée volontairement (le script la relancerait) ; Start/Test Camera masqués pendant l'attente ;
- page `/clips` (lecture publique, suppression admin), clips dans `clips/` à côté de `captures/` (clé USB) ;
- choix de FX : bouton réservé à l'admin, attente d'1 h, section séparée « Clips » ;
- relecture adverse : 3 défauts bloquants (SIGTERM pendant l'arrêt ou le nettoyage laissait la caméra arrêtée ; aucun garde-fou systemd contre SIGKILL ou gel) et plusieurs moyens, corrigés dans 0d79263 (`ExecStopPost`, `RuntimeMaxSec=3720`, garde côté serveur, erreurs affichées) ;
- tests : `scripts/test_gallery_clips.py`, `scripts/test_record_next_motion.py` (échoue sur la version précédente du script), `scripts/test_gallery_bursts.py` inchangé ; les trois passent.

Pour déployer (sur accord de FX, après fusion) : relancer `scripts/install_services.sh` (nouvelle unité), puis redémarrer `birdcam-gallery` et `birdcam-gallery-admin`. Sur le Pi, la copie de l'essai du 2026-10-05 est dans `/tmp/record_next_motion.py` (vérifié le 2026-10-06), hors du repo : elle ne gêne pas `git pull` et disparaîtra au redémarrage.

**Points ouverts sur le clip**, non tranchés, à soumettre à FX :
- clips visibles publiquement via Funnel : **tranché par FX le 2026-10-06, ils restent publics** (pas de filtre ni de validation préalable) ;
- clips sauvegardés vers macaron depuis 85c9a8e (sans `--delete`, une suppression admin reste donc sur macaron), non déployé ; toujours pas de purge des clips sur la clé USB ;
- aucune protection CSRF sur les POST admin (défaut antérieur au clip) ;
- durée réelle : 8,9 s mesuré pour environ 12 s attendues (pré-roll 2 s + 10 s), écart non expliqué ;
- charge thermique de l'encodage pendant l'attente non mesurée (Pi à 81,7 °C le 2026-09-27) ;
- si un redémarrage de `birdcam` (minuterie de 03:00, déploiement) tombe pendant l'attente, `birdcam` échoue en boucle sur la caméra occupée jusqu'à la fin du clip ; la minuterie n'a pas été adaptée ;
- le clip d'essai du 2026-10-06 n'a pas été jugé par FX : on ignore s'il contient un oiseau.

## Qu'a appris le terrain ?

- Température du Pi : 81,7 °C le 2026-09-27, `throttled=0x60002` (bridage en cours), pas de dissipateur posé.
- Flou des photos : deux causes distinctes. Flou de bougé, corrigé en partie par la pose courte (5c2cd47, 18fa5b6). Et mise au point : la caméra est derrière une vitre, la barre de la mangeoire est à environ 10 cm au-delà du verre, l'objectif OV5647 est réglé sur le lointain, donc l'oiseau est hors de la zone nette.
- Le modèle v2 a reconnu ses premières mésanges charbonnières les 28 et 29/09 (spconf 0,88 à 0,90).
- Lecture du dossier de captures : environ 150 à 200 ms sur le Pi pour 650 à 780 fichiers (mesures 0a61eef et 4b89298).
- Essai de clip du 2026-10-06 : lancé sur le Pi à 08:00:09, mouvement à 09:27:17 (score 991), clip `/mnt/birdcam-usb/clips/clip_20261006_092717.mp4`, 4,4 Mo, H.264 1280x960, 8,9 s. Capture photo relancée à 09:27:30, service `birdcam` actif. Pendant l'attente (environ 87 min), aucune photo n'a été prise : la caméra ne sert qu'à un programme à la fois. Clip copié sur le Mac dans `~/Movies/birdcam/`. Contenu non jugé.
- Hors repo : `~/.ssh/known_hosts` et le bloc `Host oaso.local` de `~/.ssh/config` corrigés côté Mac.

## Quels paris sont engagés ?

Un pari est un investissement de temps, d'effort ou d'argent sur une évaluation que l'on ne peut pas entièrement rationaliser. Seul FX en formule. Un pari sans critère d'arrêt n'est pas un pari.

| Date | Pari | Investissement engagé | Ce qui me ferait arrêter | Date de revue | Issue |
|---|---|---|---|---|---|

## Quelle est la prochaine action ?

Options à soumettre à FX, non tranchées :
- régler la mise au point de l'objectif sur environ 15 cm (assistant de netteté proposé, non fait) et coller l'objectif à la vitre avec un cache noir ;
- poser un dissipateur ;
- comparer quelques jours de photos avant et après la pose courte (bruit par temps gris, confiance d'espèce) via `journalctl -u birdcam | grep Exposition` ;
- vérifier au matin l'absence de lignes WATCHDOG ;
- exécuter `setup_system.sh` de bout en bout (jamais testé complet).
- clip vidéo : arbitrer les points ouverts ci-dessus (visibilité publique, sauvegarde et purge, redémarrage de 03:00, CSRF), puis décider de la fusion et du déploiement ; mesurer la température pendant une attente et expliquer l'écart de durée avant déploiement.
