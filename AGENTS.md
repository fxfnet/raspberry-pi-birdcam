# Birdcam : point d'entrée pour un agent

Lire ce fichier en premier. Valable pour tout agent (Claude, Codex, Copilot, modèle local).

## De quoi s'agit-il ?

Caméra de mangeoire sur Raspberry Pi 3B (caméra OV5647, Debian Trixie, Python 3.13). Détection de mouvement, détection d'oiseau (MobileNet SSD, OpenCV DNN), identification d'espèce par un modèle entraîné maison (`model/garden_birds.onnx`), galerie web Flask publique et admin.

## Où est quoi ?

| Sujet | Fichier |
|---|---|
| Capture, détection, réglages (seuils, rafales) | `birdcam_motion.py` |
| Galerie web et admin | `gallery/app.py` |
| Services et minuteries (capture, galerie, admin, purge, redémarrage nocturne) | `systemd/` |
| Installation sur le Pi | `scripts/install_services.sh`, `scripts/install_models.sh` |
| Reconstruction après panne de carte SD | `RESTORE.md`, `scripts/setup_system.sh` |
| Entraînement du modèle d'espèces | `training/` (le dataset n'est pas versionné) |
| Documentation utilisateur | `README.md` |

## Comment déployer ?

- Pi : `oaso.local`, utilisateur **`fxf`** (et non `fx` : décalage corrigé dans le commit 1923f45).
- Code dans `/home/fxf/birdcam` sur le Pi. Déploiement : `git pull` sur le Pi, puis `sudo systemctl restart birdcam birdcam-gallery birdcam-gallery-admin`.
- Ne jamais éditer directement sur le Pi : modifier le repo, puis déployer.
- Logs : `journalctl -u birdcam -f`.

## Quelles règles ?

1. Le seul modèle versionné est `garden_birds.onnx` (+ labels) : il n'est pas retéléchargeable. Ne jamais le supprimer ni l'écraser sans sauvegarde.
2. Les fonctions qui dépendent d'un paquet optionnel (TFLite, espèces) doivent se dégrader proprement si le paquet manque.
3. Tester localement ce qui peut l'être sans caméra (galerie, parsing des noms de fichiers) avant de déployer.
4. Chaque correctif de fiabilité (gel de capture, watchdog) est décrit dans le message de commit avec le symptôme observé.

## Comment travailler en parallèle ?

- Un agent = une branche `agent/<sujet>` dans son propre worktree : `git worktree add ../birdcam-wt/<sujet> -b agent/<sujet>`.
- Un agent adverse à contexte vierge relit le diff avant fusion.
- FX fusionne. Aucun agent ne pousse sur `main` sans accord explicite.

Style : français pour les échanges avec FX, vouvoiement, pas de tiret cadratin. Code et commits en anglais, comme l'historique.
