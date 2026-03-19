import io
import os
import time
import zipfile
from datetime import datetime

import psutil
import yfinance as yf

from database import check_subscription, get_connection

ALLOWED_SYMBOL_SUFFIXES = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
VIP_MONTHLY_PRICE = 299
PRO_MONTHLY_PRICE = 499
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_MAINTENANCE_MODE = False


def get_maintenance_status():
    return _MAINTENANCE_MODE


def set_maintenance_status(enabled):
    global _MAINTENANCE_MODE
    _MAINTENANCE_MODE = bool(enabled)
    return _MAINTENANCE_MODE


def toggle_maintenance_status():
    global _MAINTENANCE_MODE
    _MAINTENANCE_MODE = not _MAINTENANCE_MODE
    return _MAINTENANCE_MODE


def get_maintenance_snapshot():
    enabled = get_maintenance_status()
    return {
        "enabled": enabled,
        "label": "เปิด" if enabled else "ปิด",
        "description": (
            "ผู้ใช้ทั่วไปใช้งานไม่ได้ แต่แอดมินยังใช้งานได้"
            if enabled
            else "ระบบเปิดใช้งานตามปกติ"
        ),
    }


def get_system_health_snapshot():
    cpu_usage = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    uptime_seconds = max(0, int(time.time() - psutil.boot_time()))

    return {
        "cpu_usage": cpu_usage,
        "ram_total_gb": ram.total / (1024 ** 3),
        "ram_used_gb": ram.used / (1024 ** 3),
        "ram_percent": ram.percent,
        "disk_percent": disk.percent,
        "uptime_hours": uptime_seconds // 3600,
        "uptime_seconds": uptime_seconds,
    }


def get_user_stats_snapshot():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM users")
        all_users = cursor.fetchall()
    finally:
        conn.close()

    stats = {"free": 0, "vip": 0, "pro": 0}
    for row in all_users:
        uid = row[0]
        actual_role = check_subscription(uid)
        stats[actual_role] = stats.get(actual_role, 0) + 1

    total = len(all_users)
    estimated_revenue = (stats.get("vip", 0) * VIP_MONTHLY_PRICE) + (stats.get("pro", 0) * PRO_MONTHLY_PRICE)

    return {
        "total_users": total,
        "free_users": stats.get("free", 0),
        "vip_users": stats.get("vip", 0),
        "pro_users": stats.get("pro", 0),
        "estimated_monthly_revenue": estimated_revenue,
    }


def _normalize_symbol(symbol):
    raw = str(symbol or "").strip().upper()
    if "." in raw and not raw.endswith(ALLOWED_SYMBOL_SUFFIXES):
        return raw.replace(".", "-")
    return raw


def _format_expiry_date(expiry):
    if expiry is None:
        return "-"
    if hasattr(expiry, "strftime"):
        return expiry.strftime("%Y-%m-%d")
    return str(expiry)[:10]


def get_paid_users_snapshot():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT user_id, role, expiry_date FROM users WHERE role IN ('pro', 'vip') ORDER BY role DESC, expiry_date ASC"
        )
        users_list = cursor.fetchall()
    finally:
        conn.close()

    items = []
    for uid, role, expiry in users_list:
        active_role = check_subscription(uid)
        items.append(
            {
                "user_id": str(uid),
                "role": str(role),
                "expiry_date": _format_expiry_date(expiry),
                "is_active": active_role in ("pro", "vip"),
                "status_label": "Active" if active_role in ("pro", "vip") else "Expired",
            }
        )

    return items


def get_performance_snapshot(limit=15):
    row_limit = max(1, int(limit))
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT symbol, alert_type, price_at_alert, timestamp FROM alert_logs ORDER BY id DESC LIMIT %s",
            (row_limit,),
        )
        logs = cursor.fetchall()
    finally:
        conn.close()

    entries = []
    win_count = 0
    total_count = 0

    for symbol, alert_type, start_price, timestamp in logs:
        try:
            ticker = yf.Ticker(_normalize_symbol(symbol))
            history = ticker.history(period="1d")
            if history.empty:
                continue

            current_price = float(history["Close"].iloc[-1])
            diff_pct = ((current_price - float(start_price)) / float(start_price)) * 100

            is_win = False
            display_diff_pct = diff_pct
            upper_type = str(alert_type or "").upper()
            if any(token in upper_type for token in ("OVERSOLD", "GOLDEN_CROSS", "BREAK_RES")):
                if diff_pct > 0:
                    is_win = True
            elif any(token in upper_type for token in ("OVERBOUGHT", "DEATH_CROSS", "BREAK_SUP")):
                if diff_pct < 0:
                    is_win = True
                display_diff_pct = -diff_pct

            if is_win:
                win_count += 1
            total_count += 1

            entries.append(
                {
                    "symbol": str(symbol),
                    "alert_type": str(alert_type).replace("_", " "),
                    "start_price": float(start_price),
                    "current_price": current_price,
                    "diff_pct": display_diff_pct,
                    "is_win": is_win,
                    "timestamp": str(timestamp),
                }
            )
        except Exception:
            continue

    win_rate = (win_count / total_count * 100) if total_count else 0.0
    return {
        "entries": entries,
        "win_count": win_count,
        "total_count": total_count,
        "win_rate": win_rate,
    }


def build_local_backup_zip():
    db_filename = os.path.join(BASE_DIR, "apexify.db")
    if not os.path.exists(db_filename):
        return False, "", None, "not_found"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"apexify_backup_{timestamp}.zip"
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.write(db_filename, arcname="apexify.db")

    zip_buffer.seek(0)
    zip_buffer.name = zip_filename
    return True, zip_filename, zip_buffer, "ok"


def get_admin_dashboard_snapshot(limit=15):
    return {
        "maintenance": get_maintenance_snapshot(),
        "system_health": get_system_health_snapshot(),
        "user_stats": get_user_stats_snapshot(),
        "performance": get_performance_snapshot(limit=limit),
        "paid_users": get_paid_users_snapshot(),
        "generated_at": datetime.now(),
    }
