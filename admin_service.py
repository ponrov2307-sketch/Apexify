import io
import os
import time
import zipfile
from datetime import datetime, timedelta

import psutil
import yfinance as yf

from database import (
    check_subscription,
    get_connection,
    get_due_pending_alert_logs,
    get_recent_alert_logs,
    resolve_alert_log,
)

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


def _coerce_datetime(value):
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19] if fmt.endswith("%S") else raw[:10], fmt)
        except ValueError:
            continue
    return None


def _format_horizon_label(hours):
    try:
        horizon_hours = int(hours)
    except (TypeError, ValueError):
        return "-"
    if horizon_hours % 24 == 0:
        days = horizon_hours // 24
        return f"{days}d" if days > 0 else "0d"
    return f"{horizon_hours}h"


def _format_status_label(status):
    normalized = str(status or "pending").strip().lower()
    if normalized == "win":
        return "WIN"
    if normalized == "loss":
        return "LOSS"
    return "PENDING"


def _get_alert_price_histories(logs):
    if not logs:
        return {}

    grouped = {}
    for item in logs:
        symbol = _normalize_symbol(item.get("symbol"))
        start_dt = _coerce_datetime(item.get("timestamp")) or datetime.now() - timedelta(days=5)
        due_dt = _coerce_datetime(item.get("evaluation_due_at")) or (datetime.now() + timedelta(days=1))
        bucket = grouped.setdefault(symbol, {"start": start_dt, "end": due_dt})
        if start_dt < bucket["start"]:
            bucket["start"] = start_dt
        if due_dt > bucket["end"]:
            bucket["end"] = due_dt

    histories = {}
    for symbol, window in grouped.items():
        try:
            history = yf.Ticker(symbol).history(
                start=(window["start"] - timedelta(days=2)).date().isoformat(),
                end=(window["end"] + timedelta(days=3)).date().isoformat(),
                auto_adjust=False,
            )
            if not history.empty:
                histories[symbol] = history
        except Exception:
            continue
    return histories


def _resolve_due_alert_logs():
    pending_logs = get_due_pending_alert_logs(limit=200)
    histories = _get_alert_price_histories(pending_logs)

    for item in pending_logs:
        symbol = _normalize_symbol(item.get("symbol"))
        history = histories.get(symbol)
        if history is None or history.empty:
            continue

        start_price = float(item.get("price_at_alert") or 0)
        if start_price <= 0:
            continue

        due_dt = _coerce_datetime(item.get("evaluation_due_at"))
        alert_dt = _coerce_datetime(item.get("timestamp"))
        if due_dt is None or alert_dt is None:
            continue

        resolution_row = None
        resolution_index = None
        for idx, row in history.iterrows():
            idx_dt = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if hasattr(idx_dt, "tzinfo") and idx_dt.tzinfo is not None:
                idx_dt = idx_dt.replace(tzinfo=None)
            if idx_dt.date() >= due_dt.date():
                resolution_row = row
                resolution_index = idx_dt
                break

        if resolution_row is None or resolution_index is None:
            continue

        window = history.loc[alert_dt.date().isoformat():resolution_index.date().isoformat()]
        if window.empty:
            continue

        resolved_price = float(resolution_row.get("Close", start_price))
        raw_return_pct = ((resolved_price - start_price) / start_price) * 100
        direction = str(item.get("direction") or "up").lower()
        edge_pct = raw_return_pct if direction == "up" else -raw_return_pct

        max_high = float(window["High"].max()) if "High" in window else resolved_price
        min_low = float(window["Low"].min()) if "Low" in window else resolved_price
        if direction == "up":
            max_favorable_pct = ((max_high - start_price) / start_price) * 100
            max_adverse_pct = max(0.0, ((start_price - min_low) / start_price) * 100)
        else:
            max_favorable_pct = ((start_price - min_low) / start_price) * 100
            max_adverse_pct = max(0.0, ((max_high - start_price) / start_price) * 100)

        status = "win" if edge_pct > 0 else "loss"
        resolve_alert_log(
            item["id"],
            resolved_price=resolved_price,
            resolved_at=resolution_index,
            status=status,
            raw_return_pct=raw_return_pct,
            edge_pct=edge_pct,
            max_favorable_pct=max_favorable_pct,
            max_adverse_pct=max_adverse_pct,
        )


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


def get_top_watched_symbols_snapshot(limit=8):
    row_limit = max(1, int(limit))
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM user_watchlist")
        total_watch_entries = int(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT COUNT(DISTINCT ticker) FROM user_watchlist")
        unique_symbols = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT ticker, COUNT(*) AS watcher_count
            FROM user_watchlist
            GROUP BY ticker
            ORDER BY watcher_count DESC, ticker ASC
            LIMIT %s
            """,
            (row_limit,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    items = [{"symbol": str(symbol), "watchers": int(watcher_count)} for symbol, watcher_count in rows]
    return {
        "total_watch_entries": total_watch_entries,
        "unique_symbols": unique_symbols,
        "items": items,
    }


def get_expiring_members_snapshot(limit=8):
    row_limit = max(1, int(limit))
    now = datetime.now()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT user_id, role, expiry_date FROM users WHERE role IN ('pro', 'vip') ORDER BY expiry_date ASC"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    expiring_items = []
    expiring_3_days = 0
    expiring_7_days = 0
    revenue_at_risk_7_days = 0

    for user_id, role, expiry in rows:
        active_role = check_subscription(user_id)
        if active_role not in ("vip", "pro"):
            continue

        expiry_dt = _coerce_datetime(expiry)
        if expiry_dt is None:
            continue

        days_left = max(0, int((expiry_dt - now).total_seconds() // 86400))
        if expiry_dt < now:
            continue

        if days_left <= 3:
            expiring_3_days += 1
        if days_left <= 7:
            expiring_7_days += 1
            revenue_at_risk_7_days += PRO_MONTHLY_PRICE if str(role) == "pro" else VIP_MONTHLY_PRICE

        if days_left <= 7:
            expiring_items.append(
                {
                    "user_id": str(user_id),
                    "role": str(role),
                    "expiry_date": _format_expiry_date(expiry_dt),
                    "days_left": days_left,
                }
            )

    expiring_items.sort(key=lambda item: (item["days_left"], item["role"], item["user_id"]))
    return {
        "expiring_3_days": expiring_3_days,
        "expiring_7_days": expiring_7_days,
        "revenue_at_risk_7_days": revenue_at_risk_7_days,
        "items": expiring_items[:row_limit],
    }


def get_active_price_alerts_snapshot(limit=8):
    row_limit = max(1, int(limit))
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM user_price_alerts WHERE is_active = 1")
        total_alerts = int(cursor.fetchone()[0] or 0)

        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_price_alerts WHERE is_active = 1")
        unique_users = int(cursor.fetchone()[0] or 0)

        cursor.execute(
            """
            SELECT symbol, COUNT(*) AS alert_count
            FROM user_price_alerts
            WHERE is_active = 1
            GROUP BY symbol
            ORDER BY alert_count DESC, symbol ASC
            LIMIT %s
            """,
            (row_limit,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    items = [{"symbol": str(symbol), "alerts": int(alert_count)} for symbol, alert_count in rows]
    return {
        "total_alerts": total_alerts,
        "unique_users": unique_users,
        "items": items,
    }


def get_notification_settings_snapshot():
    digest_buckets = {1: 0, 4: 0, 8: 0, 24: 0}

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN notifications_enabled = FALSE THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN news_start_hour <> 7 OR news_end_hour <> 22 THEN 1 ELSE 0 END), 0)
            FROM user_settings
            """
        )
        total_settings, notifications_off, custom_windows = cursor.fetchone()

        cursor.execute(
            """
            SELECT digest_frequency_hours, COUNT(*)
            FROM user_settings
            GROUP BY digest_frequency_hours
            ORDER BY digest_frequency_hours ASC
            """
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    for frequency, count in rows:
        try:
            digest_buckets[int(frequency)] = int(count)
        except (TypeError, ValueError):
            continue

    distribution = [
        {"label": "1h", "count": digest_buckets[1]},
        {"label": "4h", "count": digest_buckets[4]},
        {"label": "8h", "count": digest_buckets[8]},
        {"label": "24h", "count": digest_buckets[24]},
    ]

    return {
        "total_settings": int(total_settings or 0),
        "notifications_off": int(notifications_off or 0),
        "custom_windows": int(custom_windows or 0),
        "distribution": distribution,
    }


def get_performance_snapshot(limit=15):
    row_limit = max(1, int(limit))
    summary_limit = max(60, row_limit * 4)

    _resolve_due_alert_logs()
    logs = get_recent_alert_logs(limit=summary_limit)

    entries = []
    breakdown = {}
    win_count = 0
    loss_count = 0
    pending_count = 0
    resolved_count = 0
    edge_sum = 0.0

    for item in logs:
        status = str(item.get("status") or "pending").lower()
        direction = str(item.get("direction") or "up").lower()
        horizon_label = _format_horizon_label(item.get("horizon_hours"))
        alert_type_label = str(item.get("alert_type") or "").replace("_", " ")
        alert_time = _coerce_datetime(item.get("timestamp"))
        due_time = _coerce_datetime(item.get("evaluation_due_at"))
        resolved_time = _coerce_datetime(item.get("resolved_at"))
        resolved_price = item.get("resolved_price")
        raw_return_pct = item.get("return_pct")
        edge_pct = item.get("edge_pct")
        max_favorable_pct = item.get("max_favorable_pct")
        max_adverse_pct = item.get("max_adverse_pct")

        if status == "pending":
            pending_count += 1
        else:
            resolved_count += 1
            if status == "win":
                win_count += 1
            else:
                loss_count += 1
            try:
                edge_sum += float(edge_pct or 0.0)
            except (TypeError, ValueError):
                pass

            bucket = breakdown.setdefault(
                alert_type_label,
                {
                    "alert_type": alert_type_label,
                    "resolved_count": 0,
                    "win_count": 0,
                    "edge_sum": 0.0,
                    "horizon_label": horizon_label,
                },
            )
            bucket["resolved_count"] += 1
            if status == "win":
                bucket["win_count"] += 1
            bucket["edge_sum"] += float(edge_pct or 0.0)

        if len(entries) < row_limit:
            entries.append(
                {
                    "symbol": str(item.get("symbol") or ""),
                    "alert_type": alert_type_label,
                    "start_price": float(item.get("price_at_alert") or 0.0),
                    "current_price": float(resolved_price or 0.0) if resolved_price is not None else None,
                    "diff_pct": float(edge_pct or 0.0) if edge_pct is not None else None,
                    "raw_return_pct": float(raw_return_pct or 0.0) if raw_return_pct is not None else None,
                    "is_win": status == "win",
                    "status": status,
                    "status_label": _format_status_label(status),
                    "timestamp": alert_time.strftime("%Y-%m-%d %H:%M") if alert_time else str(item.get("timestamp") or "-"),
                    "evaluation_due_at": due_time.strftime("%Y-%m-%d %H:%M") if due_time else "-",
                    "resolved_at": resolved_time.strftime("%Y-%m-%d %H:%M") if resolved_time else "-",
                    "horizon_label": horizon_label,
                    "direction_label": "Bullish" if direction == "up" else "Bearish",
                    "max_favorable_pct": float(max_favorable_pct or 0.0) if max_favorable_pct is not None else None,
                    "max_adverse_pct": float(max_adverse_pct or 0.0) if max_adverse_pct is not None else None,
                }
            )

    breakdown_items = []
    for bucket in breakdown.values():
        resolved = int(bucket["resolved_count"] or 0)
        win_total = int(bucket["win_count"] or 0)
        breakdown_items.append(
            {
                "alert_type": bucket["alert_type"],
                "resolved_count": resolved,
                "win_rate": (win_total / resolved * 100) if resolved else 0.0,
                "average_edge_pct": (bucket["edge_sum"] / resolved) if resolved else 0.0,
                "horizon_label": bucket["horizon_label"],
            }
        )

    breakdown_items.sort(
        key=lambda item: (-item["resolved_count"], -item["win_rate"], item["alert_type"])
    )

    win_rate = (win_count / resolved_count * 100) if resolved_count else 0.0
    average_edge_pct = (edge_sum / resolved_count) if resolved_count else 0.0
    return {
        "entries": entries,
        "win_count": win_count,
        "loss_count": loss_count,
        "pending_count": pending_count,
        "resolved_count": resolved_count,
        "total_count": resolved_count,
        "sample_size": len(logs),
        "win_rate": win_rate,
        "average_edge_pct": average_edge_pct,
        "breakdown": breakdown_items[:6],
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


def get_user_info_snapshot(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, role, expiry_date, status, registered_date FROM users WHERE user_id=%s",
        (str(user_id),)
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    uid, uname, role, expiry, status, reg_date = row
    cur.execute("SELECT COUNT(*) FROM user_watchlist WHERE user_id=%s", (str(user_id),))
    watchlist_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM portfolios WHERE user_id=%s", (str(user_id),))
    portfolio_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM price_alerts WHERE user_id=%s AND active=TRUE", (str(user_id),))
    alert_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {
        "user_id": uid,
        "username": uname or "Unknown",
        "role": role or "free",
        "expiry_date": str(expiry) if expiry else None,
        "status": status or "active",
        "registered_date": str(reg_date) if reg_date else None,
        "watchlist_count": watchlist_count,
        "portfolio_count": portfolio_count,
        "active_alerts": alert_count,
    }


def get_admin_dashboard_snapshot(limit=15):
    return {
        "maintenance": get_maintenance_snapshot(),
        "system_health": get_system_health_snapshot(),
        "user_stats": get_user_stats_snapshot(),
        "performance": get_performance_snapshot(limit=limit),
        "paid_users": get_paid_users_snapshot(),
        "top_watched": get_top_watched_symbols_snapshot(),
        "expiring_members": get_expiring_members_snapshot(),
        "price_alerts": get_active_price_alerts_snapshot(),
        "notification_settings": get_notification_settings_snapshot(),
        "generated_at": datetime.now(),
    }
