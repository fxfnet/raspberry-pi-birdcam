#!/usr/bin/env bash
set -euo pipefail

CAPTURE_DIR="/home/fx/birdcam/captures"
THUMB_DIR="/home/fx/birdcam/gallery/thumbs"

DAYS_TO_KEEP=14

echo "Purging motion pictures older than ${DAYS_TO_KEEP} days..."
echo "Bird pictures are kept."

# Delete only old motion pictures.
find "${CAPTURE_DIR}" \
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
