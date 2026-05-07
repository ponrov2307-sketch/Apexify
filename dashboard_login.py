import logging
from datetime import datetime, timezone
from urllib.parse import quote

import jwt

from config import (
    ADMIN_ID,
    ADMIN_DASHBOARD_LOGIN_SECRET,
    BOT_DASHBOARD_LOGIN_ENABLED,
    BOT_WEB_BASE_URL,
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


def is_admin_dashboard_ready() -> tuple[bool, str]:
    if not BOT_WEB_BASE_URL:
        return False, "url_missing"
    if not ADMIN_DASHBOARD_LOGIN_SECRET:
        return False, "secret_missing"
    if not ADMIN_ID:
        return False, "admin_missing"
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


def build_admin_dashboard_token(telegram_id: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, int(DASHBOARD_LOGIN_TOKEN_TTL))
    payload = {
        "telegram_id": str(telegram_id),
        "iat": now,
        "exp": now + ttl,
        "iss": "apexify-bot",
        "scope": "admin_dashboard",
    }
    return jwt.encode(payload, ADMIN_DASHBOARD_LOGIN_SECRET, algorithm="HS256")


def build_dashboard_login_url(telegram_id: str, src: str = "command", next_path: str = "/") -> str:
    token = build_dashboard_login_token(telegram_id)
    base_url = DASHBOARD_BASE_URL.rstrip("/")
    # Same-origin guard — defensive even though all current callers are static.
    # Reject empty, off-host ("//host"), absolute ("https://..."), or non-rooted paths.
    if (not next_path
            or not next_path.startswith("/")
            or next_path.startswith("//")
            or "://" in next_path):
        next_path = "/"
    params = f"src={quote(src, safe='')}&next={quote(next_path, safe='')}"
    return f"{base_url}/login-token?token={quote(token, safe='')}&{params}"


def build_admin_dashboard_url(telegram_id: str) -> str:
    token = build_admin_dashboard_token(telegram_id)
    base_url = BOT_WEB_BASE_URL.rstrip("/")
    return f"{base_url}/admin-login-token?token={quote(token, safe='')}"


def issue_dashboard_login_url(telegram_id: str, src: str = "command", next_path: str = "/") -> tuple[bool, str, str]:
    ready, reason = is_dashboard_login_ready()
    if not ready:
        logger.warning(
            "dashboard_token_issue_failed telegram_id=%s reason=%s",
            mask_telegram_id(telegram_id),
            reason,
        )
        return False, "", reason

    try:
        url = build_dashboard_login_url(telegram_id, src=src, next_path=next_path)
        logger.info("dashboard_token_issued telegram_id=%s", mask_telegram_id(telegram_id))
        return True, url, "ok"
    except Exception:
        logger.warning(
            "dashboard_token_issue_failed telegram_id=%s reason=internal_error",
            mask_telegram_id(telegram_id),
        )
        return False, "", "internal_error"


def issue_admin_dashboard_url(telegram_id: str) -> tuple[bool, str, str]:
    ready, reason = is_admin_dashboard_ready()
    if not ready:
        logger.warning(
            "admin_dashboard_token_issue_failed telegram_id=%s reason=%s",
            mask_telegram_id(telegram_id),
            reason,
        )
        return False, "", reason

    if str(telegram_id) != str(ADMIN_ID):
        logger.warning(
            "admin_dashboard_token_issue_failed telegram_id=%s reason=forbidden",
            mask_telegram_id(telegram_id),
        )
        return False, "", "forbidden"

    try:
        url = build_admin_dashboard_url(telegram_id)
        logger.info("admin_dashboard_token_issued telegram_id=%s", mask_telegram_id(telegram_id))
        return True, url, "ok"
    except Exception:
        logger.warning(
            "admin_dashboard_token_issue_failed telegram_id=%s reason=internal_error",
            mask_telegram_id(telegram_id),
        )
        return False, "", "internal_error"


def verify_admin_dashboard_token(token: str) -> tuple[bool, dict | None, str]:
    raw_token = str(token or "").strip()
    if not raw_token:
        return False, None, "token_missing"
    if not ADMIN_DASHBOARD_LOGIN_SECRET:
        return False, None, "secret_missing"

    try:
        payload = jwt.decode(
            raw_token,
            ADMIN_DASHBOARD_LOGIN_SECRET,
            algorithms=["HS256"],
            issuer="apexify-bot",
        )
    except jwt.ExpiredSignatureError:
        return False, None, "expired"
    except jwt.InvalidTokenError:
        return False, None, "invalid"

    if payload.get("scope") != "admin_dashboard":
        return False, None, "scope_invalid"
    if str(payload.get("telegram_id", "")) != str(ADMIN_ID):
        return False, None, "forbidden"
    return True, payload, "ok"
