import atexit
import os
from pathlib import Path
import psycopg2
import psycopg2.pool
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _get_db_url():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        return db_url

    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                db_url = value.strip()
                if db_url:
                    return db_url

    raise RuntimeError("DATABASE_URL is missing. Please set it in environment variables or /root/Apexify/.env")
DEFAULT_USER_TIMEZONE = "Asia/Bangkok"
DEFAULT_USER_LANGUAGE = "th"
DEFAULT_DIGEST_FREQUENCY_HOURS = 4
DEFAULT_NEWS_START_HOUR = 7
DEFAULT_NEWS_END_HOUR = 22
ALERT_SIGNAL_RULES = {
    "RSI_OVERSOLD": {"direction": "up", "horizon_hours": 24},
    "RSI_OVERBOUGHT": {"direction": "down", "horizon_hours": 24},
    "EMA_GOLDEN_CROSS": {"direction": "up", "horizon_hours": 72},
    "EMA_DEATH_CROSS": {"direction": "down", "horizon_hours": 72},
    "BREAKOUT_BREAK_RES": {"direction": "up", "horizon_hours": 48},
    "BREAKOUT_BREAK_SUP": {"direction": "down", "horizon_hours": 48},
    "WHALE_BUY_SPIKE": {"direction": "up", "horizon_hours": 24},
    "WHALE_SELL_SPIKE": {"direction": "down", "horizon_hours": 24},
}
ALLOWED_TIMEZONES = (
    "Asia/Bangkok",
    "UTC",
    "America/New_York",
    "Europe/London",
    "Asia/Tokyo",
)
ALLOWED_LANGUAGES = ("th", "en")
ALLOWED_DIGEST_FREQUENCIES = (1, 4, 8, 24)
NEWS_TIME_FILTER_CATEGORIES = {"flash_news", "digest_news", "morning_briefing", "xd_alert"}


def _normalize_timezone(timezone_name: str) -> str:
    tz = str(timezone_name or "").strip()
    if tz in ALLOWED_TIMEZONES:
        return tz
    return DEFAULT_USER_TIMEZONE


def _normalize_language(language: str) -> str:
    lang = str(language or "").strip().lower()
    if lang in ALLOWED_LANGUAGES:
        return lang
    return DEFAULT_USER_LANGUAGE


def _normalize_digest_frequency(hours) -> int:
    try:
        value = int(hours)
    except (TypeError, ValueError):
        value = DEFAULT_DIGEST_FREQUENCY_HOURS
    if value in ALLOWED_DIGEST_FREQUENCIES:
        return value
    return DEFAULT_DIGEST_FREQUENCY_HOURS


def _normalize_news_window(start_hour, end_hour) -> tuple[int, int]:
    try:
        start = int(start_hour)
    except (TypeError, ValueError):
        start = DEFAULT_NEWS_START_HOUR
    try:
        end = int(end_hour)
    except (TypeError, ValueError):
        end = DEFAULT_NEWS_END_HOUR
    start = max(0, min(23, start))
    end = max(0, min(23, end))
    return start, end


def _coerce_utc_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        normalized = raw.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _is_hour_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
    hour = int(hour) % 24
    start = int(start_hour) % 24
    end = int(end_hour) % 24
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _ensure_user_settings_row(cursor, user_id: str):
    cursor.execute(
        """
        INSERT INTO user_settings (
            user_id,
            notifications_enabled,
            timezone,
            language,
            digest_frequency_hours,
            news_start_hour,
            news_end_hour
        )
        VALUES (%s, TRUE, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (
            str(user_id),
            DEFAULT_USER_TIMEZONE,
            DEFAULT_USER_LANGUAGE,
            DEFAULT_DIGEST_FREQUENCY_HOURS,
            DEFAULT_NEWS_START_HOUR,
            DEFAULT_NEWS_END_HOUR,
        ),
    )


def _normalize_watchlist_ticker(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_price_alert_condition(condition: str) -> str:
    raw = str(condition or "").strip().lower()
    if raw in {"above", ">"}:
        return "above"
    if raw in {"below", "<"}:
        return "below"
    return "above"


def _coerce_local_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    raw = str(value or "").strip()
    if not raw:
        return None

    normalized = raw.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        chunk = normalized[:19] if "H" in fmt else normalized[:10]
        try:
            return datetime.strptime(chunk, fmt)
        except ValueError:
            continue
    return None


def get_alert_signal_rule(alert_type):
    upper_type = str(alert_type or "").strip().upper()
    if upper_type in ALERT_SIGNAL_RULES:
        rule = ALERT_SIGNAL_RULES[upper_type]
        return {
            "direction": rule["direction"],
            "horizon_hours": int(rule["horizon_hours"]),
        }

    if any(token in upper_type for token in ("OVERSOLD", "GOLDEN_CROSS", "BREAK_RES", "BUY_SPIKE")):
        return {"direction": "up", "horizon_hours": 24}
    if any(token in upper_type for token in ("OVERBOUGHT", "DEATH_CROSS", "BREAK_SUP", "SELL_SPIKE")):
        return {"direction": "down", "horizon_hours": 24}
    return {"direction": "up", "horizon_hours": 24}


def _ensure_alert_log_schema(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_logs (
            id SERIAL PRIMARY KEY,
            symbol TEXT,
            alert_type TEXT,
            price_at_alert REAL,
            timestamp TEXT
        )
        """
    )
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS direction TEXT")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS horizon_hours INTEGER")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS evaluation_due_at TIMESTAMP")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS resolved_price REAL")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS return_pct REAL")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS edge_pct REAL")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS max_favorable_pct REAL")
    cursor.execute("ALTER TABLE alert_logs ADD COLUMN IF NOT EXISTS max_adverse_pct REAL")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_logs_status_due
        ON alert_logs (status, evaluation_due_at)
        """
    )


def _backfill_alert_log_metadata(cursor):
    cursor.execute(
        """
        SELECT id, alert_type, timestamp, direction, horizon_hours, evaluation_due_at, status
        FROM alert_logs
        WHERE direction IS NULL
           OR horizon_hours IS NULL
           OR evaluation_due_at IS NULL
           OR status IS NULL
        """
    )
    rows = cursor.fetchall()
    for log_id, alert_type, timestamp_raw, direction, horizon_hours, evaluation_due_at, status in rows:
        rule = get_alert_signal_rule(alert_type)
        alert_time = _coerce_local_datetime(timestamp_raw) or datetime.now()
        direction_value = direction or rule["direction"]
        horizon_value = int(horizon_hours or rule["horizon_hours"])
        due_value = evaluation_due_at or (alert_time + timedelta(hours=horizon_value))
        status_value = status or "pending"
        cursor.execute(
            """
            UPDATE alert_logs
            SET direction = %s,
                horizon_hours = %s,
                evaluation_due_at = %s,
                status = %s
            WHERE id = %s
            """,
            (direction_value, horizon_value, due_value, status_value, int(log_id)),
        )


def _ensure_watchlist_tables(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlists (
            user_id TEXT,
            symbol TEXT,
            PRIMARY KEY (user_id, symbol)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_watchlist (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        "ALTER TABLE user_watchlist ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )
    cursor.execute(
        """
        UPDATE user_watchlist
        SET user_id = TRIM(user_id),
            ticker = UPPER(TRIM(ticker))
        WHERE user_id <> TRIM(user_id)
           OR ticker <> UPPER(TRIM(ticker))
        """
    )
    cursor.execute(
        """
        DELETE FROM user_watchlist a
        USING user_watchlist b
        WHERE a.ctid < b.ctid
          AND a.user_id = b.user_id
          AND a.ticker = b.ticker
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS user_watchlist_user_id_ticker_idx
        ON user_watchlist (user_id, ticker)
        """
    )


def _merge_legacy_watchlists(cursor):
    cursor.execute(
        """
        INSERT INTO user_watchlist (user_id, ticker)
        SELECT DISTINCT TRIM(user_id), UPPER(TRIM(symbol))
        FROM watchlists
        WHERE COALESCE(TRIM(user_id), '') <> ''
          AND COALESCE(TRIM(symbol), '') <> ''
        ON CONFLICT (user_id, ticker) DO NOTHING
        """
    )


def _get_user_watchlist_items(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT ticker FROM user_watchlist WHERE user_id=%s ORDER BY ticker ASC",
        (str(user_id),),
    )
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]


def _add_user_watchlist_item(user_id, symbol):
    ticker = _normalize_watchlist_ticker(symbol)
    if not ticker:
        return False

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO user_watchlist (user_id, ticker)
        VALUES (%s, %s)
        ON CONFLICT (user_id, ticker) DO NOTHING
        """,
        (str(user_id), ticker),
    )
    conn.commit()
    inserted = c.rowcount > 0
    conn.close()
    return inserted


def _remove_user_watchlist_item(user_id, symbol):
    ticker = _normalize_watchlist_ticker(symbol)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM user_watchlist WHERE user_id=%s AND ticker=%s",
        (str(user_id), ticker),
    )
    conn.commit()
    conn.close()


def _get_watchers_for_ticker(symbol):
    ticker = _normalize_watchlist_ticker(symbol)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT user_id FROM user_watchlist WHERE ticker=%s ORDER BY user_id ASC",
        (ticker,),
    )
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]


def _get_all_watchlist_tickers():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT ticker FROM user_watchlist ORDER BY ticker ASC")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, _get_db_url())
        atexit.register(lambda: _pool.closeall())
    return _pool

class _PooledConnection:
    """Wrapper ที่ทำให้ conn.close() คืน connection กลับ pool แทนที่จะปิดจริง"""
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def close(self):
        self._pool.putconn(self._conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)

def get_connection():
    """ดึงการเชื่อมต่อจาก pool (conn.close() คืน connection กลับ pool อัตโนมัติ)"""
    pool = _get_pool()
    return _PooledConnection(pool, pool.getconn())

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT, role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0, username TEXT DEFAULT 'Unknown')''')
    # Keep old deployments compatible by adding missing column if table already exists.
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT DEFAULT 'Unknown'")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_used BOOLEAN DEFAULT FALSE")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP")

    # 🌟 อัปเดตตารางเพิ่ม role_type เพื่อแยกโค้ดโปรโมชั่น VIP / PRO
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes 
                 (code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, used_by TEXT DEFAULT '', role_type TEXT DEFAULT 'vip')''')
                 
    # 🌟 ฐานข้อมูลเก็บสลิปที่ใช้แล้ว ป้องกันการส่งซ้ำ
    c.execute('''CREATE TABLE IF NOT EXISTS used_slips 
                 (ref_no TEXT PRIMARY KEY, user_id TEXT, date_used TEXT)''')

    # 🌟 ตารางใหม่: เก็บประวัติสัญญาณเพื่อใช้วัดความแม่นยำ (Accuracy Log)
    _ensure_alert_log_schema(c)
    _backfill_alert_log_metadata(c)

    # ตาราง dedup สำหรับ dispatch_once (Flash/Digest/Podcast)
    c.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_log (
            dispatch_key TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            raw_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    init_watchlist_db() 

def init_watchlist_db():
    conn = get_connection()
    c = conn.cursor()
    _ensure_watchlist_tables(c)
    _merge_legacy_watchlists(c)
    conn.commit()
    conn.close()

def register_user(user_id, username="Unknown"):
    """ลงทะเบียนผู้ใช้ใหม่ พร้อมอัปเดตชื่อล่าสุด (ถ้ามี)"""
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        # 🌟 ใช้ ON CONFLICT DO UPDATE เพื่อให้คนเก่าที่เคยกด /start ไปแล้ว ถ้ากดซ้ำ ชื่อจะถูกอัปเดตเข้า DB ทันที
        c.execute("""
            INSERT INTO users (user_id, status, registered_date, role, usage_count, username)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET username = EXCLUDED.username, status = 'active'
        """, (str(user_id), 'active', now_str, 'free', 0, username))
        conn.commit()
    except Exception as e:
        print(f"❌ Error registering user: {e}")
        conn.rollback()
    finally:
        conn.close()

def mark_user_inactive(user_id):
    """Mark user เป็น inactive (บล็อคบอท/ลบบัญชี)"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET status = 'inactive' WHERE user_id = %s", (str(user_id),))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_active_users():
    """ดึงเฉพาะ user ที่ active (ไม่รวมคนบล็อค)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE COALESCE(status, 'active') = 'active'")
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]


def update_last_active(user_id):
    """อัปเดตเวลาใช้งานล่าสุดของ user"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET last_active = NOW() WHERE user_id = %s", (str(user_id),))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def get_dashboard_stats():
    """ดึงสถิติ user growth, active users, revenue สำหรับ admin dashboard"""
    conn = get_connection()
    c = conn.cursor()
    stats = {}
    try:
        # 1) User growth — จำนวน user ใหม่ต่อวัน (30 วันล่าสุด)
        c.execute("""
            SELECT registered_date::date AS d, COUNT(*) AS cnt
            FROM users
            WHERE registered_date IS NOT NULL
              AND registered_date::date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY d ORDER BY d
        """)
        stats["user_growth"] = [{"date": str(r[0]), "count": r[1]} for r in c.fetchall()]

        # 2) Active users — จำนวน user ที่ active ใน 1, 7, 30 วัน
        c.execute("""
            SELECT
                COUNT(*) FILTER (WHERE last_active >= NOW() - INTERVAL '1 day') AS dau,
                COUNT(*) FILTER (WHERE last_active >= NOW() - INTERVAL '7 days') AS wau,
                COUNT(*) FILTER (WHERE last_active >= NOW() - INTERVAL '30 days') AS mau
            FROM users WHERE last_active IS NOT NULL
        """)
        row = c.fetchone()
        stats["active_users"] = {"dau": row[0], "wau": row[1], "mau": row[2]}

        # 3) Revenue log — จำนวนสลิปที่จ่ายเงินต่อวัน (30 วันล่าสุด)
        c.execute("""
            SELECT date_used::date AS d, COUNT(*) AS cnt
            FROM used_slips
            WHERE date_used IS NOT NULL
              AND date_used::date >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY d ORDER BY d
        """)
        stats["payment_history"] = [{"date": str(r[0]), "count": r[1]} for r in c.fetchall()]

        # 4) Role distribution (current)
        c.execute("""
            SELECT role, COUNT(*) FROM users GROUP BY role
        """)
        stats["role_distribution"] = {r[0]: r[1] for r in c.fetchall()}

        # 5) Total users
        c.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = c.fetchone()[0]

    except Exception as e:
        print(f"[get_dashboard_stats] Error: {e}")
    finally:
        conn.close()
    return stats


def _calculate_subscription_expiry(role, days, current_role=None, current_expiry=None, now=None):
    now = now or datetime.now()
    new_expiry = now + timedelta(days=days)

    if current_expiry:
        try:
            if isinstance(current_expiry, datetime):
                parsed_expiry = current_expiry
            else:
                parsed_expiry = datetime.strptime(str(current_expiry), '%Y-%m-%d %H:%M:%S')
            if parsed_expiry > now and (current_role == role or role == 'pro'):
                new_expiry = parsed_expiry + timedelta(days=days)
        except (TypeError, ValueError):
            pass

    return new_expiry

def add_subscription(user_id, role='vip', days=30):
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    
    current_role = result[0] if result else None
    current_expiry = result[1] if result else None
    new_expiry = _calculate_subscription_expiry(
        role,
        days,
        current_role=current_role,
        current_expiry=current_expiry,
    )
            
    expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role=%s, expiry_date=%s WHERE user_id=%s", (role, expiry_str, str(user_id)))
    conn.commit()
    conn.close()
    return expiry_str

def check_subscription(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result:
        role, expiry_date = result
        if role in ['vip', 'pro'] and expiry_date:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < expiry:
                return role
    return 'free'

def get_usage(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT usage_count FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_usage(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

def reset_daily_free_usage():
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET usage_count = 0 WHERE role = 'free'")
    rows = c.rowcount
    conn.commit()
    conn.close()
    print(f"🔄 รีเซ็ตโควต้าฟรีรายวัน: {rows} คน")

def add_watch(user_id, symbol):
    return _add_user_watchlist_item(user_id, symbol)

def get_user_watch(user_id):
    return _get_user_watchlist_items(user_id)

def get_users_watching(symbol):
    return _get_watchers_for_ticker(symbol)

def get_all_active_symbols():
    return _get_all_watchlist_tickers()

def get_top_watched_symbols(limit: int = 10):
    """คืน top N หุ้นที่มี user ติดตามมากที่สุดในระบบ"""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT ticker, COUNT(*) as cnt FROM user_watchlist GROUP BY ticker ORDER BY cnt DESC LIMIT %s",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def remove_watch_db(user_id, symbol):
    _remove_user_watchlist_item(user_id, symbol)

def get_user_profile(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date, usage_count, registered_date FROM users WHERE user_id=%s", (str(user_id),))
    res = c.fetchone()
    conn.close()
    return res

def get_all_users():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    result = c.fetchall()
    conn.close()
    return [row[0] for row in result]

def get_expiring_subscriptions(days_before: int):
    """Return list of (user_id, role, expiry_date) expiring in exactly `days_before` days."""
    conn = get_connection()
    c = conn.cursor()
    target = (datetime.now() + timedelta(days=days_before)).strftime('%Y-%m-%d')
    c.execute(
        "SELECT user_id, role, expiry_date FROM users "
        "WHERE role IN ('vip', 'pro') AND expiry_date IS NOT NULL "
        "AND expiry_date::date = %s::date",
        (target,)
    )
    result = c.fetchall()
    conn.close()
    return result

def add_promo_code(code, days, max_uses, role_type='vip'):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO promo_codes (code, days, max_uses, current_uses, used_by, role_type) VALUES (%s, %s, %s, 0, '', %s)", (code, days, max_uses, role_type))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def redeem_code(user_id, code):
    conn = get_connection()
    c = conn.cursor()

    # Atomic UPDATE: only succeeds if under limit AND user hasn't used it yet
    c.execute("""
        UPDATE promo_codes
        SET current_uses = current_uses + 1,
            used_by = COALESCE(used_by, '') || %s || ','
        WHERE code = %s
          AND current_uses < max_uses
          AND (used_by IS NULL OR used_by NOT LIKE %s)
    """, (str(user_id), code, f"%{user_id}%"))
    rows_updated = c.rowcount
    conn.commit()

    if rows_updated == 1:
        # Success — fetch role_type and days to complete subscription
        c.execute("SELECT days, role_type FROM promo_codes WHERE code=%s", (code,))
        row = c.fetchone()
        conn.close()
        if not row:
            return False, None, None, None
        days, role_type = row
        expiry = add_subscription(user_id, role_type, days)
        return True, days, expiry, role_type

    # Update didn't go through — find out why
    c.execute("SELECT current_uses, max_uses, used_by FROM promo_codes WHERE code=%s", (code,))
    row = c.fetchone()
    conn.close()
    if row is None:
        return False, None, None, None  # Code doesn't exist
    current_uses, max_uses, used_by = row
    if used_by and str(user_id) in used_by:
        return False, "already_used_by_you", None, None
    return False, "fully_used", None, None

def get_user_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, COUNT(*) FROM users GROUP BY role")
    results = c.fetchall()
    conn.close()
    
    stats = {'free': 0, 'vip': 0, 'pro': 0}
    total = 0
    for row in results:
        role = row[0]
        count = row[1]
        if role in stats:
            stats[role] = count
        total += count
        
    return stats, total

# ==========================================
# 🌟 ฟังก์ชันจัดการสลิปซ้ำ
# ==========================================
def check_slip_used(ref_no):
    """ตรวจสอบว่าเลขที่อ้างอิงนี้เคยถูกใช้หรือยัง"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM used_slips WHERE ref_no=%s", (str(ref_no),))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_slip_used(ref_no, user_id):
    """บันทึกเลขที่อ้างอิงสลิปลงฐานข้อมูลเมื่อใช้สำเร็จ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO used_slips (ref_no, user_id, date_used) VALUES (%s, %s, %s)", (str(ref_no), str(user_id), now_str))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def claim_slip_and_add_subscription(user_id: str, ref_no: str, role: str, days: int) -> tuple[str, str | None]:
    conn = get_connection()
    c = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """
            INSERT INTO used_slips (ref_no, user_id, date_used)
            VALUES (%s, %s, %s)
            ON CONFLICT (ref_no) DO NOTHING
            RETURNING ref_no
            """,
            (str(ref_no), str(user_id), now_str),
        )
        if c.fetchone() is None:
            return "duplicate", None

        c.execute(
            "SELECT role, expiry_date FROM users WHERE user_id=%s FOR UPDATE",
            (str(user_id),),
        )
        result = c.fetchone()
        if not result:
            conn.rollback()
            return "error", None

        current_role, current_expiry = result
        new_expiry = _calculate_subscription_expiry(
            role,
            days,
            current_role=current_role,
            current_expiry=current_expiry,
            now=now,
        )
        expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            "UPDATE users SET role=%s, expiry_date=%s WHERE user_id=%s",
            (role, expiry_str, str(user_id)),
        )
        if c.rowcount != 1:
            conn.rollback()
            return "error", None

        conn.commit()
        return "success", expiry_str
    except Exception as e:
        print(f"Slip Claim Error: {e}")
        conn.rollback()
        return "error", None
    finally:
        conn.close()

# ==========================================
def get_due_pending_alert_logs(limit=200):
    row_limit = max(1, int(limit))
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, symbol, alert_type, price_at_alert, timestamp,
                   direction, horizon_hours, evaluation_due_at
            FROM alert_logs
            WHERE COALESCE(status, 'pending') = 'pending'
              AND evaluation_due_at IS NOT NULL
              AND evaluation_due_at <= %s
            ORDER BY evaluation_due_at ASC
            LIMIT %s
            """,
            (datetime.now(), row_limit),
        )
        rows = c.fetchall()
        return [
            {
                "id": int(row[0]),
                "symbol": str(row[1]),
                "alert_type": str(row[2]),
                "price_at_alert": float(row[3]),
                "timestamp": row[4],
                "direction": str(row[5] or "up"),
                "horizon_hours": int(row[6] or 24),
                "evaluation_due_at": row[7],
            }
            for row in rows
        ]
    finally:
        conn.close()


def resolve_alert_log(log_id, resolved_price, resolved_at, status, raw_return_pct, edge_pct, max_favorable_pct, max_adverse_pct):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE alert_logs
            SET resolved_price = %s,
                resolved_at = %s,
                status = %s,
                return_pct = %s,
                edge_pct = %s,
                max_favorable_pct = %s,
                max_adverse_pct = %s
            WHERE id = %s
            """,
            (
                float(resolved_price),
                resolved_at,
                str(status),
                float(raw_return_pct),
                float(edge_pct),
                float(max_favorable_pct),
                float(max_adverse_pct),
                int(log_id),
            ),
        )
        conn.commit()
    except psycopg2.Error as e:
        print(f"Alert resolve error: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_recent_alert_logs(limit=100):
    row_limit = max(1, int(limit))
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, symbol, alert_type, price_at_alert, timestamp,
                   direction, horizon_hours, evaluation_due_at,
                   resolved_at, resolved_price, status,
                   return_pct, edge_pct, max_favorable_pct, max_adverse_pct
            FROM alert_logs
            ORDER BY id DESC
            LIMIT %s
            """,
            (row_limit,),
        )
        rows = c.fetchall()
        return [
            {
                "id": int(row[0]),
                "symbol": str(row[1]),
                "alert_type": str(row[2]),
                "price_at_alert": float(row[3]),
                "timestamp": row[4],
                "direction": str(row[5] or "up"),
                "horizon_hours": int(row[6] or 24),
                "evaluation_due_at": row[7],
                "resolved_at": row[8],
                "resolved_price": row[9],
                "status": str(row[10] or "pending"),
                "return_pct": row[11],
                "edge_pct": row[12],
                "max_favorable_pct": row[13],
                "max_adverse_pct": row[14],
            }
            for row in rows
        ]
    finally:
        conn.close()


# ==========================================
# 🌟 ฟังก์ชันจัดการแบนผู้ใช้ (Blacklist)
# ==========================================
def ban_user(user_id):
    """แบนผู้ใช้โดยเปลี่ยน status เป็น 'banned'"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET status='banned' WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

def unban_user(user_id):
    """ปลดแบนผู้ใช้โดยเปลี่ยน status กลับเป็น 'active'"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET status='active' WHERE user_id=%s", (str(user_id),))
    conn.commit()
    conn.close()

def is_user_banned(user_id):
    """ตรวจสอบว่าผู้ใช้นี้ถูกแบนหรือไม่"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result and result[0] == 'banned':
        return True
    return False

# ==========================================
# 🌟 ฟังก์ชันจัดการประวัติสัญญาณ (Alert Logs) - ใช้สรุปความแม่นยำ
# ==========================================
def log_alert(symbol, alert_type, price):
    """บันทึกสัญญาณที่ส่งออกไปเพื่อใช้วัดผลความแม่นยำภายหลัง"""
    conn = get_connection()
    c = conn.cursor()
    try:
        now = datetime.now()
        rule = get_alert_signal_rule(alert_type)
        c.execute(
            """
            INSERT INTO alert_logs (
                symbol,
                alert_type,
                price_at_alert,
                timestamp,
                direction,
                horizon_hours,
                evaluation_due_at,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(symbol),
                str(alert_type),
                float(price),
                now.strftime('%Y-%m-%d %H:%M:%S'),
                rule["direction"],
                int(rule["horizon_hours"]),
                now + timedelta(hours=int(rule["horizon_hours"])),
                "pending",
            ),
        )
        conn.commit()
    except psycopg2.Error as e:
        print(f"❌ Error logging alert: {e}")
        conn.rollback()
    finally:
        conn.close()
# ==========================================
# 🌟 ระบบชวนเพื่อน (Referral System)
# ==========================================
def init_new_features_db():
    """สร้างตารางใหม่และอัปเดตโครงสร้าง (Migration) สำหรับ PostgreSQL"""
    conn = get_connection()
    c = conn.cursor()
    _ensure_watchlist_tables(c)
    c.execute('''CREATE TABLE IF NOT EXISTS user_price_alerts
                 (id SERIAL PRIMARY KEY,
                  user_id TEXT,
                  symbol TEXT,
                  target_price REAL,
                  condition TEXT, 
                  is_active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referrals
                 (id SERIAL PRIMARY KEY,
                  referrer_id TEXT,
                  referred_id TEXT UNIQUE,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute(
        f"""CREATE TABLE IF NOT EXISTS user_settings
                 (user_id TEXT PRIMARY KEY,
                  notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                  timezone TEXT NOT NULL DEFAULT '{DEFAULT_USER_TIMEZONE}',
                  language TEXT NOT NULL DEFAULT '{DEFAULT_USER_LANGUAGE}',
                  digest_frequency_hours INTEGER NOT NULL DEFAULT {DEFAULT_DIGEST_FREQUENCY_HOURS},
                  news_start_hour INTEGER NOT NULL DEFAULT {DEFAULT_NEWS_START_HOUR},
                  news_end_hour INTEGER NOT NULL DEFAULT {DEFAULT_NEWS_END_HOUR},
                  last_digest_sent_at TIMESTAMPTZ)"""
    )
                  
    # 🌟 1. สร้างตารางใหม่ (สำหรับคนเพิ่งรันบอทครั้งแรก)
    c.execute('''CREATE TABLE IF NOT EXISTS portfolios 
                 (id SERIAL PRIMARY KEY,
                  user_id TEXT,
                  ticker TEXT NOT NULL,
                  shares NUMERIC NOT NULL,
                  avg_cost NUMERIC NOT NULL,
                  asset_group TEXT DEFAULT 'ALL',
                  alert_price NUMERIC DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(user_id, ticker))''')
    _merge_legacy_watchlists(c)
    c.execute("UPDATE user_price_alerts SET symbol = UPPER(TRIM(symbol)) WHERE COALESCE(symbol, '') <> UPPER(TRIM(symbol))")
    c.execute("UPDATE user_price_alerts SET condition = 'above' WHERE condition = '>'")
    c.execute("UPDATE user_price_alerts SET condition = 'below' WHERE condition = '<'")
    c.execute(
        """
        DELETE FROM user_price_alerts a
        USING user_price_alerts b
        WHERE a.id < b.id
          AND a.user_id = b.user_id
          AND a.symbol = b.symbol
          AND COALESCE(a.is_active, 1) = 1
          AND COALESCE(b.is_active, 1) = 1
        """
    )
    c.execute("DELETE FROM user_price_alerts WHERE COALESCE(is_active, 1) <> 1")
    c.execute("""
        CREATE TABLE IF NOT EXISTS earnings_alerts (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol)
        )
    """)
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_used BOOLEAN DEFAULT FALSE")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_vip_given BOOLEAN DEFAULT FALSE")
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP")
    conn.commit()

    # 🌟 2. บังคับอัปเดตคอลัมน์ให้ฐานข้อมูลเก่าที่มีอยู่แล้ว (ป้องกัน Error)
    try:
        c.execute("ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS alert_price NUMERIC DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback() 
        
    try:
        c.execute("ALTER TABLE portfolios ADD CONSTRAINT portfolios_user_ticker_unique UNIQUE(user_id, ticker)")
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE")
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT %s", (DEFAULT_USER_TIMEZONE,))
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT %s", (DEFAULT_USER_LANGUAGE,))
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS digest_frequency_hours INTEGER NOT NULL DEFAULT %s", (DEFAULT_DIGEST_FREQUENCY_HOURS,))
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS news_start_hour INTEGER NOT NULL DEFAULT %s", (DEFAULT_NEWS_START_HOUR,))
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS news_end_hour INTEGER NOT NULL DEFAULT %s", (DEFAULT_NEWS_END_HOUR,))
        c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS last_digest_sent_at TIMESTAMPTZ")
        conn.commit()
    except Exception:
        conn.rollback()

    c.close()
    conn.close()


def get_user_settings(user_id):
    uid = str(user_id)
    default_start, default_end = _normalize_news_window(DEFAULT_NEWS_START_HOUR, DEFAULT_NEWS_END_HOUR)
    default_settings = {
        "user_id": uid,
        "notifications_enabled": True,
        "timezone": DEFAULT_USER_TIMEZONE,
        "language": DEFAULT_USER_LANGUAGE,
        "digest_frequency_hours": DEFAULT_DIGEST_FREQUENCY_HOURS,
        "news_start_hour": default_start,
        "news_end_hour": default_end,
        "last_digest_sent_at": None,
    }

    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        conn.commit()

        c.execute(
            """
            SELECT notifications_enabled, timezone, language, digest_frequency_hours,
                   news_start_hour, news_end_hour, last_digest_sent_at
            FROM user_settings
            WHERE user_id = %s
            """,
            (uid,),
        )
        row = c.fetchone()
        if not row:
            return default_settings

        notifications_enabled = bool(row[0]) if row[0] is not None else True
        tz_name = _normalize_timezone(row[1])
        language = _normalize_language(row[2])
        digest_frequency_hours = _normalize_digest_frequency(row[3])
        news_start_hour, news_end_hour = _normalize_news_window(row[4], row[5])
        last_digest_sent_at = _coerce_utc_datetime(row[6])

        c.execute(
            """
            UPDATE user_settings
            SET notifications_enabled = %s,
                timezone = %s,
                language = %s,
                digest_frequency_hours = %s,
                news_start_hour = %s,
                news_end_hour = %s
            WHERE user_id = %s
            """,
            (
                notifications_enabled,
                tz_name,
                language,
                digest_frequency_hours,
                news_start_hour,
                news_end_hour,
                uid,
            ),
        )
        conn.commit()

        return {
            "user_id": uid,
            "notifications_enabled": notifications_enabled,
            "timezone": tz_name,
            "language": language,
            "digest_frequency_hours": digest_frequency_hours,
            "news_start_hour": news_start_hour,
            "news_end_hour": news_end_hour,
            "last_digest_sent_at": last_digest_sent_at,
        }
    except Exception:
        conn.rollback()
        return default_settings
    finally:
        conn.close()


def set_user_notifications(user_id, enabled):
    uid = str(user_id)
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            "UPDATE user_settings SET notifications_enabled = %s WHERE user_id = %s",
            (bool(enabled), uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return get_user_settings(uid)


def set_user_timezone(user_id, timezone_name):
    uid = str(user_id)
    normalized_tz = _normalize_timezone(timezone_name)
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            "UPDATE user_settings SET timezone = %s WHERE user_id = %s",
            (normalized_tz, uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return get_user_settings(uid)


def set_user_language(user_id, language):
    uid = str(user_id)
    normalized_language = _normalize_language(language)
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            "UPDATE user_settings SET language = %s WHERE user_id = %s",
            (normalized_language, uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return get_user_settings(uid)


def set_user_digest_frequency(user_id, hours):
    uid = str(user_id)
    normalized_frequency = _normalize_digest_frequency(hours)
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            "UPDATE user_settings SET digest_frequency_hours = %s WHERE user_id = %s",
            (normalized_frequency, uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return get_user_settings(uid)


def set_user_news_window(user_id, start_hour, end_hour):
    uid = str(user_id)
    normalized_start, normalized_end = _normalize_news_window(start_hour, end_hour)
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            """
            UPDATE user_settings
            SET news_start_hour = %s, news_end_hour = %s
            WHERE user_id = %s
            """,
            (normalized_start, normalized_end, uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return get_user_settings(uid)


def mark_digest_sent(user_id, when_utc=None):
    uid = str(user_id)
    sent_time = when_utc or datetime.now(timezone.utc)
    sent_time = _coerce_utc_datetime(sent_time) or datetime.now(timezone.utc)

    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_user_settings_row(c, uid)
        c.execute(
            "UPDATE user_settings SET last_digest_sent_at = %s WHERE user_id = %s",
            (sent_time, uid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def should_send_user_notification(user_id, category="general", now_utc=None):
    settings = get_user_settings(user_id)
    if not settings["notifications_enabled"]:
        return False

    category_name = str(category or "general").strip().lower()
    now = now_utc or datetime.now(timezone.utc)
    now = _coerce_utc_datetime(now) or datetime.now(timezone.utc)

    if category_name in NEWS_TIME_FILTER_CATEGORIES:
        tz_name = settings.get("timezone", DEFAULT_USER_TIMEZONE)
        try:
            local_now = now.astimezone(ZoneInfo(tz_name))
        except Exception:
            local_now = now.astimezone(ZoneInfo(DEFAULT_USER_TIMEZONE))

        if not _is_hour_in_window(
            local_now.hour,
            settings.get("news_start_hour", DEFAULT_NEWS_START_HOUR),
            settings.get("news_end_hour", DEFAULT_NEWS_END_HOUR),
        ):
            return False

    if category_name == "digest_news":
        last_sent = _coerce_utc_datetime(settings.get("last_digest_sent_at"))
        digest_interval_hours = int(settings.get("digest_frequency_hours", DEFAULT_DIGEST_FREQUENCY_HOURS))
        if last_sent and (now - last_sent).total_seconds() < digest_interval_hours * 3600:
            return False

    return True


def process_referral(referrer_id, new_user_id):
    """จัดการเมื่อมีคนกดลิงก์ชวนเพื่อนเข้ามาใช้งานบอทครั้งแรก
    รางวัล: ทุก 3 referrals = VIP 30 วัน (milestone), ฟรี user ได้ +3 โควต้าต่อคน"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM users WHERE user_id = %s", (new_user_id,))
        if c.fetchone():
            return False, False

        c.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s)", (referrer_id, new_user_id))

        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (referrer_id,))
        new_count = c.fetchone()[0]

        milestone_hit = (new_count % 3 == 0)

        if milestone_hit:
            # ทุก 3 referrals → milestone reward +10 วันทุก role
            c.execute("""
                UPDATE users SET
                    role = CASE WHEN role = 'pro' THEN 'pro' ELSE 'vip' END,
                    expiry_date = GREATEST(COALESCE(expiry_date, NOW()), NOW()) + INTERVAL '10 days'
                WHERE user_id = %s
            """, (referrer_id,))
        else:
            # per-referral: free user ได้ +3 โควต้า
            c.execute("SELECT role FROM users WHERE user_id = %s", (referrer_id,))
            row = c.fetchone()
            if row and row[0] not in ('vip', 'pro'):
                c.execute("UPDATE users SET usage_count = GREATEST(0, usage_count - 3) WHERE user_id = %s", (referrer_id,))

        conn.commit()
        return True, milestone_hit
    except Exception as e:
        print(f"Referral Error: {e}")
        return False, False
    finally:
        conn.close()

def get_referral_stats(user_id):
    """ดูว่าชวนเพื่อนไปแล้วกี่คน"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

# ==========================================
# 🌟 ระบบตั้งเตือนราคาส่วนตัว (Custom Price Alerts)
# ==========================================
def add_price_alert_db(user_id, symbol, target_price, condition):
    """เพิ่มการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    normalized_symbol = _normalize_watchlist_ticker(symbol)
    normalized_condition = _normalize_price_alert_condition(condition)
    c.execute(
        """
        UPDATE user_price_alerts
        SET target_price = %s,
            condition = %s,
            is_active = 1
        WHERE id = (
            SELECT id
            FROM user_price_alerts
            WHERE user_id = %s
              AND symbol = %s
              AND is_active = 1
            ORDER BY id DESC
            LIMIT 1
        )
        """,
        (float(target_price), normalized_condition, str(user_id), normalized_symbol),
    )
    if c.rowcount == 0:
        c.execute(
            """
            INSERT INTO user_price_alerts (user_id, symbol, target_price, condition, is_active)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (str(user_id), normalized_symbol, float(target_price), normalized_condition),
        )
    conn.commit()
    conn.close()

def get_user_price_alerts_db(user_id):
    """ดึงรายการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, symbol, target_price, condition FROM user_price_alerts WHERE user_id = %s AND is_active = 1 ORDER BY id DESC",
        (user_id,),
    )
    alerts = c.fetchall()
    conn.close()
    return [
        (alert_id, symbol, target_price, _normalize_price_alert_condition(condition))
        for alert_id, symbol, target_price, condition in alerts
    ]

def remove_price_alert_db(user_id, alert_id):
    """ลบการตั้งเตือนราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_price_alerts WHERE id = %s AND user_id = %s", (alert_id, user_id))
    conn.commit()
    conn.close()

def get_all_active_price_alerts():
    """ดึงการตั้งเตือนทั้งหมดให้ระบบ alert_system คอยเช็คราคา"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, user_id, symbol, target_price, condition FROM user_price_alerts WHERE is_active = 1 ORDER BY id DESC")
    alerts = c.fetchall()
    conn.close()
    return [
        (alert_id, watched_user_id, symbol, target_price, _normalize_price_alert_condition(condition))
        for alert_id, watched_user_id, symbol, target_price, condition in alerts
    ]

def deactivate_price_alert(alert_id):
    """ปิดการแจ้งเตือนเมื่อราคาถึงเป้าหมายแล้ว"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM user_price_alerts WHERE id = %s", (alert_id,))
    conn.commit()
    conn.close()
# ==========================================
# 🌟 ระบบ Auto-Downgrade (ลดขั้นคนหมดอายุอัตโนมัติ)
# ==========================================
def auto_downgrade_expired_users():
    """ปรับสถานะคนที่หมดอายุให้กลับเป็น free อัตโนมัติ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        # หมดอายุทั้งหมด (PRO, VIP, free trial) → free ทันที
        c.execute("""
            UPDATE users SET role = 'free'
            WHERE role IN ('vip', 'pro')
              AND expiry_date < NOW()
        """)
        conn.commit()
    except Exception as e:
        print(f"❌ Auto-Downgrade Error: {e}")
        conn.rollback()
    finally:
        conn.close()
# ==========================================
# 🌟 [เพิ่มใหม่] ระบบจัดการพอร์ตลงทุน (Apex Wealth Master)
# ==========================================
def add_portfolio_stock(user_id, ticker, shares, avg_cost):
    """บันทึกหุ้นเข้าพอร์ต"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO portfolios (user_id, ticker, shares, avg_cost) VALUES (%s, %s, %s, %s)",
              (str(user_id), ticker.upper(), float(shares), float(avg_cost)))
    conn.commit()
    conn.close()

def get_user_portfolio(user_id):
    """ดึงหุ้นทั้งหมดในพอร์ตของลูกค้ารายนั้น"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT ticker, shares, avg_cost FROM portfolios WHERE user_id = %s", (str(user_id),))
    res = c.fetchall()
    conn.close()
    
    # แปลงผลลัพธ์ให้ออกมาเป็น List of Dict (เพื่อให้ดึงค่าง่ายๆ)
    portfolio = []
    for row in res:
        portfolio.append({
            'ticker': row[0],
            'shares': float(row[1]),
            'avg_cost': float(row[2])
        })
    return portfolio
def get_user_watch(user_id: str):
    """ให้เว็บดึง Watchlist ได้แบบเดียวกับบอท"""
    try:
        return _get_user_watchlist_items(user_id)
    except Exception:
        return []

def add_watch(user_id: str, symbol: str):
    """ให้เว็บเพิ่ม Watchlist ได้แบบเดียวกับบอท"""
    try:
        return _add_user_watchlist_item(user_id, symbol)
    except Exception:
        return False


# ==========================================
# 🌟 Free Trial 7 วัน PRO
# ==========================================
def has_used_free_trial(user_id: str) -> bool:
    """ตรวจสอบว่า user เคยใช้ Free Trial แล้วหรือยัง"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT free_trial_used FROM users WHERE user_id = %s", (str(user_id),))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])


def activate_free_trial(user_id: str) -> bool:
    """เปิด Free Trial PRO 7 วัน — คืนค่า True ถ้าสำเร็จ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT role, free_trial_used FROM users WHERE user_id = %s", (str(user_id),))
        row = c.fetchone()
        if not row:
            return False
        role, used = row
        if used:
            return False
        if role in ('vip', 'pro'):
            # ถ้ามี subscription อยู่แล้ว ไม่ให้ใช้ trial
            return False
        c.execute("""
            UPDATE users SET
                role = 'pro',
                expiry_date = NOW() + INTERVAL '7 days',
                free_trial_used = TRUE
            WHERE user_id = %s
        """, (str(user_id),))
        conn.commit()
        return True
    except Exception as e:
        print(f"[FreeTrial] Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ==========================================
# 🌟 Earnings Calendar Alert
# ==========================================
def init_earnings_alerts_db():
    """สร้างตาราง earnings_alerts ถ้ายังไม่มี"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS earnings_alerts (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, symbol)
        )
    """)
    conn.commit()
    conn.close()


def add_earnings_alert_db(user_id: str, symbol: str) -> bool:
    """สมัครรับแจ้งเตือน Earnings สำหรับ symbol"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO earnings_alerts (user_id, symbol) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (str(user_id), symbol.upper().strip()),
        )
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"[EarningsAlert] add error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_earnings_alerts_db(user_id: str) -> list:
    """ดึง list ของ symbol ที่ user สมัครแจ้งเตือน Earnings"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT symbol FROM earnings_alerts WHERE user_id = %s ORDER BY symbol", (str(user_id),))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


def remove_earnings_alert_db(user_id: str, symbol: str) -> bool:
    """ยกเลิกแจ้งเตือน Earnings สำหรับ symbol"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "DELETE FROM earnings_alerts WHERE user_id = %s AND symbol = %s",
            (str(user_id), symbol.upper().strip()),
        )
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        print(f"[EarningsAlert] remove error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_all_earnings_subscriptions() -> dict:
    """คืน {symbol: [user_id, ...]} สำหรับทุก symbol ที่มีคนสมัครไว้"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT symbol, user_id FROM earnings_alerts ORDER BY symbol")
    rows = c.fetchall()
    conn.close()
    result: dict = {}
    for sym, uid in rows:
        result.setdefault(sym, []).append(uid)
    return result
