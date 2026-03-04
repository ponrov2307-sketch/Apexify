import logging
from datetime import datetime, timezone
from urllib.parse import quote

import jwt

from config import (
    BOT_DASHBOARD_LOGIN_ENABLED,
    DASHBOARD_BASE_URL,
    DASHBOARD_LOGIN_SECRET,
    DASHBOARD_LOGIN_TOKEN_TTL,
)

logger = logging.getLogger(__name__)


def mask_telegram_id(telegram_id: str) -> str:
    raw = str(telegram_id or "").strip()
    if len(raw) <= 4:
        return "****"
    return f"{raw[:2]}***{raw[-2:]}"


def is_dashboard_login_ready() -> tuple[bool, str]:
    if not BOT_DASHBOARD_LOGIN_ENABLED:
        return False, "disabled"
    if not DASHBOARD_BASE_URL:
        return False, "url_missing"
    if not DASHBOARD_LOGIN_SECRET:
        return False, "secret_missing"
    return True, "ok"


def build_dashboard_login_token(telegram_id: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, int(DASHBOARD_LOGIN_TOKEN_TTL))
    payload = {
        "telegram_id": str(telegram_id),
        "iat": now,
        "exp": now + ttl,
        "iss": "apexify-bot",
    }
    return jwt.encode(payload, DASHBOARD_LOGIN_SECRET, algorithm="HS256")


def build_dashboard_login_url(telegram_id: str) -> str:
    token = build_dashboard_login_token(telegram_id)
    base_url = DASHBOARD_BASE_URL.rstrip("/")
    return f"{base_url}/login-token?token={quote(token, safe='')}"


def issue_dashboard_login_url(telegram_id: str) -> tuple[bool, str, str]:
    ready, reason = is_dashboard_login_ready()
    if not ready:
        logger.warning(
            "dashboard_token_issue_failed telegram_id=%s reason=%s",
            mask_telegram_id(telegram_id),
            reason,
        )
        return False, "", reason

    try:
        url = build_dashboard_login_url(telegram_id)
        logger.info("dashboard_token_issued telegram_id=%s", mask_telegram_id(telegram_id))
        return True, url, "ok"
    except Exception:
        logger.warning(
            "dashboard_token_issue_failed telegram_id=%s reason=internal_error",
            mask_telegram_id(telegram_id),
        )
        return False, "", "internal_error"
