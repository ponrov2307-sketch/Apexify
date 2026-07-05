"""
daily_signals_digest.py — DM PRO users ทุกวัน 22:00 ICT
                          ส่ง 1 DM รวม Smart Money + Congress + UOA = ไม่ spam

User context (2026-05-17): "มันเยอะไปไหม มันจะเด้งทั้งวันเลยนะ 555"
→ Reduce notification fatigue: 3-4 cron DMs/day → 1 unified digest/day.

Schedule:
  - 22:00 ICT (after UOA's 21:30 scan completes, before bedtime)
  - PRO users only (admins still get 3 separate detailed DMs at 16/17/21:30
    for content-creation purposes — see config.INSIDER_SEND_PRO_INDIVIDUAL)

Workflow:
  1. Re-run 3 scanners (caching at API level keeps this cheap)
  2. For each PRO user with watchlist:
     - Match each signal type against watchlist
     - If any section has matches → build combined DM
     - Per-section dedup (digest_pro:{type}:{ticker}:{date}:{uid})
  3. Skip user entirely if zero matches across all 3 sections (no noise)

Architecture decisions:
  - No DB cache layer — scanners re-run (cleaner, ~5min total)
  - Each section dedups independently (user may see same Smart Money signal
    in 2 days but UOA won't repeat unless ratio changes)
  - Admin gets nothing here (uses individual cron DMs)
"""

import time
from datetime import datetime, timedelta, timezone

import config


# ============ Scheduling ============
TARGET_HOUR_ICT = 22
TARGET_MINUTE_ICT = 0
POLL_INTERVAL_SEC = 20 * 60
WARMUP_SEC = 5 * 60


# ============ Section limits (avoid super-long DMs) ============
MAX_SECTION_ITEMS = 3   # show top 3 per section in digest
MAX_TOTAL_ITEMS = 9     # 3 sections × 3 = 9 lines max


# ============ Dedup ============
def _today_key() -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"digest:{today.isoformat()}"


def _user_section_key(user_id: str, section: str, ticker: str, identifier: str) -> str:
    """Per-user dedup key — section + ticker + signal identifier (date/expiry/etc.)"""
    return f"digest_pro:{section}:{ticker}:{identifier}:{user_id}"


def _check_dispatch(key: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (key,))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[digest] dispatch check err: {e}", flush=True)
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
        print(f"[digest] dispatch mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _already_ran_today() -> bool:
    return _check_dispatch(_today_key())


def _mark_today_done():
    _mark_dispatch(_today_key(), "digest", "admin")


# ============ Section runners ============
def _scan_smart_money() -> list[dict]:
    """Returns Smart Money cluster buys (after quality filter)."""
    try:
        from smart_money_cron import scrape_cluster_buys, filter_quality
        items = scrape_cluster_buys()
        return filter_quality(items)
    except Exception as e:
        print(f"[digest] smart-money scan err: {e}", flush=True)
        return []


def _scan_congress() -> list[dict]:
    """Returns Congress trades (after filter)."""
    if not getattr(config, "CONGRESS_ENABLED", False):
        # Senate/House Stock Watcher APIs ตายตั้งแต่ 2026-05-17 (ดู congress_cron.py) —
        # เช็ค flag เดียวกับ run_congress_cron กันยิง API ตายทุกคืนแบบเงียบๆ
        return []
    try:
        from congress_cron import fetch_senate_transactions, fetch_house_transactions, filter_and_enrich
        raw = fetch_senate_transactions() + fetch_house_transactions()
        return filter_and_enrich(raw)
    except Exception as e:
        print(f"[digest] congress scan err: {e}", flush=True)
        return []


def _scan_uoa() -> list[dict]:
    """Returns UOA signals (after filter)."""
    try:
        from uoa_cron import scan_all_universe
        return scan_all_universe()
    except Exception as e:
        print(f"[digest] uoa scan err: {e}", flush=True)
        return []


# ============ Per-user matching ============
def _match_smart_money(items: list[dict], watchlist: set[str], user_id: str) -> list[dict]:
    """Filter SM items to user's watchlist + dedup against past DMs."""
    matched = [it for it in items if it["ticker"].upper() in watchlist]
    fresh = []
    for it in matched:
        key = _user_section_key(user_id, "sm", it["ticker"], it["trade_date"])
        if _check_dispatch(key):
            continue
        fresh.append(it)
    return fresh[:MAX_SECTION_ITEMS]


def _match_congress(items: list[dict], watchlist: set[str], user_id: str) -> list[dict]:
    matched = [it for it in items if it["ticker"].upper() in watchlist]
    fresh = []
    for it in matched:
        key = _user_section_key(
            user_id, "congress",
            it["ticker"],
            f"{it['transaction_date']}:{it['politician'][:10]}",
        )
        if _check_dispatch(key):
            continue
        fresh.append(it)
    return fresh[:MAX_SECTION_ITEMS]


def _match_uoa(signals: list[dict], watchlist: set[str], user_id: str) -> list[dict]:
    matched = [s for s in signals if s["ticker"].upper() in watchlist]
    fresh = []
    for s in matched:
        key = _user_section_key(
            user_id, "uoa",
            s["ticker"],
            f"{s['type']}:{s['expiry']}",
        )
        if _check_dispatch(key):
            continue
        fresh.append(s)
    return fresh[:MAX_SECTION_ITEMS]


# ============ Format ============
def _fmt_usd(v: int | float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def _format_digest(sm_items: list[dict], cong_items: list[dict], uoa_items: list[dict]) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    lines = [
        f"📊 *Daily Smart Signals — {today.strftime('%d %b %Y')}*",
        "_หุ้นใน watchlist ของคุณ ที่มี insider activity วันนี้_",
        "",
    ]

    if sm_items:
        lines.append("🐋 *Smart Money (CEO/CFO buys)*")
        for it in sm_items:
            lines.append(
                f"   • *{it['ticker']}* · {_fmt_usd(it['value_usd'])} · {it.get('ins_count', 0)} insiders · {it['trade_date']}"
            )
        lines.append("")

    if cong_items:
        lines.append("🏛 *Congress Trades*")
        for it in cong_items:
            tx_emoji = "🟢" if "purchase" in it["transaction_type"].lower() else "🔴"
            chamber = "Sen" if it["chamber"] == "Senate" else "Rep"
            lines.append(
                f"   {tx_emoji} *{it['ticker']}* · {chamber}. {it['politician'][:25]} · {_fmt_usd(it['amount_max'])} · {it['transaction_date']}"
            )
        lines.append("")

    if uoa_items:
        lines.append("🔥 *Unusual Options*")
        for s in uoa_items:
            arrow = "📈" if s["type"] == "CALL" else "📉"
            lines.append(
                f"   {arrow} *{s['ticker']}* {s['type']} ${s['strike']:.0f} {s['expiry']} · *{s['ratio']:.1f}x* vol/OI · {_fmt_usd(s['premium_usd'])}"
            )
        lines.append("")

    lines.append("_💡 Smart signals = early warning_")
    lines.append("_ไม่ใช่คำแนะนำลงทุน_")
    return "\n".join(lines)


# ============ Mark dispatched (after successful DM) ============
def _mark_user_dispatched(user_id: str, sm: list[dict], cong: list[dict], uoa: list[dict]):
    for it in sm:
        _mark_dispatch(_user_section_key(user_id, "sm", it["ticker"], it["trade_date"]),
                       "digest_pro_sm", user_id)
    for it in cong:
        _mark_dispatch(
            _user_section_key(user_id, "congress", it["ticker"],
                              f"{it['transaction_date']}:{it['politician'][:10]}"),
            "digest_pro_congress", user_id,
        )
    for s in uoa:
        _mark_dispatch(
            _user_section_key(user_id, "uoa", s["ticker"], f"{s['type']}:{s['expiry']}"),
            "digest_pro_uoa", user_id,
        )


# ============ Entry points ============
def run_once(bot, dry_run: bool = False):
    print("[digest] starting daily insider digest scan...", flush=True)

    # Run 3 scans in sequence
    print("[digest] scanning Smart Money...", flush=True)
    sm_items = _scan_smart_money()
    print(f"[digest] SM: {len(sm_items)} signals", flush=True)

    print("[digest] scanning Congress...", flush=True)
    cong_items = _scan_congress()
    print(f"[digest] Congress: {len(cong_items)} signals", flush=True)

    print("[digest] scanning UOA...", flush=True)
    uoa_items = _scan_uoa()
    print(f"[digest] UOA: {len(uoa_items)} signals", flush=True)

    if not (sm_items or cong_items or uoa_items):
        print("[digest] no signals across any section — skipping DM", flush=True)
        return

    # Get PRO users with watchlists
    try:
        from smart_money_cron import query_pro_users_with_watchlist
        pro_users = query_pro_users_with_watchlist(limit=500)
    except Exception as e:
        print(f"[digest] query PRO err: {e}", flush=True)
        return

    sent_count = 0
    skipped_no_match = 0
    for u in pro_users:
        uid = u["user_id"]
        watchlist = {t.upper() for t in (u.get("watchlist") or [])}
        if not watchlist:
            continue

        sm_match = _match_smart_money(sm_items, watchlist, uid)
        cong_match = _match_congress(cong_items, watchlist, uid)
        uoa_match = _match_uoa(uoa_items, watchlist, uid)

        # Skip user if no matches OR all already-DMd
        total_matches = len(sm_match) + len(cong_match) + len(uoa_match)
        if total_matches == 0:
            skipped_no_match += 1
            continue

        msg = _format_digest(sm_match, cong_match, uoa_match)
        if dry_run:
            print(f"==== DRY DIGEST user={uid} ({total_matches} signals) ====")
            print(msg)
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            sent_count += 1
            _mark_user_dispatched(uid, sm_match, cong_match, uoa_match)
            time.sleep(0.8)   # Telegram rate limit
        except Exception as e:
            print(f"[digest] DM err {uid}: {e}", flush=True)

    print(f"[digest] sent {sent_count} digests · skipped {skipped_no_match} no-match users", flush=True)


def run_digest_cron(bot):
    """Daemon thread — daily 22:00 ICT (after UOA scan at 21:30)"""
    if not getattr(config, "DIGEST_ENABLED", True):
        print("[digest] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "DIGEST_HOUR_ICT", TARGET_HOUR_ICT)
    target_m = getattr(config, "DIGEST_MINUTE_ICT", TARGET_MINUTE_ICT)
    print(f"[digest] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(WARMUP_SEC)

    while True:
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=7)   # ICT
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                # Skip weekends
                if now.weekday() in (5, 6):
                    pass
                elif not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[digest] loop err: {e}", flush=True)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    print("=== Daily Signals Digest Dry Run ===")
    sm = _scan_smart_money()
    cong = _scan_congress()
    uoa = _scan_uoa()
    print(f"Smart Money: {len(sm)} · Congress: {len(cong)} · UOA: {len(uoa)}")

    if sm or cong or uoa:
        sample_watchlist = {"AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "AMZN", "META"}
        sm_match = sm[:MAX_SECTION_ITEMS] if any(it["ticker"].upper() in sample_watchlist for it in sm) else []
        cong_match = cong[:MAX_SECTION_ITEMS] if any(it["ticker"].upper() in sample_watchlist for it in cong) else []
        uoa_match = uoa[:MAX_SECTION_ITEMS] if any(s["ticker"].upper() in sample_watchlist for s in uoa) else []

        print("\n" + _format_digest(sm_match, cong_match, uoa_match))
    else:
        print("(no signals)")
