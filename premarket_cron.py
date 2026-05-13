"""
premarket_cron.py — DM VIP+PRO ข้อมูล pre-market gap movers ก่อน US เปิด 1 ชม.

User feedback: PP P. (2026-05-13) — day trader ส่วนใหญ่เล่น small cap +
อยากเห็น setup ก่อน US เปิด (gap up/down) เพื่อเตรียมเทรด

Workflow:
  1. Daily cron 20:30 ICT (= 06:30 ET — 1 ชม. ก่อน market open 09:30 ET)
  2. Scan ~80 tickers (Morning Movers + small cap pool) parallel — fetch
     premarket price + volume + prev close → gap%
  3. Filter: |gap| ≥ 3%, premarket vol ≥ 10K
  4. สำหรับแต่ละ VIP/PRO user:
     - Watchlist matches (personalized signal)
     - Top 3 outside watchlist (discovery)
  5. DM พร้อม warning ว่า premarket vol น้อย, ราคาเปิดจริงอาจต่าง
  6. dispatch_log dedup — 1 ครั้ง/user/วัน

Skip: weekends (Sat/Sun) + วันที่ตลาด US ปิด (ตามนี้ premarket vol จะเป็น 0
อยู่แล้ว — filter auto กรองออก)
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import config


# ============ Constants ============
MIN_GAP_PCT = float(getattr(config, "PREMARKET_MIN_GAP_PCT", 3.0))
MIN_PREMARKET_VOL = 10_000        # ตัด ticker ที่ไม่มี vol จริง (กัน noise)
TOP_DISCOVERY = 3                  # gap movers นอก watchlist ที่จะแสดง
MAX_WATCHLIST_DISPLAY = 5          # cap watchlist matches แสดงสูงสุด
WORKERS = 12                       # ThreadPoolExecutor concurrent fetches

# Lazy-loaded small cap set (avoid circular import)
_SMALL_CAP_SET = None


def _get_universe() -> list:
    """รวม universe จาก alert_system.MORNING_MOVER_UNIVERSE + daily_stock_picker.SMALL_CAP_DAYTRADE

    ใช้ universe เดียวกับฟีเจอร์อื่นๆ — consistent + DRY
    """
    universe = set()
    try:
        from alert_system import MORNING_MOVER_UNIVERSE
        universe.update(MORNING_MOVER_UNIVERSE.keys())
    except Exception as e:
        print(f"[premarket] import MORNING_MOVER err: {e}", flush=True)
    try:
        from daily_stock_picker import SMALL_CAP_DAYTRADE
        universe.update(SMALL_CAP_DAYTRADE)
    except Exception as e:
        print(f"[premarket] import SMALL_CAP_DAYTRADE err: {e}", flush=True)
    return sorted(universe)


def _is_small_cap(symbol: str) -> bool:
    """Cache lazy-import — รู้ว่า ticker เป็น small cap ไหม"""
    global _SMALL_CAP_SET
    if _SMALL_CAP_SET is None:
        try:
            from daily_stock_picker import SMALL_CAP_DAYTRADE
            _SMALL_CAP_SET = set(SMALL_CAP_DAYTRADE)
        except Exception:
            _SMALL_CAP_SET = set()
    return symbol in _SMALL_CAP_SET


# ============ Fetch logic ============
def _fetch_premarket(symbol: str) -> dict:
    """ดึง premarket price + gap vs prev close

    Returns: dict { symbol, premarket_price, prev_close, gap_pct, premarket_volume } หรือ None
    """
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)

        # 1-min bars including pre/post-market (today)
        # period=2d เผื่อ edge case ที่ today ยังไม่มี data เริ่ม
        hist = t.history(period="2d", interval="1m", prepost=True)
        if hist is None or hist.empty:
            return None

        # Last bar = most recent premarket price
        last_bar = hist.iloc[-1]
        last_price = float(last_bar["Close"])
        if last_price <= 0:
            return None

        # Previous close (regular session) — period=5d เผื่อหาวันก่อน
        hist_daily = t.history(period="5d", interval="1d", prepost=False)
        if hist_daily is None or hist_daily.empty or len(hist_daily) < 1:
            return None
        prev_close = float(hist_daily["Close"].iloc[-1])
        if prev_close <= 0:
            return None

        gap_pct = (last_price - prev_close) / prev_close * 100

        # Premarket volume = sum ของ bars ที่ "extended hours" ตั้งแต่ prev close
        # ใช้ total ของ history ที่ดึงมา (period=2d, prepost=True รวมทุก session)
        # ในชั่วโมง 06:30 ET premarket, ส่วนใหญ่ vol ที่ได้คือ premarket จริงๆ
        total_pm_vol = float(hist["Volume"].sum())

        return {
            "symbol": symbol,
            "premarket_price": last_price,
            "prev_close": prev_close,
            "gap_pct": gap_pct,
            "premarket_volume": total_pm_vol,
        }
    except Exception as e:
        # Silent fail — caller logs aggregate stats
        return None


def scan_universe(min_gap_pct: float = None, min_vol: int = MIN_PREMARKET_VOL) -> list:
    """Parallel scan — return list of movers sorted by abs(gap_pct) desc"""
    if min_gap_pct is None:
        min_gap_pct = MIN_GAP_PCT

    universe = _get_universe()
    if not universe:
        print("[premarket] empty universe — skip", flush=True)
        return []

    print(f"[premarket] scanning {len(universe)} tickers (min gap {min_gap_pct}%, min vol {min_vol})...", flush=True)
    movers = []
    failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="premarket") as pool:
        futures = {pool.submit(_fetch_premarket, sym): sym for sym in universe}
        for fut in as_completed(futures):
            data = fut.result()
            if data is None:
                failed += 1
                continue
            if abs(data["gap_pct"]) < min_gap_pct:
                continue
            if data["premarket_volume"] < min_vol:
                continue
            movers.append(data)

    movers.sort(key=lambda x: -abs(x["gap_pct"]))
    print(f"[premarket] fetched {len(universe) - failed}/{len(universe)} OK · {len(movers)} pass filter", flush=True)
    return movers


# ============ Message building ============
def _fmt_vol(vol: float) -> str:
    if vol >= 1_000_000:
        return f"{vol/1_000_000:.1f}M"
    elif vol >= 1000:
        return f"{vol/1000:.0f}K"
    return f"{int(vol)}"


def _format_mover(item: dict) -> str:
    """Format 1 mover line — incl. company name in parens (PP P. 2026-05-13)"""
    sym = item["symbol"]
    price = item["premarket_price"]
    gap = item["gap_pct"]
    vol = item["premarket_volume"]
    small_tag = " 🔥small cap" if _is_small_cap(sym) else ""
    try:
        from bot_utils import get_company_short_name
        name = get_company_short_name(sym)
    except Exception:
        name = ""
    name_label = f" ({name})" if name else ""
    return f"{sym}{name_label} ${price:,.2f} ({gap:+.1f}%){small_tag} · vol {_fmt_vol(vol)}"


def build_premarket_message(in_watchlist: list, outside_watchlist: list, watchlist_size: int) -> str:
    """Build personalized DM"""
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()

    lines = [
        f"🔔 *Pre-Market Movers — {today.strftime('%d %b')} (06:30 ET)*",
        "_1 ชม.ก่อน US เปิด · gap ≥ 3%_",
        "━━━━━━━━━━━━━━",
        "",
    ]

    # Watchlist section (priority — personalized)
    if in_watchlist:
        lines.append("📌 *ใน Watchlist คุณ:*")
        for it in in_watchlist[:MAX_WATCHLIST_DISPLAY]:
            lines.append(f"   • {_format_mover(it)}")
        lines.append("")
    elif watchlist_size > 0:
        lines.append("📌 *ใน Watchlist คุณ:* _ไม่มี gap ≥3% วันนี้_")
        lines.append("")

    # Discovery section
    if outside_watchlist:
        lines.append("🌐 *ตลาดวันนี้ (Top movers):*")
        for it in outside_watchlist[:TOP_DISCOVERY]:
            lines.append(f"   • {_format_mover(it)}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━",
        "_⚠️ pre-market vol น้อย ราคาเปิดจริงอาจต่าง_",
        "_💡 พิมพ์ ticker เพื่อให้ Apexify วิเคราะห์เชิงลึก_",
    ])
    if watchlist_size < 5:
        lines.append("_➕ เพิ่มหุ้นใน /watch รับ alert specific มากขึ้น_")

    return "\n".join(lines)


# ============ Dedup (dispatch_log) ============
def _today_key(user_id: str) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"premarket:{today.isoformat()}:{user_id}"


def _user_already_received(user_id: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (_today_key(user_id),))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[premarket] dedup check err uid={user_id}: {e}", flush=True)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_user_sent(user_id: str):
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_today_key(user_id), "premarket", str(user_id)),
        )
        conn.commit()
    except Exception as e:
        print(f"[premarket] mark err {user_id}: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============ Entry points ============
def run_once(bot, dry_run: bool = False):
    """1 cycle — scan + DM VIP+PRO users"""
    # Skip weekends (ICT = US weekend ก็ปิดตลาด)
    now_ict = config.thai_now() if hasattr(config, "thai_now") else (datetime.now(timezone.utc) + timedelta(hours=7))
    if now_ict.weekday() >= 5:   # 5=Saturday, 6=Sunday
        print("[premarket] weekend — skip", flush=True)
        return

    # Scan universe
    movers = scan_universe()
    if not movers:
        print("[premarket] no movers found — skip DM", flush=True)
        return

    # Get VIP+PRO users with watchlist
    try:
        from database import query_paying_users_with_watchlist
    except Exception as e:
        print(f"[premarket] DB import err: {e}", flush=True)
        return

    users = query_paying_users_with_watchlist(roles=("vip", "pro"), limit=500)
    if not users:
        print("[premarket] no VIP/PRO users with watchlist", flush=True)
        return

    print(f"[premarket] processing {len(users)} VIP/PRO users", flush=True)
    sent_count = 0

    for u in users:
        uid = u["user_id"]
        watchlist = {t.upper() for t in (u.get("watchlist") or [])}

        # Skip if already sent today (idempotent re-run)
        if _user_already_received(uid) and not dry_run:
            continue

        # Split movers — watchlist match vs outside
        in_wl = [m for m in movers if m["symbol"].upper() in watchlist]
        outside_wl = [m for m in movers if m["symbol"].upper() not in watchlist]

        # ถ้าไม่มี watchlist match + ไม่มี outside (ไม่น่าเกิด แต่กัน safety) → skip
        if not in_wl and not outside_wl:
            continue

        msg = build_premarket_message(in_wl, outside_wl, len(watchlist))

        if dry_run:
            print(f"==== DRY user={uid} (in:{len(in_wl)} out:{len(outside_wl)}) ====")
            print(msg)
            print()
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            _mark_user_sent(uid)
            sent_count += 1
            time.sleep(0.8)   # rate-limit Telegram bulk DM
        except Exception as e:
            print(f"[premarket] send err {uid}: {e}", flush=True)
            # Fallback: plain text (in case Markdown breaks)
            try:
                plain = msg.replace("*", "").replace("_", "")
                bot.send_message(uid, plain, disable_web_page_preview=True)
                _mark_user_sent(uid)
                sent_count += 1
            except Exception:
                pass

    print(f"[premarket] sent {sent_count}/{len(users)} users", flush=True)


def run_premarket_cron(bot):
    """Daemon thread — daily 20:30 ICT (= 06:30 ET — 1 hr before US open)"""
    if not getattr(config, "PREMARKET_ENABLED", True):
        print("[premarket] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "PREMARKET_HOUR_ICT", 20)
    target_m = getattr(config, "PREMARKET_MINUTE_ICT", 30)
    print(f"[premarket] cron started — daily at {target_h:02d}:{target_m:02d} ICT (VIP+PRO, gap ≥{MIN_GAP_PCT}%)", flush=True)

    time.sleep(2 * 60)   # warm-up wait

    while True:
        try:
            now_ict = config.thai_now() if hasattr(config, "thai_now") else (datetime.now(timezone.utc) + timedelta(hours=7))
            # Trigger window: target_m ถึง target_m+30 นาที (กัน skip ถ้า poll ช้า)
            if now_ict.hour == target_h and target_m <= now_ict.minute < target_m + 30:
                run_once(bot)
        except Exception as e:
            print(f"[premarket] loop err: {e}", flush=True)
        time.sleep(15 * 60)   # poll ทุก 15 นาที


if __name__ == "__main__":
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
