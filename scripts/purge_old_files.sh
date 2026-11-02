#!/usr/bin/env bash
set -euo pipefail

CAPTURE_DIR="${HOME}/birdcam/captures"
THUMB_DIR="${HOME}/birdcam/gallery/thumbs"

DAYS_TO_KEEP=14
# Rafales sans oiseau marquées _sun (soleil, nuage) : gardées peu de temps.
DAYS_TO_KEEP_SUN=3

echo "Purging motion pictures older than ${DAYS_TO_KEEP} days..."
echo "Bird pictures are kept."

# CAPTURE_DIR is a symlink to the USB drive on the Pi: find needs -H to follow it
# (without it the purge silently deleted nothing).
# Sun-marked motion pictures go first.
find -H "${CAPTURE_DIR}" \
  -type f \
  -name "motion_*_sun.jpg" \
  -mtime +"${DAYS_TO_KEEP_SUN}" \
  -print \
  -delete

# Delete only old motion pictures.
find -H "${CAPTURE_DIR}" \
  -type f \
  \( -name "motion_*.jpg" -o -name "motion_*.jpeg" -o -name "motion_*.png" \) \
  -mtime +"${DAYS_TO_KEEP}" \
  -print \
  -delete

# Delete thumbnails whose original image no longer exists.
if [ -d "${THUMB_DIR}" ]; then
  echo "Removing orphan thumbnails..."

  find "${THUMB_DIR}" -type f | while read -r thumb; do
    filename="$(basename "${thumb}")"

    if [ ! -f "${CAPTURE_DIR}/${filename}" ]; then
      echo "${thumb}"
      rm -f "${thumb}"
    fi
  done
fi

echo "Purge done."
