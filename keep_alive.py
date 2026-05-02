import asyncio
import os
import time
from threading import Thread

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from admin_service import build_local_backup_zip, get_admin_dashboard_snapshot, get_user_info_snapshot, toggle_maintenance_status
from config import ADMIN_DASHBOARD_LOGIN_SECRET, ADMIN_ID, BOT_WEB_BASE_URL, FLASK_SECRET_KEY, TELEGRAM_TOKEN
from dashboard_login import verify_admin_dashboard_token
from database import add_subscription, ban_user, get_all_users, get_active_users, get_dashboard_stats, log_broadcast, mark_user_inactive, unban_user

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY or ADMIN_DASHBOARD_LOGIN_SECRET or os.urandom(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if (BOT_WEB_BASE_URL or "").startswith("https://"):
    app.config["SESSION_COOKIE_SECURE"] = True


def _clear_admin_session():
    session.pop("admin_dashboard_scope", None)
    session.pop("admin_dashboard_telegram_id", None)
    session.pop("admin_dashboard_exp", None)


def _has_valid_admin_session():
    admin_id = str(ADMIN_ID or "").strip()
    scope = session.get("admin_dashboard_scope")
    telegram_id = str(session.get("admin_dashboard_telegram_id", "")).strip()

    try:
        expires_at = int(session.get("admin_dashboard_exp", 0))
    except (TypeError, ValueError):
        expires_at = 0

    is_valid = (
        bool(admin_id)
        and scope == "admin_dashboard"
        and telegram_id == admin_id
        and expires_at > int(time.time())
    )
    if not is_valid:
        _clear_admin_session()
    return is_valid


def _get_bot():
    import telebot
    return telebot.TeleBot(TELEGRAM_TOKEN)


def _do_web_broadcast(msg_text, user_ids):
    import time as _time
    bot = _get_bot()
    success, fail = 0, 0
    for uid in user_ids:
        try:
            bot.send_message(uid, f"📢 **ประกาศจาก Apexify:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
            _time.sleep(0.1)
        except Exception as e:
            err = str(e)
            if "403" in err or "blocked" in err.lower() or "deactivated" in err.lower():
                try:
                    mark_user_inactive(uid)
                except Exception:
                    pass
            try:
                bot.send_message(uid, f"📢 ประกาศจาก Apexify:\n\n{msg_text}")
                success += 1
                _time.sleep(0.1)
            except Exception:
                fail += 1
    return success, fail


@app.route("/")
def home():
    return "🚀 Apexify Bot Web Service is Online!"


@app.errorhandler(403)
def forbidden(_error):
    return (
        """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Access Denied</title>
          <style>
            body { font-family: Arial, sans-serif; background: #0D1117; color: #E6EDF3; display: grid; place-items: center; min-height: 100vh; margin: 0; }
            .card { max-width: 420px; background: #161B22; border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; padding: 28px; box-shadow: 0 20px 50px rgba(0,0,0,0.4); }
            h1 { margin-top: 0; font-size: 28px; color: #FF453A; }
            p { line-height: 1.5; margin-bottom: 0; color: #8B949E; }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>403 — Access Denied</h1>
            <p>This admin dashboard is available for the configured Apexify admin account only.</p>
          </div>
        </body>
        </html>
        """,
        403,
    )


@app.route("/admin-login-token")
def admin_login_token():
    token = request.args.get("token", "")
    success, payload, _reason = verify_admin_dashboard_token(token)
    if not success or not payload:
        abort(403)

    session["admin_dashboard_scope"] = payload.get("scope", "")
    session["admin_dashboard_telegram_id"] = str(payload.get("telegram_id", ""))
    session["admin_dashboard_exp"] = int(payload.get("exp", 0))
    flash("เข้าสู่ระบบ Admin Dashboard สำเร็จ", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin")
def admin_dashboard():
    if not _has_valid_admin_session():
        abort(403)

    try:
        snapshot = get_admin_dashboard_snapshot(limit=15)
    except Exception as exc:
        flash(f"โหลดข้อมูล dashboard ไม่สำเร็จบางส่วน: {exc}", "error")
        snapshot = {
            "maintenance": {"enabled": False},
            "system_health": {},
            "user_stats": {},
            "performance": {},
            "paid_users": [],
            "top_watched": {},
            "expiring_members": {},
            "price_alerts": {},
            "notification_settings": {},
            "recent_activity": {"signups": [], "payments": []},
            "hourly_activity": {"hours": [0] * 24, "max": 1, "peak_hour": None, "total_active": 0, "window_days": 7},
            "funnel": {},
            "top_commands": {"items": [], "total": 0, "window_days": 7},
            "alert_delivery": {"batches": [], "totals": {"total": 0, "success": 0, "fail": 0, "batches": 0, "success_rate": 0.0}, "daily": [], "window_days": 7},
            "quota_burn": {"hit_quota": 0, "near_quota": 0, "total_free_active": 0, "burn_rate_pct": 0.0, "top_burners": [], "quota": 3},
            "win_rate_trend": {"daily": [], "window_days": 14},
            "generated_at": None,
        }

    return render_template(
        "admin_dashboard.html",
        admin_id=str(ADMIN_ID or "").strip(),
        maintenance=snapshot["maintenance"],
        system_health=snapshot["system_health"],
        user_stats=snapshot["user_stats"],
        performance=snapshot["performance"],
        paid_users=snapshot["paid_users"],
        top_watched=snapshot["top_watched"],
        expiring_members=snapshot["expiring_members"],
        price_alerts=snapshot["price_alerts"],
        notification_settings=snapshot["notification_settings"],
        recent_activity=snapshot.get("recent_activity") or {"signups": [], "payments": []},
        hourly_activity=snapshot.get("hourly_activity") or {"hours": [0] * 24, "max": 1, "peak_hour": None, "total_active": 0, "window_days": 7},
        funnel=snapshot.get("funnel") or {},
        top_commands=snapshot.get("top_commands") or {"items": [], "total": 0, "window_days": 7},
        alert_delivery=snapshot.get("alert_delivery") or {"batches": [], "totals": {"total": 0, "success": 0, "fail": 0, "batches": 0, "success_rate": 0.0}, "daily": [], "window_days": 7},
        quota_burn=snapshot.get("quota_burn") or {"hit_quota": 0, "near_quota": 0, "total_free_active": 0, "burn_rate_pct": 0.0, "top_burners": [], "quota": 3},
        win_rate_trend=snapshot.get("win_rate_trend") or {"daily": [], "window_days": 14},
        generated_at=snapshot["generated_at"],
    )


@app.route("/admin/actions/maintenance", methods=["POST"])
def admin_toggle_maintenance():
    if not _has_valid_admin_session():
        abort(403)

    enabled = toggle_maintenance_status()
    status_label = "เปิด" if enabled else "ปิด"
    flash(f"อัปเดต Maintenance Mode เรียบร้อยแล้ว: {status_label}", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/actions/backup", methods=["POST"])
def admin_download_backup():
    if not _has_valid_admin_session():
        abort(403)

    success, filename, zip_buffer, reason = build_local_backup_zip()
    if not success or zip_buffer is None:
        message = "ไม่พบไฟล์ apexify.db บนเครื่องเซิร์ฟเวอร์ จึงดาวน์โหลด local backup ไม่ได้"
        if reason != "not_found":
            message = "ไม่สามารถสร้างไฟล์ backup ได้ในขณะนี้"
        flash(message, "error")
        return redirect(url_for("admin_dashboard"))

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/admin/actions/broadcast", methods=["POST"])
def admin_broadcast():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    msg_text = (request.json or {}).get("message", "").strip()
    audience = (request.json or {}).get("audience", "all")
    if not msg_text:
        return jsonify({"ok": False, "error": "ข้อความว่าง"})

    all_users = get_all_users()
    if audience == "vip_pro":
        from database import check_subscription
        user_ids = [u for u in all_users if check_subscription(u) in ("vip", "pro")]
    elif audience == "pro":
        from database import check_subscription
        user_ids = [u for u in all_users if check_subscription(u) == "pro"]
    else:
        user_ids = all_users

    if str(ADMIN_ID) not in [str(u) for u in user_ids]:
        user_ids = [ADMIN_ID] + list(user_ids)

    result = {"ok": True, "sent": 0, "fail": 0, "total": len(user_ids)}

    def _run():
        s, f = _do_web_broadcast(msg_text, user_ids)
        result["sent"] = s
        result["fail"] = f
        try:
            log_broadcast(audience, len(user_ids), s, f)
        except Exception:
            pass

    t = Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=30)
    return jsonify(result)


@app.route("/admin/actions/add_role", methods=["POST"])
def admin_add_role():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    data = request.json or {}
    user_id = str(data.get("user_id", "")).strip()
    role = data.get("role", "").strip().lower()
    try:
        days = int(data.get("days", 30))
    except (TypeError, ValueError):
        days = 30

    if not user_id or role not in ("vip", "pro"):
        return jsonify({"ok": False, "error": "ข้อมูลไม่ถูกต้อง"})

    try:
        expiry = add_subscription(user_id, role, days)
        return jsonify({"ok": True, "expiry": str(expiry)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/api/user/<user_id>")
def admin_user_lookup(user_id):
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    try:
        info = get_user_info_snapshot(user_id)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    if not info:
        return jsonify({"ok": False, "error": "ไม่พบผู้ใช้"})
    return jsonify({"ok": True, "user": info})


@app.route("/admin/actions/force_briefing", methods=["POST"])
def admin_force_briefing():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    try:
        from alert_system import bot as alert_bot, send_morning_briefing

        def _run():
            try:
                send_morning_briefing(alert_bot, force=True)
            except Exception as e:
                print(f"[Force Briefing] Error: {e}")

        Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True, "message": "Morning Briefing กำลังส่ง..."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/actions/force_podcast", methods=["POST"])
def admin_force_podcast():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    try:
        from alert_system import bot as alert_bot, create_and_send_podcast

        def _run_podcast():
            try:
                asyncio.run(create_and_send_podcast(alert_bot, force=True))
            except Exception as e:
                print(f"[Force Podcast] Error: {e}")

        Thread(target=_run_podcast, daemon=True).start()
        return jsonify({"ok": True, "message": "Podcast กำลังสร้างและส่ง..."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/actions/force_flash_news", methods=["POST"])
def admin_force_flash_news():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    try:
        from alert_system import bot as alert_bot, broadcast_hourly_urgent_news

        def _run():
            try:
                broadcast_hourly_urgent_news(alert_bot, force=True)
            except Exception as e:
                print(f"[Force Flash News] Error: {e}")

        Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True, "message": "Flash News กำลังส่ง..."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/actions/force_digest_news", methods=["POST"])
def admin_force_digest_news():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    try:
        from alert_system import bot as alert_bot, check_and_broadcast_pro_news

        def _run():
            try:
                check_and_broadcast_pro_news(alert_bot, force=True)
            except Exception as e:
                print(f"[Force Digest News] Error: {e}")

        Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True, "message": "Digest News กำลังส่ง..."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/actions/ban_user", methods=["POST"])
def admin_ban_user():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str((request.json or {}).get("user_id", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "ไม่มี user_id"})
    try:
        ban_user(user_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/actions/unban_user", methods=["POST"])
def admin_unban_user():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    user_id = str((request.json or {}).get("user_id", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "ไม่มี user_id"})
    try:
        unban_user(user_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/admin/api/stats")
def admin_api_stats():
    if not _has_valid_admin_session():
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    try:
        stats = get_dashboard_stats()
        return jsonify({"ok": True, **stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


_webhook_bot = None  # จะถูก set จาก main.py


def set_webhook_bot(bot_instance):
    global _webhook_bot
    _webhook_bot = bot_instance


@app.route(f"/webhook/<secret>", methods=["POST"])
def webhook_handler(secret):
    """รับ update จาก Telegram webhook"""
    if _webhook_bot is None:
        return "bot not ready", 503
    # ตรวจ secret ป้องกันคนนอกยิง request เข้ามา
    expected = (TELEGRAM_TOKEN or "").split(":")[-1]
    if secret != expected:
        abort(403)
    import telebot
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    _webhook_bot.process_new_updates([update])
    return "ok", 200


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = Thread(target=run, daemon=True)
    thread.start()
