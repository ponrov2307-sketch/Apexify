import os
import time
from threading import Thread

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

from admin_service import build_local_backup_zip, get_admin_dashboard_snapshot, toggle_maintenance_status
from config import ADMIN_ID, BOT_WEB_BASE_URL, DASHBOARD_LOGIN_SECRET, FLASK_SECRET_KEY
from dashboard_login import verify_admin_dashboard_token

app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY or DASHBOARD_LOGIN_SECRET or os.urandom(32)
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
            body { font-family: Arial, sans-serif; background: #f7f1e8; color: #2c241b; display: grid; place-items: center; min-height: 100vh; margin: 0; }
            .card { max-width: 420px; background: #fffaf2; border: 1px solid #e3d4bf; border-radius: 18px; padding: 28px; box-shadow: 0 20px 50px rgba(64, 44, 16, 0.12); }
            h1 { margin-top: 0; font-size: 28px; }
            p { line-height: 1.5; margin-bottom: 0; }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Access denied</h1>
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

    snapshot = get_admin_dashboard_snapshot(limit=15)
    return render_template(
        "admin_dashboard.html",
        admin_id=str(ADMIN_ID or "").strip(),
        maintenance=snapshot["maintenance"],
        system_health=snapshot["system_health"],
        user_stats=snapshot["user_stats"],
        performance=snapshot["performance"],
        paid_users=snapshot["paid_users"],
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


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = Thread(target=run, daemon=True)
    thread.start()
