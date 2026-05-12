"""
smart_money_cron.py — DM admin (และ PRO watchlist) ทุกวัน 16:00 ICT
                      ดูหุ้นที่ผู้บริหารใหญ่ (CEO/CFO/Director) ซื้อเข้าตัวเองสัปดาห์นี้

Source: OpenInsider.com — latest-cluster-buys page (pre-grouped cluster signals)
       100 rows ทุก row = P - Purchase, มีหลาย insider, ใหม่สุดบนสุด

User value:
  - admin: ทำ FB content "หุ้นที่ CEO ซื้อสัปดาห์นี้" — viral content
  - PRO: alert เฉพาะ ticker ที่อยู่ใน watchlist (premium signal)

Reliability:
  - SEC บังคับ insider file Form 4 ภายใน T+2 วันทำการ (กฎหมาย)
  - OpenInsider scrape Form 4 → publish ภายในนาที
  - delay total จาก trade → DM: ~T+2 วันสูงสุด

Workflow:
  1. Daily cron 16:00 ICT (US filing window ปิดประมาณ 04:00 ICT — เผื่อ buffer)
  2. Scrape OpenInsider latest-cluster-buys (100 rows)
  3. Filter: value ≥ $500K · price ≥ $5 · skip OTC industries
  4. Format top 8 → DM admin
  5. Match PRO watchlist → DM premium signal
  6. dispatch_log dedup (1 ครั้ง/วัน)
"""

import re
import time
from datetime import datetime, timedelta, timezone

import config


# ============ Sources ============
_OI_URL = "http://openinsider.com/latest-cluster-buys"
_OI_TIMEOUT_SEC = 20
_USER_AGENT = "Apexify Trading Bot (apexify@example.com)"


# ============ Filters ============
MIN_VALUE_USD = 500_000        # ตัด small buys (<$500K)
MIN_PRICE_USD = 5.0            # ตัด penny stock
MAX_TRADE_AGE_DAYS = 14        # 🆕 เฉพาะ trade ≤ 14 วันที่ผ่านมา (กัน signal เก่าหลายเดือน)
TOP_N_ADMIN = 8                # admin DM แสดง top N

# Industries ที่ส่วนใหญ่เป็น OTC/penny → ตัดออก
_SKIP_INDUSTRIES = {
    "blank checks",
    "petroleum & petroleum products",   # บางตัวเป็น shell
}


# ============ HTTP fetch ============
def _http_get(url: str, timeout: int = _OI_TIMEOUT_SEC):
    """ใช้ curl_cffi ถ้ามี (anti-bot) — fallback เป็น requests"""
    try:
        from curl_cffi import requests as cffi_requests
        return cffi_requests.get(url, impersonate="chrome110", timeout=timeout)
    except Exception:
        import requests
        return requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)


# ============ Parser helpers ============
def _clean(s: str) -> str:
    """Normalize whitespace (HTML &nbsp; → space)"""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()


def _parse_money(s: str) -> int:
    """ '+$11,024,985' / '-$1,704,537' → int (positive USD)"""
    if not s:
        return 0
    cleaned = s.replace("$", "").replace(",", "").replace("+", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def _parse_price(s: str) -> float:
    """'$15.00' → 15.0"""
    if not s:
        return 0.0
    try:
        return float(s.replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_qty(s: str) -> int:
    """'+734,999' → 734999"""
    if not s:
        return 0
    try:
        return int(s.replace(",", "").replace("+", "").strip())
    except (ValueError, TypeError):
        return 0


def _parse_ins_count(s: str) -> int:
    """'5' → 5 (จำนวน insiders ใน cluster)"""
    try:
        return int(_clean(s))
    except (ValueError, TypeError):
        return 0


def _parse_trade_date(date_str: str):
    """'2026-05-11' → datetime.date หรือ None"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_fresh_trade(item: dict, max_days: int = MAX_TRADE_AGE_DAYS) -> bool:
    """เช็คว่า trade_date ใหม่พอ (≤ max_days)"""
    d = _parse_trade_date(item.get("trade_date", ""))
    if d is None:
        return False
    today = config.thai_today() if hasattr(config, "thai_today") else (datetime.utcnow() + timedelta(hours=7)).date()
    age = (today - d).days
    return 0 <= age <= max_days


# ============ Scraper ============
def scrape_cluster_buys() -> list[dict]:
    """Scrape OpenInsider latest-cluster-buys table.

    Returns: list of dict {
        ticker, company, industry, ins_count, trade_date, trade_type,
        price, qty, value_usd, perf_1d, perf_1w, perf_1m, perf_6m
    }
    """
    try:
        resp = _http_get(_OI_URL)
        if resp.status_code != 200:
            print(f"[smart-money] OI fetch HTTP {resp.status_code}", flush=True)
            return []
    except Exception as e:
        print(f"[smart-money] OI fetch err: {e}", flush=True)
        return []

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[smart-money] BS4 parse err: {e}", flush=True)
        return []

    table = soup.find("table", class_="tinytable")
    if not table:
        print("[smart-money] no tinytable found — site layout changed?", flush=True)
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    items = []
    for row in tbody.find_all("tr"):
        cells = [_clean(td.get_text()) for td in row.find_all("td")]
        if len(cells) < 13:
            continue   # skip malformed
        try:
            items.append({
                "ticker": cells[3],
                "company": cells[4],
                "industry": cells[5],
                "ins_count": _parse_ins_count(cells[6]),
                "trade_date": cells[2],          # YYYY-MM-DD
                "trade_type": cells[7],
                "price": _parse_price(cells[8]),
                "qty": _parse_qty(cells[9]),
                "value_usd": _parse_money(cells[12]),
                "perf_1d": cells[13] if len(cells) > 13 else "",
                "perf_1w": cells[14] if len(cells) > 14 else "",
                "perf_1m": cells[15] if len(cells) > 15 else "",
                "perf_6m": cells[16] if len(cells) > 16 else "",
            })
        except Exception as e:
            print(f"[smart-money] row parse err: {e}", flush=True)
            continue

    return items


# ============ Filter ============
def filter_quality(items: list[dict]) -> list[dict]:
    """Apply quality filters"""
    out = []
    for it in items:
        # ตัด non-purchase (sanity check — cluster page ควรเป็น P เกือบทั้งหมด)
        if not it["trade_type"].lower().startswith("p"):
            continue
        if it["value_usd"] < MIN_VALUE_USD:
            continue
        if it["price"] < MIN_PRICE_USD:
            continue
        if it["industry"].lower() in _SKIP_INDUSTRIES:
            continue
        if not it["ticker"]:
            continue
        # 🆕 fresh trade filter — เฉพาะ ≤ 14 วันที่ผ่านมา
        if not _is_fresh_trade(it):
            continue
        out.append(it)
    return out


def classify_signal(item: dict) -> str:
    """Tag signal strength"""
    val = item["value_usd"]
    ins = item["ins_count"]
    if val >= 5_000_000:
        return "🐳 Mega Buy"
    if ins >= 4:
        return "🔥 Cluster x4+"
    if ins >= 3:
        return "📈 Cluster x3"
    if val >= 2_000_000:
        return "💎 Big Buy"
    return "📊 Notable"


# ============ Format ============
def _fmt_usd(v: int) -> str:
    """1500000 → '$1.5M' · 750000 → '$750K'"""
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v}"


def format_admin_message(items: list[dict], top_n: int = TOP_N_ADMIN) -> str:
    """Build admin DM Markdown"""
    today = config.thai_today() if hasattr(config, "thai_today") else (datetime.utcnow() + timedelta(hours=7)).date()
    # sort by value desc
    items = sorted(items, key=lambda x: -x["value_usd"])[:top_n]

    lines = [
        f"🐳 *Smart Money Today — {today.strftime('%d %b %Y')}*",
        "_หุ้นที่ผู้บริหาร (CEO/CFO/Director) ซื้อเข้าตัวเอง_",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for i, it in enumerate(items, 1):
        signal = classify_signal(it)
        lines.append(f"{i}. *{it['ticker']}* — {signal}")
        lines.append(
            f"   👥 {it['ins_count']} insiders · "
            f"💵 {_fmt_usd(it['value_usd'])} @ ${it['price']:.2f}"
        )
        if it["industry"]:
            lines.append(f"   🏢 {it['industry'][:60]}")
        lines.append(f"   📅 trade {it['trade_date']}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━",
        "_ข้อมูล: SEC Form 4 (กฎหมายบังคับ insider file ภายใน T+2 วัน)_",
        "_ที่มา: openinsider.com · sec.gov_",
        "_💡 เอา hook ไปต่อยอด ChatGPT/Gemini สำหรับ FB content_",
    ])
    return "\n".join(lines)


def format_pro_message(matched: list[dict]) -> str:
    """DM PRO user — เฉพาะ ticker ที่ตัวเองมีใน watchlist"""
    lines = [
        "🐳 *Smart Money Alert — Watchlist ของคุณ*",
        "_ผู้บริหารใหญ่กำลังซื้อหุ้นที่คุณ track อยู่_",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for it in sorted(matched, key=lambda x: -x["value_usd"]):
        signal = classify_signal(it)
        lines.append(f"📈 *{it['ticker']}* — {signal}")
        lines.append(
            f"   {it['ins_count']} insiders ซื้อรวม {_fmt_usd(it['value_usd'])} "
            f"(@ ${it['price']:.2f})"
        )
        lines.append(f"   📅 {it['trade_date']}")
        lines.append("")
    lines.extend([
        "━━━━━━━━━━━━━━",
        "_💡 พิมพ์ ticker ใน bot เพื่อวิเคราะห์เชิงลึก_",
    ])
    return "\n".join(lines)


# ============ Dedup ============
# 2 layer:
#   - Daily-rerun guard: smart_money:YYYY-MM-DD (block manual rerun cron in same day)
#   - Per-signal dedup: smart_money_admin:{ticker}:{trade_date}
#                       smart_money_pro:{ticker}:{trade_date}:{user_id}
#     (ใช้ทั้ง 2 ฝั่งเพื่อกัน DM cluster เดียวกัน 2 ครั้ง สับสน user)

def _today_key() -> str:
    today = config.thai_today() if hasattr(config, "thai_today") else (datetime.utcnow() + timedelta(hours=7)).date()
    return f"smart_money:{today.isoformat()}"


def _already_ran_today() -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (_today_key(),))
        return c.fetchone() is not None
    except Exception:
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
            (_today_key(), "smart_money", "admin"),
        )
        conn.commit()
    except Exception as e:
        print(f"[smart-money] mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---- Per-signal dedup ----

def _admin_sig_key(ticker: str, trade_date: str) -> str:
    return f"smart_money_admin:{ticker}:{trade_date}"


def _pro_sig_key(user_id: str, ticker: str, trade_date: str) -> str:
    return f"smart_money_pro:{ticker}:{trade_date}:{user_id}"


def _signal_already_sent(key: str) -> bool:
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (key,))
        return c.fetchone() is not None
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_signal_sent(key: str, category: str, raw_key: str):
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
        print(f"[smart-money] mark sig err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _filter_new_for_admin(items: list[dict]) -> list[dict]:
    """กรอง items ที่ admin ยังไม่เคยได้รับ DM (per ticker × trade_date)"""
    return [it for it in items if not _signal_already_sent(_admin_sig_key(it["ticker"], it["trade_date"]))]


def _filter_new_for_user(items: list[dict], user_id: str) -> list[dict]:
    """กรอง items ที่ user คนนี้ยังไม่เคยได้รับ DM"""
    return [it for it in items if not _signal_already_sent(_pro_sig_key(user_id, it["ticker"], it["trade_date"]))]


# ============ Send ============
def _send_admin(bot, items_admin: list[dict], dry_run: bool = False):
    """DM admin top 8 — กรอง signals ที่เคยส่งให้ admin แล้ว"""
    if not config.ADMIN_ID:
        print("[smart-money] no ADMIN_ID — skip", flush=True)
        return

    # กรอง signal ใหม่ที่ admin ยังไม่ได้รับ
    fresh = _filter_new_for_admin(items_admin)
    if not fresh:
        print("[smart-money] no new signals for admin (all duplicates) — skip admin DM", flush=True)
        return

    # sort + top N
    top = sorted(fresh, key=lambda x: -x["value_usd"])[:TOP_N_ADMIN]
    msg = format_admin_message(top, top_n=TOP_N_ADMIN)

    if dry_run:
        print(f"==== DRY ADMIN ({len(top)} new signals out of {len(fresh)} total fresh) ====")
        print(msg)
        return

    try:
        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        # mark sent — เฉพาะ items ใน top N ที่ส่งจริง
        for it in top:
            _mark_signal_sent(_admin_sig_key(it["ticker"], it["trade_date"]),
                              "smart_money_admin", it["ticker"])
    except Exception as e:
        print(f"[smart-money] admin DM err: {e}", flush=True)
        # fallback no markdown
        try:
            bot.send_message(config.ADMIN_ID, msg.replace("*", "").replace("_", ""))
            for it in top:
                _mark_signal_sent(_admin_sig_key(it["ticker"], it["trade_date"]),
                                  "smart_money_admin", it["ticker"])
        except Exception:
            pass


def _send_pro_watchlists(bot, items: list[dict], dry_run: bool = False) -> int:
    """DM ทุก PRO user ที่ watchlist ติด ticker ใน items — กรอง signal ที่ user เคยรับแล้ว"""
    try:
        from database import query_pro_users_with_watchlist
    except Exception as e:
        print(f"[smart-money] DB import err: {e}", flush=True)
        return 0

    pool_tickers = {it["ticker"] for it in items}
    if not pool_tickers:
        return 0

    pro_users = query_pro_users_with_watchlist(limit=500)
    sent_count = 0

    for u in pro_users:
        uid = u["user_id"]
        watchlist = {t.upper() for t in (u.get("watchlist") or [])}
        matched = [it for it in items if it["ticker"].upper() in watchlist]
        if not matched:
            continue

        # กรอง signal ที่ user คนนี้เคยรับแล้ว
        fresh_for_user = _filter_new_for_user(matched, uid)
        if not fresh_for_user:
            continue   # user เคยได้ทั้งหมดแล้ว skip

        msg = format_pro_message(fresh_for_user)
        if dry_run:
            print(f"==== DRY PRO user={uid} ({len(fresh_for_user)} new of {len(matched)} matched) ====")
            print(msg)
            continue

        try:
            bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            sent_count += 1
            # mark sent — items ที่ส่งจริง
            for it in fresh_for_user:
                _mark_signal_sent(_pro_sig_key(uid, it["ticker"], it["trade_date"]),
                                  "smart_money_pro", uid)
            time.sleep(0.8)   # rate-limit Telegram
        except Exception as e:
            print(f"[smart-money] PRO DM err {uid}: {e}", flush=True)

    return sent_count


# ============ Entry points ============
def run_once(bot, dry_run: bool = False):
    """1 cycle — scrape + filter + DM"""
    print("[smart-money] starting scan...", flush=True)
    items = scrape_cluster_buys()
    print(f"[smart-money] fetched {len(items)} cluster rows", flush=True)
    if not items:
        if not dry_run:
            try:
                bot.send_message(config.ADMIN_ID, "⚠️ Smart Money: OpenInsider ดึงข้อมูลไม่ได้วันนี้")
            except Exception:
                pass
        return

    filtered = filter_quality(items)
    print(f"[smart-money] after filter: {len(filtered)} (min ${MIN_VALUE_USD/1000:.0f}K · price ≥ ${MIN_PRICE_USD})", flush=True)
    if not filtered:
        if not dry_run:
            try:
                bot.send_message(config.ADMIN_ID, "🐳 Smart Money: ไม่มี cluster buys เข้าเกณฑ์วันนี้")
            except Exception:
                pass
        return

    # Admin DM — _send_admin จะ filter เฉพาะ signal ที่ admin ยังไม่เคยได้
    _send_admin(bot, filtered, dry_run=dry_run)

    # PRO matched — _send_pro filter per-user signal dedup ในตัว
    pro_sent = _send_pro_watchlists(bot, filtered, dry_run=dry_run)
    print(f"[smart-money] sent to {pro_sent} PRO users", flush=True)


def run_smart_money_cron(bot):
    """Daemon thread — daily 16:00 ICT"""
    if not getattr(config, "SMART_MONEY_ENABLED", True):
        print("[smart-money] disabled — thread exiting", flush=True)
        return

    target_h = getattr(config, "SMART_MONEY_HOUR_ICT", 16)
    target_m = getattr(config, "SMART_MONEY_MINUTE_ICT", 0)
    print(f"[smart-money] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(2 * 60)   # warm-up

    while True:
        try:
            now = (datetime.now(timezone.utc) + timedelta(hours=7))
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                if not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[smart-money] loop err: {e}", flush=True)
        time.sleep(20 * 60)   # poll ทุก 20 นาที


if __name__ == "__main__":
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
