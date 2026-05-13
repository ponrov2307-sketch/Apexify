"""
earnings_prep_cron.py — DM admin 1 วันก่อนหุ้นใหญ่รายงานผล

User feedback: อยากให้ DM admin ก่อน earnings เพื่อทำ FB content tease ก่อน 1 วัน

Workflow:
  1. Daily cron 16:00 ICT (หลังตลาด US เปิด — ข้อมูล calendar อัปเดต)
  2. Scan EARNINGS_POOL (~50 ตัวเด่นๆ) — เช็คว่าใครรายงานพรุ่งนี้ (ICT date)
  3. DM admin: ticker + วันเวลา + EPS consensus + ราคา 7-day move + hook
  4. dispatch_log dedup เพื่อไม่ส่งซ้ำ
"""

import time
from datetime import datetime, timedelta, timezone

import config


# Pool หุ้นที่ admin สนใจจะ tease ก่อน earnings — Mag 7 + story stocks + hot movers
EARNINGS_POOL = [
    # Mag 7 — ต้องโพสต์ทุกครั้ง
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # AI / Semi major
    "AMD", "AVGO", "MU", "ARM", "SMCI", "DELL", "ALAB",
    # Software / Cloud
    "PLTR", "SNOW", "CRWD", "PANW", "DDOG", "NET", "CRM", "ORCL", "ADBE",
    # AI Power
    "VST", "CEG", "TLN", "VRT",
    # Internet / Consumer
    "NFLX", "DIS", "UBER", "SHOP", "ABNB", "DASH", "TOST", "RDDT", "SPOT", "DUOL", "HIMS",
    # International
    "SE", "MELI", "BABA",
    # Crypto / Fintech
    "COIN", "MSTR", "HOOD", "SOFI", "UPST",
    # Story / Growth
    "RKLB", "ASTS", "IONQ", "RIVN", "LCID",
]


def _format_eta_thai(eps_date) -> str:
    """Format วันที่ + เวลาให้อ่านง่าย"""
    try:
        ict_dt = eps_date + timedelta(hours=7)
        return ict_dt.strftime("%a %d %b · %H:%M ICT")
    except Exception:
        return str(eps_date)


def _seven_day_move_pct(symbol: str) -> float:
    """ราคา 7 วันย้อนหลัง — สำหรับใส่ใน DM"""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="8d")
        if len(hist) < 2:
            return 0.0
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[0])
        return (last - prev) / prev * 100
    except Exception:
        return 0.0


def _next_earnings(symbol: str):
    """หา earnings date ถัดไปของ ticker

    Returns: dict { date, eps_estimate, eps_actual } หรือ None
    """
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)

        # ใช้ get_earnings_dates เป็นหลัก
        try:
            df = t.get_earnings_dates(limit=8)
        except Exception:
            df = None

        if df is None or df.empty:
            return None

        now_utc = datetime.now(timezone.utc)
        future = []
        for idx in df.index:
            try:
                dt = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now_utc:
                    continue
                row = df.loc[idx]
                # 🛡 Robust EPS extraction — yfinance returns pandas Series with NaN
                eps_est = None
                try:
                    import pandas as pd
                    raw_eps = row.get("EPS Estimate") if hasattr(row, "get") else None
                    if raw_eps is not None and not pd.isna(raw_eps):
                        eps_est = float(raw_eps)
                except (ValueError, TypeError):
                    eps_est = None
                future.append({
                    "date": dt,
                    "eps_estimate": eps_est,
                })
            except Exception:
                continue

        if not future:
            return None
        future.sort(key=lambda x: x["date"])
        return future[0]
    except Exception as e:
        print(f"[earnings-prep] {symbol} fetch err: {e}", flush=True)
        return None


def _is_nan(v):
    try:
        return v != v   # NaN != NaN
    except Exception:
        return False


def _build_hook(symbol: str, move_7d: float) -> str:
    """Suggested FB tease hook"""
    if move_7d >= 5:
        return f"{symbol} วิ่ง +{move_7d:.1f}% สัปดาห์ที่ผ่านมา — ลุ้น guidance จะ confirm trend?"
    elif move_7d <= -5:
        return f"{symbol} ร่วง {move_7d:.1f}% สัปดาห์ที่ผ่านมา — earnings พรุ่งนี้จะรีบาวด์?"
    else:
        return f"{symbol} earnings พรุ่งนี้ — ตลาดยังนิ่งรอ ลุ้นเซอร์ไพรส์ไหม?"


def _today_key() -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"earnings_prep:{today.isoformat()}"


def _already_ran_today() -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (_today_key(),))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[earnings-prep] _already_ran_today DB err: {e}", flush=True)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_today_done():
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_today_key(), "earnings_prep", "admin"),
        )
        conn.commit()
    except Exception as e:
        print(f"[earnings-prep] mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def find_tomorrow_earnings() -> list:
    """Scan EARNINGS_POOL — return list ของ {symbol, eta, eps_est, move_7d, hook}"""
    today_ict = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    tomorrow_ict = today_ict + timedelta(days=1)

    found = []
    for sym in EARNINGS_POOL:
        info = _next_earnings(sym)
        if not info:
            continue
        # convert UTC → ICT date
        ict_date = (info["date"] + timedelta(hours=7)).date()
        # อนุญาตวันรุ่งขึ้น + วันถัดไป (2 วัน หน้า) สำหรับเผื่อ pre-tease
        if ict_date == tomorrow_ict:
            move_7d = _seven_day_move_pct(sym)
            found.append({
                "symbol": sym,
                "eta": info["date"],
                "eps_est": info.get("eps_estimate"),
                "move_7d": move_7d,
                "hook": _build_hook(sym, move_7d),
            })
        time.sleep(0.3)   # rate-limit yfinance

    return found


def _build_message(items: list) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    tomorrow = today + timedelta(days=1)

    lines = [
        f"📅 *Earnings Tomorrow — {tomorrow.strftime('%d %b %Y')}*",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for i, it in enumerate(items, 1):
        sym = it["symbol"]
        eta_str = _format_eta_thai(it["eta"])
        eps_str = f"EPS est: ${it['eps_est']:.2f}" if it["eps_est"] is not None else "EPS est: -"
        move = it["move_7d"]
        move_str = f"{move:+.1f}% 7d" if abs(move) >= 0.1 else "นิ่ง 7d"
        lines.append(f"{i}. *{sym}* — {eta_str}")
        lines.append(f"   📊 {eps_str} · {move_str}")
        lines.append(f"   💡 _{it['hook']}_")
        lines.append("")
    lines.extend([
        "━━━━━━━━━━━━━━",
        "_tease FB เย็นนี้ก่อน เอาไปทำคอนเทนต์เต็มในวัน earnings_",
    ])
    return "\n".join(lines)


def run_once(bot, dry_run: bool = False):
    if not config.ADMIN_ID:
        print("[earnings-prep] no ADMIN_ID set, skip", flush=True)
        return

    print("[earnings-prep] scanning earnings calendar...", flush=True)
    items = find_tomorrow_earnings()

    if not items:
        print("[earnings-prep] no earnings tomorrow — skip", flush=True)
        return

    msg = _build_message(items)
    if dry_run:
        print("==== DRY RUN ====")
        print(msg)
        return

    try:
        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown")
        print(f"[earnings-prep] sent {len(items)} items to admin", flush=True)
    except Exception as e:
        print(f"[earnings-prep] DM err: {e}", flush=True)
        try:
            bot.send_message(config.ADMIN_ID, msg.replace("*", "").replace("_", ""))
        except Exception:
            pass


def run_earnings_prep_cron(bot):
    """Daemon thread — daily 16:00 ICT"""
    if not getattr(config, "EARNINGS_PREP_ENABLED", True):
        print("[earnings-prep] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "EARNINGS_PREP_HOUR_ICT", 16)
    target_m = getattr(config, "EARNINGS_PREP_MINUTE_ICT", 0)
    print(f"[earnings-prep] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(2 * 60)  # warm-up

    while True:
        try:
            now = (datetime.now(timezone.utc) + timedelta(hours=7))
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                if not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[earnings-prep] loop err: {e}", flush=True)
        time.sleep(20 * 60)


if __name__ == "__main__":
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
