#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/Apexify}"
SERVICE_NAME="${SERVICE_NAME:-apexify.service}"
ALERT_SERVICE_NAME="${ALERT_SERVICE_NAME:-apexify-alert.service}"
PORT="${PORT:-8080}"
LOG_FILE="${LOG_FILE:-/tmp/apexify_update.log}"
PYTHON_BIN="${PYTHON_BIN:-}"
REQUIREMENTS_STATE_FILE="${REQUIREMENTS_STATE_FILE:-$APP_DIR/.requirements-sync-state}"
FORCE_PIP_SYNC="${FORCE_PIP_SYNC:-0}"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
WHITE='\033[1;37m'
NC='\033[0m'

banner() {
  clear
  echo -e "${MAGENTA}"
  cat <<'ART'
        🚀✨  █████╗ ██████╗ ███████╗██╗  ██╗██╗███████╗██╗   ██╗  ✨🚀
             ██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝██║██╔════╝╚██╗ ██╔╝
             ███████║██████╔╝█████╗   ╚███╔╝ ██║█████╗   ╚████╔╝
             ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗ ██║██╔══╝    ╚██╔╝
             ██║  ██║██║     ███████╗██╔╝ ██╗██║██║        ██║
             ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝╚═╝        ╚═╝
ART
  echo -e "${NC}"
  echo -e "${CYAN}🌌==============================================================🌌${NC}"
  echo -e "${WHITE}🛸            APEXIFY COSMIC AUTO-UPDATE ENGINE             🛸${NC}"
  echo -e "${CYAN}🌌==============================================================🌌${NC}"
  echo
}

pulse() {
  echo -ne "["
  for i in {1..16}; do
    echo -ne "${YELLOW}▓${NC}"
    sleep 0.035
  done
  echo -ne "]"
}

need_env_keys() {
  local bad=0
  : > "$LOG_FILE"
  for k in TELEGRAM_TOKEN ADMIN_ID GEMINI_API_KEY DATABASE_URL BOT_WEB_BASE_URL FLASK_SECRET_KEY DASHBOARD_LOGIN_SECRET SLIPOK_BRANCH_ID SLIPOK_API_KEY; do
    if ! grep -q "^${k}=" .env; then
      echo "missing env: $k" >> "$LOG_FILE"
      bad=1
    fi
  done
  [ $bad -eq 0 ]
}

resolve_python_bin() {
  if [ -n "${PYTHON_BIN}" ] && [ -x "${PYTHON_BIN}" ]; then
    return 0
  fi

  for candidate in "${APP_DIR}/venv/bin/python" "${APP_DIR}/.venv/bin/python" "${APP_DIR}/.venv313/bin/python"; do
    if [ -x "${candidate}" ]; then
      PYTHON_BIN="${candidate}"
      return 0
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
    return 0
  fi

  echo "python runtime not found" >> "$LOG_FILE"
  return 1
}

install_requirements() {
  local fingerprint
  fingerprint="$("${PYTHON_BIN}" - <<'PY'
import hashlib
import pathlib
import sys

requirements = pathlib.Path("requirements.txt").read_bytes()
payload = requirements + b"\n" + sys.executable.encode("utf-8") + b"\n" + sys.version.encode("utf-8")
print(hashlib.sha256(payload).hexdigest())
PY
)"

  if [ "${FORCE_PIP_SYNC}" != "1" ] && [ -f "${REQUIREMENTS_STATE_FILE}" ]; then
    local previous_fingerprint
    previous_fingerprint="$(cat "${REQUIREMENTS_STATE_FILE}")"
    if [ "${previous_fingerprint}" = "${fingerprint}" ]; then
      echo "requirements unchanged - skipping pip sync"
      return 0
    fi
  fi

  local pip_args=(
    install
    --disable-pip-version-check
    --prefer-binary
    --upgrade-strategy only-if-needed
    --no-input
    -r requirements.txt
  )

  if "${PYTHON_BIN}" - <<'PY'
import sys
raise SystemExit(0 if sys.prefix == getattr(sys, "base_prefix", sys.prefix) else 1)
PY
  then
    "${PYTHON_BIN}" -m pip "${pip_args[@]}" --break-system-packages
  else
    "${PYTHON_BIN}" -m pip "${pip_args[@]}"
  fi

  printf '%s' "${fingerprint}" > "${REQUIREMENTS_STATE_FILE}"
}

verify_runtime_imports() {
  "${PYTHON_BIN}" - <<'PY'
import flask
import jwt
import psutil
import telebot
import yfinance
from dotenv import load_dotenv
from google import genai

assert hasattr(telebot, "TeleBot"), "telebot module is present but TeleBot is missing"
assert callable(load_dotenv), "python-dotenv is present but load_dotenv is unavailable"
assert hasattr(genai, "Client"), "google.genai is present but Client is missing"
print("runtime imports ok")
PY
}

health_check_local_web() {
  local root_url="http://127.0.0.1:${PORT}/"
  local admin_url="http://127.0.0.1:${PORT}/admin"

  if command -v curl >/dev/null 2>&1; then
    curl -fsS "${root_url}" >/dev/null
    local admin_status
    admin_status="$(curl -s -o /dev/null -w "%{http_code}" "${admin_url}")"
    [ "${admin_status}" = "403" ]
    return 0
  fi

  "${PYTHON_BIN}" - <<'PY'
import os
import sys
import urllib.error
import urllib.request

port = os.environ.get("PORT", "8080")
checks = [
    (f"http://127.0.0.1:{port}/", 200),
    (f"http://127.0.0.1:{port}/admin", 403),
]

for url, expected in checks:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    if status != expected:
        sys.exit(1)
PY
}

restart_alert_worker() {
  cleanup_stray_alert_processes() {
    local service_pid="${1:-0}"
    while IFS= read -r line; do
      local pid
      pid="$(printf '%s\n' "$line" | awk '{print $1}')"
      if [ -z "${pid}" ] || [ "${pid}" = "${service_pid}" ]; then
        continue
      fi
      kill "${pid}" >/dev/null 2>&1 || true
    done < <(pgrep -af 'alert_system.py' || true)
  }

  if [ -n "${ALERT_SERVICE_NAME}" ]; then
    systemctl restart "${ALERT_SERVICE_NAME}"
    systemctl is-active --quiet "${ALERT_SERVICE_NAME}"
    sleep 2
    local service_pid
    service_pid="$(systemctl show -p MainPID --value "${ALERT_SERVICE_NAME}" 2>/dev/null || echo 0)"
    cleanup_stray_alert_processes "${service_pid}"
    return 0
  fi

  pkill -f 'alert_system.py' || true
  nohup "${PYTHON_BIN}" "${APP_DIR}/alert_system.py" > "${APP_DIR}/alert_log.txt" 2>&1 &
  sleep 2
  pgrep -f 'alert_system.py' >/dev/null
}

step() {
  local title="$1"
  local cmd="$2"
  local ignore_fail="${3:-false}"

  printf "${BLUE}%-52s${NC} " "$title"

  local status=0
  if eval "$cmd" > "$LOG_FILE" 2>&1; then
    status=0
  else
    status=$?
  fi

  pulse

  if [ $status -eq 0 ] || [ "$ignore_fail" = "true" ]; then
    echo -e "  ${GREEN}✅ OK${NC}"
  else
    echo -e "  ${RED}❌ FAIL${NC}"
    echo -e "${RED}⚠️  ERROR TRACE:${NC}"
    cat "$LOG_FILE"
    exit 1
  fi
}

banner

step "🛰️ [1/11] Docking into command center" \
     "cd \"$APP_DIR\" && pwd >/dev/null" "false"

step "🔐 [2/11] Validating secret vault (.env)" \
     "test -f .env && need_env_keys" "false"

step "🧱 [3/11] Hardening vault permission" \
     "chmod 600 .env" "true"

step "🧬 [4/11] Checking .env is never tracked" \
     "! git ls-files --error-unmatch .env >/dev/null 2>&1" "false"

step "🐍 [5/11] Resolving Python runtime" \
     "resolve_python_bin && \"\$PYTHON_BIN\" --version" "false"

step "📡 [6/11] Pulling latest star-map from GitHub" \
     "git fetch --all && git reset --hard origin/main" "false"

step "📦 [7/11] Syncing Python dependencies" \
     "install_requirements" "false"

step "🧪 [8/11] Running Python warp-syntax check" \
     "\"\$PYTHON_BIN\" -m py_compile main.py config.py dashboard_login.py keep_alive.py admin_service.py alert_system.py database.py ai_analyzer.py technical_tools.py slipok_service.py" "false"

step "🧰 [9/11] Verifying runtime imports" \
     "verify_runtime_imports" "false"

step "🤖 [10/11] Restarting bot core reactor" \
     "systemctl restart \"$SERVICE_NAME\" && systemctl is-active --quiet \"$SERVICE_NAME\"" "false"

step "🌐 [11/11] Relaunching alert satellite + web health-check" \
     "restart_alert_worker && health_check_local_web" "false"

echo
echo -e "${CYAN}🌠==============================================================🌠${NC}"
echo -e "${GREEN}🎉 MISSION COMPLETE: BOT + ALERT + WEB ONLINE 🚀               ${NC}"
echo -e "${CYAN}🌠==============================================================🌠${NC}"
echo -e "${WHITE}🐍 Python:${NC} $PYTHON_BIN"
echo -e "${WHITE}🌍 Web:${NC} http://127.0.0.1:${PORT}/"
echo -e "${WHITE}🔐 Admin:${NC} http://127.0.0.1:${PORT}/admin"
