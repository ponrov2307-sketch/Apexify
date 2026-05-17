"""
congress_cron.py — DM admin (และ PRO watchlist) ทุกวัน 17:00 ICT
                   ดูหุ้นที่ Senator / Representative US ซื้อ-ขายในรอบ 14 วัน

Sources (FREE public APIs, no auth):
  - Senate Stock Watcher: https://senatestockwatcher.com/api/v2/all_transactions
  - House Stock Watcher:  https://housestockwatcher.com/api/v2/all_transactions

User value:
  - admin: viral content "นักการเมือง US ซื้อหุ้นอะไรสัปดาห์นี้"
  - PRO: alert เฉพาะ ticker ที่อยู่ใน watchlist (premium signal)

Reliability:
  - STOCK Act บังคับ politician disclose ภายใน 45 วันหลัง trade
  - API update ภายในวันที่ filing เผยแพร่
  - Delay: trade → filing → API ≈ T+0 ถึง T+45 days (most file T+30)

Workflow:
  1. Daily cron 17:00 ICT
  2. Fetch both Senate + House APIs (JSON arrays)
  3. Filter: amount_max ≥ $50K · trade_date ≤ 14d ago · skip "Exchange"
  4. Format top 8 by amount → DM admin
  5. Match PRO watchlist → DM premium signal (per-ticker dedup)
"""

import re
import time
from datetime import datetime, timedelta, timezone

import config


# ============ Sources ============
_SENATE_URL = "https://senatestockwatcher.com/api/v2/all_transactions"
_HOUSE_URL = "https://housestockwatcher.com/api/v2/all_transactions"
_HTTP_TIMEOUT_SEC = 25
_USER_AGENT = "Apexify Trading Bot (apexify@example.com)"


# ============ Filters ============
MIN_AMOUNT_USD = 50_000           # ตัด small disclosures
MAX_TRADE_AGE_DAYS = 14           # เฉพาะ trade ใหม่ (filing delay = OK)
TOP_N_ADMIN = 8
SKIP_ASSET_TYPES = {
    # Skip non-equity (bonds, mutual funds, options often noise)
    "bond", "corporate bond", "municipal bond", "treasury",
    "401k", "403b", "ira", "mutual fund", "etf", "exchange traded fund",
    "tax exempt", "treasury bill",
}


# ============ HTTP fetch ============
def _http_get(url: str, timeout: int = _HTTP_TIMEOUT_SEC):
    """ใช้ curl_cffi ถ้ามี (anti-bot) — fallback เป็น requests"""
    try:
        from curl_cffi import requests as cffi_requests
        return cffi_requests.get(url, impersonate="chrome110", timeout=timeout)
    except Exception:
        import requests
        return requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)


# ============ Parsing ============
# Amount strings come as ranges per STOCK Act disclosure rules:
#   "$1,001 - $15,000"
#   "$15,001 - $50,000"
#   "$50,001 - $100,000"
#   "$100,001 - $250,000"
#   "$250,001 - $500,000"
#   "$500,001 - $1,000,000"
#   "$1,000,001 - $5,000,000"
#   "$5,000,001 - $25,000,000"
#   "$25,000,001 - $50,000,000"
#   "Over $50,000,000"
_AMOUNT_RANGE_RE = re.compile(r"\$?([\d,]+)\s*-\s*\$?([\d,]+)")
_AMOUNT_OVER_RE = re.compile(r"[Oo]ver\s+\$?([\d,]+)")


def _parse_amount_range(amount_str: str) -> tuple[int, int]:
    """Returns (min_usd, max_usd) — use max as conservative estimate."""
    if not amount_str:
        return (0, 0)
    s = amount_str.strip()

    # "Over $50,000,000"
    m = _AMOUNT_OVER_RE.search(s)
    if m:
        v = int(m.group(1).replace(",", ""))
        return (v, v * 2)   # treat upper as 2x lower for ranking

    # "$X - $Y" range
    m = _AMOUNT_RANGE_RE.search(s)
    if m:
        lo = int(m.group(1).replace(",", ""))
        hi = int(m.group(2).replace(",", ""))
        return (lo, hi)

    # Plain number (some entries have just "$X")
    plain = re.search(r"\$?([\d,]+)", s)
    if plain:
        v = int(plain.group(1).replace(",", ""))
        return (v, v)

    return (0, 0)


def _parse_trade_date(date_str: str):
    """'2026-05-11' or '01/15/2024' → datetime.date or None"""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _is_fresh(item: dict, max_days: int = MAX_TRADE_AGE_DAYS) -> bool:
    """Trade date within max_days from today (Thai timezone)."""
    d = _parse_trade_date(item.get("transaction_date") or item.get("date") or "")
    if d is None:
        return False
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    age = (today - d).days
    return 0 <= age <= max_days


# ============ Fetchers ============
def fetch_senate_transactions() -> list[dict]:
    """Senate Stock Watcher API. Returns raw list of dicts."""
    try:
        resp = _http_get(_SENATE_URL)
        if resp.status_code != 200:
            print(f"[congress] Senate HTTP {resp.status_code}", flush=True)
            return []
        data = resp.json()
        if not isinstance(data, list):
            print(f"[congress] Senate unexpected payload type: {type(data).__name__}", flush=True)
            return []
        # Normalize: add chamber tag
        for item in data:
            item["chamber"] = "Senate"
            item["politician"] = item.get("senator") or item.get("politician") or "Unknown Senator"
        return data
    except Exception as e:
        print(f"[congress] Senate fetch err: {e}", flush=True)
        return []


def fetch_house_transactions() -> list[dict]:
    """House Stock Watcher API."""
    try:
        resp = _http_get(_HOUSE_URL)
        if resp.status_code != 200:
            print(f"[congress] House HTTP {resp.status_code}", flush=True)
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        for item in data:
            item["chamber"] = "House"
            item["politician"] = item.get("representative") or item.get("politician") or "Unknown Representative"
        return data
    except Exception as e:
        print(f"[congress] House fetch err: {e}", flush=True)
        return []


# ============ Filter + Enrich ============
def filter_and_enrich(raw_items: list[dict]) -> list[dict]:
    """Apply quality filters + compute normalized fields.

    Returns list of {
        chamber, politician, ticker, asset_description, transaction_type,
        transaction_date, amount_min, amount_max, party (if available)
    }
    """
    out = []
    for item in raw_items:
        ticker = (item.get("ticker") or "").strip().upper()
        if not ticker or ticker == "--":
            continue

        # Skip non-equity asset types
        asset_type = (item.get("asset_type") or "").lower()
        if any(skip in asset_type for skip in SKIP_ASSET_TYPES):
            continue

        # Parse amount
        amount_str = item.get("amount") or ""
        lo, hi = _parse_amount_range(amount_str)
        if hi < MIN_AMOUNT_USD:
            continue

        # Skip Exchange (just internal rebalancing)
        tx_type = (item.get("type") or item.get("transaction_type") or "").strip()
        if tx_type.lower() in ("exchange", "exchanges"):
            continue

        # Freshness gate
        if not _is_fresh(item):
            continue

        out.append({
            "chamber":            item.get("chamber", ""),
            "politician":         (item.get("politician") or "").strip(),
            "ticker":             ticker,
            "asset_description":  (item.get("asset_description") or "").strip()[:80],
            "transaction_type":   tx_type or "Unknown",
            "transaction_date":   item.get("transaction_date") or "",
            "amount_min":         lo,
            "amount_max":         hi,
            "amount_str":         amount_str,
            "party":              item.get("party") or "",  # may not be in payload
        })
    return out


# ============ Format ============
def _fmt_usd(v: int) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v}"


def _tx_emoji(tx_type: str) -> str:
    t = tx_type.lower()
    if "purchase" in t or t.startswith("buy"):
        return "🟢"
    if "sale" in t or t.startswith("sell"):
        return "🔴"
    return "⚪"


def format_admin_message(items: list[dict], top_n: int = TOP_N_ADMIN) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    items = sorted(items, key=lambda x: -x["amount_max"])[:top_n]

    senate_count = sum(1 for it in items if it["chamber"] == "Senate")
    house_count = sum(1 for it in items if it["chamber"] == "House")

    lines = [
        f"🏛 *Congress Trades — {today.strftime('%d %b %Y')}*",
        f"_Senate: {senate_count} · House: {house_count} · last {MAX_TRADE_AGE_DAYS}d_",
        "",
    ]
    for it in items:
        emoji = _tx_emoji(it["transaction_type"])
        chamber_tag = "🇺🇸 SEN" if it["chamber"] == "Senate" else "🏛 HOU"
        lines.append(
            f"{emoji} *{it['ticker']}* · {chamber_tag}\n"
            f"   {it['politician'][:35]}\n"
            f"   {it['transaction_type']} · {_fmt_usd(it['amount_max'])} · {it['transaction_date']}"
        )
        lines.append("")

    lines.append("💡 ใช้ทำ FB content: \"นักการเมือง US ซื้อหุ้น...\"")
    return "\n".join(lines)


def format_pro_message(items: list[dict]) -> str:
    """Compact PRO DM — เฉพาะ ticker ที่อยู่ใน watchlist."""
    items = sorted(items, key=lambda x: -x["amount_max"])
    lines = ["🏛 *Congress Signal — Watchlist Hit*", ""]
    for it in items:
        emoji = _tx_emoji(it["transaction_type"])
        chamber = "Senate" if it["chamber"] == "Senate" else "House"
        lines.append(
            f"{emoji} *{it['ticker']}* — {it['politician'][:35]}\n"
            f"   {chamber} · {it['transaction_type']} {_fmt_usd(it['amount_max'])} · {it['transaction_date']}"
        )
    lines.append("")
    lines.append("_⚠️ Disclosure delay: trades may be 1-45 วันเก่า (STOCK Act 45-day window)_")
    return "\n".join(lines)


# ============ Dedup (mirror smart_money pattern) ============
def _today_key() -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"congress:{today.isoformat()}"


def _admin_sig_key(ticker: str, trade_date: str, politician: str) -> str:
    # Per-ticker × date × politician — same trade by 2 politicians = 2 signals
    pol_short = re.sub(r"[^A-Za-z]", "", politician)[:20]
    return f"congress_admin:{ticker}:{trade_date}:{pol_short}"


def _pro_sig_key(user_id: str, ticker: str, trade_date: str, politician: str) -> str:
    pol_short = re.sub(r"[^A-Za-z]", "", politician)[:20]
    return f"congress_pro:{ticker}:{trade_date}:{pol_short}:{user_id}"


def _check_dispatch(key: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (key,))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[congress] dispatch check err: {e}", flush=True)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_dispatch(key: str, category: str, raw_key: str):
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (key, category, raw_key),
        )
        conn.commit()
    except Exception as e:
        print(f"[congress] dispatch mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _already_ran_today() -> bool:
    return _check_dispatch(_today_key())


def _mark_today_done():
    _mark_dispatch(_today_key(), "congress", "admin")


# ============ Senders ============
def _send_admin(bot, items: list[dict], dry_run: bool = False) -> int:
    fresh = [it for it in items
             if not _check_dispatch(_admin_sig_key(it["ticker"], it["transaction_date"], it["politician"]))]
    if not fresh:
        print("[congress] no new admin signals (all already sent)", flush=True)
        return 0

    msg = format_admin_message(fresh)
    if dry_run:
        print("==== DRY ADMIN ====")
        print(msg)
        return 0

    try:
        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        for it in fresh[:TOP_N_ADMIN]:
            _mark_dispatch(
                _admin_sig_key(it["ticker"], it["transaction_date"], it["politician"]),
                "congress_admin", str(it["ticker"]),
            )
        return 1
    except Exception as e:
        print(f"[congress] admin DM err: {e}", flush=True)
        return 0


def _query_pro_watchlists(limit: int = 500) -> list[dict]:
    """Reuse smart_money's PRO query — same shape needed."""
    try:
        from smart_money_cron import query_pro_users_with_watchlist
        return query_pro_users_with_watchlist(limit=limit)
    except Exception as e:
        print(f"[congress] reuse pro query err: {e}", flush=True)
        return []


def _send_pro_watchlists(bot, items: list[dict], dry_run: bool = False) -> int:
    pool_tickers = {it["ticker"] for it in items}
    if not pool_tickers:
        return 0

    pro_users = _query_pro_watchlists(limit=500)
    sent_count = 0

    for u in pro_users:
        uid = u["user_id"]
        watchlist = {t.upper() for t in (u.get("watchlist") or [])}
        matched = [it for it in items if it["ticker"].upper() in watchlist]
        if not matched:
            continue

        # Per-user dedup
        fresh = [it for it in matched
                 if not _check_dispatch(_pro_sig_key(uid, it["ticker"], it["transaction_date"], it["politician"]))]
        if not fresh:
            continue

        msg = format_pro_message(fresh)
        if dry_run:
            print(f"==== DRY PRO user={uid} ({len(fresh)} hits) ====")
            print(msg)
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            sent_count += 1
            for it in fresh:
                _mark_dispatch(
                    _pro_sig_key(uid, it["ticker"], it["transaction_date"], it["politician"]),
                    "congress_pro", uid,
                )
            time.sleep(0.8)
        except Exception as e:
            print(f"[congress] PRO DM err {uid}: {e}", flush=True)

    return sent_count


# ============ Entry points ============
def run_once(bot, dry_run: bool = False):
    """1 cycle — fetch + filter + DM"""
    print("[congress] starting scan...", flush=True)

    senate_raw = fetch_senate_transactions()
    house_raw = fetch_house_transactions()
    raw_items = senate_raw + house_raw
    print(f"[congress] fetched {len(senate_raw)} Senate + {len(house_raw)} House", flush=True)

    if not raw_items:
        if not dry_run:
            try:
                bot.send_message(config.ADMIN_ID, "⚠️ Congress Trades: ดึงข้อมูลไม่ได้วันนี้")
            except Exception:
                pass
        return

    filtered = filter_and_enrich(raw_items)
    print(f"[congress] after filter: {len(filtered)} (≥${MIN_AMOUNT_USD/1000:.0f}K · ≤{MAX_TRADE_AGE_DAYS}d)", flush=True)

    if not filtered:
        if not dry_run:
            try:
                bot.send_message(
                    config.ADMIN_ID,
                    "🏛 Congress Trades: ไม่มี trades เข้าเกณฑ์วันนี้",
                )
            except Exception:
                pass
        return

    _send_admin(bot, filtered, dry_run=dry_run)
    pro_sent = _send_pro_watchlists(bot, filtered, dry_run=dry_run)
    print(f"[congress] sent to {pro_sent} PRO users", flush=True)


def run_congress_cron(bot):
    """Daemon thread — daily at CONGRESS_HOUR_ICT (default 17:00 ICT)"""
    if not getattr(config, "CONGRESS_ENABLED", True):
        print("[congress] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "CONGRESS_HOUR_ICT", 17)
    target_m = getattr(config, "CONGRESS_MINUTE_ICT", 0)
    print(f"[congress] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(3 * 60)   # warm-up — let DB pool spin up

    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=7)   # ICT
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                if not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[congress] loop err: {e}", flush=True)
        time.sleep(20 * 60)


if __name__ == "__main__":
    # CLI dry-run mode
    print("=== Congress Trades Dry Run ===")
    senate = fetch_senate_transactions()
    house = fetch_house_transactions()
    raw = senate + house
    print(f"Senate: {len(senate)} · House: {len(house)}")

    filtered = filter_and_enrich(raw)
    print(f"After filter: {len(filtered)}")

    if filtered:
        print("\n" + format_admin_message(filtered, top_n=5))
    else:
        print("(no items pass filter)")
