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

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID

# 🌟 Import ฟังก์ชันฐานข้อมูลทั้งหมด
from database import (get_all_users, init_db, register_user, check_subscription, add_subscription, 
                      get_usage, increment_usage, add_watch, get_user_watch, get_user_profile, 
                      remove_watch_db, add_promo_code, redeem_code, get_user_stats, 
                      check_slip_used, mark_slip_used, ban_user, unban_user, is_user_banned,
                      init_new_features_db, process_referral, get_referral_stats, 
                      add_price_alert_db, get_user_price_alerts_db, remove_price_alert_db,get_connection)
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index
from ai_analyzer import generate_apexify_report, analyze_payment_slip

from curl_cffi import requests as cffi_requests

telebot.logger.setLevel(logging.DEBUG)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ==========================================
# 🌟 ระบบ Anti-Spam ดักจับคนป่วนรัวข้อความ
# ==========================================
user_message_tracking = {}
spam_alerted = set()

def is_allowed(user_id):
    if user_id == ADMIN_ID: return True 
    if is_user_banned(user_id): return False 
        
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
            bot.send_message(uid, f"📢 **ประกาศจาก Apexify:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
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
                clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(".BK") else symbol
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
# 🌟 ระบบปุ่มกด Inline (เพิ่ม Apexify Screener และอัปเดตคำอธิบาย VIP/PRO)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_') or call.data.startswith('menu_') or call.data.startswith('hub_'))
def inline_callbacks(call):
    user_id = str(call.message.chat.id)
    if not is_allowed(user_id): return
    role = check_subscription(user_id)
    bot.answer_callback_query(call.id)
    
    # 🌟 เมนูอธิบายแพ็กเกจ (ปรับคำอธิบายให้ลูกค้าอยากจ่าย 499.- มากที่สุด)
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
            
    # 🌟 เมนู The Hub
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
            load_msg = bot.send_message(user_id, "📰 กำลังรวบรวมข่าวด่วน...")
            url_th = "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+การลงทุน&hl=th&gl=TH&ceid=TH:th"
            res_th = cffi_requests.get(url_th, impersonate="chrome110", timeout=15)
            root_th = ET.fromstring(res_th.content)
            items_th = root_th.findall('.//item')[:3]

            url_en = "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+investing&hl=en-US&gl=US&ceid=US:en"
            res_en = cffi_requests.get(url_en, impersonate="chrome110", timeout=15)
            root_en = ET.fromstring(res_en.content)
            items_en = root_en.findall('.//item')[:3]
            
            news_text = "🌐 **สรุปข่าวด่วนตลาดลงทุน** 🌐\n\n🇹🇭 **ไทย:**\n"
            emojis_th = ["🔥", "📌", "📢"]
            for i, item in enumerate(items_th):
                title = item.find('title').text
                link = item.find('link').text
                news_text += f"{emojis_th[i]} [{title}]({link})\n\n"

            news_text += "🌍 **ต่างประเทศ:**\n"
            emojis_en = ["💵", "🚀", "📈"]
            for i, item in enumerate(items_en):
                title = item.find('title').text
                link = item.find('link').text
                news_text += f"{emojis_en[i]} [{title}]({link})\n\n"
                
            bot.edit_message_text(news_text, user_id, load_msg.message_id, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            bot.edit_message_text(f"❌ ดึงข้อมูลข่าวล้มเหลว", user_id, load_msg.message_id)
            
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

    # 🌟 ฟีเจอร์ใหม่: Apexify Auto-Screener (PRO Exclusive)
    elif call.data == 'hub_screener':
        try:
            if role != 'pro' and user_id != ADMIN_ID:
                bot.send_message(user_id, "🔒 **ฟีเจอร์ระดับพรีเมียม (PRO Exclusive)**\nสแกนหุ้นเด่นอัตโนมัติสงวนสิทธิ์ให้ลูกค้าระดับ PRO เท่านั้นครับ 👑", parse_mode="Markdown")
                return
            
            scan_msg = bot.send_message(user_id, "⏳ **Apexify กำลังสแกนหาหุ้นเด่น...**\n*(ค้นหาจากกลุ่ม SET50 และ US Tech ที่เพิ่งเกิด Golden Cross หรือ RSI ตกเข้าโซน Oversold)*")
            
            # ลิสต์หุ้นยอดฮิตเพื่อให้สแกนได้เร็ว (กัน Timeout)
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
                    
                    # เงื่อนไขคัดหุ้นเด่น: เพิ่งตัดขึ้น หรือเข้าเขตขายมากเกินไป
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
# 🌟 ตัวรับข้อความหลัก (Main Handler)
# ==========================================
@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    text = message.text.strip()
    role = check_subscription(user_id)

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
        # 🌟 เพิ่มปุ่มใหม่สุดอลังการสำหรับ PRO
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
        admin_text = "👑 **ระบบจัดการแอดมิน**\n👉 `/addrole`, `/gencode`, `/broadcast`, `/stats`, `/ban`, `/unban`, `/performance`"
        bot.reply_to(message, admin_text, parse_mode="Markdown")
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
