"""
auto_dm_cron.py — Daily 11:00 ICT cron — Activation + Win-back DMs อัตโนมัติ

Replaces manual `activation_send.py` + `winback_send.py` workflow.
รันใน daemon thread พร้อม bot (เริ่มที่ main.py)

Workflow:
  1. Check time === AUTO_DM_HOUR_ICT (default 11:00 ICT)
  2. กัน trigger ซ้ำใน 1 วัน (check dispatch_log)
  3. Scan activation candidates (signed_up >24h, no /freetrial, no analyses)
  4. Scan winback candidates (vip/pro expired in last 1 day)
  5. Send DM พร้อม mark dispatch_log
  6. Notify ADMIN_ID สรุปผล

Safety:
  - Cooldown 30 วัน/user/category (dispatch_log dedup)
  - Rate limit 1.5s/DM
  - Daily limit cap (config.AUTO_DM_DAILY_LIMIT)
  - DRY_RUN mode → log only ไม่ส่ง

Templates: port มาจาก activation_send.py + winback_send.py
"""

import time
import threading
from datetime import datetime, timedelta

import config
import database
import bot_utils


# ============ Templates ============

def template_activation_never_used(name):
    greet = f"สวัสดีคุณ {name} ครับ" if name and name != "Unknown" else "สวัสดีครับ"
    return (
        f"{greet} 🙏\n\n"
        "เห็นว่าคุณสมัคร Apexify ไปแล้วแต่ยังไม่ได้ลองเลย\n"
        "อยากชวนทดลองดูสักครั้ง — ใช้ฟรี ไม่ต้องผูกบัตร\n\n"
        "📲 ลองง่ายๆ — พิมพ์ชื่อหุ้นที่อยากดู เช่น:\n"
        "   • AAPL\n"
        "   • NVDA\n"
        "   • PTT.BK\n"
        "   • TSLA\n\n"
        "บอทจะตอบรายงานวิเคราะห์ใน 5-10 วินาที — Trend, RSI, แนวรับ-ต้าน, Confidence Score\n\n"
        "🎁 หรือพิมพ์ /freetrial เพื่อทดลอง PRO ฟรี 7 วัน (ใช้ได้ครั้งเดียวต่อบัญชี)\n\n"
        "ถ้ามีคำถามอะไร ตอบกลับมาในแชทนี้เลยครับ\n"
        "— Apexify"
    )


def template_activation_started(name):
    greet = f"สวัสดีคุณ {name} ครับ" if name and name != "Unknown" else "สวัสดีครับ"
    return (
        f"{greet} 🙏\n\n"
        "ขอบคุณที่ลอง Apexify ครับ — เห็นว่ายังไม่ได้กด /freetrial\n\n"
        "🎁 ทดลอง PRO ฟรี 7 วัน — พิมพ์ /freetrial ในแชทนี้\n"
        "   • วิเคราะห์ไม่จำกัด (จากที่ฟรี 3 ครั้ง/วัน)\n"
        "   • Smart Alerts + Briefing เช้า\n"
        "   • Trade Plan สำเร็จรูป (Entry/TP/SL)\n\n"
        "ใช้ครั้งเดียวต่อบัญชี — ลองดูแล้วค่อยตัดสินใจสมัครต่อ\n"
        "ถ้ามี feedback อะไร บอกได้เลยครับ\n"
        "— Apexify"
    )


def template_winback_tier1(name, count, days):
    greet = f"สวัสดีคุณ {name} ครับ" if name and name not in (None, "Unknown", "เพื่อน") else "สวัสดีเพื่อน"
    return (
        f"{greet} 🙏\n\n"
        f"ขอบคุณที่เคยใช้ Apexify มา {count} ครั้ง — "
        f"ผมเห็นว่า PRO หมดอายุไปเมื่อ {days} วันที่ผ่านมา\n\n"
        "อยากชวนกลับมาลองอีกที — ผมส่งโค้ดส่วนลด 30% ให้ครับ\n"
        "🎟 พิมพ์ /redeem WINBACK30 ในแชทบอท\n"
        "💎 PRO เดือนแรก = 76 บาท (ปกติ 109)\n"
        "⏰ ใช้ได้ใน 7 วัน\n\n"
        "ถ้ามี feedback ว่าเดือนก่อนไม่ตรงใจตรงไหน บอกได้ครับ จะปรับปรุงต่อ 🙏\n\n"
        "— Apexify"
    )


def template_winback_tier2(name, days):
    greet = f"สวัสดีคุณ {name} ครับ" if name and name != "Unknown" else "สวัสดีครับ"
    return (
        f"{greet}\n\n"
        f"PRO ของคุณเพิ่งหมดอายุเมื่อ {days} วัน — "
        "ก่อนปิดเรื่องอยากถามนิดเดียว\n"
        "ที่ผ่านมาบอทตอบโจทย์มั้ยครับ? อะไรที่ใช้แล้วชอบ/ไม่ชอบ?\n\n"
        "ถ้าอยากลองอีกที ส่งโค้ด WINBACK30 ให้ครับ — ลด 30% (PRO 76 บาท)\n"
        "พิมพ์ /redeem WINBACK30 ในแชทใน 7 วัน\n\n"
        "ขอบคุณ feedback ทุกคำครับ\n"
        "— Apexify"
    )


# ============ Send helpers ============

def _send_dm(bot, user_id, text):
    """ส่งผ่าน bot ที่ส่งมา (telebot.TeleBot). Return (ok, error_msg)"""
    try:
        bot_utils.safe_send_with_retry(bot, user_id, text, retries=2, parse_mode=None)
        return True, None
    except Exception as e:
        return False, str(e)


# ============ Cron main ============

def _today_dispatch_key(category):
    """1 trigger ต่อ category ต่อวัน — กัน multi-thread race ที่จะส่ง 2 รอบ"""
    today = config.thai_today() if hasattr(config, "thai_today") else datetime.utcnow().date()
    return f"auto_dm_cron:{category}:{today.isoformat()}"


def _trigger_marked_today(category):
    """เช็คใน dispatch_log ว่าวันนี้ trigger category นี้แล้วหรือยัง"""
    key = _today_dispatch_key(category)
    try:
        conn = database.get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (key,))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[auto_dm] trigger check err: {e}", flush=True)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_trigger_today(category):
    key = _today_dispatch_key(category)
    try:
        conn = database.get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (key, "auto_dm_trigger", category),
        )
        conn.commit()
    except Exception as e:
        print(f"[auto_dm] mark trigger err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_user_dispatched(user_id, category):
    """Mark per-user per-category dispatch — สำหรับ cooldown 30 วัน"""
    key = f"auto_dm:{category}:{user_id}"
    try:
        conn = database.get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (key, f"auto_dm_{category}", str(user_id)),
        )
        conn.commit()
    except Exception as e:
        print(f"[auto_dm] mark user err {user_id}: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _send_activation_batch(bot, candidates, dry_run, daily_limit):
    sent_ok = 0
    sent_fail = 0
    skipped = 0
    for cand in candidates[:daily_limit]:
        uid = cand["user_id"]
        name = cand.get("username") or ""
        started = (cand.get("total_analyses") or 0) > 0
        msg = template_activation_started(name) if started else template_activation_never_used(name)

        if dry_run:
            print(f"[auto_dm/DRY] activation → {uid} ({name}) len={len(msg)}", flush=True)
            sent_ok += 1
            continue

        ok, err = _send_dm(bot, uid, msg)
        if ok:
            _mark_user_dispatched(uid, "activation")
            sent_ok += 1
            print(f"[auto_dm] ✅ activation → {uid} ({name})", flush=True)
        else:
            sent_fail += 1
            print(f"[auto_dm] ❌ activation → {uid} ({name}): {err}", flush=True)
        time.sleep(1.5)
    return sent_ok, sent_fail, skipped


def _send_winback_batch(bot, candidates, dry_run, daily_limit):
    sent_ok = 0
    sent_fail = 0
    for cand in candidates[:daily_limit]:
        uid = cand["user_id"]
        name = cand.get("username") or ""
        count = cand.get("total_analyses") or 0
        days = cand.get("days_lapsed") or 1
        tier = 1 if count >= 7 else 2
        msg = template_winback_tier1(name, count, days) if tier == 1 else template_winback_tier2(name, days)

        if dry_run:
            print(f"[auto_dm/DRY] winback tier{tier} → {uid} ({name}) used={count} lapsed={days}d len={len(msg)}", flush=True)
            sent_ok += 1
            continue

        ok, err = _send_dm(bot, uid, msg)
        if ok:
            _mark_user_dispatched(uid, "winback")
            sent_ok += 1
            print(f"[auto_dm] ✅ winback tier{tier} → {uid} ({name})", flush=True)
        else:
            sent_fail += 1
            print(f"[auto_dm] ❌ winback → {uid} ({name}): {err}", flush=True)
        time.sleep(1.5)
    return sent_ok, sent_fail, 0


def run_once(bot, dry_run=None):
    """รัน 1 cycle ทันที — สำหรับ manual trigger / testing"""
    dry_run = config.AUTO_DM_DRY_RUN if dry_run is None else dry_run
    cooldown_days = config.AUTO_DM_REPEAT_COOLDOWN_DAYS
    daily_limit = config.AUTO_DM_DAILY_LIMIT

    print(f"\n[auto_dm] === run_once dry={dry_run} cooldown={cooldown_days}d limit={daily_limit} ===", flush=True)

    activation = database.query_activation_candidates(cooldown_days=cooldown_days)
    winback = database.query_winback_candidates(cooldown_days=cooldown_days)
    print(f"[auto_dm] candidates: activation={len(activation)} winback={len(winback)}", flush=True)

    act_ok, act_fail, _ = _send_activation_batch(bot, activation, dry_run, daily_limit)
    wb_ok, wb_fail, _ = _send_winback_batch(bot, winback, dry_run, daily_limit)

    summary = (
        f"📬 Auto-DM Cron ({datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')})\n"
        f"━━━━━━━━━━━━━━\n"
        f"Activation: ✅ {act_ok}  ❌ {act_fail}\n"
        f"Win-back:   ✅ {wb_ok}  ❌ {wb_fail}\n"
        f"Mode: {'🧪 DRY_RUN' if dry_run else '🚀 LIVE'}"
    )
    print(summary, flush=True)

    if not dry_run and config.ADMIN_ID:
        try:
            bot.send_message(config.ADMIN_ID, summary)
        except Exception as e:
            print(f"[auto_dm] admin notify err: {e}", flush=True)

    return {"activation_ok": act_ok, "activation_fail": act_fail, "winback_ok": wb_ok, "winback_fail": wb_fail}


def run_auto_dm_cron(bot):
    """Daemon loop — check time + trigger 11:00 ICT ทุกวัน"""
    if not config.AUTO_DM_ENABLED:
        print("[auto_dm] disabled via config — thread exiting", flush=True)
        return

    print(f"[auto_dm] cron loop started — daily at {config.AUTO_DM_HOUR_ICT:02d}:00 ICT", flush=True)
    # initial delay 30 นาที กัน race กับ init_db
    time.sleep(30 * 60)

    while True:
        try:
            now = config.thai_now() if hasattr(config, "thai_now") else (datetime.utcnow() + timedelta(hours=7))
            target_hour = config.AUTO_DM_HOUR_ICT
            if now.hour == target_hour:
                if _trigger_marked_today("daily"):
                    pass  # already ran today
                else:
                    _mark_trigger_today("daily")
                    run_once(bot)
        except Exception as e:
            print(f"[auto_dm] cron loop err: {e}", flush=True)
        # poll ทุก ~50 นาที — เจอ hour จะ trigger ได้ภายใน 1 hour window
        time.sleep(50 * 60)


if __name__ == "__main__":
    # smoke test (DRY_RUN เสมอ)
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
