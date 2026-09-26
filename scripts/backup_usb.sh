#!/usr/bin/env bash
# Copie les photos d'oiseaux et corrections.json de la clé USB vers macaron.
#
# Sans --delete : une photo supprimée depuis l'admin reste dans la sauvegarde.
# Les photos de mouvement (motion_*), purgées après 14 jours, ne sont pas copiées.
# Lancé toutes les heures par birdcam-backup.timer ; rsync ne transfère que les
# nouveautés, et une heure où macaron est éteint est rattrapée à la suivante.
set -euo pipefail

USB_MOUNT="/mnt/birdcam-usb"
BACKUP_KEY="${HOME}/.ssh/id_ed25519_backup"
BACKUP_TARGET="macaron@192.168.1.177:birdcam_backups/"

# Clé absente (montage nofail) : le répertoire vide de la carte SD ne doit pas
# passer pour une sauvegarde réussie.
if ! mountpoint -q "${USB_MOUNT}"; then
  echo "Clé USB non montée sur ${USB_MOUNT}" >&2
  exit 1
fi

rsync -a \
  --include='captures/' \
  --include='captures/bird_*' \
  --include='captures/star_*' \
  --include='corrections.json' \
  --exclude='*' \
  -e "ssh -i ${BACKUP_KEY} -o BatchMode=yes -o ConnectTimeout=20" \
  "${USB_MOUNT}/" "${BACKUP_TARGET}"
