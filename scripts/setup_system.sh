#!/usr/bin/env bash
# Reconstruit la configuration système du Pi birdcam sur une carte SD neuve.
# Voir RESTORE.md pour la procédure complète (flash, clone, clés SSH).
#
# Idempotent : chaque étape vérifie l'état avant d'agir, le script peut être
# relancé sans risque. Lancer en tant qu'utilisateur normal, il appelle sudo.
#
# Usage : bash ~/birdcam/scripts/setup_system.sh
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Lancer ce script en tant qu'utilisateur normal (sans sudo) : il appelle sudo lui-même." >&2
  exit 1
fi

PROJECT_DIR="${HOME}/birdcam"
USER_NAME="$(whoami)"
USB_LABEL="birdcam-usb"
USB_MOUNT="/mnt/birdcam-usb"
BACKUP_HOST_IP="192.168.1.177"
BACKUP_KEY="${HOME}/.ssh/id_ed25519_backup"

if [ ! -d "${PROJECT_DIR}/.git" ]; then
  echo "Dépôt absent : git clone https://github.com/fxfnet/raspberry-pi-birdcam.git ${PROJECT_DIR}" >&2
  exit 1
fi

step() { echo; echo "=== $* ==="; }

step "1. Paquets"
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-opencv python3-numpy python3-flask git wget

step "2. Clé USB des captures (${USB_LABEL} -> ${USB_MOUNT})"
USB_DEV="$(sudo blkid -L "${USB_LABEL}" || true)"
if [ -z "${USB_DEV}" ]; then
  # Sans la clé, la capture écrirait sur la SD et les liens ne seraient plus créés.
  echo "Aucune partition étiquetée ${USB_LABEL}. Brancher la clé et relancer," >&2
  echo "  ou en préparer une neuve : sudo mkfs.ext4 -L ${USB_LABEL} /dev/sdX1" >&2
  exit 1
else
  sudo mkdir -p "${USB_MOUNT}"
  USB_UUID="$(sudo blkid -s UUID -o value "${USB_DEV}")"
  if ! grep -q "^UUID=${USB_UUID} ${USB_MOUNT} " /etc/fstab; then
    # Nouvelle clé ou première installation : une seule ligne pour ce point de montage.
    # nofail : le Pi démarre même si la clé est absente.
    sudo sed -i "\| ${USB_MOUNT} |d" /etc/fstab
    echo "UUID=${USB_UUID} ${USB_MOUNT} ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab >/dev/null
    sudo systemctl daemon-reload
  fi
  mountpoint -q "${USB_MOUNT}" || sudo mount "${USB_MOUNT}"
  sudo mkdir -p "${USB_MOUNT}/captures"
  sudo chown "${USER_NAME}:${USER_NAME}" "${USB_MOUNT}" "${USB_MOUNT}/captures"
  [ -f "${USB_MOUNT}/corrections.json" ] || echo "[]" > "${USB_MOUNT}/corrections.json"

  # captures/ et corrections.json vivent sur la clé ; le dépôt n'en garde qu'un lien.
  for name in captures corrections.json; do
    link="${PROJECT_DIR}/${name}"
    if [ -L "${link}" ]; then
      continue
    fi
    # Ne jamais effacer de données : seul un captures/ vide (ou avec .gitkeep)
    # est remplacé par le lien ; un corrections.json local est laissé en place.
    if [ -d "${link}" ] && [ -z "$(find "${link}" -mindepth 1 ! -name .gitkeep -print -quit)" ]; then
      rm -rf "${link}"
    fi
    if [ -e "${link}" ]; then
      echo "ATTENTION : ${link} existe sur la SD et n'est pas remplacé."
      echo "  Fusionner son contenu dans ${USB_MOUNT}/${name}, le supprimer, puis relancer."
    else
      ln -s "${USB_MOUNT}/${name}" "${link}"
    fi
  done
fi

step "3. Sudo sans mot de passe limité à systemctl et journalctl"
SUDOERS_TMP="$(mktemp)"
echo "${USER_NAME} ALL=(root) NOPASSWD: /usr/bin/systemctl, /usr/bin/journalctl" > "${SUDOERS_TMP}"
# visudo -c avant installation : un sudoers invalide peut bloquer tout sudo.
sudo visudo -cf "${SUDOERS_TMP}"
sudo install -m 0440 -o root -g root "${SUDOERS_TMP}" /etc/sudoers.d/birdcam-fxf
rm -f "${SUDOERS_TMP}"

step "4. Journaux persistants, plafonnés à 100 Mo"
# Raspberry Pi OS force Storage=volatile via un fichier du même nom dans
# /usr/lib/systemd/journald.conf.d ; celui de /etc le masque.
# Sans plafond, le journal persistant grossit sans fin et use la carte SD
# (725 Mo constatés sur le Pi Spirucontrol).
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=100M\n' | sudo tee /etc/systemd/journald.conf.d/40-rpi-volatile-storage.conf >/dev/null
sudo systemctl restart systemd-journald
sudo journalctl --flush

step "5. Wi-Fi sans économie d'énergie"
WIFI_CONN="$(nmcli -g GENERAL.CONNECTION device show wlan0 2>/dev/null || true)"
if [ -n "${WIFI_CONN}" ]; then
  # powersave=2 : désactivé. Actif, il rend SSH et la galerie injoignables par moments.
  sudo nmcli connection modify "${WIFI_CONN}" 802-11-wireless.powersave 2
  echo "Réglé sur ${WIFI_CONN} (effectif à la prochaine reconnexion ou au redémarrage)."
else
  echo "ATTENTION : aucune connexion Wi-Fi active sur wlan0, étape ignorée."
fi

step "6. Démarrage sans bureau graphique"
sudo systemctl set-default multi-user.target

step "7. Modèles"
# MobileNetSSD se retélécharge ; garden_birds.onnx est versionné dans le dépôt.
# Seulement s'il manque : install_models.sh tronque les fichiers avant de
# télécharger, une relance sans réseau casserait un Pi qui fonctionne.
if [ -s "${PROJECT_DIR}/model/MobileNetSSD_deploy.caffemodel" ] && [ -s "${PROJECT_DIR}/model/MobileNetSSD_deploy.prototxt" ]; then
  echo "Modèles déjà présents."
else
  bash "${PROJECT_DIR}/scripts/install_models.sh"
fi

step "8. Clé de sauvegarde vers macaron"
if [ ! -f "${BACKUP_KEY}" ]; then
  # Sans phrase de passe : elle sert à un envoi automatique, et ne donne accès
  # qu'au compte macaron.
  ssh-keygen -t ed25519 -N '' -C "birdcam-backup" -f "${BACKUP_KEY}"
fi
if ! ssh-keygen -F "${BACKUP_HOST_IP}" >/dev/null; then
  # Sans l'empreinte de macaron, le premier rsync non interactif échouerait.
  ssh-keyscan -t ed25519 "${BACKUP_HOST_IP}" >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
fi
if ssh -i "${BACKUP_KEY}" -o BatchMode=yes -o ConnectTimeout=10 "macaron@${BACKUP_HOST_IP}" true 2>/dev/null; then
  echo "macaron accepte la clé de sauvegarde."
else
  echo "ATTENTION : macaron refuse encore la clé. Ajouter cette ligne à"
  echo "  ~/.ssh/authorized_keys sur macaron (et retirer l'ancienne clé birdcam-backup) :"
  cat "${BACKUP_KEY}.pub"
fi

step "9. Services birdcam"
bash "${PROJECT_DIR}/scripts/install_services.sh"
sudo systemctl start birdcam birdcam-gallery birdcam-gallery-admin

step "10. Tailscale (accès hors du réseau local)"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "Ouvrir le lien affiché pour autoriser le Pi dans le tailnet."
  # Nom par défaut = hostname du Pi (oaso), comme le nœud actuel du tailnet.
  sudo tailscale up
fi

echo
echo "Configuration système terminée. Redémarrer pour tout valider : sudo reboot"
