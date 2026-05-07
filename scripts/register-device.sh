#!/usr/bin/env bash
# register-device.sh — non-interactive device registration with fioup
#
# Skips the browser-based OAuth device-flow by passing a Foundries API
# token directly to `fioup register --api-token`. Useful for fleet
# provisioning, CI bring-up, or any time you can't open a browser on
# the same machine you're registering.
#
# Run on the device itself, after `fioup` is installed (see
# https://github.com/foundriesio/fioup/blob/main/docs/install.md).
#
# Required env:
#   FOUNDRIES_API_TOKEN  Foundries OSF token with `devices:create` scope
#                        for the target factory (read it from a file or
#                        export it just before running — never commit).
#   FOUNDRIES_FACTORY    factory name (e.g. "jenny")
#   DEVICE_NAME          name to give the device in the dashboard
#
# Optional env:
#   DEVICE_TAG           target tag the device subscribes to  (default: main)
#   APP_NAME             scope the device to a single app     (default: unset → all apps)
#   FORCE                set to "yes" to wipe prior registration data
#
# Example:
#   sudo FOUNDRIES_API_TOKEN=$(cat ~/.fio-token) \
#        FOUNDRIES_FACTORY=jenny DEVICE_NAME=uno-q-01 \
#        ./scripts/register-device.sh

set -euo pipefail

: "${FOUNDRIES_API_TOKEN:?set FOUNDRIES_API_TOKEN}"
: "${FOUNDRIES_FACTORY:?set FOUNDRIES_FACTORY}"
: "${DEVICE_NAME:?set DEVICE_NAME}"

DEVICE_TAG="${DEVICE_TAG:-main}"
FORCE="${FORCE:-no}"

if ! command -v fioup >/dev/null 2>&1; then
  echo "fioup is not installed. See https://github.com/foundriesio/fioup/blob/main/docs/install.md" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "fioup register writes to /var/sota — re-run with sudo." >&2
  exit 1
fi

args=( register
       --factory   "${FOUNDRIES_FACTORY}"
       --name      "${DEVICE_NAME}"
       --tag       "${DEVICE_TAG}"
       --api-token "${FOUNDRIES_API_TOKEN}" )

[ "${FORCE}" = "yes" ] && args+=( --force )
[ -n "${APP_NAME:-}" ] && args+=( --apps "${APP_NAME}" )

echo "[register-device] fioup register --factory ${FOUNDRIES_FACTORY} --name ${DEVICE_NAME} --tag ${DEVICE_TAG}${APP_NAME:+ --apps ${APP_NAME}}${FORCE:+ --force}"
fioup "${args[@]}"

echo "[register-device] verifying connectivity..."
fioup check

echo "[register-device] enabling fioup.service..."
systemctl enable --now fioup

echo "[register-device] done. Device should appear at https://app.foundries.io/factories/${FOUNDRIES_FACTORY}/devices/"
