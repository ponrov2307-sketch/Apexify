import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import RLock

import psutil
import yfinance as yf
from cachetools import TTLCache

from database import (
    check_subscription,
    get_connection,
    get_due_pending_alert_logs,
    get_recent_alert_logs,
    resolve_alert_log,
)

ALLOWED_SYMBOL_SUFFIXES = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
VIP_MONTHLY_PRICE = 79
PRO_MONTHLY_PRICE = 109
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🌟 Dashboard snapshot cache — ลด DB query + yfinance ซ้ำ
# ถ้าหลายคนเปิด admin dashboard ในเวลาใกล้กัน หรือ refresh — instant
_dashboard_snapshot_cache = TTLCache(maxsize=4, ttl=45)
_dashboard_cache_lock = RLock()
_dashboard_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="dash")

# 🌟 Stats สำหรับ admin debug
_dashboard_metrics = {
    "snapshot_cache_hits": 0,
    "snapshot_cache_misses": 0,
    "last_build_seconds": 0.0,
}

# 🌟 Maintenance mode — persisted in `system_state` table so toggle survives restart
_MAINTENANCE_MODE = False
_MAINTENANCE_LOADED = False


def _ensure_system_state_table():
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    except Exception as e:
        print(f"[system_state init] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def _load_maintenance_from_db():
    global _MAINTENANCE_MODE, _MAINTENANCE_LOADED
    _ensure_system_state_table()
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM system_state WHERE key = 'maintenance_mode'")
        row = c.fetchone()
        if row:
            _MAINTENANCE_MODE = (str(row[0]).lower() == 'true')
    except Exception as e:
        print(f"[load maintenance] {e}", flush=True)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    _MAINTENANCE_LOADED = True


def _persist_maintenance(enabled):
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO system_state (key, value, updated_at)
            VALUES ('maintenance_mode', %s, NOW())
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """,
            ('true' if enabled else 'false',),
        )
        conn.commit()
    except Exception as e:
        print(f"[persist maintenance] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def get_maintenance_status():
    if not _MAINTENANCE_LOADED:
        _load_maintenance_from_db()
    return _MAINTENANCE_MODE


def set_maintenance_status(enabled):
    global _MAINTENANCE_MODE, _MAINTENANCE_LOADED
    _MAINTENANCE_MODE = bool(enabled)
    _MAINTENANCE_LOADED = True
    _persist_maintenance(_MAINTENANCE_MODE)
    return _MAINTENANCE_MODE


def toggle_maintenance_status():
    return set_maintenance_status(not get_maintenance_status())


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
    """🌟 1 query แทน N+1 — fetch role+expiry ทีเดียวแล้วคำนวณใน Python
    เก่า: SELECT user_id × 1 + check_subscription × N (= 1+N queries)
    ใหม่: SELECT user_id, role, expiry_date × 1 (= 1 query)
    """
    from datetime import datetime as _dt
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, role, expiry_date FROM users")
        rows = cursor.fetchall()
    finally:
        conn.close()

    # admin = pro เสมอ (สอดคล้อง check_subscription)
    admin_id = None
    try:
        from config import ADMIN_ID as _ADMIN_ID
        admin_id = str(_ADMIN_ID) if _ADMIN_ID else None
    except Exception:
        pass

    now = _dt.now()
    stats = {"free": 0, "vip": 0, "pro": 0}
    for uid, role, expiry in rows:
        if admin_id and str(uid) == admin_id:
            stats["pro"] += 1
            continue
        actual = "free"
        if role in ("vip", "pro") and expiry is not None:
            try:
                if isinstance(expiry, _dt):
                    exp = expiry.replace(tzinfo=None)
                else:
                    raw = str(expiry).strip().replace("T", " ")
                    exp = _dt.fromisoformat(raw).replace(tzinfo=None)
                if now < exp:
                    actual = role
            except (ValueError, TypeError):
                pass
        stats[actual] = stats.get(actual, 0) + 1

    total = len(rows)
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
            "SELECT user_id, role, expiry_date, username, last_active, status FROM users WHERE role IN ('pro', 'vip') ORDER BY role DESC, expiry_date ASC"
        )
        users_list = cursor.fetchall()
    finally:
        conn.close()

    items = []
    for uid, role, expiry, uname, last_active, status in users_list:
        active_role = check_subscription(uid)
        if active_role not in ("pro", "vip"):
            continue
        la_str = ""
        if last_active:
            la_str = last_active.strftime("%Y-%m-%d %H:%M") if hasattr(last_active, 'strftime') else str(last_active)[:16]
        items.append(
            {
                "user_id": str(uid),
                "username": uname or "Unknown",
                "role": str(role),
                "expiry_date": _format_expiry_date(expiry),
                "is_active": True,
                "status_label": "Active",
                "last_active": la_str,
                "bot_status": status or "active",
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
    """🌟 ลบ N+1 — ใช้ role+expiry ที่ fetch มาแล้วคำนวณ active เอง (สอดคล้อง check_subscription)"""
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
        # active = role ∈ {vip,pro} + expiry > now (เหมือน check_subscription แต่ไม่ query DB ซ้ำ)
        if role not in ("vip", "pro") or expiry is None:
            continue

        expiry_dt = _coerce_datetime(expiry)
        if expiry_dt is None or expiry_dt < now:
            continue

        days_left = max(0, int((expiry_dt - now).total_seconds() // 86400))

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


def get_performance_snapshot(limit=15, resolve_pending=True):
    """🌟 resolve_pending=False ข้าม yfinance fetch (ใช้ใน hot dashboard load)
    Background thread จะ resolve เป็นช่วงๆ ผ่าน resolve_due_alerts_background()
    """
    row_limit = max(1, int(limit))
    summary_limit = max(60, row_limit * 4)

    if resolve_pending:
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


def get_recent_activity_snapshot(limit=8):
    """Live activity feed — recent signups + recent payment slips
    เพื่อให้ admin เห็น 'อะไรเกิดขึ้นล่าสุด' โดยไม่ต้อง refresh page บ่อย
    """
    conn = get_connection()
    c = conn.cursor()
    signups = []
    payments = []
    try:
        c.execute(
            """
            SELECT user_id, username, role, registered_date
            FROM users
            WHERE registered_date IS NOT NULL
            ORDER BY registered_date DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        for row in c.fetchall():
            uid, uname, role, reg_dt = row
            signups.append({
                "user_id": str(uid),
                "username": (uname or "Unknown")[:24],
                "role": (role or "free").lower(),
                "ts": reg_dt.strftime("%m-%d %H:%M") if hasattr(reg_dt, "strftime") else str(reg_dt)[:16],
            })

        c.execute(
            """
            SELECT s.ref_no, s.user_id, u.username, u.role, s.date_used
            FROM used_slips s
            LEFT JOIN users u ON u.user_id = s.user_id
            WHERE s.date_used IS NOT NULL
            ORDER BY s.date_used DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        for row in c.fetchall():
            ref, uid, uname, role, dt = row
            payments.append({
                "ref_no": str(ref or "")[:14],
                "user_id": str(uid or ""),
                "username": (uname or "Unknown")[:20],
                "role": (role or "free").lower(),
                "ts": str(dt)[:16] if dt else "—",
            })
    except Exception as exc:
        print(f"[recent_activity] {exc}", flush=True)
    finally:
        conn.close()
    return {"signups": signups, "payments": payments}


def get_hourly_activity_snapshot(days=7):
    """24-hour heatmap of last_active (Bangkok TZ) over last N days
    ใช้ดูว่า user ส่วนใหญ่ active กี่โมง — ตัดสินใจเรื่อง broadcast timing
    """
    conn = get_connection()
    c = conn.cursor()
    counts = [0] * 24
    total_active = 0
    try:
        c.execute(
            """
            SELECT EXTRACT(HOUR FROM (last_active AT TIME ZONE 'Asia/Bangkok'))::int AS h,
                   COUNT(*)
            FROM users
            WHERE last_active IS NOT NULL
              AND last_active >= NOW() - (INTERVAL '1 day' * %s)
            GROUP BY h
            ORDER BY h
            """,
            (int(days),),
        )
        for row in c.fetchall():
            h, cnt = row
            if h is not None and 0 <= int(h) < 24:
                counts[int(h)] = int(cnt or 0)
                total_active += int(cnt or 0)
    except Exception as exc:
        print(f"[hourly_activity] {exc}", flush=True)
    finally:
        conn.close()
    peak_count = max(counts) if any(counts) else 1
    peak_hour = counts.index(peak_count) if peak_count > 0 else None
    return {
        "hours": counts,
        "max": peak_count,
        "peak_hour": peak_hour,
        "total_active": total_active,
        "window_days": int(days),
    }


def get_funnel_snapshot():
    """Conversion funnel + churn — top-of-mind metrics สำหรับ SaaS owner
    total → active 30d → paying → (churn 30d)
    """
    conn = get_connection()
    c = conn.cursor()
    funnel = {
        "total_users": 0,
        "active_30d": 0,
        "active_7d": 0,
        "paying_now": 0,
        "vip_now": 0,
        "pro_now": 0,
        "churned_30d": 0,
        "new_30d": 0,
        "new_7d": 0,
        "conversion_pct": 0.0,
        "active_rate_pct": 0.0,
    }
    try:
        c.execute("SELECT COUNT(*) FROM users")
        funnel["total_users"] = int(c.fetchone()[0] or 0)

        c.execute("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '30 days'")
        funnel["active_30d"] = int(c.fetchone()[0] or 0)

        c.execute("SELECT COUNT(*) FROM users WHERE last_active >= NOW() - INTERVAL '7 days'")
        funnel["active_7d"] = int(c.fetchone()[0] or 0)

        # 🐛 expiry_date เป็น TEXT ใน schema → ต้อง cast ก่อนเทียบกับ NOW() ไม่งั้นเทียบเป็น string ผิด
        c.execute(
            """
            SELECT role, COUNT(*) FROM users
            WHERE role IN ('vip','pro')
              AND (expiry_date IS NULL OR expiry_date::timestamp > NOW())
            GROUP BY role
            """
        )
        for row in c.fetchall():
            r, cnt = row
            if r == "vip":
                funnel["vip_now"] = int(cnt or 0)
            elif r == "pro":
                funnel["pro_now"] = int(cnt or 0)
        funnel["paying_now"] = funnel["vip_now"] + funnel["pro_now"]

        # Churned — paid users whose subscription expired in last 30 days
        c.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role IN ('vip','pro')
              AND expiry_date IS NOT NULL
              AND expiry_date::timestamp < NOW()
              AND expiry_date::timestamp >= NOW() - INTERVAL '30 days'
            """
        )
        funnel["churned_30d"] = int(c.fetchone()[0] or 0)

        c.execute("SELECT COUNT(*) FROM users WHERE registered_date >= NOW() - INTERVAL '30 days'")
        funnel["new_30d"] = int(c.fetchone()[0] or 0)

        c.execute("SELECT COUNT(*) FROM users WHERE registered_date >= NOW() - INTERVAL '7 days'")
        funnel["new_7d"] = int(c.fetchone()[0] or 0)

        if funnel["total_users"]:
            funnel["conversion_pct"] = round(funnel["paying_now"] / funnel["total_users"] * 100, 2)
            funnel["active_rate_pct"] = round(funnel["active_30d"] / funnel["total_users"] * 100, 2)
    except Exception as exc:
        print(f"[funnel] {exc}", flush=True)
    finally:
        conn.close()
    return funnel


def get_top_commands_snapshot(days=7, limit=12):
    """Top N commands พิมพ์มากสุดใน last N days
    ต้อง wire log_command() ใน main.py message dispatcher ก่อน table จะมี data
    """
    conn = get_connection()
    c = conn.cursor()
    items = []
    total = 0
    try:
        c.execute(
            """
            SELECT command, COUNT(*) AS n
            FROM bot_command_log
            WHERE ts >= NOW() - (INTERVAL '1 day' * %s)
            GROUP BY command
            ORDER BY n DESC
            LIMIT %s
            """,
            (int(days), int(limit)),
        )
        for row in c.fetchall():
            items.append({"command": str(row[0] or "")[:24], "count": int(row[1] or 0)})
        total = sum(it["count"] for it in items)
    except Exception as exc:
        print(f"[top_commands] {exc}", flush=True)
    finally:
        conn.close()
    return {"items": items, "total": total, "window_days": int(days)}


def get_alert_delivery_snapshot(days=7):
    """Broadcast/alert delivery rate — total/success/fail per batch over last N days"""
    conn = get_connection()
    c = conn.cursor()
    batches = []
    totals = {"total": 0, "success": 0, "fail": 0, "batches": 0}
    daily = []
    try:
        c.execute(
            """
            SELECT id, audience, total, success, fail, ts
            FROM broadcast_log
            WHERE ts >= NOW() - (INTERVAL '1 day' * %s)
            ORDER BY ts DESC
            LIMIT 30
            """,
            (int(days),),
        )
        for row in c.fetchall():
            bid, aud, tot, succ, fl, ts = row
            t = int(tot or 0)
            s = int(succ or 0)
            f = int(fl or 0)
            batches.append({
                "id": int(bid or 0),
                "audience": str(aud or "")[:24],
                "total": t,
                "success": s,
                "fail": f,
                "success_rate": round((s / t * 100), 1) if t else 0.0,
                "ts": ts.strftime("%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)[:16],
            })
            totals["total"] += t
            totals["success"] += s
            totals["fail"] += f
        totals["batches"] = len(batches)
        totals["success_rate"] = round((totals["success"] / totals["total"] * 100), 1) if totals["total"] else 0.0

        # Daily aggregation for trend chart
        c.execute(
            """
            SELECT date_trunc('day', ts)::date AS d, SUM(total) AS t, SUM(success) AS s, SUM(fail) AS f
            FROM broadcast_log
            WHERE ts >= NOW() - (INTERVAL '1 day' * %s)
            GROUP BY d
            ORDER BY d
            """,
            (int(days),),
        )
        for row in c.fetchall():
            d, t, s, f = row
            t = int(t or 0); s = int(s or 0); f = int(f or 0)
            daily.append({
                "date": str(d),
                "total": t,
                "success": s,
                "fail": f,
                "success_rate": round((s / t * 100), 1) if t else 0.0,
            })
    except Exception as exc:
        print(f"[alert_delivery] {exc}", flush=True)
    finally:
        conn.close()
    return {"batches": batches, "totals": totals, "daily": daily, "window_days": int(days)}


def get_quota_burn_snapshot(quota=3):
    """Free users that hit daily quota today — sign of conversion-ready users
    quota = FREE_DAILY_QUOTA (3) จาก main.py
    """
    conn = get_connection()
    c = conn.cursor()
    snapshot = {"hit_quota": 0, "near_quota": 0, "total_free_active": 0, "burn_rate_pct": 0.0, "top_burners": [], "quota": int(quota)}
    try:
        c.execute("SELECT COUNT(*) FROM users WHERE role = 'free'")
        snapshot["total_free_active"] = int(c.fetchone()[0] or 0)

        c.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'free' AND COALESCE(usage_count, 0) >= %s",
            (int(quota),),
        )
        snapshot["hit_quota"] = int(c.fetchone()[0] or 0)

        c.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'free' AND COALESCE(usage_count, 0) >= %s AND COALESCE(usage_count, 0) < %s",
            (max(int(quota) - 1, 1), int(quota)),
        )
        snapshot["near_quota"] = int(c.fetchone()[0] or 0)

        if snapshot["total_free_active"]:
            snapshot["burn_rate_pct"] = round(snapshot["hit_quota"] / snapshot["total_free_active"] * 100, 2)

        # Top free users approaching/hitting quota — best conversion targets
        c.execute(
            """
            SELECT user_id, username, usage_count, last_active
            FROM users
            WHERE role = 'free' AND COALESCE(usage_count, 0) >= 1
            ORDER BY usage_count DESC, last_active DESC NULLS LAST
            LIMIT 10
            """
        )
        for row in c.fetchall():
            uid, uname, used, la = row
            snapshot["top_burners"].append({
                "user_id": str(uid),
                "username": (uname or "Unknown")[:24],
                "used": int(used or 0),
                "last_active": la.strftime("%m-%d %H:%M") if hasattr(la, "strftime") else (str(la)[:16] if la else "—"),
            })
    except Exception as exc:
        print(f"[quota_burn] {exc}", flush=True)
    finally:
        conn.close()
    return snapshot


def get_win_rate_trend_snapshot(days=14):
    """Daily win/loss counts → frontend computes 7d rolling win rate
    ใช้ alert_logs.resolved_at + status เพื่อ group by date
    """
    conn = get_connection()
    c = conn.cursor()
    daily = []
    try:
        c.execute(
            """
            SELECT
                date_trunc('day', resolved_at)::date AS d,
                SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) AS losses
            FROM alert_logs
            WHERE resolved_at IS NOT NULL
              AND resolved_at >= NOW() - (INTERVAL '1 day' * %s)
              AND status IN ('win', 'loss')
            GROUP BY d
            ORDER BY d
            """,
            (int(days),),
        )
        for row in c.fetchall():
            d, w, l = row
            w = int(w or 0); l = int(l or 0)
            total = w + l
            daily.append({
                "date": str(d),
                "wins": w,
                "losses": l,
                "total": total,
                "win_rate": round((w / total * 100), 1) if total else None,
            })
    except Exception as exc:
        print(f"[win_rate_trend] {exc}", flush=True)
    finally:
        conn.close()
    return {"daily": daily, "window_days": int(days)}


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
        "SELECT user_id, username, role, expiry_date, status, registered_date, last_active FROM users WHERE user_id=%s",
        (str(user_id),)
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    uid, uname, role, expiry, status, reg_date, last_active = row
    cur.execute("SELECT COUNT(*) FROM user_watchlist WHERE user_id=%s", (str(user_id),))
    watchlist_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM portfolios WHERE user_id=%s", (str(user_id),))
    portfolio_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM user_price_alerts WHERE user_id=%s AND is_active=1", (str(user_id),))
    alert_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    la_str = ""
    if last_active:
        la_str = last_active.strftime("%Y-%m-%d %H:%M") if hasattr(last_active, 'strftime') else str(last_active)[:16]
    return {
        "user_id": uid,
        "username": uname or "Unknown",
        "role": role or "free",
        "expiry_date": str(expiry) if expiry else None,
        "status": status or "active",
        "registered_date": str(reg_date) if reg_date else None,
        "last_active": la_str,
        "watchlist_count": watchlist_count,
        "portfolio_count": portfolio_count,
        "active_alerts": alert_count,
    }


def get_webmaster_metrics_snapshot():
    """ApexifyWebmaster metrics — read from same Supabase project as bot.

    Fail-soft: if any of the webmaster tables doesn't exist (e.g. fresh install
    where migrations haven't been applied), returns zeros instead of crashing.
    """
    metrics = {
        # Transaction core
        "tx_total": 0,
        "tx_active_users": 0,
        "tx_this_month": 0,
        "tx_this_week": 0,
        "tx_last_week": 0,
        "tx_growth_wow_pct": 0.0,
        "tx_buy_count": 0,
        "tx_sell_count": 0,
        "tx_with_proof": 0,
        "tx_with_proof_pct": 0.0,
        "tx_proofs_pending_purge": 0,
        "tx_top_tickers": [],
        "tx_top_brokers": [],          # [(broker, count), ...]
        "tx_currency_split": {},       # {"USD": 12, "THB": 4}
        "fees_total_thb": 0.0,
        # Dividends
        "div_total_count": 0,
        "div_total_amount": 0.0,
        # Engagement
        "active_users_7d": 0,
        "active_users_30d": 0,
        # Cross-user portfolios (webmaster uses 'portfolios' table)
        "portfolio_active_users": 0,
        "portfolio_top_held": [],      # [(ticker, holders), ...]
        # Storage usage
        "proof_storage_bytes_total": 0,
        # Realized P&L cache (sum across all users + years)
        "realized_pnl_thb_total": 0.0,
        "realized_pnl_users_count": 0,
        "available": False,
    }
    conn = get_connection()
    if not conn:
        return metrics
    try:
        c = conn.cursor()

        # Transactions table — overall
        try:
            c.execute("SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL")
            metrics["tx_total"] = int(c.fetchone()[0] or 0)
        except Exception:
            conn.rollback()
            return metrics  # transactions table missing → entire metrics off

        metrics["available"] = True

        # Distinct users with at least 1 tx
        c.execute("SELECT COUNT(DISTINCT user_id) FROM transactions WHERE deleted_at IS NULL")
        metrics["tx_active_users"] = int(c.fetchone()[0] or 0)

        # This-month transactions
        c.execute(
            """
            SELECT COUNT(*) FROM transactions
             WHERE deleted_at IS NULL
               AND transaction_date >= date_trunc('month', NOW())
            """
        )
        metrics["tx_this_month"] = int(c.fetchone()[0] or 0)

        # Top tickers (top 8)
        c.execute(
            """
            SELECT ticker, COUNT(*) AS cnt FROM transactions
             WHERE deleted_at IS NULL
             GROUP BY ticker ORDER BY cnt DESC LIMIT 8
            """
        )
        metrics["tx_top_tickers"] = [(r[0], int(r[1])) for r in c.fetchall()]

        # Top brokers (top 5) — empty broker treated as "Manual"
        c.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(broker), ''), 'Manual') AS b, COUNT(*) AS cnt
              FROM transactions WHERE deleted_at IS NULL
             GROUP BY b ORDER BY cnt DESC LIMIT 5
            """
        )
        metrics["tx_top_brokers"] = [(r[0], int(r[1])) for r in c.fetchall()]

        # Buy / Sell breakdown
        c.execute(
            """
            SELECT side, COUNT(*) FROM transactions
             WHERE deleted_at IS NULL
             GROUP BY side
            """
        )
        for side, cnt in c.fetchall():
            if side == "buy":
                metrics["tx_buy_count"] = int(cnt or 0)
            elif side == "sell":
                metrics["tx_sell_count"] = int(cnt or 0)

        # Currency split
        c.execute(
            """
            SELECT UPPER(currency), COUNT(*) FROM transactions
             WHERE deleted_at IS NULL
             GROUP BY UPPER(currency)
            """
        )
        metrics["tx_currency_split"] = {r[0] or "USD": int(r[1] or 0) for r in c.fetchall()}

        # Active webmaster users — last 7 + 30 days
        c.execute(
            """
            SELECT
                SUM(CASE WHEN updated_at >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS d7,
                SUM(CASE WHEN updated_at >= NOW() - INTERVAL '30 days' THEN 1 ELSE 0 END) AS d30
              FROM (SELECT DISTINCT user_id, MAX(updated_at) AS updated_at
                    FROM transactions WHERE deleted_at IS NULL
                    GROUP BY user_id) AS uniq_users
            """
        )
        row = c.fetchone()
        metrics["active_users_7d"] = int(row[0] or 0)
        metrics["active_users_30d"] = int(row[1] or 0)

        # Week-over-week growth (this week vs prev week)
        c.execute(
            """
            SELECT
                SUM(CASE WHEN transaction_date >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS w0,
                SUM(CASE WHEN transaction_date >= NOW() - INTERVAL '14 days'
                          AND transaction_date <  NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) AS w1
              FROM transactions WHERE deleted_at IS NULL
            """
        )
        row = c.fetchone()
        metrics["tx_this_week"] = int(row[0] or 0)
        metrics["tx_last_week"] = int(row[1] or 0)
        if metrics["tx_last_week"] > 0:
            metrics["tx_growth_wow_pct"] = round(
                (metrics["tx_this_week"] - metrics["tx_last_week"]) / metrics["tx_last_week"] * 100, 1
            )
        elif metrics["tx_this_week"] > 0:
            metrics["tx_growth_wow_pct"] = 100.0  # came from zero

        # Total fees (sum) — informational
        c.execute(
            """
            SELECT COALESCE(SUM(fee * COALESCE(fx_rate, 35.5)), 0)
              FROM transactions WHERE deleted_at IS NULL
            """
        )
        metrics["fees_total_thb"] = float(c.fetchone()[0] or 0)

        # Photo proof adoption + storage bytes (only if migration 002 applied)
        try:
            c.execute(
                """
                SELECT
                    SUM(CASE WHEN proof_path IS NOT NULL AND proof_deleted_at IS NULL THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN proof_deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS pending_purge,
                    COALESCE(SUM(CASE WHEN proof_path IS NOT NULL THEN proof_size_bytes ELSE 0 END), 0) AS bytes_used
                  FROM transactions WHERE deleted_at IS NULL
                """
            )
            row = c.fetchone()
            metrics["tx_with_proof"] = int(row[0] or 0)
            metrics["tx_proofs_pending_purge"] = int(row[1] or 0)
            metrics["proof_storage_bytes_total"] = int(row[2] or 0)
            if metrics["tx_total"]:
                metrics["tx_with_proof_pct"] = round(
                    metrics["tx_with_proof"] / metrics["tx_total"] * 100, 1
                )
        except Exception:
            conn.rollback()  # migration 002 not applied — skip proof metrics

        # Dividends table (optional — may not exist on legacy installs)
        try:
            c.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(amount * COALESCE(fx_rate, 35.5)), 0)
                  FROM dividends WHERE deleted_at IS NULL
                """
            )
            row = c.fetchone()
            metrics["div_total_count"] = int(row[0] or 0)
            metrics["div_total_amount"] = float(row[1] or 0)
        except Exception:
            conn.rollback()

        # Cross-user portfolio holdings (webmaster `portfolios` table)
        try:
            c.execute(
                """
                SELECT COUNT(DISTINCT user_id) FROM portfolios
                """
            )
            metrics["portfolio_active_users"] = int(c.fetchone()[0] or 0)
            c.execute(
                """
                SELECT ticker, COUNT(DISTINCT user_id) AS holders
                  FROM portfolios
                 GROUP BY ticker ORDER BY holders DESC LIMIT 8
                """
            )
            metrics["portfolio_top_held"] = [(r[0], int(r[1])) for r in c.fetchall()]
        except Exception:
            conn.rollback()  # portfolios table may not exist or have user_id column

        # Cached realized P&L sum (across all years, all users)
        try:
            c.execute(
                """
                SELECT COUNT(DISTINCT user_id),
                       COALESCE(SUM(realized_pnl_thb), 0)
                  FROM pnl_yearly_cache
                """
            )
            row = c.fetchone()
            metrics["realized_pnl_users_count"] = int(row[0] or 0)
            metrics["realized_pnl_thb_total"] = float(row[1] or 0)
        except Exception:
            conn.rollback()

    except Exception as exc:
        print(f"[webmaster_metrics] {exc}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return metrics


def get_cohort_retention_snapshot(weeks=8):
    """Weekly signup cohorts + their +1w / +2w / +4w retention + paid conversion.

    Helps spot where the funnel breaks:
      - Drop at +1w → onboarding / first-week problem
      - Drop at +2w → product fit
      - Low paid → trial flow / pricing
    """
    rows: list[dict] = []
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            f"""
            WITH cohorts AS (
                SELECT
                    user_id,
                    role,
                    expiry_date,
                    last_active,
                    NULLIF(TRIM(registered_date), '')::timestamp AS reg_ts
                FROM users
                WHERE registered_date IS NOT NULL
                  AND TRIM(registered_date) <> ''
            )
            SELECT
                DATE_TRUNC('week', reg_ts) AS cohort_week,
                COUNT(*) AS signups,
                SUM(CASE WHEN last_active IS NOT NULL
                          AND last_active >= reg_ts + INTERVAL '7 days'
                         THEN 1 ELSE 0 END) AS active_w1,
                SUM(CASE WHEN last_active IS NOT NULL
                          AND last_active >= reg_ts + INTERVAL '14 days'
                         THEN 1 ELSE 0 END) AS active_w2,
                SUM(CASE WHEN last_active IS NOT NULL
                          AND last_active >= reg_ts + INTERVAL '28 days'
                         THEN 1 ELSE 0 END) AS active_w4,
                SUM(CASE WHEN role IN ('vip', 'pro')
                          AND expiry_date IS NOT NULL
                          AND expiry_date::timestamp > NOW()
                         THEN 1 ELSE 0 END) AS paid_now
              FROM cohorts
             WHERE reg_ts >= DATE_TRUNC('week', NOW() - INTERVAL '{int(weeks)} weeks')
             GROUP BY cohort_week
             ORDER BY cohort_week DESC
             LIMIT %s
            """,
            (int(weeks),),
        )
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)
        for cohort_week, signups, w1, w2, w4, paid in c.fetchall():
            signups = int(signups or 0)
            if signups == 0:
                continue
            week_start = cohort_week
            # Mark cells as "—" if not enough time has passed yet
            age_days = (now - week_start.replace(tzinfo=_tz.utc) if week_start.tzinfo is None else now - week_start).days
            row = {
                "cohort_week": week_start.strftime("%Y-%m-%d"),
                "signups": signups,
                "w1": int(w1 or 0) if age_days >= 7 else None,
                "w2": int(w2 or 0) if age_days >= 14 else None,
                "w4": int(w4 or 0) if age_days >= 28 else None,
                "paid": int(paid or 0),
                "w1_pct": round((int(w1 or 0) / signups) * 100, 1) if age_days >= 7 else None,
                "w2_pct": round((int(w2 or 0) / signups) * 100, 1) if age_days >= 14 else None,
                "w4_pct": round((int(w4 or 0) / signups) * 100, 1) if age_days >= 28 else None,
                "paid_pct": round((int(paid or 0) / signups) * 100, 1),
            }
            rows.append(row)
    except Exception as exc:
        print(f"[cohort_retention] {exc}", flush=True)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return {"rows": rows, "weeks": weeks}


def get_admin_dashboard_snapshot(limit=15):
    """🌟 Cache 45s + parallelize 9 sections + skip yfinance ใน hot path

    Performance journey:
    - เก่า: 9 sections sequential + yfinance fetch per pending alert per request (~3-10s)
    - หลัง bug fix: ลบ N+1 queries (~1-2s)
    - ตอนนี้: parallel 9 sections + cache 45s + background yfinance resolve (~0.2-0.5s cold, instant warm)
    """
    cache_key = ("admin_dashboard", int(limit))
    with _dashboard_cache_lock:
        cached = _dashboard_snapshot_cache.get(cache_key)
    if cached is not None:
        _dashboard_metrics["snapshot_cache_hits"] += 1
        return cached

    _dashboard_metrics["snapshot_cache_misses"] += 1
    t0 = time.time()

    # รัน sections พร้อมกันบน thread pool — รวมเวลาเท่ากับ section ที่ช้าที่สุด ไม่ใช่ผลรวม
    futures = {
        "maintenance": _dashboard_executor.submit(get_maintenance_snapshot),
        "system_health": _dashboard_executor.submit(get_system_health_snapshot),
        "user_stats": _dashboard_executor.submit(get_user_stats_snapshot),
        # ⚡ skip yfinance resolve ใน hot path — background loop จัดการให้
        "performance": _dashboard_executor.submit(get_performance_snapshot, limit, False),
        "paid_users": _dashboard_executor.submit(get_paid_users_snapshot),
        "top_watched": _dashboard_executor.submit(get_top_watched_symbols_snapshot),
        "expiring_members": _dashboard_executor.submit(get_expiring_members_snapshot),
        "price_alerts": _dashboard_executor.submit(get_active_price_alerts_snapshot),
        "notification_settings": _dashboard_executor.submit(get_notification_settings_snapshot),
        "recent_activity": _dashboard_executor.submit(get_recent_activity_snapshot),
        "hourly_activity": _dashboard_executor.submit(get_hourly_activity_snapshot),
        "funnel": _dashboard_executor.submit(get_funnel_snapshot),
        "top_commands": _dashboard_executor.submit(get_top_commands_snapshot),
        "alert_delivery": _dashboard_executor.submit(get_alert_delivery_snapshot),
        "quota_burn": _dashboard_executor.submit(get_quota_burn_snapshot),
        "win_rate_trend": _dashboard_executor.submit(get_win_rate_trend_snapshot),
        "webmaster_metrics": _dashboard_executor.submit(get_webmaster_metrics_snapshot),
        "cohort_retention": _dashboard_executor.submit(get_cohort_retention_snapshot),
    }

    snapshot = {}
    for name, future in futures.items():
        try:
            snapshot[name] = future.result(timeout=20)
        except Exception as exc:
            print(f"[dashboard] section {name} failed: {exc}", flush=True)
            snapshot[name] = {}
    snapshot["generated_at"] = datetime.now()

    elapsed = time.time() - t0
    _dashboard_metrics["last_build_seconds"] = round(elapsed, 3)
    print(f"[dashboard] snapshot built parallel in {elapsed:.2f}s (cache miss)", flush=True)

    with _dashboard_cache_lock:
        _dashboard_snapshot_cache[cache_key] = snapshot
    return snapshot


def resolve_due_alerts_background():
    """🌟 รันใน background loop (alert_system) — ไม่ block dashboard load
    Dashboard เคยเรียก _resolve_due_alert_logs ทุก request → yfinance fetch ทุก unique symbol
    ย้ายมารันที่นี่ทุก ~5 นาที ผลลัพธ์ถูกอัปเดตใน DB ก่อน dashboard อ่าน
    """
    try:
        _resolve_due_alert_logs()
    except Exception as exc:
        print(f"[dashboard] background resolve failed: {exc}", flush=True)


def get_dashboard_metrics():
    """Stats สำหรับ admin debug — ดู cache hit rate"""
    metrics = dict(_dashboard_metrics)
    total = metrics["snapshot_cache_hits"] + metrics["snapshot_cache_misses"]
    metrics["hit_rate_pct"] = (metrics["snapshot_cache_hits"] / total * 100) if total else 0.0
    metrics["total_requests"] = total
    return metrics
