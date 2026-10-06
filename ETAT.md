# ETAT : Birdcam

> État partagé du projet. Toute session ou tout agent, quel que soit le modèle, le lit en premier et le met à jour en dernier (rôle de l'archiviste). La carte du projet est `AGENTS.md`. Ce dépôt n'a pas de `DECISIONS.md` : les décisions et leurs motifs sont dans les messages de commit.

Dernière mise à jour : 2026-10-06 par Claude (session Claude Code, archivage de fin de session)

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

**Essai en cours sur la branche `agent/clip-video`** (commit e2b1daa, non fusionné dans `main`, non poussé) : clip vidéo déclenché par mouvement, `scripts/record_next_motion.py`. Écrit le 2026-10-05 et copié sur le Pi hors du flux git, ce qui contrevient à la règle « modifier le repo puis déployer » : la copie du Pi n'est pas installée proprement. Le script arrête `birdcam.service`, attend un mouvement, enregistre 10 s précédées de 2 s de pré-roll, puis relance toujours le service. Aucune décision prise sur son intégration.

**Points ouverts sur l'essai de clip** :
- durée de 8,9 s au lieu des 10 s attendues, écart non expliqué ;
- script non fusionné dans `main`, non installé proprement sur le Pi ;
- intégration au service non décidée (clip en continu ou non) ;
- charge sur le Pi 3B, déjà à 81,7 °C le 2026-09-27 ;
- le clip n'a pas encore été jugé par FX : on ignore s'il contient un oiseau.

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
- clip vidéo, options à trancher par FX : (a) abandonner l'essai ; (b) garder le script one-shot, le fusionner et l'installer proprement via le repo ; (c) intégrer au service, sans photo manquée pendant l'attente (à concevoir, car la caméra ne sert qu'à un programme à la fois) ; juger d'abord le clip copié dans `~/Movies/birdcam/` ;
- enquêter sur l'écart 8,9 s contre 10 s avant toute intégration.
