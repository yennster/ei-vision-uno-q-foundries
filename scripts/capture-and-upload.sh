#!/usr/bin/env bash
# capture-and-upload.sh — capture frames from the UNO Q's USB camera
# and POST them to the Edge Impulse ingestion API.
#
# Run on the UNO Q itself (or any Linux box with the same camera).
# Once samples land in the project, the next hourly run of
# .github/workflows/ei-data-watch-and-retrain.yml will detect the new
# count, retrain, rebuild the .eim, and tag a release that flows back
# to the device through Foundries.
#
# Required env:
#   EI_API_KEY         Edge Impulse API key (starts with ei_) with
#                      ingestion scope on the target project
#
# Optional env:
#   LABEL              x-label sent with each upload          (default: unlabeled)
#   CATEGORY           training | testing                     (default: training)
#   COUNT              how many frames to capture             (default: 10)
#   INTERVAL           seconds between frames                 (default: 2)
#   DEVICE             V4L2 device path                       (default: /dev/video0)
#   WIDTH x HEIGHT     capture resolution                     (default: 640x480)
#   DEVICE_NAME        prefix on filenames (the device's name in EI)
#                                                             (default: $(hostname))
#
# Usage:
#   sudo apt install -y ffmpeg                # one-time
#   EI_API_KEY=ei_xxx LABEL=coffee ./scripts/capture-and-upload.sh
#
#   # all defaults — 10 unlabeled training samples 2s apart:
#   EI_API_KEY=ei_xxx ./scripts/capture-and-upload.sh
#
#   # 5 testing samples for the "lamp" class:
#   EI_API_KEY=ei_xxx LABEL=lamp CATEGORY=testing COUNT=5 \
#       ./scripts/capture-and-upload.sh
#
# Note: if the inference container (edge-impulse-linux-runner) is
# already holding /dev/video0, ffmpeg may fail or produce a black
# frame. Stop the container first, or use a second camera:
#   sudo systemctl stop fioup            # or `docker stop <container>`
# After capture, restart it:
#   sudo systemctl start fioup
#
# For object-detection projects, samples uploaded with a generic LABEL
# land in the Studio's labeling queue — annotate them with bounding
# boxes there, then the watcher will pick them up.

set -euo pipefail

: "${EI_API_KEY:?set EI_API_KEY}"

LABEL="${LABEL:-unlabeled}"
CATEGORY="${CATEGORY:-training}"
COUNT="${COUNT:-10}"
INTERVAL="${INTERVAL:-2}"
DEVICE="${DEVICE:-/dev/video0}"
WIDTH="${WIDTH:-640}"
HEIGHT="${HEIGHT:-480}"
DEVICE_NAME="${DEVICE_NAME:-$(hostname)}"

case "$CATEGORY" in
  training|testing) ;;
  *) echo "CATEGORY must be 'training' or 'testing'" >&2; exit 1 ;;
esac

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg required: sudo apt install -y ffmpeg" >&2
  exit 1
fi

if [ ! -e "$DEVICE" ]; then
  echo "$DEVICE does not exist. Plug in a UVC camera or override DEVICE." >&2
  exit 1
fi

INGEST="https://ingestion.edgeimpulse.com/api/${CATEGORY}/data"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

echo "[capture] device=$DEVICE label=$LABEL category=$CATEGORY count=$COUNT interval=${INTERVAL}s"

ok=0
for i in $(seq 1 "$COUNT"); do
  ts=$(date +%Y%m%d-%H%M%S)
  fname="${LABEL}.${DEVICE_NAME}.${ts}-${i}.jpg"
  out="${tmpdir}/${fname}"

  if ! ffmpeg -hide_banner -loglevel error \
      -f v4l2 -video_size "${WIDTH}x${HEIGHT}" -i "$DEVICE" \
      -frames:v 1 -y "$out" 2>/dev/null; then
    echo "  [$i/$COUNT] capture failed (camera busy?)"; continue
  fi

  size=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
  if [ "${size:-0}" -lt 1024 ]; then
    echo "  [$i/$COUNT] frame too small (${size}B); skipping"
    continue
  fi

  if curl -fsS -X POST "$INGEST" \
      -H "x-api-key: ${EI_API_KEY}" \
      -H "x-label: ${LABEL}" \
      -H "x-file-name: ${fname}" \
      -H "Content-Type: image/jpeg" \
      --data-binary "@${out}" \
      -o /dev/null; then
    echo "  [$i/$COUNT] uploaded $fname (${size}B)"
    ok=$((ok + 1))
  else
    echo "  [$i/$COUNT] upload failed for $fname"
  fi

  [ "$i" -lt "$COUNT" ] && sleep "$INTERVAL"
done

echo "[done] uploaded $ok/$COUNT samples to ${CATEGORY}."
echo "       Next hourly run of ei-data-watch-and-retrain.yml will detect the new count."
echo "       Or trigger immediately: gh workflow run ei-data-watch-and-retrain.yml -F force=true"
