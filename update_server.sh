#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/Apexify}"
TARGET_SCRIPT="${APP_DIR}/update.sh"

if [ ! -f "${TARGET_SCRIPT}" ]; then
  echo "ERROR: update script not found at ${TARGET_SCRIPT}"
  exit 1
fi

exec bash "${TARGET_SCRIPT}" "$@"
