"""
plan_proximity_cron.py — เตือน PRO user ก่อนราคาใกล้ SL/TP/Entry zone
                         (เฉพาะหุ้นที่ user ถือจริงในพอร์ต)

User pain: alert_system เตือนตอน SL/TP "ถูกแตะ" แล้ว — สายไป.
User feedback: ห้ามเตือนทุกตัวที่ scan (research) — เฉพาะตัวที่ถือจริงในพอร์ต

Workflow:
  1. Poll ทุก 5 นาที (ใน background thread)
  2. ดึง active plans JOIN portfolios (user ถือจริง shares > 0)
  3. Group by symbol → ลด yfinance call
  4. For each plan:
     - คำนวณ % distance to SL, TP1, TP2, Entry zone
     - ถ้า ≤ threshold → DM user (soft tone, ให้ option ไม่บังคับ)
  5. Dedup: in-memory cooldown 1 ชม. per (plan, level)
"""

import time
import threading
from datetime import datetime, timedelta, timezone

import config


# ============ Config ============
POLL_INTERVAL_SEC = 5 * 60       # poll ทุก 5 นาที
COOLDOWN_SEC = 60 * 60           # 1 ชม. cooldown per (plan, level) — กัน spam

# Thresholds (%)
SL_THRESHOLD_PCT = 1.5           # ใกล้ SL ≤ 1.5%
TP1_THRESHOLD_PCT = 1.0          # ใกล้ TP1 ≤ 1.0%
TP2_THRESHOLD_PCT = 1.0
ENTRY_THRESHOLD_PCT = 1.0        # ใกล้ entry zone ≤ 1% (สำหรับ plan ที่ยังไม่ entry filled)


# ============ State (in-memory, reset on bot restart) ============
_alerted: dict = {}              # f"{plan_id}:{level}" → unix_ts
_price_cache: dict = {}          # symbol → (price, ts)
_PRICE_CACHE_TTL_SEC = 120       # 2 นาที — แต่ละ poll cycle reuse ได้

_thread_lock = threading.Lock()


# ============ Cooldown ============
def _alerted_recently(plan_id: int, level: str) -> bool:
    key = f"{plan_id}:{level}"
    last = _alerted.get(key, 0)
    return (time.time() - last) < COOLDOWN_SEC


def _mark_alerted(plan_id: int, level: str):
    _alerted[f"{plan_id}:{level}"] = time.time()


# ============ Price fetch ============
def _get_current_price(symbol: str) -> float | None:
    """yfinance fast_info — cache 2 นาที ลด API call"""
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and (now - cached[1]) < _PRICE_CACHE_TTL_SEC:
        return cached[0]
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        # fast_info เร็วกว่า .info — ใช้ regular_market_price
        try:
            price = float(t.fast_info.get("last_price") or t.fast_info.get("regular_market_price") or 0)
        except Exception:
            # fallback: ใช้ history(period="1d") last close
            hist = t.history(period="1d", interval="1m")
            if hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
        if price <= 0:
            return None
        _price_cache[symbol] = (price, now)
        return price
    except Exception as e:
        print(f"[proximity] price fetch {symbol} err: {e}", flush=True)
        return None


# ============ Distance calc ============
def _pct_distance(current: float, target: float) -> float:
    """% distance — ใช้ current เป็น base (consistent)"""
    if current <= 0 or target is None:
        return 999.0
    return abs(current - target) / current * 100


def _is_above(current: float, target: float) -> bool:
    return current > target


# ============ Message format ============
# Tone: แจ้งให้รู้ — ไม่บังคับขาย/ซื้อ
# Context: เน้นว่าเป็น Plan ที่ Apexify ออก + user ถือหุ้นใน port
# Decision: ให้ option (ขายตามแผน · ถือยาว · adjust SL · DCA)

_HOLDING_NOTE = (
    "📌 *เหตุผลที่แจ้งเตือน*\n"
    "_หุ้นนี้อยู่ในพอร์ตของคุณ + เคยมี Plan จากการวิเคราะห์ของ Apexify_\n"
    "_ราคาเริ่มเข้าใกล้ระดับสำคัญ — เป็นแนวทางให้คุณพิจารณา_"
)


def _format_sl_warning(plan: dict, current: float, dist_pct: float) -> str:
    sym = plan["symbol"]
    bias = (plan["bias"] or "").upper()
    sl = plan["sl"]
    shares = plan.get("shares") or 0
    avg_cost = plan.get("avg_cost") or 0
    direction_emoji = "📉" if bias.startswith("BULL") else "📈"
    direction_text = "ลง" if bias.startswith("BULL") else "ขึ้น"

    # Position context
    pnl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost else 0
    pnl_str = f"P&L ปัจจุบัน {pnl_pct:+.1f}%" if avg_cost else ""

    return (
        f"⚠️ *{sym} ราคาเริ่มใกล้ SL ของแผน*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 ราคาปัจจุบัน: ${current:.2f}\n"
        f"🛑 SL จากแผน: ${sl:.2f}\n"
        f"{direction_emoji} ห่าง {dist_pct:.2f}% (กำลัง{direction_text})\n"
        + (f"💼 พอร์ตคุณ: {shares:.0f} หุ้น @ ${avg_cost:.2f} · {pnl_str}\n" if avg_cost else "")
        + f"\n{_HOLDING_NOTE}\n\n"
        f"*ตัวเลือกของคุณ:*\n"
        f"✂️ ขายตามแผน → ตัดขาดทุนตาม Plan\n"
        f"💪 ถือยาว → ถ้าเชื่อ thesis ของหุ้น\n"
        f"🔧 Adjust SL → `/setalert {sym} <ราคา>`\n"
        f"📊 พิมพ์ `{sym}` ใหม่ → ขอ analyze update"
    )


def _format_tp_warning(plan: dict, current: float, dist_pct: float, tp_num: int, tp_val: float) -> str:
    sym = plan["symbol"]
    shares = plan.get("shares") or 0
    avg_cost = plan.get("avg_cost") or 0
    pnl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost else 0
    pnl_str = f"P&L ปัจจุบัน {pnl_pct:+.1f}%" if avg_cost else ""

    sizing_hint = "ขาย 33-50% ที่ TP1" if tp_num == 1 else "ขายส่วนที่เหลือ"

    return (
        f"🎯 *{sym} ราคาเริ่มใกล้ TP{tp_num} ของแผน*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 ราคาปัจจุบัน: ${current:.2f}\n"
        f"💰 TP{tp_num} จากแผน: ${tp_val:.2f}\n"
        f"📈 ห่าง {dist_pct:.2f}%\n"
        + (f"💼 พอร์ตคุณ: {shares:.0f} หุ้น @ ${avg_cost:.2f} · {pnl_str}\n" if avg_cost else "")
        + f"\n{_HOLDING_NOTE}\n\n"
        f"*ตัวเลือกของคุณ:*\n"
        f"🎯 ขายตามแผน → Apexify แนะนำ {sizing_hint}\n"
        f"💪 ถือยาว → ถ้า thesis ยังไม่จบ (long-term hold)\n"
        f"⚖️ ขายบางส่วน + ถือบางส่วน → balanced approach\n"
        f"📊 พิมพ์ `{sym}` ใหม่ → ขอ analyze update"
    )


def _format_entry_warning(plan: dict, current: float, dist_pct: float) -> str:
    sym = plan["symbol"]
    e_low = plan["entry_low"]
    e_high = plan["entry_high"]
    shares = plan.get("shares") or 0
    avg_cost = plan.get("avg_cost") or 0

    return (
        f"🎯 *{sym} ราคาวกกลับมา Entry zone ของแผน*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 ราคาปัจจุบัน: ${current:.2f}\n"
        f"🎯 Entry zone จากแผน: ${e_low:.2f} - ${e_high:.2f}\n"
        f"📈 ห่าง {dist_pct:.2f}%\n"
        + (f"💼 พอร์ตคุณ: {shares:.0f} หุ้น @ ${avg_cost:.2f}\n" if avg_cost else "")
        + f"\n{_HOLDING_NOTE}\n\n"
        f"*ตัวเลือกของคุณ:*\n"
        f"➕ DCA เพิ่ม → ราคากลับมา zone ที่ Apexify แนะนำเข้า\n"
        f"💪 ถือไว้เฉยๆ → ไม่เพิ่ม\n"
        f"📊 พิมพ์ `{sym}` ใหม่ → ขอ analyze update"
    )


# ============ Core check ============
def check_plan(bot, plan: dict, current: float, dry_run: bool = False) -> int:
    """เช็ค plan 1 อัน — DM ถ้าใกล้ level. Returns alerts sent."""
    sent = 0
    user_id = plan["user_id"]
    plan_id = plan["id"]
    bias = (plan["bias"] or "").upper()

    # SL — ทิศใกล้ SL = ราคาเข้าใกล้ SL value (ทั้ง bull/bear)
    sl = plan.get("sl")
    if sl:
        dist_sl = _pct_distance(current, sl)
        if dist_sl <= SL_THRESHOLD_PCT and not _alerted_recently(plan_id, "sl"):
            # Sanity: bull plan → SL = ต่ำกว่า entry. ถ้า current ลงใกล้ = warn
            #         bear plan → SL = สูงกว่า entry. ถ้า current ขึ้นใกล้ = warn
            valid = False
            if bias.startswith("BULL") and current >= sl:   # ยังไม่ทะลุ SL
                valid = True
            elif bias.startswith("BEAR") and current <= sl:
                valid = True
            elif not bias.startswith(("BULL", "BEAR")):
                valid = True   # unknown bias → warn anyway
            if valid:
                msg = _format_sl_warning(plan, current, dist_sl)
                if dry_run:
                    print(f"==== DRY SL plan={plan_id} user={user_id} ====")
                    print(msg)
                else:
                    try:
                        bot.send_message(user_id, msg, parse_mode="Markdown")
                        _mark_alerted(plan_id, "sl")
                        sent += 1
                    except Exception as e:
                        print(f"[proximity] SL DM err uid={user_id} plan={plan_id}: {e}", flush=True)

    # TP1
    tp1 = plan.get("tp1")
    if tp1:
        dist_tp1 = _pct_distance(current, tp1)
        if dist_tp1 <= TP1_THRESHOLD_PCT and not _alerted_recently(plan_id, "tp1"):
            valid = False
            if bias.startswith("BULL") and current <= tp1:
                valid = True
            elif bias.startswith("BEAR") and current >= tp1:
                valid = True
            elif not bias.startswith(("BULL", "BEAR")):
                valid = True
            if valid:
                msg = _format_tp_warning(plan, current, dist_tp1, 1, tp1)
                if dry_run:
                    print(f"==== DRY TP1 plan={plan_id} user={user_id} ====")
                    print(msg)
                else:
                    try:
                        bot.send_message(user_id, msg, parse_mode="Markdown")
                        _mark_alerted(plan_id, "tp1")
                        sent += 1
                    except Exception as e:
                        print(f"[proximity] TP1 DM err: {e}", flush=True)

    # TP2
    tp2 = plan.get("tp2")
    if tp2:
        dist_tp2 = _pct_distance(current, tp2)
        if dist_tp2 <= TP2_THRESHOLD_PCT and not _alerted_recently(plan_id, "tp2"):
            valid = False
            if bias.startswith("BULL") and current <= tp2:
                valid = True
            elif bias.startswith("BEAR") and current >= tp2:
                valid = True
            elif not bias.startswith(("BULL", "BEAR")):
                valid = True
            if valid:
                msg = _format_tp_warning(plan, current, dist_tp2, 2, tp2)
                if dry_run:
                    print(f"==== DRY TP2 plan={plan_id} user={user_id} ====")
                    print(msg)
                else:
                    try:
                        bot.send_message(user_id, msg, parse_mode="Markdown")
                        _mark_alerted(plan_id, "tp2")
                        sent += 1
                    except Exception as e:
                        print(f"[proximity] TP2 DM err: {e}", flush=True)

    # Entry zone (สำหรับ plan ที่อาจยังไม่ entry — pre-trade)
    e_low = plan.get("entry_low")
    e_high = plan.get("entry_high")
    if e_low and e_high:
        # ราคาอยู่ใกล้ entry zone (เหนือ/ใต้ ขอบของ zone)
        # ใช้ middle point ของ entry zone เป็น reference
        e_mid = (e_low + e_high) / 2
        dist_entry = _pct_distance(current, e_mid)
        # ใกล้ entry แต่ยังไม่อยู่ใน zone
        already_in_zone = e_low <= current <= e_high
        if (not already_in_zone) and dist_entry <= ENTRY_THRESHOLD_PCT and not _alerted_recently(plan_id, "entry"):
            msg = _format_entry_warning(plan, current, dist_entry)
            if dry_run:
                print(f"==== DRY ENTRY plan={plan_id} user={user_id} ====")
                print(msg)
            else:
                try:
                    bot.send_message(user_id, msg, parse_mode="Markdown")
                    _mark_alerted(plan_id, "entry")
                    sent += 1
                except Exception as e:
                    print(f"[proximity] Entry DM err: {e}", flush=True)

    return sent


def run_once(bot, dry_run: bool = False) -> dict:
    """1 cycle: query plans + check proximity + DM"""
    stats = {"plans": 0, "symbols": 0, "alerts_sent": 0}
    try:
        from database import get_active_plans_in_portfolio
        plans = get_active_plans_in_portfolio(max_age_days=45)
    except Exception as e:
        print(f"[proximity] DB err: {e}", flush=True)
        return stats

    stats["plans"] = len(plans)
    if not plans:
        return stats

    # Group by symbol
    by_symbol = {}
    for p in plans:
        by_symbol.setdefault(p["symbol"], []).append(p)
    stats["symbols"] = len(by_symbol)

    for symbol, group in by_symbol.items():
        current = _get_current_price(symbol)
        if current is None:
            continue
        for plan in group:
            stats["alerts_sent"] += check_plan(bot, plan, current, dry_run=dry_run)
        time.sleep(0.2)   # rate-limit yfinance

    return stats


def run_proximity_cron(bot):
    """Daemon thread — poll ทุก 5 นาที"""
    if not getattr(config, "PROXIMITY_ENABLED", True):
        print("[proximity] disabled — thread exiting", flush=True)
        return

    print(f"[proximity] cron started — poll every {POLL_INTERVAL_SEC//60}min "
          f"(SL ±{SL_THRESHOLD_PCT}% · TP1/TP2 ±{TP1_THRESHOLD_PCT}% · Entry ±{ENTRY_THRESHOLD_PCT}%)", flush=True)

    time.sleep(3 * 60)   # warm-up

    while True:
        try:
            with _thread_lock:
                stats = run_once(bot)
            if stats["alerts_sent"] > 0:
                print(f"[proximity] cycle: {stats['plans']} plans / {stats['symbols']} symbols / {stats['alerts_sent']} alerts", flush=True)
        except Exception as e:
            print(f"[proximity] loop err: {e}", flush=True)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    stats = run_once(bot, dry_run=True)
    print(f"\n=== Result: {stats} ===")
