# ETAT : Birdcam

> État partagé du projet. Toute session ou tout agent, quel que soit le modèle, le lit en premier et le met à jour en dernier (rôle de l'archiviste). La carte du projet est `AGENTS.md`. Ce dépôt n'a pas de `DECISIONS.md` : les décisions et leurs motifs sont dans les messages de commit.

Dernière mise à jour : 2026-09-29 par Claude (session Cowork, création : état courant déplacé depuis `AGENTS.md`, contenu inchangé hors tirets cadratins remplacés)

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

### 🔴 Déploiement en attente, 2026-09-27

Les commits du 2026-09-27 (mode opératoire de restauration depuis macaron dans `RESTORE.md`, vérification de `corrections.json` avec compteur dans `scripts/backup_usb.sh`, copies quotidiennes, code de sortie 3, `scripts/test_backup_usb.sh`) **ne sont pas déployés sur le Pi**. À la reconnexion : `git pull` sur le Pi, puis vérifier `systemctl status birdcam-backup`.

**Points ouverts** relevés en relecture :
- croissance des copies quotidiennes de `corrections.json` (pas de purge) ;
- horloge du Pi au démarrage (time-sync) non traitée ;
- aucune alerte hors `systemctl status` en cas d'échec de sauvegarde ;
- rsync macOS (`openrsync`) non testé en réel, seulement contre une cible locale.

## Qu'a appris le terrain ?

Rien de consigné à ce jour hors des messages de commit (symptômes observés sur le Pi : gel de capture, température, flou de bougé).

## Quels paris sont engagés ?

Un pari est un investissement de temps, d'effort ou d'argent sur une évaluation que l'on ne peut pas entièrement rationaliser. Seul FX en formule. Un pari sans critère d'arrêt n'est pas un pari.

| Date | Pari | Investissement engagé | Ce qui me ferait arrêter | Date de revue | Issue |
|---|---|---|---|---|---|

## Quelle est la prochaine action ?

`git pull` sur le Pi puis vérifier `birdcam-backup` ; exécuter `setup_system.sh` de bout en bout ; poser un dissipateur (repris de `_brain/repos.md` au 2026-09-29).
