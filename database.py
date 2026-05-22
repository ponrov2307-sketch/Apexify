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
        # 🌟 5-30 connections — รองรับ bot 8 threads + alert loop + Flask + pre-warm
        _pool = psycopg2.pool.ThreadedConnectionPool(5, 30, _get_db_url())
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
    # CREATE TABLE includes all columns — no ALTER TABLE migrations needed on existing deployments
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, status TEXT, registered_date TEXT,
                  role TEXT, expiry_date TEXT, usage_count INTEGER DEFAULT 0,
                  username TEXT DEFAULT 'Unknown',
                  free_trial_used BOOLEAN DEFAULT FALSE,
                  free_trial_vip_given BOOLEAN DEFAULT FALSE,
                  first_audit_done BOOLEAN DEFAULT FALSE,
                  topup_balance INTEGER DEFAULT 0,
                  last_active TIMESTAMP)''')
    # idempotent migration for existing deployments — column may not exist yet
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_audit_done BOOLEAN DEFAULT FALSE")
    except Exception as _e:
        print(f"[init_db] users.first_audit_done migration: {_e}", flush=True)
    # 🎟 Top-up balance — pay-per-use สำหรับคนที่ไม่อยากผูก subscription
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS topup_balance INTEGER DEFAULT 0")
    except Exception as _e:
        print(f"[init_db] users.topup_balance migration: {_e}", flush=True)
    # 🎁 Chart preview — free user ได้กราฟ 3 ครั้งแรกตลอดชีวิต (wow moment + habit)
    # ALTER COLUMN SET DEFAULT รัน idempotent กัน inconsistency หลัง deploy ที่เคย DEFAULT 1
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS chart_previews_left INTEGER DEFAULT 3")
    except Exception as _e:
        print(f"[init_db] users.chart_previews_left migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ALTER COLUMN chart_previews_left SET DEFAULT 3")
    except Exception as _e:
        print(f"[init_db] users.chart_previews_left default: {_e}", flush=True)
    # 🎁 Flash discount — เปิดเมื่อ free โดน paywall ครั้งแรก, valid 30 min, one-shot
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS flash_eligible_until TIMESTAMP")
    except Exception as _e:
        print(f"[init_db] users.flash_eligible_until migration: {_e}", flush=True)
    # 📊 Lifetime analysis count — สำหรับ sunk cost + tier badges + price anchoring
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_analyses INTEGER DEFAULT 0")
    except Exception as _e:
        print(f"[init_db] users.total_analyses migration: {_e}", flush=True)
    # 🏆 Highest tier reached — tier_unlocked_codes เก็บ tier ที่ user ได้ unlock (CSV)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tiers_unlocked TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[init_db] users.tiers_unlocked migration: {_e}", flush=True)
    # 🔔 Notification timestamps — กัน DM ซ้ำ (daily reset / streak loss / lapsed trial)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_daily_reset_dm TIMESTAMP")
    except Exception as _e:
        print(f"[init_db] users.last_daily_reset_dm migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_streak_loss_dm TIMESTAMP")
    except Exception as _e:
        print(f"[init_db] users.last_streak_loss_dm migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_lapsed_trial_dm TIMESTAMP")
    except Exception as _e:
        print(f"[init_db] users.last_lapsed_trial_dm migration: {_e}", flush=True)
    # 🎟 Code-based discount window — เปิดเมื่อ user redeem โค้ดส่วนลด %
    # ทำงานคล้าย flash discount แต่ trigger ผ่านโค้ดและมีจำนวนโค้ดใช้ได้
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discount_amount_vip INTEGER")
    except Exception as _e:
        print(f"[init_db] users.discount_amount_vip migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discount_amount_pro INTEGER")
    except Exception as _e:
        print(f"[init_db] users.discount_amount_pro migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discount_until TIMESTAMP")
    except Exception as _e:
        print(f"[init_db] users.discount_until migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS discount_code TEXT")
    except Exception as _e:
        print(f"[init_db] users.discount_code migration: {_e}", flush=True)
    # 💰 Cash balance (USD) for portfolio NAV calculation
    # Requested by nuttapon (Annual PRO customer #1) — 2026-05-16
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cash_balance NUMERIC(18,2) DEFAULT 0")
    except Exception as _e:
        print(f"[init_db] users.cash_balance migration: {_e}", flush=True)
    # 💰 Cash transaction log — audit trail for deposit/withdraw/set actions
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS cash_transactions (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                action_type TEXT NOT NULL CHECK (action_type IN ('set','deposit','withdraw')),
                delta NUMERIC(18,2) NOT NULL,
                balance_before NUMERIC(18,2),
                balance_after NUMERIC(18,2) NOT NULL,
                note TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_cash_tx_user_date ON cash_transactions(user_id, created_at DESC)")
    except Exception as _e:
        print(f"[init_db] cash_transactions migration: {_e}", flush=True)
    # 🌟 อัปเดตตารางเพิ่ม role_type เพื่อแยกโค้ดโปรโมชั่น VIP / PRO
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes
                 (code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER DEFAULT 1, current_uses INTEGER DEFAULT 0, used_by TEXT DEFAULT '', role_type TEXT DEFAULT 'vip')''')
    # 🎟 Discount mode — โค้ด % off (เปิด discount window แทนเพิ่มวัน)
    try:
        c.execute("ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS discount_pct INTEGER")
    except Exception as _e:
        print(f"[init_db] promo_codes.discount_pct migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS window_hours INTEGER DEFAULT 0")
    except Exception as _e:
        print(f"[init_db] promo_codes.window_hours migration: {_e}", flush=True)

    # 🌟 ฐานข้อมูลเก็บสลิปที่ใช้แล้ว ป้องกันการส่งซ้ำ
    c.execute('''CREATE TABLE IF NOT EXISTS used_slips
                 (ref_no TEXT PRIMARY KEY, user_id TEXT, date_used TEXT)''')
    # 📊 Payment type tracking — แยก flash/annual/monthly/topup เพื่อดู conversion ภายหลัง
    try:
        c.execute("ALTER TABLE used_slips ADD COLUMN IF NOT EXISTS payment_type TEXT DEFAULT 'standard'")
    except Exception as _e:
        print(f"[init_db] used_slips.payment_type migration: {_e}", flush=True)
    try:
        c.execute("ALTER TABLE used_slips ADD COLUMN IF NOT EXISTS amount NUMERIC")
    except Exception as _e:
        print(f"[init_db] used_slips.amount migration: {_e}", flush=True)

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

    # ตารางเก็บ log การพิมพ์คำสั่งของ user — สำหรับ admin dashboard "top commands"
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_command_log (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            command TEXT NOT NULL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_cmd_log_ts ON bot_command_log (ts DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cmd_log_command ON bot_command_log (command)")

    # ตารางเก็บ log การส่ง broadcast — success/fail/total
    c.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_log (
            id BIGSERIAL PRIMARY KEY,
            audience TEXT NOT NULL,
            total INT NOT NULL,
            success INT NOT NULL,
            fail INT NOT NULL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_bcast_log_ts ON broadcast_log (ts DESC)")

    # ตาราง persist alert state — fix bug duplicate alerts หลัง restart
    # เก็บ state ของแต่ละ (symbol, kind) เช่น (NVDA, rsi) → 'overbought'
    # โหลดตอน startup เพื่อให้รู้ว่าเคยส่ง alert ใดไปแล้ว
    c.execute("""
        CREATE TABLE IF NOT EXISTS alert_state (
            symbol TEXT NOT NULL,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, kind)
        )
    """)

    # ตาราง dedup earnings alert — กัน user ได้ "Earnings วันนี้" ซ้ำตอน bot restart 7:59 → 8:00
    c.execute("""
        CREATE TABLE IF NOT EXISTS earnings_notified (
            user_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            notify_date DATE NOT NULL,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, symbol, notify_date)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_earnings_notified_date ON earnings_notified (notify_date DESC)")

    # ตาราง analytics สำหรับ dashboard funnel — link_issued → login_redeemed → home_viewed
    c.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_events (
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            role        TEXT,
            event_name  TEXT NOT NULL,
            source      TEXT,
            feature     TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_dash_events ON dashboard_events (user_id, event_name, created_at DESC)")

    # Dedup table for "1-2 hour before expiry" warnings — fires once per (user, expiry).
    # The 7/3/1-day warnings in send_expiry_warnings rely on the daily-fire cadence
    # for dedup, but the final-hour warning runs hourly so it needs explicit guard.
    c.execute("""
        CREATE TABLE IF NOT EXISTS expiry_final_warned (
            user_id     TEXT NOT NULL,
            expiry_at   TIMESTAMPTZ NOT NULL,
            warned_at   TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, expiry_at)
        )
    """)

    # Trial-day spotlight DMs — Day 2 / Day 5 of the 7-day PRO trial. Day 4
    # would collide with the existing 3-day expiry warning, so we skip it.
    c.execute("""
        CREATE TABLE IF NOT EXISTS trial_spotlight_sent (
            user_id     TEXT NOT NULL,
            day_marker  TEXT NOT NULL,
            sent_at     TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, day_marker)
        )
    """)

    # Win-back DMs at 7/14/30 days of inactivity. Each milestone fires once
    # per user; if user comes back and goes inactive again, they cycle through
    # the milestones again only after PRIMARY KEY rows are cleared (manual
    # for now — future cleanup can re-enable cadence for repeat-churn users).
    c.execute("""
        CREATE TABLE IF NOT EXISTS winback_sent (
            user_id     TEXT NOT NULL,
            milestone   TEXT NOT NULL,
            sent_at     TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, milestone)
        )
    """)

    # 📜 Subscription History — audit trail (added 2026-05-12)
    # ใช้ debug bug แบบเคส Neil/Nattanon ที่จ่าย PRO แต่ downgrade → ดู history แทนการเดา
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscription_history (
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            role_before TEXT,
            role_after TEXT,
            expiry_before TEXT,
            expiry_after TEXT,
            days_granted INTEGER,
            source TEXT,
            source_detail TEXT,
            meta JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_sub_history_user ON subscription_history(user_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sub_history_action ON subscription_history(action_type)")

    conn.commit()
    conn.close()
    init_watchlist_db()


def log_command(user_id, command):
    """Log a slash-command invocation. Called from main.py middleware/wrapper.
    Safe to fail silently — never break bot if logging fails.
    """
    cmd = str(command or "").strip().lower()[:32]
    if not cmd:
        return
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO bot_command_log (user_id, command) VALUES (%s, %s)",
            (str(user_id), cmd),
        )
        conn.commit()
    except Exception as e:
        print(f"[log_command] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def log_dashboard_event(user_id: str, role: str | None, event_name: str,
                        source: str | None = None, feature: str | None = None):
    """Log a dashboard funnel event. Safe to fail silently."""
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dashboard_events (user_id, role, event_name, source, feature) VALUES (%s, %s, %s, %s, %s)",
            (str(user_id), role, str(event_name)[:64], source, feature),
        )
        conn.commit()
    except Exception as e:
        print(f"[log_dashboard_event] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def log_broadcast(audience, total, success, fail):
    """Log broadcast batch to broadcast_log table."""
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO broadcast_log (audience, total, success, fail) VALUES (%s, %s, %s, %s)",
            (str(audience or "")[:32], int(total or 0), int(success or 0), int(fail or 0)),
        )
        conn.commit()
    except Exception as e:
        print(f"[log_broadcast] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def cleanup_old_logs(days: int = 90) -> dict:
    """ลบ row เก่าใน bot_command_log + broadcast_log ที่อายุเกิน N วัน"""
    days = max(1, int(days))
    conn = get_connection()
    c = conn.cursor()
    deleted = {"bot_command_log": 0, "broadcast_log": 0}
    try:
        c.execute(f"DELETE FROM bot_command_log WHERE ts < NOW() - INTERVAL '{days} days'")
        deleted["bot_command_log"] = c.rowcount or 0
        c.execute(f"DELETE FROM broadcast_log  WHERE ts < NOW() - INTERVAL '{days} days'")
        deleted["broadcast_log"] = c.rowcount or 0
        conn.commit()
    except Exception as e:
        print(f"[cleanup_old_logs] {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()
    return deleted


def load_all_alert_states():
    """โหลด alert state ทั้งหมดจาก DB → คืน {symbol: {kind: state}}
    ใช้ใน alert_system ตอน startup เพื่อให้รู้ว่าเคยส่ง alert ตัวไหนไปแล้ว
    ป้องกัน duplicate alert หลัง systemctl restart
    """
    result = {}
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT symbol, kind, state FROM alert_state")
        for row in c.fetchall():
            sym, kind, state = row
            result.setdefault(str(sym), {})[str(kind)] = str(state)
    except Exception as e:
        print(f"[load_all_alert_states] {e}", flush=True)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    return result


def save_alert_state(symbol, kind, state):
    """UPSERT alert state (symbol, kind) → state. Fail-safe — ไม่ break alert loop ถ้า DB ขัดข้อง"""
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO alert_state (symbol, kind, state, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (symbol, kind) DO UPDATE
                SET state = EXCLUDED.state, updated_at = NOW()
            """,
            (str(symbol), str(kind), str(state)),
        )
        conn.commit()
    except Exception as e:
        print(f"[save_alert_state] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def is_earnings_notified(user_id, symbol, notify_date):
    """เช็คว่า user_id ได้รับ earnings alert ของ symbol ใน notify_date แล้วหรือยัง
    notify_date: date object หรือ ISO string 'YYYY-MM-DD'
    """
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM earnings_notified WHERE user_id=%s AND symbol=%s AND notify_date=%s LIMIT 1",
            (str(user_id), str(symbol), notify_date),
        )
        return c.fetchone() is not None
    except Exception as e:
        print(f"[is_earnings_notified] {e}", flush=True)
        return False  # ถ้า DB ขัดข้อง — ส่ง alert ไปดีกว่าหายไป
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def mark_earnings_notified(user_id, symbol, notify_date):
    """บันทึกว่า user_id ได้รับ earnings alert ของ symbol ใน notify_date แล้ว"""
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO earnings_notified (user_id, symbol, notify_date)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, symbol, notify_date) DO NOTHING
            """,
            (str(user_id), str(symbol), notify_date),
        )
        conn.commit()
    except Exception as e:
        print(f"[mark_earnings_notified] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

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


_ROLE_RANK = {'free': 0, 'vip': 1, 'pro': 2}


# ==========================================
# 📜 Subscription History — audit trail (added 2026-05-12)
# ==========================================
def log_subscription_event(
    user_id: str,
    action_type: str,
    role_before: str = None,
    role_after: str = None,
    expiry_before=None,
    expiry_after=None,
    days_granted: int = None,
    source: str = None,
    source_detail: str = None,
    meta: dict = None,
):
    """Append-only log สำหรับ subscription events.

    ⚠️ Defensive: ห้าม raise — ถ้า log fail ห้าม block main logic
    (logging shouldn't break feature). Wrap ใน try/except + flush ERR

    action_type:
      - 'paid'           — ลูกค้าจ่าย slip
      - 'redeem'         — ใส่ promo code (discount/days)
      - 'admin_grant'    — admin /addrole
      - 'tier_reward'    — redeem badge code (BRONZE/SILVER)
      - 'expire'         — auto downgrade ตอนหมดอายุ
      - 'auto_downgrade' — ระบบ downgrade (bug-triggered, ที่ต้อง investigate)
      - 'topup'          — ซื้อ top-up balance
      - 'referral_bonus' — ได้ vip จาก referral

    source: 'slip' | 'code' | 'admin' | 'cron' | 'system'
    """
    import json
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO subscription_history
            (user_id, action_type, role_before, role_after,
             expiry_before, expiry_after, days_granted,
             source, source_detail, meta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(user_id),
                str(action_type),
                role_before, role_after,
                str(expiry_before) if expiry_before else None,
                str(expiry_after) if expiry_after else None,
                int(days_granted) if days_granted is not None else None,
                source, source_detail,
                json.dumps(meta, ensure_ascii=False) if meta else None,
            ),
        )
        conn.commit()
    except Exception as e:
        print(f"[sub_history] log err (user={user_id} action={action_type}): {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_subscription_history(user_id: str, limit: int = 30) -> list[dict]:
    """Return timeline ของ user — เรียงตาม created_at DESC (ล่าสุดก่อน)"""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            SELECT id, action_type, role_before, role_after,
                   expiry_before, expiry_after, days_granted,
                   source, source_detail, meta, created_at
            FROM subscription_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (str(user_id), int(limit)),
        )
        rows = c.fetchall() or []
        out = []
        for r in rows:
            out.append({
                "id": r[0],
                "action_type": r[1],
                "role_before": r[2],
                "role_after": r[3],
                "expiry_before": r[4],
                "expiry_after": r[5],
                "days_granted": r[6],
                "source": r[7],
                "source_detail": r[8],
                "meta": r[9],
                "created_at": r[10],
            })
        return out
    except Exception as e:
        print(f"[sub_history] read err: {e}", flush=True)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _calculate_subscription_expiry(role, days, current_role=None, current_expiry=None, now=None):
    """คำนวณ expiry ใหม่ — stack ถ้า active + same/higher tier, reset ถ้า expired"""
    now = now or datetime.now()
    new_expiry = now + timedelta(days=days)

    if current_expiry:
        try:
            if isinstance(current_expiry, datetime):
                parsed_expiry = current_expiry.replace(tzinfo=None)
            else:
                raw = str(current_expiry).strip().replace('T', ' ')
                parsed_expiry = datetime.fromisoformat(raw).replace(tzinfo=None)
            if parsed_expiry > now:
                # Stack expiry ถ้า:
                # 1. Same tier — VIP + VIP, PRO + PRO
                # 2. Upgrade — VIP + PRO (upgrade)
                # 3. **Downgrade case (PRO + VIP)** — stack เช่นกัน (กัน user เสีย days)
                # ทุก case ที่ current active → stack เสมอ
                new_expiry = parsed_expiry + timedelta(days=days)
        except (TypeError, ValueError):
            pass

    return new_expiry


def add_subscription(user_id, role='vip', days=30, source=None, source_detail=None, meta=None):
    """Add subscription — **ห้าม downgrade** higher tier
    ถ้า user เป็น PRO อยู่ + redeem VIP code → keep PRO, stack days

    Args:
      source: 'slip' | 'code' | 'admin' | 'cron' | 'system' (สำหรับ log)
      source_detail: e.g. 'WINBACK30' | 'slip 109฿' | 'admin /addrole'
      meta: optional dict สำหรับ context เพิ่ม
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()

    current_role = result[0] if result else None
    current_expiry = result[1] if result else None

    # 🛡 Role hierarchy guard — กัน downgrade (เคสจริง: PRO + redeem VIP welcome code → เสีย PRO)
    is_active = False
    if current_role in ('vip', 'pro') and current_expiry:
        try:
            if isinstance(current_expiry, datetime):
                parsed = current_expiry.replace(tzinfo=None)
            else:
                raw = str(current_expiry).strip().replace('T', ' ')
                parsed = datetime.fromisoformat(raw).replace(tzinfo=None)
            is_active = parsed > datetime.now()
        except Exception:
            pass

    effective_role = role
    guarded_downgrade = False
    if is_active and _ROLE_RANK.get(current_role, 0) > _ROLE_RANK.get(role, 0):
        # Current higher tier (PRO) + new lower (VIP) → keep current tier, just extend
        effective_role = current_role
        guarded_downgrade = True
        print(f"[add_subscription] guard: keep {current_role} (no downgrade to {role}) for user {user_id}", flush=True)

    new_expiry = _calculate_subscription_expiry(
        effective_role,
        days,
        current_role=current_role,
        current_expiry=current_expiry,
    )

    expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    c.execute("UPDATE users SET role=%s, expiry_date=%s WHERE user_id=%s", (effective_role, expiry_str, str(user_id)))
    conn.commit()
    conn.close()

    # 📜 Log to subscription_history (defensive — never block)
    log_meta = dict(meta or {})
    if guarded_downgrade:
        log_meta["downgrade_prevented_to"] = role   # log ว่า user พยายาม downgrade เป็น role อะไร
    log_subscription_event(
        user_id=user_id,
        action_type=source or "system_grant",       # default 'system_grant' ถ้า caller ไม่ระบุ
        role_before=current_role,
        role_after=effective_role,
        expiry_before=current_expiry,
        expiry_after=expiry_str,
        days_granted=days,
        source=source,
        source_detail=source_detail,
        meta=log_meta if log_meta else None,
    )
    return expiry_str

def check_subscription(user_id):
    # 🌟 Admin ได้สิทธิ์ PRO เสมอ (ทุก feature ที่เช็ค == 'pro' จะผ่าน)
    try:
        from config import ADMIN_ID as _ADMIN_ID
        if _ADMIN_ID and str(user_id) == str(_ADMIN_ID):
            return 'pro'
    except Exception:
        pass

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT role, expiry_date FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if result:
        role, expiry_date = result
        if role in ['vip', 'pro'] and expiry_date:
            try:
                if isinstance(expiry_date, datetime):
                    expiry = expiry_date.replace(tzinfo=None)
                else:
                    raw = str(expiry_date).strip().replace('T', ' ')
                    # fromisoformat handles microseconds & tz; strip tz for naive compare
                    parsed = datetime.fromisoformat(raw)
                    expiry = parsed.replace(tzinfo=None)
                if datetime.now() < expiry:
                    return role
            except (ValueError, TypeError):
                pass
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


# 🎟 Top-up balance — pay-per-use สำหรับ user ที่ไม่อยากผูก subscription รายเดือน
# ใช้คู่กับ free quota: เมื่อใช้ครบ 3/วัน ระบบจะหักจาก top-up ก่อนปฏิเสธ
def get_topup_balance(user_id):
    """คืนยอด top-up คงเหลือของ user (int >= 0)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT topup_balance FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    return int(result[0]) if result and result[0] else 0


def add_topup_balance(user_id, count):
    """เพิ่มยอด top-up — คืนยอดรวมหลังเพิ่ม"""
    if count <= 0:
        return get_topup_balance(user_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET topup_balance = COALESCE(topup_balance, 0) + %s WHERE user_id=%s",
        (int(count), str(user_id)),
    )
    c.execute("SELECT topup_balance FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.commit()
    conn.close()
    return int(result[0]) if result and result[0] else 0


def consume_topup_balance(user_id, count=1):
    """หัก top-up — คืน True ถ้าหักสำเร็จ (มียอดพอ), False ถ้ายอดไม่พอ
    ใช้ atomic UPDATE WHERE topup_balance >= count กัน race condition
    """
    if count <= 0:
        return True
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET topup_balance = topup_balance - %s "
        "WHERE user_id=%s AND COALESCE(topup_balance, 0) >= %s",
        (int(count), str(user_id), int(count)),
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


# 🎁 Chart preview — free user ได้กราฟ 3 ครั้งแรกตลอดชีวิต (default 3)
CHART_PREVIEW_TOTAL = 3  # ใช้ใน banner "ครั้งที่ X/3"

def get_chart_previews_left(user_id):
    """คืนจำนวน preview ที่เหลือ (int >= 0)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT chart_previews_left FROM users WHERE user_id=%s", (str(user_id),))
    result = c.fetchone()
    conn.close()
    if not result:
        return 0
    return int(result[0]) if result[0] is not None else CHART_PREVIEW_TOTAL


def consume_chart_preview(user_id):
    """หัก preview 1 ครั้ง — atomic UPDATE คืน (consumed:bool, remaining:int)
    consumed=True ถ้าหักสำเร็จ, False ถ้าหมด/error
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE users SET chart_previews_left = chart_previews_left - 1 "
        "WHERE user_id=%s AND COALESCE(chart_previews_left, 0) > 0 "
        "RETURNING chart_previews_left",
        (str(user_id),),
    )
    row = c.fetchone()
    conn.commit()
    conn.close()
    if row is None:
        return False, 0
    return True, int(row[0]) if row[0] is not None else 0


def refund_chart_preview(user_id):
    """คืน preview 1 ครั้ง — ใช้กรณี analyze fail หลัง consume แล้ว
    เพื่อกัน user เสียครั้งฟรีโดยไม่ได้ใช้
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET chart_previews_left = chart_previews_left + 1 "
            "WHERE user_id=%s",
            (str(user_id),),
        )
        conn.commit()
    except Exception as e:
        print(f"[refund_chart_preview] err: {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()


# 🎁 Flash discount — เปิดเมื่อ free โดน paywall ครั้งแรก
# pricing: 63 = VIP 20% off, 87 = PRO 20% off
FLASH_VIP_AMOUNT = 63
FLASH_PRO_AMOUNT = 87
FLASH_WINDOW_MINUTES = 30


def start_flash_discount_if_eligible(user_id):
    """เปิด flash window 30 นาที ถ้า user ยังไม่เคยใช้ (NULL) หรือเปิดเมื่อก่อนแต่หมดแล้ว
    Cooldown: ห่างกันอย่างน้อย 24 ชม. ก่อนเปิดใหม่ — กันคนเก่ากด /start ทุกวันได้ flash

    Returns: (eligible:bool, expires_at:datetime หรือ None)
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        from datetime import timedelta
        now = datetime.now()
        cooldown_cutoff = now - timedelta(hours=24)
        c.execute(
            "SELECT flash_eligible_until FROM users WHERE user_id=%s FOR UPDATE",
            (str(user_id),),
        )
        row = c.fetchone()
        if not row:
            conn.rollback()
            return False, None
        cur = row[0]
        # eligible if: never used (NULL) OR last offer cooldown passed (>24h before now)
        if cur is None:
            should_open = True
        else:
            try:
                cur_dt = cur if isinstance(cur, datetime) else datetime.fromisoformat(str(cur).replace('T', ' '))
                cur_dt = cur_dt.replace(tzinfo=None) if cur_dt.tzinfo else cur_dt
                # if cur > now → flash ยัง active อยู่ (คืน eligible+expiry เดิม)
                if cur_dt > now:
                    conn.rollback()
                    return True, cur_dt
                # cooldown: must be older than 24h ago
                should_open = cur_dt < cooldown_cutoff
            except Exception:
                should_open = True

        if not should_open:
            conn.rollback()
            return False, None

        new_expiry = now + timedelta(minutes=FLASH_WINDOW_MINUTES)
        c.execute(
            "UPDATE users SET flash_eligible_until=%s WHERE user_id=%s",
            (new_expiry.strftime('%Y-%m-%d %H:%M:%S'), str(user_id)),
        )
        conn.commit()
        return True, new_expiry
    except Exception as e:
        print(f"[flash] start err: {e}", flush=True)
        conn.rollback()
        return False, None
    finally:
        conn.close()


def is_flash_active(user_id):
    """เช็คว่า flash window ยัง active อยู่ไหม — ใช้ใน slip handler ตอน amount=63/87
    Returns: bool
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT flash_eligible_until FROM users WHERE user_id=%s", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    try:
        cur_dt = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0]).replace('T', ' '))
        cur_dt = cur_dt.replace(tzinfo=None) if cur_dt.tzinfo else cur_dt
        return datetime.now() < cur_dt
    except Exception:
        return False


def consume_flash_discount(user_id):
    """ปิด flash window หลังใช้สำเร็จ — กันใช้ซ้ำใน window เดียวกัน"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET flash_eligible_until=NULL WHERE user_id=%s", (str(user_id),))
        conn.commit()
    except Exception as e:
        print(f"[flash] consume err: {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()


# 📊 Lifetime analysis tracking — ใช้กับ sunk cost + tier badges
def get_total_analyses(user_id):
    """คืน lifetime analysis count ของ user (int >= 0)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT total_analyses FROM users WHERE user_id=%s", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if not row or row[0] is None:
        return 0
    return int(row[0])


def increment_total_analyses(user_id):
    """+1 lifetime — รันทุกครั้งที่ user ทำ analyze (free + paid)"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET total_analyses = COALESCE(total_analyses, 0) + 1 WHERE user_id=%s "
            "RETURNING total_analyses",
            (str(user_id),),
        )
        row = c.fetchone()
        conn.commit()
        return int(row[0]) if row else 0
    except Exception as e:
        print(f"[total_analyses] inc err: {e}", flush=True)
        conn.rollback()
        return 0
    finally:
        conn.close()


# 🏆 Tier badges system — auto-grant promo codes when user hits milestone
# ⚠️ Threshold ระยะ launch (test phase) ลดลงให้ user ได้ feedback เร็ว
# กลับมาเพิ่มได้เมื่อ scale > 100 paying — แค่แก้ตัวเลขในนี้
TIER_BADGES = [
    # (tier_id, threshold_type, threshold_value, badge, label, days_bonus, role_type, code_prefix)
    ('bronze',   'analyses', 3,   '🥉', 'Bronze Trader',   3,  'vip', 'BRONZE'),
    ('silver',   'analyses', 15,  '🥈', 'Silver Trader',   7,  'vip', 'SILVER'),
    ('gold',     'analyses', 50,  '🥇', 'Gold Analyst',    7,  'pro', 'GOLD'),
    # Diamond = 21 (ห่าง 7-day milestone ที่ 7/14 — กัน user ได้ 2 reward พร้อมกัน)
    ('diamond',  'streak',   21,  '💎', 'Diamond Streak',  14, 'pro', 'DIAMOND'),
]


def check_and_grant_tier_codes(user_id, total_analyses, current_streak):
    """ตรวจว่า user ถึง tier ใหม่หรือยัง — ถ้าใช่ auto-create personal promo code
    Returns: list of dict {tier_id, badge, label, code, days, role_type} ที่ unlock ใหม่
    Idempotent: ถ้าเคย unlock แล้วจะไม่สร้าง code ซ้ำ
    Note: skip code generation สำหรับ admin (ป้องกัน DM spam) — admin ดู badge UI ได้ปกติ
    """
    if not user_id:
        return []
    # Skip admin — ไม่ต้องส่งโค้ดให้ admin (ใช้ DB ตรงได้)
    try:
        from config import ADMIN_ID as _ADMIN_ID
        if _ADMIN_ID and str(user_id) == str(_ADMIN_ID):
            return []
    except Exception:
        pass

    conn = get_connection()
    c = conn.cursor()
    newly_unlocked = []
    try:
        c.execute("SELECT tiers_unlocked FROM users WHERE user_id=%s FOR UPDATE", (str(user_id),))
        row = c.fetchone()
        if not row:
            conn.rollback()
            return []
        unlocked_csv = (row[0] or '').strip()
        already = set(t.strip() for t in unlocked_csv.split(',') if t.strip())

        for tier_id, threshold_type, threshold_value, badge, label, days, role_type, prefix in TIER_BADGES:
            if tier_id in already:
                continue
            value = total_analyses if threshold_type == 'analyses' else current_streak
            if value < threshold_value:
                continue

            # 🎁 Generate personal promo code: PREFIX_USERID
            code = f"{prefix}_{user_id}"
            try:
                c.execute(
                    "INSERT INTO promo_codes (code, days, max_uses, current_uses, used_by, role_type) "
                    "VALUES (%s, %s, 1, 0, '', %s) ON CONFLICT (code) DO NOTHING",
                    (code, days, role_type),
                )
            except Exception as e:
                print(f"[tier] insert code {code} err: {e}", flush=True)
                continue
            newly_unlocked.append({
                'tier_id': tier_id, 'badge': badge, 'label': label,
                'code': code, 'days': days, 'role_type': role_type,
            })
            already.add(tier_id)

        if newly_unlocked:
            new_csv = ','.join(sorted(already))
            c.execute("UPDATE users SET tiers_unlocked=%s WHERE user_id=%s", (new_csv, str(user_id)))
        conn.commit()
        return newly_unlocked
    except Exception as e:
        print(f"[tier] err: {e}", flush=True)
        conn.rollback()
        return []
    finally:
        conn.close()


def get_user_tier(total_analyses, current_streak):
    """หา highest tier ของ user ตอนนี้ ตาม TIER_BADGES (deterministic, no DB)
    คืน dict {tier_id, badge, label} ของ highest tier ที่ user ผ่าน หรือ None
    """
    highest = None
    for tier_id, threshold_type, threshold_value, badge, label, *_ in TIER_BADGES:
        value = total_analyses if threshold_type == 'analyses' else current_streak
        if value >= threshold_value:
            highest = {'tier_id': tier_id, 'badge': badge, 'label': label}
    return highest


def get_payment_type_breakdown(days_back=30):
    """รายงาน conversion breakdown แยกตาม payment_type ใน N วันล่าสุด
    Returns: list of dict {type, count, total_amount}
    ใช้กับ /admin command ดู conversion rate ของ flash vs standard vs annual
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """
            SELECT
              COALESCE(payment_type, 'standard') AS type,
              COUNT(*) AS cnt,
              COALESCE(SUM(amount), 0) AS total
            FROM used_slips
            WHERE date_used >= %s
            GROUP BY COALESCE(payment_type, 'standard')
            ORDER BY cnt DESC
            """,
            (cutoff,),
        )
        rows = c.fetchall() or []
        return [
            {"type": str(r[0]), "count": int(r[1]), "total_amount": float(r[2] or 0)}
            for r in rows
        ]
    except Exception as e:
        print(f"[payment_breakdown] err: {e}", flush=True)
        return []
    finally:
        conn.close()


# 👥 Social proof stats — ดึง real-time จาก DB ใส่ paywall
def get_social_proof_stats(symbol=None):
    """ดึงสถิติเพื่อแสดง social proof ใน paywall — ทุก count atomic ไม่กิน performance
    Returns: dict {
        active_24h: int — user ที่ active ใน 24 ชม.
        new_paid_7d: int — user ใหม่ที่สมัคร VIP/PRO ใน 7 วัน
        watching_symbol: int — ติดตาม symbol นี้ (ถ้า symbol given)
    }
    """
    conn = get_connection()
    c = conn.cursor()
    stats = {"active_24h": 0, "new_paid_7d": 0, "watching_symbol": 0}
    try:
        from datetime import timedelta
        now = datetime.now()
        c.execute(
            "SELECT COUNT(*) FROM users WHERE last_active >= %s",
            (now - timedelta(hours=24),),
        )
        r = c.fetchone()
        if r:
            stats["active_24h"] = int(r[0] or 0)

        c.execute(
            "SELECT COUNT(*) FROM users WHERE role IN ('vip','pro') AND expiry_date >= %s",
            (now,),
        )
        r = c.fetchone()
        if r:
            stats["new_paid_7d"] = int(r[0] or 0)

        if symbol:
            c.execute(
                "SELECT COUNT(*) FROM user_watchlist WHERE UPPER(ticker)=%s",
                (str(symbol).upper(),),
            )
            r = c.fetchone()
            if r:
                stats["watching_symbol"] = int(r[0] or 0)
    except Exception as e:
        print(f"[social_proof] err: {e}", flush=True)
    finally:
        conn.close()
    return stats

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


# ==========================================
# 🌟 Track Record — AI Plan outcome tracking
# ==========================================
def log_analysis_plan(user_id, symbol, bias, entry_low, entry_high, tp1, tp2, sl, price_at_issue):
    """บันทึก Plan ที่ออกให้ PRO — ใช้ตรวจ outcome ภายหลัง"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO analysis_plans
            (user_id, symbol, bias, entry_low, entry_high, tp1, tp2, sl, price_at_issue)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (str(user_id), symbol.upper(), bias,
              entry_low, entry_high, tp1, tp2, sl, price_at_issue))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[log_plan] error: {e}")
    finally:
        conn.close()


def get_pending_plans(min_age_hours=24, max_age_days=45):
    """ดึง Plan ที่ยังเปิดอยู่ (outcome='open') อายุระหว่าง 1 วัน - 45 วัน
    ต่ำกว่า 1 วันยังไม่ควรตรวจเพราะราคายังไม่ expected hit
    เกิน 45 วันจะ mark expired
    """
    conn = get_connection()
    c = conn.cursor()
    # 🐛 Fix: INTERVAL '%s hours' inside string literal — psycopg2 ไม่ replace +
    # Postgres throw error → silently fail ตั้งแต่ deploy แรก ทำให้ 368 plans
    # ไม่เคยถูก evaluate ใช้ %s::INTERVAL cast แทน (parametrized ปลอดภัย)
    c.execute(
        """
        SELECT id, symbol, bias, entry_low, entry_high, tp1, tp2, sl,
               price_at_issue, issued_at
        FROM analysis_plans
        WHERE outcome = 'open'
          AND issued_at < NOW() - %s::INTERVAL
          AND issued_at > NOW() - %s::INTERVAL
        """,
        (f"{int(min_age_hours)} hours", f"{int(max_age_days)} days"),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_active_plans_in_portfolio(max_age_days: int = 45):
    """ดึง Plan ที่ symbol นั้น user ถือจริงในพอร์ต (JOIN portfolios) — สำหรับ proximity warning

    เปลี่ยนจาก "wait for all open plans" → "เฉพาะ plan ของหุ้นที่ user ถือจริง"
    เหตุผล: user scan หุ้น 10 ตัวเพื่อ research ≠ ต้องการ alert ทุกตัว
    Plans ของหุ้นใน portfolio = user มี skin in the game = alert ตรงประเด็น
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT ap.id, ap.user_id, ap.symbol, ap.bias, ap.entry_low, ap.entry_high,
                   ap.tp1, ap.tp2, ap.sl, ap.price_at_issue, ap.issued_at,
                   p.shares, p.avg_cost
            FROM analysis_plans ap
            INNER JOIN portfolios p
              ON TRIM(ap.user_id) = TRIM(p.user_id)
             AND UPPER(ap.symbol) = UPPER(p.ticker)
            WHERE ap.outcome = 'open'
              AND ap.issued_at > NOW() - %s::INTERVAL
              AND ap.tp1 IS NOT NULL
              AND ap.sl IS NOT NULL
              AND COALESCE(p.shares, 0) > 0
            ORDER BY ap.symbol, ap.issued_at DESC
            """,
            (f"{int(max_age_days)} days",),
        )
        rows = c.fetchall()
    except Exception as e:
        print(f"[get_active_plans_in_portfolio] err: {e}", flush=True)
        return []
    finally:
        conn.close()
    return [
        {
            "id": r[0], "user_id": str(r[1]), "symbol": r[2], "bias": r[3],
            "entry_low": float(r[4]) if r[4] is not None else None,
            "entry_high": float(r[5]) if r[5] is not None else None,
            "tp1": float(r[6]) if r[6] is not None else None,
            "tp2": float(r[7]) if r[7] is not None else None,
            "sl": float(r[8]) if r[8] is not None else None,
            "price_at_issue": float(r[9]) if r[9] is not None else None,
            "issued_at": r[10],
            "shares": float(r[11]) if r[11] is not None else 0,
            "avg_cost": float(r[12]) if r[12] is not None else 0,
        }
        for r in rows
    ]


# Backward-compat alias (deprecated — ใช้ get_active_plans_in_portfolio แทน)
def get_active_plans_for_proximity(max_age_days: int = 45):
    return get_active_plans_in_portfolio(max_age_days)


def update_plan_outcome(plan_id, outcome, outcome_note=""):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE analysis_plans
            SET outcome = %s, outcome_at = CURRENT_TIMESTAMP, outcome_note = %s
            WHERE id = %s
        """, (outcome, outcome_note[:200], plan_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[update_plan_outcome] error: {e}")
    finally:
        conn.close()


def expire_stale_plans(max_age_days=45):
    """Mark แผนที่เกิน 45 วันยังไม่ hit อะไรเป็น expired"""
    conn = get_connection()
    c = conn.cursor()
    try:
        # 🐛 Fix: bug เดียวกับ get_pending_plans — INTERVAL ใน string literal
        c.execute(
            """
            UPDATE analysis_plans
            SET outcome = 'expired', outcome_at = CURRENT_TIMESTAMP
            WHERE outcome = 'open'
              AND issued_at < NOW() - %s::INTERVAL
            """,
            (f"{int(max_age_days)} days",),
        )
        conn.commit()
    except Exception as e:
        print(f"[expire_stale_plans] err: {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()


def _thai_today():
    """Return today's date in Asia/Bangkok timezone (UTC+7)"""
    return (datetime.utcnow() + timedelta(hours=7)).date()


def update_user_streak(user_id):
    """อัปเดต daily streak เมื่อ user ทำ action (เช่น วิเคราะห์หุ้น)
    ใช้ Thai date (UTC+7) — กัน server timezone ทำให้ streak นับผิด
    คืน dict: {current, is_new_day, milestone_7days, longest}
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT streak_count, last_streak_date, longest_streak FROM users WHERE user_id=%s",
                  (str(user_id),))
        row = c.fetchone()
        if not row:
            print(f"[streak] user {user_id} not found in users table", flush=True)
            return {"current": 0, "is_new_day": False, "milestone_7days": False, "longest": 0}

        current_streak = int(row[0] or 0)
        last_date = row[1]
        longest = int(row[2] or 0)
        today = _thai_today()

        # ถ้าวันเดียวกัน (เทียบ Thai date) — ไม่ count ซ้ำ
        if last_date == today:
            return {"current": current_streak, "is_new_day": False, "milestone_7days": False, "longest": longest}

        # ถ้าเมื่อวาน — +1 (ต่อเนื่อง)
        if last_date == today - timedelta(days=1):
            new_streak = current_streak + 1
        else:
            # ขาดวัน หรือ first time → เริ่มใหม่ที่ 1
            new_streak = 1

        new_longest = max(longest, new_streak)
        c.execute("""
            UPDATE users SET streak_count=%s, last_streak_date=%s, longest_streak=%s
            WHERE user_id=%s
        """, (new_streak, today, new_longest, str(user_id)))
        conn.commit()

        milestone = (new_streak > 0 and new_streak % 7 == 0)
        print(f"[streak] user={user_id} streak={current_streak}→{new_streak} milestone={milestone}", flush=True)
        return {
            "current": new_streak,
            "is_new_day": True,
            "milestone_7days": milestone,
            "longest": new_longest,
        }
    except Exception as e:
        conn.rollback()
        # 🌟 Surface error เพื่อ debug — ไม่ silent fail
        import traceback
        print(f"[streak] ERROR user={user_id}: {e}\n{traceback.format_exc()}", flush=True)
        return {"current": 0, "is_new_day": False, "milestone_7days": False, "longest": 0}
    finally:
        conn.close()


def grant_streak_reward(user_id, days=1):
    """ให้รางวัล streak milestone — เพิ่มวัน VIP (หรือต่อ role ที่มีอยู่)

    กัน bug:
    - Admin: ข้าม DB write เพราะอาจทำให้ role column เพี้ยน
      (admin ได้ PRO infinite ผ่าน check_subscription อยู่แล้ว)
    - CASE statement: keep vip/pro; roles อื่น (free/admin) → vip
    - expiry: ใช้ GREATEST + COALESCE กันเคส expiry_date เป็น NULL หรือ past
    """
    try:
        from config import ADMIN_ID as _ADMIN_ID
        if _ADMIN_ID and str(user_id) == str(_ADMIN_ID):
            # Admin ได้ PRO infinite อยู่แล้ว — ไม่ต้อง update DB
            print(f"[streak_reward] admin {user_id} — skip DB update (already infinite PRO)", flush=True)
            return True
    except Exception:
        pass

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE users SET
                role = CASE WHEN role IN ('vip', 'pro') THEN role ELSE 'vip' END,
                expiry_date = GREATEST(COALESCE(expiry_date::timestamp, NOW()), NOW()) + (%s || ' days')::INTERVAL
            WHERE user_id = %s
        """, (str(days), str(user_id)))
        affected = c.rowcount
        conn.commit()
        if affected == 0:
            print(f"[streak_reward] user {user_id} not found in users — skipped", flush=True)
            return False
        print(f"[streak_reward] user {user_id} +{days} day(s) VIP granted", flush=True)
        return True
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"[streak_reward] ERROR user={user_id}: {e}\n{traceback.format_exc()}", flush=True)
        return False
    finally:
        conn.close()


def get_streak_info(user_id):
    """ดึงข้อมูล streak ปัจจุบันของ user (ไม่อัปเดต)"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT streak_count, last_streak_date, longest_streak FROM users WHERE user_id=%s",
                  (str(user_id),))
        row = c.fetchone()
        if not row:
            return {"current": 0, "longest": 0, "last_date": None}
        return {
            "current": int(row[0] or 0),
            "longest": int(row[2] or 0),
            "last_date": row[1],
        }
    finally:
        conn.close()


def get_track_record_stats(days=30, user_id=None):
    """สถิติ outcome ในช่วง N วันที่ผ่านมา
    คืน dict: {total, tp1_hit, tp2_hit, sl_hit, expired, open, hit_rate_pct}
    """
    conn = get_connection()
    c = conn.cursor()
    where = "issued_at > NOW() - INTERVAL '%s days'"
    params = [days]
    if user_id:
        where += " AND user_id = %s"
        params.append(str(user_id))
    c.execute(f"""
        SELECT outcome, COUNT(*)
        FROM analysis_plans
        WHERE {where}
        GROUP BY outcome
    """, tuple(params))
    counts = {row[0]: int(row[1]) for row in c.fetchall()}
    conn.close()
    tp1 = counts.get('tp1_hit', 0)
    tp2 = counts.get('tp2_hit', 0)
    sl = counts.get('sl_hit', 0)
    expired = counts.get('expired', 0)
    no_entry = counts.get('no_entry', 0)
    open_count = counts.get('open', 0)
    # 🛡 Hit rate ดู "ที่เข้า trade ได้จริง" — exclude no_entry (ไม่ได้เข้า = ไม่ได้กำไรขาดทุน)
    closed_with_entry = tp1 + tp2 + sl + expired
    total = closed_with_entry + no_entry + open_count
    wins = tp1 + tp2
    hit_rate = (wins / closed_with_entry * 100) if closed_with_entry > 0 else 0.0
    return {
        "total": total,
        "closed": closed_with_entry,
        "open": open_count,
        "tp1_hit": tp1,
        "tp2_hit": tp2,
        "sl_hit": sl,
        "expired": expired,
        "no_entry": no_entry,
        "wins": wins,
        "hit_rate_pct": hit_rate,
    }


def get_track_record_by_symbol(symbol, days=90):
    """สถิติ track record ของ symbol นี้โดยเฉพาะ ใน N วันล่าสุด
    คืน dict เดียวกับ get_track_record_stats — ใช้แสดงใน per-symbol footer
    """
    if not symbol:
        return None
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT outcome, COUNT(*)
            FROM analysis_plans
            WHERE UPPER(symbol) = %s
              AND issued_at > NOW() - INTERVAL %s
            GROUP BY outcome
            """,
            (str(symbol).upper(), f"{int(days)} days"),
        )
        counts = {row[0]: int(row[1]) for row in c.fetchall()}
    except Exception as e:
        print(f"[track-by-symbol] err: {e}", flush=True)
        counts = {}
    finally:
        conn.close()
    tp1 = counts.get('tp1_hit', 0)
    tp2 = counts.get('tp2_hit', 0)
    sl = counts.get('sl_hit', 0)
    expired = counts.get('expired', 0)
    no_entry = counts.get('no_entry', 0)
    open_count = counts.get('open', 0)
    closed_with_entry = tp1 + tp2 + sl + expired
    wins = tp1 + tp2
    hit_rate = (wins / closed_with_entry * 100) if closed_with_entry > 0 else 0.0
    return {
        "symbol": str(symbol).upper(),
        "closed": closed_with_entry,
        "open": open_count,
        "tp1_hit": tp1,
        "tp2_hit": tp2,
        "sl_hit": sl,
        "expired": expired,
        "no_entry": no_entry,
        "wins": wins,
        "hit_rate_pct": hit_rate,
    }


def get_recent_wins(days: int = 30, limit: int = 5) -> list[dict]:
    """ดึง trades ล่าสุดที่ "ชนะ" (tp1_hit / tp2_hit) — เรียงตาม outcome_at desc

    ใช้ใน /track section "Recent Wins" — social proof + trust signal
    Returns: list of dict { symbol, outcome, bias, tp1, tp2, entry_low, entry_high,
                            outcome_note, issued_at, outcome_at, gain_pct (estimated) }
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT UPPER(symbol), outcome, bias, tp1, tp2, entry_low, entry_high,
                   outcome_note, issued_at, outcome_at, price_at_issue
            FROM analysis_plans
            WHERE outcome IN ('tp1_hit', 'tp2_hit')
              AND outcome_at IS NOT NULL
              AND outcome_at > NOW() - %s::INTERVAL
            ORDER BY outcome_at DESC
            LIMIT %s
            """,
            (f"{int(days)} days", int(limit)),
        )
        rows = c.fetchall() or []
    except Exception as e:
        print(f"[recent-wins] err: {e}", flush=True)
        rows = []
    finally:
        conn.close()

    items = []
    seen_symbols = set()    # dedup — 1 win per symbol max ใน showcase
    for row in rows:
        sym, outcome, bias, tp1, tp2, e_low, e_high, note, issued_at, outcome_at, price_at_issue = row
        if sym in seen_symbols:
            continue
        try:
            entry_mid = (float(e_low) + float(e_high)) / 2 if e_low and e_high else float(price_at_issue or 0)
            target_val = float(tp2) if outcome == 'tp2_hit' else float(tp1) if tp1 else 0
            gain_pct = ((target_val - entry_mid) / entry_mid * 100) if entry_mid else 0
            hold_days = (outcome_at - issued_at).days if (outcome_at and issued_at) else None
        except Exception:
            gain_pct = 0
            hold_days = None
            target_val = 0

        # Skip outlier — gain > 100% น่าจะ data corruption (split, bad TP, wrong entry)
        # User เห็น "RPGL +130%" จะคิดว่า unrealistic → trust signal ลด
        if abs(gain_pct) > 100:
            continue

        seen_symbols.add(sym)
        items.append({
            "symbol": sym,
            "outcome": outcome,
            "bias": bias,
            "gain_pct": gain_pct,
            "hold_days": hold_days,
            "outcome_at": outcome_at,
            "target": target_val,
            "note": note or "",
        })
    return items


def get_top_performing_symbols(days=90, limit=5, min_plans=3):
    """ดึง top N symbols ตาม hit rate ใน N วัน (กรอง min_plans กันเลขเล็กน้อยมา bias)
    คืน list of dict {symbol, closed, wins, hit_rate_pct}
    เรียงตาม hit_rate_pct desc, ตาม closed desc สำหรับ tie-break
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            f"""
            SELECT
              UPPER(symbol) AS sym,
              SUM(CASE WHEN outcome IN ('tp1_hit','tp2_hit','sl_hit','expired') THEN 1 ELSE 0 END) AS closed,
              SUM(CASE WHEN outcome IN ('tp1_hit','tp2_hit') THEN 1 ELSE 0 END) AS wins
            FROM analysis_plans
            WHERE issued_at > NOW() - INTERVAL %s
            GROUP BY UPPER(symbol)
            HAVING SUM(CASE WHEN outcome IN ('tp1_hit','tp2_hit','sl_hit','expired') THEN 1 ELSE 0 END) >= %s
            """,
            (f"{int(days)} days", int(min_plans)),
        )
        rows = c.fetchall() or []
    except Exception as e:
        print(f"[top-symbols] err: {e}", flush=True)
        rows = []
    finally:
        conn.close()

    items = []
    for row in rows:
        sym, closed, wins = row[0], int(row[1] or 0), int(row[2] or 0)
        if closed == 0:
            continue
        items.append({
            "symbol": sym,
            "closed": closed,
            "wins": wins,
            "hit_rate_pct": (wins / closed * 100),
        })
    items.sort(key=lambda x: (-x["hit_rate_pct"], -x["closed"]))
    return items[:int(limit)]


def calculate_hypothetical_return(days=90, risk_per_trade_pct=1.0):
    """คำนวณ return ทฤษฎีถ้า follow ทุก plan ตามจำนวน % risk/trade
    Assumptions:
      - tp1_hit  → return = (tp1 - entry_mid) / entry_mid * (target_R / risk) * risk_per_trade
        คำนวณ R:R จาก |tp1-entry| / |entry-sl|
      - tp2_hit  → ใช้ tp2
      - sl_hit   → return = -risk_per_trade (เสีย 1R)
      - expired  → return = 0 (เกินกรอบเวลา ไม่นับ)
    คืน dict {total_plans, total_return_pct, win_count, loss_count, expired_count}
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        # 🛡 exclude 'no_entry' — ไม่ได้เข้า trade = no return contribution
        c.execute(
            """
            SELECT entry_low, entry_high, tp1, tp2, sl, outcome
            FROM analysis_plans
            WHERE issued_at > NOW() - INTERVAL %s
              AND outcome IN ('tp1_hit', 'tp2_hit', 'sl_hit', 'expired')
            """,
            (f"{int(days)} days",),
        )
        rows = c.fetchall() or []
    except Exception as e:
        print(f"[hypothetical] err: {e}", flush=True)
        rows = []
    finally:
        conn.close()

    total_return = 0.0
    win_count = 0
    loss_count = 0
    expired_count = 0
    for row in rows:
        entry_low, entry_high, tp1, tp2, sl, outcome = row
        try:
            entry = (float(entry_low or 0) + float(entry_high or 0)) / 2.0
            tp1_v = float(tp1 or 0)
            tp2_v = float(tp2 or 0)
            sl_v = float(sl or 0)
        except (TypeError, ValueError):
            continue
        if entry <= 0 or sl_v <= 0:
            continue
        risk_distance = abs(entry - sl_v)
        if risk_distance <= 0:
            continue

        if outcome == 'tp1_hit':
            r_multiple = abs(tp1_v - entry) / risk_distance if tp1_v > 0 else 1.0
            total_return += risk_per_trade_pct * r_multiple
            win_count += 1
        elif outcome == 'tp2_hit':
            r_multiple = abs(tp2_v - entry) / risk_distance if tp2_v > 0 else 2.0
            total_return += risk_per_trade_pct * r_multiple
            win_count += 1
        elif outcome == 'sl_hit':
            total_return -= risk_per_trade_pct
            loss_count += 1
        else:  # expired
            expired_count += 1

    return {
        "total_plans": len(rows),
        "total_return_pct": total_return,
        "win_count": win_count,
        "loss_count": loss_count,
        "expired_count": expired_count,
        "risk_per_trade_pct": risk_per_trade_pct,
    }


def add_promo_code(code, days, max_uses, role_type='vip', discount_pct=None, window_hours=0):
    """สร้าง promo code — รองรับ 2 mode:
    1. Days mode (default): discount_pct=None → user redeem ได้ subscription +days ทันที
    2. Discount mode: discount_pct=10/15/20/.../50 + window_hours > 0
       → user redeem แล้วเปิด discount window ใน users
       → user โอนยอดส่วนลด → slip handler เช็ค window + grant
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO promo_codes (code, days, max_uses, current_uses, used_by, role_type, discount_pct, window_hours) "
            "VALUES (%s, %s, %s, 0, '', %s, %s, %s)",
            (code, days, max_uses, role_type,
             int(discount_pct) if discount_pct else None,
             int(window_hours) if window_hours else 0),
        )
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def redeem_code(user_id, code):
    """Redeem promo code — รองรับ 2 mode

    Returns: (success:bool, days_or_label, expiry_or_amount, role_type)
    - Days mode: (True, days, expiry_str, role)
    - Discount mode: (True, "discount", {"pct":20, "amount":63, "until":...}, role)
    - Fail: (False, "already_used_by_you" / "fully_used" / None, None, None)
    """
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
        # Success — เลือก mode ตาม discount_pct
        c.execute(
            "SELECT days, role_type, discount_pct, window_hours FROM promo_codes WHERE code=%s",
            (code,),
        )
        row = c.fetchone()
        if not row:
            conn.close()
            return False, None, None, None
        days, role_type, discount_pct, window_hours = row

        # 🎟 Discount mode — เปิด window แทนการ add subscription
        if discount_pct and discount_pct > 0:
            from datetime import timedelta
            window_h = int(window_hours or 24)
            until = datetime.now() + timedelta(hours=window_h)
            # คำนวณยอดส่วนลด: VIP 79 / PRO 109 → discounted
            vip_amount = round(79 * (1 - discount_pct / 100.0))
            pro_amount = round(109 * (1 - discount_pct / 100.0))
            try:
                c.execute(
                    "UPDATE users SET discount_amount_vip=%s, discount_amount_pro=%s, "
                    "discount_until=%s, discount_code=%s WHERE user_id=%s",
                    (
                        vip_amount, pro_amount,
                        until.strftime('%Y-%m-%d %H:%M:%S'),
                        str(code), str(user_id),
                    ),
                )
                conn.commit()
            except Exception as e:
                print(f"[redeem-discount] err: {e}", flush=True)
                conn.rollback()
                conn.close()
                return False, None, None, None
            conn.close()
            return True, "discount", {
                "pct": int(discount_pct),
                "vip_amount": vip_amount,
                "pro_amount": pro_amount,
                "until": until,
                "window_hours": window_h,
            }, role_type

        # 🎁 Days mode (existing) — add subscription ทันที
        conn.close()
        # Detect tier reward code (BRONZE_xxx / SILVER_xxx / GOLD_xxx) → log as tier_reward
        # ปกติ redeem code → log as redeem
        upper_code = str(code).upper()
        is_tier_reward = upper_code.startswith(("BRONZE_", "SILVER_", "GOLD_"))
        action_type = "tier_reward" if is_tier_reward else "redeem"
        expiry = add_subscription(
            user_id, role_type, days,
            source=action_type,
            source_detail=str(code),
            meta={"days": days, "role_type": role_type},
        )
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


# 🎟 Discount window helpers — ใช้กับ slip handler
def get_user_discount(user_id):
    """คืนสถานะ discount ของ user — dict หรือ None ถ้าไม่มี/หมดเวลา
    {"vip_amount", "pro_amount", "until", "code"}
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT discount_amount_vip, discount_amount_pro, discount_until, discount_code "
        "FROM users WHERE user_id=%s",
        (str(user_id),),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    vip_amt, pro_amt, until, code = row
    if not until:
        return None
    try:
        until_dt = until if isinstance(until, datetime) else datetime.fromisoformat(str(until).replace('T', ' '))
        until_dt = until_dt.replace(tzinfo=None) if until_dt.tzinfo else until_dt
        if datetime.now() >= until_dt:
            return None
    except Exception:
        return None
    return {
        "vip_amount": int(vip_amt) if vip_amt else None,
        "pro_amount": int(pro_amt) if pro_amt else None,
        "until": until_dt,
        "code": str(code or ""),
    }


def consume_user_discount(user_id):
    """ปิด discount window หลัง user ใช้สำเร็จ — clear ทุก field"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET discount_amount_vip=NULL, discount_amount_pro=NULL, "
            "discount_until=NULL, discount_code=NULL WHERE user_id=%s",
            (str(user_id),),
        )
        conn.commit()
    except Exception as e:
        print(f"[consume-discount] err: {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()

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

def claim_slip_and_add_subscription(user_id: str, ref_no: str, role: str, days: int, payment_type: str = 'standard', amount: float | None = None) -> tuple[str, str | None]:
    conn = get_connection()
    c = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """
            INSERT INTO used_slips (ref_no, user_id, date_used, payment_type, amount)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ref_no) DO NOTHING
            RETURNING ref_no
            """,
            (str(ref_no), str(user_id), now_str, str(payment_type or 'standard'), float(amount) if amount else None),
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

        # 🛡️ ปฏิเสธ downgrade ถ้ายังมี subscription ที่สูงกว่า active อยู่
        # เคส: PRO ยังไม่หมดอายุ + จ่าย VIP → block + แจ้ง admin คืนเงิน
        if role == 'vip' and current_role == 'pro' and current_expiry:
            try:
                if isinstance(current_expiry, datetime):
                    cur_exp_dt = current_expiry.replace(tzinfo=None)
                else:
                    cur_exp_dt = datetime.fromisoformat(
                        str(current_expiry).strip().replace('T', ' ')
                    ).replace(tzinfo=None)
                if cur_exp_dt > now:
                    # คงสลิปใน used_slips ไว้ (ลูกค้าโอนเงินจริง) ไม่ rollback
                    conn.commit()
                    return "downgrade_blocked", cur_exp_dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                pass

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

        # 📜 Log subscription history (defensive — outside transaction)
        try:
            log_subscription_event(
                user_id=user_id,
                action_type="paid",
                role_before=current_role,
                role_after=role,
                expiry_before=current_expiry,
                expiry_after=expiry_str,
                days_granted=days,
                source="slip",
                source_detail=f"slip {amount:.0f}฿" if amount else f"slip ({payment_type})",
                meta={"ref_no": str(ref_no), "payment_type": payment_type, "amount": amount},
            )
        except Exception as _e:
            print(f"[slip-claim] log err: {_e}", flush=True)

        return "success", expiry_str
    except Exception as e:
        print(f"Slip Claim Error: {e}")
        conn.rollback()
        return "error", None
    finally:
        conn.close()


def claim_slip_and_add_topup(user_id: str, ref_no: str, count: int, amount: float | None = None) -> tuple[str, int | None]:
    """ใช้สลิปเติม top-up balance — ไม่เปลี่ยน role/expiry แค่บวก credits

    Returns: (status, new_balance_or_None)
    status:
      - "duplicate" — สลิป ref_no นี้เคยใช้แล้ว
      - "success" — เติมสำเร็จ คืน balance ใหม่
      - "error" — DB error
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            """
            INSERT INTO used_slips (ref_no, user_id, date_used, payment_type, amount)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ref_no) DO NOTHING
            RETURNING ref_no
            """,
            (str(ref_no), str(user_id), now_str, 'topup', float(amount) if amount else None),
        )
        if c.fetchone() is None:
            return "duplicate", None

        c.execute(
            "UPDATE users SET topup_balance = COALESCE(topup_balance, 0) + %s "
            "WHERE user_id=%s "
            "RETURNING topup_balance",
            (int(count), str(user_id)),
        )
        row = c.fetchone()
        if not row:
            conn.rollback()
            return "error", None
        new_balance = int(row[0]) if row[0] is not None else int(count)
        conn.commit()
        return "success", new_balance
    except Exception as e:
        print(f"Topup Claim Error: {e}")
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
    # 🌟 Track Record — log ทุก Plan ที่ออกให้ PRO เพื่อตรวจ outcome ภายหลัง
    c.execute("""
        CREATE TABLE IF NOT EXISTS analysis_plans (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            symbol TEXT NOT NULL,
            bias TEXT NOT NULL,
            entry_low NUMERIC,
            entry_high NUMERIC,
            tp1 NUMERIC,
            tp2 NUMERIC,
            sl NUMERIC,
            price_at_issue NUMERIC,
            issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            outcome TEXT DEFAULT 'open',
            outcome_at TIMESTAMP,
            outcome_note TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_plans_outcome_issued ON analysis_plans(outcome, issued_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_plans_symbol ON analysis_plans(symbol)")
    for col_ddl in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_used BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_vip_given BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP",
        # 🌟 Daily Streak columns
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_streak_date DATE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_streak INTEGER DEFAULT 0",
    ]:
        try:
            c.execute(col_ddl)
            conn.commit()
        except Exception:
            conn.rollback()

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

    for col_ddl in [
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE", None),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT %s", (DEFAULT_USER_TIMEZONE,)),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT %s", (DEFAULT_USER_LANGUAGE,)),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS digest_frequency_hours INTEGER NOT NULL DEFAULT %s", (DEFAULT_DIGEST_FREQUENCY_HOURS,)),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS news_start_hour INTEGER NOT NULL DEFAULT %s", (DEFAULT_NEWS_START_HOUR,)),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS news_end_hour INTEGER NOT NULL DEFAULT %s", (DEFAULT_NEWS_END_HOUR,)),
        ("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS last_digest_sent_at TIMESTAMPTZ", None),
    ]:
        sql, params = col_ddl
        try:
            c.execute(sql, params) if params else c.execute(sql)
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
    รางวัล Referrer:
      - ทุก referral → ลด usage_count 3 (สำหรับ free) = +3 quota
      - ทุก 3 referrals → upgrade เป็น VIP + ต่อ 10 วัน (milestone)
    รางวัล Referred (v2 ใหม่):
      - ทุก new user ผ่านลิงก์ → ได้ VIP ฟรี 3 วัน (welcome bonus)
    """
    # Defense-in-depth — main.py:808 already guards /start REF_ flow,
    # but admin /award_ref + uid-input paths reach here too. Block the
    # easiest exploit: claiming yourself as referrer to farm milestones.
    if str(referrer_id) == str(new_user_id):
        return False, False

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM users WHERE user_id = %s", (new_user_id,))
        if c.fetchone():
            return False, False

        c.execute(
            "INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s) ON CONFLICT (referred_id) DO NOTHING",
            (referrer_id, new_user_id),
        )
        # Bail if INSERT was a no-op (referred_id already credited to someone).
        # Without this, a re-call computes new_count from the existing rows and
        # could re-fire milestone bonuses on every retry — silent VIP leak.
        if c.rowcount == 0:
            conn.commit()
            return False, False

        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (referrer_id,))
        new_count = c.fetchone()[0]

        milestone_hit = (new_count % 3 == 0)

        # 🛡️ ใช้ check_subscription เพื่อให้ใช้ effective tier (เคารพ expiry)
        # กันเคส role='pro' ค้างใน DB (หมดอายุแล้ว) → ได้ bonus PRO ฟรี
        effective_role = check_subscription(referrer_id)

        if milestone_hit:
            if effective_role == 'pro':
                # PRO active → คง PRO + ต่อ 10 วัน
                c.execute("""
                    UPDATE users SET
                        expiry_date = GREATEST(COALESCE(expiry_date, NOW()), NOW()) + INTERVAL '10 days'
                    WHERE user_id = %s
                """, (referrer_id,))
            else:
                # Free, VIP active, หรือ premium หมดอายุ → upgrade/extend VIP
                c.execute("""
                    UPDATE users SET
                        role = 'vip',
                        expiry_date = GREATEST(COALESCE(expiry_date, NOW()), NOW()) + INTERVAL '10 days'
                    WHERE user_id = %s
                """, (referrer_id,))
        else:
            if effective_role == 'free':
                c.execute("UPDATE users SET usage_count = GREATEST(0, usage_count - 3) WHERE user_id = %s", (referrer_id,))

        # 🌟 Referred user bonus — VIP 3 วันฟรี (v2 ใหม่)
        # ใช้ INSERT ON CONFLICT DO UPDATE เพราะ new user อาจยังไม่มี row
        c.execute("""
            INSERT INTO users (user_id, role, expiry_date, registered_date, status)
            VALUES (%s, 'vip', NOW() + INTERVAL '3 days', NOW(), 'active')
            ON CONFLICT (user_id) DO UPDATE SET
                role = CASE WHEN users.role IN ('vip', 'pro') THEN users.role ELSE 'vip' END,
                expiry_date = GREATEST(COALESCE(users.expiry_date, NOW()), NOW()) + INTERVAL '3 days'
        """, (new_user_id,))

        conn.commit()
        return True, milestone_hit
    except Exception as e:
        print(f"Referral Error: {e}")
        conn.rollback()
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
def is_first_audit_done(user_id) -> bool:
    """True if the one-shot Free portfolio audit has already been delivered."""
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT first_audit_done FROM users WHERE user_id = %s", (str(user_id),))
        row = c.fetchone()
        return bool(row and row[0])
    except Exception as e:
        print(f"[is_first_audit_done] {e}", flush=True)
        return True  # fail-safe: don't re-fire audit on DB error
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def mark_first_audit_done(user_id) -> None:
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "UPDATE users SET first_audit_done = TRUE WHERE user_id = %s",
            (str(user_id),),
        )
        conn.commit()
    except Exception as e:
        print(f"[mark_first_audit_done] {e}", flush=True)
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def auto_downgrade_expired_users():
    """ปรับสถานะคนที่หมดอายุให้กลับเป็น free อัตโนมัติ + log history

    🐛 Bug fix 2026-05-14: expiry_date เป็น text → ต้อง cast เป็น timestamptz
    ก่อนนำมาเปรียบเทียบกับ NOW() ไม่งั้น Postgres raise error 42883
    (operator does not exist: text < timestamp) → silent fail ตลอด
    ทำให้ user 18 คน expired แล้วยังใช้ PRO/VIP features ฟรี
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        # หา users ที่ต้อง downgrade (เพื่อ log ก่อน update)
        # ✋ Cast expiry_date::timestamptz เพราะ DB schema เก็บเป็น text
        # ใช้ NULLIF เพื่อกัน case ค่าว่าง '' ซึ่งจะทำให้ cast fail
        c.execute("""
            SELECT user_id, role, expiry_date FROM users
            WHERE role IN ('vip', 'pro')
              AND expiry_date IS NOT NULL
              AND NULLIF(expiry_date, '')::timestamptz < NOW()
        """)
        expired = c.fetchall() or []

        # หมดอายุทั้งหมด (PRO, VIP, free trial) → free ทันที
        c.execute("""
            UPDATE users SET role = 'free'
            WHERE role IN ('vip', 'pro')
              AND expiry_date IS NOT NULL
              AND NULLIF(expiry_date, '')::timestamptz < NOW()
        """)
        conn.commit()
        print(f"✅ Auto-Downgrade: downgraded {len(expired)} expired users", flush=True)
    except Exception as e:
        print(f"❌ Auto-Downgrade Error: {e}", flush=True)
        conn.rollback()
        expired = []
    finally:
        conn.close()

    # 📜 Log expire events (defensive — outside transaction)
    for row in expired:
        try:
            uid, old_role, old_expiry = row[0], row[1], row[2]
            log_subscription_event(
                user_id=uid,
                action_type="expire",
                role_before=old_role,
                role_after="free",
                expiry_before=old_expiry,
                expiry_after=None,
                source="cron",
                source_detail="auto_downgrade_expired_users",
            )
        except Exception as _e:
            print(f"[auto_downgrade] log err: {_e}", flush=True)
# ==========================================
# 🌟 [เพิ่มใหม่] ระบบจัดการพอร์ตลงทุน (Apex Wealth Master)
# ==========================================
def add_portfolio_stock(user_id, ticker, shares, avg_cost):
    """บันทึกหุ้นเข้าพอร์ต — คืน True ถ้าเพิ่มใหม่, False ถ้า ticker ซ้ำในพอร์ต"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO portfolios (user_id, ticker, shares, avg_cost)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, ticker) DO NOTHING
            """,
            (str(user_id), ticker.upper(), float(shares), float(avg_cost)),
        )
        inserted = (c.rowcount or 0) > 0
        conn.commit()
        return inserted
    finally:
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

def delete_portfolio_stock(user_id, ticker):
    """ลบหุ้น 1 ตัวออกจากพอร์ต — คืน True ถ้ามีแถวถูกลบ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "DELETE FROM portfolios WHERE user_id = %s AND ticker = %s",
            (str(user_id), ticker.upper()),
        )
        deleted = c.rowcount or 0
        conn.commit()
        return deleted > 0
    finally:
        conn.close()

def update_portfolio_stock(user_id, ticker, shares, avg_cost):
    """แก้จำนวนหุ้น/ราคาเฉลี่ยของ ticker เดิม — คืน True ถ้ามีแถวถูกอัปเดต"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE portfolios SET shares = %s, avg_cost = %s WHERE user_id = %s AND ticker = %s",
            (float(shares), float(avg_cost), str(user_id), ticker.upper()),
        )
        updated = c.rowcount or 0
        conn.commit()
        return updated > 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# 💰 Cash Balance — portfolio NAV component (USD)
# Requested by nuttapon (Annual PRO #1) 2026-05-16
# Option B: full audit trail via cash_transactions log
# ─────────────────────────────────────────────────────────────────
def get_user_cash_balance(user_id) -> float:
    """ดึงเงินสดเหลือในพอร์ต (USD) — default 0"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT cash_balance FROM users WHERE user_id = %s", (str(user_id),))
        row = c.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception as e:
        print(f"[get_user_cash_balance] {e}", flush=True)
        return 0.0
    finally:
        conn.close()


def _log_cash_transaction(c, user_id, action_type: str, delta: float,
                          balance_before: float, balance_after: float, note: str = None):
    """Internal — insert audit row. Caller controls conn/commit."""
    c.execute(
        """
        INSERT INTO cash_transactions (user_id, action_type, delta, balance_before, balance_after, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (str(user_id), action_type, float(delta), float(balance_before), float(balance_after), note),
    )


def apply_cash_action(user_id, action_type: str, amount: float, note: str = None,
                       log_to_history: bool = True) -> dict:
    """แก้ไขเงินสด + (optional) log transaction.

    action_type: 'set' | 'deposit' | 'withdraw'
    amount: USD positive number (interpretation depends on action_type)
    log_to_history: when True (default) — log to cash_transactions audit trail.

    Returns: {'ok': bool, 'balance_before': float, 'balance_after': float,
              'delta': float, 'error': str|None}
    """
    if action_type not in ('set', 'deposit', 'withdraw'):
        return {'ok': False, 'error': f'invalid action_type: {action_type}'}
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'amount must be a number'}
    if amount < 0:
        return {'ok': False, 'error': 'amount must be >= 0'}

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT cash_balance FROM users WHERE user_id = %s", (str(user_id),))
        row = c.fetchone()
        balance_before = float(row[0]) if row and row[0] is not None else 0.0

        if action_type == 'set':
            balance_after = amount
        elif action_type == 'deposit':
            balance_after = balance_before + amount
        else:  # withdraw
            balance_after = max(0.0, balance_before - amount)

        delta = balance_after - balance_before

        c.execute(
            "UPDATE users SET cash_balance = %s WHERE user_id = %s",
            (balance_after, str(user_id)),
        )
        if c.rowcount and c.rowcount > 0:
            if log_to_history:
                _log_cash_transaction(c, user_id, action_type, delta, balance_before, balance_after, note)
            conn.commit()
            return {
                'ok': True,
                'balance_before': balance_before,
                'balance_after': balance_after,
                'delta': delta,
                'error': None,
            }
        else:
            return {'ok': False, 'error': 'user not found'}
    except Exception as e:
        print(f"[apply_cash_action] {e}", flush=True)
        try:
            conn.rollback()
        except Exception:
            pass
        return {'ok': False, 'error': str(e)}
    finally:
        conn.close()


def set_user_cash_balance(user_id, amount: float) -> bool:
    """Backwards-compat wrapper — sets cash via apply_cash_action('set', ...)."""
    result = apply_cash_action(user_id, 'set', amount, note='legacy set')
    return result.get('ok', False)


def get_cash_transactions(user_id, limit: int = 50) -> list:
    """ดึงประวัติ cash transactions ล่าสุด — ใหม่สุดก่อน"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, action_type, delta, balance_before, balance_after, note, created_at
            FROM cash_transactions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (str(user_id), int(limit)),
        )
        rows = c.fetchall() or []
        return [
            {
                'id': r[0],
                'action_type': r[1],
                'delta': float(r[2]),
                'balance_before': float(r[3]) if r[3] is not None else None,
                'balance_after': float(r[4]),
                'note': r[5],
                'created_at': r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[get_cash_transactions] {e}", flush=True)
        return []
    finally:
        conn.close()
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


def reset_free_trial(user_id: str) -> bool:
    """รีเซ็ต flag free_trial_used เป็น FALSE — สำหรับ refund / support
    คืน True ถ้ามีแถวถูกอัปเดต"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE users SET free_trial_used = FALSE WHERE user_id = %s",
            (str(user_id),),
        )
        updated = (c.rowcount or 0) > 0
        conn.commit()
        return updated
    finally:
        conn.close()


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


# ==========================================
# Breaking News Alert — subscribers + log helpers
# ==========================================

def is_breaking_news_seen(url_hash: str) -> bool:
    """Dedup check — has this article already been classified?"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM breaking_news_log WHERE url_hash = %s LIMIT 1",
                  (url_hash,))
        return c.fetchone() is not None
    finally:
        conn.close()


def _ensure_breaking_news_published_at_column(c) -> None:
    """Idempotent migration — adds published_at column if missing.

    Added 2026-05-17 after nuttapon flagged 2-7 day old "breaking" news being
    shown. We now store the article's actual publish time so the frontend can
    display it instead of classified_at (= when bot processed, misleading).
    """
    try:
        c.execute(
            "ALTER TABLE breaking_news_log ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ"
        )
    except Exception as e:
        print(f"[migrate] breaking_news_log.published_at: {e}")


def log_breaking_news(url_hash: str, source: str, title: str, link: str,
                      summary_th: str, importance: str, reasoning: str,
                      published_at: str | None = None) -> int | None:
    """Insert classified news. Returns id, or None on duplicate.

    published_at: ISO-format string of article's original publish time (from RSS
    pubDate). None if source didn't provide one. Frontend uses this for the
    "X ago" display — far more honest than classified_at.
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        _ensure_breaking_news_published_at_column(c)
        c.execute(
            """
            INSERT INTO breaking_news_log
                (url_hash, source, title, link, summary_th, importance, reasoning, published_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url_hash) DO NOTHING
            RETURNING id
            """,
            (url_hash, source, title, link, summary_th, importance, reasoning, published_at),
        )
        row = c.fetchone()
        conn.commit()
        return int(row[0]) if row else None
    except Exception as e:
        print(f"[BreakingNews] log insert error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def is_news_seen_within(url_hash: str, hours: int = 48) -> bool:
    """Windowed dedup — was this hash logged within the last `hours`?
    Used by News Digest so an identical headline can resurface after the window
    (permanent dedup would block a recurring topic forever)."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT 1 FROM breaking_news_log "
            "WHERE url_hash = %s AND classified_at > NOW() - (%s || ' hours')::interval LIMIT 1",
            (url_hash, str(int(hours))),
        )
        return c.fetchone() is not None
    except Exception as e:
        print(f"[news] is_news_seen_within err: {e}", flush=True)
        return False
    finally:
        conn.close()


def record_digest_feedback(user_id: str, digest_key: str, vote: str) -> None:
    """Store 👍/👎 feedback on a News Digest. Idempotent table create.
    digest_key = per-digest id (e.g. date string); vote = 'up'|'down'."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS digest_feedback (
                user_id TEXT NOT NULL,
                digest_key TEXT NOT NULL,
                vote TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, digest_key)
            )
            """
        )
        c.execute(
            """
            INSERT INTO digest_feedback (user_id, digest_key, vote)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, digest_key) DO UPDATE SET vote = EXCLUDED.vote, created_at = NOW()
            """,
            (str(user_id), str(digest_key), str(vote)),
        )
        conn.commit()
    except Exception as e:
        print(f"[digest_feedback] {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()


def mark_breaking_news_sent(news_id: int, count: int) -> None:
    """Update sent_to_count after successful push."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "UPDATE breaking_news_log SET sent_to_count = %s WHERE id = %s",
            (int(count), int(news_id)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def is_subscribed_breaking_news(user_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT enabled FROM breaking_news_subscribers WHERE user_id = %s",
            (str(user_id),),
        )
        row = c.fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def set_breaking_news_subscription(user_id: str, enabled: bool) -> None:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO breaking_news_subscribers (user_id, enabled)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """,
            (str(user_id), bool(enabled)),
        )
        conn.commit()
    except Exception as e:
        print(f"[BreakingNews] subscription update error: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_breaking_news_subscribers() -> list[str]:
    """Enabled subscribers, filtered to active PRO via check_subscription
    so we don't have to second-guess the TEXT vs timestamp shape of expiry_date."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM breaking_news_subscribers WHERE enabled = TRUE")
        candidates = [r[0] for r in c.fetchall()]
    finally:
        conn.close()
    return [uid for uid in candidates if check_subscription(uid) == 'pro']


def get_recent_breaking_news(limit: int = 20, importance: str | None = None) -> list[dict]:
    """For web banner / API — recent classified news, newest first."""
    conn = get_connection()
    c = conn.cursor()
    try:
        if importance:
            c.execute(
                """
                SELECT id, source, title, link, summary_th, importance,
                       reasoning, classified_at, sent_to_count
                FROM breaking_news_log
                WHERE importance = %s
                ORDER BY classified_at DESC
                LIMIT %s
                """,
                (importance.upper(), int(limit)),
            )
        else:
            c.execute(
                """
                SELECT id, source, title, link, summary_th, importance,
                       reasoning, classified_at, sent_to_count
                FROM breaking_news_log
                ORDER BY classified_at DESC
                LIMIT %s
                """,
                (int(limit),),
            )
        rows = c.fetchall()
    finally:
        conn.close()
    return [{
        "id": r[0],
        "source": r[1],
        "title": r[2],
        "link": r[3],
        "summary_th": r[4],
        "importance": r[5],
        "reasoning": r[6],
        "classified_at": r[7].isoformat() if r[7] else None,
        "sent_to_count": r[8],
    } for r in rows]


# ==========================================
# Pending Referrals — manual capture from users who didn't use REF_ link
# ==========================================

def has_pending_referral(new_user_id: str) -> bool:
    """Has this user already submitted a 'who referred you' answer?"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT 1 FROM pending_referrals WHERE new_user_id = %s LIMIT 1",
            (str(new_user_id),),
        )
        return c.fetchone() is not None
    finally:
        conn.close()


def add_pending_referral(new_user_id: str, new_user_name: str | None,
                         referrer_query: str) -> int | None:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO pending_referrals (new_user_id, new_user_name, referrer_query)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (str(new_user_id), new_user_name, str(referrer_query)[:200]),
        )
        new_id = c.fetchone()[0]
        conn.commit()
        return int(new_id)
    except Exception as e:
        print(f"[PendingRef] insert error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()


def list_pending_referrals(limit: int = 50) -> list[dict]:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT id, new_user_id, new_user_name, referrer_query, submitted_at, awarded
            FROM pending_referrals
            WHERE awarded = FALSE
            ORDER BY submitted_at DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        rows = c.fetchall()
    finally:
        conn.close()
    return [{
        "id": r[0], "new_user_id": r[1], "new_user_name": r[2],
        "referrer_query": r[3],
        "submitted_at": r[4].isoformat() if r[4] else None,
        "awarded": r[5],
    } for r in rows]


def delete_pending_referral(pending_id: int) -> bool:
    """ลบ pending referral row (สำหรับ admin จัดการ submission ผิด/spam)
    คืน True ถ้ามีแถวถูกลบ"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM pending_referrals WHERE id = %s", (int(pending_id),))
        deleted = (c.rowcount or 0) > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def user_exists(user_id: str) -> bool:
    """เช็คว่า user_id มี row ใน users table"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users WHERE user_id = %s LIMIT 1", (str(user_id),))
        return c.fetchone() is not None
    finally:
        conn.close()


def find_users_by_name(query: str, limit: int = 5) -> list[tuple[str, str]]:
    """หา user จากชื่อ (case-insensitive partial match บน users.username)
    คืน list ของ (user_id, username) — เรียงตาม recently active"""
    q = (query or "").strip()
    if not q:
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT user_id, COALESCE(username, '')
            FROM users
            WHERE username ILIKE %s
            ORDER BY last_active DESC NULLS LAST, registered_date DESC NULLS LAST
            LIMIT %s
            """,
            (f"%{q}%", int(limit)),
        )
        return [(str(row[0]), str(row[1])) for row in c.fetchall()]
    except Exception as e:
        print(f"[find_users_by_name] {e}", flush=True)
        return []
    finally:
        conn.close()


def mark_referral_awarded(pending_id: int, referrer_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE pending_referrals
            SET resolved_referrer_id = %s, awarded = TRUE, awarded_at = NOW()
            WHERE id = %s AND awarded = FALSE
            """,
            (str(referrer_id), int(pending_id)),
        )
        affected = c.rowcount
        conn.commit()
        return affected > 0
    except Exception as e:
        print(f"[PendingRef] mark awarded error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ==========================================
# Achievement Badges — gamification for engagement (esp. trial users)
# ==========================================

# Badge catalog: code → (label, description). Adding a new badge:
# 1. Add row here
# 2. Add detection logic in `evaluate_achievements()` below
# 3. Decide if it gets a reward (+1 day VIP etc.) — call grant_streak_reward
ACHIEVEMENT_CATALOG = {
    "first_analysis":  ("🎯 First Analysis",     "วิเคราะห์หุ้นครั้งแรก"),
    "ten_analyses":    ("🔥 10 Stocks Analyzed", "วิเคราะห์ครบ 10 ตัวแล้ว"),
    "fifty_analyses":  ("💯 Power Analyst",      "วิเคราะห์ครบ 50 ตัว"),
    "first_watch":     ("⭐ First Watchlist",     "เพิ่ม watchlist ครั้งแรก"),
    "watch_full_free": ("👀 Watchful Eye",        "Free watchlist เต็ม 3 ตัว"),
    "first_trial":     ("✨ Trial Activated",     "เริ่มทดลอง PRO 7 วัน"),
    "first_referral":  ("🤝 First Referral",      "ชวนเพื่อนคนแรกสำเร็จ"),
    "streak_7":        ("🔥 7-Day Streak",        "ใช้บอท 7 วันติด"),
    "streak_30":       ("⚡ 30-Day Streak",       "ใช้บอท 30 วันติด"),
    "first_pro":       ("👑 PRO Member",          "อัปเกรดเป็น PRO"),
    "first_vip":       ("💎 VIP Member",          "อัปเกรดเป็น VIP"),
}


def has_achievement(user_id: str, badge_code: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT 1 FROM user_achievements WHERE user_id = %s AND badge_code = %s LIMIT 1",
            (str(user_id), badge_code),
        )
        return c.fetchone() is not None
    finally:
        conn.close()


def grant_achievement(user_id: str, badge_code: str) -> bool:
    """Insert badge if not already earned. Returns True if newly granted."""
    if badge_code not in ACHIEVEMENT_CATALOG:
        return False
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO user_achievements (user_id, badge_code)
            VALUES (%s, %s)
            ON CONFLICT (user_id, badge_code) DO NOTHING
            RETURNING badge_code
            """,
            (str(user_id), badge_code),
        )
        granted = c.fetchone() is not None
        conn.commit()
        return granted
    except Exception as e:
        print(f"[Achievement] grant error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_user_achievements(user_id: str) -> list[dict]:
    """Return list of {code, label, description, earned_at} for user."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT badge_code, earned_at FROM user_achievements WHERE user_id = %s ORDER BY earned_at",
            (str(user_id),),
        )
        rows = c.fetchall()
    finally:
        conn.close()
    out = []
    for code, earned in rows:
        meta = ACHIEVEMENT_CATALOG.get(code, (code, ""))
        out.append({
            "code": code,
            "label": meta[0],
            "description": meta[1],
            "earned_at": earned.isoformat() if earned else None,
        })
    return out


def evaluate_achievements(user_id: str, *, context: str | None = None) -> list[str]:
    """Check user state and grant any newly-earned badges. Returns list of newly-granted codes.

    Call this from analyze flow + watchlist add + trial activate + payment claim.
    `context` is an optional hint (e.g., 'analyze', 'watch_add', 'trial', 'pro_grant')
    so we can short-circuit irrelevant checks.
    """
    new_grants: list[str] = []

    # 1. Analysis count badges (driven by usage_count)
    if context in (None, "analyze"):
        try:
            usage = get_usage(user_id) or 0
            if usage >= 1 and not has_achievement(user_id, "first_analysis"):
                if grant_achievement(user_id, "first_analysis"):
                    new_grants.append("first_analysis")
            if usage >= 10 and not has_achievement(user_id, "ten_analyses"):
                if grant_achievement(user_id, "ten_analyses"):
                    new_grants.append("ten_analyses")
            if usage >= 50 and not has_achievement(user_id, "fifty_analyses"):
                if grant_achievement(user_id, "fifty_analyses"):
                    new_grants.append("fifty_analyses")
        except Exception:
            pass

    # 2. Watchlist badges
    if context in (None, "watch_add"):
        try:
            watch = get_user_watch(user_id) or []
            if len(watch) >= 1 and not has_achievement(user_id, "first_watch"):
                if grant_achievement(user_id, "first_watch"):
                    new_grants.append("first_watch")
            if len(watch) >= 3 and not has_achievement(user_id, "watch_full_free"):
                if grant_achievement(user_id, "watch_full_free"):
                    new_grants.append("watch_full_free")
        except Exception:
            pass

    # 3. Tier badges (driven by check_subscription)
    if context in (None, "tier_change", "trial", "pro_grant"):
        try:
            role = check_subscription(user_id)
            if role == 'pro' and not has_achievement(user_id, "first_pro"):
                if grant_achievement(user_id, "first_pro"):
                    new_grants.append("first_pro")
            if role == 'vip' and not has_achievement(user_id, "first_vip"):
                if grant_achievement(user_id, "first_vip"):
                    new_grants.append("first_vip")
        except Exception:
            pass

    # 4. Streak badges
    if context in (None, "analyze"):
        try:
            sinfo = get_streak_info(user_id) or {"current": 0}
            cur = sinfo.get("current", 0)
            if cur >= 7 and not has_achievement(user_id, "streak_7"):
                if grant_achievement(user_id, "streak_7"):
                    new_grants.append("streak_7")
            if cur >= 30 and not has_achievement(user_id, "streak_30"):
                if grant_achievement(user_id, "streak_30"):
                    new_grants.append("streak_30")
        except Exception:
            pass

    # 5. Trial badge — granted once free_trial_used flips to True
    if context in (None, "trial"):
        try:
            if has_used_free_trial(user_id) and not has_achievement(user_id, "first_trial"):
                if grant_achievement(user_id, "first_trial"):
                    new_grants.append("first_trial")
        except Exception:
            pass

    # 6. Referral badge — granted on first successful referral (referrer side)
    if context in (None, "referral"):
        try:
            if get_referral_stats(user_id) >= 1 and not has_achievement(user_id, "first_referral"):
                if grant_achievement(user_id, "first_referral"):
                    new_grants.append("first_referral")
        except Exception:
            pass

    return new_grants


# ==========================================
# 📬 Auto-DM Cron — candidates queries
# ==========================================
def query_activation_candidates(cooldown_days: int = 30, limit: int = 200):
    """หาก users ที่ "สมัครแล้วยังไม่ activate" — 1-query (รวม dispatch_log dedupe)

    Criteria:
      - registered_date 1-14 days ago
      - free_trial_used = FALSE
      - total_analyses ≤ 2 (warm: เคยลอง 0-2 ครั้งแต่ไม่ /freetrial)
      - role = free
      - NOT IN dispatch_log category=auto_dm_activation ใน cooldown_days

    Returns: list ของ dict { user_id, username, total_analyses }
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT u.user_id, u.username, COALESCE(u.total_analyses, 0) AS total_analyses
            FROM users u
            WHERE u.registered_date IS NOT NULL
              AND u.registered_date::timestamp < NOW() - INTERVAL '24 hours'
              AND u.registered_date::timestamp > NOW() - INTERVAL '14 days'
              AND COALESCE(u.free_trial_used, FALSE) = FALSE
              AND COALESCE(u.total_analyses, 0) <= 2
              AND COALESCE(u.role, 'free') = 'free'
              AND u.user_id NOT IN (
                  SELECT raw_key FROM dispatch_log
                  WHERE category = 'auto_dm_activation'
                    AND created_at > NOW() - %s::INTERVAL
                    AND raw_key IS NOT NULL
              )
            ORDER BY u.registered_date::timestamp DESC
            LIMIT %s
            """,
            (f"{int(cooldown_days)} days", int(limit)),
        )
        rows = c.fetchall()
    except Exception as e:
        print(f"[query_activation_candidates] err: {e}", flush=True)
        return []
    finally:
        conn.close()

    return [
        {"user_id": str(row[0]), "username": row[1] or "", "total_analyses": int(row[2] or 0)}
        for row in rows
    ]


def query_winback_candidates(cooldown_days: int = 30, limit: int = 200):
    """หาก users ที่ "เคยจ่าย VIP/PRO เพิ่งหมดอายุ" — 1-query (รวม dedupe)

    Criteria:
      - role ∈ vip/pro
      - expiry_date หมดใน 7 วันที่ผ่านมา
      - total_analyses ≥ 3 (กรอง trial-only)
      - NOT IN dispatch_log category=auto_dm_winback ใน cooldown_days

    Returns: list ของ dict { user_id, username, total_analyses, days_lapsed }
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT u.user_id, u.username, COALESCE(u.total_analyses, 0) AS total_analyses,
                   GREATEST(1, EXTRACT(DAY FROM (NOW() - u.expiry_date::timestamp))::int) AS days_lapsed
            FROM users u
            WHERE u.expiry_date IS NOT NULL
              AND u.role IN ('vip', 'pro')
              AND u.expiry_date::timestamp BETWEEN NOW() - INTERVAL '7 days' AND NOW()
              AND COALESCE(u.total_analyses, 0) >= 3
              AND u.user_id NOT IN (
                  SELECT raw_key FROM dispatch_log
                  WHERE category = 'auto_dm_winback'
                    AND created_at > NOW() - %s::INTERVAL
                    AND raw_key IS NOT NULL
              )
            ORDER BY u.expiry_date::timestamp DESC
            LIMIT %s
            """,
            (f"{int(cooldown_days)} days", int(limit)),
        )
        rows = c.fetchall()
    except Exception as e:
        print(f"[query_winback_candidates] err: {e}", flush=True)
        return []
    finally:
        conn.close()

    return [
        {"user_id": str(row[0]), "username": row[1] or "", "total_analyses": int(row[2] or 0), "days_lapsed": int(row[3] or 1)}
        for row in rows
    ]


def query_pro_users_with_watchlist(limit: int = 500) -> list:
    """หา PRO users ที่ยังไม่หมดอายุ + มี watchlist อย่างน้อย 1 ตัว
    Backward-compat wrapper — เรียก query_paying_users_with_watchlist roles=['pro']
    """
    return query_paying_users_with_watchlist(roles=['pro'], limit=limit)


def query_paying_users_with_watchlist(roles=('vip', 'pro'), limit: int = 500) -> list:
    """หา paying users (VIP + PRO ที่ยังไม่หมดอายุ) + มี watchlist อย่างน้อย 1 ตัว

    ใช้สำหรับ Daily P&L Recap cron — ขยายจาก PRO-only เป็น VIP+PRO ที่ยังไม่หมด

    Returns: list ของ dict { user_id, username, role, watchlist: [ticker, ...] }
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        role_list = list(roles) if not isinstance(roles, str) else [roles]
        # Use IN with placeholders dynamic
        placeholders = ",".join(["%s"] * len(role_list))
        c.execute(
            f"""
            SELECT u.user_id, u.username, u.role
            FROM users u
            WHERE COALESCE(u.role, 'free') IN ({placeholders})
              AND u.expiry_date IS NOT NULL
              AND u.expiry_date::timestamp > NOW()
              AND EXISTS (
                  SELECT 1 FROM user_watchlist w
                  WHERE TRIM(w.user_id) = TRIM(u.user_id)
              )
            ORDER BY u.user_id
            LIMIT %s
            """,
            tuple(role_list) + (int(limit),),
        )
        rows = c.fetchall()
    except Exception as e:
        print(f"[query_paying_users_with_watchlist] err: {e}", flush=True)
        return []
    finally:
        conn.close()

    out = []
    for row in rows:
        uid = str(row[0])
        tickers = _get_user_watchlist_items(uid) or []
        if tickers:
            out.append({
                "user_id": uid,
                "username": row[1] or "",
                "role": row[2] or "",
                "watchlist": tickers,
            })
    return out


def query_dm_stats(days: int = 7) -> dict:
    """Stats สำหรับ /dm_stats admin command — ดู auto_dm performance

    Returns: dict {
        days, total_activation, total_winback,
        activation_users_who_freetrial,    # converted by /freetrial after DM
        winback_users_who_redeem,          # converted by /redeem after DM
        activation_conversion_pct,
        winback_conversion_pct,
        recent_activations: [{user_id, username, sent_at, converted}, ...],
        recent_winbacks: [...],
    }
    """
    conn = get_connection()
    c = conn.cursor()
    out = {
        "days": days,
        "total_activation": 0,
        "total_winback": 0,
        "activation_users_who_freetrial": 0,
        "winback_users_who_redeem": 0,
        "activation_conversion_pct": 0.0,
        "winback_conversion_pct": 0.0,
        "recent_activations": [],
        "recent_winbacks": [],
    }
    try:
        # Total DM sent per category
        c.execute(
            """
            SELECT category, COUNT(DISTINCT raw_key) AS cnt
            FROM dispatch_log
            WHERE category IN ('auto_dm_activation', 'auto_dm_winback')
              AND created_at > NOW() - %s::INTERVAL
              AND raw_key IS NOT NULL
            GROUP BY category
            """,
            (f"{int(days)} days",),
        )
        for row in c.fetchall():
            cat, cnt = row[0], int(row[1] or 0)
            if cat == "auto_dm_activation":
                out["total_activation"] = cnt
            elif cat == "auto_dm_winback":
                out["total_winback"] = cnt

        # Activation conversion — user ที่ใช้ /freetrial หลัง DM
        c.execute(
            """
            SELECT COUNT(DISTINCT d.raw_key)
            FROM dispatch_log d
            JOIN users u ON u.user_id = d.raw_key
            WHERE d.category = 'auto_dm_activation'
              AND d.created_at > NOW() - %s::INTERVAL
              AND COALESCE(u.free_trial_used, FALSE) = TRUE
            """,
            (f"{int(days)} days",),
        )
        row = c.fetchone()
        out["activation_users_who_freetrial"] = int(row[0] or 0) if row else 0

        # Win-back conversion — user ที่ role IN (vip/pro) หลัง DM (renewed)
        c.execute(
            """
            SELECT COUNT(DISTINCT d.raw_key)
            FROM dispatch_log d
            JOIN users u ON u.user_id = d.raw_key
            WHERE d.category = 'auto_dm_winback'
              AND d.created_at > NOW() - %s::INTERVAL
              AND u.role IN ('vip', 'pro')
              AND u.expiry_date::timestamp > NOW()
            """,
            (f"{int(days)} days",),
        )
        row = c.fetchone()
        out["winback_users_who_redeem"] = int(row[0] or 0) if row else 0

        # Recent activations (last 10)
        c.execute(
            """
            SELECT d.raw_key, u.username, d.created_at, COALESCE(u.free_trial_used, FALSE)
            FROM dispatch_log d
            LEFT JOIN users u ON u.user_id = d.raw_key
            WHERE d.category = 'auto_dm_activation'
              AND d.created_at > NOW() - %s::INTERVAL
            ORDER BY d.created_at DESC
            LIMIT 10
            """,
            (f"{int(days)} days",),
        )
        for row in c.fetchall():
            out["recent_activations"].append({
                "user_id": row[0], "username": row[1] or "Unknown",
                "sent_at": row[2], "converted": bool(row[3]),
            })

        # Recent winbacks (last 10)
        c.execute(
            """
            SELECT d.raw_key, u.username, d.created_at,
                   (u.role IN ('vip','pro') AND u.expiry_date::timestamp > NOW()) AS renewed
            FROM dispatch_log d
            LEFT JOIN users u ON u.user_id = d.raw_key
            WHERE d.category = 'auto_dm_winback'
              AND d.created_at > NOW() - %s::INTERVAL
            ORDER BY d.created_at DESC
            LIMIT 10
            """,
            (f"{int(days)} days",),
        )
        for row in c.fetchall():
            out["recent_winbacks"].append({
                "user_id": row[0], "username": row[1] or "Unknown",
                "sent_at": row[2], "converted": bool(row[3]),
            })

        if out["total_activation"] > 0:
            out["activation_conversion_pct"] = out["activation_users_who_freetrial"] / out["total_activation"] * 100
        if out["total_winback"] > 0:
            out["winback_conversion_pct"] = out["winback_users_who_redeem"] / out["total_winback"] * 100
    except Exception as e:
        print(f"[query_dm_stats] err: {e}", flush=True)
    finally:
        conn.close()
    return out


# Legacy helper — kept for backward compat แต่ไม่ใช้ใน query ใหม่แล้ว
def _fetch_dispatched_users(category: str, cooldown_days: int) -> set:
    """Return set ของ user_ids ที่ถูก DM ใน category นี้ภายใน cooldown_days"""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT DISTINCT raw_key FROM dispatch_log
            WHERE category = %s
              AND created_at > NOW() - %s::INTERVAL
              AND raw_key IS NOT NULL
            """,
            (category, f"{int(cooldown_days)} days"),
        )
        rows = c.fetchall()
        return {str(row[0]) for row in rows if row[0]}
    except Exception as e:
        print(f"[_fetch_dispatched_users] err: {e}", flush=True)
        return set()
    finally:
        conn.close()
