#!/usr/bin/env bash
# Teste que la purge retire les rafales _sun après 3 jours, les autres motion_
# après 14 jours, et ne touche jamais aux oiseaux ni aux photos étoilées.
# Usage : bash scripts/test_purge_old_files.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HOME="$(mktemp -d)"
REAL="$(mktemp -d)"
CAP="${HOME}/birdcam/captures"
mkdir -p "${HOME}/birdcam"
ln -s "${REAL}" "${CAP}"  # comme sur le Pi : captures est un lien vers la clé USB
old() { # fichier, âge en jours (touch -d n'existe pas sous macOS)
  python3 -c "import os,sys,time; t=time.time()-float(sys.argv[2])*86400; os.utime(sys.argv[1],(t,t))" "${CAP}/$1" "$2"
}
mk() { : > "${CAP}/$1"; old "$1" "$2"; }
mk motion_a_sun.jpg 4
mk motion_b_sun.jpg 2
mk motion_c.jpg 4
mk motion_d.jpg 15
mk bird_e.jpg 40
mk star_motion_f_sun.jpg 40
bash "${ROOT}/scripts/purge_old_files.sh" >/dev/null
fail=0
expect() { # présence attendue (1/0) du fichier
  if [ -f "${CAP}/$2" ]; then got=1; else got=0; fi
  if [ "$got" = "$1" ]; then echo "ok    : $2 présent=$1"; else echo "ECHEC : $2 présent=$got (attendu $1)"; fail=1; fi
}
expect 0 motion_a_sun.jpg
expect 1 motion_b_sun.jpg
expect 1 motion_c.jpg
expect 0 motion_d.jpg
expect 1 bird_e.jpg
expect 1 star_motion_f_sun.jpg
exit "${fail}"
