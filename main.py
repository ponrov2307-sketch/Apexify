import sys
sys.stdout.reconfigure(line_buffering=True)
from pnl_generator import generate_pnl_card
import telebot
import logging
import yfinance as yf
import random
import string
import time
import threading
import xml.etree.ElementTree as ET 
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from keep_alive import keep_alive, set_webhook_bot
from config import TELEGRAM_TOKEN, ADMIN_ID, DASHBOARD_LOGIN_TOKEN_TTL, APEXIFY_PASSWORD, gemini_client, BOT_WEB_BASE_URL
from dashboard_login import (
    issue_admin_dashboard_url, issue_dashboard_login_url,
    build_dashboard_login_url, is_dashboard_login_ready,
)
# 🌟 Import ฟังก์ชันฐานข้อมูลทั้งหมด รวมถึงระบบจัดการพอร์ต
from database import (get_all_users, init_db, register_user, check_subscription, add_subscription,
                      get_usage, increment_usage, add_watch, get_user_watch, get_user_profile,
                      remove_watch_db, add_promo_code, redeem_code, get_user_stats,
                      claim_slip_and_add_subscription, claim_slip_and_add_topup,
                      get_topup_balance, consume_topup_balance,
                      get_chart_previews_left, consume_chart_preview, refund_chart_preview,
                      CHART_PREVIEW_TOTAL,
                      start_flash_discount_if_eligible, is_flash_active, consume_flash_discount,
                      FLASH_VIP_AMOUNT, FLASH_PRO_AMOUNT, FLASH_WINDOW_MINUTES,
                      get_social_proof_stats,
                      get_total_analyses, increment_total_analyses,
                      check_and_grant_tier_codes, get_user_tier, TIER_BADGES,
                      get_user_discount, consume_user_discount,
                      ban_user, unban_user, is_user_banned,
                      init_new_features_db, process_referral, get_referral_stats,
                      add_price_alert_db, get_user_price_alerts_db, remove_price_alert_db,
                      get_connection, add_portfolio_stock, get_user_portfolio,
                      delete_portfolio_stock, update_portfolio_stock,
                      get_user_cash_balance, set_user_cash_balance,
                      apply_cash_action, get_cash_transactions,
                      get_user_settings, set_user_notifications, set_user_timezone,
                      set_user_language, set_user_digest_frequency, set_user_news_window,
                      ALLOWED_TIMEZONES, ALLOWED_LANGUAGES, ALLOWED_DIGEST_FREQUENCIES,
                      has_used_free_trial, activate_free_trial,
                      add_earnings_alert_db, get_user_earnings_alerts_db, remove_earnings_alert_db,
                      update_last_active, mark_user_inactive, get_active_users, log_command,
                      delete_pending_referral, reset_free_trial, cleanup_old_logs,
                      log_dashboard_event)
from bot_utils import friendly_error, broadcast_maintenance_notice
from admin_service import (
    build_local_backup_zip,
    get_dashboard_metrics,
    get_maintenance_status,
    get_paid_users_snapshot,
    get_performance_snapshot,
    get_system_health_snapshot,
    get_user_stats_snapshot,
    toggle_maintenance_status,
)
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index, generate_pro_annotated_chart
from ai_analyzer import generate_apexify_report
from alert_system import (broadcast_hourly_urgent_news, check_and_broadcast_pro_news,
                          run_alert_loop, send_weekly_performance_digest)
from slipok_service import verify_payment_slip
from curl_cffi import requests as cffi_requests

telebot.logger.setLevel(logging.WARNING)
# 🌟 num_threads=8 — handler รันใน thread pool ใหญ่ → bot ไม่ block ระหว่างผู้ใช้คนเดียววิเคราะห์ 10-20 วิ
bot = telebot.TeleBot(TELEGRAM_TOKEN, num_threads=8)


# 🌟 Command logger — runs alongside (not instead of) message handlers
# ใช้เก็บ stat สำหรับ admin dashboard "top_commands" — fail-safe ไม่กระทบ bot ถ้า DB ขัดข้อง
def _command_log_listener(messages):
    for msg in messages:
        try:
            text = getattr(msg, "text", None)
            if not text or not text.startswith("/"):
                continue
            cmd = text.split()[0].lstrip("/").split("@")[0].lower()
            if not cmd or len(cmd) > 32 or not cmd.replace("_", "").isalnum():
                continue
            user_id = str(msg.from_user.id) if getattr(msg, "from_user", None) else "?"
            log_command(user_id, cmd)
        except Exception:
            pass


bot.set_update_listener(_command_log_listener)

# ==========================================
# 🌟 ระบบ Anti-Spam ดักจับคนป่วนรัวข้อความ
# ==========================================
user_message_tracking = {}
user_command_history = {}
spam_alerted = set()
_last_active_cache = {}  # rate-limit last_active DB writes (5 min)

SETTINGS_NEWS_WINDOW_PRESETS = [
    (0, 23),   # all day
    (7, 11),   # morning
    (12, 17),  # afternoon
    (18, 23),  # evening
    (7, 22),   # business day
]
SETTINGS_LANGUAGE_LABELS = {"th": "Thai", "en": "English"}

# 🌟 โควต้าฟรีต่อวัน (รีเซ็ตเที่ยงคืน)
FREE_DAILY_QUOTA = 3


def _format_news_window(start_hour, end_hour):
    start = int(start_hour) % 24
    end = int(end_hour) % 24
    if start <= end:
        return f"{start:02d}:00-{end:02d}:59"
    return f"{start:02d}:00-{end:02d}:59 (overnight)"


def _build_settings_keyboard(settings):
    notifications_label = "ON" if settings["notifications_enabled"] else "OFF"
    timezone_label = settings.get("timezone", "Asia/Bangkok")
    language_label = SETTINGS_LANGUAGE_LABELS.get(
        settings.get("language", "th"),
        settings.get("language", "th"),
    )
    digest_label = f"Every {settings.get('digest_frequency_hours', 4)}h"
    news_window_label = _format_news_window(
        settings.get("news_start_hour", 7),
        settings.get("news_end_hour", 22),
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"Alerts: {notifications_label}", callback_data="settings_toggle"),
        InlineKeyboardButton(f"Timezone: {timezone_label}", callback_data="settings_tz_next"),
    )
    markup.add(
        InlineKeyboardButton(f"Language: {language_label}", callback_data="settings_lang_next"),
        InlineKeyboardButton(f"Digest: {digest_label}", callback_data="settings_digest_next"),
    )
    markup.add(
        InlineKeyboardButton(f"News window: {news_window_label}", callback_data="settings_window_cycle"),
    )
    markup.add(
        InlineKeyboardButton("Refresh", callback_data="settings_refresh"),
    )
    return markup


def _build_settings_text(user_id, settings):
    notifications_label = "ON" if settings["notifications_enabled"] else "OFF"
    timezone_label = settings.get("timezone", "Asia/Bangkok")
    language_label = SETTINGS_LANGUAGE_LABELS.get(
        settings.get("language", "th"),
        settings.get("language", "th"),
    )
    digest_label = f"{settings.get('digest_frequency_hours', 4)} hours"
    news_window_label = _format_news_window(
        settings.get("news_start_hour", 7),
        settings.get("news_end_hour", 22),
    )
    return (
        "⚙️ *User Settings*\n\n"
        f"`User ID:` `{user_id}`\n"
        f"`Alerts:` `{notifications_label}`\n"
        f"`News Timezone:` `{timezone_label}`\n"
        f"`Language:` `{language_label}`\n"
        f"`Digest Frequency:` `{digest_label}`\n"
        f"`News Receive Window:` `{news_window_label}`\n\n"
        "Tap buttons below to update."
    )


def send_settings_panel(chat_id, user_id=None, edit_message_id=None):
    target_user = str(user_id or chat_id)
    settings = get_user_settings(target_user)
    text = _build_settings_text(target_user, settings)
    markup = _build_settings_keyboard(settings)
    if edit_message_id:
        return bot.edit_message_text(
            text,
            chat_id,
            edit_message_id,
            parse_mode="Markdown",
            reply_markup=markup,
        )
    return bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown",
        reply_markup=markup,
    )

def is_allowed(user_id):
    if user_id == ADMIN_ID: return True 
    if is_user_banned(user_id): return False 
    
    # 🌟 ดักโหมดปิดปรับปรุงระบบ (แอดมินจะรอดผ่าน if user_id == ADMIN_ID ด้านบนมาแล้ว)
    if get_maintenance_status():
        try:
            bot.send_message(user_id, "🛠 **ระบบกำลังปิดปรับปรุง (Maintenance Mode)**\n\nทีมงาน Apexify กำลังอัปเกรดระบบให้ดียิ่งขึ้น กรุณารอสักครู่ครับ... 🚀", parse_mode="Markdown")
        except Exception:
            pass
        return False
        
    now = time.time()
    if user_id not in user_message_tracking:
        user_message_tracking[user_id] = []

    user_message_tracking[user_id].append(now)
    user_message_tracking[user_id] = [t for t in user_message_tracking[user_id] if now - t < 10]

    if len(user_message_tracking[user_id]) > 5:
        if user_id not in spam_alerted:
            bot.send_message(ADMIN_ID, f"🚨 **แจ้งเตือนสแปม:** User `{user_id}` พยายามส่งข้อความรัวๆ ระบบระงับชั่วคราว\n👉 พิมพ์ `/ban {user_id}` เพื่อแบน", parse_mode="Markdown")
            spam_alerted.add(user_id)
        return False

    if user_id in spam_alerted:
        spam_alerted.remove(user_id)

    return True

# 🌟 เพิ่ม def สำหรับคำสั่ง /maintenance ไว้ในกลุ่ม @bot.message_handler(commands=...)
@bot.message_handler(commands=['maintenance'])
def handle_maintenance(message):
    if str(message.chat.id) != ADMIN_ID: return
    enabled = toggle_maintenance_status()
    status = "🔴 เปิด (ผู้ใช้ทั่วไปใช้งานไม่ได้, แอดมินใช้ได้ปกติ)" if enabled else "🟢 ปิด (ระบบเปิดใช้งานปกติทุกคน)"
    notice_label = "ปิดปรับปรุง" if enabled else "กลับมาใช้งานปกติ"
    bot.reply_to(
        message,
        f"🛠 **สถานะ Maintenance Mode:** {status}\n\n"
        f"📣 กำลังบรอดแคสต์แจ้ง user ทุกคนว่า '{notice_label}' ในเบื้องหลัง...",
        parse_mode="Markdown",
    )
    # Background broadcast — ไม่ block handler thread
    broadcast_maintenance_notice(bot, enabled, admin_id=ADMIN_ID)

@bot.message_handler(commands=['force_backup'])
def handle_force_backup(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    load_msg = bot.reply_to(message, "⏳ กำลังบีบอัดฐานข้อมูล `apexify.db` โปรดรอสักครู่...", parse_mode="Markdown")
    
    try:
        success, zip_filename, zip_buffer, reason = build_local_backup_zip()
        if not success or zip_buffer is None:
            bot.edit_message_text("❌ ไม่พบไฟล์ฐานข้อมูล (ระบบอาจจะเชื่อมต่อกับ Cloud Database อยู่)", message.chat.id, load_msg.message_id)
            return

        # ส่งไฟล์เข้าแชทแอดมิน
        zip_buffer.seek(0)
        bot.send_document(
            message.chat.id,
            zip_buffer,
            caption=f"📦 **Backup ฐานข้อมูลสำเร็จ!**\n📅 {time.strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode="Markdown",
        )
        bot.delete_message(message.chat.id, load_msg.message_id)
        
    except Exception as e:
        print(f"[force_backup] {e}", flush=True)
        bot.edit_message_text(friendly_error("Backup ล้มเหลว"), message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['system_health'])
def handle_system_health(message):
    if str(message.chat.id) != ADMIN_ID: return

    load_msg = bot.reply_to(message, "⏳ กำลังดึงข้อมูลสถานะเซิร์ฟเวอร์...")
    try:
        snapshot = get_system_health_snapshot()
        msg = (
            "💻 **สถานะเซิร์ฟเวอร์ (System Health)** 💻\n\n"
            f"🧠 **CPU Usage:** {snapshot['cpu_usage']:.0f}%\n"
            f"💽 **RAM Usage:** {snapshot['ram_used_gb']:.2f} GB / {snapshot['ram_total_gb']:.2f} GB ({snapshot['ram_percent']:.0f}%)\n"
            f"💾 **Disk Space:** {snapshot['disk_percent']:.0f}% ใช้ไป\n"
            f"⏱ **Server Uptime:** {int(snapshot['uptime_hours'])} ชั่วโมง\n\n"
            f"✅ ระบบทำงานปกติ ลื่นไหลไม่มีสะดุดครับ!"
        )
        bot.edit_message_text(msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[system_health] {e}", flush=True)
        bot.edit_message_text(friendly_error("ดึงข้อมูลระบบไม่สำเร็จ"), message.chat.id, load_msg.message_id)


@bot.message_handler(commands=['perf_stats'])
def handle_perf_stats(message):
    """🌟 Admin command — ดู cache hit rate + dashboard build time"""
    if str(message.chat.id) != ADMIN_ID:
        return
    try:
        metrics = get_dashboard_metrics()
        from technical_tools import _yf_history_cache
        from ai_analyzer import _ai_response_cache
        msg = (
            "📊 **Performance Metrics** 📊\n\n"
            "**Admin Dashboard:**\n"
            f"• Cache hits: {metrics['snapshot_cache_hits']}\n"
            f"• Cache misses: {metrics['snapshot_cache_misses']}\n"
            f"• Hit rate: {metrics['hit_rate_pct']:.1f}%\n"
            f"• Last build: {metrics['last_build_seconds']:.2f}s\n\n"
            "**yfinance cache (TTL 300s):**\n"
            f"• Items: {len(_yf_history_cache)}/{_yf_history_cache.maxsize}\n\n"
            "**AI response cache (TTL 300s):**\n"
            f"• Items: {len(_ai_response_cache)}/{_ai_response_cache.maxsize}\n\n"
            "_Cache miss = ครั้งแรกของหุ้น/dashboard ใหม่ (ปกติ)_\n"
            "_Hit rate ยิ่งสูง = bot ยิ่งเร็ว_"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[perf_stats] {e}", flush=True)
        bot.reply_to(message, friendly_error("ดึงข้อมูลไม่สำเร็จ"))

@bot.message_handler(commands=['users_pro'])
def handle_users_pro(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    load_msg = bot.reply_to(message, "⏳ กำลังดึงรายชื่อลูกค้า PRO และ VIP...")
    try:
        users_list = get_paid_users_snapshot()
        
        if not users_list:
            bot.edit_message_text("❌ ยังไม่มีลูกค้า VIP หรือ PRO ในระบบ", message.chat.id, load_msg.message_id)
            return
            
        report = "👑 **รายชื่อลูกค้า VIP / PRO ทั้งหมด** 👑\n\n"
        count = 1
        for item in users_list:
            role_icon = "👑" if item["role"] == 'pro' else "💎"
            status_icon = "✅" if item["is_active"] else "❌ (หมดอายุ)"
            
            report += f"{count}. {role_icon} `{item['user_id']}` | หมดอายุ: {item['expiry_date']} {status_icon}\n"
            count += 1
            
            # ป้องกันข้อความยาวเกินลิมิตของ Telegram (ประมาณ 4000 ตัวอักษร)
            if len(report) > 3500:
                report += "\n... (ยังมีต่อ แต่ข้อความยาวเกินไป)"
                break
                
        bot.edit_message_text(report, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.edit_message_text("❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ", message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['force_news'])
def handle_force_news(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    args = message.text.split()
    news_type = args[1].lower() if len(args) > 1 else 'flash'
    
    load_msg = bot.reply_to(message, f"🚨 กำลังให้ Apexify ดึงข่าวด่วนแบบ `{news_type.upper()}` และบรอดแคสต์ทันที...")
    try:
        if news_type == 'flash':
            broadcast_hourly_urgent_news(bot, force=True)
            bot.edit_message_text("✅ บรอดแคสต์ Flash News ข่าวเดียวเด่นๆ สำเร็จ!", message.chat.id, load_msg.message_id)
        elif news_type == 'digest':
            check_and_broadcast_pro_news(bot, force=True)
            bot.edit_message_text("✅ บรอดแคสต์ Digest News (แบบ 2 ข่าวสั้น) สำเร็จ!", message.chat.id, load_msg.message_id)
        else:
            bot.edit_message_text("❌ ประเภทข่าวไม่ถูกต้อง พิมพ์ `/force_news flash` หรือ `/force_news digest`", message.chat.id, load_msg.message_id)
    except Exception as e:
        print(f"[force_news] {e}", flush=True)
        bot.edit_message_text(friendly_error("ดึงข่าวไม่สำเร็จ"), message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['streak_debug'])
def handle_streak_debug(message):
    """Admin: ตรวจ schema + สถานะ streak ของตัวเอง"""
    if str(message.chat.id) != ADMIN_ID:
        return
    try:
        from database import get_connection, get_streak_info, _thai_today
        conn = get_connection()
        c = conn.cursor()
        # 1. ตรวจว่า columns มีไหม
        c.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name IN
                ('streak_count', 'last_streak_date', 'longest_streak')
        """)
        cols = [row[0] for row in c.fetchall()]
        # 2. ค่าตัวเอง
        c.execute("SELECT streak_count, last_streak_date, longest_streak FROM users WHERE user_id=%s",
                  (str(message.chat.id),))
        row = c.fetchone()
        conn.close()

        info = get_streak_info(str(message.chat.id))
        msg = (
            "🔍 *Streak Debug*\n\n"
            f"*Schema columns found:* {len(cols)}/3\n"
            f"  • streak_count: {'✅' if 'streak_count' in cols else '❌ MISSING'}\n"
            f"  • last_streak_date: {'✅' if 'last_streak_date' in cols else '❌ MISSING'}\n"
            f"  • longest_streak: {'✅' if 'longest_streak' in cols else '❌ MISSING'}\n\n"
            f"*Thai today:* `{_thai_today()}`\n"
            f"*Your raw row:* `{row}`\n"
            f"*get_streak_info:* `{info}`\n\n"
            "_ถ้า columns missing → รัน `init_new_features_db()` ใหม่_"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        import traceback
        bot.reply_to(message, f"❌ Debug error: `{e}`\n```\n{traceback.format_exc()[-500:]}\n```", parse_mode="Markdown")


@bot.message_handler(commands=['force_weekly'])
def handle_force_weekly(message):
    """Admin: สั่งส่ง Weekly Digest ทันที (สำหรับทดสอบ)"""
    if str(message.chat.id) != ADMIN_ID:
        return
    load_msg = bot.reply_to(message, "🚨 กำลังบรอดแคสต์ Weekly Digest...")
    try:
        send_weekly_performance_digest(bot)
        bot.edit_message_text("✅ บรอดแคสต์ Weekly Digest สำเร็จ!", message.chat.id, load_msg.message_id)
    except Exception as e:
        print(f"[force_weekly] {e}", flush=True)
        bot.edit_message_text(friendly_error("ส่ง Weekly Digest ล้มเหลว"), message.chat.id, load_msg.message_id)


@bot.message_handler(commands=['user_history'])
def handle_user_history(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/user_history [รหัสผู้ใช้]`", parse_mode="Markdown")
        return
        
    target_id = args[1]
    history = user_command_history.get(target_id, [])
    
    if not history:
        bot.reply_to(message, f"❌ ไม่พบประวัติการใช้งานล่าสุดของ `{target_id}` ในหน่วยความจำ\n*(อาจจะยังไม่ได้พิมพ์อะไรเข้ามา หรือเซิร์ฟเวอร์เพิ่งรีสตาร์ท)*", parse_mode="Markdown")
        return
        
    report = f"🕵️‍♂️ **ประวัติคำสั่งล่าสุดของ `{target_id}`**\n\n"
    for i, cmd in enumerate(history[-10:], 1): # ดึงมาแค่ 10 อันล่าสุดก็พอ
        report += f"{i}. `{cmd}`\n"
        
    bot.reply_to(message, report, parse_mode="Markdown")

@bot.message_handler(commands=['mock_alert'])
def handle_mock_alert(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    args = message.text.split()
    alert_type = args[1].lower() if len(args) > 1 else 'whale'
    
    try:
        if alert_type == 'whale':
            msg = f"🐳 **WHALE ALERT (มีวาฬเข้า!)** 🐳\nหุ้น **PTT.BK** มีวอลุ่มซื้อพุ่งกระฉูดกว่าค่าเฉลี่ย 350% จับตาดูให้ดี!\n(ราคาปัจจุบัน: 35.50)"
        elif alert_type == 'dump':
            msg = f"🩸 **WHALE DUMP (วาฬเทขาย!)** 🩸\nหุ้น **DELTA.BK** โดนสาดวอลุ่มขายทิ้งหนักกว่าค่าเฉลี่ย 400% ระวังแรงฉุด!\n(ราคาปัจจุบัน: 75.00)"
        elif alert_type == 'golden':
            msg = f"✨ **GOLDEN CROSS DETECTED** ✨\nเส้น EMA50 ตัดขึ้นเหนือ EMA200 สัญญาณกลับตัวเป็นขาขึ้นระยะยาว! (ราคาปัจจุบัน: 120.00)"
        elif alert_type == 'xd':
            msg = f"📅 **XD ALERT: ADVANC.BK** 📅\n\nหุ้นตัวนี้กำลังจะขึ้นเครื่องหมาย XD (จ่ายปันผล) ในวันที่ **28/02/2026**\n*(เหลือเวลาอีกประมาณ 3 วัน)*\n\n👉 สายปันผลเตรียมตัว สายเก็งกำไรระวังราคาเปิดกระโดดลงนะครับ!"
        else:
            bot.reply_to(message, "❌ ไม่รู้จักประเภท Alert. พิมพ์ลองเทสต์แบบนี้ครับ:\n`/mock_alert whale`\n`/mock_alert dump`\n`/mock_alert golden`\n`/mock_alert xd`", parse_mode="Markdown")
            return
            
        bot.send_message(ADMIN_ID, f"🧪 **[MOCK TEST]** ส่งทดสอบข้อความแจ้งเตือนเข้าแชทคุณสำเร็จ:\n\n{msg}", parse_mode="Markdown")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")        
def generate_random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ==========================================
# Dashboard Magic Login (Telegram -> Web)
# ==========================================

def _log_dashboard_event(user_id, role, event_name, source=None, feature=None):
    threading.Thread(
        target=log_dashboard_event,
        args=(user_id, role, event_name, source, feature),
        daemon=True,
    ).start()


def _dashboard_cta_button(user_id: str, label: str, src: str, next_path: str = "/"):
    """Returns an InlineKeyboardButton with a magic-login URL, or None if dashboard is unavailable.
    Logs `dashboard_link_issued` with `source=src` so funnel analytics can attribute
    each CTA touchpoint (alerts_cmd, portfolio_cmd, etc.) — not just /dashboard."""
    ready, _ = is_dashboard_login_ready()
    if not ready:
        return None
    url = build_dashboard_login_url(user_id, src=src, next_path=next_path)
    try:
        role = check_subscription(user_id)
    except Exception:
        role = None
    _log_dashboard_event(user_id, role, "dashboard_link_issued", source=src)
    return InlineKeyboardButton(label, url=url)


def send_dashboard_login_link(user_id, src="command"):
    success, login_url, reason = issue_dashboard_login_url(user_id, src=src)
    if not success:
        if reason in {'disabled', 'url_missing', 'secret_missing'}:
            bot.send_message(user_id, "ระบบลิงก์ Dashboard ยังไม่พร้อมใช้งาน กรุณาติดต่อแอดมิน")
        else:
            bot.send_message(user_id, "ไม่สามารถสร้างลิงก์เข้า Dashboard ได้ กรุณาลองใหม่อีกครั้ง")
        return

    ttl_minutes = max(1, (max(1, int(DASHBOARD_LOGIN_TOKEN_TTL)) + 59) // 60)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🌐 เปิด Dashboard", url=login_url))
    msg = (
        "🌐 *Dashboard ของคุณพร้อมใช้งาน*\n\n"
        "กดปุ่มด้านล่างเพื่อเปิด Portfolio Cockpit — ดูพอร์ต, Watchlist และฟีเจอร์ทั้งหมดของคุณ\n\n"
        f"_ลิงก์ใช้ได้ {ttl_minutes} นาที — หมดอายุแล้วพิมพ์ /dashboard ใหม่_"
    )
    bot.send_message(user_id, msg, reply_markup=markup, parse_mode="Markdown")
    role = check_subscription(user_id)
    _log_dashboard_event(user_id, role, "dashboard_link_issued", source=src)


def send_admin_dashboard_link(user_id):
    if str(user_id) != str(ADMIN_ID):
        return

    success, login_url, reason = issue_admin_dashboard_url(user_id)
    if not success:
        if reason in {"disabled", "url_missing", "secret_missing", "admin_missing"}:
            bot.send_message(user_id, "ระบบ Admin Dashboard ยังไม่พร้อมใช้งาน กรุณาตรวจสอบค่า BOT_WEB_BASE_URL และ secret")
        else:
            bot.send_message(user_id, "ไม่สามารถสร้างลิงก์เข้า Admin Dashboard ได้ กรุณาลองใหม่อีกครั้ง")
        return

    ttl_seconds = max(1, int(DASHBOARD_LOGIN_TOKEN_TTL))
    ttl_minutes = max(1, (ttl_seconds + 59) // 60)

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("เปิด Admin Dashboard", url=login_url))
    msg = (
        "กดปุ่มด้านล่างเพื่อเปิด Admin Dashboard แบบลิงก์ชั่วคราว\n"
        f"ลิงก์นี้มีอายุประมาณ {ttl_minutes} นาที\n\n"
        "ลิงก์นี้ใช้ได้เฉพาะบัญชีแอดมินเท่านั้น"
    )
    bot.send_message(user_id, msg, reply_markup=markup)


@bot.message_handler(commands=['dashboard'])
def handle_dashboard_login(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    send_dashboard_login_link(user_id)


@bot.message_handler(commands=['settings'])
def handle_settings(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    send_settings_panel(message.chat.id, user_id=user_id)


# 🌟 เก็บ symbol ล่าสุดที่ user วิเคราะห์ (สำหรับ /ask context)
_user_last_symbol = {}  # {user_id: symbol}


@bot.message_handler(commands=['ask'])
def handle_ask(message):
    """PRO: ถาม AI เป็นคำถามเฉพาะ (context-aware ถ้าวิเคราะห์หุ้นล่าสุด)
    Examples: /ask ทำไม RSI สูง, /ask หุ้นไหนน่าสนตอนนี้
    """
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role != 'pro' and user_id != ADMIN_ID:
        bot.reply_to(message,
            "🔒 **Apexify Q&A — ฟีเจอร์ PRO เท่านั้น**\n\n"
            "ถาม AI คำถามการลงทุน/หุ้น ได้ตลอด 24 ชม.\n\n"
            "👑 อัปเกรดเป็น PRO เพื่อใช้ฟีเจอร์นี้",
            parse_mode="Markdown")
        return

    # ดึงคำถาม
    args = message.text.split(' ', 1)
    if len(args) < 2 or not args[1].strip():
        example_symbol = _user_last_symbol.get(user_id, "AAPL")
        bot.reply_to(message,
            "💬 **Apexify Q&A — วิธีใช้**\n\n"
            "พิมพ์: `/ask <คำถาม>`\n\n"
            "*ตัวอย่าง:*\n"
            f"• `/ask ทำไม RSI {example_symbol} สูง?`\n"
            "• `/ask อธิบาย MACD ให้หน่อย`\n"
            "• `/ask หุ้นเทคโนโลยีกับ financial ตอนนี้อันไหนน่าสน?`\n"
            "• `/ask ควรใช้ SL กี่ % ดี`\n\n"
            "_ถามได้ทั้งคำถามทั่วไป + คำถามเกี่ยวกับหุ้นที่วิเคราะห์ล่าสุด_",
            parse_mode="Markdown")
        return

    question = args[1].strip()[:500]  # cap 500 chars
    load_msg = bot.reply_to(message, "🤔 Apexify กำลังคิด...")

    try:
        # 🌟 ถ้ามี symbol ล่าสุด → ใส่ context ให้ AI
        last_symbol = _user_last_symbol.get(user_id)
        context_section = ""
        if last_symbol:
            try:
                tech_data, _, err = _get_cached_analysis(last_symbol, generate_chart=False)
                if tech_data and not err:
                    context_section = (
                        f"\n[Context: user เพิ่งวิเคราะห์ {last_symbol} "
                        f"ราคา ${tech_data.get('price', 0):.2f} "
                        f"RSI={tech_data.get('rsi', 0):.1f} "
                        f"MACD={tech_data.get('macd', 0):.2f}/{tech_data.get('macd_signal', 0):.2f} "
                        f"S={tech_data.get('support', 0):.2f} R={tech_data.get('resistance', 0):.2f}]\n"
                    )
            except Exception:
                pass

        from ai_analyzer import client as ai_client
        prompt = f"""
คุณคือ Apexify AI Analyst — ตอบคำถามนักลงทุนภาษาไทย

กฎ:
- ตอบกระชับ 3-5 บรรทัด ห้ามยาวเกิน 400 ตัวอักษร
- actionable สำหรับคนไทย — มีตัวอย่าง/ตัวเลขถ้าเป็นไปได้
- ไม่ชี้นำซื้อขาย (ห้ามใช้ "ซื้อเลย" "ขายเลย" "การันตี")
- ถ้าถามเกี่ยวกับหุ้นเฉพาะ ใช้ context ที่ให้
- ถ้าไม่มีข้อมูลพอ บอกตรงๆ ห้ามมั่ว
{context_section}
คำถาม: {question}

ตอบ:
""".strip()

        response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        answer = response.text.strip()[:800]

        # Thai quality guard
        try:
            from ai_analyzer import _fix_thai_typos
            answer = _fix_thai_typos(answer)
        except Exception:
            pass

        reply = (
            f"💬 **Q:** _{question[:150]}_\n\n"
            f"🤖 **A:** {answer}\n\n"
            f"_⚠️ คำตอบนี้จัดทำขึ้นเพื่อประกอบการพิจารณาเท่านั้น มิใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรใช้ดุลยพินิจของตนเอง_"
        )
        bot.edit_message_text(reply, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[/ask] error: {e}", flush=True)
        err_str = str(e).lower()
        if '503' in err_str or 'unavailable' in err_str:
            friendly = "✨ Apexify กำลังมีคนใช้งานเยอะเป็นพิเศษ ขอรบกวนลองอีกครั้งในอีกสักครู่ครับ 🙏"
        elif 'safety' in err_str:
            friendly = "📋 Apexify ขอปฏิเสธตอบคำถามนี้ (ติดฟิลเตอร์ความปลอดภัย)\nรบกวนลองปรับคำถามใหม่ดูครับ"
        else:
            friendly = "📡 ขณะนี้ระบบตอบสนองช้ากว่าปกติ\nรบกวนลองอีกครั้งในอีกสักครู่ครับ"
        bot.edit_message_text(friendly, message.chat.id, load_msg.message_id)


@bot.message_handler(commands=['account', 'me', 'payment'])
def handle_account_command(message):
    """Shortcut → ส่งข้อความ "💎 บัญชี / VIP" ให้ trigger flow เดิม"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    # Reuse logic ของปุ่ม "💎 บัญชี / VIP"
    class FakeMsg:
        def __init__(self, chat_id, msg_id):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(id=chat_id)
            self.from_user = SimpleNamespace(id=chat_id)
            self.text = "💎 บัญชี / VIP"
            self.message_id = msg_id
    handle_main(FakeMsg(int(user_id), message.message_id))


@bot.message_handler(commands=['myalerts'])
def handle_my_alerts(message):
    """แสดง price alerts ที่ตั้งไว้ — wrapper ของ hub_price_alert"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role != 'pro' and user_id != ADMIN_ID:
        bot.reply_to(message,
            "🔒 **Price Alerts — ฟีเจอร์ PRO เท่านั้น**\n\n"
            "อัปเกรด PRO เพื่อตั้งเตือนราคาส่วนตัว",
            parse_mode="Markdown")
        return
    try:
        alerts = get_user_price_alerts_db(user_id)
        markup = InlineKeyboardMarkup()
        if not alerts:
            header = "🔔 *Price Alerts ของคุณ*\n\nยังไม่มีรายการเฝ้าดู\n\n"
        else:
            header = f"🔔 *Price Alerts ของคุณ* ({len(alerts)} รายการ)\n\n"
            for alert in alerts:
                a_id, sym, price, cond = alert
                cond_text = "ขึ้นถึง" if cond == 'above' else "ลงถึง"
                markup.add(InlineKeyboardButton(
                    f"❌ {sym} {cond_text} {price:,.2f}",
                    callback_data=f"delalert_{a_id}"
                ))
        footer = "➕ เพิ่มเตือนใหม่: `/setalert [หุ้น] [ราคา]`\nเช่น `/setalert PTT.BK 35`"
        _alerts_btn = _dashboard_cta_button(user_id, "🔔 จัดการ Alerts ใน Dashboard", src="alerts_cmd", next_path="/alerts")
        if _alerts_btn:
            markup.add(_alerts_btn)
        bot.reply_to(message, header + footer, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"[/myalerts] error: {e}", flush=True)
        bot.reply_to(message, "📡 ระบบขัดข้องชั่วคราว ลองอีกครั้งนะครับ")


@bot.message_handler(commands=['weekly_recap', 'weekly'])
def handle_weekly_recap(message):
    """สรุปประจำสัปดาห์ส่วนตัว — watchlist 7d, streak, tier status. on-demand any tier."""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return

    role = check_subscription(user_id)
    try:
        from database import get_streak_info
        streak = get_streak_info(user_id) or {}
    except Exception:
        streak = {}
    try:
        watchlist = get_user_watch(user_id) or []
    except Exception:
        watchlist = []

    lines = ["🗓️ **Weekly Recap** — สรุปอาทิตย์นี้\n"]

    # Tier line
    if role == 'pro':
        lines.append("👑 **PRO** กำลังใช้งาน · ฟีเจอร์ครบทุกอย่าง")
    elif role == 'vip':
        lines.append("💎 **VIP** กำลังใช้งาน · กราฟเทคนิค + Trend Radar")
    else:
        lines.append("🆓 **Free** · 3 ครั้ง/วัน · `/freetrial` ทดลอง PRO 7 วันฟรี")

    # Streak
    cur_streak = streak.get('current', 0) if isinstance(streak, dict) else 0
    longest = streak.get('longest', 0) if isinstance(streak, dict) else 0
    if cur_streak > 0:
        lines.append(f"🔥 Streak: **{cur_streak} วันติด** (best: {longest})")
    else:
        lines.append("🔥 Streak: ยังไม่เริ่ม — วิเคราะห์หุ้นวันนี้เพื่อสะสม streak")

    # Watchlist 7d performance
    if watchlist:
        lines.append(f"\n📋 **Watchlist 7 วันที่ผ่านมา** ({len(watchlist)} ตัว)")
        perfs = []
        for sym in watchlist[:10]:  # cap at 10 — yfinance latency
            try:
                hist = yf.Ticker(sym).history(period='8d')
                if len(hist) < 2:
                    continue
                start = hist['Close'].iloc[0]
                end = hist['Close'].iloc[-1]
                if not start:
                    continue
                pct = (end - start) / start * 100
                perfs.append((sym, pct))
            except Exception:
                continue
        if perfs:
            perfs.sort(key=lambda x: x[1], reverse=True)
            top = perfs[:3]
            bottom = [p for p in perfs[-3:] if p[1] < 0 and p not in top]
            lines.append("\n📈 _ขึ้นมากสุด:_")
            for sym, pct in top:
                icon = "🟢" if pct >= 0 else "🔴"
                lines.append(f"   {icon} **{sym}** {pct:+.2f}%")
            if bottom:
                lines.append("\n📉 _ลงมากสุด:_")
                for sym, pct in bottom[::-1]:
                    lines.append(f"   🔴 **{sym}** {pct:+.2f}%")
        else:
            lines.append("   _ดึงข้อมูลตลาดไม่สำเร็จ — ลองพิมพ์ `/weekly_recap` ใหม่_")
    else:
        lines.append("\n📋 **Watchlist:** ยังว่าง — `/watch AAPL` เพิ่มหุ้นที่สนใจไว้ติดตาม")

    lines.append("\n_💡 พิมพ์ `/weekly_recap` ทุกอาทิตย์เพื่อดูสรุปใหม่_")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['demo', 'showcase', 'features'])
def handle_demo(message):
    """แสดง overview ฟีเจอร์ทั้งหมด — ใช้ทั้งโชว์ user ใหม่ + sales pitch"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return

    msg = (
        "🚀 **Apexify — Full Feature Tour**\n\n"
        "🤖 *บอทวิเคราะห์หุ้นด้วย AI — 3 สิ่งที่ Apexify ทำได้:*\n\n"
        "**1️⃣ Apexify วิเคราะห์หุ้นให้ทันที**\n"
        "   • พิมพ์ชื่อหุ้น → รายงานครบใน 10 วิ\n"
        "   • Trend Radar 3 timeframes (วัน/สัปดาห์/เดือน)\n"
        "   • Conviction Score 0-100\n"
        "   • รองรับ 10+ ตลาดทั่วโลก (US, ไทย, HK, JP, ...)\n\n"
        "**2️⃣ Plan เทรดสำเร็จรูป (PRO)** 🎯\n"
        "   • Entry zone + TP1 + TP2 + SL เป็นตัวเลข\n"
        "   • กราฟวาด zone ให้ดูเลย (Entry สีเขียว / SL สีแดง)\n"
        "   • เงื่อนไขยืนยัน + ยกเลิก Plan\n"
        "   • R:R warning เมื่อ setup ไม่ดี\n\n"
        "**3️⃣ ติดตาม 24/7** 🔔\n"
        "   • Smart Alerts (RSI, MACD, volume spike)\n"
        "   • Custom Price Alerts (PRO)\n"
        "   • Earnings Calendar + News feed\n"
        "   • Morning Briefing 8:30 + Weekly Digest ศุกร์\n\n"
        "**📊 พิสูจน์ว่าใช้ได้จริง:**\n"
        "   • `/track` — Track Record 30/90 วัน hit rate\n"
        "   • 🔥 ใช้ทุกวัน 7 วัน → รับ VIP 1 วันฟรี\n\n"
        "**💎 ราคา:**\n"
        "   🆓 Free — 3 ครั้ง/วัน (ลองก่อน)\n"
        "   💎 VIP — 79฿/เดือน (ภาพรวม + Alerts)\n"
        "   👑 PRO — 109฿/เดือน (Plan เทรด + ครบทุกอย่าง)\n\n"
        "_💡 พิมพ์ `/` ใน Telegram เพื่อดูคำสั่งทั้งหมด หรือลองพิมพ์ `AAPL` ได้เลย_"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔍 ลองวิเคราะห์ AAPL", callback_data="tutorial_analyze_AAPL"),
        InlineKeyboardButton("🇹🇭 ลอง PTT.BK", callback_data="tutorial_analyze_PTT.BK"),
    )
    markup.add(
        InlineKeyboardButton("⚡ ลอง NVDA", callback_data="tutorial_analyze_NVDA"),
    )
    markup.add(
        InlineKeyboardButton("📊 ดู Track Record", callback_data="hub_track"),
        InlineKeyboardButton("📋 Full Commands", callback_data="menu_manual"),
    )
    markup.add(
        InlineKeyboardButton("🆓 ทดลอง PRO 7 วันฟรี", callback_data="menu_freetrial"),
        InlineKeyboardButton("💎 สมัคร VIP/PRO", callback_data="menu_vip"),
    )
    markup.add(
        InlineKeyboardButton("🤝 ชวนเพื่อน รับ VIP ฟรี", callback_data="menu_referral"),
    )
    bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=['backfill_analyses'])
def handle_backfill_analyses(message):
    """Admin: backfill total_analyses จาก analysis_plans (count plans per user)
    one-shot script — รันครั้งเดียวหลัง deploy ใหม่
    เฉพาะ user ที่มี total_analyses=0 (กันเขียนทับคนที่นับจริงแล้ว)
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(
            message,
            f"🔒 *Admin only*\n\nYour chat_id: `{user_id}`\nADMIN_ID: `{ADMIN_ID}`",
            parse_mode="Markdown",
        )
        return
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        # นับ plans per user
        c.execute(
            """
            SELECT user_id, COUNT(*) AS cnt
            FROM analysis_plans
            WHERE user_id IS NOT NULL
            GROUP BY user_id
            HAVING COUNT(*) > 0
            """
        )
        rows = c.fetchall() or []
        if not rows:
            c.close()
            conn.close()
            bot.reply_to(message, "ℹ️ ยังไม่มี analysis_plans ใน DB — ไม่มีอะไรให้ backfill")
            return

        # อัปเดต — เฉพาะ user ที่ปัจจุบัน total=0 (กันทับ data ที่นับ post-deploy)
        updated = 0
        skipped = 0
        for uid, cnt in rows:
            try:
                c.execute(
                    "UPDATE users SET total_analyses=%s "
                    "WHERE user_id=%s AND COALESCE(total_analyses, 0) = 0 "
                    "RETURNING user_id",
                    (int(cnt), str(uid)),
                )
                if c.fetchone():
                    updated += 1
                else:
                    skipped += 1
            except Exception as _e:
                print(f"[backfill] {uid}: {_e}", flush=True)
        conn.commit()
        c.close()
        conn.close()

        # ใช้ plain text กัน Markdown parse error (em-dash ในข้อความบางครั้งทำให้ parser พัง)
        bot.reply_to(
            message,
            f"✅ Backfill สำเร็จ\n\n"
            f"📊 พบ {len(rows)} user มี analysis_plans\n"
            f"✏️ อัปเดต: {updated} คน (total=0 → count จาก plans)\n"
            f"⏭ ข้าม: {skipped} คน (มี total อยู่แล้ว ไม่เขียนทับ)\n\n"
            f"หมายเหตุ: backfill เฉพาะ PRO/admin ที่เคยมี plan log อยู่ — Free user ไม่มี history นับ",
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Backfill error: {e}")


@bot.message_handler(commands=['reset_outcomes'])
def handle_reset_outcomes(message):
    """Admin: reset evaluated plans กลับเป็น open เพื่อ re-evaluate ด้วย logic ใหม่
    ใช้หลังแก้ logic เพื่อ recompute statistics
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(
            message,
            f"🔒 *Admin only*\nYour chat_id: `{user_id}`\nADMIN_ID: `{ADMIN_ID}`",
            parse_mode="Markdown",
        )
        return
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "UPDATE analysis_plans SET outcome='open', outcome_at=NULL, outcome_note=NULL "
            "WHERE outcome IN ('tp1_hit','tp2_hit','sl_hit','expired') "
            "RETURNING id"
        )
        affected = len(c.fetchall())
        conn.commit()
        c.close(); conn.close()
        bot.reply_to(
            message,
            f"✅ Reset {affected} plans กลับเป็น `open`\n\n"
            f"ขั้นตอนถัดไป: `/run_outcomes` เพื่อ re-evaluate ด้วย logic ใหม่",
            parse_mode="Markdown",
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['run_outcomes', 'evaluate_plans'])
def handle_run_outcomes(message):
    """Admin: verbose version — รายงานทุกขั้นตอน เพื่อ debug หา bug ตัวจริง"""
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(
            message,
            f"🔒 *Admin only*\nYour chat_id: `{user_id}`\nADMIN_ID: `{ADMIN_ID}`",
            parse_mode="Markdown",
        )
        return

    progress_msg = bot.reply_to(message, "⏳ กำลังตรวจ pending plans...")
    try:
        from database import get_pending_plans, update_plan_outcome, expire_stale_plans
        import yfinance as _yf
        pending = get_pending_plans(min_age_hours=24, max_age_days=45)
        if not pending:
            bot.edit_message_text(
                "❌ *get_pending_plans คืน 0 plans*\n\n"
                "ทั้งที่ DB มี plans อายุ >24 ชม. → SQL fix อาจยังไม่ deploy หรือ has bug\n\n"
                "Verify: `git log --oneline -1` บน DO ควรเห็น `1c806ba` หรือใหม่กว่า",
                message.chat.id, progress_msg.message_id, parse_mode="Markdown",
            )
            return

        # Group by symbol
        symbols = {}
        for row in pending:
            symbols.setdefault(row[1], []).append(row)

        total_plans = len(pending)
        total_symbols = len(symbols)

        bot.edit_message_text(
            f"⏳ พบ {total_plans} plans จาก {total_symbols} symbols — กำลัง check yfinance...",
            message.chat.id, progress_msg.message_id,
        )

        updated = 0
        sym_log: list[str] = []
        yf_failed = 0
        no_hit = 0

        for symbol, plans in symbols.items():
            try:
                earliest_issued = min(p[9] for p in plans)
                ticker = _yf.Ticker(symbol)
                hist = ticker.history(start=earliest_issued.date(), interval="1d")
                if hist.empty:
                    yf_failed += 1
                    sym_log.append(f"❌ {symbol}: yf empty")
                    continue

                # 🐛 Fix: hist.index = tz-aware (US/Eastern), issued_at = naive (DB)
                # Strip tz จาก hist.index ก่อนเปรียบ
                try:
                    hist.index = hist.index.tz_localize(None)
                except (TypeError, AttributeError):
                    pass  # already naive

                sym_updated = 0
                from datetime import datetime as _dt2
                for plan in plans:
                    plan_id, _, bias, e_low, e_high, tp1, tp2, sl, _, issued_at = plan
                    tp1_v = float(tp1) if tp1 is not None else None
                    tp2_v = float(tp2) if tp2 is not None else None
                    sl_v = float(sl) if sl is not None else None
                    e_low_v = float(e_low) if e_low is not None else None
                    e_high_v = float(e_high) if e_high is not None else None

                    if hasattr(issued_at, 'tzinfo') and issued_at.tzinfo is not None:
                        issued_at = issued_at.replace(tzinfo=None)

                    plan_hist = hist[hist.index >= issued_at]
                    if plan_hist.empty:
                        continue

                    # 🛡 Phase 1: รอ entry fill, Phase 2: ตรวจ TP/SL หลัง fill
                    entry_dt = sl_dt = tp1_dt = tp2_dt = None
                    for date, row_data in plan_hist.iterrows():
                        hi = float(row_data['High'])
                        lo = float(row_data['Low'])
                        if entry_dt is None:
                            if e_low_v is not None and e_high_v is not None:
                                if lo <= e_high_v and hi >= e_low_v:
                                    entry_dt = date
                            if entry_dt is None:
                                continue
                        if sl_v is not None and lo <= sl_v and sl_dt is None:
                            sl_dt = date
                        if tp1_v is not None and hi >= tp1_v and tp1_dt is None:
                            tp1_dt = date
                        if tp2_v is not None and hi >= tp2_v and tp2_dt is None:
                            tp2_dt = date

                    # Decide outcome — entry-filled-first + conservative
                    if entry_dt is None:
                        plan_age = (_dt2.now() - issued_at).days
                        if plan_age >= 14:
                            update_plan_outcome(plan_id, 'no_entry', "Entry never reached")
                            sym_updated += 1
                        else:
                            no_hit += 1  # too young, leave open
                    elif sl_dt and (tp1_dt is None or sl_dt <= tp1_dt):
                        update_plan_outcome(plan_id, 'sl_hit', f"SL {sl_v:.2f}")
                        sym_updated += 1
                    elif tp2_dt and (sl_dt is None or tp2_dt < sl_dt):
                        update_plan_outcome(plan_id, 'tp2_hit', f"TP2 {tp2_v:.2f}")
                        sym_updated += 1
                    elif tp1_dt and (sl_dt is None or tp1_dt < sl_dt):
                        update_plan_outcome(plan_id, 'tp1_hit', f"TP1 {tp1_v:.2f}")
                        sym_updated += 1
                    else:
                        no_hit += 1  # entry filled แต่ TP/SL ยังไม่แตะ

                if sym_updated > 0:
                    sym_log.append(f"✅ {symbol}: +{sym_updated}")
                updated += sym_updated
            except Exception as e:
                sym_log.append(f"⚠️ {symbol}: {type(e).__name__}: {str(e)[:40]}")

        try:
            expire_stale_plans(max_age_days=45)
        except Exception:
            pass

        # Final report
        from database import get_connection
        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT outcome, COUNT(*) FROM analysis_plans GROUP BY outcome")
        breakdown = {row[0]: int(row[1]) for row in c.fetchall()}
        c.close(); conn.close()

        msg_parts = [
            f"✅ *evaluation เสร็จ*",
            f"",
            f"📊 *Stats:*",
            f"  • pending: {total_plans} plans / {total_symbols} symbols",
            f"  • updated: **{updated}**",
            f"  • yfinance fail: {yf_failed}",
            f"  • no hit (TP/SL ยังไม่แตะ): {no_hit}",
            f"",
            f"📈 *Outcome breakdown:*",
        ]
        for outcome in ['open', 'tp1_hit', 'tp2_hit', 'sl_hit', 'expired']:
            cnt = breakdown.get(outcome, 0)
            msg_parts.append(f"  • `{outcome}`: {cnt}")

        # Sample log (top 15 — กัน Telegram limit)
        if sym_log:
            msg_parts.extend(["", "*Sample symbols:*"])
            msg_parts.extend(sym_log[:15])
            if len(sym_log) > 15:
                msg_parts.append(f"... และอีก {len(sym_log) - 15}")

        bot.edit_message_text(
            "\n".join(msg_parts), message.chat.id, progress_msg.message_id, parse_mode="Markdown",
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Error: `{type(e).__name__}: {str(e)[:200]}`",
            message.chat.id, progress_msg.message_id, parse_mode="Markdown",
        )


@bot.message_handler(commands=['userdebug'])
def handle_user_debug(message):
    """Admin: ตรวจ state ของ user ใดๆ — full row + plans + tier
    Usage: /userdebug 8410357841
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(
            message,
            f"🔒 *Admin only*\nYour chat_id: `{user_id}`\nADMIN_ID: `{ADMIN_ID}`",
            parse_mode="Markdown",
        )
        return
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "ใช้: `/userdebug <user_id>`\nเช่น `/userdebug 8410357841`", parse_mode="Markdown")
        return
    target_id = args[1].strip()
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        # Full users row
        c.execute(
            """
            SELECT user_id, role, expiry_date, usage_count, total_analyses, streak_count,
                   longest_streak, free_trial_used, topup_balance, chart_previews_left,
                   tiers_unlocked, flash_eligible_until, discount_amount_vip, discount_amount_pro,
                   discount_until, discount_code, last_active, registered_date
            FROM users WHERE user_id=%s
            """,
            (target_id,),
        )
        row = c.fetchone()
        if not row:
            c.close(); conn.close()
            bot.reply_to(message, f"❌ ไม่พบ user `{target_id}`", parse_mode="Markdown")
            return
        # Count plans + portfolio + watchlist
        c.execute("SELECT COUNT(*) FROM analysis_plans WHERE user_id=%s", (target_id,))
        plans_count = int((c.fetchone() or [0])[0] or 0)
        c.execute("SELECT COUNT(*) FROM portfolios WHERE user_id=%s AND COALESCE(shares,0)>0", (target_id,))
        port_count = int((c.fetchone() or [0])[0] or 0)
        c.execute("SELECT COUNT(*) FROM user_watchlist WHERE user_id=%s", (target_id,))
        wl_count = int((c.fetchone() or [0])[0] or 0)
        c.close(); conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ DB error: {e}")
        return

    (uid, role, expiry, usage, total_an, streak_cur, streak_long, ft_used,
     topup_bal, chart_prev, tiers, flash_until, disc_vip, disc_pro,
     disc_until, disc_code, last_active, reg_date) = row

    # Compute effective role from check_subscription logic
    eff_role = role or 'free'
    if role in ('vip', 'pro') and expiry:
        try:
            exp_dt = expiry if isinstance(expiry, datetime) else datetime.fromisoformat(str(expiry).replace('T', ' '))
            if isinstance(exp_dt, datetime) and exp_dt.replace(tzinfo=None) < datetime.now():
                eff_role = 'free'
        except Exception:
            pass
    if str(target_id) == str(ADMIN_ID):
        eff_role = 'pro (admin)'

    parts = [
        f"👤 **User Debug — `{uid}`**",
        f"",
        f"🏷 *role (DB):* `{role or 'free'}`  →  *effective:* `{eff_role}`",
        f"⏰ *expiry_date:* `{expiry or '—'}`",
        f"📅 *registered:* `{str(reg_date)[:10] if reg_date else '—'}`",
        f"⏱ *last_active:* `{str(last_active)[:19] if last_active else '—'}`",
        f"",
        f"📈 *Quota:* `{usage or 0}/3` (free reset midnight)",
        f"📊 *total_analyses:* `{total_an or 0}` (lifetime)",
        f"🔥 *streak:* current `{streak_cur or 0}` · longest `{streak_long or 0}`",
        f"🆓 *free_trial_used:* `{ft_used}`",
        f"",
        f"🎟 *topup_balance:* `{topup_bal or 0}` ครั้ง",
        f"🎁 *chart_previews_left:* `{chart_prev if chart_prev is not None else '—'}`",
        f"🏆 *tiers_unlocked:* `{tiers or '(empty)'}`",
        f"",
        f"⚡ *flash_eligible_until:* `{flash_until or '—'}`",
        f"💰 *discount:* code=`{disc_code or '—'}` vip=`{disc_vip or '—'}` pro=`{disc_pro or '—'}` until=`{disc_until or '—'}`",
        f"",
        f"📋 *Holdings:* `{port_count}` · *Watchlist:* `{wl_count}` · *Plans logged:* `{plans_count}`",
    ]
    bot.reply_to(message, "\n".join(parts), parse_mode="Markdown")


@bot.message_handler(commands=['reset_quota'])
def handle_reset_quota(message):
    """Admin: reset quota+counters ของ user (สำหรับ test) — ไม่กระทบ subscription
    Usage: /reset_quota 8410357841
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(
            message,
            f"🔒 *Admin only*\nYour chat_id: `{user_id}`\nADMIN_ID: `{ADMIN_ID}`",
            parse_mode="Markdown",
        )
        return
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "ใช้: `/reset_quota <user_id>`", parse_mode="Markdown")
        return
    target_id = args[1].strip()
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "UPDATE users SET usage_count=0 WHERE user_id=%s RETURNING user_id",
            (target_id,),
        )
        ok = c.fetchone() is not None
        conn.commit()
        c.close(); conn.close()
        if ok:
            bot.reply_to(message, f"✅ Reset quota สำเร็จ — user `{target_id}` ใช้ได้อีก 3 ครั้ง", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ ไม่พบ user `{target_id}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ DB error: {e}")


@bot.message_handler(commands=['whoami'])
def handle_whoami(message):
    """ตรวจ chat_id + admin status — ใครก็ใช้ได้ ช่วย debug"""
    user_id = str(message.chat.id)
    is_admin = user_id == str(ADMIN_ID)
    msg = (
        f"🆔 **Your chat_id:** `{user_id}`\n"
        f"👑 **Admin status:** {'✅ YES' if is_admin else '❌ NO (admin only commands จะไม่ทำงาน)'}\n"
        f"🔧 **ADMIN_ID configured:** `{ADMIN_ID}`"
    )
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=['plansdebug', 'tracdebug'])
def handle_plans_debug(message):
    """Admin: ตรวจ DB analysis_plans ตรงๆ — ดูว่า log + outcome ทำงานไหม"""
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        # ACK กลับไป กัน user งงว่าทำไมไม่ตอบ
        bot.reply_to(
            message,
            f"🔒 *คำสั่งนี้สำหรับ admin เท่านั้น*\n\n"
            f"Your chat_id: `{user_id}`\n"
            f"ADMIN_ID required: `{ADMIN_ID}`\n\n"
            f"_(ใช้ /whoami ดู info ตัวเอง)_",
            parse_mode="Markdown",
        )
        return
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        # 1. นับ outcome
        c.execute("SELECT outcome, COUNT(*) FROM analysis_plans GROUP BY outcome ORDER BY COUNT(*) DESC")
        outcome_rows = c.fetchall() or []
        # 2. ดู 5 rows ล่าสุด
        c.execute(
            "SELECT id, user_id, symbol, bias, outcome, issued_at, outcome_at "
            "FROM analysis_plans ORDER BY issued_at DESC LIMIT 5"
        )
        recent_rows = c.fetchall() or []
        # 3. นับ pending ที่ "พร้อม evaluate" แล้ว (>24h)
        c.execute(
            "SELECT COUNT(*) FROM analysis_plans "
            "WHERE outcome='open' AND issued_at < NOW() - INTERVAL '24 hours'"
        )
        ready_count = int((c.fetchone() or [0])[0] or 0)
        # 4. user สถิติของ admin (คุณเอง)
        c.execute(
            "SELECT total_analyses, streak_count, tiers_unlocked FROM users WHERE user_id=%s",
            (str(ADMIN_ID),),
        )
        admin_row = c.fetchone() or (0, 0, '')
        c.close()
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ DB error: {e}")
        return

    parts = ["📊 **Plans Debug**", ""]

    parts.append("**Outcome breakdown:**")
    if not outcome_rows:
        parts.append("  _(table ว่าง — ยังไม่เคยมี plan ถูก log)_")
    else:
        for outcome, cnt in outcome_rows:
            parts.append(f"  • `{outcome or 'NULL'}`: {cnt}")

    parts.append("")
    parts.append(f"**Ready to evaluate:** {ready_count} plans (open + อายุ > 24 ชม.)")
    parts.append("_(cron `check_plan_outcomes` รันที่ 6:00 Thai ทุกวัน)_")

    parts.append("")
    parts.append("**5 rows ล่าสุด:**")
    if not recent_rows:
        parts.append("  _(ไม่มีเลย — log_analysis_plan ไม่ทำงาน)_")
    else:
        for rid, uid, sym, bias, outcome, issued_at, outcome_at in recent_rows:
            issued_str = issued_at.strftime('%m-%d %H:%M') if hasattr(issued_at, 'strftime') else str(issued_at)[:16]
            parts.append(f"  • #{rid} {sym} ({bias}) `{outcome}` [{issued_str}] uid={uid}")

    parts.append("")
    parts.append("**Admin (คุณ) stats:**")
    parts.append(f"  • total_analyses: `{admin_row[0] or 0}`")
    parts.append(f"  • streak: `{admin_row[1] or 0}`")
    parts.append(f"  • tiers_unlocked: `{admin_row[2] or '(empty)'}`")

    parts.append("")
    parts.append("_💡 ถ้า table ว่าง → log_analysis_plan ไม่ทำงาน (ดู error log)_")
    parts.append("_💡 ถ้ามีแต่ outcome=open ทั้งหมด → รอ 24h+ + cron 6:00_")
    parts.append("_💡 ถ้า admin total_analyses=0 → restart bot รับ ALTER TABLE migration_")

    bot.reply_to(message, "\n".join(parts), parse_mode="Markdown")


@bot.message_handler(commands=['track', 'trackrecord'])
def handle_track_record(message):
    """แสดงสถิติ Track Record + leaderboard + hypothetical return"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    from database import (
        get_track_record_stats, get_top_performing_symbols, calculate_hypothetical_return,
        get_recent_wins,
    )
    s30 = get_track_record_stats(days=30)
    s90 = get_track_record_stats(days=90)
    top_symbols = get_top_performing_symbols(days=90, limit=5, min_plans=3)
    recent_wins = get_recent_wins(days=30, limit=5)
    hypo = calculate_hypothetical_return(days=90, risk_per_trade_pct=1.0)

    def fmt(s, label):
        if s["closed"] == 0:
            return f"*{label}:* ยังไม่มีข้อมูลพอ (เก็บสถิติเพิ่มอยู่)"
        no_entry_line = f" · 🚫 No-entry: {s.get('no_entry', 0)}" if s.get('no_entry', 0) > 0 else ""
        return (
            f"*{label}* ({s['closed']} entry-filled, {s['open']} เปิด){no_entry_line}\n"
            f"  ✅ Hit Rate (TP1/TP2): *{s['hit_rate_pct']:.1f}%*\n"
            f"  🎯 TP2 hit: {s['tp2_hit']} | TP1 hit: {s['tp1_hit']}\n"
            f"  🛑 SL hit: {s['sl_hit']} | ⏱ Expired: {s['expired']}"
        )

    parts = [
        "📊 **Apexify Track Record**",
        "_สถิติ Plans ที่ออกให้ PRO ตลอด 30/90 วัน_",
        "",
        fmt(s30, '30 วันที่ผ่านมา'),
        "",
        fmt(s90, '90 วันที่ผ่านมา'),
    ]

    # 🏆 Leaderboard — top 5 symbols
    if top_symbols:
        parts.extend(["", "🏆 *Top 5 หุ้นที่ Apexify ทำได้ดีสุด (90 วัน)*"])
        rank_emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, item in enumerate(top_symbols):
            emo = rank_emoji[i] if i < len(rank_emoji) else "•"
            parts.append(
                f"  {emo} *{item['symbol']}*: {item['wins']}/{item['closed']} hit "
                f"(*{item['hit_rate_pct']:.0f}%*)"
            )

    # 🔥 Recent Wins — 5 TP hits ล่าสุด (social proof + trust signal)
    if recent_wins:
        parts.extend(["", "🔥 *Recent Wins (30 วัน)*"])
        for w in recent_wins:
            tp_label = "TP2" if w["outcome"] == "tp2_hit" else "TP1"
            tp_emoji = "🎯🎯" if w["outcome"] == "tp2_hit" else "🎯"
            hold_str = f" · {w['hold_days']}d" if w.get("hold_days") is not None else ""
            gain_str = f"+{w['gain_pct']:.1f}%" if w.get("gain_pct") else ""
            parts.append(f"  {tp_emoji} *{w['symbol']}* {tp_label} hit {gain_str}{hold_str}")

    # 📈 Hypothetical return — simulated portfolio
    if hypo and hypo["total_plans"] >= 5:
        wins = hypo["win_count"]
        losses = hypo["loss_count"]
        total = hypo["total_plans"]
        ret = hypo["total_return_pct"]
        emoji = "🟢" if ret > 0 else "🔴" if ret < 0 else "⚪"
        parts.extend([
            "",
            "📈 *Hypothetical Return (90 วัน)*",
            f"  ถ้าตามทุก plan เสี่ยง 1% ต่อไม้:",
            f"  {emoji} รวม **{ret:+.1f}%** ใน {total} plans (ชนะ {wins} · แพ้ {losses})",
            f"  _หาก start 100,000฿ → ประมาณ {100000 * (1 + ret/100):,.0f}฿_",
        ])

    parts.extend([
        "",
        "💡 *วิธีนับ (Realistic — entry-filled-first):*",
        "• เริ่มนับเฉพาะ trade ที่ราคา **เข้า entry zone จริง** (limit buy filled)",
        "• 🚫 No-entry = ราคาไม่เคยลงไปแตะ entry zone → ไม่ได้เข้า trade → ไม่นับ hit/miss",
        "• ✅ TP1/TP2 hit = หลัง entry filled, ราคาแตะเป้า + ก่อน SL",
        "• 🛑 SL hit = ราคาแตะ SL หรือ same-day กับ TP → SL ชนะ (worst-case)",
        "• ⏱ Expired = เกิน 45 วันยังไม่ hit",
        "",
        "_📘 Hit Rate คิดจาก trade ที่เข้าได้จริง · ผลอนาคตอาจแตกต่าง · ไม่ใช่คำแนะนำลงทุน_",
    ])
    bot.reply_to(message, "\n".join(parts), parse_mode="Markdown")


# ==========================================
# 🌟 ระบบ Start & Referral
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    # 🌟 1. ดึงชื่อ Username หรือชื่อจริงจาก Telegram
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    
    if not full_name:
        full_name = message.from_user.username or f"User_{user_id[-4:]}"
    
    args = message.text.split()
    referred_welcome_bonus = False
    if len(args) > 1 and args[1].startswith('REF_'):
        referrer_id = args[1].replace('REF_', '')
        if referrer_id != user_id:
            try:
                success, milestone_hit = process_referral(referrer_id, user_id)
                if success:
                    referred_welcome_bonus = True
                    if milestone_hit:
                        new_count = get_referral_stats(referrer_id)
                        ref_role = check_subscription(referrer_id)
                        if ref_role == 'pro':
                            reward_text = "**PRO +10 วัน** เรียบร้อยแล้ว!"
                            next_text = "ชวนต่อทุก 3 คน = PRO +10 วัน 🚀"
                        else:
                            reward_text = "**VIP +10 วัน** เรียบร้อยแล้ว!"
                            next_text = "ชวนต่อทุก 3 คน = VIP +10 วัน 🚀"
                        bot.send_message(referrer_id,
                            f"🎉 **ยินดีด้วย! Milestone ครบ {new_count} คน!**\n\n"
                            f"🏆 คุณได้รับ {reward_text}\n{next_text}",
                            parse_mode="Markdown")
                    else:
                        ref_role_now = check_subscription(referrer_id)
                        current_count = get_referral_stats(referrer_id)
                        needed = 3 - (current_count % 3)
                        if ref_role_now == 'pro':
                            next_reward = f"PRO +10 วัน"
                        else:
                            next_reward = f"VIP +10 วัน"
                        bot.send_message(referrer_id,
                            f"🎁 มีเพื่อนสมัครผ่านลิงก์ของคุณแล้ว! ({current_count} คน)\n"
                            f"อีก {needed} คน รับ **{next_reward}** ฟรีครับ 🤝",
                            parse_mode="Markdown")
            except Exception as e:
                print(f"Referral logic error: {e}")
    
    # 🌟 2. ส่งชื่อเข้าไปเซฟใน Database
    register_user(user_id, full_name)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 วิเคราะห์หุ้น"), KeyboardButton("📱 เปิดเมนูหลัก"))
    markup.add(KeyboardButton("💎 บัญชี / VIP"), KeyboardButton("📖 คู่มือ /manual"))

    if user_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 แผงควบคุมแอดมิน"))

    welcome_text = (
        f"⚡️ ยินดีต้อนรับคุณ **{full_name}** สู่ **Apexify!**\n\n"
        "🤖 บอทวิเคราะห์หุ้นด้วย AI — รองรับหุ้นทั่วโลก, แจ้งเตือนสัญญาณเทคนิค, สรุปข่าวตลาดรายวัน\n\n"
        f"🎁 **ทดลองใช้ฟรี {FREE_DAILY_QUOTA} ครั้ง/วัน** ไม่ต้องสมัคร\n\n"
        "**เริ่มต้น 3 ขั้นตอน:**\n"
        "1️⃣ พิมพ์ชื่อหุ้น → รับรายงานวิเคราะห์ทันที\n"
        "   `AAPL` `TSLA` `NVDA` `PTT.BK` `AOT.BK`\n"
        "2️⃣ กด ⭐ ใต้รายงาน → เพิ่มเข้า Watchlist\n"
        "3️⃣ รับแจ้งเตือนสัญญาณ & ข่าวอัตโนมัติ\n\n"
        "👇 กด **📱 เปิดเมนูหลัก** เพื่อดูฟีเจอร์ทั้งหมด"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

    # 🌟 ขอข้อมูลผู้แนะนำ — เฉพาะ user ใหม่ที่ไม่ได้มากับลิงก์ REF_
    # PP P. case: เพื่อนส่งแคปหน้าจอ + URL ทำให้ referral หาย → กู้ผ่านฟอร์มนี้
    try:
        from database import has_pending_referral
        if not referred_welcome_bonus and not has_pending_referral(user_id):
            ref_markup = InlineKeyboardMarkup(row_width=2)
            ref_markup.add(
                InlineKeyboardButton("✋ มาเอง", callback_data="referral_self"),
                InlineKeyboardButton("👥 มีเพื่อนแนะนำ", callback_data="referral_friend"),
            )
            bot.send_message(
                int(user_id),
                "🤝 **มีเพื่อนแนะนำ Apexify ให้คุณไหมครับ?**\n\n"
                "ถ้ามี เพื่อนของคุณจะได้รับ VIP +10 วัน เป็นรางวัลขอบคุณ\n"
                "(ระบบจะถามชื่อ/Telegram ID ของเพื่อน)",
                parse_mode="Markdown",
                reply_markup=ref_markup,
            )
    except Exception as e:
        print(f"[ReferralCapture] ask error: {e}", flush=True)

    # 🌟 Referral welcome bonus — แจ้ง new user ว่าได้ VIP 3 วันฟรี
    if referred_welcome_bonus:
        try:
            bot.send_message(user_id,
                "🎁 **โบนัสต้อนรับ!**\n\n"
                "คุณสมัครผ่านลิงก์ชวนเพื่อน\n"
                "✨ **รับ VIP 3 วันฟรี** เรียบร้อยแล้ว!\n\n"
                "💎 ใช้งานได้เต็มรูปแบบ:\n"
                "• วิเคราะห์ไม่จำกัด + กราฟเทคนิค\n"
                "• Apexify Trend Radar 3 ระยะ\n"
                "• Morning Briefing + Digest News\n\n"
                "_ลองพิมพ์ชื่อหุ้นใดๆ เช่น `AAPL` เพื่อเริ่มทดลองเลยครับ!_",
                parse_mode="Markdown")
        except Exception as e:
            print(f"[ReferralWelcome] error: {e}", flush=True)

    # Tutorial card with inline keyboard
    tutorial_markup = InlineKeyboardMarkup(row_width=2)
    # 🎁 Surface /freetrial as primary CTA — fix 96% activation gap
    tutorial_markup.add(
        InlineKeyboardButton("🎁 ทดลอง PRO ฟรี 7 วัน — เริ่มเลย!", callback_data="trigger_freetrial")
    )
    tutorial_markup.add(
        InlineKeyboardButton("📊 ลอง AAPL", callback_data="tutorial_analyze_AAPL"),
        InlineKeyboardButton("⚡ ลอง NVDA", callback_data="tutorial_analyze_NVDA"),
    )
    tutorial_markup.add(InlineKeyboardButton("🇹🇭 ลอง PTT.BK", callback_data="tutorial_analyze_PTT.BK"))
    tutorial_markup.add(InlineKeyboardButton("📱 เปิดเมนูหลัก", callback_data="hub_home"))
    _, login_url, _ = issue_dashboard_login_url(user_id)
    if login_url:
        tutorial_markup.add(InlineKeyboardButton("🌐 Web Dashboard", url=login_url))
    bot.send_message(
        user_id,
        "🚀 **เริ่มต้นได้เลยครับ!**\n\nกดปุ่มด้านล่างเพื่อทดลองวิเคราะห์หุ้น หรือเปิดฟีเจอร์ที่ต้องการ 👇",
        reply_markup=tutorial_markup,
        parse_mode="Markdown",
    )

# ==========================================
# 🌟 ระบบบันทึกและดูพอร์ตลงทุน (Apex Wealth Master)
# ==========================================
@bot.message_handler(commands=['add'])
def handle_add_stock(message):
    """คำสั่งเพิ่มหุ้น เช่น /add AAPL 10 150"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    try:
        parts = message.text.split()
        if len(parts) != 4:
            # Push dashboard — easier than typing syntax
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 เพิ่มหุ้นบน Dashboard (ง่ายกว่า)", src="add_err", next_path="/")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(message,
                "❌ รูปแบบผิด!\n"
                "• พิมพ์: `/add [ชื่อหุ้น] [จำนวน] [ราคาเฉลี่ย]`\n"
                "  เช่น: `/add AAPL 10 150`\n\n"
                "💡 หรือทำผ่าน Dashboard ง่ายกว่า ↓",
                parse_mode='Markdown', reply_markup=kb if _dash_btn else None)
            return
        
        ticker = parts[1].upper()
        shares = float(parts[2])
        cost = float(parts[3])

        existing = get_user_portfolio(user_id)
        if any(p['ticker'] == ticker for p in existing):
            bot.reply_to(
                message,
                f"⚠️ **{ticker}** มีอยู่ในพอร์ตแล้ว\n"
                f"• แก้จำนวน/ต้นทุน: `/edit {ticker} [จำนวน] [ราคาเฉลี่ย]`\n"
                f"• ลบทิ้ง: `/del {ticker}`",
                parse_mode='Markdown',
            )
            return

        role = check_subscription(user_id)
        if user_id != ADMIN_ID:
            portfolio_count = len(existing)
            if role == 'free' and portfolio_count >= 3:
                bot.reply_to(message, "🔒 **จำกัดพอร์ต 3 หุ้น (Free)**\nอัปเกรดเป็น **VIP** เพื่อเพิ่มได้ถึง 10 ตัว หรือ **PRO** ไม่จำกัดครับ!", parse_mode='Markdown')
                return
            elif role == 'vip' and portfolio_count >= 10:
                bot.reply_to(message, "🔒 **จำกัดพอร์ต 10 หุ้น (VIP)**\nอัปเกรดเป็น **PRO** เพื่อเพิ่มหุ้นได้ไม่จำกัดครับ! 👑", parse_mode='Markdown')
                return

        # 🌟 ดึงชื่อเพื่อบันทึกลง DB ด้วย
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip() or message.from_user.username or f"User_{user_id[-4:]}"
        
        # มั่นใจว่ามีรหัสในฐานข้อมูลก่อน
        register_user(user_id, full_name)
        
        # บันทึกหุ้นลงฐานข้อมูล
        add_portfolio_stock(user_id, ticker, shares, cost)

        bot.reply_to(message, f"✅ เพิ่มหุ้น **{ticker}** จำนวน {shares} หุ้น (ต้นทุน ${cost}) ลงในพอร์ตเรียบร้อยแล้ว!\nพิมพ์ `/portfolio` หรือเปิดเมนูเพื่อดูพอร์ตในหน้า Web Dashboard ได้เลยครับ", parse_mode='Markdown')

        # 🎁 One-shot Free portfolio audit — fires once per user when they hit
        # 3+ stocks. Runs in a background thread so /add reply isn't delayed.
        try:
            from database import is_first_audit_done, mark_first_audit_done
            if not is_first_audit_done(user_id):
                portfolio_count = len(get_user_portfolio(user_id))
                if portfolio_count >= 3:
                    def _audit_thread():
                        try:
                            from portfolio_audit import run_free_audit
                            audit_msg = run_free_audit(user_id)
                            if audit_msg:
                                bot.send_message(int(user_id), audit_msg, parse_mode="Markdown")
                                mark_first_audit_done(user_id)
                        except Exception as audit_err:
                            print(f"[FreeAudit] {audit_err}", flush=True)
                    threading.Thread(target=_audit_thread, daemon=True).start()
        except Exception as audit_err:
            print(f"[FreeAudit-trigger] {audit_err}", flush=True)

    except ValueError:
        bot.reply_to(message, "❌ จำนวนหุ้นและราคาต้องเป็นตัวเลขเท่านั้นครับ!")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")

@bot.message_handler(commands=['del', 'remove'])
def handle_del_stock(message):
    """ลบหุ้นออกจากพอร์ต — /del [ticker]"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 ลบหุ้นบน Dashboard (ง่ายกว่า)", src="del_err", next_path="/")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "❌ รูปแบบผิด! พิมพ์: `/del [ชื่อหุ้น]`\nเช่น: `/del AAPL`\n\n💡 หรือทำผ่าน Dashboard ↓",
                parse_mode='Markdown', reply_markup=kb if _dash_btn else None,
            )
            return

        ticker = parts[1].upper()
        removed = delete_portfolio_stock(user_id, ticker)
        if not removed:
            bot.reply_to(
                message,
                f"ℹ️ ไม่พบ **{ticker}** ในพอร์ตของคุณ\nพิมพ์ `/portfolio` เพื่อดูรายการที่มีอยู่ครับ",
                parse_mode='Markdown',
            )
            return

        bot.reply_to(
            message,
            f"🗑️ ลบ **{ticker}** ออกจากพอร์ตเรียบร้อยแล้วครับ",
            parse_mode='Markdown',
        )
    except Exception as e:
        print(f"[BotError /del] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")


@bot.message_handler(commands=['edit'])
def handle_edit_stock(message):
    """แก้จำนวน/ราคาเฉลี่ยของหุ้นในพอร์ต — /edit [ticker] [shares] [cost]"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    try:
        parts = message.text.split()
        if len(parts) != 4:
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 แก้พอร์ตบน Dashboard (ง่ายกว่า)", src="edit_err", next_path="/")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "❌ รูปแบบผิด! พิมพ์: `/edit [ชื่อหุ้น] [จำนวน] [ราคาเฉลี่ย]`\nเช่น: `/edit AAPL 15 165`\n\n💡 หรือทำผ่าน Dashboard ↓",
                parse_mode='Markdown', reply_markup=kb if _dash_btn else None,
            )
            return

        ticker = parts[1].upper()
        shares = float(parts[2])
        cost = float(parts[3])

        updated = update_portfolio_stock(user_id, ticker, shares, cost)
        if not updated:
            bot.reply_to(
                message,
                f"ℹ️ ไม่พบ **{ticker}** ในพอร์ต\nใช้ `/add {ticker} {shares} {cost}` เพื่อเพิ่มใหม่ครับ",
                parse_mode='Markdown',
            )
            return

        bot.reply_to(
            message,
            f"✏️ อัปเดต **{ticker}** เป็น {shares} หุ้น (ต้นทุน ${cost}) เรียบร้อยแล้วครับ",
            parse_mode='Markdown',
        )
    except ValueError:
        bot.reply_to(message, "❌ จำนวนหุ้นและราคาต้องเป็นตัวเลขเท่านั้นครับ!")
    except Exception as e:
        print(f"[BotError /edit] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")


@bot.message_handler(commands=['watch'])
def handle_watch(message):
    """เพิ่มหุ้นเข้า Watchlist — /watch [ticker]"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 จัดการ Watchlist บน Dashboard", src="watch_err", next_path="/watchlist")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "❌ รูปแบบผิด! พิมพ์: `/watch [ชื่อหุ้น]`\nเช่น: `/watch AAPL`\n\n💡 หรือทำผ่าน Dashboard ↓",
                parse_mode='Markdown', reply_markup=kb if _dash_btn else None,
            )
            return

        symbol = parts[1].upper()
        role = check_subscription(user_id)
        current_watch = len(get_user_watch(user_id))
        if user_id != ADMIN_ID:
            if role == 'free' and current_watch >= 3:
                bot.reply_to(message, "🔒 **จำกัด Watchlist 3 ตัว (Free)**\nอัปเกรดเป็น **VIP** เพื่อเพิ่มได้ถึง 10 ตัว หรือ **PRO** ไม่จำกัดครับ!", parse_mode='Markdown')
                return
            elif role == 'vip' and current_watch >= 10:
                bot.reply_to(message, "🔒 **จำกัด Watchlist 10 ตัว (VIP)**\nอัปเกรดเป็น **PRO** เพื่อเพิ่มได้ไม่จำกัดครับ! 👑", parse_mode='Markdown')
                return

        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = f"{first_name} {last_name}".strip() or message.from_user.username or f"User_{user_id[-4:]}"
        register_user(user_id, full_name)

        if add_watch(user_id, symbol):
            bot.reply_to(message, f"✅ เพิ่ม **{symbol}** เข้า Watchlist แล้วครับ", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"⚠️ **{symbol}** มีอยู่ใน Watchlist แล้วครับ", parse_mode='Markdown')
    except Exception as e:
        print(f"[BotError /watch] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")


@bot.message_handler(commands=['unwatch'])
def handle_unwatch(message):
    """ลบหุ้นออกจาก Watchlist — /unwatch [ticker]"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 จัดการ Watchlist บน Dashboard", src="unwatch_err", next_path="/watchlist")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "❌ รูปแบบผิด! พิมพ์: `/unwatch [ชื่อหุ้น]`\nเช่น: `/unwatch AAPL`\n\n💡 หรือทำผ่าน Dashboard ↓",
                parse_mode='Markdown', reply_markup=kb if _dash_btn else None,
            )
            return

        symbol = parts[1].upper()
        existing = get_user_watch(user_id)
        if symbol not in existing:
            bot.reply_to(
                message,
                f"ℹ️ ไม่พบ **{symbol}** ใน Watchlist\nพิมพ์ `/portfolio` หรือเปิดเมนู Watchlist เพื่อดูรายการที่มีอยู่ครับ",
                parse_mode='Markdown',
            )
            return

        remove_watch_db(user_id, symbol)
        bot.reply_to(message, f"🗑️ ลบ **{symbol}** ออกจาก Watchlist แล้วครับ", parse_mode='Markdown')
    except Exception as e:
        print(f"[BotError /unwatch] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")


# ==========================================
# 🌟 ระบบบันทึกและดูพอร์ตลงทุน (แก้บั๊ก Telegram Markdown)
# ==========================================
@bot.message_handler(commands=['portfolio', 'port'])
def handle_portfolio(message):
    """คำสั่งเช็คพอร์ตผ่านแชท"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    processing_msg = bot.reply_to(message, "⏳ กำลังดึงข้อมูลพอร์ตและราคาล่าสุดจากตลาด...")
    try:
        portfolio = get_user_portfolio(user_id)
        if not portfolio:
            bot.edit_message_text("📊 พอร์ตลงทุนของคุณยังว่างเปล่า\nพิมพ์ <code>/add [ชื่อหุ้น] [จำนวน] [ราคาเฉลี่ย]</code> เพื่อเพิ่มหุ้นเข้าพอร์ตครับ", chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode='HTML')
            return
        
        total_invested = 0
        current_value = 0
        
        rows = []
        for asset in portfolio:
            ticker = asset['ticker']
            shares = asset['shares']
            avg_cost = asset['avg_cost']

            try:
                allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
                clean_ticker = ticker.replace(".", "-") if "." in ticker and not ticker.endswith(allowed_suffixes) else ticker
                live_price = float(yf.Ticker(clean_ticker).fast_info.last_price)
            except Exception:
                live_price = avg_cost

            invested = shares * avg_cost
            current = shares * live_price
            profit = current - invested
            profit_pct = (profit / invested * 100) if invested > 0 else 0

            total_invested += invested
            current_value += current
            rows.append((ticker, shares, avg_cost, live_price, profit, profit_pct))

        total_profit = current_value - total_invested
        total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
        total_icon = "🟢" if total_profit >= 0 else "🔴"

        # 💰 Cash balance + Total NAV — requested by nuttapon (Annual PRO) 2026-05-16
        cash_balance = get_user_cash_balance(user_id)
        total_nav = current_value + cash_balance

        lines = [f"💼 <b>พอร์ตลงทุน</b>  ({len(rows)} หลักทรัพย์)\n"]
        for ticker, shares, avg_cost, live_price, profit, profit_pct in rows:
            icon = "🟢" if profit >= 0 else "🔴"
            sign = "+" if profit >= 0 else ""
            lines.append(
                f"{icon} <b>{ticker}</b>  {shares:,.4g} หุ้น\n"
                f"   ทุน {avg_cost:,.2f}  →  ล่าสุด {live_price:,.2f}\n"
                f"   {sign}{profit:,.2f}  ({sign}{profit_pct:.2f}%)\n"
            )

        summary_lines = [
            f"─────────────────────",
            f"💼 <b>มูลค่าหุ้น:</b> {current_value:,.2f}",
            f"💵 <b>ต้นทุนรวม:</b> {total_invested:,.2f}",
        ]
        if cash_balance > 0:
            summary_lines.extend([
                f"💰 <b>เงินสด:</b> {cash_balance:,.2f}",
                f"🏦 <b>NAV รวม:</b> {total_nav:,.2f}",
            ])
        else:
            summary_lines.append(
                f"💰 <b>เงินสด:</b> 0.00  <i>(ตั้งค่าด้วย /setcash)</i>"
            )
        summary_lines.append(
            f"{total_icon} <b>กำไร/ขาดทุนรวม:</b> {'+' if total_profit >= 0 else ''}{total_profit:,.2f}  ({'+' if total_profit_pct >= 0 else ''}{total_profit_pct:.2f}%)"
        )
        lines.append("\n".join(summary_lines))

        msg = "\n".join(lines)
        port_markup = InlineKeyboardMarkup()
        _port_btn = _dashboard_cta_button(user_id, "📊 ดูพอร์ต + chart บน Dashboard", src="portfolio_cmd", next_path="/")
        if _port_btn:
            port_markup.add(_port_btn)
        bot.edit_message_text(msg, chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode='HTML', reply_markup=port_markup)

    except Exception as e:
        print(f"[user_history] {e}", flush=True)
        bot.edit_message_text(friendly_error("ดึงข้อมูลผู้ใช้ไม่สำเร็จ"), chat_id=message.chat.id, message_id=processing_msg.message_id)


# 💰 /editcash — edit cash balance for NAV calculation (PRO+VIP)
# Requested by nuttapon (Annual PRO #1) 2026-05-16
# Single command with 3 modes via prefix:
#   /editcash 5000   → set to $5,000
#   /editcash +1000  → deposit $1,000 (add to current)
#   /editcash -500   → withdraw $500 (subtract from current, min 0)
#   /editcash        → show current balance + recent history
# (setcash kept as alias for backwards compat)
@bot.message_handler(commands=['editcash', 'setcash'])
def handle_editcash(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return

    role = (check_subscription(user_id) or 'free').lower()
    if role not in ('pro', 'vip', 'admin'):
        bot.reply_to(
            message,
            "💰 <b>เงินสดในพอร์ต (Cash Balance)</b>\n\n"
            "ฟีเจอร์นี้สำหรับ <b>VIP / PRO</b> เท่านั้น\n"
            "เพื่อคำนวณ NAV รวม (มูลค่าหุ้น + เงินสด)\n\n"
            "🚀 อัพเกรดที่ /upgrade",
            parse_mode='HTML',
        )
        return

    parts = (message.text or '').split(maxsplit=1)

    # No args → show current + recent history + usage
    if len(parts) < 2:
        cur = get_user_cash_balance(user_id)
        history = get_cash_transactions(user_id, limit=5)

        history_lines = []
        if history:
            history_lines.append("\n📜 <b>ประวัติล่าสุด:</b>")
            for h in history:
                action_emoji = {'deposit': '➕', 'withdraw': '➖', 'set': '🔄'}.get(h['action_type'], '•')
                delta_sign = '+' if h['delta'] >= 0 else ''
                action_th = {'deposit': 'ฝากเข้า', 'withdraw': 'ถอนออก', 'set': 'ตั้งใหม่'}.get(h['action_type'], h['action_type'])
                # parse ISO date
                date_str = h['created_at'][:10] if h.get('created_at') else '?'
                history_lines.append(
                    f"  {action_emoji} {action_th} <code>{delta_sign}${h['delta']:,.2f}</code> → <b>${h['balance_after']:,.2f}</b> <i>({date_str})</i>"
                )

        bot.reply_to(
            message,
            f"💰 <b>เงินสดปัจจุบัน:</b> ${cur:,.2f}\n"
            + "\n".join(history_lines)
            + f"\n\n<b>วิธีใช้:</b>\n"
            f"<code>/editcash 5000</code>      — ตั้งเงินสด $5,000\n"
            f"<code>/editcash +1000</code>     — ฝากเข้า $1,000\n"
            f"<code>/editcash -500</code>      — ถอนออก $500\n\n"
            f"<i>หน่วย USD · นำไปรวมกับมูลค่าหุ้นใน /port เพื่อคำนวณ NAV</i>",
            parse_mode='HTML',
        )
        return

    # Parse arg with action prefix
    arg_raw = parts[1].strip().replace(',', '').replace('$', '').replace(' ', '')
    try:
        if arg_raw.startswith('+'):
            action_type = 'deposit'
            amount = float(arg_raw[1:])
        elif arg_raw.startswith('-'):
            action_type = 'withdraw'
            amount = float(arg_raw[1:])
        else:
            action_type = 'set'
            amount = float(arg_raw)
        if amount < 0:
            raise ValueError("amount must be >= 0")
    except (ValueError, AttributeError):
        bot.reply_to(
            message,
            "❌ รูปแบบไม่ถูกต้อง\n\n"
            "<b>ตัวอย่าง:</b>\n"
            "<code>/editcash 5000</code>    — ตั้งใหม่\n"
            "<code>/editcash +1000</code>   — ฝากเข้า\n"
            "<code>/editcash -500</code>    — ถอนออก",
            parse_mode='HTML',
        )
        return

    result = apply_cash_action(user_id, action_type, amount, note='via telegram')
    if not result.get('ok'):
        bot.reply_to(message, friendly_error(result.get('error') or "ตั้งค่าเงินสดไม่สำเร็จ"))
        return

    before = result['balance_before']
    after = result['balance_after']
    delta = result['delta']

    if action_type == 'set':
        bot.reply_to(
            message,
            f"✅ <b>ตั้งเงินสดใหม่</b>\n"
            f"💰 ${before:,.2f} → <b>${after:,.2f}</b>\n\n"
            f"ดู NAV รวมได้ใน /port",
            parse_mode='HTML',
        )
    elif action_type == 'deposit':
        bot.reply_to(
            message,
            f"➕ <b>ฝากเข้า $+{amount:,.2f}</b>\n"
            f"💰 ${before:,.2f} → <b>${after:,.2f}</b>\n\n"
            f"ดู NAV รวมได้ใน /port",
            parse_mode='HTML',
        )
    else:  # withdraw
        actual_withdrawn = abs(delta)
        capped_note = ""
        if actual_withdrawn < amount:
            capped_note = f"\n<i>⚠️ ลดเหลือ ${actual_withdrawn:,.2f} (เงินสดติดลบไม่ได้)</i>"
        bot.reply_to(
            message,
            f"➖ <b>ถอนออก ${actual_withdrawn:,.2f}</b>{capped_note}\n"
            f"💰 ${before:,.2f} → <b>${after:,.2f}</b>\n\n"
            f"ดู NAV รวมได้ใน /port",
            parse_mode='HTML',
        )


def _handle_pnl_all(message):
    """Portfolio-wide PnL card — sums all holdings into one shareable image."""
    user_id = str(message.chat.id)
    username = message.from_user.username or message.from_user.first_name or f"User_{user_id[-4:]}"

    portfolio = get_user_portfolio(user_id)
    if not portfolio:
        bot.reply_to(
            message,
            "📊 พอร์ตของคุณยังว่างเปล่า\n"
            "พิมพ์ <code>/add [หุ้น] [จำนวน] [ราคา]</code> เพื่อเริ่มบันทึกพอร์ตก่อนครับ",
            parse_mode='HTML',
        )
        return

    if len(portfolio) > 30:
        bot.reply_to(message, "⚠️ พอร์ตคุณมีหุ้นมากเกินไป (>30) — ลด lottos เกินจำเป็นก่อนครับ")
        return

    wait_msg = bot.reply_to(message, "🎨 กำลังสร้างการ์ดสรุปพอร์ตทั้งหมด...")

    try:
        import yfinance as yf
        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")

        # Fetch live prices for every ticker via fast_info — sub-second per stock
        holdings = []
        for p in portfolio:
            ticker = p['ticker']
            clean = ticker.replace(".", "-") if "." in ticker and not ticker.endswith(allowed_suffixes) else ticker
            try:
                fi = yf.Ticker(clean).fast_info
                price = float(fi.get('lastPrice') if hasattr(fi, 'get') else getattr(fi, 'last_price', 0) or 0)
            except Exception:
                price = 0.0
            if price <= 0:
                continue
            cost = p['shares'] * p['avg_cost']
            value = p['shares'] * price
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0
            holdings.append({
                'ticker': ticker,
                'shares': p['shares'],
                'avg_cost': p['avg_cost'],
                'price': price,
                'value': value,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
            })

        if not holdings:
            bot.edit_message_text(
                "📡 ดึงราคาหุ้นในพอร์ตไม่สำเร็จ — ลองอีกครั้งใน 1 นาทีนะครับ",
                message.chat.id, wait_msg.message_id,
            )
            return

        total_value = sum(h['value'] for h in holdings)
        total_cost = sum(h['cost'] if 'cost' in h else h['shares'] * h['avg_cost'] for h in holdings)

        # THB rate (best-effort)
        thb_value = None
        try:
            fx = yf.Ticker("THB=X").fast_info
            rate = float(fx.get('lastPrice') if hasattr(fx, 'get') else getattr(fx, 'last_price', 0) or 0)
            if rate > 0:
                thb_value = total_value * rate
        except Exception:
            pass

        from pnl_generator import generate_portfolio_pnl_card
        image_bytes = generate_portfolio_pnl_card(
            username=username,
            holdings=holdings,
            total_value=total_value,
            total_cost=total_cost,
            thb_value=thb_value,
        )

        total_pnl_pct = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0
        emoji = "🟢" if total_pnl_pct >= 0 else "🔴"
        sign = "+" if total_pnl_pct >= 0 else ""

        # Personalized share URL — same flow as single-ticker /pnl
        from urllib.parse import quote
        from config import DASHBOARD_BASE_URL
        base = (DASHBOARD_BASE_URL or "https://apexifyy.up.railway.app").rstrip("/")
        share_user = quote(username[:24])
        share_url = (
            f"{base}/pnl-share?t=PORTFOLIO&p={total_pnl_pct:.2f}&u={share_user}&bot=REF_{user_id}"
        )

        caption = (
            f"📊 <b>พอร์ตของผม</b> · {len(holdings)} หุ้น · ${total_value:,.0f}\n"
            f"{emoji} P&L รวม: <b>{sign}{total_pnl_pct:.2f}%</b>\n\n"
            f"ตามไปดูใครก็ทำได้แบบนี้ — ใช้ <b>Apexify Trading AI</b> ช่วยสแกน + เตือน 24 ชม. 🤖✨\n\n"
            f"🔗 https://t.me/Apexify_Trading_Bot?start=REF_{user_id}"
        )

        share_markup = InlineKeyboardMarkup()
        share_markup.add(
            InlineKeyboardButton("📤 แชร์ลิงก์ (preview สวย)", url=share_url),
        )

        bot.send_photo(
            message.chat.id,
            photo=image_bytes,
            caption=caption,
            parse_mode='HTML',
            reply_markup=share_markup,
        )
        try:
            bot.delete_message(message.chat.id, wait_msg.message_id)
        except Exception:
            pass

    except Exception as e:
        print(f"[/pnl all] {e}", flush=True)
        from bot_utils import alert_admin_error
        alert_admin_error(bot, "/pnl all", e, user_id=user_id)
        try:
            bot.edit_message_text(
                friendly_error("สร้างการ์ดพอร์ตไม่สำเร็จ"),
                message.chat.id, wait_msg.message_id,
            )
        except Exception:
            pass


@bot.message_handler(commands=['pnl'])
def handle_pnl_card(message):
    """คำสั่ง /pnl [ชื่อหุ้น] หรือ /pnl all เพื่อสร้างการ์ดอวดกำไร"""
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ กรุณาพิมพ์ชื่อหุ้นด้วยครับ\n"
            "<code>/pnl NVDA</code> — การ์ดของหุ้นเดียว\n"
            "<code>/pnl all</code> — การ์ดสรุปทั้งพอร์ต ⭐",
            parse_mode='HTML',
        )
        return

    # /pnl all → portfolio-wide card
    if parts[1].lower() == "all":
        _handle_pnl_all(message)
        return

    ticker = parts[1].upper()
    user_id = str(message.chat.id)
    username = message.from_user.username or message.from_user.first_name
    
    from database import get_connection
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        user_row = c.fetchone()
        
        if not user_row:
            bot.reply_to(message, "⚠️ คุณยังไม่ได้ลงทะเบียนในระบบครับ พิมพ์ /start เพื่อลงทะเบียน")
            return
            
        c.execute("SELECT avg_cost FROM portfolios WHERE user_id = %s AND ticker = %s", (user_id, ticker))
        port_row = c.fetchone()
        
        if not port_row:
            bot.reply_to(message, f"❌ ไม่พบหุ้น <b>{ticker}</b> ในพอร์ตของคุณครับ\n<i>(พิมพ์ <code>/add {ticker} [จำนวน] [ราคา]</code> เพื่อเพิ่มเข้าพอร์ตก่อน)</i>", parse_mode='HTML')
            return
            
        entry_price = float(port_row[0])
        wait_msg = bot.reply_to(message, "🎨 กำลังสร้างการ์ด PnL ระดับ Pro ให้คุณ...")
        
        import yfinance as yf
        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
        clean_ticker = ticker.replace(".", "-") if "." in ticker and not ticker.endswith(allowed_suffixes) else ticker
        
        ticker_yf = yf.Ticker(clean_ticker)
        current_price = float(ticker_yf.fast_info['lastPrice'])
        
        # วาดรูปการ์ด
        from pnl_generator import generate_pnl_card
        image_bytes = generate_pnl_card(username, ticker, entry_price, current_price)

        # คำนวณ % สำหรับ share URL — Personalized OG image
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        from urllib.parse import quote
        share_user = quote((username or "Trader")[:24])
        # DASHBOARD_BASE_URL might not have trailing slash — strip & rebuild
        from config import DASHBOARD_BASE_URL
        base = (DASHBOARD_BASE_URL or "https://apexifyy.up.railway.app").rstrip("/")
        share_url = (
            f"{base}/pnl-share?t={ticker}&p={pnl_pct:.2f}&u={share_user}&bot=REF_{user_id}"
        )

        # สร้างแคปชั่นพร้อมแนบลิงก์ Referral ของคนกด
        pnl_caption = (
            f"ตลาดจะผันผวนแค่ไหนก็ไม่หวั่น ถ้ามีผู้ช่วยส่วนตัวดีๆ 🤖✨ "
            f"ผลประกอบการ <b>{ticker}</b> รอบนี้บวกมาสวยๆ ขอบคุณ <b>Apexify Trading AI</b> "
            f"ที่ช่วยสแกนหาจุดเข้าและคอยเตือนตลอด 24 ชม. ใครอยากเทรดสบายขึ้นแบบนี้ มากดลองใช้ฟรีได้เลย! 👇\n\n"
            f"🔗 ลิงก์บอท: https://t.me/Apexify_Trading_Bot?start=REF_{user_id}"
        )

        # Inline button: "share link with auto-rendered OG card preview"
        share_markup = InlineKeyboardMarkup()
        share_markup.add(
            InlineKeyboardButton("📤 แชร์ลิงก์ (preview สวย)", url=share_url),
        )

        # ส่งรูปลงแชท
        bot.send_photo(
            message.chat.id,
            photo=image_bytes,
            caption=pnl_caption,
            parse_mode='HTML',
            reply_markup=share_markup,
        )
        bot.delete_message(message.chat.id, wait_msg.message_id)
        
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")
        print(f"PnL Error: {e}") 
    finally:
        c.close()
        conn.close()

# ==========================================
# 🌟 ระบบคำสั่งตั้งเตือนราคาส่วนตัว
# ==========================================
@bot.message_handler(commands=['setalert'])
def handle_set_alert(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    role = check_subscription(user_id)
    if role != 'pro' and user_id != ADMIN_ID:
        bot.reply_to(message, "🔒 **ฟีเจอร์ระดับพรีเมียม (PRO Exclusive)**\nการตั้งเตือนราคาส่วนตัวสงวนสิทธิ์ให้ลูกค้าระดับ PRO เท่านั้นครับ กรุณาอัปเกรดเพื่อใช้งาน 👑", parse_mode="Markdown")
        return
        
    try:
        args = message.text.split()

        # 🎯 Guided UX — ถ้าพิมพ์ /setalert ไม่มี args หรือ args เดียว (symbol only)
        # → แสดงปุ่มเลือกหุ้น/เปอร์เซ็นต์ แทน error message
        # User feedback: 3 users/30 วันใช้ feature → guided form กัน drop-off จาก syntax error
        if len(args) == 1:
            kb = InlineKeyboardMarkup(row_width=3)
            popular = ["NVDA", "AAPL", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "PLTR"]
            for i in range(0, len(popular), 3):
                kb.add(*[InlineKeyboardButton(sym, callback_data=f"setalert_pick_{sym}") for sym in popular[i:i+3]])
            thai_stocks = ["PTT.BK", "KBANK.BK", "AOT.BK"]
            kb.add(*[InlineKeyboardButton(sym, callback_data=f"setalert_pick_{sym}") for sym in thai_stocks])
            # เพิ่ม dashboard CTA — push คนไปทำผ่านเว็บ
            _dash_btn = _dashboard_cta_button(user_id, "🌐 จัดการ Alerts บน Dashboard", src="setalert_guided", next_path="/alerts")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "🔔 *ตั้งเตือนราคา — เลือกหุ้น*\n\n"
                "กดปุ่มข้างล่าง หรือพิมพ์เอง:\n"
                "• `/setalert AAPL 180` — ระบุราคาเป้าหมาย\n"
                "• `/setalert AAPL +5%` — เพิ่มขึ้น 5%\n"
                "• `/setalert AAPL -3%` — ลดลง 3%",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        if len(args) == 2:
            # /setalert SYMBOL → show pct picker
            symbol_guess = args[1].upper()
            tech_data, _, _ = _get_cached_analysis(symbol_guess, generate_chart=False)
            if not tech_data:
                bot.reply_to(message, f"❌ ไม่พบ **{symbol_guess}** — ลองพิมพ์ symbol ใหม่หรือเติม `.BK` สำหรับหุ้นไทย", parse_mode="Markdown")
                return
            current_price = tech_data['price']
            kb = InlineKeyboardMarkup(row_width=3)
            kb.add(
                InlineKeyboardButton("📈 +5%", callback_data=f"setalert_pct_{symbol_guess}_5"),
                InlineKeyboardButton("📈 +10%", callback_data=f"setalert_pct_{symbol_guess}_10"),
                InlineKeyboardButton("📈 +20%", callback_data=f"setalert_pct_{symbol_guess}_20"),
            )
            kb.add(
                InlineKeyboardButton("📉 -5%", callback_data=f"setalert_pct_{symbol_guess}_-5"),
                InlineKeyboardButton("📉 -10%", callback_data=f"setalert_pct_{symbol_guess}_-10"),
                InlineKeyboardButton("📉 -20%", callback_data=f"setalert_pct_{symbol_guess}_-20"),
            )
            bot.reply_to(
                message,
                f"🔔 *{symbol_guess}* — ราคาปัจจุบัน **${current_price:,.2f}**\n\n"
                f"เลือกเปอร์เซ็นต์เพื่อตั้งเตือน:\n"
                f"หรือพิมพ์ราคาเอง: `/setalert {symbol_guess} 180`",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        if len(args) != 3:
            bot.reply_to(message, "❌ รูปแบบผิด!\n**วิธีใช้:**\n• `/setalert AAPL 180` — ระบุราคาเป้าหมาย\n• `/setalert AAPL +5%` — เพิ่มขึ้น 5% จากราคาปัจจุบัน\n• `/setalert AAPL -3%` — ลดลง 3% จากราคาปัจจุบัน", parse_mode="Markdown")
            return

        symbol = args[1].upper()
        raw_target = args[2]

        load_msg = bot.reply_to(message, f"⏳ กำลังตรวจสอบราคาปัจจุบันของ {symbol}...")
        tech_data, _, err = _get_cached_analysis(symbol, generate_chart=False)

        if err or not tech_data:
            bot.edit_message_text(f"❌ ไม่พบข้อมูลหุ้น **{symbol}**\n\n💡 **คำแนะนำ:**\nหากเป็นหุ้นไทย กรุณาเติม `.BK` ต่อท้ายด้วยครับ เช่น `PTT.BK`, `KBANK.BK`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
            return

        current_price = tech_data['price']

        if raw_target.endswith('%'):
            try:
                pct = float(raw_target.rstrip('%'))
                target_price = round(current_price * (1 + pct / 100), 4)
                pct_label = f" ({raw_target} จาก {current_price:,.2f})"
            except ValueError:
                bot.edit_message_text("❌ รูปแบบเปอร์เซ็นต์ไม่ถูกต้อง เช่น `+5%` หรือ `-3%`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
                return
        else:
            try:
                target_price = float(raw_target)
                pct_label = ""
            except ValueError:
                bot.edit_message_text("❌ ราคาต้องเป็นตัวเลขหรือเปอร์เซ็นต์ เช่น `180` หรือ `+5%`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
                return

        condition = 'above' if target_price > current_price else 'below'
        cond_text = "ขึ้นไปแตะ" if condition == 'above' else "ร่วงลงมาแตะ"

        add_price_alert_db(user_id, symbol, target_price, condition)

        success_msg = (
            f"✅ **ตั้งเตือนสำเร็จ!** 🔔\n\n"
            f"📌 หุ้น: **{symbol}**\n"
            f"💵 ราคาปัจจุบัน: {current_price:,.2f}\n"
            f"🎯 ระบบจะแจ้งเตือนเมื่อราคา **{cond_text} {target_price:,.2f}**{pct_label}\n\n"
            f"*(ระบบจะคอยเฝ้ากราฟและอัปเดตราคาให้ทุกๆ 5 นาทีตลอด 24 ชม.)*"
        )
        bot.edit_message_text(success_msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")

    except ValueError:
        bot.reply_to(message, "❌ ราคาต้องเป็นตัวเลขเท่านั้นครับ เช่น 35 หรือ 35.50")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")

@bot.message_handler(commands=['delalert'])
def handle_del_alert(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    try:
        args = message.text.split()
        if len(args) != 2:
            kb = InlineKeyboardMarkup()
            _dash_btn = _dashboard_cta_button(user_id, "🌐 จัดการ Alerts บน Dashboard", src="delalert_err", next_path="/alerts")
            if _dash_btn:
                kb.add(_dash_btn)
            bot.reply_to(
                message,
                "❌ วิธีใช้: `/delalert [รหัสการตั้งเตือน]`\n(ดูรหัสได้จากเมนู 🔔 ตั้งเตือนราคา)\n\n💡 หรือลบผ่าน Dashboard ↓",
                parse_mode="Markdown", reply_markup=kb if _dash_btn else None,
            )
            return
        alert_id = int(args[1])
        remove_price_alert_db(user_id, alert_id)
        bot.reply_to(message, "🗑️ **ยกเลิกการแจ้งเตือนราคารายการนี้เรียบร้อยแล้วครับ**", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ รูปแบบไม่ถูกต้อง")

# ==========================================
# 🌟 ระบบคำสั่งแอดมิน 
# ==========================================
@bot.message_handler(commands=['user_log', 'sublog'])
def handle_user_log(message):
    """Admin: Subscription history timeline ของ user (audit trail)
    /user_log <user_id> [limit=30]

    ใช้ debug บั๊กแบบ Neil/Nattanon — ดู role/expiry changes ตามเวลา
    """
    user_id_admin = str(message.chat.id)
    if user_id_admin != ADMIN_ID:
        return
    try:
        from database import get_user_subscription_history
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ รูปแบบ: `/user_log <user_id> [limit=30]`", parse_mode="Markdown")
            return
        target_uid = args[1]
        limit = 30
        if len(args) > 2:
            try:
                limit = max(1, min(100, int(args[2])))
            except ValueError:
                pass

        events = get_user_subscription_history(target_uid, limit=limit)
        if not events:
            bot.reply_to(message, f"📜 *User Log — `{target_uid}`*\n\n_ยังไม่มี events_ (table อาจเพิ่งสร้าง)", parse_mode="Markdown")
            return

        lines = [f"📜 *User Log — `{target_uid}`* ({len(events)} events)", "━━━━━━━━━━━━━━━━━━"]
        for e in events:
            ts = e['created_at']
            ts_str = ts.strftime('%Y-%m-%d %H:%M') if hasattr(ts, 'strftime') else str(ts)[:16]
            action = e['action_type']
            rb = e['role_before'] or '?'
            ra = e['role_after'] or '?'
            days = f" +{e['days_granted']}d" if e['days_granted'] else ""
            arrow = "→"
            # flag suspicious downgrade
            warn = ""
            _RR = {'free': 0, 'vip': 1, 'pro': 2}
            if _RR.get(rb, 0) > _RR.get(ra, 0):
                warn = " ⚠️ DOWNGRADE"

            detail = e.get('source_detail') or e.get('source') or ''
            detail = str(detail)[:40]
            lines.append(f"`{ts_str}`  *{action}*  {rb} {arrow} {ra}{days}  _{detail}_{warn}")

        msg = "\n".join(lines)
        if len(msg) > 3800:
            msg = msg[:3800] + "\n\n_(truncated)_"
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[user_log] {e}", flush=True)
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['dm_stats', 'dmstats'])
def handle_dm_stats(message):
    """Admin: Auto-DM Cron performance — ดู DM sent + conversion rate"""
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        return
    try:
        from database import query_dm_stats
        args = message.text.split()
        days = 7
        if len(args) > 1:
            try:
                days = max(1, min(90, int(args[1])))
            except ValueError:
                pass

        stats = query_dm_stats(days=days)
        lines = [
            f"📬 *Auto-DM Stats ({stats['days']} วัน)*",
            f"━━━━━━━━━━━━━━",
            "",
            f"*🎯 Activation (สมัครแล้วไม่ activate):*",
            f"  ส่ง DM: **{stats['total_activation']}** คน",
            f"  ใช้ /freetrial แล้ว: {stats['activation_users_who_freetrial']} คน "
            f"({stats['activation_conversion_pct']:.1f}%)",
            "",
            f"*💎 Win-back (paying user หมดอายุ):*",
            f"  ส่ง DM: **{stats['total_winback']}** คน",
            f"  Renew กลับมา: {stats['winback_users_who_redeem']} คน "
            f"({stats['winback_conversion_pct']:.1f}%)",
        ]

        if stats['recent_activations']:
            lines.extend(["", "*📝 Recent Activation DMs:*"])
            for r in stats['recent_activations'][:8]:
                check = "✅" if r['converted'] else "⏳"
                uname = (r['username'] or 'Unknown')[:20]
                lines.append(f"  {check} `{r['user_id']}` {uname}")

        if stats['recent_winbacks']:
            lines.extend(["", "*📝 Recent Win-back DMs:*"])
            for r in stats['recent_winbacks'][:8]:
                check = "✅" if r['converted'] else "⏳"
                uname = (r['username'] or 'Unknown')[:20]
                lines.append(f"  {check} `{r['user_id']}` {uname}")

        lines.extend([
            "",
            f"_ปรับช่วงเวลา: /dm_stats 30 (default 7 วัน)_",
        ])
        bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        print(f"[dm_stats] {e}", flush=True)
        bot.reply_to(message, f"❌ Error: {e}")


@bot.message_handler(commands=['ban'])
def handle_ban(message):
    if str(message.chat.id) != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/ban [รหัสผู้ใช้]`", parse_mode="Markdown")
        return
    try:
        target_user = args[1]
        ban_user(target_user)
        bot.reply_to(message, f"🚫 **แบนสำเร็จ:** เตะ User `{target_user}` ออกจากระบบถาวรแล้ว!", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/ban [รหัสผู้ใช้]`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def handle_unban(message):
    if str(message.chat.id) != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/unban [รหัสผู้ใช้]`", parse_mode="Markdown")
        return
    try:
        target_user = args[1]
        unban_user(target_user)
        bot.reply_to(message, f"✅ **ปลดแบนสำเร็จ:** ให้โอกาส User `{target_user}` กลับมาใช้งานได้แล้ว", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/unban [รหัสผู้ใช้]`", parse_mode="Markdown")

@bot.message_handler(commands=['gencode'])
def handle_gencode(message):
    """Admin: สร้างโค้ด 2 mode

    Mode A — Days (เพิ่มวันฟรี):
      /gencode <days> <max_uses> <vip|pro> [custom_code_name]
      เช่น /gencode 7 100 vip          → "VIP7-XXXXXX" 7 วัน VIP, 100 uses
           /gencode 7 100 vip WELCOME7 → "WELCOME7" 7 วัน VIP, 100 uses

    Mode B — Discount % (ส่วนลด %):
      /gencode <pct>% <max_uses> <vip|pro> <window_hours> [custom_code_name]
      เช่น /gencode 20% 100 vip 48          → "VIP20OFF-XXXXXX" ลด 20%, 48 ชม., 100 uses
           /gencode 30% 50 pro 24 NEWYEAR30 → "NEWYEAR30" ลด 30% PRO, 24 ชม., 50 uses
    """
    if str(message.chat.id) != ADMIN_ID: return
    args = message.text.split()
    usage_text = (
        "❌ รูปแบบผิด!\n\n"
        "*Days mode:*\n"
        "  `/gencode <days> <max_uses> <vip|pro> [code_name]`\n"
        "  เช่น `/gencode 7 100 vip` หรือ `/gencode 7 100 vip WELCOME7`\n\n"
        "*Discount mode (ลด %):*\n"
        "  `/gencode <pct>% <max_uses> <vip|pro> <window_hours> [code_name]`\n"
        "  เช่น `/gencode 20% 100 vip 48` หรือ `/gencode 30% 50 pro 24 NEWYEAR30`"
    )
    if len(args) < 4:
        bot.reply_to(message, usage_text, parse_mode="Markdown")
        return
    try:
        first = args[1].strip()
        max_uses = int(args[2])
        role_type = args[3].lower()
        if role_type not in ('vip', 'pro'):
            bot.reply_to(message, "❌ role ต้องเป็น vip หรือ pro", parse_mode="Markdown")
            return

        # 🎟 Discount mode — first arg ลงท้าย "%"
        if first.endswith('%'):
            try:
                discount_pct = int(first.rstrip('%'))
            except ValueError:
                bot.reply_to(message, usage_text, parse_mode="Markdown")
                return
            if discount_pct < 5 or discount_pct > 75:
                bot.reply_to(message, "❌ ส่วนลดต้องอยู่ระหว่าง 5%-75%", parse_mode="Markdown")
                return
            if len(args) < 5:
                bot.reply_to(message, usage_text, parse_mode="Markdown")
                return
            window_hours = int(args[4])
            custom_name = args[5].strip().upper() if len(args) > 5 else None
            code = custom_name or f"{role_type.upper()}{discount_pct}OFF-" + generate_random_code(6)
            # คำนวณยอดเพื่อ preview ใน admin response
            vip_amt = round(79 * (1 - discount_pct / 100.0))
            pro_amt = round(109 * (1 - discount_pct / 100.0))
            preview_amt = vip_amt if role_type == 'vip' else pro_amt
            ok = add_promo_code(
                code, days=30, max_uses=max_uses, role_type=role_type,
                discount_pct=discount_pct, window_hours=window_hours,
            )
            if ok:
                msg = (
                    f"✅ *สร้างโค้ดส่วนลด {role_type.upper()} สำเร็จ!*\n\n"
                    f"🎟 *โค้ด:* `{code}`\n"
                    f"💰 *ส่วนลด:* {discount_pct}% ({role_type.upper()} เหลือ {preview_amt}฿)\n"
                    f"⏰ *Window:* {window_hours} ชม. หลัง redeem\n"
                    f"👥 *Max uses:* {max_uses} คน\n\n"
                    f"*Flow ของ user:*\n"
                    f"1. พิมพ์ `/redeem {code}`\n"
                    f"2. bot บอก \"โอน {preview_amt}฿ ภายใน {window_hours} ชม.\"\n"
                    f"3. user โอน → ได้ {role_type.upper()} 30 วัน"
                )
                bot.reply_to(message, msg, parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ โค้ด `{code}` ซ้ำแล้ว — ลองชื่ออื่น", parse_mode="Markdown")
            return

        # 🎁 Days mode (existing)
        days = int(first)
        custom_name = args[4].strip().upper() if len(args) > 4 else None
        code = custom_name or f"{role_type.upper()}{days}-" + generate_random_code(6)
        if add_promo_code(code, days, max_uses, role_type):
            msg = (
                f"✅ *สร้างโค้ด {role_type.upper()} สำเร็จ!*\n\n"
                f"🎟 *โค้ด:* `{code}`\n"
                f"⏰ *เพิ่มวัน:* {days} วัน\n"
                f"👥 *Max uses:* {max_uses} คน\n\n"
                f"*(ส่งให้ลูกค้า — พิมพ์ `/redeem {code}` รับ {role_type.upper()} ทันที)*"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
        else:
            bot.reply_to(message, f"❌ โค้ด `{code}` ซ้ำแล้ว — ลองชื่ออื่น", parse_mode="Markdown")
    except Exception as e:
        print(f"[gencode] err: {e}", flush=True)
        bot.reply_to(message, usage_text, parse_mode="Markdown")

@bot.message_handler(commands=['redeem'])
def handle_redeem(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ รูปแบบคำสั่งไม่ถูกต้อง พิมพ์: `/redeem [โค้ดของคุณ]`", parse_mode="Markdown")
        return
    
    code = args[1].strip().upper()
    success, days, expiry, role_type = redeem_code(user_id, code)

    if success:
        # 🎟 Discount mode — expiry เป็น dict ของ discount window ไม่ใช่ string วันหมดอายุ
        if days == "discount" and isinstance(expiry, dict):
            pct = expiry.get("pct", 0)
            vip_amt = expiry.get("vip_amount")
            pro_amt = expiry.get("pro_amount")
            window_h = expiry.get("window_hours", 24)
            target_amt = pro_amt if role_type == 'pro' else vip_amt
            target_role = "PRO" if role_type == 'pro' else "VIP"
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(f"💎 สร้าง QR ยอด {target_amt}฿", callback_data=f"qr_pay_{target_amt}"))
            msg = (
                f"🎁 *ส่วนลด {pct}% เปิดให้คุณแล้ว!*\n\n"
                f"💰 *ราคาพิเศษ:* {target_amt}฿ ({target_role} รายเดือน)\n"
                f"⏰ *ใช้ได้ภายใน:* {window_h} ชม.\n\n"
                f"*ขั้นตอน:*\n"
                f"1. กดปุ่มด้านล่างเพื่อสร้าง QR\n"
                f"2. โอนยอด {target_amt}฿ ผ่าน PromptPay\n"
                f"3. ส่งสลิปกลับในแชทนี้ → bot อัปเกรดอัตโนมัติ\n\n"
                f"_โค้ดนี้ใช้ได้ครั้งเดียว ถ้าไม่โอนใน {window_h} ชม. โค้ดจะหมดอายุ_"
            )
            bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=kb)
            return
        # 🎁 Days mode (existing)
        bot.reply_to(message, f"🎉 **ยินดีด้วย!** เติมโค้ดสำเร็จ\nคุณได้รับการอัปเกรดเป็น **{role_type.upper()} Member** ถึงวันที่: `{expiry}`\n\nสามารถใช้งานฟีเจอร์ใหม่ได้ทันทีครับ 🚀", parse_mode="Markdown")
        # 🐛 ลบ increment_usage(user_id) ออก — ไม่ควรนับเป็น quota ตอน redeem code
        # (legacy code อาจเป็นต้นเหตุที่ usage_count ของ test user สูงผิดปกติ)
    elif days == "already_used_by_you":
        bot.reply_to(message, "⚠️ คุณเคยใช้โค้ดโปรโมชั่นนี้ไปแล้วครับ (1 คน ใช้ได้ 1 ครั้ง)")
    elif days == "fully_used":
        bot.reply_to(message, "❌ น่าเสียดาย! สิทธิ์ของโค้ดนี้ถูกใช้งานครบตามจำนวนแล้วครับ")
    else:
        bot.reply_to(message, "❌ โค้ดไม่ถูกต้อง หรือไม่มีในระบบ")

@bot.message_handler(commands=['freetrial'])
def handle_free_trial(message):
    """ทดลองใช้ PRO 7 วันฟรี — ใช้ได้ 1 ครั้งต่อ account"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role in ('vip', 'pro'):
        # 🌟 ดึง expiry date มาแสดงด้วย ให้ user รู้ชัดเจน
        try:
            profile = get_user_profile(user_id)
            expiry = profile[1] if profile else None
            expiry_str = str(expiry)[:10] if expiry else "ไม่มีวันหมด"
        except Exception:
            expiry_str = "ไม่ทราบ"
        role_label = "👑 PRO" if role == 'pro' else "💎 VIP"
        bot.reply_to(message,
            f"✨ **คุณมีแพ็กเกจอยู่แล้วครับ!**\n\n"
            f"📦 สถานะปัจจุบัน: {role_label}\n"
            f"⏰ ใช้ได้ถึงวันที่: `{expiry_str}`\n\n"
            f"_Free Trial สำหรับผู้ที่ยังไม่เคยใช้ VIP/PRO เท่านั้นครับ_",
            parse_mode="Markdown")
        return
    if has_used_free_trial(user_id):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("💎 สมัคร VIP 79฿", callback_data="menu_vip"),
            InlineKeyboardButton("👑 สมัคร PRO 109฿", callback_data="menu_vip"),
        )
        markup.add(InlineKeyboardButton("🤝 ชวนเพื่อน รับ VIP ฟรี", callback_data="menu_referral"))
        bot.reply_to(message,
            "✨ **คุณเคยใช้ Free Trial ไปแล้วครับ**\n\n"
            "_Free Trial ใช้ได้เพียง 1 ครั้งต่อบัญชีเท่านั้น_\n\n"
            "💎 *ตัวเลือกอื่น ๆ สำหรับคุณ:*\n"
            "• สมัคร VIP/PRO รายเดือนได้ตลอดเวลา\n"
            "• ชวนเพื่อนสมัคร → ทั้งคู่ได้รางวัล\n"
            "• ใช้โค้ดโปรโมฯ ผ่าน `/redeem`",
            parse_mode="Markdown", reply_markup=markup)
        return
    ok = activate_free_trial(user_id)
    if ok:
        bot.reply_to(message,
            "🎉 **ยินดีต้อนรับสู่ PRO 7 วัน!**\n\n"
            "✅ คุณได้รับสิทธิ์ PRO เต็มรูปแบบ 7 วันฟรีแล้ว\n\n"
            "**สิ่งที่คุณทำได้ตอนนี้:**\n"
            "• วิเคราะห์หุ้นไม่จำกัดครั้ง + กราฟเทคนิค\n"
            "• Entry/TP/SL พร้อมกราฟวาด zone\n"
            "• Flash News + Morning Briefing\n"
            "• Smart Alerts + Price Alerts\n"
            "• Watchlist ไม่จำกัด\n\n"
            "_💡 ใช้งานได้จนครบ 7 วัน — หลังจากนั้นกลับเป็น Free อัตโนมัติ (ไม่มีหักเงิน)_",
            parse_mode="Markdown")
    else:
        bot.reply_to(message, "📡 ระบบขัดข้องชั่วคราว ขออภัยในความไม่สะดวก รบกวนลองอีกครั้งในสักครู่ครับ")


def _capture_referrer_input(message):
    """Receives the user's reply to 'who referred you?'.
    Fast path: ถ้าใส่ user_id ตัวเลขที่มีจริงและไม่ใช่ตัวเอง → auto-credit ทันที
    Slow path: ใส่ชื่อ / @username / uid ที่ไม่มีในระบบ → เข้า pending_referrals รอ admin review
    """
    user_id = str(message.chat.id)
    txt = (message.text or "").strip()
    if not txt or txt.startswith("/"):
        bot.send_message(int(user_id), "ยกเลิกแล้วครับ ใช้ /start หากต้องการเริ่มใหม่")
        return

    # 🛡️ กันลูกค้ากดปุ่มเมนูแทนการพิมพ์ชื่อเพื่อน → ตีความเป็น cancel
    MENU_BUTTON_KEYWORDS = (
        "เปิดเมนู", "Dashboard", "แผงควบคุม", "บัญชี / VIP",
        "วิเคราะห์หุ้น", "ติดต่อแอดมิน",
    )
    if any(kw in txt for kw in MENU_BUTTON_KEYWORDS):
        bot.send_message(
            int(user_id),
            "ℹ️ ดูเหมือนคุณกดปุ่มเมนู — กรุณา *พิมพ์ชื่อ* หรือ *user\\_id* ของเพื่อนที่ชวนแทนนะครับ\n"
            "หรือพิมพ์ /start เพื่อเริ่มใหม่",
            parse_mode="Markdown",
        )
        return

    first = message.from_user.first_name or ""
    last = message.from_user.last_name or ""
    name = f"{first} {last}".strip()

    # 🚀 Fast path — auto-credit ถ้า input คือ user_id ตัวเลข + valid + ไม่ใช่ตัวเอง
    candidate = txt.lstrip("@").strip()
    if candidate.isdigit() and candidate != user_id:
        try:
            from database import user_exists, process_referral
            if user_exists(candidate):
                success, milestone = process_referral(candidate, user_id)
                if success:
                    bot.send_message(
                        int(user_id),
                        "🎉 *เครดิตให้เพื่อนคุณเรียบร้อยแล้ว!*\n\n"
                        "เพื่อนได้รางวัลทันที + คุณได้ VIP 3 วันฟรี 🎁\n"
                        "ขอบคุณที่ช่วยบอกต่อ Apexify ครับ 🤝",
                        parse_mode="Markdown",
                    )
                    try:
                        bonus = "milestone +10 days VIP" if milestone else "+3 quota"
                        bot.send_message(
                            int(ADMIN_ID),
                            f"✅ *Auto-credited referral*\n\n"
                            f"Referrer: `{candidate}` ({bonus})\n"
                            f"Referred: `{user_id}` ({name or '-'})",
                            parse_mode="Markdown",
                        )
                    except Exception as notify_err:
                        print(f"[ReferralAutoCredit] admin notify failed: {notify_err}", flush=True)
                    return
        except Exception as e:
            print(f"[ReferralAutoCredit] fast path failed, falling back to pending: {e}", flush=True)

    # 🐌 Slow path — ชื่อ/text/uid ที่ไม่มีในระบบ → pending review
    try:
        from database import add_pending_referral
        add_pending_referral(user_id, name, txt)
        bot.send_message(
            int(user_id),
            "✅ *ได้รับข้อมูลแล้วครับ*\n\n"
            "ทีมงานจะตรวจสอบและให้รางวัลกับเพื่อนคุณภายใน 24 ชม.\n"
            "ขอบคุณที่ช่วยบอกต่อ Apexify ครับ 🤝",
            parse_mode="Markdown",
        )
        try:
            bot.send_message(
                int(ADMIN_ID),
                f"🎁 *New referral submission*\n\n"
                f"From user: `{user_id}` ({name or '-'})\n"
                f"Referrer query: `{txt[:120]}`\n\n"
                f"_ใช้ /pending\\_refs เพื่อดูรายการ_",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"[ReferralCapture] admin notify failed: {e}", flush=True)
    except Exception as e:
        print(f"[ReferralCapture] save failed: {e}", flush=True)
        from bot_utils import alert_admin_error
        alert_admin_error(bot, "ReferralCapture", e, user_id=user_id)
        bot.send_message(int(user_id), friendly_error("บันทึกไม่สำเร็จ — ลองใหม่ผ่าน /start"))


@bot.message_handler(commands=['badges', 'achievements'])
def handle_badges(message):
    """ดู badges ที่สะสมไว้ + คำแนะนำหา badges ถัดไป"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    from database import get_user_achievements, ACHIEVEMENT_CATALOG, evaluate_achievements
    # Safety net — catch any badges that should have been granted but weren't
    # (e.g., trial activated before badge logic existed, referrals without trigger)
    try:
        evaluate_achievements(user_id, context=None)
    except Exception:
        pass
    earned = get_user_achievements(user_id)
    earned_codes = {b["code"] for b in earned}
    total = len(ACHIEVEMENT_CATALOG)
    have = len(earned_codes)
    lines = [
        f"🏆 *Badges & Achievements* — {have}/{total}",
        "",
    ]
    if earned:
        lines.append("*✅ ที่ได้แล้ว:*")
        for b in earned:
            lines.append(f"  {b['label']} — _{b['description']}_")
        lines.append("")
    locked = [c for c in ACHIEVEMENT_CATALOG if c not in earned_codes]
    if locked:
        lines.append("*🔒 รอปลดล็อก:*")
        for code in locked[:5]:  # show top 5 next
            label, desc = ACHIEVEMENT_CATALOG[code]
            lines.append(f"  ⬜ {label} — _{desc}_")
        if len(locked) > 5:
            lines.append(f"  _...และอีก {len(locked) - 5} badges_")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['contact', 'support', 'admin_contact'])
def handle_contact(message):
    """ติดต่อแอดมิน — Telegram @apexify_admin"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💬 แชทกับ Admin", url="https://t.me/apexify_admin"))
    bot.reply_to(message,
        "🆘 *ติดต่อแอดมิน Apexify*\n\n"
        "Telegram: [@apexify\\_admin](https://t.me/apexify_admin)\n\n"
        "ใช้ติดต่อ:\n"
        "• สอบถามเรื่องบัญชี / การชำระเงิน\n"
        "• แจ้งปัญหาการใช้งาน\n"
        "• ขอความช่วยเหลือเรื่องสิทธิ์\n"
        "• เสนอแนะฟีเจอร์ใหม่",
        parse_mode="Markdown",
        reply_markup=markup,
        disable_web_page_preview=True,
    )


@bot.message_handler(commands=['pending_refs'])
def handle_pending_refs(message):
    """[Admin] ดู pending referral submissions พร้อม candidate match อัตโนมัติ"""
    user_id = str(message.chat.id)
    if str(user_id) != str(ADMIN_ID):
        return
    from database import list_pending_referrals, find_users_by_name
    rows = list_pending_referrals(limit=20)
    if not rows:
        bot.reply_to(message, "✅ ไม่มี pending referral")
        return
    lines = ["📋 *Pending Referrals* (รอ admin จับคู่)", ""]
    for r in rows:
        query = (r['referrer_query'] or "").strip()
        candidates = find_users_by_name(query.lstrip("@"), limit=3) if query else []
        block = [
            f"`#{r['id']}` user `{r['new_user_id']}` ({r['new_user_name'] or '-'})",
            f"   → ระบุว่ามาจาก: *{query}*",
        ]
        if candidates:
            block.append("   🔍 *candidate match:*")
            for cand_uid, cand_name in candidates:
                block.append(f"      • `/award_ref {r['id']} {cand_uid}` — {cand_name or '(no name)'}")
        else:
            block.append(f"   _ไม่พบ user ที่ชื่อใกล้เคียง — ใช้ /finduser ค้นเอง_")
        block.append(f"   _submitted: {r['submitted_at'][:16] if r['submitted_at'] else '-'}_")
        lines.append("\n".join(block))
    lines.append("\n_จับคู่ด้วย:_ `/award_ref <id> <referrer_telegram_id>`")
    lines.append("_ลบ submission ผิด:_ `/del_pending <id>`")
    bot.reply_to(message, "\n\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['finduser'])
def handle_finduser(message):
    """[Admin] ค้นหา user_id จากชื่อ — /finduser [partial_name]"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        bot.reply_to(message, "❌ รูปแบบ: `/finduser [ชื่อ_หรือ_บางส่วน]`", parse_mode="Markdown")
        return
    from database import find_users_by_name
    matches = find_users_by_name(parts[1].strip(), limit=10)
    if not matches:
        bot.reply_to(message, f"ℹ️ ไม่พบ user ชื่อใกล้เคียง `{parts[1]}`", parse_mode="Markdown")
        return
    lines = [f"🔍 *พบ {len(matches)} user* ที่ชื่อตรงกับ `{parts[1]}`", ""]
    for uid, uname in matches:
        lines.append(f"• `{uid}` — {uname or '(no name)'}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['award_ref'])
def handle_award_ref(message):
    """[Admin] /award_ref <pending_id> <referrer_telegram_id>"""
    user_id = str(message.chat.id)
    if str(user_id) != str(ADMIN_ID):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        bot.reply_to(message, "Usage: `/award_ref <pending_id> <referrer_telegram_id>`",
                     parse_mode="Markdown")
        return
    try:
        pid = int(parts[1].lstrip("#"))
        ref_id = parts[2].lstrip("@")
    except ValueError:
        bot.reply_to(message, "❌ pending_id ต้องเป็นตัวเลข")
        return
    from database import mark_referral_awarded
    # NOTE: Use existing process_referral logic to actually grant the reward
    # by simulating a back-dated referral. We import process_referral lazily.
    try:
        from database import process_referral
        # Find the new_user from pending row
        from database import list_pending_referrals
        target = next((r for r in list_pending_referrals(limit=200) if r["id"] == pid), None)
        if not target:
            bot.reply_to(message, f"❌ pending_id `{pid}` ไม่พบ หรือ awarded ไปแล้ว",
                         parse_mode="Markdown")
            return
        success, milestone = process_referral(ref_id, target["new_user_id"])
        if not success:
            bot.reply_to(message, "❌ process_referral ล้มเหลว — อาจ user ใหม่ยังไม่ register เป็น row หรือ already-recorded")
            return
        mark_referral_awarded(pid, ref_id)
        bot.reply_to(
            message,
            f"✅ Awarded — referrer `{ref_id}` ได้รับ "
            f"{'milestone bonus + 10 days' if milestone else '+3 quota'}\n"
            f"new user `{target['new_user_id']}` ได้ VIP 3 วันฟรี",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[award_ref] {e}", flush=True)
        bot.reply_to(message, friendly_error("เพิ่มรางวัล referral ไม่สำเร็จ"))


@bot.message_handler(commands=['del_pending'])
def handle_del_pending_ref(message):
    """[Admin] ลบ pending referral ผิด/spam — /del_pending [pending_id]"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบ: `/del_pending [pending_id]`\nใช้ `/pending_refs` เพื่อดู id", parse_mode="Markdown")
        return
    try:
        pid = int(args[1].lstrip("#"))
    except ValueError:
        bot.reply_to(message, "❌ pending_id ต้องเป็นตัวเลข")
        return
    if delete_pending_referral(pid):
        bot.reply_to(message, f"🗑️ ลบ pending referral `{pid}` แล้ว", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ ไม่พบ pending_id `{pid}`", parse_mode="Markdown")


@bot.message_handler(commands=['reset_trial'])
def handle_reset_trial(message):
    """[Admin] รีเซ็ต free_trial_used flag ของ user — /reset_trial [uid]"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบ: `/reset_trial [user_id]`", parse_mode="Markdown")
        return
    target = args[1].strip()
    if reset_free_trial(target):
        bot.reply_to(message, f"✅ รีเซ็ต Free Trial flag ของ `{target}` แล้ว — user สมัคร `/freetrial` ได้อีกครั้ง", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ ไม่พบ user `{target}` ในระบบ", parse_mode="Markdown")


@bot.message_handler(commands=['cleanup_logs'])
def handle_cleanup_logs(message):
    """[Admin] ลบ row เก่าใน bot_command_log + broadcast_log — /cleanup_logs [days=90]"""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    days = 90
    if len(args) >= 2:
        try:
            days = max(1, int(args[1]))
        except ValueError:
            bot.reply_to(message, "❌ days ต้องเป็นตัวเลข")
            return
    result = cleanup_old_logs(days=days)
    bot.reply_to(
        message,
        f"🧹 *Cleanup เสร็จ* (เก็บ {days} วันล่าสุด)\n"
        f"• bot_command_log: ลบ {result['bot_command_log']:,} แถว\n"
        f"• broadcast_log: ลบ {result['broadcast_log']:,} แถว",
        parse_mode="Markdown",
    )


# Day-trade coach state — in-memory dict {(user_id, ticker, date_str): count}
# OK to lose on restart; coaching is a soft nudge not data-critical.
_daytrade_count: dict = {}

# Day-trade coach messages keyed by analysis count for the same ticker today.
_DAYTRADE_COACH_MESSAGES = {
    5: ("🧘 *Discipline check:* คุณวิเคราะห์ {symbol} แล้ว 5 ครั้งวันนี้\n"
        "_ตลาดไม่ได้เปลี่ยนทุก 30 นาที — เก็บแผนเดิมไว้แล้วรอสัญญาณยืนยัน 1-2 วันก็พอครับ_"),
    8: ("⏸ *FOMO alert:* วิเคราะห์ {symbol} 8 ครั้งวันนี้แล้ว\n"
        "_นักลงทุนเก่งๆ เน้น \"รอจังหวะที่ใช่\" มากกว่า \"จับจังหวะให้ครบ\"_\n"
        "_ลองพักดู 24 ชม. แล้วค่อยตัดสินใจอีกที_"),
    12: ("🛑 *Trade journaling tip:* {symbol} ถูกวิเคราะห์ 12+ ครั้งวันนี้\n"
         "_นี่อาจเป็น signal ของอารมณ์ ไม่ใช่การวิเคราะห์ — บางทีพอร์ตที่ดีคือพอร์ตที่ \"ไม่ทำอะไร\"_"),
}


def _maybe_append_daytrade_coach(user_id: str, symbol: str, report: str) -> str:
    """Append a discipline-coach note when user re-analyzes the same ticker too often."""
    from datetime import datetime, timedelta, timezone
    if str(user_id) == str(ADMIN_ID):
        return report
    today = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    key = (str(user_id), str(symbol).upper(), today)
    _daytrade_count[key] = _daytrade_count.get(key, 0) + 1
    count = _daytrade_count[key]
    # Trigger at exact thresholds only — once per threshold per day
    msg = _DAYTRADE_COACH_MESSAGES.get(count)
    if msg:
        return report + "\n\n" + msg.format(symbol=symbol)
    return report


def _send_breaking_status_card(chat_id: int, enabled: bool):
    """Render the breaking-news settings card with toggle button."""
    icon = "🔔 เปิดอยู่" if enabled else "🔕 ปิดอยู่"
    btn_label = "🔕 ปิดข่าวด่วน" if enabled else "🔔 เปิดข่าวด่วน"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(btn_label, callback_data="breaking_toggle"))
    text = (
        "🚨 *ข่าวด่วนตลาด US*\n\n"
        f"สถานะ: *{icon}*\n\n"
        "ระบบจะแจ้งเฉพาะข่าวระดับ HIGH ที่กระทบ S&P 500 / Nasdaq จริง\n"
        "เช่น CPI, NFP, FOMC, สงคราม, OPEC cut\n\n"
        "🌙 ช่วง 02:00-08:00 น. (ไทย) จะรวมไว้ใน Morning Briefing"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(commands=['breaking', 'breaking_on', 'breakingon',
                               'breaking_off', 'breakingoff',
                               'breaking_status', 'breakingstatus'])
def handle_breaking(message):
    """หน้าตั้งค่าข่าวด่วน — มีปุ่มเปิด/ปิด"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role != 'pro':
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("👑 สมัคร PRO 109฿", callback_data="menu_vip"),
            InlineKeyboardButton("✨ Free Trial 7 วัน", callback_data="menu_freetrial"),
        )
        bot.reply_to(
            message,
            "🔒 *ข่าวด่วนตลาด US — ฟีเจอร์ PRO เท่านั้น*\n\n"
            "🚨 ระบบจะแจ้งเตือนเฉพาะข่าวที่กระทบ S&P 500/Nasdaq จริง\n"
            "เช่น CPI, NFP, FOMC, สงคราม, OPEC cut\n\n"
            "Apexify คัดเฉพาะระดับ HIGH ส่งให้ — ไม่สแปม",
            parse_mode="Markdown",
            reply_markup=markup,
        )
        return
    from database import is_subscribed_breaking_news
    _send_breaking_status_card(int(user_id), is_subscribed_breaking_news(user_id))


@bot.message_handler(commands=['breaking_test'])
def handle_breaking_test(message):
    """[Admin] ทดสอบ breaking news pipeline"""
    user_id = str(message.chat.id)
    if str(user_id) != str(ADMIN_ID):
        return
    bot.reply_to(message, "⏳ กำลังทดสอบ breaking news pipeline...")
    try:
        from breaking_news import process_breaking_news
        stats = process_breaking_news(bot, dry_run=False)
        bot.send_message(user_id,
            f"📊 **Breaking News Test Result**\n\n"
            f"🔍 Fetched: `{stats['fetched']}`\n"
            f"📋 Shortlisted: `{stats['shortlisted']}`\n"
            f"🤖 Classified: `{stats['classified']}`\n"
            f"🚨 HIGH: `{stats['high']}`\n"
            f"📤 Pushed (users): `{stats['pushed_users']}`\n"
            f"♻️ Skipped dup: `{stats['skipped_dup']}`\n"
            f"🌙 Quiet hour: `{stats['skipped_quiet']}`",
            parse_mode="Markdown")
    except Exception as e:
        print(f"[breaking_test] {e}", flush=True)
        bot.send_message(user_id, friendly_error("ทดสอบ Breaking News ล้มเหลว"))


@bot.message_handler(commands=['ealert'])
def handle_ealert(message):
    """Earnings Calendar Alert: /ealert [SYMBOL] | /ealert list | /ealert remove SYMBOL"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    args = message.text.split()

    if len(args) == 1:
        bot.reply_to(message,
            "📅 **Earnings Calendar Alert**\n\n"
            "รับแจ้งเตือนวันที่บริษัทจะประกาศผลกำไร ทุกเช้า 8:00 น.\n\n"
            "**คำสั่ง:**\n"
            "`/ealert AAPL` — สมัครแจ้งเตือน AAPL\n"
            "`/ealert list` — ดู symbol ที่สมัครไว้\n"
            "`/ealert remove AAPL` — ยกเลิก AAPL\n\n"
            "_ฟีเจอร์นี้สำหรับสมาชิก VIP/PRO ครับ_",
            parse_mode="Markdown")
        return

    sub_cmd = args[1].upper()

    if sub_cmd == 'LIST':
        subs = get_user_earnings_alerts_db(user_id)
        if not subs:
            bot.reply_to(message, "📋 ยังไม่ได้สมัครแจ้งเตือน Earnings ของ symbol ใดเลยครับ\nใช้ `/ealert AAPL` เพื่อสมัคร", parse_mode="Markdown")
        else:
            bot.reply_to(message, "📋 **Earnings Alert ของคุณ:**\n" + "\n".join(f"• {s}" for s in subs), parse_mode="Markdown")
        return

    if sub_cmd == 'REMOVE' and len(args) >= 3:
        sym = args[2].upper()
        ok = remove_earnings_alert_db(user_id, sym)
        if ok:
            bot.reply_to(message, f"✅ ยกเลิกแจ้งเตือน **{sym}** แล้วครับ", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ ไม่พบ **{sym}** ในรายการของคุณ", parse_mode="Markdown")
        return

    symbol = sub_cmd
    if role == 'free' and str(user_id) != str(ADMIN_ID):
        bot.reply_to(message,
            "🔒 **Earnings Alert สำหรับ VIP/PRO**\n\n"
            "ทดลองฟรี 7 วันด้วย `/freetrial` ครับ",
            parse_mode="Markdown")
        return
    ok = add_earnings_alert_db(user_id, symbol)
    if ok:
        bot.reply_to(message,
            f"✅ สมัครแจ้งเตือน **{symbol}** Earnings แล้วครับ\n"
            "_แจ้งเตือนทุกเช้าเมื่อมี Earnings วันนั้นหรือพรุ่งนี้_",
            parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ คุณสมัครแจ้งเตือน **{symbol}** ไว้แล้วครับ", parse_mode="Markdown")


@bot.message_handler(commands=['manual', 'help'])
def handle_manual(message):
    """คู่มือการใช้งานคำสั่งทั้งหมด"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)

    msg = (
        "📖 **คู่มือการใช้งาน Apexify** 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"

        "**🔍 วิเคราะห์หุ้น / สินทรัพย์**\n"
        "พิมพ์ชื่อตรงๆ ได้เลย ไม่ต้องใช้คำสั่ง\n"
        "`AAPL` `TSLA` `NVDA` — หุ้น US\n"
        "`PTT.BK` `KBANK.BK` — หุ้นไทย (ต้องมี .BK)\n"
        "`CBA.AX` `.L` `.HK` `.T` — ตลาดอื่นๆ\n"
        "`gold` `silver` `oil` `gas` `copper` — โลหะ/น้ำมัน 🥇🛢\n"
        "`btc` `eth` — คริปโต ₿\n\n"

        "**💼 จัดการพอร์ต**\n"
        "`/add AAPL 10 150` — บันทึกซื้อหุ้น 10 หุ้น ราคา 150\n"
        "`/edit AAPL 15 165` — แก้จำนวน/ราคาเฉลี่ยของหุ้นเดิม\n"
        "`/del AAPL` — ลบหุ้นออกจากพอร์ต\n"
        "`/portfolio` หรือ `/port` — ดูพอร์ตทั้งหมด\n"
        "`/pnl` — สร้างการ์ด P&L แบบสวยงาม\n\n"

        "**⭐ Watchlist**\n"
        "`/watch AAPL` — เพิ่มหุ้นเข้า Watchlist (หรือกด ⭐ ใต้รายงาน)\n"
        "`/unwatch AAPL` — ลบหุ้นออกจาก Watchlist\n\n"

        "**🔔 ตั้งเตือนราคา** _(PRO)_\n"
        "`/setalert AAPL 200` — แจ้งเตือนเมื่อ AAPL ถึง $200\n"
        "`/setalert AAPL +5%` — แจ้งเตือนเมื่อขึ้น 5%\n"
        "`/setalert AAPL -3%` — แจ้งเตือนเมื่อลง 3%\n"
        "`/myalerts` — ดู alerts ที่ตั้งไว้ทั้งหมด\n"
        "`/delalert AAPL` — ลบการแจ้งเตือนของ AAPL\n\n"

        "**📅 Earnings Calendar** _(VIP/PRO)_\n"
        "`/ealert AAPL` — สมัครแจ้งเตือนวัน Earnings\n"
        "`/ealert list` — ดูรายการที่สมัครไว้\n"
        "`/ealert remove AAPL` — ยกเลิก\n"
        "`/earnings AAPL` — Apexify วิเคราะห์งบการเงิน _(VIP/PRO)_\n"
        "`/fund AAPL` — P/E, EPS, Dividend, Market Cap _(VIP/PRO)_\n"
        "`/compare AAPL MSFT` — เปรียบเทียบ 2-3 หุ้น + AI verdict _(PRO)_\n"
        "`/ask <คำถาม>` — ถาม Apexify อะไรก็ได้ _(PRO)_\n\n"

        "**📰 Breaking News** _(PRO)_\n"
        "`/breaking_on` — เปิดรับข่าว flash ทันทีเมื่อมีข่าวใหญ่\n"
        "`/breaking_off` — ปิดรับข่าว flash\n"
        "`/breaking_status` — เช็คสถานะ subscription ปัจจุบัน\n\n"

        "**📊 Track Record & Streak & Badges**\n"
        "`/track` — สถิติ Apexify Plans: hit rate TP1/TP2 ย้อนหลัง 30/90 วัน\n"
        "`/badges` หรือ `/achievements` — ดูเหรียญตราที่ได้รับ\n"
        "🔥 **Daily Streak:** ใช้ทุกวันติดต่อกัน → ครบ 7 วัน รับ VIP 1 วันฟรี!\n\n"

        "**💎 บัญชี & สิทธิ์**\n"
        "`/account` หรือ `/me` — สถานะบัญชี + Streak + โควต้า\n"
        "`/payment` — สมัคร/ต่ออายุ VIP/PRO + ดู QR ชำระเงิน\n"
        "`/freetrial` — ทดลอง PRO 7 วันฟรี (ใช้ได้ 1 ครั้ง/บัญชี)\n"
        "`/redeem [โค้ด]` — เติมโค้ดโปรโมชั่น (เช่น VIP7-A1B2C3)\n"
        "🤝 *ชวนเพื่อน:* ทั้งคู่ได้รางวัล (คุณ +3 quota, เพื่อน VIP 3 วันฟรี)\n\n"

        "**⚙️ การตั้งค่า**\n"
        "`/settings` — ตั้งค่า: แจ้งเตือน, timezone, ภาษา, ความถี่ digest\n"
        "`/dashboard` — เปิด Web Dashboard (auto-login ผ่านลิงก์)\n\n"

        "**🎬 สำรวจฟีเจอร์**\n"
        "`/demo` — ทัวร์ฟีเจอร์ทั้งหมดในหน้าเดียว\n"
        "`/manual` หรือ `/help` — เปิดคู่มือนี้อีกครั้ง\n"
        "`/contact` หรือ `/support` — ส่งข้อความถึงแอดมินโดยตรง\n\n"

        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**🌟 Workflow แนะนำ**\n\n"

        "*👶 มือใหม่เริ่มต้น (Free):*\n"
        "1️⃣ พิมพ์ชื่อหุ้น เช่น `AAPL` → ดูรายงาน\n"
        "2️⃣ กด ⭐ เพิ่มเข้า Watchlist (สูงสุด 3 ตัว)\n"
        "3️⃣ `/track` ดูสถิติว่า Apexify แม่นแค่ไหน\n"
        "4️⃣ `/freetrial` ทดลอง PRO ฟรี 7 วัน\n\n"

        "*📈 นักลงทุนระยะยาว (VIP):*\n"
        "1️⃣ ดูข่าวเช้าจาก Morning Briefing (8:30 น.)\n"
        "2️⃣ วิเคราะห์หุ้นที่สนใจ + `/fund` ดูความแข็งแกร่ง\n"
        "3️⃣ `/ealert` สมัครรับแจ้งวันประกาศงบ\n"
        "4️⃣ เช็ค Weekly Digest ทุกศุกร์ 18:00 น.\n\n"

        "*🚀 เทรดเดอร์ระยะสั้น (PRO):*\n"
        "1️⃣ `/compare` หาหุ้นที่ setup ดีที่สุด\n"
        "2️⃣ ใช้ Entry zone / TP / SL ที่บอทคำนวณ\n"
        "3️⃣ `/setalert` ตั้งเตือนราคาเป้าหมาย\n"
        "4️⃣ `/ask` ถาม Apexify เพิ่มเติมเมื่อไม่มั่นใจ\n"
        "5️⃣ รับ Smart Alerts (RSI/MACD/Volume spike) อัตโนมัติ\n\n"

        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**❓ คำถามที่พบบ่อย**\n\n"
        "*Q: หุ้นไทยต้องเติม .BK ไหม?*\n"
        "A: ใส่ก็ดี ไม่ใส่ก็ได้ — บอทจะลอง `.BK` ให้อัตโนมัติ\n\n"

        "*Q: ข้อมูลมาจากไหน?*\n"
        "A: ราคาจาก Yahoo Finance + วิเคราะห์ด้วย Google Gemini AI\n\n"

        "*Q: ทำไมใช้เวลา 10-20 วินาที?*\n"
        "A: ระบบดึงข้อมูล 3 timeframes + วิเคราะห์ด้วย AI + วาดกราฟ\n\n"

        "*Q: ถ้า Apexify วิเคราะห์ผิดจะฟ้องได้ไหม?*\n"
        "A: รายงานทั้งหมดจัดทำขึ้นเพื่อประกอบการพิจารณาเท่านั้น มิใช่คำแนะนำการลงทุน การเสนอขาย หรือการชักชวนให้ซื้อขายหลักทรัพย์ใด ๆ การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลและใช้ดุลยพินิจของตนเองก่อนตัดสินใจลงทุน\n\n"

        "*Q: ต่ออายุ VIP/PRO ยังไง?*\n"
        "A: พิมพ์ `/payment` (หรือกดปุ่ม 💎 บัญชี / VIP) → เลือกแพ็กเกจ → โอน → ส่งสลิป — ระบบ auto upgrade ใน 3 วินาที\n\n"

        "*Q: ยกเลิกสมาชิกยังไง?*\n"
        "A: ไม่มีการผูกบัตร — ปล่อยหมดอายุได้เลย (ใช้งานต่อได้จนครบวันที่จ่ายไว้)\n\n"

        "*Q: แจ้งเตือนมาบ่อยไป ปิดยังไง?*\n"
        "A: `/settings` → เลือกประเภทที่ต้องการปิด หรือกำหนดช่วงเวลาเงียบ\n\n"

        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**💡 Tips & Tricks**\n\n"
        "• ⚡ พิมพ์ `/` ใน Telegram = เห็นเมนูคำสั่งอัตโนมัติ\n"
        "• ⭐ กด Watchlist หลังวิเคราะห์ → รับ daily summary ทุกเช้า\n"
        "• 🔔 PRO: ตั้ง `/setalert` ทิ้งไว้ ไม่ต้องเฝ้ากราฟเอง\n"
        "• 🎁 เติมโค้ดโปรโมฯ ก่อนสมัครเพื่อประหยัด\n"
        "• 🤝 ชวนเพื่อน 3 คน = +10 วัน VIP ฟรี\n"
        "• 📊 Track Record (`/track`) ดูได้ทุก tier — ไม่ต้องสมัคร\n"
        "• 🔥 เปิดบอททุกวันเพื่อ streak reward (7 วัน = +1 วัน VIP)\n"
        "• 🌐 Web Dashboard สะดวกสำหรับพิมพ์พอร์ตเยอะ ๆ\n"
        "• 📱 เปิด Hub menu เพื่อดูฟีเจอร์ทั้งหมดในปุ่มเดียว\n\n"

        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**📖 คำศัพท์เทคนิค (อ่านง่ายๆ)**\n"
        "_เจอใน report Apexify บ่อยๆ — เก็บไว้ดูทุกครั้งที่งง_\n\n"

        "🌡️ **RSI** _(Relative Strength Index)_\n"
        "วัดความ \"ตึง\" ของราคา 0-100\n"
        "• > 70 = ตึงเกิน (Overbought) — อาจปรับลง\n"
        "• < 30 = ของถูก (Oversold) — อาจรีบาวด์\n"
        "• 40-60 = ปกติ\n\n"

        "⚡ **MACD** _(Moving Average Convergence Divergence)_\n"
        "ดูแรง momentum เปรียบเทียบ EMA สั้น vs ยาว\n"
        "• MACD > Signal line = มีแรง buy\n"
        "• MACD < Signal line = แรง buy หาย/มีแรงขาย\n\n"

        "✨ **Golden Cross**\n"
        "EMA50 ตัด EMA200 ขึ้น = signal เริ่มเทรนด์ขาขึ้นใหญ่ (bullish)\n\n"

        "💀 **Death Cross**\n"
        "EMA50 ตัด EMA200 ลง = signal เริ่มเทรนด์ขาลงใหญ่ (bearish)\n\n"

        "📈 **EMA20 / EMA50 / EMA200**\n"
        "เส้นเฉลี่ยราคา 20/50/200 วันที่ผ่านมา\n"
        "• ราคา > EMA = เทรนด์ขึ้น\n"
        "• ราคา < EMA = เทรนด์ลง\n\n"

        "🟢 **แนวรับ (Support)** = ราคาที่มักจะหยุดลง (มี buyer)\n"
        "🔴 **แนวต้าน (Resistance)** = ราคาที่มักจะหยุดขึ้น (มี seller)\n\n"

        "🛑 **SL (Stop Loss)** = ราคาตัดขาดทุน — ออกถ้าผิดทาง\n"
        "🎯 **TP (Take Profit)** = ราคาเป้าหมาย — ออกตอนกำไร\n\n"

        "⚖️ **R:R Ratio** _(Risk-Reward)_\n"
        "กำไรเป้า ÷ ขาดทุนเสี่ยง\n"
        "• > 2:1 = ดี (เสี่ยง 1 ได้ 2)\n"
        "• < 1:1 = แย่ (เสี่ยงเกินกำไร — หลีกเลี่ยง)\n\n"

        "🔵 **Bollinger Bands**\n"
        "ช่องราคาบน/ล่าง วัด volatility\n"
        "• ทะลุ band บน = pump/overextended\n"
        "• ทะลุ band ล่าง = panic/oversold\n\n"

        "🟡 **POC (Point of Control)**\n"
        "ราคาที่มีการซื้อขายหนาแน่นที่สุด → เป็น \"แม่เหล็ก\" ของราคา\n\n"

        "🎯 **Conviction Score** _(Apexify exclusive)_\n"
        "คะแนน 0-100% ความมั่นใจของ Apexify\n"
        "ดูจาก: bias alignment + volatility + RSI + volume confirmation\n\n"

        "📊 **Volume Ratio**\n"
        "Vol วันนี้ ÷ Vol เฉลี่ย 20 วัน\n"
        "• > 2x = vol สูงผิดปกติ → institutional interest\n"
        "• < 0.5x = vol แห้ง → ไม่มีคนสนใจ\n\n"

        "🌅 **Pre-Market** = เทรดก่อน 9:30 ET (premarket 4:00-9:30 ET)\n"
        "🌃 **After-Hours** = เทรดหลัง 16:00 ET (16:00-20:00 ET)\n"
        "⚠️ Extended hours: vol น้อย ราคาผันผวนสูง\n\n"

        "🐳 **Cluster Buy** _(Smart Money signal)_\n"
        "ตอน insider (ผู้บริหาร/บอร์ด) หลายคนซื้อหุ้นตัวเดียวกันในช่วงสั้นๆ\n"
        "→ signal สำคัญที่ \"คนใน\" เห็น opportunity (SEC Form 4)\n\n"

        "📰 **Gap Up / Gap Down**\n"
        "ราคาเปิดวันนี้สูง/ต่ำกว่าราคาปิดเมื่อวานเยอะ ≥3%\n"
        "→ news/earnings/catalyst ทำให้ market พรุ่งนี้ตอบสนอง\n\n"

        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**📞 ติดต่อ / รายงานปัญหา**\n"
        "หากพบปัญหาหรือมีคำแนะนำ ส่งข้อความถึงแอดมินได้โดยตรง\n"
        "เรายินดีรับฟังและปรับปรุงอย่างต่อเนื่องครับ 🙏\n\n"

        "_⚠️ ข้อมูลและรายงานทั้งหมดในระบบจัดทำขึ้นเพื่อประกอบการพิจารณาเท่านั้น มิใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลและใช้ดุลยพินิจของตนเองก่อนตัดสินใจลงทุน_"
    )
    if str(user_id) == str(ADMIN_ID):
        msg += (
            "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            "**👑 Admin Commands** _(เห็นเฉพาะ admin)_\n\n"

            "*📊 จัดการ User & Subscription*\n"
            "`/addrole [uid] [vip/pro] [days]` — เพิ่ม role ให้ user\n"
            "`/gencode [days] [uses] [vip/pro]` — สร้างโค้ด (ระบบ gen ชื่อ)\n"
            "`/ban [uid]` / `/unban [uid]` — จัดการ user\n"
            "`/users_pro` — list VIP/PRO ทั้งหมด + วันหมด\n"
            "`/user_history [uid]` — ดูประวัติ activity ของ user\n\n"

            "*📈 สถิติ & Performance*\n"
            "`/stats` — สถิติ user/รายได้\n"
            "`/performance` — ผลกำไร/ขาดทุนของ AI plans\n"
            "`/perf_stats` — สรุป latency/throughput ของระบบ\n"
            "`/streak_debug [uid]` — ตรวจ streak counter ของ user\n"
            "`/dm_stats [days=7]` — Auto-DM Cron performance (activation/winback conversion)\n"
            "`/user_log [uid]` — Subscription history timeline (audit trail)\n\n"

            "*🤝 Referral Review*\n"
            "`/pending_refs` — list (พร้อม candidate match auto)\n"
            "`/award_ref [pending_id] [referrer_uid]` — อนุมัติ + ให้รางวัล\n"
            "`/del_pending [pending_id]` — ลบ submission ผิด/spam\n"
            "`/finduser [ชื่อ]` — ค้นหา user_id จากชื่อ\n"
            "`/reset_trial [uid]` — รีเซ็ต free_trial flag (refund/support)\n"
            "_💡 ลูกค้าใส่ user\\_id ตัวเลข → auto-credit ทันที (ไม่เข้า pending)_\n\n"

            "*📢 Broadcast & Force*\n"
            "`/broadcast [msg]` — ส่งข้อความทุก active user\n"
            "`/force_news flash/digest` — บรอดแคสต์ข่าวทันที\n"
            "`/force_weekly` — บรอดแคสต์ Weekly Digest ทันที\n"
            "`/mock_alert [symbol] [type]` — จำลอง alert ทดสอบ\n"
            "`/breaking_test` — ทดสอบ flow Breaking News\n\n"

            "*🛠 System*\n"
            "`/maintenance` — toggle maintenance mode\n"
            "`/force_backup` — backup database ทันที\n"
            "`/system_health` — สถานะเซิร์ฟเวอร์ + memory\n"
            "`/cleanup_logs [days=90]` — ลบ log เก่าใน DB\n"
        )

    # Dashboard CTA — push คนที่อ่าน manual ลึก → ลอง dashboard
    _manual_kb = InlineKeyboardMarkup()
    _manual_btn = _dashboard_cta_button(user_id, "🌐 เปิด Dashboard (ใช้ฟีเจอร์ง่ายกว่า)", src="manual_cmd", next_path="/")
    if _manual_btn:
        _manual_kb.add(_manual_btn)

    # 🌟 ถ้ายาวเกิน Telegram limit → แบ่งเป็น 2-3 messages
    # เริ่มที่ 4096 limit แต่ใช้ 3900 เป็น margin กัน parse_mode overhead
    TG_LIMIT = 3900
    if len(msg) <= TG_LIMIT:
        bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=_manual_kb if _manual_btn else None)
    else:
        workflow_marker = "━━━━━━━━━━━━━━━━━━━━━\n**🌟 Workflow"
        admin_marker = "━━━━━━━━━━━━━━━━━━━━━\n**👑 Admin Commands**"

        workflow_at = msg.find(workflow_marker)
        admin_at = msg.find(admin_marker)

        parts: list[str] = []
        if workflow_at > 0 and admin_at > 0:
            # 3 ส่วน: public → workflow+FAQ → admin
            parts = [
                msg[:workflow_at],
                "📖 **คู่มือ (ต่อ)**\n\n" + msg[workflow_at:admin_at],
                "👑 **Admin Section**\n\n" + msg[admin_at:],
            ]
        elif workflow_at > 0:
            # 2 ส่วน: public → workflow+FAQ (ไม่มี admin section)
            parts = [
                msg[:workflow_at],
                "📖 **คู่มือ (ต่อ)**\n\n" + msg[workflow_at:],
            ]
        else:
            parts = [msg[:TG_LIMIT]]

        def _safe_send_part(chat_id, content, is_first=False):
            """Send + fallback to plain text ถ้า markdown break (กัน admin section หายเงียบๆ)"""
            try:
                if is_first:
                    bot.reply_to(message, content, parse_mode="Markdown")
                else:
                    bot.send_message(chat_id, content, parse_mode="Markdown")
            except Exception as _err:
                print(f"[manual] markdown send failed, retrying plain: {_err}", flush=True)
                try:
                    if is_first:
                        bot.reply_to(message, content)
                    else:
                        bot.send_message(chat_id, content)
                except Exception as _err2:
                    print(f"[manual] plain retry failed: {_err2}", flush=True)

        _safe_send_part(message.chat.id, parts[0], is_first=True)
        for extra in parts[1:]:
            # ถ้ายัง > limit → ตัด chunk แบบไม่หาย
            while len(extra) > TG_LIMIT:
                _safe_send_part(message.chat.id, extra[:TG_LIMIT])
                extra = extra[TG_LIMIT:]
            _safe_send_part(message.chat.id, extra)


@bot.message_handler(commands=['addrole'])
def handle_add_role(message):
    if str(message.chat.id) == ADMIN_ID:
        try:
            args = message.text.split()
            target_user = args[1]
            role = args[2].lower()
            days = int(args[3]) if len(args) > 3 else 30
            expiry = add_subscription(
                target_user, role, days,
                source="admin",
                source_detail=f"/addrole by {message.chat.id}",
                meta={"admin_id": str(message.chat.id), "days": days},
            )
            bot.reply_to(message, f"✅ อัปเกรด `{target_user}` เป็น {role.upper()} แล้ว\nหมดอายุ: {expiry}")
        except Exception:
            bot.reply_to(message, "❌ รูปแบบ: /addrole [user_id] [vip/pro] [days]")

def _do_broadcast(message, users, msg_text):
    success, fail = 0, 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 **ประกาศจาก Apexify:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.1)
        except Exception as e:
            err = str(e)
            # Auto-mark inactive ถ้า 403
            if "403" in err or "blocked" in err.lower() or "deactivated" in err.lower():
                try:
                    mark_user_inactive(uid)
                    print(f"[Broadcast] {uid} → inactive")
                except Exception:
                    pass
            try:
                bot.send_message(uid, f"📢 ประกาศจาก Apexify:\n\n{msg_text}")
                success += 1
                time.sleep(0.1)
            except Exception:
                fail += 1
    bot.reply_to(message, f"✅ บรอดแคสต์สำเร็จ: {success} คน\n❌ ล้มเหลว: {fail} คน")

@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID: return
    msg_text = message.text.replace('/broadcast', '').strip()
    if not msg_text: return
    users = get_active_users()
    bot.reply_to(message, f"⏳ กำลังส่งข้อความหาผู้ใช้ {len(users)} คน... (รันอยู่เบื้องหลัง)")
    threading.Thread(target=_do_broadcast, args=(message, users, msg_text), daemon=True).start()


@bot.message_handler(commands=['dm'])
def handle_admin_dm(message):
    """Admin command — ส่ง DM ตรงไปยัง user_id ที่ระบุ
    ใช้: /dm <user_id> <ข้อความ>  (รองรับ newline)
    เพิ่ม 2026-05-15 — สำหรับ DM 18 expired users + future ad hoc
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        return
    # split max 2: ['/dm', '<uid>', '<rest>']
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        bot.reply_to(message, "❓ ใช้: /dm <user_id> <ข้อความ>\nตัวอย่าง: /dm 12345678 สวัสดีครับ")
        return
    target_uid = parts[1].strip()
    msg_text = parts[2]
    try:
        bot.send_message(target_uid, msg_text, parse_mode="Markdown", disable_web_page_preview=True)
        bot.reply_to(message, f"✅ ส่งหา `{target_uid}` เรียบร้อย ({len(msg_text)} chars)", parse_mode="Markdown")
    except Exception as e:
        err = str(e)
        # Fallback to plain text ถ้า Markdown error
        try:
            bot.send_message(target_uid, msg_text.replace("*", "").replace("_", ""), disable_web_page_preview=True)
            bot.reply_to(message, f"⚠️ ส่งหา `{target_uid}` สำเร็จ (plain text — markdown error)", parse_mode="Markdown")
        except Exception as e2:
            bot.reply_to(message, f"❌ ส่งไม่ได้: {e}\n(plain text ก็ fail: {e2})")


def _build_renewal_dm(username, role_before, days_expired, watchlist_n, port_n, tx_n):
    """สร้างข้อความ renewal personalized"""
    greet = f"สวัสดีคุณ {username}" if username and username.strip() else "สวัสดีครับ"
    tier = (role_before or 'pro').upper()
    price = 109 if role_before == 'pro' else 79

    # Data tease — บอกของที่ลูกค้ายังมี
    data_bits = []
    if watchlist_n and watchlist_n > 0:
        data_bits.append(f"Watchlist {watchlist_n} ตัว")
    if port_n and port_n > 0:
        data_bits.append(f"Portfolio {port_n} ตัว")
    if tx_n and tx_n > 0:
        data_bits.append(f"Transactions {tx_n} รายการ")
    data_line = " + ".join(data_bits) + " ของคุณยังอยู่ครบ ✅\n\n" if data_bits else ""

    # Tier-specific benefits
    if role_before == 'pro':
        benefits = (
            "ที่คุณจะกลับมาได้:\n"
            "✅ ไม่จำกัด การวิเคราะห์\n"
            "✅ Entry/TP/SL ตัวเลข + กราฟ annotated\n"
            "✅ 🔔 Pre-Market Movers (20:30 น. ทุกวัน)\n"
            "✅ 🐳 Smart Money Tracker (insider cluster buys)\n"
            "✅ ⚠️ Plan Proximity Warning\n"
            "✅ 🔥 Screener หุ้นเด่น 10 ตัว (225 ตัวคัดมา)"
        )
    else:  # vip
        benefits = (
            "ที่คุณจะกลับมาได้:\n"
            "✅ ไม่จำกัด การวิเคราะห์\n"
            "✅ AI Trend Radar 3 ระยะ + Watch Next\n"
            "✅ 🔔 Pre-Market Movers (20:30 น.)\n"
            "✅ 🌅 Daily Watchlist + P&L Recap (8:00 น.)\n"
            "✅ Morning Briefing + Weekly Digest"
        )

    return (
        f"{greet} 👋\n\n"
        f"แพ็คเกจ {tier} หมดอายุไป {days_expired} วันแล้ว\n"
        f"ตอนนี้ใช้ Free (3 การวิเคราะห์/วัน)\n\n"
        f"{data_line}"
        f"{benefits}\n\n"
        f"💎 ต่อ {tier} {price}฿/เดือน → /payment\n"
        f"🎁 หรือ /freetrial — ลอง PRO 7 วันฟรี (ถ้ายังไม่เคยใช้)\n\n"
        f"มี feedback อยากให้ปรับ ทักได้ตลอดครับ 🙏"
    )


def _do_dm_expired_send(reply_message, rows):
    """ส่ง personalized renewal DM ให้ expired users ทุกคน"""
    success = 0
    fail = 0
    for r in rows:
        uid, role_before, days_expired, username, wl_n, port_n, tx_n = r
        try:
            msg = _build_renewal_dm(username, role_before, days_expired, wl_n, port_n, tx_n)
            bot.send_message(uid, msg, disable_web_page_preview=True)
            success += 1
            time.sleep(1.0)   # rate limit Telegram (30 msg/sec global, 1/sec per chat)
        except Exception as e:
            err = str(e)
            if "403" in err or "blocked" in err.lower() or "deactivated" in err.lower():
                try:
                    mark_user_inactive(uid)
                except Exception:
                    pass
            fail += 1
    try:
        bot.reply_to(reply_message, f"📨 DM Renewal Blast เสร็จ\n✅ ส่งสำเร็จ: {success}\n❌ ล้มเหลว: {fail}")
    except Exception:
        pass


@bot.message_handler(commands=['dm_expired'])
def handle_dm_expired(message):
    """Admin command — DM ลูกค้าที่ expired recently เพื่อขอ renew
    ใช้: /dm_expired         — preview รายชื่อ + รายละเอียด (ไม่ส่ง)
         /dm_expired confirm — ส่ง personalized DM ให้ทุกคนใน list
    """
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        return

    # ตัด keyword "confirm" ออกจาก args
    parts = message.text.split()
    is_confirm = len(parts) > 1 and parts[1].lower() == 'confirm'

    # Query expired users (7 วันที่ผ่านมา)
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT ON (sh.user_id)
                sh.user_id,
                sh.role_before,
                EXTRACT(DAY FROM (NOW() - NULLIF(sh.expiry_before, '')::timestamptz))::int AS days_expired,
                COALESCE(u.username, '') AS username,
                COALESCE((SELECT COUNT(*) FROM user_watchlist WHERE user_id::text = sh.user_id), 0) AS wl_n,
                COALESCE((SELECT COUNT(*) FROM portfolios WHERE user_id = sh.user_id), 0) AS port_n,
                COALESCE((SELECT COUNT(*) FROM transactions WHERE user_id = sh.user_id AND deleted_at IS NULL), 0) AS tx_n
            FROM subscription_history sh
            LEFT JOIN users u ON u.user_id = sh.user_id
            WHERE sh.action_type = 'expire'
              AND sh.created_at >= NOW() - INTERVAL '7 days'
              AND sh.expiry_before IS NOT NULL
              AND COALESCE(NULLIF(TRIM(sh.expiry_before), ''), '') <> ''
            ORDER BY sh.user_id, sh.created_at DESC
        """)
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ DB error: {e}")
        return

    if not rows:
        bot.reply_to(message, "ไม่พบ expired users ใน 7 วันที่ผ่านมา")
        return

    # Preview mode
    if not is_confirm:
        lines = [f"🔍 พบ {len(rows)} expired users (last 7 days):\n"]
        for r in rows[:25]:
            uid, role, days, username, wl, port, tx = r
            data_bits = []
            if wl > 0: data_bits.append(f"wl={wl}")
            if port > 0: data_bits.append(f"port={port}")
            if tx > 0: data_bits.append(f"tx={tx}")
            data_str = " " + " ".join(data_bits) if data_bits else ""
            uname = username or "(no name)"
            lines.append(f"• `{uid}` {uname} ({role.upper()}, {days}d){data_str}")
        lines.append(f"\n➡️ พิมพ์ `/dm_expired confirm` เพื่อส่ง personalized DM ทั้งหมด")
        bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")
        return

    # Confirmed — send all
    bot.reply_to(message, f"⏳ กำลังส่ง {len(rows)} DM... (~{len(rows)} วินาที) — รันอยู่เบื้องหลัง")
    threading.Thread(target=_do_dm_expired_send, args=(message, rows), daemon=True).start()

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    if str(message.chat.id) != ADMIN_ID: return
    try:
        snapshot = get_user_stats_snapshot()
        msg = (
            "📊 **สถิติการใช้งาน Apexify (อัปเดตสถานะล่าสุด)** 📊\n\n"
            f"👥 **ผู้ใช้งานทั้งหมด:** {snapshot['total_users']} คน\n"
            f"🆓 **สายฟรี:** {snapshot['free_users']} คน\n"
            f"💎 **ระดับ VIP (Active):** {snapshot['vip_users']} คน\n"
            f"👑 **ระดับ PRO (Active):** {snapshot['pro_users']} คน\n\n"
            f"💰 **ประมาณการรายได้ขั้นต่ำ:** {snapshot['estimated_monthly_revenue']:,.2f} บาท/เดือน\n"
            f"*(หมายเหตุ: ระบบตัดผู้ที่หมดอายุแพ็กเกจออกจากการคำนวณรายได้แล้ว)*"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")

@bot.message_handler(commands=['performance'])
def handle_performance(message):
    if str(message.chat.id) != ADMIN_ID: return
    status_msg = bot.reply_to(message, "⏳ กำลังดึงประวัติและคำนวณผลกำไร/ขาดทุน...")
    try:
        snapshot = get_performance_snapshot(limit=15)

        if not snapshot["entries"]:
            bot.edit_message_text("❌ ยังไม่มีประวัติการแจ้งเตือนในระบบครับ", message.chat.id, status_msg.message_id)
            return

        report_text = "🎯 **สรุปผลงานความแม่นยำ Apexify**\n\n"
        report_text += (
            f"• ปิดผลแล้ว: **{snapshot.get('resolved_count', 0)}** สัญญาณ\n"
            f"• รอปิดผล: **{snapshot.get('pending_count', 0)}** สัญญาณ\n"
            f"• Win Rate: **{snapshot.get('win_rate', 0):.2f}%**\n"
            f"• Average Edge: **{snapshot.get('average_edge_pct', 0):+.2f}%**\n\n"
        )
        for item in snapshot["entries"]:
            status_label = item.get("status_label", "PENDING")
            emoji = "✅" if status_label == "WIN" else ("❌" if status_label == "LOSS" else "⏳")
            performance_text = f"{item['diff_pct']:+.2f}%" if item.get("diff_pct") is not None else "รอปิดผล"
            resolved_price = f"{item['current_price']:.2f}" if item.get("current_price") is not None else "-"
            report_text += (
                f"{emoji} **{item['symbol']}** ({item['alert_type']}) [{item.get('horizon_label', '-')}]\n"
                f"   สถานะ: {status_label} | มุมมอง: {item.get('direction_label', '-')}\n"
                f"   ราคาเตือน: {item['start_price']:.2f} | ราคาปิดผล: {resolved_price}\n"
                f"   Edge: {performance_text} | ครบกำหนด: {item.get('evaluation_due_at', '-')}\n\n"
            )

        if snapshot.get("breakdown"):
            report_text += "📊 **แยกตามประเภทสัญญาณ**\n"
            for item in snapshot["breakdown"][:4]:
                report_text += (
                    f"• {item['alert_type']}: {item['win_rate']:.1f}% "
                    f"จาก {item['resolved_count']} สัญญาณ "
                    f"(avg edge {item['average_edge_pct']:+.2f}%)\n"
                )
        bot.edit_message_text(report_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[track_record] {e}", flush=True)
        bot.edit_message_text(friendly_error("คำนวณ Track Record ไม่สำเร็จ"), message.chat.id, status_msg.message_id)

@bot.message_handler(content_types=['photo'])
def handle_payment_slip_check(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    progress_msg = bot.reply_to(message, "🧾 Apexify กำลังตรวจสอบสลิปโอนเงิน...")
        
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        slip_result = verify_payment_slip(downloaded_file, filename=f"telegram-slip-{message.message_id}.jpg")
        status = slip_result.get('status')
        ref_no = str(slip_result.get('trans_ref') or '').strip()
        amount = float(slip_result.get('amount') or 0)
        provider_code = slip_result.get('provider_code')
        provider_message = str(slip_result.get('message') or '').strip()

        if status == 'verified':
            if not ref_no:
                bot.edit_message_text(
                    "⚠️ Apexify ตรวจสลิปได้แล้ว แต่ไม่พบเลขอ้างอิงธุรกรรม กรุณาส่งสลิปใหม่ที่เห็นข้อมูลชัดเจนครับ",
                    message.chat.id,
                    progress_msg.message_id,
                )
                bot.send_message(
                    ADMIN_ID,
                    f"⚠️ **SlipOK ตรวจผ่านแต่ ref หาย** User `{user_id}` ยอด `{amount:,.2f}` บาท",
                    parse_mode="Markdown",
                )
                return

            # Subscription packages (role + expiry)
            slip_packages = {
                1090: ('pro', 365, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายปี)**\n⏰ หมดอายุ: {expiry}"),
                790: ('vip', 365, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายปี)**\n⏰ หมดอายุ: {expiry}"),
                109: ('pro', 30, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายเดือน)**\n⏰ หมดอายุ: {expiry}"),
                79: ('vip', 30, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายเดือน)**\n⏰ หมดอายุ: {expiry}"),
            }
            # 🎟 Top-up packages (เติม credits ไม่เปลี่ยน role)
            topup_packages = {
                20: 10,  # 20฿ = 10 credits (= 2฿/ครั้ง)
            }
            # 🎁 Flash discount — รับเฉพาะ user ที่ยังอยู่ใน 30 นาทีของ flash window
            # 🛡 NOTE: ห้าม consume_flash_discount ที่นี่ — defer จนกว่า claim_slip จะ success
            # (ป้องกัน user เสีย flash window ฟรีถ้า claim ล้มเหลวเช่น downgrade_blocked)
            is_flash_payment = False
            if amount in (FLASH_VIP_AMOUNT, FLASH_PRO_AMOUNT):
                if not is_flash_active(user_id):
                    bot.edit_message_text(
                        f"❌ ยอด {amount}฿ ใช้ได้เฉพาะใน {FLASH_WINDOW_MINUTES} นาทีหลังเปิด flash discount\n\n"
                        f"flash discount หมดเวลาแล้ว กรุณาโอนตามราคาปกติ:\n"
                        f"• 79฿ = VIP รายเดือน\n"
                        f"• 109฿ = PRO รายเดือน\n\n"
                        f"_(หรือติดต่อแอดมินถ้าโอนภายในเวลาแล้วระบบไม่อ่าน)_",
                        message.chat.id,
                        progress_msg.message_id,
                        parse_mode="Markdown",
                    )
                    bot.send_message(
                        ADMIN_ID,
                        f"⚠️ User `{user_id}` โอน flash {amount}฿ แต่ window หมด — Ref `{ref_no}`",
                        parse_mode="Markdown",
                    )
                    return
                # รับเป็น VIP/PRO 30 วัน — เพิ่มเข้า slip_packages dynamically
                if amount == FLASH_VIP_AMOUNT:
                    slip_packages[FLASH_VIP_AMOUNT] = (
                        'vip', 30,
                        "🎉 **Flash 20% สำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายเดือน)** — ประหยัด 16฿\n⏰ หมดอายุ: {expiry}"
                    )
                else:
                    slip_packages[FLASH_PRO_AMOUNT] = (
                        'pro', 30,
                        "🎉 **Flash 20% สำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายเดือน)** — ประหยัด 22฿\n⏰ หมดอายุ: {expiry}"
                    )
                is_flash_payment = True
                # consume_flash_discount จะรันหลัง claim_slip success ด้านล่าง

            if amount in topup_packages:
                # === Top-up flow ===
                credits = topup_packages[amount]
                claim_status, new_balance = claim_slip_and_add_topup(user_id, ref_no, credits, amount=amount)
                if claim_status == "duplicate":
                    bot.edit_message_text(
                        "❌ **สลิปนี้ถูกใช้งานไปแล้ว!**\nไม่อนุญาตให้ใช้สลิปซ้ำครับ",
                        message.chat.id,
                        progress_msg.message_id,
                        parse_mode="Markdown",
                    )
                    bot.send_message(
                        ADMIN_ID,
                        f"🚨 **ทุจริต!** User `{user_id}` ส่งสลิปซ้ำ Top-up (Ref: `{ref_no}`)",
                        parse_mode="Markdown",
                    )
                    return
                if claim_status != "success":
                    bot.edit_message_text(
                        "⚠️ Apexify ตรวจสอบสลิปได้แล้ว แต่ยังไม่สามารถเติม Top-up ได้ กรุณาลองใหม่อีกครั้ง",
                        message.chat.id,
                        progress_msg.message_id,
                    )
                    bot.send_message(
                        ADMIN_ID,
                        f"⚠️ **Top-up ล้มเหลวหลัง SlipOK ผ่าน** User `{user_id}` Ref `{ref_no}`",
                        parse_mode="Markdown",
                    )
                    return
                bot.edit_message_text(
                    (
                        f"🎉 **เติม Top-up สำเร็จ!**\n"
                        f"🎟 ได้รับเพิ่ม **+{credits} ครั้ง**\n"
                        f"💼 ยอดคงเหลือ: **{new_balance} ครั้ง**\n\n"
                        f"_ระบบจะหัก top-up หลังคุณใช้ครบโควต้าฟรีรายวัน_"
                    ),
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                )
                bot.send_message(
                    ADMIN_ID,
                    f"🎟 **Top-up:** User `{user_id}` +{credits} ครั้ง (ยอด: {new_balance}) Ref `{ref_no}`",
                    parse_mode="Markdown",
                )
                return

            package_info = slip_packages.get(amount)

            # 🎟 Code-based discount — ก่อน reject ตรวจ user's discount window จาก redeemed code
            # (e.g., user redeem NEWYEAR30 → discount_amount_vip=55 → user โอน 55฿ → match)
            if not package_info:
                try:
                    user_disc = get_user_discount(user_id)
                except Exception as _e:
                    print(f"[CodeDiscount] get err: {_e}", flush=True)
                    user_disc = None
                if user_disc:
                    int_amount = int(round(amount))
                    if user_disc.get("vip_amount") == int_amount:
                        package_info = ('vip', 30, "🎉 **ส่วนลดจากโค้ดสำเร็จ!** ได้รับ **💎 VIP (รายเดือน)** — โค้ด `" + user_disc.get("code", "?") + "`\n⏰ หมดอายุ: {expiry}")
                        # ปิด discount window กันใช้ซ้ำ
                        try: consume_user_discount(user_id)
                        except Exception: pass
                    elif user_disc.get("pro_amount") == int_amount:
                        package_info = ('pro', 30, "🎉 **ส่วนลดจากโค้ดสำเร็จ!** ได้รับ **👑 PRO (รายเดือน)** — โค้ด `" + user_disc.get("code", "?") + "`\n⏰ หมดอายุ: {expiry}")
                        try: consume_user_discount(user_id)
                        except Exception: pass

            if not package_info:
                # 📜 Log abnormal slip to subscription_history (audit trail)
                try:
                    from database import log_subscription_event
                    log_subscription_event(
                        user_id=user_id,
                        action_type="abnormal_slip",
                        source="slip",
                        source_detail=f"unmatched amount {amount:.2f}฿",
                        meta={
                            "ref_no": str(ref_no),
                            "amount": float(amount),
                            "sender": slip_result.get('sender_display_name', '-'),
                        },
                    )
                except Exception as _e:
                    print(f"[abnormal_slip] log err: {_e}", flush=True)

                # Better error message — list packages + Dashboard CTA + admin contact
                err_kb = InlineKeyboardMarkup()
                _dash_btn = _dashboard_cta_button(user_id, "🌐 ดู Package ใน Dashboard", src="abnormal_slip", next_path="/")
                if _dash_btn:
                    err_kb.add(_dash_btn)
                err_kb.add(InlineKeyboardButton("💬 ติดต่อ Admin", url=f"tg://user?id={ADMIN_ID}"))

                bot.edit_message_text(
                    (
                        f"❌ **ยอด {amount:,.2f}฿ ไม่ตรงกับ package ที่เปิดอยู่**\n\n"
                        f"💎 *VIP* = 79฿/เดือน · 790฿/ปี (ฟรี 2 เดือน)\n"
                        f"👑 *PRO* = 109฿/เดือน · 1,090฿/ปี (ฟรี 2 เดือน)\n"
                        f"🎟 *Top-up* = 20฿ (10 ครั้ง)\n\n"
                        f"_ถ้า redeem โค้ดส่วนลดมาแล้ว ตรวจให้แน่ใจว่ายังอยู่ในเวลาที่กำหนด_\n"
                        f"_หรือกดติดต่อ admin ถ้าโอนแล้วระบบไม่อ่าน_"
                    ),
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                    reply_markup=err_kb if _dash_btn else None,
                )
                bot.send_message(
                    ADMIN_ID,
                    (
                        f"⚠️ **ยอดผิดปกติจาก SlipOK** User `{user_id}` โอน `{amount:,.2f}` บาท\n"
                        f"Ref: `{ref_no}`\n"
                        f"ผู้โอน: `{slip_result.get('sender_display_name') or '-'}`\n"
                        f"_log แล้วใน `/user_log {user_id}`_"
                    ),
                    parse_mode="Markdown",
                )
                return

            target_role, subscription_days, message_template = package_info
            # 📊 Tag payment type สำหรับ analytics — flash vs annual vs monthly
            _payment_type_map = {
                FLASH_VIP_AMOUNT: 'flash_vip',
                FLASH_PRO_AMOUNT: 'flash_pro',
                79: 'monthly_vip',
                109: 'monthly_pro',
                790: 'annual_vip',
                1090: 'annual_pro',
            }
            _payment_type = _payment_type_map.get(amount, 'standard')
            claim_status, expiry = claim_slip_and_add_subscription(
                user_id,
                ref_no,
                target_role,
                subscription_days,
                payment_type=_payment_type,
                amount=amount,
            )
            if claim_status == "duplicate":
                bot.edit_message_text(
                    "❌ **สลิปนี้ถูกใช้งานไปแล้ว!**\nไม่อนุญาตให้ใช้สลิปซ้ำครับ",
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                )
                bot.send_message(
                    ADMIN_ID,
                    f"🚨 **ทุจริต!** User `{user_id}` ส่งสลิปซ้ำ (Ref: `{ref_no}`)",
                    parse_mode="Markdown",
                )
                return
            if claim_status == "downgrade_blocked":
                bot.edit_message_text(
                    (
                        "🛑 **คุณยังเป็น PRO อยู่ไม่สามารถซื้อ VIP ได้**\n\n"
                        f"PRO ของคุณหมดอายุ: `{expiry}`\n"
                        "ระบบไม่อัปเดตสิทธิ์เพื่อกัน PRO ของคุณหายครับ\n\n"
                        "💬 ทีมงานจะติดต่อคืนเงินภายใน 24 ชม."
                    ),
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                )
                bot.send_message(
                    ADMIN_ID,
                    (
                        f"🛑 **DOWNGRADE BLOCKED — ต้องคืนเงิน!**\n"
                        f"User `{user_id}` โอน `{amount:,.2f}` บาท (VIP) ทั้งที่ยังเป็น PRO อยู่\n"
                        f"PRO หมดอายุ: `{expiry}`\n"
                        f"Ref: `{ref_no}`\n"
                        f"ผู้โอน: `{slip_result.get('sender_display_name') or '-'}`\n"
                        f"➡️ ติดต่อคืนเงินผู้ใช้"
                    ),
                    parse_mode="Markdown",
                )
                return

            if claim_status != "success" or not expiry:
                bot.edit_message_text(
                    "⚠️ Apexify ตรวจสอบสลิปได้แล้ว แต่ยังไม่สามารถอัปเดตสิทธิ์ได้ กรุณาลองใหม่อีกครั้ง",
                    message.chat.id,
                    progress_msg.message_id,
                )
                bot.send_message(
                    ADMIN_ID,
                    f"⚠️ **อัปเดตสิทธิ์ไม่สำเร็จหลัง SlipOK ผ่าน** User `{user_id}` Ref `{ref_no}`",
                    parse_mode="Markdown",
                )
                return

            # 🛡 Flash window — consume เฉพาะตอน claim_slip success (กัน user เสีย flash ฟรีถ้า claim fail)
            if locals().get('is_flash_payment', False):
                try:
                    consume_flash_discount(user_id)
                except Exception as _e:
                    print(f"[FlashConsume] err: {_e}", flush=True)

            msg_text = message_template.format(expiry=expiry)
            bot.delete_message(message.chat.id, progress_msg.message_id)
            bot.reply_to(message, msg_text, parse_mode="Markdown")
            bot.send_message(
                ADMIN_ID,
                (
                    f"💰 เงินเข้า! User `{user_id}` โอน `{amount:,.2f}` บาท\n"
                    f"Ref: `{ref_no}`\n"
                    f"ผู้โอน: `{slip_result.get('sender_display_name') or '-'}`"
                ),
                parse_mode="Markdown",
            )
            return

        if status == 'duplicate':
            bot.edit_message_text(
                "❌ **สลิปนี้ถูกใช้งานไปแล้ว!**\nไม่อนุญาตให้ใช้สลิปซ้ำครับ",
                message.chat.id,
                progress_msg.message_id,
                parse_mode="Markdown",
            )
            bot.send_message(
                ADMIN_ID,
                f"🚨 **SlipOK แจ้งสลิปซ้ำ** User `{user_id}` Ref `{ref_no or '-'}`",
                parse_mode="Markdown",
            )
            return

        if status == 'receiver_mismatch':
            bot.edit_message_text(
                "❌ **สลิปนี้โอนไปยังบัญชีปลายทางไม่ตรงกับร้าน**\nกรุณาตรวจสอบบัญชีรับเงินและส่งสลิปใหม่ครับ",
                message.chat.id,
                progress_msg.message_id,
                parse_mode="Markdown",
            )
            bot.send_message(
                ADMIN_ID,
                (
                    f"🚨 **บัญชีปลายทางไม่ตรง** User `{user_id}`\n"
                    f"Ref: `{ref_no or '-'}`\n"
                    f"ข้อความ: `{provider_message or '-'}`"
                ),
                parse_mode="Markdown",
            )
            return

        if status == 'delayed':
            retry_after_minutes = slip_result.get('retry_after_minutes') or 8
            bot.edit_message_text(
                (
                    f"⏳ **สลิปนี้ยังอยู่ระหว่างรอธนาคารยืนยัน**\n"
                    f"กรุณารอประมาณ {retry_after_minutes} นาที แล้วส่งสลิปเดิมมาใหม่อีกครั้งครับ"
                ),
                message.chat.id,
                progress_msg.message_id,
                parse_mode="Markdown",
            )
            return

        if status in {'invalid_slip', 'amount_mismatch'}:
            # 📷 Chart Vision fallback — ถ้า slip ใช้ไม่ได้ ลอง treat as chart screenshot
            # Free → upsell, VIP/PRO → run Gemini Vision อ่าน chart ให้
            if status == 'invalid_slip':
                try:
                    role, _ = check_subscription(user_id)
                except Exception:
                    role = 'free'
                if role in ('vip', 'pro') or user_id == ADMIN_ID:
                    bot.edit_message_text(
                        "📷 ดูเหมือนรูปนี้ไม่ใช่สลิป — Apexify กำลังลองอ่านเป็น Chart...",
                        message.chat.id,
                        progress_msg.message_id,
                    )
                    try:
                        from ai_analyzer import analyze_chart_image, render_chart_vision_report
                        parsed = analyze_chart_image(downloaded_file)
                        rendered = render_chart_vision_report(parsed)
                        if rendered:
                            bot.edit_message_text(
                                rendered,
                                message.chat.id,
                                progress_msg.message_id,
                                parse_mode="Markdown",
                            )
                            return
                    except Exception as _e:
                        print(f"[ChartVision] err for {user_id}: {type(_e).__name__}: {str(_e)[:80]}", flush=True)
                    bot.edit_message_text(
                        "❌ Apexify อ่าน chart นี้ไม่ได้ครับ ลองส่งรูปใหม่ที่ชัดเจนกว่านี้",
                        message.chat.id,
                        progress_msg.message_id,
                    )
                    return
                # Free user — upsell chart vision เป็น VIP/PRO feature
                upsell_kb = InlineKeyboardMarkup(row_width=1)
                upsell_kb.add(
                    InlineKeyboardButton("🆓 ทดลอง PRO 7 วันฟรี — อ่าน chart ได้", callback_data="menu_freetrial"),
                )
                upsell_kb.add(
                    InlineKeyboardButton("💎 สมัคร VIP/PRO", callback_data="menu_vip"),
                )
                bot.edit_message_text(
                    (
                        "📷 *Apexify อ่าน Chart ได้!*\n\n"
                        "ส่งรูป chart จาก Bualuang/Settrade/TradingView/อื่นๆ → Apexify "
                        "วิเคราะห์ trend, แนวรับ/แนวต้าน, pattern, indicators ที่เห็น\n\n"
                        "🔒 ฟีเจอร์นี้สำหรับ *VIP / PRO* เท่านั้น\n"
                        "_(หรือทดลอง PRO 7 วันฟรี ใช้ได้ทันที)_"
                    ),
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                    reply_markup=upsell_kb,
                )
                return
            # amount_mismatch — รูปเป็น slip จริง แต่ยอดผิด → ข้อความเดิม
            bot.edit_message_text(
                "❌ รูปนี้ไม่ใช่สลิปโอนเงินที่ตรวจสอบได้ หรือข้อมูลบนสลิปไม่ถูกต้องครับ",
                message.chat.id,
                progress_msg.message_id,
            )
            return

        if status in {'auth_or_quota_error', 'provider_error', 'network_error', 'config_error'}:
            bot.edit_message_text(
                "⚠️ ระบบตรวจสลิปอัตโนมัติขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งในภายหลังครับ",
                message.chat.id,
                progress_msg.message_id,
            )
            bot.send_message(
                ADMIN_ID,
                (
                    f"⚠️ **SlipOK error** status=`{status}` code=`{provider_code}`\n"
                    f"User `{user_id}`\n"
                    f"Message: `{provider_message or '-'}`"
                ),
                parse_mode="Markdown",
            )
            return

        bot.edit_message_text(
            "⚠️ Apexify ไม่สามารถยืนยันสลิปนี้ได้ กรุณาลองใหม่อีกครั้งครับ",
            message.chat.id,
            progress_msg.message_id,
        )
    except Exception as e:
        bot.edit_message_text("⚠️ Apexify ไม่สามารถอ่านสลิปได้ โปรดถ่ายให้ชัดเจนอีกครั้ง", message.chat.id, progress_msg.message_id)

# ==========================================
# 🌟 ระบบปุ่มกด Inline
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('quick_'))
def quick_action_callbacks(call):
    """Contextual quick-action buttons after analysis"""
    user_id = str(call.message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    bot.answer_callback_query(call.id)

    parts = call.data.split('_', 2)  # quick_fund_AAPL
    if len(parts) < 3:
        return
    action = parts[1]
    symbol = parts[2]

    # Fake message object to reuse existing handlers
    class FakeMessage:
        def __init__(self, chat_id, text):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(id=chat_id)
            self.from_user = SimpleNamespace(id=chat_id)
            self.text = text
            self.message_id = call.message.message_id

    if action == 'fund':
        if role not in ('vip', 'pro') and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 Fundamentals = ฟีเจอร์ VIP/PRO")
            return
        fake = FakeMessage(int(user_id), f"/fund {symbol}")
        handle_fundamentals(fake)

    elif action == 'earnings':
        if role not in ('vip', 'pro') and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 วิเคราะห์งบการเงิน = ฟีเจอร์ VIP/PRO")
            return
        fake = FakeMessage(int(user_id), f"/earnings {symbol}")
        handle_earnings(fake)

    elif action == 'compare':
        if role != 'pro' and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 Stock Comparison = ฟีเจอร์ PRO เท่านั้น")
            return
        bot.send_message(user_id,
            f"⚖️ *เปรียบเทียบ {symbol} กับหุ้นอื่น*\n\n"
            f"พิมพ์คำสั่ง: `/compare {symbol} <หุ้น2>`\n"
            f"ตัวอย่าง: `/compare {symbol} MSFT` หรือ `/compare {symbol} NVDA AMD`",
            parse_mode="Markdown")

    elif action == 'ask':
        if role != 'pro' and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 Apexify Q&A = ฟีเจอร์ PRO เท่านั้น")
            return
        bot.send_message(user_id,
            f"💬 *ถาม Apexify เกี่ยวกับ {symbol}*\n\n"
            f"พิมพ์คำสั่ง: `/ask <คำถาม>`\n"
            f"ตัวอย่าง:\n"
            f"• `/ask ทำไม RSI {symbol} สูง?`\n"
            f"• `/ask {symbol} ควรซื้อตอนไหน`\n"
            f"• `/ask อธิบาย MACD ของ {symbol}`\n\n"
            f"_AI จะใช้ข้อมูลวิเคราะห์ล่าสุดของ {symbol} เป็น context ให้เลย_",
            parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_') or call.data.startswith('delalert_') or call.data.startswith('menu_') or call.data.startswith('hub_') or call.data.startswith('admin_') or call.data.startswith('settings_') or call.data.startswith('tutorial_') or call.data.startswith('qr_pay_') or call.data == 'breaking_toggle' or call.data.startswith('referral_') or call.data.startswith('setalert_'))
def inline_callbacks(call):
    user_id = str(call.message.chat.id)
    if not is_allowed(user_id): return
    role = check_subscription(user_id)
    if str(user_id) == str(ADMIN_ID):
        role = 'pro'
    bot.answer_callback_query(call.id)

    if call.data.startswith('tutorial_analyze_'):
        symbol = call.data.replace('tutorial_analyze_', '').upper()
        load_msg = bot.send_message(user_id, f"🔍 กำลังวิเคราะห์ {symbol}...")
        # 🎁 Tier-aware chart — Free user: ใช้ chart preview (atomic consume 3 ครั้งแรกตลอดชีวิต)
        # VIP: basic chart, PRO: skip (no annotated in tutorial flow)
        chart_preview_consumed = False
        chart_preview_remaining = 0
        if role == 'free' and user_id != ADMIN_ID:
            try:
                consumed, remaining = consume_chart_preview(user_id)
                chart_preview_consumed = consumed
                chart_preview_remaining = remaining
            except Exception as _e:
                print(f"[ChartPreview] tutorial err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)
        # generate chart ถ้าเป็น VIP หรือ free ที่ใช้ preview ได้
        want_chart = (role == 'vip') or chart_preview_consumed
        tech_data, chart, err = _get_cached_analysis(symbol, generate_chart=want_chart)
        if err or not tech_data:
            # 🛡 Refund chart preview ถ้า consume แล้วแต่ดึงข้อมูลไม่ได้
            if chart_preview_consumed:
                try: refund_chart_preview(user_id)
                except Exception: pass
            bot.edit_message_text(f"❌ ไม่สามารถดึงข้อมูล {symbol} ได้", user_id, load_msg.message_id)
            return
        report, _ = generate_apexify_report(tech_data, role=role, user_id=user_id)
        # Free + ใช้ preview → banner: count + urgency เมื่อหมด
        if chart_preview_consumed:
            report = _build_chart_preview_banner(chart_preview_remaining) + report
        correct_symbol = tech_data['symbol']
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton(f"⭐ เพิ่ม {correct_symbol} เข้า Watchlist", callback_data=f"addwatch_{correct_symbol}"))
        kb.add(InlineKeyboardButton("📱 เมนูหลัก", callback_data="hub_home"))
        bot.delete_message(user_id, load_msg.message_id)
        if chart is not None:
            try:
                bot.send_photo(user_id, chart)
            except Exception:
                pass
        try:
            bot.send_message(user_id, report, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            bot.send_message(user_id, report, reply_markup=kb)
        return

    if call.data == 'settings_open' or call.data.startswith('settings_'):
        action = call.data.replace('settings_', '', 1)
        settings = get_user_settings(user_id)

        if action == 'toggle':
            set_user_notifications(user_id, not settings.get("notifications_enabled", True))
        elif action == 'tz_next':
            tz_values = list(ALLOWED_TIMEZONES)
            current_tz = settings.get("timezone", tz_values[0])
            next_tz = tz_values[(tz_values.index(current_tz) + 1) % len(tz_values)] if current_tz in tz_values else tz_values[0]
            set_user_timezone(user_id, next_tz)
        elif action == 'lang_next':
            lang_values = list(ALLOWED_LANGUAGES)
            current_lang = settings.get("language", lang_values[0])
            next_lang = lang_values[(lang_values.index(current_lang) + 1) % len(lang_values)] if current_lang in lang_values else lang_values[0]
            set_user_language(user_id, next_lang)
        elif action == 'digest_next':
            # PRO: 1/4/8/24h — VIP: 4/8/24h เท่านั้น
            if role in ('pro',) or user_id == ADMIN_ID:
                digest_values = list(ALLOWED_DIGEST_FREQUENCIES)
            else:
                digest_values = [f for f in ALLOWED_DIGEST_FREQUENCIES if f >= 4]
            current_digest = int(settings.get("digest_frequency_hours", digest_values[0]))
            next_digest = digest_values[(digest_values.index(current_digest) + 1) % len(digest_values)] if current_digest in digest_values else digest_values[0]
            set_user_digest_frequency(user_id, next_digest)
        elif action == 'window_cycle':
            current_window = (
                int(settings.get("news_start_hour", SETTINGS_NEWS_WINDOW_PRESETS[0][0])),
                int(settings.get("news_end_hour", SETTINGS_NEWS_WINDOW_PRESETS[0][1])),
            )
            if current_window in SETTINGS_NEWS_WINDOW_PRESETS:
                next_index = (SETTINGS_NEWS_WINDOW_PRESETS.index(current_window) + 1) % len(SETTINGS_NEWS_WINDOW_PRESETS)
            else:
                next_index = 0
            next_start, next_end = SETTINGS_NEWS_WINDOW_PRESETS[next_index]
            set_user_news_window(user_id, next_start, next_end)

        try:
            send_settings_panel(call.message.chat.id, user_id=user_id, edit_message_id=call.message.message_id)
        except Exception:
            send_settings_panel(call.message.chat.id, user_id=user_id)
        return
    
    if call.data == 'menu_vip':
        try:
            # 🎟 แสดง top-up balance ถ้ามี — ลูกค้าจะรู้ว่าเหลือกี่ครั้ง
            try:
                _topup = get_topup_balance(user_id)
            except Exception:
                _topup = 0
            topup_line = f"\n🎟 **Top-up คงเหลือ:** {_topup} ครั้ง\n" if _topup > 0 else ""

            # 🎯 Scarcity — ดึง count ของ paying users เพื่อบอกว่ายังมี early bird seats
            try:
                from database import get_user_stats
                _stats, _ = get_user_stats()
                _paying_count = _stats.get('vip', 0) + _stats.get('pro', 0)
            except Exception:
                _paying_count = 0
            EARLY_BIRD_CAP = 200  # launch promo limit
            seats_left = max(0, EARLY_BIRD_CAP - _paying_count)
            if seats_left > 0 and seats_left <= 100:
                scarcity_line = (
                    f"\n⚡ *Early Bird Pricing* — เหลือ **{seats_left}/{EARLY_BIRD_CAP}** ที่นั่ง\n"
                    f"_(ราคา launch 79฿/ด — จะปรับเป็น 99฿ เมื่อครบ {EARLY_BIRD_CAP} user)_\n"
                )
            elif seats_left > 100:
                scarcity_line = (
                    f"\n⚡ _Early Bird Pricing 79฿/ด — สำหรับ {EARLY_BIRD_CAP} user แรก_\n"
                )
            else:
                scarcity_line = ""

            pay_text = (
                "🚀 **แพ็กเกจ APEXIFY** 🚀\n"
                "💳 กสิกรไทย: `135-1-34469-1` (นาย เกียรติศักดิ์ วุฒิจันทร์)\n"
                "*(โอนแล้วส่งสลิปในแชทนี้ ระบบอัปเกรดอัตโนมัติใน 3 วิ!)*\n"
                f"{topup_line}"
                f"{scarcity_line}\n"

                "🆓 **BASIC (ฟรี)**\n"
                f"• สแกน Apexify {FREE_DAILY_QUOTA} ครั้ง/วัน\n"
                "• Watchlist 3 ตัว\n"
                "• Fear & Greed, PnL Card\n"
                "• พอร์ตเว็บ 3 ตัว, DRIP/Simulator\n\n"

                "🎟 **TOP-UP — 20.-/10 ครั้ง** (เติมเฉพาะกิจ)\n"
                "• เพิ่มจากโควต้าฟรี เพียง 2฿/ครั้ง\n"
                "• ใช้ได้กับ Free tier — ไม่หมดอายุ\n"
                "• เหมาะ: ใช้ไม่บ่อย ไม่อยากผูก subscription\n\n"

                "💎 **VIP — 79.-/เดือน หรือ 790.-/ปี** _(ประหยัด 158฿ · ฟรี 2 เดือน)_\n"
                "• สแกน Apexify ไม่จำกัด\n"
                "• Watchlist 10 ตัว + Scan all\n"
                "• Morning Briefing, Apexify Podcast, News Digest\n"
                "• Daily Portfolio Summary\n"
                "• พอร์ตเว็บ 10 ตัว, Trade Plan, Health Score, Heatmap, Matchmaker\n\n"

                "👑 **PRO — 109.-/เดือน หรือ 1,090.-/ปี** _(ประหยัด 218฿ · ฟรี 2 เดือน)_ 🔥\n"
                "• ทุกอย่างของ VIP +\n"
                "• Watchlist & พอร์ตเว็บ ไม่จำกัด\n"
                "• Smart Alerts, Technical Radar\n"
                "• Flash News, Dividend Hunter, Screener\n"
                "• Apexify Rebalance, Port Doctor, Sentiment Analysis\n\n"

                "💡 *เทียบราคา:* Bualuang Premium 1,200฿/ด · efin StockSelect 990฿/ด · "
                "Apexify เริ่มเพียง **79฿/ด** (ถูกกว่า ~93%)\n"
            )
            qr_markup = InlineKeyboardMarkup(row_width=2)
            qr_markup.add(
                InlineKeyboardButton("🎟 เติม 20฿ → 10 ครั้ง (2฿/ครั้ง)", callback_data="qr_pay_20"),
            )
            qr_markup.add(
                InlineKeyboardButton("💎 VIP 79฿/เดือน", callback_data="qr_pay_79"),
                InlineKeyboardButton("👑 PRO 109฿/เดือน", callback_data="qr_pay_109"),
            )
            qr_markup.add(
                InlineKeyboardButton("💎 VIP 790.-/ปี (ฟรี 2 เดือน)", callback_data="qr_pay_790"),
                InlineKeyboardButton("👑 PRO 1,090.-/ปี (ฟรี 2 เดือน)", callback_data="qr_pay_1090"),
            )
            bot.send_message(user_id, pay_text, parse_mode="Markdown", reply_markup=qr_markup)
        except Exception as e:
            print(f"[hub_vip_menu] {e}", flush=True)
            bot.send_message(user_id, friendly_error("โหลดเมนู VIP ไม่สำเร็จ"))

    elif call.data.startswith('qr_pay_'):
        try:
            from promptpay_qr import generate_promptpay_qr
            from config import PROMPTPAY_ID
            amount_str = call.data.replace('qr_pay_', '')
            amount = int(amount_str)
            pkg_names = {
                20: "🎟 Top-up 10 ครั้ง",
                79: "💎 VIP รายเดือน",
                109: "👑 PRO รายเดือน",
                790: "💎 VIP รายปี (ฟรี 2 เดือน)",
                1090: "👑 PRO รายปี (ฟรี 2 เดือน)",
            }
            pkg_name = pkg_names.get(amount, f"แพ็กเกจ {amount} บาท")

            if not PROMPTPAY_ID:
                bot.send_message(user_id,
                    f"📱 **{pkg_name} — {amount:,} บาท**\n\n"
                    f"💳 กสิกรไทย: `135-1-34469-1`\n"
                    f"*(โอน {amount:,} บาท แล้วส่งสลิปในแชทนี้)*",
                    parse_mode="Markdown")
                return

            qr_buf = generate_promptpay_qr(PROMPTPAY_ID, amount=float(amount))
            if qr_buf:
                caption = (
                    f"📱 **{pkg_name} — {amount:,} บาท**\n\n"
                    f"สแกน QR Code ด้านบนเพื่อชำระเงิน\n"
                    f"*(โอนแล้วส่งรูปสลิปในแชทนี้ ระบบจะอัปเกรดอัตโนมัติ!)*"
                )
                bot.send_photo(user_id, qr_buf, caption=caption, parse_mode="Markdown")
            else:
                bot.send_message(user_id,
                    f"📱 **{pkg_name} — {amount:,} บาท**\n\n"
                    f"💳 กสิกรไทย: `135-1-34469-1`\n"
                    f"*(โอน {amount:,} บาท แล้วส่งสลิปในแชทนี้)*",
                    parse_mode="Markdown")
        except Exception as e:
            print(f"[generate_qr] {e}", flush=True)
            bot.send_message(user_id, friendly_error("สร้าง QR Code ไม่สำเร็จ"))

    elif call.data == 'menu_code':
        bot.send_message(user_id, "🎟 **พิมพ์คำสั่ง:** `/redeem [โค้ดของคุณ]`", parse_mode="Markdown")

    elif call.data.startswith('setalert_pick_'):
        # Guided UX step 2 — เลือก symbol แล้ว → แสดง pct picker
        if role != 'pro' and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 ตั้งเตือนราคา = PRO เท่านั้น", parse_mode="Markdown")
            return
        sym = call.data.replace('setalert_pick_', '')
        try:
            tech_data, _, _ = _get_cached_analysis(sym, generate_chart=False)
            if not tech_data:
                bot.send_message(user_id, f"❌ ไม่พบ {sym}")
                return
            current_price = tech_data['price']
            kb = InlineKeyboardMarkup(row_width=3)
            kb.add(
                InlineKeyboardButton("📈 +5%", callback_data=f"setalert_pct_{sym}_5"),
                InlineKeyboardButton("📈 +10%", callback_data=f"setalert_pct_{sym}_10"),
                InlineKeyboardButton("📈 +20%", callback_data=f"setalert_pct_{sym}_20"),
            )
            kb.add(
                InlineKeyboardButton("📉 -5%", callback_data=f"setalert_pct_{sym}_-5"),
                InlineKeyboardButton("📉 -10%", callback_data=f"setalert_pct_{sym}_-10"),
                InlineKeyboardButton("📉 -20%", callback_data=f"setalert_pct_{sym}_-20"),
            )
            bot.send_message(
                user_id,
                f"🔔 *{sym}* — ราคาปัจจุบัน **${current_price:,.2f}**\n\n"
                f"เลือกเปอร์เซ็นต์เพื่อตั้งเตือน:\n"
                f"หรือพิมพ์ราคาเอง: `/setalert {sym} 180`",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as e:
            print(f"[setalert_pick] {e}", flush=True)
            bot.send_message(user_id, "❌ ระบบขัดข้อง ลองพิมพ์ /setalert ใหม่")

    elif call.data.startswith('setalert_pct_'):
        # Guided UX step 3 — เลือก % แล้ว → ตั้งเตือนทันที
        if role != 'pro' and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 ตั้งเตือนราคา = PRO เท่านั้น", parse_mode="Markdown")
            return
        try:
            payload = call.data.replace('setalert_pct_', '')
            sym, pct_str = payload.rsplit('_', 1)
            pct = float(pct_str)
            tech_data, _, _ = _get_cached_analysis(sym, generate_chart=False)
            if not tech_data:
                bot.send_message(user_id, f"❌ ไม่พบ {sym}")
                return
            current_price = tech_data['price']
            target_price = round(current_price * (1 + pct / 100), 4)
            condition = 'above' if pct > 0 else 'below'
            cond_text = "ขึ้นไปแตะ" if condition == 'above' else "ร่วงลงมาแตะ"
            add_price_alert_db(user_id, sym, target_price, condition)
            bot.send_message(
                user_id,
                f"✅ *ตั้งเตือนสำเร็จ* 🔔\n\n"
                f"📌 **{sym}** ราคาปัจจุบัน ${current_price:,.2f}\n"
                f"🎯 แจ้งเตือนเมื่อ **{cond_text} ${target_price:,.2f}** ({pct:+.0f}%)\n\n"
                f"_ระบบเช็คทุก 5 นาทีตลอด 24 ชม._",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"[setalert_pct] {e}", flush=True)
            bot.send_message(user_id, "❌ ระบบขัดข้อง ลองพิมพ์ /setalert ใหม่")

    elif call.data == 'trigger_freetrial':
        # 🎁 Trigger /freetrial flow from /start inline button (fix 96% activation gap)
        try:
            handle_free_trial(call.message)
        except Exception as e:
            print(f"[trigger_freetrial] {e}", flush=True)
            bot.send_message(user_id, "📡 ระบบขัดข้องชั่วคราว ลอง /freetrial ในแชทอีกครั้งครับ")
        bot.answer_callback_query(call.id)

    elif call.data == 'menu_referral':
        try:
            ref_count = get_referral_stats(user_id)
            bot_info = bot.get_me()
            bot_username = bot_info.username
            ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
            next_milestone = 3 - (ref_count % 3) if ref_count % 3 != 0 else 3
            progress_bar = "🟩" * (ref_count % 3) + "⬜" * (3 - (ref_count % 3))
            share_text = (
                f"🚀 แนะนำบอทวิเคราะห์หุ้น AI ที่ผมใช้อยู่! "
                f"สมัครผ่านลิงก์นี้รับ VIP 3 วันฟรีทันที 🎁\n{ref_link}"
            )
            msg = (
                "🤝 **ชวนเพื่อน รับรางวัล!** 🤝\n\n"
                "🎁 **รางวัลของคุณ:**\n"
                "   • ทุก **1 เพื่อน** → +3 โควต้า (free) / ลด counter\n"
                "   • ทุก **3 เพื่อน** → **+10 วัน VIP/PRO!**\n"
                "   • ชวนครบ 6 = +20 วัน, 9 = +30 วัน ...\n\n"
                "🎁 **รางวัลเพื่อน (ใหม่!):**\n"
                "   เพื่อนที่สมัครผ่านลิงก์คุณ → **รับ VIP 3 วันฟรี** ทันที\n\n"
                f"📊 **ความคืบหน้าของคุณ:** {ref_count} คน\n"
                f"   {progress_bar}  อีก {next_milestone} คน ถึง milestone!\n\n"
                f"🔗 **ลิงก์ของคุณ:**\n`{ref_link}`"
            )
            share_kb = InlineKeyboardMarkup(row_width=1)
            share_kb.add(InlineKeyboardButton(
                "📤 แชร์ลิงก์ให้เพื่อน (Telegram)",
                switch_inline_query=share_text,
            ))
            bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=share_kb)
        except Exception as e:
            print(f"[menu_referral] error: {e}", flush=True)
            bot.send_message(user_id, "❌ ระบบชวนเพื่อนขัดข้องชั่วคราว กรุณาลองใหม่ครับ")
            
    elif call.data == 'menu_freetrial':
        role = check_subscription(user_id)
        if role in ('vip', 'pro'):
            # มีแพ็กเกจอยู่แล้ว → ส่ง message + popup
            try:
                profile = get_user_profile(user_id)
                expiry = profile[1] if profile else None
                expiry_str = str(expiry)[:10] if expiry else "ไม่มีวันหมด"
            except Exception:
                expiry_str = "ไม่ทราบ"
            role_label = "👑 PRO" if role == 'pro' else "💎 VIP"
            bot.answer_callback_query(call.id,
                f"✨ คุณมี {role_label} อยู่แล้ว ถึงวันที่ {expiry_str}",
                show_alert=True)
            bot.send_message(user_id,
                f"✨ **คุณมีแพ็กเกจอยู่แล้วครับ**\n\n"
                f"📦 สถานะ: {role_label}\n"
                f"⏰ ใช้ได้ถึง: `{expiry_str}`\n\n"
                f"_Free Trial สำหรับผู้ที่ยังไม่เคยใช้ VIP/PRO เท่านั้น_",
                parse_mode="Markdown")
        elif has_used_free_trial(user_id):
            # เคยใช้แล้ว → popup + message พร้อมปุ่มสมัคร
            bot.answer_callback_query(call.id,
                "✨ คุณเคยใช้ Free Trial แล้ว (1 ครั้ง/บัญชี)",
                show_alert=True)
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("💎 สมัคร VIP 79฿", callback_data="menu_vip"),
                InlineKeyboardButton("👑 สมัคร PRO 109฿", callback_data="menu_vip"),
            )
            markup.add(InlineKeyboardButton("🤝 ชวนเพื่อน รับ VIP ฟรี", callback_data="menu_referral"))
            bot.send_message(user_id,
                "✨ **คุณเคยใช้ Free Trial ไปแล้ว**\n\n"
                "_Free Trial ใช้ได้เพียง 1 ครั้งต่อบัญชีเท่านั้น_\n\n"
                "💎 *ตัวเลือกอื่นๆ สำหรับคุณ:*\n"
                "• สมัคร VIP/PRO รายเดือน/รายปีได้ตลอดเวลา\n"
                "• ชวนเพื่อนสมัคร → ทั้งคู่ได้รางวัล\n"
                "• ใช้โค้ดโปรโมฯ ผ่าน `/redeem <โค้ด>`",
                parse_mode="Markdown", reply_markup=markup)
        else:
            ok = activate_free_trial(user_id)
            if ok:
                # 🌟 แก้ไข inline keyboard เดิมเอาปุ่ม freetrial ออก (กันกดซ้ำจาก message เดิม)
                try:
                    bot.edit_message_reply_markup(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        reply_markup=None,
                    )
                except Exception:
                    pass
                bot.send_message(user_id,
                    "🎉 **PRO 7 วันฟรี เปิดใช้งานแล้ว!**\n\n"
                    "✅ วิเคราะห์ไม่จำกัด + กราฟเทคนิค\n"
                    "✅ Entry/TP/SL พร้อมกราฟ\n"
                    "✅ Flash News + Morning Briefing\n"
                    "✅ Smart Alerts + Price Alerts\n"
                    "✅ Earnings Alert (`/ealert`)\n\n"
                    "_💡 ใช้งานได้ 7 วัน หลังจากนั้นกลับเป็น Free อัตโนมัติ (ไม่หักเงิน)_\n"
                    "_ลองพิมพ์ชื่อหุ้น เช่น `AAPL` เพื่อเริ่มทดลองได้เลยครับ!_",
                    parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id,
                    "📡 ระบบขัดข้องชั่วคราว ลองใหม่อีกครั้งครับ",
                    show_alert=True)

    elif call.data == 'menu_dashboard':
        send_dashboard_login_link(user_id)

    elif call.data == 'referral_self':
        try:
            bot.edit_message_text(
                "✅ มาเอง — ขอให้สนุกกับ Apexify ครับ! 🚀",
                call.message.chat.id, call.message.message_id,
            )
        except Exception:
            pass

    elif call.data == 'referral_friend':
        prompt_msg = bot.send_message(
            int(user_id),
            "👥 พิมพ์ชื่อหรือ Telegram ID ของเพื่อนที่แนะนำคุณ\n\n"
            "_เช่น @username, ชื่อจริง, หรือเลข Telegram ID_\n"
            "_พิมพ์ /cancel เพื่อยกเลิก_",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(prompt_msg, _capture_referrer_input)

    elif call.data == 'hub_today':
        try:
            load_msg = bot.send_message(user_id, "📅 กำลังรวบรวมข้อมูลวันนี้...")
            from datetime import datetime as _dt, timedelta
            thai_now = _dt.utcnow() + timedelta(hours=7)
            date_str = thai_now.strftime("%d %b %Y")

            # ตลาด
            indices = {"SET": "^SET.BK", "S&P500": "^GSPC", "Bitcoin": "BTC-USD", "Gold": "GC=F"}
            market_lines = []
            for name, sym in indices.items():
                try:
                    data = yf.Ticker(sym).history(period="5d")
                    if len(data) >= 2:
                        c_now = data['Close'].iloc[-1]
                        c_prev = data['Close'].iloc[-2]
                        pct = (c_now - c_prev) / c_prev * 100
                        arrow = "🟢" if pct >= 0 else "🔴"
                        market_lines.append(f"{arrow} {name}: {c_now:,.2f} ({pct:+.2f}%)")
                except Exception:
                    pass
            market_text = "\n".join(market_lines) if market_lines else "ไม่สามารถดึงข้อมูลได้"

            # Watchlist scan (ถ้ามี)
            watch_list = get_user_watch(user_id)
            watch_text = ""
            if watch_list:
                watch_lines = []
                for sym in watch_list[:5]:
                    try:
                        td, _, err = _get_cached_analysis(sym, generate_chart=False)
                        if err or not td:
                            continue
                        trend = "🟢" if td['ema20'] > td['ema50'] else "🔴"
                        rsi = td['rsi']
                        rsi_note = " ⚠️ Oversold" if rsi < 30 else (" ⚠️ Overbought" if rsi > 70 else "")
                        watch_lines.append(f"{trend} {sym}: {td['price']:.2f} | RSI {rsi:.0f}{rsi_note}")
                    except Exception:
                        pass
                if watch_lines:
                    watch_text = "\n\n📋 *Watchlist ของฉัน:*\n" + "\n".join(watch_lines)

            msg = (
                f"📅 *สรุปวันนี้ — {date_str}*\n\n"
                f"🌍 *ตลาดล่าสุด:*\n{market_text}"
                f"{watch_text}\n\n"
                f"💡 กด 📰 ข่าวด่วน เพื่อดูข่าววันนี้เพิ่มเติม"
            )
            bot.edit_message_text(msg, user_id, load_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            print(f"[hub_analyze] {e}", flush=True)
            bot.edit_message_text(friendly_error("ดึงข้อมูลไม่สำเร็จ"), user_id, load_msg.message_id)

    elif call.data == 'hub_market':
        try:
            load_msg = bot.send_message(user_id, "🌍 กำลังดึงข้อมูลสภาวะตลาดโลก...")
            fg_index = get_fear_and_greed_index()
            indices = {"SET (ไทย)": "^SET.BK", "S&P 500 (สหรัฐ)": "^GSPC", "Bitcoin (คริปโต)": "BTC-USD"}
            market_text = ""
            for name, sym in indices.items():
                data = yf.Ticker(sym).history(period="5d")
                if len(data) >= 2:
                    close_today = data['Close'].iloc[-1]
                    close_yest = data['Close'].iloc[-2]
                    pct_change = ((close_today - close_yest) / close_yest) * 100
                    emoji = "🟢" if pct_change >= 0 else "🔴"
                    market_text += f"• {name}: {close_today:,.2f} ({pct_change:+.2f}%) {emoji}\n"
            msg = f"🌍 **สรุปสภาวะตลาด**\n\n🧭 **Fear & Greed:**\n{fg_index}\n\n📊 **ดัชนีสำคัญ:**\n{market_text}"
            bot.edit_message_text(msg, user_id, load_msg.message_id, parse_mode="Markdown")
        except Exception:
            bot.edit_message_text(f"❌ ล้มเหลว", user_id, load_msg.message_id)
            
    elif call.data == 'hub_news':
        try:
            load_msg = bot.send_message(user_id, "📰 กำลังให้ 💎 APEXIFY ประมวลผลและสรุปข่าวด่วน...")
            
            urls = [
                "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+ทองคำ+OR+คริปโต+OR+น้ำมัน+when:1d&hl=th&gl=TH&ceid=TH:th",
                "https://www.investing.com/rss/news_25.rss",
                "https://www.investing.com/rss/news_301.rss"
            ]
            all_titles = []
            for url in urls:
                try:
                    res = cffi_requests.get(url, impersonate="chrome110", timeout=10)
                    root = ET.fromstring(res.content)
                    for item in root.findall('.//item')[:5]: 
                        title_elem = item.find('title')
                        if title_elem is not None:
                            all_titles.append(title_elem.text)
                except Exception:
                    pass

            titles_str = "\n".join([f"- {t}" for t in all_titles[:15]])

            ai_client = gemini_client
            
            prompt = f"""
            คัดเลือกข่าวที่สำคัญและด่วนที่สุด 3 ข่าวจากหัวข้อเหล่านี้:
            {titles_str}
            
            นำมาเขียนสรุปเนื้อหาข่าวแบบกระชับ ข่าวละ 3-4 บรรทัด (เป็นภาษาไทย)
            ห้ามใส่ลิงก์ใดๆ ทั้งสิ้น บังคับใช้รูปแบบนี้เท่านั้น:
            
            🔥 **[พาดหัวข่าวที่คุณเลือก]**
            📝 [สรุปเนื้อหาข่าว 3-4 บรรทัด อธิบายให้เข้าใจง่ายว่าเกิดอะไรขึ้น และกระทบตลาดยังไง]
            """
            
            ai_response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            final_news = "🌐 **สรุปข่าวด่วนตลาดลงทุน (💎 APEXIFY Digest)** 🌐\n\n" + ai_response.text.strip()
            
            bot.edit_message_text(final_news, user_id, load_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ ดึงข้อมูลข่าวล้มเหลว กรุณาลองใหม่", user_id, load_msg.message_id)
            
    elif call.data == 'hub_watchlist':
        try:
            my_list = get_user_watch(user_id)
            if not my_list:
                bot.send_message(
                    user_id,
                    "📋 *Watchlist ของฉัน*\n\n"
                    "ยังไม่มีหุ้นในรายการ\n\n"
                    "*วิธีเพิ่ม:* พิมพ์ชื่อหุ้น → กด ⭐ ใต้รายงานวิเคราะห์\n\n"
                    "บอทจะแจ้งเตือนสัญญาณเทคนิค (RSI, EMA Cross) ของหุ้นในรายการให้อัตโนมัติครับ",
                    parse_mode="Markdown"
                )
                return
            markup = InlineKeyboardMarkup()
            for symbol in my_list:
                markup.add(InlineKeyboardButton(f"❌ ลบ {symbol}", callback_data=f"delwatch_{symbol}"))
            watch_info = (
                f"📋 *Watchlist ของฉัน* ({len(my_list)} ตัว)\n\n"
                "บอทติดตามและแจ้งเตือนสัญญาณอัตโนมัติสำหรับหุ้นเหล่านี้\n"
                "กดปุ่มด้านล่างเพื่อลบออกจากรายการ:"
            )
            bot.send_message(user_id, watch_info, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"[hub_watchlist] {e}", flush=True)
            bot.send_message(user_id, friendly_error("ดึง Watchlist ไม่สำเร็จ"))

    elif call.data == 'hub_home':
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📅 สรุปวันนี้", callback_data="hub_today"),
            InlineKeyboardButton("🌍 สภาวะตลาดโลก", callback_data="hub_market")
        )
        markup.add(
            InlineKeyboardButton("📰 ข่าวด่วนลงทุน", callback_data="hub_news"),
            InlineKeyboardButton("📋 Watchlist ของฉัน", callback_data="hub_watchlist")
        )
        markup.add(
            InlineKeyboardButton("🚀 สแกนหุ้น (VIP)", callback_data="hub_scan"),
            InlineKeyboardButton("💼 พอร์ตลงทุน", callback_data="hub_portfolio")
        )
        markup.add(
            InlineKeyboardButton("🔥 หุ้นเด่น (PRO)", callback_data="hub_screener"),
            InlineKeyboardButton("🔔 ตั้งเตือนราคา (PRO)", callback_data="hub_price_alert")
        )
        markup.add(
            InlineKeyboardButton("⚙️ ตั้งค่าการแจ้งเตือน", callback_data="settings_open"),
            InlineKeyboardButton("🌐 Web Dashboard", callback_data="menu_dashboard")
        )
        bot.send_message(user_id, "📱 **Apexify Hub**\nเลือกฟีเจอร์ที่ต้องการได้เลยครับ:", parse_mode="Markdown", reply_markup=markup)

    elif call.data == 'hub_portfolio':
        load_msg = bot.send_message(user_id, "⏳ กำลังดึงข้อมูลพอร์ต...")
        try:
            portfolio = get_user_portfolio(user_id)
            if not portfolio:
                bot.edit_message_text(
                    "💼 <b>พอร์ตลงทุน</b>\n\nยังไม่มีหุ้นในพอร์ต\n\n"
                    "เพิ่มหุ้นด้วยคำสั่ง:\n<code>/add [ชื่อหุ้น] [จำนวน] [ราคาเฉลี่ย]</code>\n"
                    "เช่น <code>/add PTT.BK 100 32.50</code>",
                    chat_id=user_id, message_id=load_msg.message_id, parse_mode='HTML'
                )
            else:
                total_invested = 0
                current_value = 0
                rows = []
                for asset in portfolio:
                    ticker = asset['ticker']
                    shares = asset['shares']
                    avg_cost = asset['avg_cost']
                    try:
                        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
                        clean_ticker = ticker.replace(".", "-") if "." in ticker and not ticker.endswith(allowed_suffixes) else ticker
                        live_price = float(yf.Ticker(clean_ticker).fast_info.last_price)
                    except Exception:
                        live_price = avg_cost
                    invested = shares * avg_cost
                    current = shares * live_price
                    profit = current - invested
                    profit_pct = (profit / invested * 100) if invested > 0 else 0
                    total_invested += invested
                    current_value += current
                    rows.append((ticker, shares, avg_cost, live_price, profit, profit_pct))

                total_profit = current_value - total_invested
                total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
                total_icon = "🟢" if total_profit >= 0 else "🔴"

                lines = [f"💼 <b>พอร์ตลงทุน</b>  ({len(rows)} หลักทรัพย์)\n"]
                for ticker, shares, avg_cost, live_price, profit, profit_pct in rows:
                    icon = "🟢" if profit >= 0 else "🔴"
                    sign = "+" if profit >= 0 else ""
                    lines.append(
                        f"{icon} <b>{ticker}</b>  {shares:,.4g} หุ้น\n"
                        f"   ทุน {avg_cost:,.2f}  →  ล่าสุด {live_price:,.2f}\n"
                        f"   {sign}{profit:,.2f}  ({sign}{profit_pct:.2f}%)\n"
                    )
                lines.append(
                    f"─────────────────────\n"
                    f"💰 <b>มูลค่ารวม:</b> {current_value:,.2f}\n"
                    f"💵 <b>ต้นทุนรวม:</b> {total_invested:,.2f}\n"
                    f"{total_icon} <b>กำไร/ขาดทุนรวม:</b> {'+' if total_profit >= 0 else ''}{total_profit:,.2f}  ({'+' if total_profit_pct >= 0 else ''}{total_profit_pct:.2f}%)"
                )
                bot.edit_message_text("\n".join(lines), chat_id=user_id, message_id=load_msg.message_id, parse_mode='HTML')
        except Exception as e:
            print(f"[BotError] {e}", flush=True)
            bot.edit_message_text("❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ", chat_id=user_id, message_id=load_msg.message_id)
        
    elif call.data == 'hub_scan':
        try:
            if user_id != ADMIN_ID and role == 'free':
                bot.send_message(user_id, "🔒 ฟีเจอร์สงวนสิทธิ์เฉพาะ **VIP / PRO**", parse_mode="Markdown")
                return
            my_list = get_user_watch(user_id)
            if not my_list:
                bot.send_message(user_id, "📋 Watchlist ว่างเปล่า")
                return
            scan_msg = bot.send_message(user_id, f"🚀 กำลังสแกนหุ้น {len(my_list)} ตัว...")
            scan_result = "🚀 **รายงานสแกน Watchlist**\n\n"
            for sym in my_list:
                try:
                    tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                    if err or not tech_data: continue
                    ema_short = "🟢 ขาขึ้น" if tech_data['ema20'] > tech_data['ema50'] else "🔴 ขาลง"
                    cross = "✨ Golden Cross!" if tech_data['ema50'] > tech_data['ema200'] else "ธรรมดา"
                    rsi = tech_data['rsi']
                    rsi_txt = "🔥 ตึงไป (Overbought)" if rsi > 70 else "🎯 น่าสะสม (Oversold)" if rsi < 30 else "⚪️ กลางๆ"
                    scan_result += f"📌 **{sym}** ({tech_data['price']:.2f})\n   เทรนด์: {ema_short} | RSI: {rsi_txt}\n"
                    if "Golden" in cross or rsi < 30:
                        scan_result += f"   👉 **สัญญาณ:** {cross}\n"
                    scan_result += "\n"
                except Exception as e:
                    print(f"[Screener] {sym} ล้มเหลว: {e}")
            bot.edit_message_text(scan_result, user_id, scan_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            print(f"[hub_screener] {e}", flush=True)
            bot.send_message(user_id, friendly_error("Screener ทำงานไม่สำเร็จ"))

    elif call.data == 'hub_screener':
        try:
            if role != 'pro' and user_id != ADMIN_ID:
                bot.send_message(user_id, "🔒 **ฟีเจอร์ระดับพรีเมียม (PRO Exclusive)**\nสแกนหุ้นเด่นอัตโนมัติสงวนสิทธิ์ให้ลูกค้าระดับ PRO เท่านั้นครับ 👑", parse_mode="Markdown")
                return
            
            scan_msg = bot.send_message(user_id, "⏳ **Apexify กำลังสแกนหุ้นเด่น US...**\n*(สแกน ~225 ตัว — Mag 7 + S&P 500 + story stocks + small cap day trade คัด 10 อันดับ คละขนาด)*", parse_mode="Markdown")

            # 🇺🇸 US universe — ~225 ตัว ผสม blue-chip + story stocks + hot movers + small cap (PP P. 2026-05-13)
            scan_list = [
                # Mega Tech & Internet (15)
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NFLX', 'CRM', 'ORCL',
                'ADBE', 'NOW', 'IBM', 'CSCO', 'INTU', 'ANET', 'SHOP',
                # Semi / Hardware (15)
                'NVDA', 'AMD', 'AVGO', 'TSM', 'INTC', 'QCOM', 'MU', 'ASML',
                'AMAT', 'KLAC', 'LRCX', 'MRVL', 'ON', 'ARM', 'TXN',
                # Software / SaaS / AI (15)
                'PLTR', 'SNOW', 'CRWD', 'PANW', 'DDOG', 'NET', 'FTNT', 'ZS',
                'MDB', 'TEAM', 'WDAY', 'SQ', 'U', 'EA', 'TTWO',
                # Consumer Discretionary (15)
                'TSLA', 'COST', 'NKE', 'MCD', 'SBUX', 'DIS', 'LOW', 'HD',
                'TJX', 'ROST', 'LULU', 'BKNG', 'MAR', 'F', 'GM',
                # Consumer Staples (15)
                'WMT', 'PG', 'KO', 'PEP', 'MO', 'PM', 'MDLZ', 'KMB',
                'CL', 'EL', 'KHC', 'GIS', 'K', 'SYY', 'STZ',
                # Financials (15)
                'JPM', 'BAC', 'V', 'MA', 'GS', 'BLK', 'AXP', 'MS',
                'C', 'WFC', 'SCHW', 'USB', 'COF', 'PYPL', 'AFL',
                # Healthcare / Pharma (15)
                'LLY', 'UNH', 'JNJ', 'PFE', 'ABBV', 'MRK', 'TMO', 'ABT',
                'BMY', 'AMGN', 'GILD', 'REGN', 'VRTX', 'ELV', 'CVS',
                # Energy (10)
                'XOM', 'CVX', 'COP', 'OXY', 'EOG', 'SLB', 'MPC', 'PSX',
                'KMI', 'EPD',
                # Industrial (12)
                'CAT', 'BA', 'GE', 'UPS', 'FDX', 'HON', 'LMT', 'RTX',
                'NOC', 'DE', 'ETN', 'EMR',
                # REIT (5)
                'O', 'PLD', 'AMT', 'EQIX', 'SPG',
                # Materials (5)
                'LIN', 'FCX', 'NEM', 'APD', 'SHW',
                # Travel / Leisure (8)
                'UBER', 'ABNB', 'HLT', 'DAL', 'AAL', 'LUV', 'CCL', 'RCL',
                # Telecom / Retail (5)
                'T', 'VZ', 'TMUS', 'CMCSA', 'TGT',
                # 🚀 Story / High-Beta Stocks (30) — คนไทยชอบหุ้นซิ่ง สตอรี่ดี
                'RKLB', 'ASTS', 'IRDM', 'PL',           # Space
                'IONQ', 'RGTI', 'QBTS', 'ARQQ',         # Quantum
                'AI', 'SOUN', 'BBAI', 'NBIS',           # AI plays
                'RIVN', 'LCID', 'NIO', 'XPEV',          # EV
                'COIN', 'MSTR', 'MARA', 'RIOT', 'HOOD', # Crypto-linked
                'RXRX', 'EXAS', 'SAVA',                 # Biotech
                'GME', 'SOFI', 'UPST', 'AFRM', 'NU',    # Meme / Fintech
                'SMCI',                                 # AI hardware
                # 🔥 Hot Movers (25) — กลุ่มที่กำลังร้อนแรงตอนนี้
                'VST', 'CEG', 'TLN',                            # AI Power / Nuclear
                'VRT', 'ALAB', 'DELL', 'CRWV',                  # AI infrastructure
                'SE', 'MELI', 'SPOT', 'DUOL',                   # International consumer
                'HIMS', 'RDDT', 'DASH', 'TOST',                 # Consumer tech / DTC
                'ENPH', 'FSLR', 'BE',                           # Clean Energy
                'LDOS', 'TDG',                                  # Defense
                'CLSK', 'CIFR',                                 # Crypto mining
                'TEM',                                          # Genomics / AI healthcare
                # 🆕 2026-05-13 — Small cap day trade favorites (PP P. request)
                # ขอ small cap ใน screener ด้วย ("คนเทรดรายวันส่วนมากเป็น small cap")
                'OKLO', 'SMR', 'LEU',                           # AI Power / Nuclear small
                'BTBT', 'BTDR', 'IREN', 'WULF', 'HUT',          # Crypto mining (CLSK/CIFR/MARA/RIOT มีแล้ว)
                'ACHR', 'JOBY',                                 # eVTOL
                'HOLO', 'LAES', 'GFAI', 'SERV', 'KSCP',         # AI small
                'QUBT',                                         # Quantum (IONQ/RGTI/QBTS/ARQQ มีแล้ว)
                'BKSY', 'SPIR',                                 # Space small
                'USAR', 'MP',                                   # Rare earth / Critical minerals
                'DJT',                                          # Political / meme
                'DAVE',                                         # Fintech small
                'ONDS',                                         # Defense drone
                'OPEN',                                         # Real estate tech
                'NVAX', 'VKTX',                                 # Biotech catalyst
                'WKHS',                                         # EV small (GOEV delisted 2026-05)
            ]

            # 🆕 Small cap set — ใช้ tag + quota top 10 (target 4 small + 6 large)
            # Quota approach (2026-05-13 update): พยายามเติม small cap ให้ครบ 4 ตัว
            # ถ้า signal มีน้อยกว่า 4 → เติมเท่าที่มี (graceful fallback)
            SCREENER_SMALL_CAP_SET = {
                # Existing in scan_list (story stocks + hot movers small)
                'IONQ', 'RGTI', 'QBTS', 'ARQQ', 'BBAI', 'SOUN', 'NBIS',
                'RKLB', 'ASTS', 'IRDM', 'PL', 'RXRX', 'EXAS', 'SAVA',
                'AI', 'CLSK', 'CIFR', 'TEM', 'ALAB', 'CRWV',
                # Newly added small caps (2026-05-13)
                'OKLO', 'SMR', 'LEU', 'BTBT', 'BTDR', 'IREN', 'WULF', 'HUT',
                'ACHR', 'JOBY', 'HOLO', 'LAES', 'GFAI', 'SERV', 'KSCP', 'QUBT',
                'BKSY', 'SPIR', 'USAR', 'MP', 'DJT', 'DAVE', 'ONDS', 'OPEN',
                'NVAX', 'VKTX', 'WKHS',
            }
            SMALL_CAP_QUOTA = 4   # target: ~4 small + ~6 large ใน top 10

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _score_symbol(sym):
                try:
                    tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                    if err or not tech_data:
                        return None

                    rsi = tech_data['rsi']
                    ema50 = tech_data['ema50']
                    ema200 = tech_data['ema200']
                    price = tech_data['price']
                    vol_ratio = tech_data.get('volume_ratio', 1) or 1
                    close_vs_ema20 = tech_data.get('close_vs_ema20_pct', 0) or 0

                    score = 0
                    reasons = []

                    if ema50 > ema200:
                        ratio = ema50 / ema200
                        if ratio < 1.03:
                            score += 100
                            reasons.append("✨ Golden Cross (เพิ่งเกิด)")
                        elif ratio < 1.08:
                            score += 60
                            reasons.append("📈 เทรนด์ขาขึ้นยังไม่ extended")
                        elif ratio < 1.15:
                            score += 30

                    if rsi < 30:
                        score += 100
                        reasons.append(f"🎯 Oversold (RSI {rsi:.1f})")
                    elif rsi < 40:
                        score += 70
                        reasons.append(f"💎 ใกล้แนวรับ (RSI {rsi:.1f})")
                    elif 40 <= rsi <= 55:
                        score += 30
                        reasons.append(f"⚖️ โมเมนตัมเป็นกลาง (RSI {rsi:.1f})")

                    # 🚀 Momentum bonus — ใช้ close vs EMA20 (proxy หุ้นกำลังวิ่ง)
                    # > 3% above EMA20 = วิ่งแรงเหนือ trend / < -3% = oversold-stretch
                    if abs(close_vs_ema20) >= 5:
                        score += 80
                        reasons.append(f"⚡ โมเมนตัมแรง ({close_vs_ema20:+.1f}% vs EMA20)")
                    elif abs(close_vs_ema20) >= 3:
                        score += 40
                        reasons.append(f"📊 ขยับชัด ({close_vs_ema20:+.1f}% vs EMA20)")
                    elif abs(close_vs_ema20) >= 1.5:
                        score += 15

                    # 🔊 Volume bonus — vol สูงเหนือค่าเฉลี่ย = institutional interest
                    if vol_ratio >= 3:
                        score += 50
                        reasons.append(f"🔊 vol {vol_ratio:.1f}x")
                    elif vol_ratio >= 1.8:
                        score += 25

                    if score > 0:
                        return (score, sym, price, reasons)
                    return None
                except Exception as e:
                    print(f"[Screener] {sym} ล้มเหลว: {e}")
                    return None

            candidates = []
            # 16 workers: yfinance bound, network parallel ดีสุด ~12-16
            with ThreadPoolExecutor(max_workers=16, thread_name_prefix="screener") as pool:
                futures = {pool.submit(_score_symbol, sym): sym for sym in scan_list}
                for fut in as_completed(futures):
                    result = fut.result()
                    if result is not None:
                        candidates.append(result)

            candidates.sort(key=lambda x: x[0], reverse=True)

            # 🆕 Quota-based pick (2026-05-13 v2): พยายามเติม 4 small + 6 large
            # แยก 2 bucket → ดึง top ของแต่ละ → รวม + sort by score สำหรับ display
            small_caps_avail = [c for c in candidates if c[1] in SCREENER_SMALL_CAP_SET]
            large_caps_avail = [c for c in candidates if c[1] not in SCREENER_SMALL_CAP_SET]

            top_small = small_caps_avail[:SMALL_CAP_QUOTA]
            remaining_slots = 10 - len(top_small)
            top_large = large_caps_avail[:remaining_slots]

            # Combine และเรียงรวมตาม score สำหรับ display (highest first)
            top_10 = sorted(top_small + top_large, key=lambda x: -x[0])
            small_cap_count = len(top_small)

            if top_10:
                lines = []
                # 📝 Company name in parens (PP P. 2026-05-13)
                try:
                    from bot_utils import get_company_short_name as _get_co_name
                except Exception:
                    _get_co_name = lambda x: ""
                for i, (_, sym, price, reasons) in enumerate(top_10, 1):
                    reason_text = " + ".join(reasons) if reasons else "📊 น่าจับตา"
                    small_tag = " 🔥small cap" if sym in SCREENER_SMALL_CAP_SET else ""
                    _name = _get_co_name(sym)
                    _name_label = f" _({_name})_" if _name else ""
                    lines.append(f"**{i}. {sym}**{_name_label} (${price:,.2f}){small_tag}\n   👉 {reason_text}")
                # Subtitle + footer warning เฉพาะเมื่อมี small cap จริง (avoid noise)
                if small_cap_count > 0:
                    subtitle = f"_(mega + small cap คละกัน · small cap {small_cap_count}/{SMALL_CAP_QUOTA} ตัว)_\n\n"
                    footer_warning = "\n⚠️ _small cap volatility สูง — ใช้ size เล็ก, ตั้ง SL เคร่ง_"
                else:
                    subtitle = "\n"
                    footer_warning = ""
                result_msg = (
                    "🔥 **Apexify US Picks — 10 หุ้นเด่นวันนี้** 🔥\n"
                    + subtitle
                    + "\n\n".join(lines)
                    + "\n\n💡 พิมพ์ชื่อหุ้นเพื่อให้ Apexify วิเคราะห์เชิงลึก"
                    + footer_warning
                )
            else:
                result_msg = "🔥 **Apexify US Picks** 🔥\n\nขณะนี้ตลาดสหรัฐฯ ยังไม่มีหุ้นเข้าเกณฑ์น่าสะสมชัดเจน\n*(เทรนด์ extended ทั้งกระดาน — แนะนำให้รอจังหวะ pullback)*"
                
            bot.edit_message_text(result_msg, user_id, scan_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            print(f"[hub_screener_scan] {e}", flush=True)
            bot.edit_message_text(friendly_error("ระบบสแกนขัดข้อง"), user_id, scan_msg.message_id)

    elif call.data == 'menu_manual':
        class FakeMsg:
            def __init__(self, chat_id, msg_id):
                from types import SimpleNamespace
                self.chat = SimpleNamespace(id=chat_id)
                self.from_user = SimpleNamespace(id=chat_id)
                self.text = '/manual'
                self.message_id = msg_id
        try:
            handle_manual(FakeMsg(int(user_id), call.message.message_id))
        except Exception as e:
            print(f"[hub_manual] {e}", flush=True)
            bot.send_message(user_id, friendly_error("เปิดคู่มือไม่สำเร็จ"))

    elif call.data == 'hub_track':
        # Reuse handler ของ /track
        class FakeMsg:
            def __init__(self, chat_id, msg_id):
                from types import SimpleNamespace
                self.chat = SimpleNamespace(id=chat_id)
                self.from_user = SimpleNamespace(id=chat_id)
                self.text = '/track'
                self.message_id = msg_id
        try:
            handle_track_record(FakeMsg(int(user_id), call.message.message_id))
        except Exception as e:
            print(f"[hub_track] {e}", flush=True)
            bot.send_message(user_id, friendly_error("โหลด Track Record ไม่สำเร็จ"))

    elif call.data == 'hub_earnings':
        if role not in ('vip', 'pro') and user_id != ADMIN_ID:
            bot.send_message(user_id, "🔒 Earnings Alert = ฟีเจอร์ VIP/PRO\n\nอัปเกรดเพื่อสมัครรับแจ้งวัน Earnings ของหุ้นที่สนใจ")
            return
        bot.send_message(user_id,
            "📈 **Earnings Alert**\n\n"
            "พิมพ์คำสั่งดังนี้:\n"
            "• `/ealert AAPL` — สมัครแจ้งเตือนวัน Earnings\n"
            "• `/ealert list` — ดูรายการที่สมัครไว้\n"
            "• `/ealert remove AAPL` — ยกเลิก\n"
            "• `/earnings AAPL` — Apexify วิเคราะห์งบล่าสุด",
            parse_mode="Markdown")

    elif call.data == 'hub_badges':
        from database import get_user_achievements, ACHIEVEMENT_CATALOG, evaluate_achievements
        try:
            evaluate_achievements(user_id, context=None)
        except Exception:
            pass
        earned = get_user_achievements(user_id)
        earned_codes = {b["code"] for b in earned}
        total = len(ACHIEVEMENT_CATALOG)
        have = len(earned_codes)
        lines = [f"🏆 *Badges* — {have}/{total}", ""]
        if earned:
            lines.append("*✅ ที่ได้แล้ว:*")
            for b in earned:
                lines.append(f"  {b['label']} — _{b['description']}_")
            lines.append("")
        locked = [c for c in ACHIEVEMENT_CATALOG if c not in earned_codes]
        if locked:
            lines.append("*🔒 รอปลดล็อก:*")
            for code in locked[:5]:
                label, desc = ACHIEVEMENT_CATALOG[code]
                lines.append(f"  ⬜ {label} — _{desc}_")
        bot.send_message(int(user_id), "\n".join(lines), parse_mode="Markdown")

    elif call.data == 'hub_breaking':
        if role != 'pro' and user_id != ADMIN_ID:
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("👑 สมัคร PRO 109฿", callback_data="menu_vip"),
                InlineKeyboardButton("✨ Free Trial 7 วัน", callback_data="menu_freetrial"),
            )
            bot.send_message(user_id,
                "🔒 *ข่าวด่วนตลาด US — ฟีเจอร์ PRO เท่านั้น*\n\n"
                "🚨 ระบบจะแจ้งเตือนเฉพาะข่าวที่กระทบ S&P 500/Nasdaq จริง\n"
                "เช่น CPI, NFP, FOMC, สงคราม, OPEC cut\n\n"
                "Apexify คัดเฉพาะระดับ HIGH ส่งให้ — ไม่สแปม",
                parse_mode="Markdown", reply_markup=markup)
            return
        from database import is_subscribed_breaking_news
        _send_breaking_status_card(int(user_id), is_subscribed_breaking_news(user_id))

    elif call.data == 'breaking_toggle':
        if role != 'pro' and user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "🔒 PRO เท่านั้น", show_alert=True)
            return
        try:
            from database import is_subscribed_breaking_news, set_breaking_news_subscription
            now_on = is_subscribed_breaking_news(user_id)
            new_state = not now_on
            set_breaking_news_subscription(user_id, new_state)
            # Edit existing message in place to reflect new state
            icon = "🔔 เปิดอยู่" if new_state else "🔕 ปิดอยู่"
            btn_label = "🔕 ปิดข่าวด่วน" if new_state else "🔔 เปิดข่าวด่วน"
            new_markup = InlineKeyboardMarkup()
            new_markup.add(InlineKeyboardButton(btn_label, callback_data="breaking_toggle"))
            new_text = (
                "🚨 *ข่าวด่วนตลาด US*\n\n"
                f"สถานะ: *{icon}*\n\n"
                "ระบบจะแจ้งเฉพาะข่าวระดับ HIGH ที่กระทบ S&P 500 / Nasdaq จริง\n"
                "เช่น CPI, NFP, FOMC, สงคราม, OPEC cut\n\n"
                "🌙 ช่วง 02:00-08:00 น. (ไทย) จะรวมไว้ใน Morning Briefing"
            )
            try:
                bot.edit_message_text(
                    new_text, call.message.chat.id, call.message.message_id,
                    parse_mode="Markdown", reply_markup=new_markup,
                )
            except Exception:
                # Fallback: send new card if edit fails (e.g., message too old)
                _send_breaking_status_card(int(user_id), new_state)
            bot.answer_callback_query(
                call.id,
                "✅ เปิดแจ้งเตือนแล้ว" if new_state else "🔕 ปิดแจ้งเตือนแล้ว",
            )
        except Exception as e:
            print(f"[breaking_toggle] {e}", flush=True)
            from bot_utils import alert_admin_error
            alert_admin_error(bot, "breaking_toggle", e, user_id=user_id)
            bot.answer_callback_query(call.id, "❌ บันทึกไม่สำเร็จ ลองใหม่อีกครั้งนะครับ", show_alert=True)

    elif call.data == 'hub_price_alert':
        try:
            if role != 'pro' and user_id != ADMIN_ID:
                bot.send_message(user_id, "🔒 **ฟีเจอร์ระดับพรีเมียม (PRO Exclusive)**\nการตั้งเตือนราคาส่วนตัวสงวนสิทธิ์ให้ลูกค้าระดับ PRO เท่านั้นครับ 👑", parse_mode="Markdown")
                return
            alerts = get_user_price_alerts_db(user_id)
            markup = InlineKeyboardMarkup()
            if not alerts:
                header = "🔔 *การตั้งเตือนราคา*\n\nยังไม่มีรายการเฝ้าดู\n\n"
            else:
                header = f"🔔 *การตั้งเตือนราคา* ({len(alerts)} รายการ)\n\n"
                for alert in alerts:
                    a_id, sym, price, cond = alert
                    arrow = "📈" if cond == 'above' else "📉"
                    cond_text = "ขึ้นถึง" if cond == 'above' else "ลงถึง"
                    markup.add(InlineKeyboardButton(
                        f"❌ {sym} {cond_text} {price:,.2f}",
                        callback_data=f"delalert_{a_id}"
                    ))
            footer = "➕ เพิ่มเตือนใหม่: `/setalert [หุ้น] [ราคา]`\nเช่น `/setalert PTT.BK 35`"
            bot.send_message(user_id, header + footer, parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            print(f"[hub_alerts] {e}", flush=True)
            bot.send_message(user_id, friendly_error("ระบบตั้งเตือนราคาขัดข้อง"))

    elif call.data.startswith('addwatch_'):
        symbol = call.data.removeprefix('addwatch_')
        current_watch = len(get_user_watch(user_id))
        if role == 'free' and current_watch >= 3:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 3 ตัว** โปรดอัปเกรด", parse_mode="Markdown")
            return
        elif role == 'vip' and current_watch >= 10:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 10 ตัว** โปรดอัปเกรดเป็น PRO", parse_mode="Markdown")
            return
        if add_watch(user_id, symbol):
            bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** แล้ว", parse_mode="Markdown")
        else:
            bot.send_message(user_id, f"⚠️ มี **{symbol}** อยู่แล้ว", parse_mode="Markdown")

    elif call.data.startswith('delwatch_'):
        symbol = call.data.removeprefix('delwatch_')
        remove_watch_db(user_id, symbol)
        bot.edit_message_text(f"🗑️ ลบ **{symbol}** ออกจาก Watchlist แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")

    elif call.data.startswith('delalert_'):
        try:
            alert_id = int(call.data.removeprefix('delalert_'))
            remove_price_alert_db(user_id, alert_id)
            bot.edit_message_text(f"🗑️ ลบการตั้งเตือน ID {alert_id} แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception as e:
            print(f"[delalert_callback] {e}", flush=True)
            bot.answer_callback_query(call.id, "❌ ลบไม่สำเร็จ", show_alert=True)
        
    # ==========================================
    # 🌟 ส่วนรับคำสั่งจากปุ่มแผงควบคุมแอดมิน
    # ==========================================
    elif call.data.startswith('admin_'):
        if user_id != ADMIN_ID:
            bot.answer_callback_query(call.id, "⛔ ไม่อนุญาตให้ใช้งาน", show_alert=True)
            return
            
        bot.answer_callback_query(call.id)
            
       # สร้าง Mock Message เพื่อหลอกระบบให้เรียกใช้ฟังก์ชันเดิมได้
        class MockMessage:
            def __init__(self, chat_id, msg_id, text=""):
                self.chat = type('obj', (object,), {'id': chat_id})
                self.message_id = msg_id  # 🌟 เพิ่มข้อมูลตรงนี้
                self.text = text
                
        # ใส่ call.message.message_id เข้าไปด้วย
        mock_msg = MockMessage(int(user_id), call.message.message_id)

        if call.data == 'admin_maintenance':
            handle_maintenance(mock_msg)
        elif call.data == 'admin_health':
            handle_system_health(mock_msg)
        elif call.data == 'admin_stats':
            handle_stats(mock_msg)
        elif call.data == 'admin_perf':
            handle_performance(mock_msg)
        elif call.data == 'admin_perf_stats':
            handle_perf_stats(mock_msg)
        elif call.data == 'admin_pending_refs':
            handle_pending_refs(mock_msg)
        elif call.data == 'admin_users_pro':
            handle_users_pro(mock_msg)
        elif call.data == 'admin_backup':
            handle_force_backup(mock_msg)
        elif call.data == 'admin_force_news_flash':
            mock_msg.text = "/force_news flash"
            handle_force_news(mock_msg)
        elif call.data == 'admin_force_news_digest':
            mock_msg.text = "/force_news digest"
            handle_force_news(mock_msg)
        elif call.data == 'admin_force_weekly':
            handle_force_weekly(mock_msg)
        elif call.data == 'admin_breaking_test':
            handle_breaking_test(mock_msg)
        elif call.data == 'admin_cleanup_logs':
            mock_msg.text = "/cleanup_logs 90"
            handle_cleanup_logs(mock_msg)
        elif call.data == 'admin_web_dashboard':
            send_admin_dashboard_link(user_id)
        elif call.data in ('admin_guide_user', 'admin_guide_msg', 'admin_guide_referral', 'admin_guide_system', 'admin_guide_all'):
            _admin_guides = {
                'admin_guide_user': (
                    "📖 *คู่มือจัดการสมาชิก & สถิติ* (คัดลอกได้เลย)\n\n"
                    "*จัดการ User & Subscription:*\n"
                    "• `/user_history [uid]` — ดูประวัติ activity\n"
                    "• `/userdebug [uid]` 🆕 — ดู full DB row ของ user (role/quota/total/streak/topup/preview/tier/flash/discount)\n"
                    "• `/reset_quota [uid]` 🆕 — รีเซ็ต usage_count → 0/3 (ใช้กับ test)\n"
                    "• `/addrole [uid] [vip/pro] [days]` — ปรับ role / ต่ออายุ\n"
                    "• `/ban [uid]` / `/unban [uid]` — ระงับ/คืนสิทธิ์\n"
                    "• `/users_pro` — list VIP/PRO ทั้งหมด + วันหมด\n"
                    "• `/whoami` — ตรวจ chat_id + admin status (ใครก็ใช้ได้)\n\n"
                    "*🎟 Promo Codes:*\n"
                    "• `/gencode [days] [uses] [vip/pro] [name?]` — โค้ด days mode\n"
                    "  เช่น `/gencode 7 100 vip WELCOME7`\n"
                    "• `/gencode [pct]% [uses] [vip/pro] [hours] [name?]` — โค้ดส่วนลด %\n"
                    "  เช่น `/gencode 30% 50 pro 24 NEWYEAR30`\n\n"
                    "*สถิติ & Performance:*\n"
                    "• `/stats` — สถิติ user/รายได้\n"
                    "• `/performance` — กำไร/ขาดทุน AI plans\n"
                    "• `/perf_stats` — latency/throughput ระบบ\n"
                    "• `/streak_debug [uid]` — ตรวจ streak counter\n"
                    "• `/track` — global track record + leaderboard + hypothetical return\n"
                    "• `/plansdebug` 🆕 — ตรวจ analysis_plans table (outcome breakdown + recent)\n"
                    "• `/backfill_analyses` 🆕 — backfill total_analyses จาก plan log (one-shot)"
                ),
                'admin_guide_msg': (
                    "📣 *คู่มือบรอดแคสต์ & ข่าว* (คัดลอกได้เลย)\n\n"
                    "• `/broadcast [ข้อความ]` — ส่งข้อความทุก active user\n"
                    "• `/force_news flash` — ยิงข่าวด่วน 1 ข่าวทันที\n"
                    "• `/force_news digest` — ยิงสรุปข่าวย่อ 2 ข่าว\n"
                    "• `/force_weekly` — บรอดแคสต์ Weekly Digest\n"
                    "• `/breaking_test` — ทดสอบ flow Breaking News\n"
                    "• `/mock_alert [symbol] [whale/dump/xd/golden]` — จำลอง alert\n"
                    "• `/earnings [ticker]` — Apexify วิเคราะห์งบการเงินล่าสุด"
                ),
                'admin_guide_referral': (
                    "🤝 *คู่มือ Referral Review* (คัดลอกได้เลย)\n\n"
                    "• `/pending_refs` — list (โชว์ candidate uid match ให้)\n"
                    "• `/award_ref [pending_id] [referrer_uid]` — อนุมัติ + ให้รางวัล\n"
                    "• `/del_pending [pending_id]` — ลบ submission ผิด/spam\n"
                    "• `/finduser [ชื่อ]` — ค้นหา user_id จากชื่อ\n"
                    "• `/reset_trial [uid]` — รีเซ็ต free_trial flag (refund/support)\n\n"
                    "💡 ลูกค้าใส่ user_id ตัวเลข → ระบบ auto-credit ทันที"
                ),
                'admin_guide_system': (
                    "🛠 *คู่มือ System* (คัดลอกได้เลย)\n\n"
                    "• `/maintenance` — toggle maintenance mode\n"
                    "• `/system_health` — สถานะเซิร์ฟเวอร์ + memory\n"
                    "• `/force_backup` — backup database ทันที\n"
                    "• `/cleanup_logs [days=90]` — ลบ log เก่าใน DB\n"
                    "• `/manual` — คู่มือคำสั่งทั้งหมด (มี admin section)"
                ),
                'admin_guide_all': (
                    "📜 *คำสั่ง Admin ทั้งหมด* (คัดลอกได้เลย)\n\n"
                    "*👥 User & Subscription:*\n"
                    "• `/user_history [uid]` — ประวัติ activity\n"
                    "• `/userdebug [uid]` 🆕 — full DB state ของ user\n"
                    "• `/reset_quota [uid]` 🆕 — usage→0/3\n"
                    "• `/addrole [uid] [vip/pro] [days]` — ปรับ role/ต่ออายุ\n"
                    "• `/ban [uid]` / `/unban [uid]`\n"
                    "• `/users_pro` — list VIP/PRO\n"
                    "• `/whoami` — chat_id + admin status\n\n"
                    "*🎟 Promo Codes:*\n"
                    "• `/gencode [days] [uses] [vip/pro] [name?]` — days mode\n"
                    "• `/gencode [pct]% [uses] [vip/pro] [hours] [name?]` — discount mode\n"
                    "  เช่น `/gencode 30% 50 pro 24 NEWYEAR30`\n\n"
                    "*📈 Stats & Performance:*\n"
                    "• `/stats` — user/รายได้\n"
                    "• `/performance` — กำไร/ขาดทุน AI plans\n"
                    "• `/perf_stats` — latency/throughput\n"
                    "• `/streak_debug [uid]` — streak counter\n"
                    "• `/track` — global track record + leaderboard + hypo return\n"
                    "• `/plansdebug` 🆕 — analysis_plans breakdown\n"
                    "• `/backfill_analyses` 🆕 — backfill total_analyses\n\n"
                    "*🤝 Referral:*\n"
                    "• `/pending_refs` — list (มี candidate match)\n"
                    "• `/award_ref [pid] [uid]` — อนุมัติ + รางวัล\n"
                    "• `/del_pending [pid]` — ลบ submission ผิด\n"
                    "• `/finduser [ชื่อ]` — ค้น user_id จากชื่อ\n"
                    "• `/reset_trial [uid]` — รีเซ็ต free_trial flag\n\n"
                    "*📣 Broadcast & News:*\n"
                    "• `/broadcast [ข้อความ]`\n"
                    "• `/force_news flash` / `/force_news digest`\n"
                    "• `/force_weekly` — Weekly Digest\n"
                    "• `/breaking_test` — ทดสอบ Breaking News\n"
                    "• `/mock_alert [symbol] [whale/dump/xd/golden]`\n"
                    "• `/earnings [ticker]` — Apexify วิเคราะห์งบ\n\n"
                    "*🛠 System:*\n"
                    "• `/maintenance` — toggle\n"
                    "• `/system_health` — status\n"
                    "• `/force_backup` — backup DB\n"
                    "• `/cleanup_logs [days=90]` — ลบ log เก่า\n"
                    "• `/manual` — คู่มือ user\n\n"
                    "💡 *Quick action* — กดผ่านปุ่มแผงควบคุมแอดมินได้\n"
                    "🆕 = เพิ่งเพิ่ม sprint นี้"
                ),
            }
            guide = _admin_guides[call.data]
            try:
                bot.send_message(user_id, guide, parse_mode="Markdown")
            except Exception as md_err:
                print(f"[{call.data}] Markdown send failed: {md_err} — retrying as plain text", flush=True)
                try:
                    bot.send_message(user_id, guide)
                except Exception as plain_err:
                    print(f"[{call.data}] plain send failed: {plain_err}", flush=True)
                    bot.answer_callback_query(call.id, "❌ ส่งคู่มือไม่สำเร็จ", show_alert=True)

@bot.message_handler(commands=['earnings'])
def handle_earnings(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    role = check_subscription(user_id)
    if role not in ('vip', 'pro') and user_id != ADMIN_ID:
        bot.reply_to(message, "🔒 **ฟีเจอร์ระดับพรีเมียม (VIP+)**\nการวิเคราะห์งบการเงินด้วย Apexify สงวนสิทธิ์เฉพาะสมาชิก VIP และ PRO ครับ\n\n👉 กด **💎 บัญชี / VIP** เพื่ออัปเกรด", parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/earnings [ชื่อหุ้น]`\n(หุ้นไทยเติม .BK เช่น `/earnings PTT.BK`)", parse_mode="Markdown")
        return

    symbol = args[1].upper()
    load_msg = bot.reply_to(message, f"⏳ Apexify กำลังแกะงบ {symbol} (data + ข่าว + วิเคราะห์)...", parse_mode="Markdown")

    try:
        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
        clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(allowed_suffixes) else symbol
        ticker = yf.Ticker(clean_symbol)

        earnings = ticker.earnings_dates
        if earnings is None or earnings.empty:
            bot.edit_message_text(f"❌ ไม่พบข้อมูลการประกาศงบของ {symbol}", message.chat.id, load_msg.message_id)
            return

        latest_earnings = earnings.iloc[0]
        eps_estimate = latest_earnings.get('EPS Estimate')
        eps_actual = latest_earnings.get('Reported EPS')
        surprise = latest_earnings.get('Surprise(%)')

        def _is_nan(v):
            return v is None or (isinstance(v, float) and v != v)

        # ⏳ งบประกาศแล้วแต่ค่าจริงยังไม่ออก
        if _is_nan(eps_actual):
            earnings_date = latest_earnings.name
            date_str = earnings_date.strftime('%d %b %Y') if hasattr(earnings_date, 'strftime') else 'เร็วๆ นี้'
            est_str = f"{eps_estimate:.2f}" if not _is_nan(eps_estimate) else "ไม่ระบุ"
            bot.edit_message_text(
                f"📅 **{symbol}** — Earnings ประกาศ {date_str}\n\n"
                f"🎯 EPS คาดการณ์: **{est_str}**\n"
                f"⏳ ผลจริงยังไม่ออก หรือ yfinance ยัง sync ไม่ครบ\n\n"
                f"💡 _ลองอีกครั้งใน 2-4 ชม. หลังประกาศ หรือ `/ealert {symbol}` รับแจ้งเตือน_",
                message.chat.id, load_msg.message_id, parse_mode="Markdown"
            )
            return

        # 🌟 Deep data — Revenue + YoY + history (ใหม่)
        revenue_actual = latest_earnings.get('Revenue Actual') or latest_earnings.get('Revenue')
        revenue_estimate = latest_earnings.get('Revenue Estimate')
        rev_act_str = f"${revenue_actual/1e9:.2f}B" if (revenue_actual and not _is_nan(revenue_actual)) else "—"
        rev_est_str = f"${revenue_estimate/1e9:.2f}B" if (revenue_estimate and not _is_nan(revenue_estimate)) else "—"

        # YoY EPS comparison — ดูงบ 4-5 ไตรมาสย้อน
        yoy_str = "—"
        history_str = ""
        try:
            past_eps = []
            for i in range(min(5, len(earnings))):
                e = earnings.iloc[i]
                e_actual = e.get('Reported EPS')
                e_date = e.name
                if not _is_nan(e_actual):
                    past_eps.append((e_date, float(e_actual)))
            if len(past_eps) >= 4:
                yoy_value = (past_eps[0][1] / past_eps[3][1] - 1) * 100 if past_eps[3][1] else 0
                yoy_str = f"{yoy_value:+.1f}%" if past_eps[3][1] else "—"
            if len(past_eps) >= 2:
                last_4 = past_eps[:4]
                history_str = " → ".join(f"{e[1]:.2f}" for e in reversed(last_4))
        except Exception:
            pass

        # Sector + market cap context
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            info = {}
        sector = info.get('sector') or info.get('industry') or "—"
        market_cap = info.get('marketCap')
        cap_str = f"${market_cap/1e9:.1f}B" if market_cap else "—"

        # 📰 News context — inject ข่าว earnings reaction
        news_block = ""
        try:
            from news_context import fetch_ticker_news, format_news_for_prompt
            news_items = fetch_ticker_news(symbol, max_items=4)
            if news_items:
                news_block = "\n\nRecent headlines (post-earnings reactions):\n" + format_news_for_prompt(news_items, max_items=4)
        except Exception as e:
            print(f"[earnings_cmd] news fetch err: {e}", flush=True)

        est_str = f"{eps_estimate:.2f}" if not _is_nan(eps_estimate) else "—"
        act_str = f"{eps_actual:.2f}"
        sur_str = f"{surprise * 100:+.2f}%" if not _is_nan(surprise) else "—"
        beat_label = "เกินคาด" if (not _is_nan(surprise) and surprise > 0) else ("ต่ำกว่าคาด" if (not _is_nan(surprise) and surprise < 0) else "ตามคาด")

        prompt = f"""
คุณคือนักวิเคราะห์งบของ Apexify ตอบเป็น JSON object เท่านั้น ห้ามมี markdown หรือข้อความนอก JSON

ข้อมูลหุ้น {symbol} ({sector}, market cap {cap_str}):
- EPS estimate: {est_str}, EPS actual: {act_str}, Surprise: {sur_str} ({beat_label})
- Revenue estimate: {rev_est_str}, Revenue actual: {rev_act_str}
- EPS YoY (vs ไตรมาสปีก่อนหน้า): {yoy_str}
- EPS 4 ไตรมาสล่าสุด (เก่า→ใหม่): {history_str or "ข้อมูลไม่ครบ"}
{news_block}

กฎ:
- ภาษาไทย เป็นกลาง-ระวัง ห้ามชี้นำซื้อขายเด็ดขาด
- ตอบ JSON ตาม schema ด้านล่าง

Schema:
{{
  "verdict_score": 0-10 ตามคุณภาพงบ (10=ยอดเยี่ยม, 5=กลางๆ, 0=แย่มาก),
  "verdict_label": "ยอดเยี่ยม | ดี | กลางๆ | อ่อน | แย่",
  "headline": "1 ประโยคสรุปงบ ห้ามเกิน 80 ตัวอักษร",
  "highlights": ["จุดเด่น 2-3 ข้อ แต่ละข้อสั้นไม่เกิน 60 ตัวอักษร"],
  "concerns": ["จุดเสี่ยง 1-2 ข้อ แต่ละข้อสั้นไม่เกิน 60 ตัวอักษร"],
  "news_reaction": "1-2 ประโยค ตลาดและข่าวมีปฏิกิริยายังไง (ใช้ headline ที่ให้)",
  "outlook": "1-2 ประโยค แนวโน้มไตรมาสหน้า อ้างอิง guidance/sector หรือ 'ข้อมูลไม่พอ'",
  "price_impact": "bullish | bearish | neutral"
}}
"""

        from google.genai import types as _gtypes
        config = _gtypes.GenerateContentConfig(temperature=0.3, response_mime_type="application/json")
        try:
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash', contents=prompt, config=config
            )
        except Exception:
            response = gemini_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)

        import json as _json
        raw = (getattr(response, 'text', '') or '').strip()
        # extract JSON ถ้า AI ห่อด้วย markdown
        if '{' in raw:
            raw = raw[raw.index('{'): raw.rindex('}') + 1]
        try:
            parsed = _json.loads(raw)
        except Exception:
            parsed = {}

        # Render — ปลอดภัย กรณี AI ไม่ส่ง field ครบ
        v_score = parsed.get('verdict_score')
        v_label = parsed.get('verdict_label') or 'ไม่สามารถประเมิน'
        headline = parsed.get('headline') or 'ไม่มีข้อมูลสรุป'
        highlights = parsed.get('highlights') or []
        concerns = parsed.get('concerns') or []
        news_reaction = parsed.get('news_reaction') or ''
        outlook = parsed.get('outlook') or ''
        impact = (parsed.get('price_impact') or 'neutral').lower()

        impact_emoji = {'bullish': '🟢', 'bearish': '🔴', 'neutral': '⚪'}.get(impact, '⚪')

        # Verdict bar
        if isinstance(v_score, (int, float)):
            score_int = max(0, min(10, int(v_score)))
            score_bar = "▰" * score_int + "▱" * (10 - score_int)
            score_line = f"🎯 *Verdict:* `{score_bar}` *{score_int}/10* — {v_label}"
        else:
            score_line = f"🎯 *Verdict:* {v_label}"

        eps_emoji = '🟢' if (not _is_nan(surprise) and surprise > 0) else ('🔴' if (not _is_nan(surprise) and surprise < 0) else '⚪')

        msg_parts = [
            f"📊 *Apexify Earnings — {symbol}* ({sector})",
            "─" * 17,
            score_line,
            f"_💬 {headline}_",
            "",
            f"*📈 EPS:* `{est_str}` → `{act_str}` {eps_emoji} *{sur_str}* ({beat_label})",
            f"*💵 Revenue:* `{rev_est_str}` → `{rev_act_str}`",
        ]
        if yoy_str != "—":
            msg_parts.append(f"*📅 EPS YoY:* `{yoy_str}`")
        if history_str:
            msg_parts.append(f"*🗓 EPS 4 ไตรมาส:* `{history_str}`")

        if highlights:
            msg_parts.extend(["", "*✅ จุดเด่น:*"])
            for h in highlights[:3]:
                msg_parts.append(f"  • {h}")
        if concerns:
            msg_parts.extend(["", "*⚠️ ความเสี่ยง:*"])
            for c in concerns[:2]:
                msg_parts.append(f"  • {c}")

        if news_reaction:
            msg_parts.extend(["", f"*📰 ตลาด & ข่าว:* {news_reaction}"])
        if outlook and outlook != 'ข้อมูลไม่พอ':
            msg_parts.extend(["", f"*🔮 แนวโน้ม:* {outlook}"])

        msg_parts.extend(["", f"*📊 Price impact:* {impact_emoji} _{impact}_"])
        msg_parts.extend(["", "_⚠️ ข้อมูลเพื่อประกอบการพิจารณา ไม่ใช่คำแนะนำลงทุน_"])

        bot.edit_message_text("\n".join(msg_parts), message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[earnings_cmd] {e}", flush=True)
        bot.edit_message_text(friendly_error("ดึงข้อมูลงบการเงินไม่สำเร็จ"), message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['fund', 'fundamentals'])
def handle_fundamentals(message):
    """VIP/PRO: ดู fundamentals ของหุ้น (P/E, EPS, dividend, market cap, ...)"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role not in ('vip', 'pro') and user_id != ADMIN_ID:
        bot.reply_to(message,
            "🔒 **Fundamentals — ฟีเจอร์ VIP/PRO**\n\n"
            "อัปเกรดเพื่อดูข้อมูลพื้นฐาน (P/E, EPS, Dividend Yield, Market Cap, Beta ...)",
            parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message,
            "❌ รูปแบบผิด! พิมพ์: `/fund <ชื่อหุ้น>`\n"
            "ตัวอย่าง: `/fund AAPL` หรือ `/fund PTT.BK`",
            parse_mode="Markdown")
        return

    raw_symbol = args[1].upper()
    # auto fallback .BK สำหรับหุ้นไทยที่ไม่ใส่ suffix
    symbol = raw_symbol
    load_msg = bot.reply_to(message, f"🔍 กำลังดึงข้อมูลพื้นฐานของ {symbol}...")
    try:
        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
        clean = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(allowed_suffixes) else symbol
        ticker = yf.Ticker(clean)
        info = ticker.info or {}

        # ถ้าไม่เจอ US → ลอง .BK
        if not info.get('regularMarketPrice') and "." not in clean and "-" not in clean:
            fallback = f"{clean}.BK"
            ticker = yf.Ticker(fallback)
            info = ticker.info or {}
            if info.get('regularMarketPrice'):
                symbol = fallback

        if not info.get('regularMarketPrice'):
            bot.edit_message_text(f"❌ ไม่พบข้อมูลหุ้น '{raw_symbol}'", message.chat.id, load_msg.message_id)
            return

        def fmt_num(val, suffix=""):
            if val is None or val == 'N/A':
                return "N/A"
            try:
                v = float(val)
                if suffix == "pct":
                    return f"{v*100:.2f}%"
                if suffix == "B":
                    return f"${v/1e9:.2f}B"
                if suffix == "M":
                    return f"${v/1e6:.0f}M"
                return f"{v:.2f}"
            except (TypeError, ValueError):
                return str(val)

        name = info.get('longName') or info.get('shortName') or symbol
        price = info.get('regularMarketPrice', 0)
        change_pct = info.get('regularMarketChangePercent', 0)
        change_icon = "🟢" if (change_pct or 0) >= 0 else "🔴"

        # Valuation
        pe = info.get('trailingPE')
        forward_pe = info.get('forwardPE')
        peg = info.get('pegRatio')
        pb = info.get('priceToBook')
        eps = info.get('trailingEps')
        eps_forward = info.get('forwardEps')

        # Size
        market_cap = info.get('marketCap')
        enterprise = info.get('enterpriseValue')

        # Dividend
        div_yield = info.get('dividendYield')
        div_rate = info.get('dividendRate')
        payout = info.get('payoutRatio')

        # Profitability
        profit_margin = info.get('profitMargins')
        roe = info.get('returnOnEquity')

        # Risk
        beta = info.get('beta')
        w52_high = info.get('fiftyTwoWeekHigh')
        w52_low = info.get('fiftyTwoWeekLow')

        msg_parts = [
            f"📊 **Fundamentals — {symbol}**",
            f"_{name}_",
            f"{change_icon} ${price:,.2f} ({(change_pct or 0)*100:+.2f}% วันนี้)\n",
            "*💰 Valuation*",
            f"  P/E (TTM): {fmt_num(pe)} | Forward P/E: {fmt_num(forward_pe)}",
            f"  PEG: {fmt_num(peg)} | P/B: {fmt_num(pb)}",
            f"  EPS: {fmt_num(eps)} | Forward EPS: {fmt_num(eps_forward)}\n",
            "*📏 ขนาดบริษัท*",
            f"  Market Cap: {fmt_num(market_cap, 'B')}",
            f"  Enterprise Value: {fmt_num(enterprise, 'B')}\n",
        ]

        if div_yield or div_rate:
            msg_parts.append("*💵 Dividend*")
            msg_parts.append(f"  Yield: {fmt_num(div_yield, 'pct')} | Rate: ${fmt_num(div_rate)}")
            msg_parts.append(f"  Payout Ratio: {fmt_num(payout, 'pct')}\n")

        msg_parts.append("*📈 Profitability*")
        msg_parts.append(f"  Profit Margin: {fmt_num(profit_margin, 'pct')} | ROE: {fmt_num(roe, 'pct')}\n")

        msg_parts.append("*⚖️ Risk*")
        msg_parts.append(f"  Beta: {fmt_num(beta)} (1.0 = volatility เท่าตลาด)")
        if w52_high and w52_low:
            from_high = (price - w52_high) / w52_high * 100
            from_low = (price - w52_low) / w52_low * 100
            msg_parts.append(f"  52W High: ${w52_high:.2f} ({from_high:+.1f}%)")
            msg_parts.append(f"  52W Low: ${w52_low:.2f} ({from_low:+.1f}%)")

        msg_parts.append("\n_📚 Source: yfinance | อัปเดตแบบ real-time_")

        bot.edit_message_text("\n".join(msg_parts), message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[fund] error {symbol}: {e}", flush=True)
        bot.edit_message_text(friendly_error(f"ดึงข้อมูล {symbol} ไม่สำเร็จ"), message.chat.id, load_msg.message_id)


@bot.message_handler(commands=['compare'])
def handle_compare(message):
    """PRO: เปรียบเทียบ 2-3 หุ้น side-by-side + AI บอกตัวไหนน่าซื้อกว่า"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)
    if role != 'pro' and user_id != ADMIN_ID:
        bot.reply_to(message,
            "🔒 **Stock Comparison — ฟีเจอร์ PRO เท่านั้น**\n\n"
            "เปรียบเทียบ 2-3 หุ้น side-by-side พร้อม Apexify วิเคราะห์ว่าตัวไหนน่าสะสมกว่า\n\n"
            "👑 อัปเกรดเป็น PRO เพื่อใช้ฟีเจอร์นี้",
            parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) < 3 or len(args) > 4:
        kb = InlineKeyboardMarkup()
        _dash_btn = _dashboard_cta_button(user_id, "🌐 เปรียบเทียบ S&P500 บน Dashboard", src="compare_err", next_path="/sp500")
        if _dash_btn:
            kb.add(_dash_btn)
        bot.reply_to(message,
            "❌ รูปแบบผิด! พิมพ์: `/compare <หุ้น1> <หุ้น2> [หุ้น3]`\n"
            "ตัวอย่าง: `/compare AAPL MSFT` หรือ `/compare NVDA AMD TSM`\n\n"
            "💡 หรือเปรียบเทียบบน Dashboard ↓",
            parse_mode="Markdown", reply_markup=kb if _dash_btn else None)
        return

    raw_symbols = [s.upper() for s in args[1:]]
    # 🛡 Dedup: ถ้า user พิมพ์ซ้ำ (เช่น NVDA NVDA AMD) → ใช้แค่ตัวเดียว
    seen = set()
    symbols = [s for s in raw_symbols if not (s in seen or seen.add(s))]
    if len(symbols) < 2:
        bot.reply_to(message,
            f"❌ ต้องใช้หุ้นต่างกันอย่างน้อย 2 ตัว — คุณส่งมา: {', '.join(raw_symbols)}",
            parse_mode="Markdown")
        return
    load_msg = bot.reply_to(message, f"🔍 กำลังเปรียบเทียบ {' vs '.join(symbols)}...", parse_mode="Markdown")

    try:
        # 🌟 Parallel fetch — ดึง tech + info พร้อมกัน ลดเวลา 3 ตัวจาก ~15s → ~5s
        from concurrent.futures import ThreadPoolExecutor
        def _fetch_one(sym):
            td, _, err = _get_cached_analysis(sym, generate_chart=False)
            if err or not td:
                return sym, None, None, err
            extras = {}
            try:
                tk = yf.Ticker(sym)
                info = tk.info or {}
                hist = tk.history(period="6mo", interval="1d")
                last30 = [float(x) for x in hist['Close'].tail(30).tolist()] if not hist.empty else []
                ytd_pct = None
                if not hist.empty:
                    cur_year = hist.index[-1].year
                    ys = hist[hist.index.year == cur_year]
                    if not ys.empty and ys['Close'].iloc[0]:
                        ytd_pct = (hist['Close'].iloc[-1] - ys['Close'].iloc[0]) / ys['Close'].iloc[0] * 100
                extras = {
                    'last30': last30,
                    'w52_high': info.get('fiftyTwoWeekHigh'),
                    'w52_low': info.get('fiftyTwoWeekLow'),
                    'ytd_pct': ytd_pct,
                    'pe': info.get('trailingPE') or info.get('forwardPE'),
                    'market_cap': info.get('marketCap'),
                    'beta': info.get('beta'),
                    'div_yield': info.get('dividendYield'),
                    'sector': info.get('sector'),
                }
            except Exception as ex:
                print(f"[compare] extras fetch failed for {sym}: {ex}", flush=True)
            return sym, td, extras, None

        with ThreadPoolExecutor(max_workers=len(symbols)) as ex:
            results = list(ex.map(_fetch_one, symbols))

        all_data = []
        for sym, td, extras, err in results:
            if err or not td:
                bot.edit_message_text(f"❌ ไม่พบข้อมูล '{sym}' — ตรวจตัวสะกดอีกครั้ง", message.chat.id, load_msg.message_id)
                return
            td['_extras'] = extras or {}
            all_data.append(td)

        # Helpers สำหรับ format
        def status_icon(td):
            rsi = td.get('rsi', 50)
            if rsi > 70:
                return "🔴 Overbought"
            if rsi < 30:
                return "🟢 Oversold"
            return "⚪ Neutral"

        def trend_icon(td):
            price = td.get('price', 0)
            ema20 = td.get('ema20', 0)
            pct = (price - ema20) / ema20 * 100 if ema20 else 0
            arrow = "🟢 ขาขึ้น" if price > ema20 else "🔴 ขาลง"
            return f"{arrow} ({pct:+.1f}%)"

        def sparkline(vals):
            if not vals or len(vals) < 2:
                return ''
            blocks = '▁▂▃▄▅▆▇█'
            lo, hi = min(vals), max(vals)
            if hi == lo:
                return blocks[3] * len(vals)
            return ''.join(blocks[int((v - lo) / (hi - lo) * (len(blocks) - 1))] for v in vals)

        def fmt_cap(cap):
            if not cap or cap <= 0:
                return '—'
            if cap >= 1e12:
                return f"${cap/1e12:.2f}T"
            if cap >= 1e9:
                return f"${cap/1e9:.2f}B"
            if cap >= 1e6:
                return f"${cap/1e6:.0f}M"
            return f"${cap:,.0f}"

        def fmt_pct(v, signed=True):
            if v is None:
                return '—'
            return f"{v:+.1f}%" if signed else f"{v:.1f}%"

        comparison_lines = ["⚖️ **Stock Comparison**\n"]
        for td in all_data:
            sym = td.get('symbol', '?')
            price = td.get('price', 0)
            rsi = td.get('rsi', 0)
            macd = td.get('macd', 0)
            signal = td.get('macd_signal', 0)
            atr = td.get('atr')
            volume = td.get('volume', 0)
            avg_vol = td.get('avg_volume', 0)
            vol_ratio = (volume / avg_vol) if avg_vol else None
            macd_direction = "🟢 บวก" if macd > signal else "🔴 ลบ"
            ex = td.get('_extras', {})
            spark = sparkline(ex.get('last30', []))

            # 52W position
            w52_line = ''
            if ex.get('w52_high') and ex.get('w52_low'):
                rng = ex['w52_high'] - ex['w52_low']
                pos_pct = ((price - ex['w52_low']) / rng * 100) if rng else 50
                w52_line = f"  📐 52W: ${ex['w52_low']:,.2f} ─[{pos_pct:.0f}%]─ ${ex['w52_high']:,.2f}\n"

            vol_line = ''
            if vol_ratio is not None:
                vol_emoji = "🔥" if vol_ratio > 1.5 else ("📊" if vol_ratio > 0.8 else "💤")
                vol_line = f"  {vol_emoji} Volume: {vol_ratio:.2f}x ของค่าเฉลี่ย 20 วัน\n"

            atr_pct = (atr / price * 100) if (atr and price) else None
            atr_line = f"  📏 ATR: ${atr:.2f} ({atr_pct:.1f}% ความผันผวน/วัน)\n" if atr_pct else ''

            ytd_line = f"  📅 YTD: {fmt_pct(ex.get('ytd_pct'))}\n" if ex.get('ytd_pct') is not None else ''
            spark_line = f"  📈 30D: `{spark}`\n" if spark else ''

            # Fundamentals row
            fund_parts = []
            if ex.get('pe'):
                fund_parts.append(f"P/E {ex['pe']:.1f}")
            if ex.get('market_cap'):
                fund_parts.append(f"Cap {fmt_cap(ex['market_cap'])}")
            if ex.get('beta'):
                fund_parts.append(f"β {ex['beta']:.2f}")
            if ex.get('div_yield'):
                fund_parts.append(f"Div {ex['div_yield']*100:.1f}%")
            fund_line = f"  💼 {' · '.join(fund_parts)}\n" if fund_parts else ''
            sector_line = f"  🏷 Sector: {ex['sector']}\n" if ex.get('sector') else ''

            comparison_lines.append(
                f"📌 **{sym}** @ ${price:,.2f}\n"
                f"  🌊 {trend_icon(td)}\n"
                f"{spark_line}"
                f"  🌡 RSI {rsi:.1f} — {status_icon(td)}\n"
                f"  ⚡ MACD: {macd_direction} ({macd:.2f}/{signal:.2f})\n"
                f"  🎯 S/R: ${td.get('support', 0):,.2f} / ${td.get('resistance', 0):,.2f}\n"
                f"{w52_line}"
                f"{vol_line}"
                f"{atr_line}"
                f"{ytd_line}"
                f"{fund_line}"
                f"{sector_line}"
            )

        # AI verdict — ส่ง context ที่ขยายแล้วไปด้วย
        context_lines = []
        for td in all_data:
            sym = td.get('symbol', '?')
            ex = td.get('_extras', {})
            atr_pct = (td.get('atr', 0) / td.get('price', 1) * 100) if td.get('atr') and td.get('price') else 0
            avg_vol = td.get('avg_volume', 0)
            vol_ratio = (td.get('volume', 0) / avg_vol) if avg_vol else 1.0
            extras_str = ''
            if ex.get('w52_high') and ex.get('w52_low'):
                rng = ex['w52_high'] - ex['w52_low']
                pos_pct = ((td.get('price', 0) - ex['w52_low']) / rng * 100) if rng else 50
                extras_str += f" 52W_pos={pos_pct:.0f}%"
            if ex.get('ytd_pct') is not None:
                extras_str += f" YTD={ex['ytd_pct']:+.1f}%"
            if ex.get('pe'):
                extras_str += f" PE={ex['pe']:.1f}"
            if ex.get('beta'):
                extras_str += f" Beta={ex['beta']:.2f}"
            if ex.get('sector'):
                extras_str += f" Sector={ex['sector']}"
            context_lines.append(
                f"{sym}: price={td.get('price', 0):.2f} RSI={td.get('rsi', 0):.1f} "
                f"EMA20={td.get('ema20', 0):.2f} MACD={td.get('macd', 0):.2f}/{td.get('macd_signal', 0):.2f} "
                f"S={td.get('support', 0):.2f} R={td.get('resistance', 0):.2f} "
                f"ATR%={atr_pct:.1f} VolRatio={vol_ratio:.2f}{extras_str}"
            )

        try:
            from ai_analyzer import client as ai_client
            ai_prompt = f"""
เปรียบเทียบหุ้น {len(symbols)} ตัว ตอบภาษาไทย 5-6 บรรทัด

ข้อมูลเทคนิค + พื้นฐาน:
{chr(10).join(context_lines)}

คำอธิบาย metrics:
- 52W_pos = ตำแหน่งราคาในช่วง 52 สัปดาห์ (0% = ใกล้ low, 100% = ใกล้ high)
- VolRatio = volume วันนี้ / avg 20 วัน (>1.5 = มีแรงผิดปกติ)
- ATR% = ความผันผวนรายวันเทียบกับราคา
- Beta < 1 = นิ่งกว่าตลาด, > 1 = ผันผวนกว่าตลาด

ตอบตามโครงนี้ ไม่เกิน 500 ตัวอักษร:
1. ตัวไหน "น่าสะสมที่สุด" ตอนนี้ — อ้างอิง metric ที่เด่น (RSI, 52W pos, P/E ฯลฯ)
2. ตัวไหน "ระวังมากสุด" — อ้างอิง metric เสี่ยง (RSI overbought, VolRatio สูง, ATR สูง ฯลฯ)
3. มุมมอง valuation (ใช้ P/E + Sector)
4. สรุปภาพรวม + คำแนะนำ allocation

ห้ามชี้นำซื้อขาย ห้ามใช้คำ "ซื้อเลย" "ขายเลย" "การันตี"
""".strip()
            ai_resp = ai_client.models.generate_content(model='gemini-2.5-flash', contents=ai_prompt)
            ai_verdict = ai_resp.text.strip()[:800]
            comparison_lines.append(f"\n🤖 **AI Verdict:**\n{ai_verdict}")
        except Exception as e:
            print(f"[compare] AI verdict failed: {e}", flush=True)
            comparison_lines.append("\n_(AI verdict ไม่ว่างตอนนี้ — ดูข้อมูลเทคนิคด้านบนประกอบ)_")

        comparison_lines.append(
            "\n_⚠️ ข้อมูลในรายงานเปรียบเทียบนี้จัดทำขึ้นเพื่อประกอบการพิจารณาเท่านั้น "
            "มิใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรใช้ดุลยพินิจของตนเอง_"
        )

        bot.edit_message_text("\n".join(comparison_lines), message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        print(f"[compare] error: {e}", flush=True)
        bot.edit_message_text(friendly_error("เปรียบเทียบไม่สำเร็จ"), message.chat.id, load_msg.message_id)


_analysis_cache = {}  # {symbol: (timestamp, tech_data, chart_bytes, err)}
_ANALYSIS_CACHE_TTL = 300  # 5 minutes


def _get_cached_analysis(symbol, generate_chart=True):
    """ดึงผล analysis จาก cache ถ้ายังไม่หมดอายุ (5 นาที) ลด Gemini+yfinance call
    - เก็บ chart เป็น bytes เพื่อสร้าง BytesIO ใหม่ได้ทุกครั้ง (BytesIO cursor ไม่หมด)
    - generate_chart=False ใช้ใน scan — เร็วกว่ามาก ไม่ต้องรอวาดกราฟ"""
    import io as _io
    now = time.time()
    if symbol in _analysis_cache:
        ts, td, ch_bytes, er = _analysis_cache[symbol]
        if now - ts < _ANALYSIS_CACHE_TTL:
            if generate_chart and ch_bytes is not None:
                return td, _io.BytesIO(ch_bytes), er
            return td, None, er
    td, ch, er = calculate_technical_indicators(symbol, generate_chart=generate_chart)
    ch_bytes = ch.read() if ch is not None else None
    # ถ้า no-chart call ให้คงไว้ chart_bytes เดิมใน cache (ถ้ามี)
    existing = _analysis_cache.get(symbol)
    saved_bytes = ch_bytes if ch_bytes is not None else (existing[2] if existing else None)
    _analysis_cache[symbol] = (now, td, saved_bytes, er)
    chart_out = _io.BytesIO(ch_bytes) if (generate_chart and ch_bytes) else None
    return td, chart_out, er


def _build_chart_preview_banner(remaining):
    """Free user ใช้ chart preview → สร้าง banner ตาม remaining count
    - >0 เหลืออีก: บอกใช้ไปกี่ครั้ง / รวม CHART_PREVIEW_TOTAL
    - 0 ครั้งสุดท้าย: urgency message ดันให้สมัคร VIP
    """
    used = CHART_PREVIEW_TOTAL - remaining  # ใช้ไปแล้วครั้งที่เท่าไหร่
    if remaining > 0:
        return (
            f"🎁 *พรีวิวฟรี — กราฟครั้งที่ {used}/{CHART_PREVIEW_TOTAL}* "
            f"_(เหลืออีก {remaining} ครั้ง · หลังจากนั้นต้อง VIP/PRO)_\n\n"
        )
    return (
        f"🎁 *พรีวิวฟรี — กราฟครั้งที่ {used}/{CHART_PREVIEW_TOTAL} (สุดท้าย!)* 🔥\n"
        f"_ครั้งหน้าต้องสมัคร VIP 79฿/เดือน หรือทดลอง PRO 7 วันฟรี_\n\n"
    )


def _send_safe(bot_instance, chat_id, text, parse_mode=None, reply_markup=None, max_len=4096):
    """ส่งข้อความยาวโดยแบ่งอัตโนมัติถ้าเกิน Telegram limit (4096 chars)"""
    if len(text) <= max_len:
        try:
            bot_instance.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            bot_instance.send_message(chat_id, text, reply_markup=reply_markup)
        return
    chunks, buf = [], ""
    for line in text.split('\n'):
        if len(buf) + len(line) + 1 > max_len:
            chunks.append(buf)
            buf = line
        else:
            buf = (buf + '\n' + line) if buf else line
    if buf:
        chunks.append(buf)
    for i, chunk in enumerate(chunks):
        kb = reply_markup if i == len(chunks) - 1 else None
        try:
            bot_instance.send_message(chat_id, chunk, parse_mode=parse_mode, reply_markup=kb)
        except Exception:
            bot_instance.send_message(chat_id, chunk, reply_markup=kb)

# 🌟 ตัวแปรเก็บสถานะการตอบควิซ
# ==========================================
# 🌟 ตัวรับข้อความหลัก (Main Handler)
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    text = message.text.strip()
    role = check_subscription(user_id)
    if str(user_id) == str(ADMIN_ID):
        role = 'pro'

    # บันทึก last_active (rate-limit ไม่ให้อัปเดตถี่เกิน 5 นาที)
    _la_key = f"la_{user_id}"
    _la_now = time.time()
    if _la_now - _last_active_cache.get(_la_key, 0) > 300:
        _last_active_cache[_la_key] = _la_now
        try:
            update_last_active(user_id)
        except Exception:
            pass

    global user_command_history
    if user_id not in user_command_history:
        user_command_history[user_id] = []
    user_command_history[user_id].append(text)
    if len(user_command_history[user_id]) > 50: 
        user_command_history[user_id].pop(0) 

    if text == "📊 วิเคราะห์หุ้น":
        msg = (
            "📈 **ส่งชื่อหุ้นมาให้ Apexify วิเคราะห์ได้เลยครับ!**\n\n"
            "🇺🇸 หุ้นอเมริกา: พิมพ์ชื่อตรงๆ เช่น `AAPL`, `TSLA`\n"
            "🇹🇭 หุ้นไทย: เติม `.BK` เช่น `PTT.BK`, `AOT.BK`\n"
            "🦘 หุ้นออสเตรเลีย: เติม `.AX` เช่น `CBA.AX`\n"
            "🇬🇧 หุ้นลอนดอน: เติม `.L` เช่น `HSBA.L`\n"
            "🇯🇵 หุ้นญี่ปุ่น: เติม `.T` เช่น `7203.T`\n"
            "🇭🇰 หุ้นฮ่องกง: เติม `.HK` เช่น `0700.HK`\n"
            "🥇 โลหะ/น้ำมัน: พิมพ์ `gold` `silver` `oil` `gas` `copper` `platinum`\n"
            "₿ คริปโต: `btc` `eth`\n\n"
            "*(พิมพ์แล้วกดส่งมาได้เลยครับ!)*"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
        return
        
    elif text == "📖 คู่มือ /manual":
        handle_manual(message)
        return

    elif text == "📱 เปิดเมนูหลัก":
        markup = InlineKeyboardMarkup(row_width=2)
        # 📊 หมวด: วิเคราะห์ & ข้อมูลหุ้น
        markup.add(
            InlineKeyboardButton("📅 สรุปวันนี้", callback_data="hub_today"),
            InlineKeyboardButton("🌍 ตลาดโลก", callback_data="hub_market"),
        )
        markup.add(
            InlineKeyboardButton("📰 ข่าวด่วน", callback_data="hub_news"),
            InlineKeyboardButton("📊 Track Record", callback_data="hub_track"),
        )
        # 💼 หมวด: พอร์ต & Watchlist
        markup.add(
            InlineKeyboardButton("📋 Watchlist", callback_data="hub_watchlist"),
            InlineKeyboardButton("💼 พอร์ตลงทุน", callback_data="hub_portfolio"),
        )
        # 🚀 หมวด: เครื่องมือพรีเมียม
        markup.add(
            InlineKeyboardButton("🚀 สแกนหุ้น (VIP)", callback_data="hub_scan"),
            InlineKeyboardButton("🔥 หุ้นเด่น (PRO)", callback_data="hub_screener"),
        )
        markup.add(
            InlineKeyboardButton("🔔 ตั้งเตือนราคา (PRO)", callback_data="hub_price_alert"),
            InlineKeyboardButton("📈 Earnings Alert", callback_data="hub_earnings"),
        )
        markup.add(
            InlineKeyboardButton("🚨 ข่าวด่วนตลาด US (PRO)", callback_data="hub_breaking"),
        )
        # ⚙️ หมวด: ตั้งค่า + ติดต่อ
        markup.add(
            InlineKeyboardButton("⚙️ ตั้งค่าแจ้งเตือน", callback_data="settings_open"),
            InlineKeyboardButton("🌐 Web Dashboard", callback_data="menu_dashboard"),
        )
        markup.add(
            InlineKeyboardButton("🏆 Badges", callback_data="hub_badges"),
            InlineKeyboardButton("💬 ติดต่อแอดมิน", url="https://t.me/apexify_admin"),
        )

        msg = (
            "📱 **Apexify Hub**\n\n"
            "💡 *เคล็ดลับ:* พิมพ์ `/` ในแชทเพื่อดูคำสั่งทั้งหมด\n"
            "หรือพิมพ์ชื่อหุ้นเลย เช่น `AAPL` `PTT.BK`"
        )
        bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        return
        
    elif text in ["💎 สมัคร VIP", "💎 บัญชี / VIP"]:
        profile = get_user_profile(user_id)
        if profile:
            _, expiry, usage, reg_date = profile
            watch_count = len(get_user_watch(user_id))

            # 🏆 Tier badge + lifetime stats
            try:
                _total_an = get_total_analyses(user_id)
            except Exception:
                _total_an = 0
            try:
                from database import get_streak_info as _gsi
                _streak_info = _gsi(user_id) or {}
            except Exception:
                _streak_info = {}
            _cur_streak = int(_streak_info.get('current') or 0)
            _user_tier = get_user_tier(_total_an, _cur_streak)
            tier_line = ""
            if _user_tier:
                tier_line = f"🏆 *Badge:* {_user_tier['badge']} *{_user_tier['label']}*\n"
            else:
                # Show progress to next tier
                next_tier = TIER_BADGES[0]  # Bronze
                tier_line = f"🏆 *Badge:* — _(วิเคราะห์อีก {next_tier[2] - _total_an} ครั้ง = {next_tier[3]} {next_tier[4]})_\n"

            if role == 'pro': status_text = "👑 PRO (Platinum)"
            elif role == 'vip': status_text = "💎 VIP (Standard)"
            else: status_text = "🆓 Free"

            expiry_text = expiry if expiry else "ไม่มีวันหมดอายุ"
            quota_text = f"ไม่จำกัด" if role in ['vip', 'pro'] else f"{usage}/{FREE_DAILY_QUOTA} ครั้ง"
            reg_text = reg_date[:10] if reg_date else "ไม่ทราบ"

            # 🌟 Streak info — แสดงเสมอแม้ streak = 0 ให้ user รู้ว่ามีฟีเจอร์
            from database import get_streak_info
            streak_data = get_streak_info(user_id)
            cur = streak_data["current"]
            if cur > 0:
                next_in = 7 - (cur % 7) if cur % 7 != 0 else 7
                streak_line = (
                    f"🔥 **Streak:** {cur} วัน "
                    f"_(longest: {streak_data['longest']} | อีก {next_in} วัน รับ VIP +1 วัน)_\n"
                )
            else:
                streak_line = (
                    f"🔥 **Streak:** 0 วัน "
                    f"_(วิเคราะห์หุ้นวันนี้เริ่ม streak ครบ 7 วัน = VIP +1 วันฟรี!)_\n"
                )

            # 💸 Sunk cost messaging — ถ้า free + ใช้มาเยอะ ตอกย้ำ
            sunk_cost_block = ""
            if role == 'free' and _total_an >= 10:
                # Price anchoring แบบ Claude — เปรียบกับเครื่องมืออื่น
                # 79฿/ด ÷ 30 ≈ 2.6฿/ครั้งสำหรับ VIP
                est_value = _total_an * 2.6  # baht equivalent
                sunk_cost_block = (
                    f"\n💸 *คุณวิเคราะห์มาแล้ว* `{_total_an}` *ครั้งตลอดชีวิต*\n"
                    f"_(เทียบมูลค่าใช้บริการ Apexify ฟรีไปประมาณ {est_value:,.0f} บาท · "
                    f"Bualuang Premium 1,200฿/ด · efin StockSelect 990฿/ด)_\n"
                )

            msg = (
                f"👤 **ข้อมูลบัญชี (ID: `{user_id}`)**\n\n"
                f"🏷 **สถานะ:** {status_text}\n"
                f"{tier_line}"
                f"📅 **วันที่เริ่มใช้งาน:** {reg_text}\n"
                f"📈 **โควต้าวิเคราะห์:** {quota_text}\n"
                f"⏰ **แพ็กเกจหมดอายุ:** {expiry_text}\n"
                f"📋 **หุ้นใน Watchlist:** {watch_count} ตัว · 📊 ตลอดชีวิต {_total_an} ครั้ง\n"
                f"{streak_line}"
                f"{sunk_cost_block}\n"
                f"👇 **จัดการบัญชีและแพ็กเกจของคุณ:**"
            )
            
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("💎 สมัคร/ต่ออายุ VIP", callback_data="menu_vip"),
                InlineKeyboardButton("🎁 เติมโค้ด", callback_data="menu_code")
            )
            markup.add(
                InlineKeyboardButton("🤝 ชวนเพื่อน รับ VIP ฟรี", callback_data="menu_referral")
            )
            if role == 'free' and not has_used_free_trial(user_id):
                markup.add(
                    InlineKeyboardButton("🆓 ทดลองใช้ PRO 7 วันฟรี!", callback_data="menu_freetrial")
                )
            _account_btn = _dashboard_cta_button(user_id, "🌐 ดูสิทธิ์ใน Dashboard", src="account_panel")
            if _account_btn:
                markup.add(_account_btn)
            bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.reply_to(message, "❌ ไม่พบข้อมูลบัญชี พิมพ์ /start เพื่อลงทะเบียนใหม่")
        return

    elif text == "⚙️ ตั้งค่าแจ้งเตือน":
        send_settings_panel(message.chat.id, user_id=user_id)
        return
        
    elif text == "👑 แผงควบคุมแอดมิน":
        if user_id != ADMIN_ID: return

        markup = InlineKeyboardMarkup(row_width=2)

        # 🚀 Quick actions — ปุ่มที่กดแล้วทำงานเลยไม่ต้องพิมพ์อาร์กิวเมนต์
        markup.add(
            InlineKeyboardButton("🛠 เปิด/ปิด Maintenance", callback_data="admin_maintenance"),
            InlineKeyboardButton("💻 สถานะเซิร์ฟเวอร์", callback_data="admin_health"),
        )
        markup.add(
            InlineKeyboardButton("📊 สถิติผู้ใช้งาน", callback_data="admin_stats"),
            InlineKeyboardButton("🎯 ผลงานความแม่นยำ", callback_data="admin_perf"),
        )
        markup.add(
            InlineKeyboardButton("⏱ Perf Stats (latency)", callback_data="admin_perf_stats"),
            InlineKeyboardButton("📋 Pending Referrals", callback_data="admin_pending_refs"),
        )
        markup.add(
            InlineKeyboardButton("👑 รายชื่อ PRO/VIP", callback_data="admin_users_pro"),
            InlineKeyboardButton("📦 Backup ฐานข้อมูล", callback_data="admin_backup"),
        )
        markup.add(
            InlineKeyboardButton("📰 Flash News (force)", callback_data="admin_force_news_flash"),
            InlineKeyboardButton("📊 Digest News (force)", callback_data="admin_force_news_digest"),
        )
        markup.add(
            InlineKeyboardButton("📅 Weekly Digest (force)", callback_data="admin_force_weekly"),
            InlineKeyboardButton("🚨 ทดสอบ Breaking News", callback_data="admin_breaking_test"),
        )
        markup.add(
            InlineKeyboardButton("🧹 Cleanup Logs (90d)", callback_data="admin_cleanup_logs"),
            InlineKeyboardButton("🌐 Admin Dashboard", callback_data="admin_web_dashboard"),
        )

        # 📚 Guides — สำหรับคำสั่งที่ต้องพิมพ์อาร์กิวเมนต์เอง
        markup.add(
            InlineKeyboardButton("📖 จัดการสมาชิก & สถิติ", callback_data="admin_guide_user"),
            InlineKeyboardButton("📣 บรอดแคสต์ & ข่าว", callback_data="admin_guide_msg"),
        )
        markup.add(
            InlineKeyboardButton("🤝 Referral Review", callback_data="admin_guide_referral"),
            InlineKeyboardButton("🛠 System & Maintenance", callback_data="admin_guide_system"),
        )
        markup.add(
            InlineKeyboardButton("📜 ดูคำสั่ง Admin ทั้งหมด (รวม)", callback_data="admin_guide_all"),
        )

        admin_text = "👑 **Apexify Admin Master Control**\nเลือกระบบที่คุณต้องการจัดการจากปุ่มด้านล่างได้เลยครับ:"
        bot.reply_to(message, admin_text, parse_mode="Markdown", reply_markup=markup)
        return

    elif text == "🌐 เปิด Dashboard อัตโนมัติ":
        send_dashboard_login_link(user_id)
        return

    symbol = text.upper()
    if len(symbol) > 10:
        bot.reply_to(message,
            "🤔 ยังไม่เข้าใจคำสั่งนี้ครับ\n\n"
            "หากต้องการวิเคราะห์หุ้น พิมพ์ชื่อย่อหุ้นสั้นๆ เช่น `AAPL` หรือ `PTT.BK`\n"
            "หรือพิมพ์ `/manual` เพื่อดูคำสั่งทั้งหมด",
            parse_mode="Markdown")
        return

    usage = get_usage(user_id)
    if user_id != ADMIN_ID and role == 'free' and usage >= FREE_DAILY_QUOTA:
        # 🎟 Try Top-up first — atomic consume; ถ้า balance > 0 หัก 1 + ให้ผ่าน
        topup_consumed = False
        try:
            if consume_topup_balance(user_id, count=1):
                topup_consumed = True
                _remaining = get_topup_balance(user_id)
                bot.reply_to(
                    message,
                    f"🎟 หัก Top-up 1 ครั้ง · เหลือ **{_remaining} ครั้ง**",
                    parse_mode="Markdown",
                )
        except Exception as _e:
            print(f"[Topup] consume err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)
            topup_consumed = False

    # paywall block: ทำงานเฉพาะเมื่อ topup ไม่ได้หัก
    if user_id != ADMIN_ID and role == 'free' and usage >= FREE_DAILY_QUOTA and not locals().get('topup_consumed', False):
        from datetime import datetime as _dt, timedelta as _td
        _now_thai = _dt.utcnow() + _td(hours=7)
        _midnight = _now_thai.replace(hour=0, minute=0, second=0, microsecond=0) + _td(days=1)
        _mins_left = int((_midnight - _now_thai).total_seconds() // 60)
        _h, _m = divmod(_mins_left, 60)
        _reset_str = f"{_h} ชม. {_m} นาที" if _h else f"{_m} นาที"
        # 🌟 Inline upsell — ให้ user กดสมัครได้ทันทีไม่ต้อง dig menu
        # Top-up = ทางเลือกที่ commit ต่ำสุด สำหรับคนยังไม่อยากผูก subscription
        upsell_kb = InlineKeyboardMarkup(row_width=2)
        upsell_kb.add(
            InlineKeyboardButton("🎟 เติม 20฿ → ใช้ได้ 10 ครั้ง (2฿/ครั้ง)", callback_data="qr_pay_20"),
        )
        upsell_kb.add(
            InlineKeyboardButton("💎 VIP 79฿ · ไม่จำกัด", callback_data="menu_vip"),
            InlineKeyboardButton("👑 PRO 109฿ · ทุกฟีเจอร์", callback_data="menu_vip"),
        )
        if not has_used_free_trial(user_id):
            upsell_kb.add(InlineKeyboardButton("🆓 ทดลองใช้ PRO 7 วันฟรี!", callback_data="menu_freetrial"))
        upsell_kb.add(InlineKeyboardButton("🎁 เติมโค้ดส่วนลด", callback_data="menu_code"))
        # 🎯 quota_exceeded = high-intent moment — ส่งไป /payment โดยตรง (เดิมไป / ทำให้ CTR 0%)
        _quota_btn = _dashboard_cta_button(
            user_id, "💎 อัปเกรดในเว็บ → เห็นทุกราคา + ส่วนลด",
            src="quota_exceeded",
            next_path="/payment?tier=vip",
        )
        if _quota_btn:
            upsell_kb.add(_quota_btn)

        # 🌟 Smart Paywall — preview ของ ticker + flash discount + social proof
        preview_block = ""
        try:
            from ai_analyzer import build_paywall_preview, render_paywall_preview
            preview = build_paywall_preview(symbol)
            if preview:
                preview_block = "\n\n" + render_paywall_preview(preview)
        except Exception as _e:
            print(f"[SmartPaywall] preview err for {symbol}: {type(_e).__name__}: {str(_e)[:80]}", flush=True)

        # 🎁 Flash discount — เปิด 30 นาทีถ้า eligible (one-shot per cooldown)
        flash_block = ""
        try:
            eligible, expires_at = start_flash_discount_if_eligible(user_id)
            if eligible and expires_at:
                # 🐛 Fix: start_flash_discount ใช้ datetime.now() (server local) — เปรียบกับ
                # _dt.utcnow() + 7h ทำให้ผลลัพธ์ผิด ใช้ datetime.now() ตรงกัน
                mins_left = max(1, int((expires_at - _dt.now()).total_seconds() // 60))
                if mins_left > FLASH_WINDOW_MINUTES + 1:
                    mins_left = FLASH_WINDOW_MINUTES
                flash_block = (
                    f"\n\n🎁 *พิเศษ! ลด 20% ภายใน {mins_left} นาที* 🔥\n"
                    f"  💎 *VIP* {FLASH_VIP_AMOUNT}฿ (ปกติ 79฿) · ประหยัด 16฿\n"
                    f"  👑 *PRO* {FLASH_PRO_AMOUNT}฿ (ปกติ 109฿) · ประหยัด 22฿\n"
                    f"  _โอนยอดส่วนลดได้เลย — บอทจะอัปเกรดอัตโนมัติ_"
                )
                upsell_kb.add(
                    InlineKeyboardButton(f"🎁 VIP {FLASH_VIP_AMOUNT}฿ (ลด 20%)", callback_data=f"qr_pay_{FLASH_VIP_AMOUNT}"),
                    InlineKeyboardButton(f"🎁 PRO {FLASH_PRO_AMOUNT}฿ (ลด 20%)", callback_data=f"qr_pay_{FLASH_PRO_AMOUNT}"),
                )
        except Exception as _e:
            print(f"[FlashDiscount] err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)

        # 👥 Social proof — ดึง real-time จาก DB
        social_block = ""
        try:
            stats = get_social_proof_stats(symbol)
            parts = []
            if stats.get("watching_symbol", 0) > 0:
                parts.append(f"👥 *{stats['watching_symbol']}* คนติดตาม {symbol}")
            if stats.get("active_24h", 0) > 5:
                parts.append(f"🔥 *{stats['active_24h']}* คนใช้ Apexify ใน 24 ชม.")
            if stats.get("new_paid_7d", 0) > 0:
                parts.append(f"💎 *{stats['new_paid_7d']}* VIP/PRO active")
            if parts:
                social_block = "\n\n" + " · ".join(parts)
        except Exception as _e:
            print(f"[SocialProof] err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)

        # 📊 Track Record booster — ใส่ hit rate ของ symbol + global ใน paywall
        track_block = ""
        try:
            from database import get_track_record_by_symbol, get_track_record_stats
            sym_track = get_track_record_by_symbol(symbol, days=90)
            global_track = get_track_record_stats(days=90)
            track_parts = []
            if sym_track and sym_track.get("closed", 0) >= 2:
                track_parts.append(
                    f"📊 *{symbol}* ใน Apexify: {sym_track['wins']}/{sym_track['closed']} hit "
                    f"*({sym_track['hit_rate_pct']:.0f}%)*"
                )
            if global_track and global_track.get("closed", 0) >= 10:
                track_parts.append(
                    f"🏆 รวม 90 วัน: hit rate *{global_track['hit_rate_pct']:.0f}%* "
                    f"({global_track['closed']} plans)"
                )
            if track_parts:
                track_block = "\n\n" + "\n".join(track_parts)
        except Exception as _e:
            print(f"[TrackRecord] paywall err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)

        if preview_block:
            upsell_msg = (
                f"✨ **ใช้ครบโควต้าประจำวันแล้วครับ** ({FREE_DAILY_QUOTA}/{FREE_DAILY_QUOTA})\n"
                f"🕛 รีเซ็ตในอีก **{_reset_str}**"
                f"{preview_block}"
                f"{track_block}"
                f"{flash_block}"
                f"{social_block}\n\n"
                f"_💡 ทดลอง PRO ฟรี 7 วัน — เห็นทุกอย่างของ {symbol} ทันที_"
            )
        else:
            # fallback ถ้า preview ดึงไม่ได้ (ticker ไม่มีข้อมูล)
            upsell_msg = (
                f"✨ **ขอบคุณที่ใช้ครบโควต้าประจำวันครับ** ({FREE_DAILY_QUOTA}/{FREE_DAILY_QUOTA})\n\n"
                f"🕛 ระบบจะรีเซ็ตโควต้าใหม่ในอีก **{_reset_str}**\n\n"
                f"💎 *สนใจใช้งานไม่จำกัด + ปลดล็อกฟีเจอร์พรีเมียม?*\n"
                f"• 📊 กราฟเทคนิคเต็มรูปแบบ\n"
                f"• 🔭 Apexify Trend Radar 3 ระยะ\n"
                f"• 🎯 Entry / TP / SL ชัดเจน พร้อมกราฟ (PRO)\n"
                f"• 🔔 Smart Alerts + สรุปข่าวรายวัน (PRO)"
            )
        bot.reply_to(message, upsell_msg, parse_mode="Markdown", reply_markup=upsell_kb)
        return

    load_msg = bot.reply_to(message, f"🔍 กำลังดึงข้อมูล **{symbol}**...", parse_mode="Markdown")

    def _safe_edit(text):
        try:
            bot.edit_message_text(text, message.chat.id, load_msg.message_id, parse_mode="Markdown")
        except Exception:
            pass

    # 🌟 Tier-aware chart:
    # - Free: text only (แต่ได้ preview 3 ครั้งแรกตลอดชีวิต)
    # - VIP: basic chart
    # - PRO: skip basic + วาด annotated หลังได้ plan
    chart_preview_consumed = False
    chart_preview_remaining = 0
    if role == 'free' and user_id != ADMIN_ID:
        try:
            consumed, remaining = consume_chart_preview(user_id)
            chart_preview_consumed = consumed
            chart_preview_remaining = remaining
        except Exception as _e:
            print(f"[ChartPreview] analyze err: {type(_e).__name__}: {str(_e)[:80]}", flush=True)
    want_chart = (role == 'vip') or chart_preview_consumed
    tech_data, chart, err = _get_cached_analysis(symbol, generate_chart=want_chart)

    if err:
        # 🛡 Refund chart preview ถ้า consume แล้วแต่ analyze fail
        if chart_preview_consumed:
            try:
                refund_chart_preview(user_id)
            except Exception as _e:
                print(f"[ChartPreview] refund err: {_e}", flush=True)
        _safe_edit(err)
        return

    _safe_edit(f"🤖 Apexify กำลังวิเคราะห์ **{symbol}**...")

    # 🌟 Wrap AI report generation — กัน Gemini 503/safety crash ทำให้ load_msg ค้าง
    try:
        report, plan = generate_apexify_report(tech_data, role=role, user_id=user_id)
        # 🎁 Free user ใช้ preview → banner count + urgency เมื่อหมด
        if chart_preview_consumed:
            report = _build_chart_preview_banner(chart_preview_remaining) + report
    except Exception as e:
        print(f"[Analyze] generate_apexify_report failed for {symbol}: {e}", flush=True)
        # 🛡 Refund chart preview — Gemini fail ไม่ควรให้ user เสียครั้งฟรี
        if chart_preview_consumed:
            try: refund_chart_preview(user_id)
            except Exception: pass
        err_str = str(e).lower()
        if '503' in err_str or 'unavailable' in err_str or 'overloaded' in err_str or 'high demand' in err_str:
            friendly = "✨ ขณะนี้มีผู้ใช้งาน AI จำนวนมาก ขอรบกวนลองพิมพ์อีกครั้งในอีกสักครู่นะครับ 🙏"
        elif 'safety' in err_str or 'blocked' in err_str:
            friendly = "📋 ระบบความปลอดภัยของ Apexify ขอปฏิเสธหุ้นตัวนี้ชั่วคราว\nลองวิเคราะห์หุ้นตัวอื่นดูก่อนนะครับ"
        else:
            friendly = "📡 ขณะนี้ข้อมูลยังไม่พร้อมให้บริการ\nรบกวนลองอีกครั้งในอีกสักครู่ครับ"
            # Sentry-lite: ping admin only on the unknown-error branch (503 + safety filter is expected noise)
            from bot_utils import alert_admin_error
            alert_admin_error(bot, f"Analyze:{symbol}", e, user_id=user_id)
        bot.edit_message_text(friendly, message.chat.id, load_msg.message_id)
        return

    # 🌟 PRO: สร้างกราฟ annotated หลังได้ plan
    if role == 'pro' and plan:
        _safe_edit(f"🎨 กำลังวาดกราฟ **{symbol}** + Plan...")
        try:
            chart = generate_pro_annotated_chart(symbol, plan)
        except Exception as e:
            print(f"[Analyze] pro chart failed for {symbol}: {e}", flush=True)
            chart = None
        # 🌟 Track Record — log plan ไว้ตรวจ outcome ภายหลัง
        try:
            from database import log_analysis_plan
            log_analysis_plan(
                user_id=user_id,
                symbol=tech_data.get('symbol', symbol),
                bias='bullish' if plan.get('tp1') and plan.get('entry_low') and plan['tp1'] > plan['entry_low'] else 'bearish',
                entry_low=plan.get('entry_low'),
                entry_high=plan.get('entry_high'),
                tp1=plan.get('tp1'),
                tp2=plan.get('tp2'),
                sl=plan.get('sl'),
                price_at_issue=tech_data.get('price'),
            )
        except Exception as e:
            print(f"[Analyze] log_plan failed: {e}", flush=True)

    # 📊 Lifetime analysis count + tier badge check (รวม admin ด้วย — ให้เห็น UI ตอนเทส)
    new_total = 0
    newly_unlocked_tiers = []
    try:
        new_total = increment_total_analyses(user_id)
    except Exception as _e:
        print(f"[total_analyses] err: {_e}", flush=True)
    # ตรวจ tier badge — ถ้า unlock ใหม่จะ DM แจ้ง user หลัง report
    try:
        from database import get_streak_info
        _streak_data = get_streak_info(user_id) or {}
        _cur_streak = int(_streak_data.get('current') or 0)
        newly_unlocked_tiers = check_and_grant_tier_codes(user_id, new_total, _cur_streak) or []
    except Exception as _e:
        print(f"[tier] check err: {_e}", flush=True)

    if user_id != ADMIN_ID and role == 'free':
        increment_usage(user_id)
        # 🌟 Quota visibility — show usage explicitly so trial users feel pressure to upgrade
        used = usage + 1
        remaining = FREE_DAILY_QUOTA - used
        # 💸 Sunk cost messaging — ถ้า user ใช้มาเกิน 10 ครั้ง ใส่ลงไปด้วย
        sunk_cost_line = ""
        if new_total >= 10:
            sunk_cost_line = (
                f"\n📊 _คุณวิเคราะห์มาแล้ว **{new_total} ครั้ง** ตลอดชีวิต — "
                f"สมัคร PRO เห็น Plan/Entry/SL ของทุกหุ้นที่คุณเคยถาม_"
            )
        # Concrete tier teaser — same copy on every free analysis so user sees
        # what they're missing in real numbers, not generic "upgrade" CTAs.
        tier_teaser = (
            "💎 _VIP 79฿/เดือน เห็นเพิ่ม:_ กราฟเทคนิค · Trend Radar 3 TF · Watch Next\n"
            "👑 _PRO 109฿/เดือน เพิ่ม:_ Entry/TP1/TP2/SL · กราฟ annotated · /ask /compare"
        ) + sunk_cost_line
        if remaining <= 0:
            report += (
                f"\n\n📊 **Free Trial:** ใช้ครบ {used}/{FREE_DAILY_QUOTA} วันนี้แล้ว — รีเซ็ตเที่ยงคืน 🌙\n\n"
                f"{tier_teaser}"
            )
        elif remaining == 1:
            # Penultimate analysis — peak intent moment for upgrade decision
            report += (
                f"\n\n⚠️ **Free Trial:** เหลือ {remaining} ครั้งสุดท้ายวันนี้ ({used}/{FREE_DAILY_QUOTA})\n\n"
                f"{tier_teaser}"
            )
        else:
            report += (
                f"\n\n📊 **Free Trial:** {used}/{FREE_DAILY_QUOTA} วันนี้ (เหลือ {remaining} ครั้ง)\n\n"
                f"{tier_teaser}"
            )

    # 🌟 Day-trade discipline coach — แจ้งเตือนถ้าวิเคราะห์ซ้ำหุ้นเดียวกันถี่เกินใน 1 วัน
    # ตลาดไม่เปลี่ยนทุก 30 นาที — โค้ชเตือนให้ใจเย็น (PP P. ขอ)
    try:
        report = _maybe_append_daytrade_coach(user_id, symbol, report)
    except Exception as e:
        print(f"[DaytradeCoach] error: {e}", flush=True)

    # 🌟 Achievement badges — gamification, ตรวจหลัง increment_usage
    try:
        from database import evaluate_achievements, ACHIEVEMENT_CATALOG
        new_badges = evaluate_achievements(user_id, context="analyze")
        if new_badges:
            badge_lines = []
            for code in new_badges:
                label, desc = ACHIEVEMENT_CATALOG.get(code, (code, ""))
                badge_lines.append(f"{label} — _{desc}_")
            badge_msg = "🏆 **ปลดล็อก Badge ใหม่!**\n" + "\n".join(badge_lines)
            try:
                bot.send_message(user_id, badge_msg, parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        print(f"[Achievement] eval error: {e}", flush=True)

    # 🌟 Daily Streak — อัปเดตทุกครั้งที่วิเคราะห์หุ้น
    streak_notification = None
    try:
        from database import update_user_streak, grant_streak_reward
        streak = update_user_streak(user_id)
        if streak["milestone_7days"]:
            # ครบ 7 วัน → +1 วัน VIP ฟรี
            granted = grant_streak_reward(user_id, days=1)
            if granted:
                streak_notification = (
                    f"🔥 **Streak {streak['current']} วัน!** 🎉\n\n"
                    f"ขอแสดงความยินดี! คุณใช้งาน Apexify ทุกวันต่อเนื่อง\n"
                    f"🎁 รับ **VIP +1 วันฟรี** ไปเลย!\n\n"
                    f"_Longest streak: {streak['longest']} วัน — ทำลายสถิติไปอีกได้!_"
                )
            else:
                # Grant fail (ไม่ควรเกิดปกติ) — แจ้ง user ว่าได้ streak แล้ว
                streak_notification = (
                    f"🔥 **Streak {streak['current']} วัน!** 🎉\n\n"
                    f"ขอแสดงความยินดี! (ระบบรางวัลขัดข้องเล็กน้อย — แอดมินจะตรวจสอบให้)\n\n"
                    f"_Longest: {streak['longest']} วัน_"
                )
        elif streak["is_new_day"] and streak["current"] in (3, 14, 30, 50, 100):
            # แสดง celebration ที่ milestone พิเศษ (ที่ไม่ใช่ multiple of 7)
            remaining = 7 - (streak['current'] % 7) if streak['current'] % 7 != 0 else 7
            streak_notification = (
                f"🔥 **Streak {streak['current']} วัน!** ต่อเนื่อง\n"
                f"_อีก {remaining} วัน ถึง reward ถัดไป (+VIP 1 วัน)_"
            )
    except Exception as e:
        import traceback
        print(f"[streak] outer error: {e}\n{traceback.format_exc()}", flush=True)

    correct_symbol = tech_data['symbol']
    # 🌟 เก็บ symbol ล่าสุดของ user เพื่อใช้ใน /ask context
    _user_last_symbol[user_id] = correct_symbol

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"⭐ Watchlist", callback_data=f"addwatch_{correct_symbol}"))

    # 🌟 Contextual quick-actions (VIP/PRO เท่านั้น — แต่ละปุ่มจะเช็ค role ของตัวเองอีกที)
    if role in ('vip', 'pro'):
        markup.add(
            InlineKeyboardButton(f"📊 Fundamentals", callback_data=f"quick_fund_{correct_symbol}"),
            InlineKeyboardButton(f"📈 งบการเงิน", callback_data=f"quick_earnings_{correct_symbol}"),
        )
    if role == 'pro':
        markup.add(
            InlineKeyboardButton(f"⚖️ เปรียบเทียบหุ้นอื่น", callback_data=f"quick_compare_{correct_symbol}"),
            InlineKeyboardButton(f"💬 ถาม Apexify เพิ่ม", callback_data=f"quick_ask_{correct_symbol}"),
        )
        markup.add(
            InlineKeyboardButton(f"🔔 ตั้งเตือนราคา", callback_data="hub_price_alert"),
        )

    markup.add(
        InlineKeyboardButton("💼 พอร์ต", callback_data="hub_portfolio"),
        InlineKeyboardButton("📱 เมนูหลัก", callback_data="hub_home"),
    )
    # 🎯 analysis_result CTA — label specific to action (CTR ก่อนหน้านี้ 3.7%)
    # เปลี่ยน "ดู Dashboard" generic → "ติดตาม {SYM}" ที่ user รู้ว่า click แล้วได้อะไร
    _analysis_btn = _dashboard_cta_button(
        user_id, f"🔔 ติดตาม {correct_symbol} ในเว็บ", src="analysis_result",
        next_path=f"/watchlist?symbol={correct_symbol}",
    )
    if _analysis_btn:
        markup.add(_analysis_btn)

    try:
        bot.delete_message(message.chat.id, load_msg.message_id)
    except Exception:
        pass

    # 🌟 ส่งรายงาน — Free: text only, VIP/PRO: chart + text
    if chart is None:
        _send_safe(bot, message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
    else:
        try:
            bot.send_photo(message.chat.id, chart)
        except Exception:
            pass
        _send_safe(bot, message.chat.id, report, parse_mode="Markdown", reply_markup=markup)

    # 🌟 Streak notification — ส่งหลังรายงาน (ถ้ามี milestone)
    if streak_notification:
        try:
            bot.send_message(message.chat.id, streak_notification, parse_mode="Markdown")
        except Exception:
            pass

    # 🏆 Tier badge unlock — DM ใหม่ที่ผ่าน threshold เพิ่งเปิดในรอบนี้
    if newly_unlocked_tiers:
        for tier in newly_unlocked_tiers:
            try:
                role_word = "VIP" if tier['role_type'] == 'vip' else "PRO"
                msg = (
                    f"{tier['badge']} *ปลดล็อก Badge ใหม่: {tier['label']}!* 🎉\n\n"
                    f"🎁 รับโค้ดส่วนตัว: `{tier['code']}`\n"
                    f"แลกได้ **{role_word} +{tier['days']} วันฟรี**\n\n"
                    f"พิมพ์: `/redeem {tier['code']}` เพื่อแลกเลย\n"
                    f"_โค้ดนี้ใช้ได้ครั้งเดียว · ของคุณคนเดียว_"
                )
                bot.send_message(message.chat.id, msg, parse_mode="Markdown")
            except Exception as _e:
                print(f"[tier-dm] {tier.get('tier_id')}: {_e}", flush=True)


if __name__ == "__main__":
    keep_alive()  # Flask ขึ้นก่อนเลย

    def _bg_init():
        try:
            init_db()
        except Exception as e:
            print("DB Init Error:", e)
        try:
            init_new_features_db()
        except Exception as e:
            print("DB Init Error:", e)
        # 🆕 2026-05-15: Run auto-downgrade IMMEDIATELY at startup (defense in depth)
        # Bug: alert_loop's midnight check could be delayed by slow stock_news loop
        # (~30-60 min per iteration with Gemini 503 retries) → miss midnight window
        try:
            from database import auto_downgrade_expired_users
            auto_downgrade_expired_users()
        except Exception as _e:
            print(f"[main] startup downgrade err: {_e}", flush=True)
        run_alert_loop(bot)

    threading.Thread(target=_bg_init, daemon=True).start()

    # 🧹 Auto-Downgrade Cron — separate thread, runs every 30 min
    # 🆕 2026-05-15: ที่ alert_loop midnight check ไม่ได้ trigger เพราะ stock_news
    # loop ช้ามาก (~50-60 min/iteration ตอน Gemini 503) → ผ่าน midnight window
    # ทางแก้: thread แยกตัวเอง poll ทุก 30 min — independent ของ alert_loop
    # Function เป็น idempotent (run 100 ครั้งเหมือนกัน) → safe to call frequently
    def _downgrade_cron_loop():
        from database import auto_downgrade_expired_users
        time.sleep(60)   # warm-up
        while True:
            try:
                auto_downgrade_expired_users()
            except Exception as _e:
                print(f"[downgrade-cron] err: {_e}", flush=True)
            time.sleep(30 * 60)   # 30 min

    threading.Thread(target=_downgrade_cron_loop, daemon=True, name="downgrade-cron").start()
    print("[main] downgrade cron thread started (poll every 30 min)", flush=True)

    # 📬 Auto-DM Cron — daily 11:00 ICT (activation + win-back)
    try:
        from auto_dm_cron import run_auto_dm_cron
        threading.Thread(target=run_auto_dm_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] auto_dm_cron failed to start: {_e}", flush=True)

    # 📊 Plan Evaluator Cron — auto /run_outcomes ทุก 6 ชม.
    # แก้ปัญหา: admin run มือ 5/30 วัน → 365 pending plans ค้าง → track record stale
    try:
        from plan_evaluator_cron import run_plan_evaluator_cron
        threading.Thread(target=run_plan_evaluator_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] plan_evaluator_cron failed to start: {_e}", flush=True)

    # ☀️ Daily Stock Picker — DM admin 3 หุ้นน่าโพสต์วันนี้ (7:30 ICT)
    # Mix Mag 7 + S&P 500 + story stocks + chart image + suggested FB hook
    try:
        from daily_stock_picker import run_daily_picker_cron
        threading.Thread(target=run_daily_picker_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] daily_picker failed to start: {_e}", flush=True)

    # 📅 Earnings Prep — DM admin 1 วันก่อนหุ้นใหญ่รายงานผล (16:00 ICT)
    try:
        from earnings_prep_cron import run_earnings_prep_cron
        threading.Thread(target=run_earnings_prep_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] earnings_prep failed to start: {_e}", flush=True)

    # 🌅 Daily P&L Recap — DM PRO users สรุป watchlist ทุกเช้า (08:00 ICT)
    try:
        from daily_pnl_cron import run_daily_pnl_cron
        threading.Thread(target=run_daily_pnl_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] daily_pnl failed to start: {_e}", flush=True)

    # 🐳 Smart Money — DM admin + PRO watchlist หุ้นที่ insider ซื้อใหญ่ (16:00 ICT)
    # Source: OpenInsider cluster-buys (SEC Form 4, T+2 day filing rule, official)
    try:
        from smart_money_cron import run_smart_money_cron
        threading.Thread(target=run_smart_money_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] smart_money failed to start: {_e}", flush=True)

    # ⚠️ Plan Proximity Warning — เตือน PRO ก่อนราคาใกล้ SL/TP/Entry (poll ทุก 5 นาที)
    # SL ±1.5% · TP ±1% · Entry zone ±1% · cooldown 1 ชม./plan/level
    try:
        from plan_proximity_cron import run_proximity_cron
        threading.Thread(target=run_proximity_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] plan_proximity failed to start: {_e}", flush=True)

    # 🔔 Pre-Market Movers — DM VIP+PRO 1 ชม.ก่อน US เปิด (19:30 ICT = 08:30 EDT in summer)
    # ⚠️ Winter (EST): set env PREMARKET_HOUR_ICT=20
    # gap ≥3% · hybrid: watchlist matches + top 3 discovery · PP P. request 2026-05-13
    try:
        from premarket_cron import run_premarket_cron
        threading.Thread(target=run_premarket_cron, args=(bot,), daemon=True).start()
    except Exception as _e:
        print(f"[main] premarket failed to start: {_e}", flush=True)

    # 💓 Heartbeat — เขียน timestamp ไป /tmp/apexify_heartbeat.txt ทุก 60s
    # ใช้คู่กับ heartbeat_watchdog.py (cron */5 min) ที่ DM admin ถ้า stale > 5 min
    def _heartbeat_loop():
        from pathlib import Path
        hb_file = Path("/tmp/apexify_heartbeat.txt")
        while True:
            try:
                hb_file.write_text(str(time.time()), encoding="utf-8")
            except Exception as e:
                print(f"[heartbeat] write err: {e}", flush=True)
            time.sleep(60)

    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    print("[heartbeat] writer started — /tmp/apexify_heartbeat.txt every 60s", flush=True)

    # 🌟 Pre-warm yfinance cache — popular tickers refresh ทุก 5 นาที
    # ทำให้ user ที่ขอหุ้นเหล่านี้ได้รายงานเกือบทันที (cache hit)
    POPULAR_TICKERS = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
        "PTT.BK", "KBANK.BK", "AOT.BK", "ADVANC.BK", "CPALL.BK",
        "0700.HK", "7203.T",
    ]

    def _prewarm_loop():
        time.sleep(20)  # รอ Flask + DB init เสร็จก่อน
        cycle = 0
        while True:
            cycle += 1
            t0 = time.time()
            for sym in POPULAR_TICKERS:
                try:
                    from technical_tools import _fetch_history_cached
                    # 🌟 ต้อง warm ทั้ง auto_adjust=True (calculate_technical_indicators) และ False (multi-timeframe context)
                    # เพราะ key ต่างกัน — ถ้า warm แค่ค่าใดค่าหนึ่ง analyze flow จะ MISS อยู่ดี
                    _fetch_history_cached(sym, period="1y", auto_adjust=True)   # for calculate_technical_indicators
                    _fetch_history_cached(sym, period="1y", interval="1d", auto_adjust=False)  # for multi-tf
                    _fetch_history_cached(sym, period="5y", interval="1wk", auto_adjust=False)
                    _fetch_history_cached(sym, period="10y", interval="1mo", auto_adjust=False)
                except Exception as e:
                    print(f"[prewarm] {sym} error: {e}", flush=True)
                time.sleep(1)  # rate-limit yfinance ไม่ให้ถูก ban
            print(f"[prewarm] cycle {cycle} done in {time.time()-t0:.1f}s — sleeping 60s", flush=True)
            time.sleep(60)  # TTL 300s, cycle ทุก ~75s → cache อยู่ตลอด

    threading.Thread(target=_prewarm_loop, daemon=True).start()

    # 🌟 Set bot commands menu — แสดงใน Telegram เมื่อ user พิมพ์ "/"
    try:
        from telebot.types import BotCommand, BotCommandScopeChat

        public_commands = [
            BotCommand("start", "เริ่มใช้งาน / ลงทะเบียน"),
            BotCommand("demo", "ทัวร์ฟีเจอร์ทั้งหมด — ดูบอททำอะไรได้บ้าง"),
            BotCommand("manual", "คู่มือคำสั่งทั้งหมด"),
            BotCommand("account", "ดูสถานะบัญชี + Streak + โควต้า"),
            BotCommand("payment", "สมัคร/ต่ออายุ VIP/PRO + ดู QR ชำระเงิน"),
            BotCommand("portfolio", "ดูพอร์ตลงทุน + กำไร/ขาดทุนสด"),
            BotCommand("add", "เพิ่มหุ้นเข้าพอร์ต — /add AAPL 10 150"),
            BotCommand("edit", "แก้จำนวน/ราคาเฉลี่ย — /edit AAPL 15 165"),
            BotCommand("del", "ลบหุ้นออกจากพอร์ต — /del AAPL"),
            BotCommand("pnl", "สร้างการ์ด P&L แบบสวยงาม"),
            BotCommand("watch", "เพิ่มหุ้นเข้า Watchlist — /watch AAPL"),
            BotCommand("unwatch", "ลบหุ้นออกจาก Watchlist — /unwatch AAPL"),
            BotCommand("track", "สถิติ Apexify Plans — hit rate ย้อนหลัง"),
            BotCommand("fund", "ข้อมูลพื้นฐาน (P/E, EPS, Dividend) — VIP/PRO"),
            BotCommand("compare", "เปรียบเทียบ 2-3 หุ้น — PRO"),
            BotCommand("ask", "ถาม Apexify คำถามการลงทุน — PRO"),
            BotCommand("earnings", "Apexify วิเคราะห์งบการเงิน — VIP/PRO"),
            BotCommand("ealert", "แจ้งเตือนวัน Earnings — VIP/PRO"),
            BotCommand("setalert", "ตั้งเตือนราคา — PRO"),
            BotCommand("myalerts", "ดู price alerts ที่ตั้งไว้"),
            BotCommand("delalert", "ลบ price alert — /delalert [id]"),
            BotCommand("breaking", "ข่าวด่วนตลาด US (เปิด/ปิด) — PRO"),
            BotCommand("badges", "ดู Achievement badges ที่สะสม"),
            BotCommand("weekly_recap", "สรุปอาทิตย์นี้ — watchlist 7d + streak"),
            BotCommand("freetrial", "ทดลอง PRO 7 วันฟรี"),
            BotCommand("redeem", "เติมโค้ดโปรโมชั่น"),
            BotCommand("settings", "ตั้งค่าการแจ้งเตือน"),
            BotCommand("dashboard", "เปิด Web Dashboard"),
            BotCommand("contact", "ติดต่อแอดมิน @apexify_admin"),
        ]
        bot.set_my_commands(public_commands)
        print("✅ Public bot commands menu set", flush=True)

        # 🔒 Admin scope — admin เห็น public + admin commands ใน popup ของตัวเอง
        # ใช้ BotCommandScopeChat ผูกกับ ADMIN_ID — user ปกติยังเห็นแค่ public list
        if ADMIN_ID:
            try:
                admin_extras = [
                    BotCommand("ban",            "[Admin] แบน user"),
                    BotCommand("unban",          "[Admin] ยกเลิกแบน user"),
                    BotCommand("addrole",        "[Admin] เพิ่ม role ให้ user"),
                    BotCommand("gencode",        "[Admin] สร้างโค้ดโปรโมชั่น"),
                    BotCommand("users_pro",      "[Admin] list VIP/PRO ทั้งหมด"),
                    BotCommand("user_history",   "[Admin] ดูประวัติ activity ของ user"),
                    BotCommand("stats",          "[Admin] สถิติ user/รายได้"),
                    BotCommand("performance",    "[Admin] ผลกำไร/ขาดทุน AI plans"),
                    BotCommand("perf_stats",     "[Admin] latency/throughput"),
                    BotCommand("streak_debug",   "[Admin] ตรวจ streak counter"),
                    BotCommand("pending_refs",   "[Admin] referral submissions รออนุมัติ"),
                    BotCommand("award_ref",      "[Admin] อนุมัติ + ให้รางวัล referral"),
                    BotCommand("del_pending",    "[Admin] ลบ pending referral"),
                    BotCommand("reset_trial",    "[Admin] รีเซ็ต free_trial flag"),
                    BotCommand("finduser",       "[Admin] ค้นหา user_id จากชื่อ"),
                    BotCommand("broadcast",      "[Admin] ส่งข้อความทุก active user"),
                    BotCommand("force_news",     "[Admin] บรอดแคสต์ flash/digest"),
                    BotCommand("force_weekly",   "[Admin] บรอดแคสต์ Weekly Digest"),
                    BotCommand("mock_alert",     "[Admin] จำลอง alert ทดสอบ"),
                    BotCommand("breaking_test",  "[Admin] ทดสอบ Breaking News"),
                    BotCommand("maintenance",    "[Admin] toggle maintenance mode"),
                    BotCommand("force_backup",   "[Admin] backup database"),
                    BotCommand("system_health",  "[Admin] สถานะเซิร์ฟเวอร์"),
                    BotCommand("cleanup_logs",   "[Admin] ลบ log เก่าใน DB"),
                ]
                bot.set_my_commands(
                    public_commands + admin_extras,
                    scope=BotCommandScopeChat(chat_id=int(ADMIN_ID)),
                )
                print(f"✅ Admin bot commands menu set (chat_id={ADMIN_ID})", flush=True)
            except Exception as admin_err:
                print(f"⚠️ admin set_my_commands failed: {admin_err}", flush=True)
    except Exception as e:
        print(f"⚠️ set_my_commands failed: {e}", flush=True)

    # Webhook mode: ถ้ามี BOT_WEB_BASE_URL → ใช้ webhook, ไม่มี → fallback polling
    _base = BOT_WEB_BASE_URL.rstrip("/") if BOT_WEB_BASE_URL else ""
    if _base and _base.startswith("https://"):
        _secret = TELEGRAM_TOKEN.split(":")[-1]
        _webhook_url = f"{_base}/webhook/{_secret}"
        set_webhook_bot(bot)
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=_webhook_url)
        print(f"🔗 Webhook mode: {_base}/webhook/***", flush=True)
        # Flask server รันอยู่แล้วใน keep_alive() — block main thread ไม่ให้จบ
        try:
            import signal
            signal.pause()
        except (AttributeError, OSError):
            # Windows ไม่มี signal.pause
            while True:
                time.sleep(3600)
    else:
        print("📡 Polling mode (no BOT_WEB_BASE_URL set)", flush=True)
        bot.remove_webhook()
        bot.infinity_polling()
