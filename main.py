from email.mime import message

import telebot
import logging
import json
import PIL.Image
import io
import yfinance as yf
import requests
import random
import string
import time
import xml.etree.ElementTree as ET 
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
MAINTENANCE_MODE = False
from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
import zipfile
import os
from datetime import datetime
# 🌟 Import ฟังก์ชันฐานข้อมูลทั้งหมด (เพิ่ม get_connection แก้ Error)
from database import (get_all_users, init_db, register_user, check_subscription, add_subscription, 
                      get_usage, increment_usage, add_watch, get_user_watch, get_user_profile, 
                      remove_watch_db, add_promo_code, redeem_code, get_user_stats, 
                      check_slip_used, mark_slip_used, ban_user, unban_user, is_user_banned,
                      init_new_features_db, process_referral, get_referral_stats, 
                      add_price_alert_db, get_user_price_alerts_db, remove_price_alert_db,
                      get_connection)
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index
from ai_analyzer import generate_apexify_report, analyze_payment_slip
import psutil
from alert_system import broadcast_hourly_urgent_news, check_and_broadcast_pro_news
from curl_cffi import requests as cffi_requests

telebot.logger.setLevel(logging.DEBUG)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ==========================================
# 🌟 ระบบ Anti-Spam ดักจับคนป่วนรัวข้อความ
# ==========================================
user_message_tracking = {}
user_command_history = {}
spam_alerted = set()

def is_allowed(user_id):
    global MAINTENANCE_MODE
    if user_id == ADMIN_ID: return True 
    if is_user_banned(user_id): return False 
    
    # 🌟 ดักโหมดปิดปรับปรุงระบบ (แอดมินจะรอดผ่าน if user_id == ADMIN_ID ด้านบนมาแล้ว)
    if MAINTENANCE_MODE:
        try:
            bot.send_message(user_id, "🛠 **ระบบกำลังปิดปรับปรุง (Maintenance Mode)**\n\nทีมงาน Apexify กำลังอัปเกรดระบบให้ดียิ่งขึ้น กรุณารอสักครู่ครับ... 🚀", parse_mode="Markdown")
        except:
            pass
        return False
        
    now = time.time()
    if user_id not in user_message_tracking:
        user_message_tracking[user_id] = []
        
    user_message_tracking[user_id] = [t for t in user_message_tracking[user_id] if now - t < 10]
    user_message_tracking[user_id].append(now)
    
    if len(user_message_tracking[user_id]) > 5:
        if user_id not in spam_alerted:
            bot.send_message(ADMIN_ID, f"🚨 **แจ้งเตือนสแปม:** User `{user_id}` พยายามส่งข้อความรัวๆ ระบบระงับชั่วคราว\n👉 พิมพ์ `/ban {user_id}` เพื่อแบน", parse_mode="Markdown")
            spam_alerted.add(user_id)
        return False
        
    if len(user_message_tracking[user_id]) <= 5 and user_id in spam_alerted:
        spam_alerted.remove(user_id)
        
    return True

# 🌟 เพิ่ม def สำหรับคำสั่ง /maintenance ไว้ในกลุ่ม @bot.message_handler(commands=...)
@bot.message_handler(commands=['maintenance'])
def handle_maintenance(message):
    if str(message.chat.id) != ADMIN_ID: return
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    status = "🔴 เปิด (ผู้ใช้ทั่วไปใช้งานไม่ได้, แอดมินใช้ได้ปกติ)" if MAINTENANCE_MODE else "🟢 ปิด (ระบบเปิดใช้งานปกติทุกคน)"
    bot.reply_to(message, f"🛠 **สถานะ Maintenance Mode:** {status}", parse_mode="Markdown")
@bot.message_handler(commands=['force_backup'])
def handle_force_backup(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    load_msg = bot.reply_to(message, "⏳ กำลังบีบอัดฐานข้อมูล `apexify.db` โปรดรอสักครู่...", parse_mode="Markdown")
    
    try:
        db_filename = "apexify.db"
        if not os.path.exists(db_filename):
            bot.edit_message_text("❌ ไม่พบไฟล์ฐานข้อมูล (ระบบอาจจะเชื่อมต่อกับ Cloud Database อยู่)", message.chat.id, load_msg.message_id)
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"apexify_backup_{timestamp}.zip"
        
        # สร้างไฟล์ Zip (บีบอัดไฟล์ db ให้เล็กลง)
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(db_filename)
        
        # ส่งไฟล์เข้าแชทแอดมิน
        with open(zip_filename, 'rb') as doc:
            bot.send_document(message.chat.id, doc, caption=f"📦 **Backup ฐานข้อมูลสำเร็จ!**\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # ลบไฟล์ zip ทิ้งหลังจากส่งเสร็จเพื่อไม่ให้รกพื้นที่เซิร์ฟเวอร์
        os.remove(zip_filename)
        bot.delete_message(message.chat.id, load_msg.message_id)
        
    except Exception as e:
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาดในการ Backup: {e}", message.chat.id, load_msg.message_id)
@bot.message_handler(commands=['system_health'])
def handle_system_health(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    load_msg = bot.reply_to(message, "⏳ กำลังดึงข้อมูลสถานะเซิร์ฟเวอร์...")
    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_total = ram.total / (1024**3)
        ram_used = ram.used / (1024**3)
        ram_percent = ram.percent
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        
        uptime = time.time() - psutil.boot_time()
        uptime_hours = uptime // 3600
        
        msg = (
            "💻 **สถานะเซิร์ฟเวอร์ (System Health)** 💻\n\n"
            f"🧠 **CPU Usage:** {cpu_usage}%\n"
            f"💽 **RAM Usage:** {ram_used:.2f} GB / {ram_total:.2f} GB ({ram_percent}%)\n"
            f"💾 **Disk Space:** {disk_percent}% ใช้ไป\n"
            f"⏱ **Server Uptime:** {int(uptime_hours)} ชั่วโมง\n\n"
            f"✅ ระบบทำงานปกติ ลื่นไหลไม่มีสะดุดครับ!"
        )
        bot.edit_message_text(msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ ไม่สามารถดึงข้อมูลระบบได้: {e}\n(คำแนะนำ: ต้องรัน `pip install psutil` บนเซิร์ฟเวอร์ด้วยครับ)", message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['users_pro'])
def handle_users_pro(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    load_msg = bot.reply_to(message, "⏳ กำลังดึงรายชื่อลูกค้า PRO และ VIP...")
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, role, expiry_date FROM users WHERE role IN ('pro', 'vip') ORDER BY role DESC, expiry_date ASC")
        users_list = cur.fetchall()
        cur.close()
        conn.close()
        
        if not users_list:
            bot.edit_message_text("❌ ยังไม่มีลูกค้า VIP หรือ PRO ในระบบ", message.chat.id, load_msg.message_id)
            return
            
        report = "👑 **รายชื่อลูกค้า VIP / PRO ทั้งหมด** 👑\n\n"
        count = 1
        for uid, role, expiry in users_list:
            role_icon = "👑" if role == 'pro' else "💎"
            is_active = check_subscription(uid)
            status_icon = "✅" if is_active in ['pro', 'vip'] else "❌ (หมดอายุ)"
            
            report += f"{count}. {role_icon} `{uid}` | หมดอายุ: {expiry[:10]} {status_icon}\n"
            count += 1
            
            # ป้องกันข้อความยาวเกินลิมิตของ Telegram (ประมาณ 4000 ตัวอักษร)
            if len(report) > 3500:
                report += "\n... (ยังมีต่อ แต่ข้อความยาวเกินไป)"
                break
                
        bot.edit_message_text(report, message.chat.id, load_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ เกิดข้อผิดพลาด: {e}", message.chat.id, load_msg.message_id)

@bot.message_handler(commands=['force_news'])
def handle_force_news(message):
    if str(message.chat.id) != ADMIN_ID: return
    
    args = message.text.split()
    news_type = args[1].lower() if len(args) > 1 else 'flash'
    
    load_msg = bot.reply_to(message, f"🚨 กำลังสั่งให้ AI ดึงข่าวด่วนแบบ `{news_type.upper()}` และบรอดแคสต์ทันที...")
    try:
        if news_type == 'flash':
            broadcast_hourly_urgent_news(bot)
            bot.edit_message_text("✅ บรอดแคสต์ Flash News ข่าวเดียวเด่นๆ สำเร็จ!", message.chat.id, load_msg.message_id)
        elif news_type == 'digest':
            check_and_broadcast_pro_news(bot)
            bot.edit_message_text("✅ บรอดแคสต์ Digest News (แบบ 3 ข่าว) สำเร็จ!", message.chat.id, load_msg.message_id)
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
        bot.reply_to(message, f"❌ เกิดข้อผิดพลาด: {e}")        
def generate_random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ==========================================
# 🌟 ระบบ Start & Referral
# ==========================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('REF_'):
        referrer_id = args[1].replace('REF_', '')
        if referrer_id != user_id:
            try:
                if process_referral(referrer_id, user_id):
                    bot.send_message(referrer_id, "🎉 **ยินดีด้วย!** มีเพื่อนสมัครใช้งานผ่านลิงก์ของคุณ\nคุณได้รับโบนัสการใช้งานเรียบร้อยแล้ว! 🎁", parse_mode="Markdown")
            except Exception as e:
                print(f"Referral logic error: {e}")
    
    register_user(user_id)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 วิเคราะห์หุ้น"), KeyboardButton("📱 เปิดเมนูหลัก"))
    markup.add(KeyboardButton("💎 บัญชี / VIP"))
    
    if user_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 แผงควบคุมแอดมิน"))
    
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "พิมพ์ชื่อหุ้นที่ต้องการวิเคราะห์ส่งมาได้เลยครับ:\n"
        "🇺🇸 หุ้นต่างประเทศ: `AAPL`, `TSLA`, `NVDA`\n"
        "🇹🇭 หุ้นไทย (ต้องมี .BK): `PTT.BK`, `AOT.BK`\n\n"
        "👇 *กดปุ่มด้านล่างเพื่อเลือกใช้งานฟีเจอร์ต่างๆ*"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

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
            bot.reply_to(message, "❌ รูปแบบผิด!\n**วิธีใช้:** `/setalert [ชื่อหุ้น] [ราคาที่ต้องการ]`\nเช่น: `/setalert PTT.BK 35`", parse_mode="Markdown")
            return
            
        symbol = args[1].upper()
        target_price = float(args[2])
        
        load_msg = bot.reply_to(message, f"⏳ กำลังตรวจสอบราคาปัจจุบันของ {symbol}...")
        tech_data, _, err = calculate_technical_indicators(symbol, generate_chart=False)
        
        if err or not tech_data:
            bot.edit_message_text(f"❌ ไม่พบข้อมูลหุ้น **{symbol}**\n\n💡 **คำแนะนำ:**\nหากเป็นหุ้นไทย กรุณาเติม `.BK` ต่อท้ายด้วยครับ เช่น `PTT.BK`, `KBANK.BK`", message.chat.id, load_msg.message_id, parse_mode="Markdown")
            return
            
        current_price = tech_data['price']
        
        condition = 'above' if target_price > current_price else 'below'
        cond_text = "ขึ้นไปแตะ" if condition == 'above' else "ร่วงลงมาแตะ"
        
        add_price_alert_db(user_id, symbol, target_price, condition)
        
        success_msg = (
            f"✅ **ตั้งเตือนสำเร็จ!** 🔔\n\n"
            f"📌 หุ้น: **{symbol}**\n"
            f"💵 ราคาปัจจุบัน: {current_price:,.2f}\n"
            f"🎯 ระบบจะแจ้งเตือนเมื่อราคา **{cond_text} {target_price:,.2f}**\n\n"
            f"*(ระบบจะคอยเฝ้ากราฟและอัปเดตราคาให้ทุกๆ 5 นาทีตลอด 24 ชม.)*"
        )
        bot.edit_message_text(success_msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ ราคาต้องเป็นตัวเลขเท่านั้นครับ เช่น 35 หรือ 35.50")
    except Exception as e:
        bot.reply_to(message, f"❌ เกิดข้อผิดพลาด: {e}")

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
    try:
        target_user = message.text.split()[1]
        ban_user(target_user)
        bot.reply_to(message, f"🚫 **แบนสำเร็จ:** เตะ User `{target_user}` ออกจากระบบถาวรแล้ว!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/ban [รหัสผู้ใช้]`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def handle_unban(message):
    if str(message.chat.id) != ADMIN_ID: return
    try:
        target_user = message.text.split()[1]
        unban_user(target_user)
        bot.reply_to(message, f"✅ **ปลดแบนสำเร็จ:** ให้โอกาส User `{target_user}` กลับมาใช้งานได้แล้ว", parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/unban [รหัสผู้ใช้]`", parse_mode="Markdown")

@bot.message_handler(commands=['gencode'])
def handle_gencode(message):
    if str(message.chat.id) != ADMIN_ID: return
    try:
        args = message.text.split()
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
        except:
            bot.reply_to(message, "❌ รูปแบบ: /addrole [user_id] [vip/pro] [days]")

@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID: return
    msg_text = message.text.replace('/broadcast', '').strip()
    if not msg_text: return
    users = get_all_users()
    success, fail = 0, 0
    bot.reply_to(message, f"⏳ กำลังส่งข้อความหาผู้ใช้ {len(users)} คน...")
    for uid in users:
        try:
            # ลองส่งแบบจัดหน้าตา (Markdown) ก่อน
            bot.send_message(uid, f"📢 **ประกาศจาก Apexify:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.1) # หน่วงเวลากัน Telegram แบน
        except Exception:
            try:
                # ถ้าพังเพราะแอดมินส่งลิงก์หรือสัญลักษณ์แปลกๆ ให้ส่งแบบธรรมดาแทน (ไม้ตาย)
                bot.send_message(uid, f"📢 ประกาศจาก Apexify:\n\n{msg_text}")
                success += 1
                time.sleep(0.1)
            except Exception:
                fail += 1 
    bot.reply_to(message, f"✅ บรอดแคสต์สำเร็จ: {success} คน\n❌ ล้มเหลว: {fail} คน")

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    if str(message.chat.id) != ADMIN_ID: return
    try:
        stats, total = get_user_stats()
        est_revenue = (stats.get('vip', 0) * 199) + (stats.get('pro', 0) * 499)
        msg = (
            "📊 **สถิติการใช้งาน Apexify** 📊\n\n"
            f"👥 **ผู้ใช้งานทั้งหมด:** {total} คน\n"
            f"🆓 **สายฟรี:** {stats.get('free', 0)} คน\n"
            f"💎 **ระดับ VIP:** {stats.get('vip', 0)} คน\n"
            f"👑 **ระดับ PRO:** {stats.get('pro', 0)} คน\n\n"
            f"💰 **ประมาณการรายได้ขั้นต่ำ:** {est_revenue:,.2f} บาท/เดือน"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ เกิดข้อผิดพลาด: {e}")

@bot.message_handler(commands=['performance'])
def handle_performance(message):
    if str(message.chat.id) != ADMIN_ID: return
    status_msg = bot.reply_to(message, "⏳ กำลังดึงประวัติและคำนวณผลกำไร/ขาดทุน...")
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT symbol, alert_type, price_at_alert, timestamp FROM alert_logs ORDER BY id DESC LIMIT 15")
        logs = c.fetchall()
        conn.close()

        if not logs:
            bot.edit_message_text("❌ ยังไม่มีประวัติการแจ้งเตือนในระบบครับ", message.chat.id, status_msg.message_id)
            return

        report_text = "🎯 **สรุปผลงานความแม่นยำ Apexify (ล่าสุด)** 🎯\n\n"
        win_count, total_count = 0, 0

        for row in logs:
            symbol, alert_type, start_price, timestamp = row
            try:
            
                # 🌟 อัปเดตให้รองรับตลาดหุ้นทั่วโลก
                allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
                clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(allowed_suffixes) else symbol
                ticker = yf.Ticker(clean_symbol)
                hist = ticker.history(period="1d")
                if hist.empty: continue
                
                current_price = float(hist['Close'].iloc[-1])
                diff_pct = ((current_price - start_price) / start_price) * 100
                
                is_win = False
                if any(x in alert_type.upper() for x in ["OVERSOLD", "GOLDEN_CROSS", "BREAK_RES"]):
                    if diff_pct > 0: is_win = True
                elif any(x in alert_type.upper() for x in ["OVERBOUGHT", "DEATH_CROSS", "BREAK_SUP"]):
                    if diff_pct < 0: is_win = True
                    diff_pct = -diff_pct 
                    
                if is_win: win_count += 1
                total_count += 1
                
                emoji = "✅" if is_win else "❌"
                short_type = alert_type.replace('_', ' ')
                report_text += f"{emoji} **{symbol}** ({short_type})\n   เตือน: {start_price:.2f} ➡️ ปัจจุบัน: {current_price:.2f} ({diff_pct:+.2f}%)\n\n"
            except Exception: continue
        
        if total_count > 0:
            win_rate = (win_count / total_count) * 100
            report_text += f"🏆 **อัตราชนะรวม (Win Rate):** {win_rate:.2f}% ({win_count}/{total_count})"
        bot.edit_message_text(report_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

@bot.message_handler(content_types=['photo'])
def handle_payment_slip_check(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    role = check_subscription(user_id)
    progress_msg = bot.reply_to(message, "🧾 Apexify กำลังตรวจสอบสลิปโอนเงิน...")
        
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ai_result = analyze_payment_slip(downloaded_file)
        result = json.loads(ai_result.replace('```json', '').replace('```', ''))
        
        if result.get('is_slip'):
            amount = float(result.get('amount', 0))
            ref_no = result.get('ref_no', '').strip()
            
            if not ref_no or ref_no == "" or ref_no.lower() == "none":
                bot.edit_message_text("⚠️ Apexify อ่าน 'เลขที่อ้างอิง' บนสลิปไม่ชัดเจน โปรดถ่ายให้เห็นชัดๆ ครับ", message.chat.id, progress_msg.message_id)
                return
            if check_slip_used(ref_no):
                bot.edit_message_text("❌ **สลิปนี้ถูกใช้งานไปแล้ว!**\nไม่อนุญาตให้ใช้สลิปซ้ำครับ", message.chat.id, progress_msg.message_id, parse_mode="Markdown")
                bot.send_message(ADMIN_ID, f"🚨 **ทุจริต!** User `{user_id}` ส่งสลิปซ้ำ (Ref: `{ref_no}`)", parse_mode="Markdown")
                return

            if amount == 4990:
                expiry = add_subscription(user_id, 'pro', 365)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายปี)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 1990:
                expiry = add_subscription(user_id, 'vip', 365)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายปี)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 499:
                expiry = add_subscription(user_id, 'pro', 30)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **👑 PRO (รายเดือน)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 199:
                expiry = add_subscription(user_id, 'vip', 30)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** ได้รับสิทธิ์ **💎 VIP (รายเดือน)**\n⏰ หมดอายุ: {expiry}"
            else:
                bot.edit_message_text(
                    f"❌ **ยอดเงินไม่ตรงกับแพ็กเกจ** ({amount:,.2f} บาท)\nกรุณาโอนให้ตรงราคา (199, 499, 1990, 4990)", 
                    message.chat.id, progress_msg.message_id, parse_mode="Markdown"
                )
                bot.send_message(ADMIN_ID, f"⚠️ **ยอดผิดปกติ!** User `{user_id}` โอน {amount:,.2f} บาท", parse_mode="Markdown")
                return

            mark_slip_used(ref_no, user_id)
            bot.delete_message(message.chat.id, progress_msg.message_id)
            bot.reply_to(message, msg_text, parse_mode="Markdown")
            bot.send_message(ADMIN_ID, f"💰 เงินเข้า! User `{user_id}` โอน {amount} บาท")
        else:
            bot.edit_message_text("❌ รูปนี้ไม่ใช่สลิปโอนเงินที่ถูกต้องครับ", message.chat.id, progress_msg.message_id)
    except Exception as e:
        bot.edit_message_text("⚠️ Apexify ไม่สามารถอ่านสลิปได้ โปรดถ่ายให้ชัดเจนอีกครั้ง", message.chat.id, progress_msg.message_id)

# ==========================================
# 🌟 ระบบปุ่มกด Inline
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_') or call.data.startswith('menu_') or call.data.startswith('hub_') or call.data.startswith('admin_'))
def inline_callbacks(call):
    user_id = str(call.message.chat.id)
    if not is_allowed(user_id): return
    role = check_subscription(user_id)
    bot.answer_callback_query(call.id)
    
    if call.data == 'menu_vip':
        try:
            pay_text = (
                "🚀 **แพ็กเกจการลงทุนกับ Apexify** 🚀\n"
                "💳 กสิกรไทย: `135-1-34469-1` (นาย เกียรติศักดิ์ วุฒิจันทร์)\n\n"
                
                "🆓 **1. ระดับ Free Trial (สายฟรี):**\n"
                "• โควต้าวิเคราะห์กราฟ 10 ครั้ง\n"
                "• สร้าง Watchlist สูงสุด 3 ตัว\n\n"
                
                "💎 **2. ระดับ VIP (199.-/เดือน หรือ 1,990.-/ปี):**\n"
                "• โควต้าวิเคราะห์กราฟ **ไม่จำกัด!**\n"
                "• สร้าง Watchlist **สูงสุด 10 ตัว**\n"
                "• สแกนหุ้นใน Watchlist รวดเดียวจบ\n"
                "• Apexify ฟันธงจุดเข้าซื้อ/ขายละเอียด\n\n"
                
                "👑 **3. ระดับ PRO (499.-/เดือน หรือ 4,990.-/ปี) [แนะนำ!]:**\n"
                "• **[NEW] 🔥 Apexify สแกนหุ้นเด่น (Screener)** คัดตัวเข้าตามาให้ทุกวัน\n"
                "• **[NEW] 🌅 Morning Briefing** สรุปทิศทางตลาดส่งให้ทุกเช้า\n"
                "• **[NEW] 📅 แจ้งเตือนปันผล (XD)** ล่วงหน้า 3 วัน\n"
                "• 🔔 ตั้งเตือนราคาส่วนตัว (Custom Price Alerts)\n"
                "• 📰 แจ้งเตือนข่าวด่วนโลก/ไทย (แปลไทยอัตโนมัติ)\n"
                "• 📈 แจ้งเตือนสัญญาณกราฟ (Golden Cross, RSI) 24 ชม.\n"
                "• สร้าง Watchlist **ไม่จำกัดจำนวน!**\n\n"
                
                "✅ *โอนเงินแล้วส่งรูปสลิปในแชทนี้ ระบบจะอัปเกรดให้อัตโนมัติครับ!*"
            )
            bot.send_message(user_id, pay_text, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(user_id, f"❌ เกิดข้อผิดพลาดในการโหลดเมนู VIP: {e}")
            
    elif call.data == 'menu_code':
        bot.send_message(user_id, "🎟 **พิมพ์คำสั่ง:** `/redeem [โค้ดของคุณ]`", parse_mode="Markdown")
        
    elif call.data == 'menu_referral':
        try:
            ref_count = get_referral_stats(user_id)
            bot_info = bot.get_me()
            bot_username = bot_info.username
            ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
            msg = (
                "🤝 **ชวนเพื่อนรับฟรี VIP/โควต้า!** 🤝\n\n"
                "คัดลอกลิงก์ด้านล่างนี้ส่งให้เพื่อน หากเพื่อนสมัครใช้งานผ่านลิงก์ของคุณสำเร็จ รับรางวัลทันที:\n\n"
                "🆓 สายฟรีชวนเพื่อน: **รับโควต้าวิเคราะห์เพิ่ม 3 ครั้ง/คน**\n"
                "👑 VIP/PRO ชวนเพื่อน: **รับวันใช้งานเพิ่ม 1 วัน/คน**\n\n"
                f"🔗 **ลิงก์ของคุณ:**\n`{ref_link}`\n\n"
                f"📊 **สถิติของคุณ:** ชวนสำเร็จ {ref_count} คน"
            )
            bot.send_message(user_id, msg, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(user_id, f"❌ ระบบชวนเพื่อนขัดข้อง (ฐานข้อมูลอาจยังไม่อัปเดต)\nแจ้งเตือน: {e}")
            
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
            
    # 🌟 อัปเดตเมนูข่าวสารให้ครอบคลุมและดึงเฉพาะ 24 ชม.
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
                except: pass
                
            titles_str = "\n".join([f"- {t}" for t in all_titles[:15]])
            
            from google import genai
            from config import GEMINI_API_KEY
            ai_client = genai.Client(api_key=GEMINI_API_KEY)
            
            # 🌟 บังคับ AI สรุป 3-4 บรรทัดและห้ามมีลิงก์
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
                bot.send_message(user_id, "📋 Watchlist ว่างเปล่า พิมพ์ชื่อหุ้นแล้วกด ⭐ ใต้กราฟครับ")
                return
            markup = InlineKeyboardMarkup()
            for symbol in my_list:
                markup.add(InlineKeyboardButton(f"❌ ลบ {symbol}", callback_data=f"delwatch_{symbol}"))
            bot.send_message(user_id, "📋 **จัดการ Watchlist ของคุณ:**", parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            bot.send_message(user_id, f"❌ Error: {e}")
        
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
                except Exception: pass
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
            msg = "🔔 **จัดการตั้งเตือนราคาส่วนตัว**\n\n"
            if not alerts:
                msg += "คุณยังไม่มีการตั้งเตือนราคา\n\n"
            else:
                msg += "รายการที่กำลังเฝ้าดู:\n"
                for alert in alerts:
                    a_id, sym, price, cond = alert
                    cond_text = "ทะลุขึ้น" if cond == 'above' else "ร่วงลง"
                    msg += f"• **ID {a_id}:** {sym} ({cond_text} {price:,.2f})\n"
                msg += "\n"
            
            msg += (
                "👉 **วิธีตั้งเตือนใหม่ (พิมพ์ในช่องแชท):**\n"
                "`/setalert [ชื่อหุ้น] [ราคา]`\n*(เช่น /setalert PTT.BK 35)*\n\n"
                "👉 **วิธียกเลิก:**\n`/delalert [ID]`\n*(เช่น /delalert 1)*"
            )
            bot.send_message(user_id, msg, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(user_id, f"❌ ระบบตั้งเตือนราคาขัดข้อง (ฐานข้อมูลอาจยังไม่อัปเดต)\nแจ้งเตือน: {e}")

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
        bot.edit_message_text(f"🗑️ ลบ **{symbol}** แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)
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
        elif call.data == 'admin_quiz':
            handle_quiz(mock_msg)
            
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
                "• `/force_news digest` : ยิงสรุปข่าวเจาะลึก 3 ข่าว\n"
                "• `/mock_alert [whale/dump/xd/golden]` : ทดสอบการแจ้งเตือน\n"
                "• `/earnings [ชื่อหุ้น]` : สั่ง AI วิเคราะห์งบการเงินล่าสุด"
            )
            bot.send_message(user_id, guide, parse_mode="Markdown")
@bot.message_handler(commands=['earnings'])
def handle_earnings(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    args = message.text.split()
    if len(args) != 2:
        bot.reply_to(message, "❌ รูปแบบผิด! พิมพ์: `/earnings [ชื่อหุ้น]`\n(หุ้นไทยเติม .BK ด้วย เช่น `/earnings PTT.BK`)", parse_mode="Markdown")
        return
        
    symbol = args[1].upper()
    load_msg = bot.reply_to(message, f"⏳ กำลังให้ AI แกะงบการเงินล่าสุดของ {symbol}...", parse_mode="Markdown")
    
    try:
        from google import genai
        from config import GEMINI_API_KEY
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        # 🌟 อัปเดตให้รองรับตลาดหุ้นทั่วโลก
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
# 🌟 ตัวแปรเก็บสถานะการตอบควิซ
quiz_data = {
    "question": "ถ้าเกิดสัญญาณ 'Golden Cross' (EMA50 ตัดขึ้นเหนือ EMA200) บ่งบอกถึงสภาวะตลาดแบบใด?",
    "options": ["ตลาดกำลังเข้าสู่ขาลงระยะยาว", "ตลาดกำลังเข้าสู่ขาขึ้นระยะยาว", "ตลาดจะไซด์เวย์ไม่ไปไหน"],
    "answer": 1
}
users_played_quiz = set()

@bot.message_handler(commands=['quiz'])
def handle_quiz(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    if user_id in users_played_quiz:
        bot.reply_to(message, "⏳ วันนี้คุณร่วมสนุกกับควิซไปแล้วครับ พรุ่งนี้มาทายกันใหม่นะ!")
        return
        
    markup = InlineKeyboardMarkup(row_width=1)
    for i, opt in enumerate(quiz_data["options"]):
        markup.add(InlineKeyboardButton(opt, callback_data=f"quiz_{i}"))
        
    msg = (
        "🎮 **Daily Trading Quiz (ทายใจตลาด)** 🎮\n\n"
        f"❓ **คำถามวันนี้:**\n{quiz_data['question']}\n\n"
        "*(ลองตอบดูนะครับ ตอบผิดไม่เป็นไร ถือว่าได้ความรู้ไปใช้เทรดจริง!)*"
    )
    bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def quiz_callback(call):
    user_id = str(call.message.chat.id)
    bot.answer_callback_query(call.id)
    
    if user_id in users_played_quiz:
        bot.send_message(user_id, "⏳ คุณตอบคำถามของวันนี้ไปแล้วครับ รอเล่นคำถามใหม่พรุ่งนี้นะ!")
        return
        
    users_played_quiz.add(user_id)
    
    chosen_idx = int(call.data.split('_')[1])
    correct_idx = quiz_data["answer"]
    
    if chosen_idx == correct_idx:
        bot.edit_message_text(
            f"✅ **ถูกต้องครับ! เก่งมาก!** 🎉\n\nคำถาม: {quiz_data['question']}\nคำตอบ: {quiz_data['options'][correct_idx]}",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown"
        )
    else:
        bot.edit_message_text(
            f"❌ **ยังไม่ถูกน้าา** 😅\n\nคำถาม: {quiz_data['question']}\nคำตอบที่ถูกคือ: **{quiz_data['options'][correct_idx]}**\n\nไม่เป็นไรครับ เก็บความรู้ไว้ใช้เทรด พรุ่งนี้มาลุยกันใหม่!",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown"
        )          
# ==========================================
# 🌟 ตัวรับข้อความหลัก (Main Handler)
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    text = message.text.strip()
    role = check_subscription(user_id)
    
    # 🌟 [เพิ่มใหม่] แอบเก็บประวัติการพิมพ์ 50 ข้อความล่าสุดไว้ใน RAM เซิร์ฟเวอร์
    global user_command_history
    if user_id not in user_command_history:
        user_command_history[user_id] = []
    user_command_history[user_id].append(text)
    if len(user_command_history[user_id]) > 50: 
        user_command_history[user_id].pop(0) # ลบอันเก่าสุดทิ้ง

    if text == "📊 วิเคราะห์หุ้น":
        bot.reply_to(message, "ส่งชื่อหุ้นมาได้เลยครับ (หุ้นไทยอย่าลืมใส่ .BK ต่อท้ายนะ)")
        return
        
    elif text == "📱 เปิดเมนูหลัก":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🌍 สภาวะตลาดโลก", callback_data="hub_market"),
            InlineKeyboardButton("📰 ข่าวด่วนลงทุน", callback_data="hub_news")
        )
        markup.add(
            InlineKeyboardButton("📋 จัดการ Watchlist", callback_data="hub_watchlist"),
            InlineKeyboardButton("🚀 สแกนหุ้น (VIP)", callback_data="hub_scan")
        )
        markup.add(
            InlineKeyboardButton("🔔 ตั้งเตือนราคา (PRO)", callback_data="hub_price_alert"),
            InlineKeyboardButton("🔥 หุ้นเด่น (PRO)", callback_data="hub_screener")
        )
        
        msg = "📱 **Apexify Hub (เมนูหลัก)**\nเลือกฟีเจอร์ที่คุณต้องการใช้งานได้เลยครับ:"
        bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        return
        
    elif text in ["💎 สมัคร VIP", "💎 บัญชี / VIP"]:
        profile = get_user_profile(user_id)
        if profile:
            _, expiry, usage, reg_date = profile
            watch_count = len(get_user_watch(user_id))
            
            if role == 'pro': status_text = "👑 PRO (Platinum)"
            elif role == 'vip': status_text = "💎 VIP (Standard)"
            else: status_text = "🆓 Free Trial"
            
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
            markup.add(InlineKeyboardButton("🤝 ชวนเพื่อนรับ VIP ฟรี", callback_data="menu_referral"))
            bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.reply_to(message, "❌ ไม่พบข้อมูลบัญชี พิมพ์ /start เพื่อลงทะเบียนใหม่")
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
            InlineKeyboardButton("🎮 เล่น Daily Quiz", callback_data="admin_quiz")
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

    symbol = text.upper()
    if len(symbol) > 10: return

    usage = get_usage(user_id)
    if user_id != ADMIN_ID and role == 'free' and usage >= 10:
        bot.reply_to(message, "🔒 โควต้าฟรีหมดแล้ว กดเข้าเมนู [💎 บัญชี / VIP] เพื่อสมัครใช้งานต่อครับ!")
        return

    load_msg = bot.reply_to(message, f"🔍 กำลังวิเคราะห์ {symbol}...")
    tech_data, chart, err = calculate_technical_indicators(symbol)
    
    if err:
        bot.edit_message_text(err, message.chat.id, load_msg.message_id)
        return

    report = generate_apexify_report(tech_data, role=role)
    
    if user_id != ADMIN_ID and role == 'free':
        increment_usage(user_id)
        report += f"\n\n🎁 **Trial:** {usage + 1}/10"
    else:
        report += f"\n\n💎 **{role.upper()} Member**"

    correct_symbol = tech_data['symbol']
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"⭐ เพิ่ม {correct_symbol} เข้า Watchlist", callback_data=f"addwatch_{correct_symbol}"))

    bot.delete_message(message.chat.id, load_msg.message_id)
    
    if len(report) > 1000:
        bot.send_photo(message.chat.id, chart)
        try:
            bot.send_message(message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            bot.send_message(message.chat.id, report, reply_markup=markup)
    else:
        try:
            bot.send_photo(message.chat.id, chart, caption=report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            chart.seek(0) 
            bot.send_photo(message.chat.id, chart)
            bot.send_message(message.chat.id, report, reply_markup=markup)

if __name__ == "__main__":
    init_db()
    try:
        init_new_features_db()
    except Exception as e:
        print("DB Init Error:", e)
        
    keep_alive()
    bot.infinity_polling()
