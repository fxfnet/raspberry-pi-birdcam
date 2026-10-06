#!/usr/bin/env bash
# Teste backup_usb.sh contre des répertoires temporaires, sans clé USB ni macaron.
# Usage : bash scripts/test_backup_usb.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# Seul le test de montage est neutralisé ; rsync ignore -e pour une cible locale.
sed 's|^if ! mountpoint -q.*|if false; then|' "${HERE}/backup_usb.sh" > "${WORK}/backup.sh"

export USB_MOUNT="${WORK}/usb" BACKUP_TARGET="${WORK}/dest/" CORRECTIONS_STATE="${WORK}/state"
mkdir -p "${USB_MOUNT}/captures" "${USB_MOUNT}/clips" "${WORK}/dest"
touch "${USB_MOUNT}/clips/clip_20261006_092717.mp4" "${USB_MOUNT}/clips/autre.mp4"
FAIL=0

run() {  # run <contenu de corrections.json ou ABSENT> <code attendu> <contenu attendu sur la cible>
  if [ "$1" = ABSENT ]; then rm -f "${USB_MOUNT}/corrections.json"; else printf '%s' "$1" > "${USB_MOUNT}/corrections.json"; fi
  touch "${USB_MOUNT}/captures/bird_$RANDOM.jpg"
  bash "${WORK}/backup.sh" 2>/dev/null
  local rc=$? got
  got="$(cat "${WORK}/dest/corrections.json" 2>/dev/null)"
  if [ "${rc}" -ne "$2" ] || [ "${got}" != "$3" ]; then
    echo "ECHEC : '$1' -> code ${rc} (attendu $2), cible '${got}' (attendu '$3')"; FAIL=1
  else
    echo "ok    : '$1' -> code ${rc}"
  fi
}

run '[1, 2]'   0 '[1, 2]'
run '[1, 2, 3]' 0 '[1, 2, 3]'
run '{broken'  3 '[1, 2, 3]'
run '{}'       3 '[1, 2, 3]'
run '[]'       3 '[1, 2, 3]'    # clé neuve : régression bloquée
run ABSENT     3 '[1, 2, 3]'
rm -f "${CORRECTIONS_STATE}"     # restauration voulue d'une version plus courte
run '[1]'      0 '[1]'

[ "$(ls "${WORK}/dest/captures" | wc -l)" -eq 7 ] || { echo "ECHEC : photos non toutes sauvegardées"; FAIL=1; }
[ -e "${WORK}/dest/clips/clip_20261006_092717.mp4" ] || { echo "ECHEC : clip non sauvegardé"; FAIL=1; }
[ ! -e "${WORK}/dest/clips/autre.mp4" ] || { echo "ECHEC : fichier étranger copié depuis clips/"; FAIL=1; }
ls "${WORK}/dest" | grep -q "corrections_$(date +%F).json" || { echo "ECHEC : copie du jour absente"; FAIL=1; }
[ "${FAIL}" -eq 0 ] && echo "Tous les tests passent."
exit "${FAIL}"
