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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from keep_alive import keep_alive, set_webhook_bot
from config import TELEGRAM_TOKEN, ADMIN_ID, DASHBOARD_LOGIN_TOKEN_TTL, APEXIFY_PASSWORD, gemini_client, BOT_WEB_BASE_URL
from dashboard_login import issue_admin_dashboard_url, issue_dashboard_login_url
# 🌟 Import ฟังก์ชันฐานข้อมูลทั้งหมด รวมถึงระบบจัดการพอร์ต
from database import (get_all_users, init_db, register_user, check_subscription, add_subscription,
                      get_usage, increment_usage, add_watch, get_user_watch, get_user_profile,
                      remove_watch_db, add_promo_code, redeem_code, get_user_stats,
                      claim_slip_and_add_subscription, ban_user, unban_user, is_user_banned,
                      init_new_features_db, process_referral, get_referral_stats,
                      add_price_alert_db, get_user_price_alerts_db, remove_price_alert_db,
                      get_connection, add_portfolio_stock, get_user_portfolio,
                      get_user_settings, set_user_notifications, set_user_timezone,
                      set_user_language, set_user_digest_frequency, set_user_news_window,
                      ALLOWED_TIMEZONES, ALLOWED_LANGUAGES, ALLOWED_DIGEST_FREQUENCIES,
                      has_used_free_trial, activate_free_trial,
                      add_earnings_alert_db, get_user_earnings_alerts_db, remove_earnings_alert_db,
                      update_last_active, mark_user_inactive, get_active_users)
from admin_service import (
    build_local_backup_zip,
    get_maintenance_status,
    get_paid_users_snapshot,
    get_performance_snapshot,
    get_system_health_snapshot,
    get_user_stats_snapshot,
    toggle_maintenance_status,
)
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index
from ai_analyzer import generate_apexify_report
from alert_system import broadcast_hourly_urgent_news, check_and_broadcast_pro_news, run_alert_loop
from slipok_service import verify_payment_slip
from curl_cffi import requests as cffi_requests

telebot.logger.setLevel(logging.WARNING)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

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
    bot.reply_to(message, f"🛠 **สถานะ Maintenance Mode:** {status}", parse_mode="Markdown")

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
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาดในการ Backup: {e}", message.chat.id, load_msg.message_id)

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
        bot.edit_message_text(f"❌ ไม่สามารถดึงข้อมูลระบบได้: {e}", message.chat.id, load_msg.message_id)

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
    
    load_msg = bot.reply_to(message, f"🚨 กำลังสั่งให้ AI ดึงข่าวด่วนแบบ `{news_type.upper()}` และบรอดแคสต์ทันที...")
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
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาดในการดึงข่าว: {e}", message.chat.id, load_msg.message_id)

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
def send_dashboard_login_link(user_id):
    success, login_url, reason = issue_dashboard_login_url(user_id)
    if not success:
        if reason in {'disabled', 'url_missing', 'secret_missing'}:
            bot.send_message(user_id, "ระบบลิงก์ Dashboard ยังไม่พร้อมใช้งาน กรุณาติดต่อแอดมิน")
        else:
            bot.send_message(user_id, "ไม่สามารถสร้างลิงก์เข้า Dashboard ได้ กรุณาลองใหม่อีกครั้ง")
        return

    ttl_seconds = max(1, int(DASHBOARD_LOGIN_TOKEN_TTL))
    ttl_minutes = max(1, (ttl_seconds + 59) // 60)
    apexify_password = APEXIFY_PASSWORD or "(ยังไม่ได้ตั้งค่า APEXIFY_PASSWORD/AUTH_SHARED_PASSCODE)"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("เปิดแดชบอร์ด (ล็อกอินอัตโนมัติ)", url=login_url))
    msg = (
        "กดปุ่มด้านล่างเพื่อเปิด Dashboard แบบล็อกอินอัตโนมัติ\n"
        f"ลิงก์นี้มีอายุประมาณ {ttl_minutes} นาที\n\n"
        "ข้อมูลสำหรับล็อกอินผ่านหน้าเว็บ (กรณีเข้าอัตโนมัติไม่สำเร็จ)\n"
        f"- Telegram ID: {user_id}\n"
        f"- รหัส Apexify: {apexify_password}\n\n"
        "หากลิงก์หมดอายุ ให้กด /dashboard เพื่อสร้างลิงก์ใหม่"
    )
    bot.send_message(user_id, msg, reply_markup=markup)


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
    if len(args) > 1 and args[1].startswith('REF_'):
        referrer_id = args[1].replace('REF_', '')
        if referrer_id != user_id:
            try:
                success, milestone_hit = process_referral(referrer_id, user_id)
                if success:
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
        "🎁 **ทดลองใช้ฟรี 10 ครั้ง** ไม่ต้องสมัคร\n\n"
        "**เริ่มต้น 3 ขั้นตอน:**\n"
        "1️⃣ พิมพ์ชื่อหุ้น → รับรายงานวิเคราะห์ทันที\n"
        "   `AAPL` `TSLA` `NVDA` `PTT.BK` `AOT.BK`\n"
        "2️⃣ กด ⭐ ใต้รายงาน → เพิ่มเข้า Watchlist\n"
        "3️⃣ รับแจ้งเตือนสัญญาณ & ข่าวอัตโนมัติ\n\n"
        "👇 กด **📱 เปิดเมนูหลัก** เพื่อดูฟีเจอร์ทั้งหมด"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

    # Tutorial card with inline keyboard
    tutorial_markup = InlineKeyboardMarkup(row_width=2)
    tutorial_markup.add(
        InlineKeyboardButton("📊 ลอง AAPL", callback_data="tutorial_analyze_AAPL"),
        InlineKeyboardButton("📊 ลอง PTT.BK", callback_data="tutorial_analyze_PTT.BK"),
    )
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
            bot.reply_to(message, "❌ รูปแบบผิด! กรุณาพิมพ์: `/add [ชื่อหุ้น] [จำนวน] [ราคาเฉลี่ย]`\nเช่น: `/add AAPL 10 150`", parse_mode='Markdown')
            return
        
        ticker = parts[1].upper()
        shares = float(parts[2])
        cost = float(parts[3])

        role = check_subscription(user_id)
        if user_id != ADMIN_ID:
            portfolio_count = len(get_user_portfolio(user_id))
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
        
    except ValueError:
        bot.reply_to(message, "❌ จำนวนหุ้นและราคาต้องเป็นตัวเลขเท่านั้นครับ!")
    except Exception as e:
        print(f"[BotError] {e}", flush=True)
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

        msg = "\n".join(lines)
        bot.edit_message_text(msg, chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode='HTML')
        
    except Exception as e:
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาดในการดึงข้อมูล: {e}", chat_id=message.chat.id, message_id=processing_msg.message_id)


@bot.message_handler(commands=['pnl'])
def handle_pnl_card(message):
    """คำสั่ง /pnl [ชื่อหุ้น] เพื่อสร้างการ์ดอวดกำไร"""
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❌ กรุณาพิมพ์ชื่อหุ้นด้วยครับ เช่น <code>/pnl NVDA</code>", parse_mode='HTML')
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
        
       # สร้างแคปชั่นพร้อมแนบลิงก์ Referral ของคนกด
        pnl_caption = (
            f"ตลาดจะผันผวนแค่ไหนก็ไม่หวั่น ถ้ามีผู้ช่วยส่วนตัวดีๆ 🤖✨ "
            f"ผลประกอบการ <b>{ticker}</b> รอบนี้บวกมาสวยๆ ขอบคุณ <b>Apexify Trading AI</b> "
            f"ที่ช่วยสแกนหาจุดเข้าและคอยเตือนตลอด 24 ชม. ใครอยากเทรดสบายขึ้นแบบนี้ มากดลองใช้ฟรีได้เลย! 👇\n\n"
            f"🔗 ลิงก์บอท: https://t.me/Apexify_Trading_bot?start=REF_{user_id}"
        )

        # ส่งรูปลงแชท
        bot.send_photo(
            message.chat.id, 
            photo=image_bytes, 
            caption=pnl_caption,
            parse_mode='HTML'
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
            bot.reply_to(message, "❌ วิธีใช้: `/delalert [รหัสการตั้งเตือน]`\n(ดูรหัสได้จากเมนู 🔔 ตั้งเตือนราคา)", parse_mode="Markdown")
            return
        alert_id = int(args[1])
        remove_price_alert_db(user_id, alert_id)
        bot.reply_to(message, "🗑️ **ยกเลิกการแจ้งเตือนราคารายการนี้เรียบร้อยแล้วครับ**", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ รูปแบบไม่ถูกต้อง")

# ==========================================
# 🌟 ระบบคำสั่งแอดมิน 
# ==========================================
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
    if str(message.chat.id) != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: /gencode [จำนวนวัน] [จำนวนคนที่ใช้ได้] [vip/pro]")
        return
    try:
        days = int(args[1])
        max_uses = int(args[2])
        role_type = args[3].lower() if len(args) > 3 else 'vip'
        
        code = f"{role_type.upper()}{days}-" + generate_random_code(6)
        if add_promo_code(code, days, max_uses, role_type):
            msg = (
                f"✅ **สร้างโค้ด {role_type.upper()} สำเร็จ!**\n\n"
                f"🎟 **โค้ด:** `{code}`\n"
                f"⏰ **เพิ่มวัน:** {days} วัน\n"
                f"👥 **จำนวนสิทธิ์:** ใช้ได้ {max_uses} คน\n\n"
                f"*(ส่งให้ลูกค้ากด Copy และพิมพ์ /redeem ตามด้วยโค้ดได้เลย)*"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: /gencode [จำนวนวัน] [จำนวนคนที่ใช้ได้] [vip/pro]")

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
        bot.reply_to(message, f"🎉 **ยินดีด้วย!** เติมโค้ดสำเร็จ\nคุณได้รับการอัปเกรดเป็น **{role_type.upper()} Member** ถึงวันที่: `{expiry}`\n\nสามารถใช้งานฟีเจอร์ใหม่ได้ทันทีครับ 🚀", parse_mode="Markdown")
        increment_usage(user_id) 
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
        bot.reply_to(message, "ℹ️ คุณมีแพ็กเกจ VIP/PRO อยู่แล้วครับ ไม่จำเป็นต้องใช้ Free Trial")
        return
    if has_used_free_trial(user_id):
        bot.reply_to(message,
            "⚠️ **Free Trial ใช้ได้เพียง 1 ครั้งต่อบัญชีครับ**\n\n"
            "💎 หากต้องการใช้งานต่อ สมัคร VIP/PRO ได้ที่เมนู [💎 บัญชี / VIP]",
            parse_mode="Markdown")
        return
    ok = activate_free_trial(user_id)
    if ok:
        bot.reply_to(message,
            "🎉 **ยินดีต้อนรับสู่ PRO 7 วัน!**\n\n"
            "✅ คุณได้รับสิทธิ์ PRO เต็มรูปแบบ 7 วันฟรีแล้ว\n\n"
            "**สิ่งที่คุณทำได้ตอนนี้:**\n"
            "• วิเคราะห์หุ้นไม่จำกัดครั้ง\n"
            "• รับข่าว Flash News & Digest\n"
            "• Morning Briefing รายวัน\n"
            "• Watchlist ไม่จำกัด\n\n"
            "_ใช้งานได้จนครบ 7 วัน — จากนั้นอัปเกรดเพื่อใช้ต่อเนื่อง_",
            parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งครับ")


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


@bot.message_handler(commands=['manual'])
def handle_manual(message):
    """คู่มือการใช้งานคำสั่งทั้งหมด"""
    user_id = str(message.chat.id)
    if not is_allowed(user_id):
        return
    role = check_subscription(user_id)

    msg = (
        "📖 **คู่มือการใช้งาน Apexify** 📖\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"

        "**🔍 วิเคราะห์หุ้น**\n"
        "พิมพ์ชื่อหุ้นตรงๆ ได้เลย ไม่ต้องใช้คำสั่ง\n"
        "`AAPL` `TSLA` `NVDA` — หุ้น US\n"
        "`PTT.BK` `KBANK.BK` — หุ้นไทย (ต้องมี .BK)\n"
        "`CBA.AX` `.L` `.HK` `.T` — ตลาดอื่นๆ\n\n"

        "**💼 จัดการพอร์ต**\n"
        "`/add AAPL 10 150` — บันทึกซื้อหุ้น 10 หุ้น ราคา 150\n"
        "`/portfolio` หรือ `/port` — ดูพอร์ตทั้งหมด\n"
        "`/pnl` — สร้างการ์ด P&L แบบสวยงาม\n\n"

        "**🔔 ตั้งเตือนราคา**\n"
        "`/setalert AAPL 200` — แจ้งเตือนเมื่อ AAPL ถึง $200\n"
        "`/setalert AAPL +5%` — แจ้งเตือนเมื่อขึ้น 5%\n"
        "`/setalert AAPL -3%` — แจ้งเตือนเมื่อลง 3%\n"
        "`/delalert AAPL` — ลบการแจ้งเตือนของ AAPL\n\n"

        "**📅 Earnings Calendar** _(VIP/PRO)_\n"
        "`/ealert AAPL` — สมัครแจ้งเตือนวัน Earnings\n"
        "`/ealert list` — ดูรายการที่สมัครไว้\n"
        "`/ealert remove AAPL` — ยกเลิก\n"
        "`/earnings AAPL` — วิเคราะห์งบการเงิน AI _(VIP/PRO)_\n\n"

        "**💎 บัญชี & สิทธิ์**\n"
        "`/freetrial` — ทดลอง PRO 7 วันฟรี (ใช้ได้ 1 ครั้ง)\n"
        "`/redeem [โค้ด]` — เติมโค้ดโปรโมชั่น\n\n"

        "**⚙️ การตั้งค่า**\n"
        "`/settings` — ตั้งค่าการแจ้งเตือน, timezone, ภาษา\n"
        "`/dashboard` — เปิด Web Dashboard\n\n"

        "**📱 เมนูลัด**\n"
        "📊 วิเคราะห์หุ้น — เริ่มวิเคราะห์\n"
        "📱 เปิดเมนูหลัก — Hub ฟีเจอร์ทั้งหมด\n"
        "💎 บัญชี / VIP — ดูสถานะ & สมัครแพ็กเกจ\n"
    )
    if str(user_id) == str(ADMIN_ID):
        msg += (
            "\n**👑 Admin Commands**\n"
            "`/addrole [uid] [vip/pro] [days]` — เพิ่ม role\n"
            "`/gencode [days] [uses] [vip/pro]` — สร้างโค้ด\n"
            "`/ban [uid]` / `/unban [uid]` — จัดการ user\n"
            "`/broadcast [msg]` — ส่งข้อความทุกคน\n"
            "`/stats` — สถิติผู้ใช้\n"
            "`/maintenance` — toggle maintenance mode\n"
            "`/force_news` — force ส่งข่าว\n"
        )
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=['addrole'])
def handle_add_role(message):
    if str(message.chat.id) == ADMIN_ID:
        try:
            args = message.text.split()
            target_user = args[1]
            role = args[2].lower()
            days = int(args[3]) if len(args) > 3 else 30
            expiry = add_subscription(target_user, role, days)
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
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

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

            slip_packages = {
                1090: ('pro', 365, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายปี)**\n⏰ หมดอายุ: {expiry}"),
                790: ('vip', 365, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายปี)**\n⏰ หมดอายุ: {expiry}"),
                109: ('pro', 30, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายเดือน)**\n⏰ หมดอายุ: {expiry}"),
                79: ('vip', 30, "🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายเดือน)**\n⏰ หมดอายุ: {expiry}"),
            }
            package_info = slip_packages.get(amount)
            if not package_info:
                bot.edit_message_text(
                    f"❌ **ยอดเงินไม่ตรงกับแพ็กเกจ** ({amount:,.2f} บาท)\nกรุณาโอนให้ตรงราคา (79, 109, 790, 1090)",
                    message.chat.id,
                    progress_msg.message_id,
                    parse_mode="Markdown",
                )
                bot.send_message(
                    ADMIN_ID,
                    (
                        f"⚠️ **ยอดผิดปกติจาก SlipOK** User `{user_id}` โอน `{amount:,.2f}` บาท\n"
                        f"Ref: `{ref_no}`\n"
                        f"ผู้โอน: `{slip_result.get('sender_display_name') or '-'}`"
                    ),
                    parse_mode="Markdown",
                )
                return

            target_role, subscription_days, message_template = package_info
            claim_status, expiry = claim_slip_and_add_subscription(
                user_id,
                ref_no,
                target_role,
                subscription_days,
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
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_') or call.data.startswith('delalert_') or call.data.startswith('menu_') or call.data.startswith('hub_') or call.data.startswith('admin_') or call.data.startswith('settings_') or call.data.startswith('tutorial_') or call.data.startswith('qr_pay_'))
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
        tech_data, chart, err = _get_cached_analysis(symbol)
        if err or not tech_data:
            bot.edit_message_text(f"❌ ไม่สามารถดึงข้อมูล {symbol} ได้", user_id, load_msg.message_id)
            return
        report = generate_apexify_report(tech_data, role=role)
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
            pay_text = (
                "🚀 **แพ็กเกจ APEXIFY** 🚀\n"
                "💳 กสิกรไทย: `135-1-34469-1` (นาย เกียรติศักดิ์ วุฒิจันทร์)\n"
                "*(โอนแล้วส่งสลิปในแชทนี้ ระบบอัปเกรดอัตโนมัติใน 3 วิ!)*\n\n"

                "🆓 **BASIC (ฟรี)**\n"
                "• สแกน AI 10 ครั้ง/วัน\n"
                "• Watchlist 3 ตัว\n"
                "• Fear & Greed, PnL Card\n"
                "• พอร์ตเว็บ 3 ตัว, DRIP/Simulator\n\n"

                "💎 **VIP — 79.-/เดือน หรือ 790.-/ปี**\n"
                "• สแกน AI ไม่จำกัด\n"
                "• Watchlist 10 ตัว + Scan all\n"
                "• Morning Briefing, AI Podcast, News Digest\n"
                "• Daily Portfolio Summary\n"
                "• พอร์ตเว็บ 10 ตัว, Trade Plan, Health Score, Heatmap, Matchmaker\n\n"

                "👑 **PRO — 109.-/เดือน หรือ 1,090.-/ปี** 🔥\n"
                "• ทุกอย่างของ VIP +\n"
                "• Watchlist & พอร์ตเว็บ ไม่จำกัด\n"
                "• Smart Alerts, Technical Radar\n"
                "• Flash News, Dividend Hunter, Screener\n"
                "• AI Rebalance, Port Doctor, Sentiment Analysis\n"
            )
            # เพิ่มปุ่มเลือกแพ็กเกจ + สร้าง QR
            qr_markup = InlineKeyboardMarkup(row_width=2)
            qr_markup.add(
                InlineKeyboardButton("💎 VIP 79.-/เดือน", callback_data="qr_pay_79"),
                InlineKeyboardButton("👑 PRO 109.-/เดือน", callback_data="qr_pay_109"),
            )
            qr_markup.add(
                InlineKeyboardButton("💎 VIP 790.-/ปี", callback_data="qr_pay_790"),
                InlineKeyboardButton("👑 PRO 1,090.-/ปี", callback_data="qr_pay_1090"),
            )
            bot.send_message(user_id, pay_text, parse_mode="Markdown", reply_markup=qr_markup)
        except Exception as e:
            bot.send_message(user_id, f"❌ เกิดข้อผิดพลาดในการโหลดเมนู VIP: {e}")

    elif call.data.startswith('qr_pay_'):
        try:
            from promptpay_qr import generate_promptpay_qr
            from config import PROMPTPAY_ID
            amount_str = call.data.replace('qr_pay_', '')
            amount = int(amount_str)
            pkg_names = {79: "💎 VIP รายเดือน", 109: "👑 PRO รายเดือน", 790: "💎 VIP รายปี", 1090: "👑 PRO รายปี"}
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
            bot.send_message(user_id, f"❌ ไม่สามารถสร้าง QR ได้: {e}")

    elif call.data == 'menu_code':
        bot.send_message(user_id, "🎟 **พิมพ์คำสั่ง:** `/redeem [โค้ดของคุณ]`", parse_mode="Markdown")
        
    elif call.data == 'menu_referral':
        try:
            ref_count = get_referral_stats(user_id)
            bot_info = bot.get_me()
            bot_username = bot_info.username
            ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
            next_milestone = 3 - (ref_count % 3) if ref_count % 3 != 0 else 3
            progress_bar = "🟩" * (ref_count % 3) + "⬜" * (3 - (ref_count % 3))
            msg = (
                "🤝 **ชวนเพื่อน รับรางวัล!** 🤝\n\n"
                "🎁 **รางวัล Milestone:**\n"
                "   ทุก **3 เพื่อน** → **+10 วัน ฟรี!**\n"
                "   (ชวนครบ 6 = +20 วัน, 9 = +30 วัน ...)\n\n"
                f"📊 **ความคืบหน้าของคุณ:** {ref_count} คน\n"
                f"   {progress_bar}  อีก {next_milestone} คน ถึง milestone!\n\n"
                f"🔗 **ลิงก์ของคุณ:**\n`{ref_link}`\n\n"
                "_คัดลอกลิงก์ส่งให้เพื่อน — เพื่อนต้องกด Start ผ่านลิงก์นี้เท่านั้น_"
            )
            bot.send_message(user_id, msg, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(user_id, "❌ ระบบชวนเพื่อนขัดข้องชั่วคราว กรุณาลองใหม่ครับ")
            
    elif call.data == 'menu_freetrial':
        role = check_subscription(user_id)
        if role in ('vip', 'pro'):
            bot.answer_callback_query(call.id, "คุณมีแพ็กเกจ VIP/PRO อยู่แล้วครับ", show_alert=True)
        elif has_used_free_trial(user_id):
            bot.answer_callback_query(call.id, "Free Trial ใช้ได้เพียง 1 ครั้ง/บัญชีครับ", show_alert=True)
        else:
            ok = activate_free_trial(user_id)
            if ok:
                bot.send_message(user_id,
                    "🎉 **PRO 7 วันฟรี เปิดใช้งานแล้ว!**\n\n"
                    "✅ วิเคราะห์ไม่จำกัด\n"
                    "✅ Flash News & Morning Briefing\n"
                    "✅ Earnings Alert (`/ealert`)\n\n"
                    "_ใช้งานได้ทันที 7 วัน ขอบคุณที่ลองใช้ครับ!_",
                    parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "ระบบขัดข้อง กรุณาลองใหม่ครับ", show_alert=True)

    elif call.data == 'menu_dashboard':
        send_dashboard_login_link(user_id)

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
            bot.edit_message_text(f"❌ ดึงข้อมูลล้มเหลว: {e}", user_id, load_msg.message_id)

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
            bot.send_message(user_id, f"❌ Error: {e}")

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
                bot.send_message(user_id, "🔒 ฟีเจอร์สงวนสิทธิ์เฉพาะ **VIP / PRO**")
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
            bot.send_message(user_id, f"❌ Error: {e}")

    elif call.data == 'hub_screener':
        try:
            if role != 'pro' and user_id != ADMIN_ID:
                bot.send_message(user_id, "🔒 **ฟีเจอร์ระดับพรีเมียม (PRO Exclusive)**\nสแกนหุ้นเด่นอัตโนมัติสงวนสิทธิ์ให้ลูกค้าระดับ PRO เท่านั้นครับ 👑", parse_mode="Markdown")
                return
            
            scan_msg = bot.send_message(user_id, "⏳ **Apexify กำลังสแกนหาหุ้นเด่น...**\n*(ค้นหาจากกลุ่ม SET50 และ US Tech ที่เพิ่งเกิด Golden Cross หรือ RSI ตกเข้าโซน Oversold)*")
            
            scan_list = ['PTT.BK', 'AOT.BK', 'ADVANC.BK', 'CPALL.BK', 'DELTA.BK', 'GULF.BK', 'KBANK.BK', 'SCB.BK', 'BDMS.BK', 'BBL.BK', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'GOOGL']
            
            found_stocks = []
            for sym in scan_list:
                try:
                    tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                    if err or not tech_data: continue
                    
                    rsi = tech_data['rsi']
                    ema50 = tech_data['ema50']
                    ema200 = tech_data['ema200']
                    price = tech_data['price']
                    
                    is_golden = (ema50 > ema200) and (ema50 / ema200 < 1.02)
                    is_oversold = rsi < 30
                    
                    if is_golden or is_oversold:
                        reason = "✨ เพิ่งเกิด Golden Cross (เทรนด์เปลี่ยนเป็นขาขึ้น)" if is_golden else f"🎯 น่าสะสม (RSI ต่ำเพียง {rsi:.2f})"
                        found_stocks.append(f"📌 **{sym}** (ราคา: {price:,.2f})\n   👉 {reason}")
                except Exception:
                    pass
            
            if found_stocks:
                result_msg = "🔥 **หุ้นเด่นน่าเก็บประจำวัน (Apexify Screener)** 🔥\n\n" + "\n\n".join(found_stocks)
            else:
                result_msg = "🔥 **หุ้นเด่นน่าเก็บประจำวัน** 🔥\n\nขณะนี้ยังไม่พบหุ้นที่เข้าเกณฑ์ Golden Cross หรือ Oversold แบบชัดเจนครับ\n*(Apexify แนะนำให้จับตาดูตลาด หรือถือเงินสดรอดูสถานการณ์)*"
                
            bot.edit_message_text(result_msg, user_id, scan_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ ระบบสแกนขัดข้อง: {e}", user_id, scan_msg.message_id)

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
            bot.send_message(user_id, f"❌ ระบบตั้งเตือนราคาขัดข้อง: {e}")

    elif call.data.startswith('addwatch_'):
        symbol = call.data.split('_')[1]
        current_watch = len(get_user_watch(user_id))
        if role == 'free' and current_watch >= 3:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 3 ตัว** โปรดอัปเกรด", parse_mode="Markdown")
            return
        elif role == 'vip' and current_watch >= 10:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 10 ตัว** โปรดอัปเกรดเป็น PRO", parse_mode="Markdown")
            return
        if add_watch(user_id, symbol):
            bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** แล้ว")
        else:
            bot.send_message(user_id, f"⚠️ มี **{symbol}** อยู่แล้ว")
            
    elif call.data.startswith('delwatch_'):
        symbol = call.data.split('_')[1]
        remove_watch_db(user_id, symbol)
        bot.edit_message_text(f"🗑️ ลบ **{symbol}** ออกจาก Watchlist แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)

    elif call.data.startswith('delalert_'):
        alert_id = int(call.data.split('_')[1])
        remove_price_alert_db(user_id, alert_id)
        bot.edit_message_text(f"🗑️ ลบการตั้งเตือน ID {alert_id} แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)
        
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
        elif call.data == 'admin_users_pro':
            handle_users_pro(mock_msg)
        elif call.data == 'admin_backup':
            handle_force_backup(mock_msg)
        elif call.data == 'admin_web_dashboard':
            send_admin_dashboard_link(user_id)
        elif call.data == 'admin_guide_user':
            guide = (
                "📖 **คู่มือจัดการสมาชิก (คัดลอกคำสั่งไปพิมพ์ได้เลย)**\n\n"
                "• `/user_history [ID]` : ส่องคำสั่งล่าสุดของ User\n"
                "• `/addrole [ID] [Role] [Days]` : ปรับระดับ/เพิ่มวันสมาชิก\n"
                "• `/gencode [Days] [Uses] [Role]` : สร้างโค้ดโปรโมชั่น\n"
                "• `/ban [ID]` หรือ `/unban [ID]` : ระงับ/คืนสิทธิ์ผู้ใช้งาน"
            )
            bot.send_message(user_id, guide, parse_mode="Markdown")
            
        elif call.data == 'admin_guide_msg':
            guide = (
                "📣 **คู่มือบรอดแคสต์และข่าวสาร (คัดลอกคำสั่งไปพิมพ์ได้เลย)**\n\n"
                "• `/broadcast [ข้อความที่ต้องการส่ง]` : แจ้งเตือน User ทุกคน\n"
                "• `/force_news flash` : ยิงข่าวด่วนที่สุด 1 ข่าว\n"
                "• `/force_news digest` : ยิงสรุปข่าวย่อ 2 ข่าว\n"
                "• `/mock_alert [whale/dump/xd/golden]` : ทดสอบการแจ้งเตือน\n"
                "• `/earnings [ชื่อหุ้น]` : สั่ง AI วิเคราะห์งบการเงินล่าสุด"
            )
            bot.send_message(user_id, guide, parse_mode="Markdown")

@bot.message_handler(commands=['earnings'])
def handle_earnings(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return

    role = check_subscription(user_id)
    if role not in ('vip', 'pro') and user_id != ADMIN_ID:
        bot.reply_to(message, "🔒 **ฟีเจอร์ระดับพรีเมียม (VIP+)**\nการวิเคราะห์งบการเงินด้วย AI สงวนสิทธิ์เฉพาะสมาชิก VIP และ PRO ครับ\n\n👉 กด **💎 บัญชี / VIP** เพื่ออัปเกรด", parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/earnings [ชื่อหุ้น]`\n(หุ้นไทยเติม .BK ด้วย เช่น `/earnings PTT.BK`)", parse_mode="Markdown")
        return
        
    symbol = args[1].upper()
    load_msg = bot.reply_to(message, f"⏳ กำลังให้ AI แกะงบการเงินล่าสุดของ {symbol}...", parse_mode="Markdown")
    
    try:
        ai_client = gemini_client

        allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
        clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(allowed_suffixes) else symbol
        ticker = yf.Ticker(clean_symbol)
        
        earnings = ticker.earnings_dates
        if earnings is None or earnings.empty:
            bot.edit_message_text(f"❌ ไม่พบข้อมูลการประกาศงบการเงินของ {symbol}", message.chat.id, load_msg.message_id)
            return
            
        latest_earnings = earnings.iloc[0]
        eps_estimate = latest_earnings.get('EPS Estimate', 'N/A')
        eps_actual = latest_earnings.get('Reported EPS', 'N/A')
        surprise = latest_earnings.get('Surprise(%)', 0)
        
        prompt = f"""
        วิเคราะห์งบการเงินล่าสุดของหุ้น {symbol}
        คาดการณ์ EPS: {eps_estimate}
        EPS จริงที่ทำได้: {eps_actual}
        Surprise: {surprise * 100:.2f}%
        
        เขียนสรุปสั้นๆ 3-4 บรรทัดด้วยภาษาเป็นกันเอง ว่างบออกมาดีกว่าหรือแย่กว่าที่คาดการณ์ และส่งผลบวก/ลบกับราคาหุ้นอย่างไร
        """
        
        ai_check = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        summary = ai_check.text.strip()
        
        msg = (
            f"📊 **สรุปงบการเงินฉบับ AI (Earnings Flash)** 📊\n\n"
            f"📌 **หุ้น:** {symbol}\n"
            f"🎯 **กำไรต่อหุ้น (EPS) คาดการณ์:** {eps_estimate}\n"
            f"✅ **กำไรต่อหุ้น (EPS) ทำได้จริง:** {eps_actual}\n"
            f"😲 **เซอร์ไพรส์ตลาด:** {surprise * 100:.2f}%\n\n"
            f"🤖 **มุมมอง Apexify:**\n{summary}"
        )
        bot.edit_message_text(msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาดในการดึงข้อมูลงบการเงิน: {e}", message.chat.id, load_msg.message_id) 

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
            "🇭🇰 หุ้นฮ่องกง: เติม `.HK` เช่น `0700.HK`\n\n"
            "*(พิมพ์แล้วกดส่งมาได้เลยครับ!)*"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
        return
        
    elif text == "📖 คู่มือ /manual":
        handle_manual(message)
        return

    elif text == "📱 เปิดเมนูหลัก":
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

        msg = "📱 **Apexify Hub**\nเลือกฟีเจอร์ที่ต้องการได้เลยครับ:"
        bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        return
        
    elif text in ["💎 สมัคร VIP", "💎 บัญชี / VIP"]:
        profile = get_user_profile(user_id)
        if profile:
            _, expiry, usage, reg_date = profile
            watch_count = len(get_user_watch(user_id))
            
            if role == 'pro': status_text = "👑 PRO (Platinum)"
            elif role == 'vip': status_text = "💎 VIP (Standard)"
            else: status_text = "🆓 Free"
            
            expiry_text = expiry if expiry else "ไม่มีวันหมดอายุ"
            quota_text = f"ไม่จำกัด" if role in ['vip', 'pro'] else f"{usage}/10 ครั้ง"
            reg_text = reg_date[:10] if reg_date else "ไม่ทราบ"
            
            msg = (
                f"👤 **ข้อมูลบัญชี (ID: `{user_id}`)**\n\n"
                f"🏷 **สถานะ:** {status_text}\n"
                f"📅 **วันที่เริ่มใช้งาน:** {reg_text}\n"
                f"📈 **โควต้าวิเคราะห์:** {quota_text}\n"
                f"⏰ **แพ็กเกจหมดอายุ:** {expiry_text}\n"
                f"📋 **หุ้นใน Watchlist:** {watch_count} ตัว\n\n"
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
        
        markup.add(
            InlineKeyboardButton("🛠 เปิด/ปิด Maintenance", callback_data="admin_maintenance"),
            InlineKeyboardButton("💻 สถานะเซิร์ฟเวอร์", callback_data="admin_health")
        )
        markup.add(
            InlineKeyboardButton("📊 สถิติผู้ใช้งาน", callback_data="admin_stats"),
            InlineKeyboardButton("🎯 ผลงานความแม่นยำ", callback_data="admin_perf")
        )
        markup.add(
            InlineKeyboardButton("👑 รายชื่อ PRO/VIP", callback_data="admin_users_pro"),
            InlineKeyboardButton("📦 Backup ฐานข้อมูล", callback_data="admin_backup")
        )
        markup.add(
            InlineKeyboardButton("🌐 เปิด Admin Dashboard", callback_data="admin_web_dashboard")
        )
        markup.add(
            InlineKeyboardButton("📖 คู่มือจัดการสมาชิก & โค้ด", callback_data="admin_guide_user")
        )
        markup.add(
            InlineKeyboardButton("📣 คู่มือบรอดแคสต์ & ข่าว", callback_data="admin_guide_msg")
        )

        admin_text = "👑 **Apexify Admin Master Control**\nเลือกระบบที่คุณต้องการจัดการจากปุ่มด้านล่างได้เลยครับ:"
        bot.reply_to(message, admin_text, parse_mode="Markdown", reply_markup=markup)
        return

    elif text == "🌐 เปิด Dashboard อัตโนมัติ":
        send_dashboard_login_link(user_id)
        return

    symbol = text.upper()
    if len(symbol) > 10:
        bot.reply_to(message, "❓ ไม่เข้าใจคำสั่งนั้น\n\nถ้าต้องการวิเคราะห์หุ้น ลองพิมพ์ชื่อหุ้นสั้นๆ เช่น `AAPL` หรือ `PTT.BK` ครับ", parse_mode="Markdown")
        return

    usage = get_usage(user_id)
    if user_id != ADMIN_ID and role == 'free' and usage >= 10:
        from datetime import datetime as _dt, timedelta as _td
        _now_thai = _dt.utcnow() + _td(hours=7)
        _midnight = _now_thai.replace(hour=0, minute=0, second=0, microsecond=0) + _td(days=1)
        _mins_left = int((_midnight - _now_thai).total_seconds() // 60)
        _h, _m = divmod(_mins_left, 60)
        _reset_str = f"{_h} ชม. {_m} นาที" if _h else f"{_m} นาที"
        bot.reply_to(message, f"🔒 โควต้าฟรีวันนี้หมดแล้ว (10/10)\n\n⏰ รีเซ็ตใหม่ในอีก **{_reset_str}** (เที่ยงคืน)\n\n💎 หรือสมัคร VIP/PRO เพื่อใช้งานไม่จำกัดครับ!", parse_mode="Markdown")
        return

    load_msg = bot.reply_to(message, f"🔍 กำลังวิเคราะห์ **{symbol}** — ใช้เวลา ~10-20 วินาทีครับ", parse_mode="Markdown")
    tech_data, chart, err = _get_cached_analysis(symbol)

    if err:
        bot.edit_message_text(err, message.chat.id, load_msg.message_id, parse_mode="Markdown")
        return

    # 🌟 Wrap AI report generation — กัน Gemini 503/safety crash ทำให้ load_msg ค้าง
    try:
        report = generate_apexify_report(tech_data, role=role)
    except Exception as e:
        print(f"[Analyze] generate_apexify_report failed for {symbol}: {e}", flush=True)
        err_str = str(e).lower()
        if '503' in err_str or 'unavailable' in err_str or 'overloaded' in err_str or 'high demand' in err_str:
            friendly = "⚠️ AI กำลังโหลดหนัก ขอเวลาสักครู่แล้วลองพิมพ์หุ้นส่งมาใหม่นะครับ 🙏"
        elif 'safety' in err_str or 'blocked' in err_str:
            friendly = "⚠️ ระบบความปลอดภัยของ AI ปฏิเสธรอบนี้ ลองหุ้นตัวอื่นหรือลองใหม่ในอีกครู่ครับ"
        else:
            friendly = "⚠️ วิเคราะห์ไม่สำเร็จชั่วคราว ลองพิมพ์หุ้นส่งมาใหม่อีกครั้งครับ"
        bot.edit_message_text(friendly, message.chat.id, load_msg.message_id)
        return

    if user_id != ADMIN_ID and role == 'free':
        increment_usage(user_id)
        report += f"\n\n🎁 **Trial:** {usage + 1}/10"

    correct_symbol = tech_data['symbol']
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"⭐ เพิ่ม {correct_symbol} เข้า Watchlist", callback_data=f"addwatch_{correct_symbol}"))
    markup.add(
        InlineKeyboardButton("💼 ดูพอร์ต", callback_data="hub_portfolio"),
        InlineKeyboardButton("📱 เมนูหลัก", callback_data="hub_home")
    )
    if role == 'pro':
        markup.add(InlineKeyboardButton(f"🔔 ตั้งเตือนราคา {correct_symbol}", callback_data="hub_price_alert"))

    try:
        bot.delete_message(message.chat.id, load_msg.message_id)
    except Exception:
        pass

    # 🌟 chart=None safety — ถ้าวาดกราฟไม่ได้ก็ส่ง report อย่างเดียว
    if chart is None:
        _send_safe(bot, message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
    elif role in ['vip', 'pro']:
        try:
            bot.send_photo(message.chat.id, chart)
        except Exception:
            pass
        _send_safe(bot, message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
    elif len(report) > 1000:
        try:
            bot.send_photo(message.chat.id, chart)
        except Exception:
            pass
        try:
            bot.send_message(message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            bot.send_message(message.chat.id, report, reply_markup=markup)
    else:
        try:
            bot.send_photo(message.chat.id, chart, caption=report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            try:
                chart.seek(0)
                bot.send_photo(message.chat.id, chart)
            except Exception:
                pass
            bot.send_message(message.chat.id, report, reply_markup=markup)

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
        run_alert_loop(bot)

    threading.Thread(target=_bg_init, daemon=True).start()

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
