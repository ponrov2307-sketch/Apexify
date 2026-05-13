"""bot_utils.py — shared helpers สำหรับ Telegram bot

- safe_send_with_retry(): wrap bot.send_message() พร้อม retry logic + auto-mark
  inactive ถ้า user block bot
- friendly_error(): แปลง raw exception เป็น Thai user-facing message
  (ไม่ leak stack trace ไปหา user)
- broadcast_maintenance_notice(): ส่งข้อความเปิด/ปิด maintenance หา active users
- alert_admin_error(): ping ADMIN_ID เมื่อ user เจอ error — Sentry-lite
- get_company_short_name(): ดึงชื่อบริษัทย่อ cached 24h (PP P. 2026-05-13)
"""
import time
import traceback
from threading import Thread

from database import mark_user_inactive


# ============ Company name cache (2026-05-13 — PP P. request) ============
# Display "AAPL (Apple Inc.)" ในทุก ticker mention
# yfinance .info เป็น HTTP call หนัก → cache 24h (company name แทบไม่เปลี่ยน)
_company_name_cache = {}    # {symbol_upper: (name, ts)}
_COMPANY_NAME_TTL = 24 * 3600   # 24 hours


def get_company_short_name(symbol: str) -> str:
    """ดึงชื่อบริษัทย่อ (cached 24h)

    Returns: short name (≤22 chars) หรือ "" ถ้าหาไม่ได้
    """
    if not symbol:
        return ""
    key = symbol.upper()
    cached = _company_name_cache.get(key)
    if cached:
        name, ts = cached
        if time.time() - ts < _COMPANY_NAME_TTL:
            return name

    name = ""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        raw = (info.get("shortName") or info.get("longName") or "").strip()
        # Clean common suffixes — เก็บแค่ส่วน core
        for suffix in (", Inc.", " Inc.", " Inc", ", Inc", " Corporation", " Corp.", " Corp"):
            if raw.endswith(suffix):
                raw = raw[:-len(suffix)].strip()
                break
        # Truncate ≤22 chars
        if len(raw) > 22:
            raw = raw[:22].rstrip() + "…"
        name = raw
    except Exception:
        # Network err / no info — cache empty string ป้องกัน hammer
        name = ""

    _company_name_cache[key] = (name, time.time())
    return name


# Maintenance notices — ใช้ทั้งใน admin dashboard และ /maintenance command ในบอท
MAINT_NOTICE_ON = (
    "🔧 *Apexify ปิดปรับปรุงระบบชั่วคราว*\n\n"
    "ระบบกำลังอัปเกรดเพื่อบริการคุณดีขึ้น "
    "ขออภัยในความไม่สะดวกครับ — เราจะแจ้งทันทีเมื่อกลับมาใช้งานได้ 🙏"
)
MAINT_NOTICE_OFF = (
    "✅ *Apexify กลับมาใช้งานได้แล้ว!*\n\n"
    "ขอบคุณที่รอครับ ทุกฟีเจอร์พร้อมใช้แล้ว — "
    "พิมพ์ชื่อหุ้นเพื่อเริ่มวิเคราะห์ได้เลย 📊"
)


def broadcast_maintenance_notice(bot_instance, enabled, admin_id=None):
    """Background broadcast: แจ้ง user ทุกคนว่าบอทเข้า/ออกจาก maintenance mode
    เรียกได้จากทั้ง admin dashboard (keep_alive.py) และ /maintenance (main.py)
    ส่งกลับ Thread instance ในกรณีที่ caller อยากรอหรือ join
    """
    def _run():
        from database import get_active_users, log_broadcast
        msg = MAINT_NOTICE_ON if enabled else MAINT_NOTICE_OFF
        audience_label = "maint_on" if enabled else "maint_off"
        try:
            active = list(get_active_users() or [])
            if admin_id and str(admin_id) not in [str(u) for u in active]:
                active.insert(0, admin_id)
            success = 0
            fail = 0
            for uid in active:
                ok = safe_send_with_retry(bot_instance, uid, msg, retries=2, parse_mode="Markdown")
                if ok:
                    success += 1
                else:
                    fail += 1
                time.sleep(0.05)  # ~20 msg/sec — ปลอดภัยจาก Telegram rate limit
            try:
                log_broadcast(audience_label, len(active), success, fail)
            except Exception:
                pass
            print(f"[MaintenanceBroadcast] {audience_label}: sent {success}, failed {fail}, total {len(active)}", flush=True)
        except Exception as e:
            print(f"[MaintenanceBroadcast] error: {e}", flush=True)

    t = Thread(target=_run, daemon=True)
    t.start()
    return t


# Generic Thai-friendly fallback ที่โชว์ให้ user เห็นแทน raw exception
_FRIENDLY_ERROR_DEFAULT = "❌ ระบบขัดข้องชั่วคราว ลองอีกครั้งใน 1 นาทีนะครับ"


def friendly_error(prefix=None):
    """คืน Thai-friendly error message สำหรับโชว์ user
    ไว้คู่กับ print(f"[handler] {e}") server-side log

    Usage:
        except Exception as e:
            print(f"[my_handler] {e}", flush=True)
            bot.reply_to(message, friendly_error("ดึงข่าวไม่สำเร็จ"))
    """
    if prefix:
        return f"❌ {prefix} — ลองอีกครั้งใน 1 นาทีนะครับ"
    return _FRIENDLY_ERROR_DEFAULT


def safe_send_with_retry(bot_instance, user_id, text, retries=3, base_backoff=1.5, **kwargs):
    """ส่งข้อความแบบมี retry — ใช้สำหรับ bulk send (broadcast / alert) หรือ critical path

    - Retry เฉพาะ transient errors (429 rate limit, timeout, 5xx)
    - 403/blocked → mark_user_inactive ไม่ retry
    - คืน True ถ้าสำเร็จ, False ถ้าทุกครั้งล้มเหลว
    """
    last_err = None
    for attempt in range(retries):
        try:
            bot_instance.send_message(user_id, text, **kwargs)
            return True
        except Exception as e:
            last_err = e
            err_str = str(e).lower()

            # Hard fail — user blocked bot, ไม่ต้อง retry
            if any(token in err_str for token in ("403", "blocked", "deactivated", "can't initiate", "user is deactivated")):
                try:
                    mark_user_inactive(user_id)
                except Exception:
                    pass
                return False

            # Rate limit (429) — retry-after value
            if "429" in err_str or "too many requests" in err_str:
                # Telegram บอก retry_after ใน exception บางที parse ได้ บางทีไม่ — fallback exponential
                wait = base_backoff * (2 ** attempt)
                time.sleep(wait)
                continue

            # Transient (timeout, 5xx, network) — retry
            if any(token in err_str for token in ("timeout", "timed out", "500", "502", "503", "504", "connection", "network")):
                wait = base_backoff * (attempt + 1)
                time.sleep(wait)
                continue

            # Other errors — log + don't retry (likely Markdown parse error etc.)
            break

    # ทุก retry หมด — log + return False
    if last_err:
        print(f"[safe_send_with_retry] {user_id} fail after {retries} tries: {last_err}", flush=True)
    return False


# ─── Sentry-lite — error ping ไปยัง ADMIN_ID ใน Telegram ─────────────────
# Throttle: ส่ง error เดียวกันสูงสุด 1 ครั้ง/30 นาที กัน admin chat ถูก spam
_ERROR_NOTIFY_LAST: dict[str, float] = {}
_ERROR_NOTIFY_COOLDOWN = 1800  # 30 minutes per (handler+error_type)


def alert_admin_error(bot_instance, context: str, exc: Exception, user_id=None):
    """แจ้ง admin ทันทีเมื่อ user เจอ error ที่ critical
    เรียกจาก except block:

        except Exception as e:
            print(f"[my_handler] {e}", flush=True)
            alert_admin_error(bot, "my_handler", e, user_id=user_id)
            bot.reply_to(message, friendly_error("..."))

    - ส่งไปยัง ADMIN_ID ผ่าน Telegram (ไม่ต้องจ่าย Sentry)
    - Throttle: error เดียวกันส่งสูงสุด 1 ครั้ง/30 นาที
    - Best-effort — ถ้าส่งไม่สำเร็จก็ silent fail (ไม่กระทบ user flow)
    """
    try:
        from config import ADMIN_ID
        if not ADMIN_ID:
            return

        err_type = type(exc).__name__
        key = f"{context}:{err_type}"
        now = time.time()
        last = _ERROR_NOTIFY_LAST.get(key, 0)
        if now - last < _ERROR_NOTIFY_COOLDOWN:
            return  # throttled
        _ERROR_NOTIFY_LAST[key] = now

        # Trim stack trace to last 6 frames so the message stays readable
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tb_short = "".join(tb_lines)[-700:]

        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = (
            f"🚨 *Apexify Error*\n"
            f"`{ts}`\n\n"
            f"*Where:* `{context}`\n"
            f"*User:* `{user_id or 'unknown'}`\n"
            f"*Error:* `{err_type}`\n"
            f"_{str(exc)[:150]}_\n\n"
            f"```\n{tb_short}\n```\n"
            f"_(throttled 30min — same error won't ping again)_"
        )

        # Send in background thread — never block the caller's response
        def _ping():
            try:
                bot_instance.send_message(int(ADMIN_ID), msg, parse_mode="Markdown",
                                           disable_web_page_preview=True)
            except Exception as send_err:
                # Markdown parse failure → fallback plain text
                try:
                    plain = (
                        f"🚨 Apexify Error · {ts}\n"
                        f"Where: {context}\nUser: {user_id or 'unknown'}\n"
                        f"{err_type}: {str(exc)[:200]}"
                    )
                    bot_instance.send_message(int(ADMIN_ID), plain)
                except Exception:
                    print(f"[alert_admin_error] failed to ping admin: {send_err}", flush=True)

        Thread(target=_ping, daemon=True).start()
    except Exception as outer:
        # Never let the error-reporter itself raise
        print(f"[alert_admin_error] internal: {outer}", flush=True)
