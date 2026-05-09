"""User memory — personalize Apexify analysis ตาม user แต่ละคน

ดึงจาก data ที่มีอยู่แล้ว (portfolios + user_watchlist) ไม่ต้อง schema ใหม่
ใส่เข้า Gemini prompt → AI กล่าวถึง holdings/watchlist ของ user เอง

Cache: TTL 30 นาที/user (ลด DB hit + เร็ว)
"""

from threading import RLock
from cachetools import TTLCache

try:
    from database import get_user_portfolio, get_connection
except Exception:
    get_user_portfolio = None
    get_connection = None


_MEMORY_CACHE = TTLCache(maxsize=500, ttl=1800)  # 30 นาที
_CACHE_LOCK = RLock()


def _safe_call(fn, *args, default=None):
    if fn is None:
        return default
    try:
        return fn(*args)
    except Exception as e:
        print(f"[user_memory] {fn.__name__} err: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return default


def _fetch_watchlist(user_id):
    """ดึง user_watchlist ผ่าน raw query — function ที่ export ของ database คืน list ของหุ้นที่ติดตาม global ไม่ใช่ของ user
    ต้อง query ตรงๆ
    """
    if get_connection is None:
        return []
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT ticker FROM user_watchlist WHERE user_id=%s ORDER BY ticker ASC LIMIT 30",
            (str(user_id),),
        )
        rows = c.fetchall()
        return [str(r[0]).upper() for r in rows if r and r[0]]
    except Exception as e:
        print(f"[user_memory] watchlist err: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def build_user_memory(user_id):
    """คืน dict สำหรับ inject เข้า Gemini prompt + render
    {
        "holdings": [{"ticker", "shares", "avg_cost"}, ...],
        "watchlist": ["TICKER", ...],
        "has_data": bool,
    }
    """
    if not user_id:
        return {"holdings": [], "watchlist": [], "has_data": False}
    key = str(user_id)

    with _CACHE_LOCK:
        cached = _MEMORY_CACHE.get(key)
        if cached is not None:
            return dict(cached)  # snapshot

    holdings = _safe_call(get_user_portfolio, key, default=[]) or []
    # normalize: บางรายการอาจ shares=0 = ขายแล้ว → ตัดทิ้ง
    holdings = [h for h in holdings if isinstance(h, dict) and float(h.get("shares") or 0) > 0]
    watchlist = _fetch_watchlist(key)

    memory = {
        "holdings": holdings,
        "watchlist": watchlist,
        "has_data": bool(holdings) or bool(watchlist),
    }

    with _CACHE_LOCK:
        _MEMORY_CACHE[key] = dict(memory)

    return memory


def find_holding(memory, symbol):
    """หา holding ของ symbol ใน memory — คืน dict {ticker, shares, avg_cost} หรือ None
    เปรียบ ticker แบบ case-insensitive + ตัด market suffix
    """
    if not memory or not symbol:
        return None
    target = str(symbol).upper().strip()
    target_base = target.split(".")[0]
    for h in memory.get("holdings") or []:
        h_ticker = str(h.get("ticker") or "").upper().strip()
        if not h_ticker:
            continue
        if h_ticker == target or h_ticker.split(".")[0] == target_base:
            return h
    return None


def is_in_watchlist(memory, symbol):
    if not memory or not symbol:
        return False
    target = str(symbol).upper().strip()
    target_base = target.split(".")[0]
    for t in memory.get("watchlist") or []:
        if t == target or t.split(".")[0] == target_base:
            return True
    return False


def format_memory_for_prompt(memory, current_symbol=None):
    """format compact สำหรับใส่ใน Gemini prompt — token-efficient

    คืน "" ถ้า user ไม่มี data (free + ไม่มี portfolio)
    """
    if not memory or not memory.get("has_data"):
        return ""

    parts = []
    holdings = memory.get("holdings") or []
    if holdings:
        # max 5 holdings, prioritize ตัวที่ตรงกับ current_symbol
        sorted_h = sorted(
            holdings,
            key=lambda h: 0 if (current_symbol and str(h.get("ticker") or "").upper() == str(current_symbol).upper()) else 1,
        )
        h_str = ", ".join(
            f"{str(h.get('ticker') or '?').upper()}@{float(h.get('avg_cost') or 0):.2f}"
            for h in sorted_h[:5]
        )
        parts.append(f"holds: {h_str}")

    watchlist = memory.get("watchlist") or []
    if watchlist:
        parts.append(f"watching: {', '.join(watchlist[:8])}")

    return " | ".join(parts)


def render_holding_line(holding, current_price=None):
    """Render บรรทัด "💼 ถือ: X หุ้น @ Y → ตอนนี้ +Z%" ใน Telegram Markdown
    คืน "" ถ้า holding ไม่ valid
    """
    if not holding or not isinstance(holding, dict):
        return ""
    try:
        ticker = str(holding.get("ticker") or "?").upper()
        shares = float(holding.get("shares") or 0)
        avg_cost = float(holding.get("avg_cost") or 0)
    except (TypeError, ValueError):
        return ""
    if shares <= 0 or avg_cost <= 0:
        return ""

    line = f"💼 *คุณถืออยู่:* `{shares:g}` หุ้น @ `{avg_cost:.2f}`"
    if current_price and current_price > 0 and avg_cost > 0:
        pnl_pct = (current_price - avg_cost) / avg_cost * 100
        emoji = "🟢" if pnl_pct >= 0 else "🔴"
        line += f"  {emoji} *{pnl_pct:+.2f}%*"
    return line
