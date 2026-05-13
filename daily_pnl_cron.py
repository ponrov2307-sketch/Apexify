"""
daily_pnl_cron.py — เช้าวันใหม่ DM user PRO สรุป watchlist ของตัวเอง

User feedback: อยากให้ feature ที่ทำให้ PRO เพิ่ม engagement + เห็น value
→ summary watchlist ทุกเช้า → user เห็นทันทีว่าตัวไหนวิ่ง + ข่าวสด

Workflow:
  1. Daily cron 08:00 ICT (US market ปิดตอน 04:00 ICT แล้ว — มีเวลา 4 ชม. ให้ news catch up)
  2. Query PRO users ที่ยังไม่หมดอายุ + มี watchlist
  3. สำหรับแต่ละ user — fetch ราคา + move% + RSI + news ล่าสุด ของ tickers
  4. DM สรุปแยกตามตัว (sorted by abs move% desc)
  5. dispatch_log dedup — 1 ครั้ง/user/วัน
"""

import time
from datetime import datetime, timedelta, timezone

import config


# กัน DM ไม่ให้ DM user ที่ watchlist ยาวเกิน (rate-limit Telegram + ไม่ overwhelm user)
MAX_TICKERS_PER_USER = 10


def _fetch_ticker_snapshot(symbol: str) -> dict:
    """Fetch last close + previous close + vol + RSI + 1 ข่าวสด

    Returns: dict { price, move_pct, vol_ratio, rsi, headline, news_url, age_h } หรือ None
    """
    try:
        from technical_tools import calculate_technical_indicators
        td, _, err = calculate_technical_indicators(symbol, generate_chart=False)
        if err or not td:
            return None

        price = td.get("price", 0)
        rsi = td.get("rsi", 50)
        vol_ratio = td.get("volume_ratio", 1) or 1

        # daily move (close vs prev close)
        move_pct = 0
        try:
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="2d")
            if len(hist) >= 2:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                move_pct = (last - prev) / prev * 100
        except Exception:
            pass

        # ข่าวสดล่าสุด ≤24h (ตอนเช้า user สนใจข่าว overnight)
        news = _fetch_fresh_news(symbol, max_age_h=24)

        return {
            "symbol": symbol,
            "price": price,
            "move_pct": move_pct,
            "vol_ratio": vol_ratio,
            "rsi": rsi,
            "headline": news["headline"] if news else "",
            "news_url": news["url"] if news else "",
            "age_h": news["age_h"] if news else 0,
        }
    except Exception as e:
        print(f"[daily-pnl] {symbol} err: {e}", flush=True)
        return None


def _fetch_fresh_news(symbol: str, max_age_h: int = 24) -> dict:
    """Reuse logic จาก daily_stock_picker._fetch_news_for_symbol แต่ inline เพื่อไม่ผูกกัน"""
    try:
        import yfinance as yf
        items = yf.Ticker(symbol).news or []
        if not items:
            return None
        now = datetime.now(timezone.utc)
        candidates = []
        for n in items[:8]:
            content = n.get("content") if isinstance(n.get("content"), dict) else n
            pub_dt = None
            pub_str = content.get("pubDate") or content.get("displayTime")
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                except Exception:
                    pass
            if pub_dt is None:
                epoch = n.get("providerPublishTime") or content.get("providerPublishTime")
                if epoch:
                    try:
                        pub_dt = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
                    except Exception:
                        pass
            if pub_dt is None:
                continue
            age_h = (now - pub_dt).total_seconds() / 3600
            if age_h < 0 or age_h > max_age_h:
                continue
            headline = content.get("title") or n.get("title", "")
            url = ""
            cu = content.get("canonicalUrl")
            if isinstance(cu, dict):
                url = cu.get("url", "") or ""
            url = url or n.get("link", "") or ""
            candidates.append({"headline": headline, "url": url, "age_h": age_h})
        if not candidates:
            return None
        candidates.sort(key=lambda x: x["age_h"])
        return candidates[0]
    except Exception:
        return None


def _move_emoji(pct: float) -> str:
    if pct >= 5: return "🔥"
    if pct >= 2: return "📈"
    if pct <= -5: return "🔻"
    if pct <= -2: return "📉"
    return "➖"


def _build_user_message(snapshots: list) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else (datetime.utcnow() + timedelta(hours=7)).date()
    # sort by abs move desc — ตัวที่วิ่งแรงสุดอยู่บน
    snapshots = sorted(snapshots, key=lambda s: -abs(s.get("move_pct", 0) or 0))

    lines = [
        f"🌅 *Watchlist Recap — {today.strftime('%d %b %Y')}*",
        "_สรุป overnight ตลาด US ของหุ้นที่คุณติดตาม_",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for s in snapshots:
        emoji = _move_emoji(s["move_pct"])
        lines.append(f"{emoji} *{s['symbol']}*  ${s['price']:.2f} ({s['move_pct']:+.2f}%)")
        lines.append(f"   📊 vol {s['vol_ratio']:.1f}x · RSI {s['rsi']:.1f}")
        if s.get("headline"):
            age = s.get("age_h", 0)
            if age < 1:
                age_str = f"{int(age * 60)}m"
            else:
                age_str = f"{age:.0f}h"
            head = (s["headline"] or "")[:90]
            if s.get("news_url"):
                lines.append(f"   📰 [{head}]({s['news_url'][:120]}) · {age_str}")
            else:
                lines.append(f"   📰 {head} · {age_str}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━",
        "_💡 พิมพ์ ticker เพื่อให้ Apexify วิเคราะห์เชิงลึก_",
        "_/watch SYM เพิ่ม · /unwatch SYM ลบ_",
    ])
    return "\n".join(lines)


def _today_key(user_id: str) -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else (datetime.utcnow() + timedelta(hours=7)).date()
    return f"daily_pnl:{today.isoformat()}:{user_id}"


def _user_already_received(user_id: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (_today_key(user_id),))
        return c.fetchone() is not None
    except Exception:
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
            (_today_key(user_id), "daily_pnl", str(user_id)),
        )
        conn.commit()
    except Exception as e:
        print(f"[daily-pnl] mark err {user_id}: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_once(bot, dry_run: bool = False):
    """รัน 1 cycle — DM ทุก VIP/PRO user ที่มี watchlist
    (ขยายจาก PRO only 2026-05-13 — replacing legacy send_watchlist_daily_summary 5:00 ICT)
    """
    try:
        from database import query_paying_users_with_watchlist
    except Exception as e:
        print(f"[daily-pnl] DB import err: {e}", flush=True)
        return

    users = query_paying_users_with_watchlist(roles=('vip', 'pro'), limit=500)
    if not users:
        print("[daily-pnl] no VIP/PRO users with watchlist", flush=True)
        return

    print(f"[daily-pnl] processing {len(users)} PRO users", flush=True)
    sent_count = 0

    for u in users:
        uid = u["user_id"]
        watchlist = u.get("watchlist") or []
        if not watchlist:
            continue
        if _user_already_received(uid) and not dry_run:
            continue

        # cap จำนวน tickers ต่อ user
        tickers = watchlist[:MAX_TICKERS_PER_USER]
        snapshots = []
        for t in tickers:
            snap = _fetch_ticker_snapshot(t)
            if snap:
                snapshots.append(snap)
            time.sleep(0.3)
        if not snapshots:
            continue

        msg = _build_user_message(snapshots)
        if dry_run:
            print(f"==== DRY user={uid} ({len(snapshots)} items) ====")
            print(msg)
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            _mark_user_sent(uid)
            sent_count += 1
            time.sleep(1.0)   # rate-limit Telegram bulk DM
        except Exception as e:
            print(f"[daily-pnl] send err {uid}: {e}", flush=True)
            # fallback no markdown
            try:
                bot.send_message(uid, msg.replace("*", "").replace("_", ""))
                _mark_user_sent(uid)
                sent_count += 1
            except Exception:
                pass

    print(f"[daily-pnl] sent {sent_count}/{len(users)} users", flush=True)


def run_daily_pnl_cron(bot):
    """Daemon thread — daily 08:00 ICT (US market ปิดเวลา 04:00 ICT แล้ว)"""
    if not getattr(config, "DAILY_PNL_ENABLED", True):
        print("[daily-pnl] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "DAILY_PNL_HOUR_ICT", 8)
    target_m = getattr(config, "DAILY_PNL_MINUTE_ICT", 0)
    print(f"[daily-pnl] cron started — daily at {target_h:02d}:{target_m:02d} ICT (PRO users)", flush=True)

    time.sleep(2 * 60)   # warm-up

    while True:
        try:
            now = (datetime.now(timezone.utc) + timedelta(hours=7))
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 45:
                # ใช้ time-based dedup ผ่าน dispatch_log per-user
                run_once(bot)
        except Exception as e:
            print(f"[daily-pnl] loop err: {e}", flush=True)
        time.sleep(30 * 60)   # poll ทุก 30 นาที


if __name__ == "__main__":
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
