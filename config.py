import os
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:
    _load_dotenv = None


def _load_local_env():
    env_path = Path(__file__).resolve().parent / ".env"

    if callable(_load_dotenv):
        try:
            _load_dotenv(dotenv_path=env_path)
        except TypeError:
            _load_dotenv(str(env_path))
        except Exception:
            pass

    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())


# โหลดค่าจากไฟล์ .env จากโฟลเดอร์โปรเจกต์โดยตรง
_load_local_env()


def _to_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")
SLIPOK_BRANCH_ID = (os.getenv("SLIPOK_BRANCH_ID") or "").strip()
SLIPOK_API_KEY = (os.getenv("SLIPOK_API_KEY") or "").strip()
SLIPOK_TIMEOUT_SECONDS = _to_int("SLIPOK_TIMEOUT_SECONDS", 15)
PROMPTPAY_ID = (os.getenv("PROMPTPAY_ID") or "").strip()  # เบอร์โทร/บัตรปชช. PromptPay

# Dashboard magic login (optional; should not crash bot when missing)
BOT_DASHBOARD_LOGIN_ENABLED = _to_bool("BOT_DASHBOARD_LOGIN_ENABLED", True)
DASHBOARD_BASE_URL = (os.getenv("DASHBOARD_BASE_URL") or "").strip()
DASHBOARD_LOGIN_SECRET = (os.getenv("DASHBOARD_LOGIN_SECRET") or "").strip()
ADMIN_DASHBOARD_LOGIN_SECRET = (
    os.getenv("ADMIN_DASHBOARD_LOGIN_SECRET")
    or DASHBOARD_LOGIN_SECRET
    or ""
).strip()
DASHBOARD_LOGIN_TOKEN_TTL = _to_int("DASHBOARD_LOGIN_TOKEN_TTL", 300)
BOT_WEB_BASE_URL = (os.getenv("BOT_WEB_BASE_URL") or "").strip()
FLASK_SECRET_KEY = (
    os.getenv("FLASK_SECRET_KEY")
    or ADMIN_DASHBOARD_LOGIN_SECRET
    or DASHBOARD_LOGIN_SECRET
    or ""
).strip()
APEXIFY_PASSWORD = (
    os.getenv("APEXIFY_PASSWORD")
    or os.getenv("AUTH_SHARED_PASSCODE")
    or ""
).strip()

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Error: กรุณาตั้งค่า TELEGRAM_TOKEN และ GEMINI_API_KEY ในไฟล์ .env หรือ Environment Variables")

from google import genai as _genai
gemini_client = _genai.Client(api_key=GEMINI_API_KEY)

# ============ Auto-DM Cron (P1 #2 — Activation + Win-back) ============
# Defaults sensible — ถ้าไม่มี .env override ก็ work ทันที
AUTO_DM_ENABLED = _to_bool("AUTO_DM_ENABLED", True)
AUTO_DM_HOUR_ICT = _to_int("AUTO_DM_HOUR_ICT", 11)
AUTO_DM_DAILY_LIMIT = _to_int("AUTO_DM_DAILY_LIMIT", 50)
AUTO_DM_DRY_RUN = _to_bool("AUTO_DM_DRY_RUN", False)
AUTO_DM_REPEAT_COOLDOWN_DAYS = _to_int("AUTO_DM_REPEAT_COOLDOWN_DAYS", 30)

# ============ Daily Stock Picker (A — admin DM 7:30 ICT) ============
DAILY_PICKER_ENABLED = _to_bool("DAILY_PICKER_ENABLED", True)
DAILY_PICKER_HOUR_ICT = _to_int("DAILY_PICKER_HOUR_ICT", 7)
DAILY_PICKER_MINUTE_ICT = _to_int("DAILY_PICKER_MINUTE_ICT", 30)

# ============ Earnings Prep (B — DM admin 1 day before big earnings, 16:00 ICT) ============
EARNINGS_PREP_ENABLED = _to_bool("EARNINGS_PREP_ENABLED", True)
EARNINGS_PREP_HOUR_ICT = _to_int("EARNINGS_PREP_HOUR_ICT", 16)
EARNINGS_PREP_MINUTE_ICT = _to_int("EARNINGS_PREP_MINUTE_ICT", 0)


# ============ Thai timezone helpers ============
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

def thai_now():
    """datetime ปัจจุบันใน Asia/Bangkok (UTC+7)"""
    return _dt.now(_tz.utc) + _td(hours=7)


def thai_today():
    """date วันนี้ใน Asia/Bangkok"""
    return thai_now().date()
