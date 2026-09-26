#!/usr/bin/env bash
# Copie les photos d'oiseaux et corrections.json de la clé USB vers macaron.
#
# Sans --delete : une photo supprimée depuis l'admin reste dans la sauvegarde.
# Les photos de mouvement (motion_*), purgées après 14 jours, ne sont pas copiées.
# Lancé toutes les heures par birdcam-backup.timer ; rsync ne transfère que les
# nouveautés, et une heure où macaron est éteint est rattrapée à la suivante.
#
# corrections.json n'est poussé que s'il se lit comme du JSON : un fichier
# abîmé remplacerait sinon la seule bonne copie sur macaron. Il est aussi copié
# chaque jour sous corrections_AAAA-MM-JJ.json, ce qui garde une version par
# jour en cas de fichier valide mais vidé (clé neuve, par exemple).
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

SSH="ssh -i ${BACKUP_KEY} -o BatchMode=yes -o ConnectTimeout=20"
CORRECTIONS="${USB_MOUNT}/corrections.json"

if python3 -m json.tool "${CORRECTIONS}" >/dev/null 2>&1; then
  CORRECTIONS_OK=1
  FILTER_CORRECTIONS=(--include='corrections.json')
else
  CORRECTIONS_OK=0
  FILTER_CORRECTIONS=(--exclude='corrections.json')
  echo "corrections.json illisible : non sauvegardé, la copie de macaron est conservée" >&2
fi

rsync -a \
  --include='captures/' \
  --include='captures/bird_*' \
  --include='captures/star_*' \
  "${FILTER_CORRECTIONS[@]}" \
  --exclude='*' \
  -e "${SSH}" \
  "${USB_MOUNT}/" "${BACKUP_TARGET}"

if [ "${CORRECTIONS_OK}" -eq 1 ]; then
  rsync -a -e "${SSH}" "${CORRECTIONS}" "${BACKUP_TARGET}corrections_$(date +%F).json"
else
  # Les photos sont sauvegardées ; l'échec reste visible dans systemctl status.
  exit 1
fi
