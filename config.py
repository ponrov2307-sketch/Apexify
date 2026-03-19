import os
import dotenv

# โหลดค่าจากไฟล์ .env (ถ้ารันบนเครื่องตัวเอง)
dotenv.load_dotenv()


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

# Dashboard magic login (optional; should not crash bot when missing)
BOT_DASHBOARD_LOGIN_ENABLED = _to_bool("BOT_DASHBOARD_LOGIN_ENABLED", True)
DASHBOARD_BASE_URL = (os.getenv("DASHBOARD_BASE_URL") or "").strip()
DASHBOARD_LOGIN_SECRET = (os.getenv("DASHBOARD_LOGIN_SECRET") or "").strip()
DASHBOARD_LOGIN_TOKEN_TTL = _to_int("DASHBOARD_LOGIN_TOKEN_TTL", 300)
BOT_WEB_BASE_URL = (os.getenv("BOT_WEB_BASE_URL") or "").strip()
FLASK_SECRET_KEY = (os.getenv("FLASK_SECRET_KEY") or DASHBOARD_LOGIN_SECRET or "").strip()
APEXIFY_PASSWORD = (
    os.getenv("APEXIFY_PASSWORD")
    or os.getenv("AUTH_SHARED_PASSCODE")
    or ""
).strip()

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Error: กรุณาตั้งค่า TELEGRAM_TOKEN และ GEMINI_API_KEY ในไฟล์ .env หรือ Environment Variables")
