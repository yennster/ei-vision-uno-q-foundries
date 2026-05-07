#!/usr/bin/env bash
# refresh-model.sh — locally retrain (optional) and rebuild the .eim
# for the EI project configured below, then drop fresh copies into
#   app/model/${EI_MODEL_FILENAME}
#   containers/${APP_NAME}/model.eim
#
# This is the local equivalent of .github/workflows/ei-data-watch-and-retrain.yml
# minus the git/tag steps. Use it when you want to refresh the model on
# your laptop (e.g. before pushing a release tag manually).
#
# Required env:
#   EI_API_KEY            Edge Impulse API key (starts with ei_)
#
# Optional env (with defaults — match the GitHub Actions repo variables):
#   EI_PROJECT_ID         numeric EI project ID            (no default; required)
#   EI_DEPLOY_TARGET      EI deployment target name        (default: arduino-uno-q)
#   EI_MODEL_TYPE         float32 | int8                   (default: float32)
#   EI_MODEL_FILENAME     name under app/model/            (default: object-detection.eim)
#   APP_NAME              name under containers/           (default: ei-vision)
#   RETRAIN               yes | no                         (default: no)
#
# Usage:
#   EI_API_KEY=ei_xxx EI_PROJECT_ID=12345 ./scripts/refresh-model.sh
#   EI_API_KEY=ei_xxx EI_PROJECT_ID=12345 RETRAIN=yes ./scripts/refresh-model.sh

set -euo pipefail

: "${EI_API_KEY:?EI_API_KEY is required}"
: "${EI_PROJECT_ID:?EI_PROJECT_ID is required}"

EI_DEPLOY_TARGET="${EI_DEPLOY_TARGET:-arduino-uno-q}"
EI_MODEL_TYPE="${EI_MODEL_TYPE:-float32}"
EI_MODEL_FILENAME="${EI_MODEL_FILENAME:-object-detection.eim}"
APP_NAME="${APP_NAME:-ei-vision}"
RETRAIN="${RETRAIN:-no}"

EI_BASE="https://studio.edgeimpulse.com/v1/api"
H=(-H "x-api-key: ${EI_API_KEY}")

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

log()  { printf '[refresh-model] %s\n' "$*"; }
api()  { curl -fsS "${H[@]}" "$@"; }

poll_job() {
  local job=$1 max=${2:-180} interval=${3:-30}
  for i in $(seq 1 "$max"); do
    local status fin ok
    status=$(api "${EI_BASE}/${EI_PROJECT_ID}/jobs/${job}/status")
    fin=$(echo "$status" | jq -r .job.finished)
    if [ "$fin" != "null" ] && [ -n "$fin" ]; then
      ok=$(echo "$status" | jq -r .job.finishedSuccessful)
      [ "$ok" = "true" ] && return 0
      log "job $job FAILED: $status"
      return 1
    fi
    log "[$i] job $job in progress..."
    sleep "$interval"
  done
  log "job $job timed out"
  return 1
}

if [ "$RETRAIN" = "yes" ]; then
  log "starting retrain for project ${EI_PROJECT_ID}"
  job=$(api -X POST "${EI_BASE}/${EI_PROJECT_ID}/jobs/retrain" | jq -r .id)
  [ -z "$job" ] || [ "$job" = "null" ] && { log "failed to start retrain"; exit 1; }
  log "retrain job: $job — follow at https://studio.edgeimpulse.com/studio/${EI_PROJECT_ID}/jobs"
  poll_job "$job" 180 30
  log "retrain complete"
else
  log "RETRAIN=no — skipping retrain (set RETRAIN=yes to retrain first)"
fi

log "building .eim for ${EI_DEPLOY_TARGET} (${EI_MODEL_TYPE})"
build=$(api -X POST -H "Content-Type: application/json" \
  -d "{\"engine\":\"tflite\",\"modelType\":\"${EI_MODEL_TYPE}\"}" \
  "${EI_BASE}/${EI_PROJECT_ID}/jobs/build-ondevice-model?type=${EI_DEPLOY_TARGET}")
build_job=$(echo "$build" | jq -r .id)
deployment_version=$(echo "$build" | jq -r .deploymentVersion)
log "build job: $build_job (deployment v${deployment_version})"
poll_job "$build_job" 60 20
log "build complete"

mkdir -p "app/model" "containers/${APP_NAME}"
out="app/model/${EI_MODEL_FILENAME}"
log "downloading .eim → $out"
curl -fsSL "${H[@]}" -o "$out" \
  "${EI_BASE}/${EI_PROJECT_ID}/deployment/download?type=${EI_DEPLOY_TARGET}&modelType=${EI_MODEL_TYPE}"
chmod +x "$out"
cp "$out" "containers/${APP_NAME}/model.eim"

log "updated:"
ls -lh "$out" "containers/${APP_NAME}/model.eim"

if command -v jq >/dev/null && [ -f .dataset-state.json ]; then
  train=$(api "${EI_BASE}/${EI_PROJECT_ID}/raw-data/count?category=training" | jq -r .count)
  test=$( api "${EI_BASE}/${EI_PROJECT_ID}/raw-data/count?category=testing"  | jq -r .count)
  total=$((train + test))
  jq --argjson t "$total" --argjson v "$deployment_version" \
     '.lastTrainedSampleCount=$t | .lastDeploymentVersion=$v' \
     .dataset-state.json > .dataset-state.json.new
  mv .dataset-state.json.new .dataset-state.json
  log "state file updated: count=$total deployment=$deployment_version"
fi

log "done. Commit, tag (vX.Y.Z), and push to fire foundries-deploy.yml."
