#!/usr/bin/env bash
# Copie les photos d'oiseaux, les clips vidéo et corrections.json de la clé USB vers macaron.
#
# Sans --delete : une photo ou un clip supprimé depuis l'admin reste dans la sauvegarde.
# Les photos de mouvement (motion_*), purgées après 14 jours, ne sont pas copiées.
# Lancé toutes les heures par birdcam-backup.timer ; rsync ne transfère que les
# nouveautés, et une heure où macaron est éteint est rattrapée à la suivante.
#
# corrections.json n'est poussé que s'il est une liste JSON lisible, et s'il n'a
# pas moins d'entrées qu'au dernier envoi réussi : le fichier ne fait que
# s'allonger (append_correction), une baisse signale une clé neuve (`[]`) ou un
# fichier remplacé, qui écraserait sinon la bonne copie sur macaron. Après une
# restauration voulue d'une version plus courte, supprimer CORRECTIONS_STATE.
# Il est aussi copié chaque jour sous corrections_AAAA-MM-JJ.json, pour pouvoir
# revenir à la veille.
#
# Codes de sortie : 0 tout envoyé, 3 photos envoyées mais corrections.json
# retenu, autre valeur : échec de la copie (macaron éteint, réseau).
set -euo pipefail

# Surchargeables pour tester le script contre un répertoire local.
USB_MOUNT="${USB_MOUNT:-/mnt/birdcam-usb}"
BACKUP_KEY="${HOME}/.ssh/id_ed25519_backup"
BACKUP_TARGET="${BACKUP_TARGET:-macaron@192.168.1.177:birdcam_backups/}"
CORRECTIONS_STATE="${CORRECTIONS_STATE:-${HOME}/.local/state/birdcam/corrections_count}"

# Clé absente (montage nofail) : le répertoire vide de la carte SD ne doit pas
# passer pour une sauvegarde réussie.
if ! mountpoint -q "${USB_MOUNT}"; then
  echo "Clé USB non montée sur ${USB_MOUNT}" >&2
  exit 1
fi

SSH="ssh -i ${BACKUP_KEY} -o BatchMode=yes -o ConnectTimeout=20"
CORRECTIONS="${USB_MOUNT}/corrections.json"

# Nombre d'entrées si le fichier est une liste JSON, rien sinon.
COUNT="$(python3 -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(d) if isinstance(d, list) else "")' "${CORRECTIONS}" 2>/dev/null || true)"
LAST_COUNT="$(cat "${CORRECTIONS_STATE}" 2>/dev/null || echo 0)"

CORRECTIONS_OK=0
if [ ! -e "${CORRECTIONS}" ]; then
  echo "corrections.json absent de la clé : rien à sauvegarder pour ce fichier" >&2
elif [ -z "${COUNT}" ]; then
  echo "corrections.json illisible ou pas une liste : non sauvegardé, la copie de macaron est conservée" >&2
elif [ "${COUNT}" -lt "${LAST_COUNT}" ]; then
  echo "corrections.json a ${COUNT} entrées contre ${LAST_COUNT} au dernier envoi : non sauvegardé." >&2
  echo "  Si c'est une restauration voulue : rm ${CORRECTIONS_STATE}" >&2
else
  CORRECTIONS_OK=1
fi

if [ "${CORRECTIONS_OK}" -eq 1 ]; then
  FILTER_CORRECTIONS=(--include='corrections.json')
else
  FILTER_CORRECTIONS=(--exclude='corrections.json')
fi

rsync -a \
  --include='captures/' \
  --include='captures/bird_*' \
  --include='captures/star_*' \
  --include='clips/' \
  --include='clips/clip_*.mp4' \
  "${FILTER_CORRECTIONS[@]}" \
  --exclude='*' \
  -e "${SSH}" \
  "${USB_MOUNT}/" "${BACKUP_TARGET}"

if [ "${CORRECTIONS_OK}" -eq 1 ]; then
  rsync -a -e "${SSH}" "${CORRECTIONS}" "${BACKUP_TARGET}corrections_$(date +%F).json"
  mkdir -p "$(dirname "${CORRECTIONS_STATE}")"
  echo "${COUNT}" > "${CORRECTIONS_STATE}"
else
  # Les photos sont sauvegardées ; le code 3 distingue ce cas d'un Mac éteint.
  exit 3
fi
