"""
uoa_cron.py — Unusual Options Activity scanner (daily 21:30 ICT, after US open)
              ดูหุ้นที่มี option volume สูงผิดปกติเมื่อเทียบกับ open interest

Theory: ถ้า today's volume > 2x open interest → "fresh" position opening,
       มักเป็น smart money / informed trader เริ่ม bet ก่อน catalyst
       (earnings, FDA approval, M&A rumor ฯลฯ)

Source: yfinance option_chain() — FREE
        - Pulls all expirations + calls/puts for a ticker
        - Compares today's volume vs total open interest
        - No paid API needed

User value:
  - admin: viral content "หุ้นที่มี options activity ผิดปกติ" — early warning
  - PRO: alert เฉพาะ ticker ใน watchlist + premium signal

Limits:
  - yfinance has rate limits — limit to popular tickers (top 100 from screener)
  - Run after US market open (~21:30 ICT in summer DST = 10:30 ET)
"""

import time
from datetime import datetime, timedelta, timezone

import config


# ============ Universe — scan these tickers only ============
# Mega + popular mid-cap + meme stocks (where UOA signal matters most)
# Limited to ~50 tickers to avoid yfinance throttling
_UOA_UNIVERSE = [
    # Mega cap (always relevant)
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "BRK-B", "JPM",
    # Semi (high-options interest)
    "AMD", "INTC", "TSM", "AMAT", "LRCX", "QCOM", "MU", "SMCI", "ARM", "MRVL",
    # Tech / AI plays
    "ORCL", "CRM", "ADBE", "NFLX", "DIS", "UBER", "PYPL", "SHOP", "SQ", "PLTR",
    # Banks / Finance
    "BAC", "WFC", "GS", "MS", "C", "BLK", "V", "MA",
    # Healthcare / Pharma (catalyst-driven)
    "LLY", "UNH", "PFE", "JNJ", "MRK", "ABBV", "GILD", "AMGN",
    # Energy
    "XOM", "CVX", "COP", "OXY", "SLB",
    # Memes / High-vol speculative
    "GME", "AMC", "BB", "RIVN", "LCID", "COIN", "MARA", "RIOT",
    # Index/Vol ETFs (UOA can signal market hedging)
    "SPY", "QQQ", "IWM", "VIX",
]


# ============ Filters ============
MIN_VOL_OI_RATIO = 2.0       # today_vol / open_interest > this = unusual
MIN_TOTAL_VOLUME = 500       # skip illiquid (<500 contracts traded today)
MIN_PREMIUM_USD = 100_000    # premium = vol × price × 100 — skip cheap noise
TOP_N_ADMIN = 8


# ============ Helpers ============
def _safe_float(v) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v) -> int:
    try:
        if v is None:
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def _fmt_premium(usd: float) -> str:
    if usd >= 1_000_000:
        return f"${usd/1_000_000:.1f}M"
    if usd >= 1_000:
        return f"${usd/1_000:.0f}K"
    return f"${usd:.0f}"


# ============ Core scanner ============
def scan_ticker_uoa(ticker: str) -> dict | None:
    """Scan one ticker for unusual options activity.

    Returns dict with strongest signal {ticker, type, strike, expiry,
    volume, oi, ratio, last_price, premium_usd} OR None if no signal.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        t = yf.Ticker(ticker)
        expirations = t.options
    except Exception as e:
        print(f"[uoa] {ticker} fetch expirations err: {e}", flush=True)
        return None

    if not expirations:
        return None

    best_signal = None
    best_ratio = MIN_VOL_OI_RATIO

    # Check first 6 expiries (most volume is in front month + 1)
    for expiry in expirations[:6]:
        try:
            chain = t.option_chain(expiry)
        except Exception:
            continue

        # Check both calls and puts
        for opt_type, df in (("CALL", chain.calls), ("PUT", chain.puts)):
            if df is None or df.empty:
                continue

            for _, row in df.iterrows():
                vol = _safe_int(row.get("volume"))
                oi = _safe_int(row.get("openInterest"))
                strike = _safe_float(row.get("strike"))
                last_price = _safe_float(row.get("lastPrice"))

                if vol < MIN_TOTAL_VOLUME or oi <= 0:
                    continue

                ratio = vol / max(oi, 1)
                premium = vol * last_price * 100   # 1 contract = 100 shares

                if ratio < MIN_VOL_OI_RATIO:
                    continue
                if premium < MIN_PREMIUM_USD:
                    continue

                # Track strongest by ratio (could also weight by premium)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_signal = {
                        "ticker": ticker,
                        "type": opt_type,
                        "strike": strike,
                        "expiry": expiry,
                        "volume": vol,
                        "oi": oi,
                        "ratio": ratio,
                        "last_price": last_price,
                        "premium_usd": premium,
                    }
    return best_signal


def scan_all_universe() -> list[dict]:
    """Scan entire universe, return list of unusual signals."""
    signals = []
    for i, ticker in enumerate(_UOA_UNIVERSE):
        try:
            sig = scan_ticker_uoa(ticker)
            if sig:
                signals.append(sig)
        except Exception as e:
            print(f"[uoa] {ticker} scan err: {e}", flush=True)
        # Be gentle on yfinance — sleep between tickers
        if i % 10 == 9:
            time.sleep(2)
    return signals


# ============ Format ============
def format_admin_message(signals: list[dict], top_n: int = TOP_N_ADMIN) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    # Sort by ratio desc (most unusual first)
    signals = sorted(signals, key=lambda s: -s["ratio"])[:top_n]

    calls = sum(1 for s in signals if s["type"] == "CALL")
    puts = sum(1 for s in signals if s["type"] == "PUT")

    lines = [
        f"🔥 *Unusual Options — {today.strftime('%d %b %Y')}*",
        f"_{calls} Call · {puts} Put · vol/OI ≥ {MIN_VOL_OI_RATIO}x_",
        "",
    ]
    for s in signals:
        side_emoji = "🟢📈" if s["type"] == "CALL" else "🔴📉"
        lines.append(
            f"{side_emoji} *{s['ticker']}* · {s['type']} ${s['strike']:.0f} · {s['expiry']}\n"
            f"   Vol {s['volume']:,} / OI {s['oi']:,} = *{s['ratio']:.1f}x*\n"
            f"   Premium {_fmt_premium(s['premium_usd'])} · last ${s['last_price']:.2f}"
        )
        lines.append("")

    lines.append("💡 vol > 2x OI = fresh position opening (smart money mark?)")
    lines.append("_⚠️ ไม่ใช่คำแนะนำลงทุน — option trading เสี่ยงสูง_")
    return "\n".join(lines)


def format_pro_message(signals: list[dict]) -> str:
    signals = sorted(signals, key=lambda s: -s["ratio"])
    lines = ["🔥 *Unusual Options — Watchlist Hit*", ""]
    for s in signals:
        side_emoji = "🟢📈" if s["type"] == "CALL" else "🔴📉"
        lines.append(
            f"{side_emoji} *{s['ticker']}* · {s['type']} ${s['strike']:.0f} {s['expiry']}\n"
            f"   *{s['ratio']:.1f}x* vol/OI · Premium {_fmt_premium(s['premium_usd'])}"
        )
    lines.append("")
    lines.append("_💡 Smart money อาจ bet ก่อน catalyst (earnings, M&A)_")
    return "\n".join(lines)


# ============ Dedup ============
def _today_key() -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"uoa:{today.isoformat()}"


def _sig_key_admin(s: dict) -> str:
    return f"uoa_admin:{s['ticker']}:{s['type']}:{s['expiry']}"


def _sig_key_pro(user_id: str, s: dict) -> str:
    return f"uoa_pro:{s['ticker']}:{s['type']}:{s['expiry']}:{user_id}"


def _check_dispatch(key: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (key,))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[uoa] dispatch check err: {e}", flush=True)
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
        print(f"[uoa] dispatch mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _already_ran_today() -> bool:
    return _check_dispatch(_today_key())


def _mark_today_done():
    _mark_dispatch(_today_key(), "uoa", "admin")


# ============ Senders ============
def _send_admin(bot, signals: list[dict], dry_run: bool = False) -> int:
    fresh = [s for s in signals if not _check_dispatch(_sig_key_admin(s))]
    if not fresh:
        return 0

    msg = format_admin_message(fresh)
    if dry_run:
        print("==== DRY ADMIN ====")
        print(msg)
        return 0

    try:
        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        for s in fresh[:TOP_N_ADMIN]:
            _mark_dispatch(_sig_key_admin(s), "uoa_admin", s["ticker"])
        return 1
    except Exception as e:
        print(f"[uoa] admin DM err: {e}", flush=True)
        return 0


def _send_pro_watchlists(bot, signals: list[dict], dry_run: bool = False) -> int:
    pool_tickers = {s["ticker"] for s in signals}
    if not pool_tickers:
        return 0

    try:
        from smart_money_cron import query_pro_users_with_watchlist
        pro_users = query_pro_users_with_watchlist(limit=500)
    except Exception as e:
        print(f"[uoa] query pro err: {e}", flush=True)
        return 0

    sent_count = 0
    for u in pro_users:
        uid = u["user_id"]
        watchlist = {t.upper() for t in (u.get("watchlist") or [])}
        matched = [s for s in signals if s["ticker"].upper() in watchlist]
        if not matched:
            continue

        fresh = [s for s in matched if not _check_dispatch(_sig_key_pro(uid, s))]
        if not fresh:
            continue

        msg = format_pro_message(fresh)
        if dry_run:
            print(f"==== DRY PRO {uid} ====")
            print(msg)
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            sent_count += 1
            for s in fresh:
                _mark_dispatch(_sig_key_pro(uid, s), "uoa_pro", uid)
            time.sleep(0.8)
        except Exception as e:
            print(f"[uoa] PRO DM err {uid}: {e}", flush=True)

    return sent_count


# ============ Entry points ============
def run_once(bot, dry_run: bool = False):
    print(f"[uoa] starting scan ({len(_UOA_UNIVERSE)} tickers)...", flush=True)
    signals = scan_all_universe()
    print(f"[uoa] found {len(signals)} unusual signals", flush=True)

    if not signals:
        if not dry_run:
            try:
                bot.send_message(config.ADMIN_ID, "🔥 UOA: ไม่มี unusual activity เข้าเกณฑ์วันนี้")
            except Exception:
                pass
        return

    _send_admin(bot, signals, dry_run=dry_run)
    pro_sent = _send_pro_watchlists(bot, signals, dry_run=dry_run)
    print(f"[uoa] sent to {pro_sent} PRO users", flush=True)


def run_uoa_cron(bot):
    """Daemon thread — daily at UOA_HOUR_ICT (default 21:30 ICT = ~10:30 ET, 1hr after US open)"""
    if not getattr(config, "UOA_ENABLED", True):
        print("[uoa] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "UOA_HOUR_ICT", 21)
    target_m = getattr(config, "UOA_MINUTE_ICT", 30)
    print(f"[uoa] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(4 * 60)   # warm-up — let other crons settle

    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=7)
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                # Skip weekends (no US trading)
                if now.weekday() in (5, 6):
                    pass
                elif not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[uoa] loop err: {e}", flush=True)
        time.sleep(20 * 60)


if __name__ == "__main__":
    print("=== UOA Dry Run ===")
    # Test 5 tickers only in CLI for quick check
    test_tickers = ["AAPL", "NVDA", "TSLA", "AMD", "SPY"]
    for tk in test_tickers:
        sig = scan_ticker_uoa(tk)
        if sig:
            print(f"{tk}: {sig['type']} ${sig['strike']:.0f} {sig['expiry']} · vol {sig['volume']:,} / OI {sig['oi']:,} = {sig['ratio']:.1f}x · premium ${sig['premium_usd']:,.0f}")
        else:
            print(f"{tk}: no signal")
