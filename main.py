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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
# 🌟 Import ฟังก์ชันทั้งหมดจาก database
from database import (get_all_users, init_db, register_user, check_subscription, add_subscription, 
                      get_usage, increment_usage, add_watch, get_user_watch, get_user_profile, 
                      remove_watch_db, add_promo_code, redeem_code, get_user_stats, 
                      check_slip_used, mark_slip_used, ban_user, unban_user, is_user_banned)
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index
from ai_analyzer import generate_apexify_report, analyze_payment_slip

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

telebot.logger.setLevel(logging.DEBUG)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

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
            bot.send_message(ADMIN_ID, f"🚨 **แจ้งเตือนสแปม:** User `{user_id}` พยายามส่งข้อความรัวๆ\n👉 พิมพ์ `/ban {user_id}` เพื่อแบน", parse_mode="Markdown")
            spam_alerted.add(user_id)
        return False
        
    if len(user_message_tracking[user_id]) <= 5 and user_id in spam_alerted:
        spam_alerted.remove(user_id)
        
    return True

def generate_random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    register_user(user_id)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 วิเคราะห์หุ้น"), KeyboardButton("📋 Watchlist ของฉัน"))
    markup.add(KeyboardButton("🌍 สภาวะตลาด"), KeyboardButton("📰 ข่าวด่วนตลาดทุน"))
    markup.add(KeyboardButton("🚀 สแกน Watchlist (VIP)"), KeyboardButton("👤 บัญชีของฉัน"))
    markup.add(KeyboardButton("📚 วิธีอ่านสัญญาณ"), KeyboardButton("💎 สมัคร VIP"))
    markup.add(KeyboardButton("🎁 เติมโค้ด VIP")) 
    
    if user_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 แผงควบคุมแอดมิน"))
    
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "พิมพ์ชื่อหุ้นที่ต้องการวิเคราะห์ส่งมาได้เลยครับ:\n"
        "🇺🇸 หุ้นต่างประเทศ: `AAPL`, `TSLA`, `NVDA`\n"
        "🇹🇭 หุ้นไทย (ต้องมี .BK): `PTT.BK`, `AOT.BK`, `TRUE.BK`"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

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
        bot.reply_to(message, "❌ รูปแบบคำสั่งไม่ถูกต้อง พิมพ์: `/redeem [โค้ดของคุณ]`")
        return
    
    code = args[1].strip().upper()
    success, days, expiry, role_type = redeem_code(user_id, code)
    
    if success:
        bot.reply_to(message, f"🎉 **ยินดีด้วย!** เติมโค้ดสำเร็จ\nคุณได้รับการอัปเกรดเป็น **{role_type.upper()} Member** ถึงวันที่: `{expiry}`", parse_mode="Markdown")
        increment_usage(user_id) 
    elif days == "already_used_by_you":
        bot.reply_to(message, "⚠️ คุณเคยใช้โค้ดโปรโมชั่นนี้ไปแล้วครับ")
    elif days == "fully_used":
        bot.reply_to(message, "❌ สิทธิ์ของโค้ดนี้ถูกใช้งานครบตามจำนวนแล้วครับ")
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

@bot.message_handler(commands=['watchlist'])
def handle_watchlist_cmd(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    my_list = get_user_watch(user_id)
    if not my_list:
        bot.reply_to(message, "📋 Watchlist ของคุณว่างเปล่า")
        return
    markup = InlineKeyboardMarkup()
    for symbol in my_list:
        markup.add(InlineKeyboardButton(f"❌ ลบ {symbol}", callback_data=f"delwatch_{symbol}"))
    bot.reply_to(message, "📋 **จัดการ Watchlist:**", parse_mode="Markdown", reply_markup=markup)

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
            bot.send_message(uid, f"📢 **ประกาศ:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
        except Exception:
            fail += 1 
    bot.reply_to(message, f"✅ สำเร็จ: {success} คน | ❌ ล้มเหลว: {fail} คน")

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    if str(message.chat.id) != ADMIN_ID: return
    try:
        stats, total = get_user_stats()
        est_revenue = (stats.get('vip', 0) * 199) + (stats.get('pro', 0) * 499)
        msg = (
            "📊 **สถิติการใช้งาน Apexify**\n\n"
            f"👥 **ผู้ใช้งานทั้งหมด:** {total} คน\n"
            f"🆓 **สายฟรี:** {stats.get('free', 0)} คน\n"
            f"💎 **VIP:** {stats.get('vip', 0)} คน\n"
            f"👑 **PRO:** {stats.get('pro', 0)} คน\n\n"
            f"💰 **รายได้ประเมิน:** {est_revenue:,.2f} บาท/เดือน"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['performance'])
def handle_performance(message):
    if str(message.chat.id) != ADMIN_ID: return
    status_msg = bot.reply_to(message, "⏳ กำลังคำนวณความแม่นยำ AI...")
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT symbol, alert_type, price_at_alert, timestamp FROM alert_logs ORDER BY id DESC LIMIT 15")
        logs = c.fetchall()
        conn.close()

        if not logs:
            bot.edit_message_text("❌ ยังไม่มีประวัติการแจ้งเตือน", message.chat.id, status_msg.message_id)
            return

        report_text = "🎯 **ผลงานความแม่นยำ AI (ล่าสุด)** 🎯\n\n"
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
                
                report_text += f"{emoji} **{symbol}** ({short_type})\n   เตือน: {start_price:.2f} ➡️ ปัจจุบัน: {current_price:.2f} ({diff_pct:+.2f}%)\n"
            except Exception: continue
        
        if total_count > 0:
            win_rate = (win_count / total_count) * 100
            report_text += f"\n🏆 **Win Rate:** {win_rate:.2f}% ({win_count}/{total_count})"
        bot.edit_message_text(report_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

@bot.message_handler(content_types=['photo'])
def handle_payment_slip_check(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    role = check_subscription(user_id)
    
    progress_msg = bot.reply_to(message, "🧾 AI กำลังตรวจสอบสลิป...")
        
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ai_result = analyze_payment_slip(downloaded_file)
        result = json.loads(ai_result.replace('```json', '').replace('```', ''))
        
        if result.get('is_slip'):
            amount = float(result.get('amount', 0))
            ref_no = result.get('ref_no', '').strip()
            
            if not ref_no or ref_no == "" or ref_no.lower() == "none":
                bot.edit_message_text("⚠️ ควรถ่ายให้เห็นเลขที่อ้างอิงชัดๆ ครับ", message.chat.id, progress_msg.message_id)
                return
            if check_slip_used(ref_no):
                bot.edit_message_text("❌ **สลิปนี้ถูกใช้งานไปแล้ว!**", message.chat.id, progress_msg.message_id)
                return

            if amount == 4990:
                expiry = add_subscription(user_id, 'pro', 365)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** อัปเกรด **👑 PRO (รายปี)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 1990:
                expiry = add_subscription(user_id, 'vip', 365)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** อัปเกรด **💎 VIP (รายปี)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 499:
                expiry = add_subscription(user_id, 'pro', 30)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** อัปเกรด **👑 PRO (รายเดือน)**\n⏰ หมดอายุ: {expiry}"
            elif amount == 199:
                expiry = add_subscription(user_id, 'vip', 30)
                msg_text = f"🎉 **ชำระเงินสำเร็จ!** อัปเกรด **💎 VIP (รายเดือน)**\n⏰ หมดอายุ: {expiry}"
            else:
                bot.edit_message_text(f"❌ **ยอดเงินไม่ตรงกับแพ็กเกจ** ({amount:,.2f} บาท)", message.chat.id, progress_msg.message_id)
                return

            mark_slip_used(ref_no, user_id)
            bot.delete_message(message.chat.id, progress_msg.message_id)
            bot.reply_to(message, msg_text, parse_mode="Markdown")
        else:
            bot.edit_message_text("❌ รูปนี้ไม่ใช่สลิปโอนเงินครับ", message.chat.id, progress_msg.message_id)
    except Exception as e:
        bot.edit_message_text("⚠️ AI อ่านสลิปไม่ได้ โปรดลองใหม่", message.chat.id, progress_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_'))
def inline_watchlist(call):
    user_id = str(call.message.chat.id)
    if not is_allowed(user_id): return
    action, symbol = call.data.split('_')
    role = check_subscription(user_id)
    bot.answer_callback_query(call.id)
    
    if action == 'addwatch':
        current_watch = len(get_user_watch(user_id))
        if role == 'free' and current_watch >= 3:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 3 ตัว** โปรดอัปเกรด")
            return
        elif role == 'vip' and current_watch >= 10:
            bot.send_message(user_id, "🔒 **จำกัด Watchlist 10 ตัว** โปรดอัปเกรดเป็น PRO")
            return
        if add_watch(user_id, symbol):
            bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** แล้ว")
        else:
            bot.send_message(user_id, f"⚠️ มี **{symbol}** อยู่แล้ว")
    elif action == 'delwatch':
        remove_watch_db(user_id, symbol)
        bot.edit_message_text(f"🗑️ ลบ **{symbol}** แล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    if not is_allowed(user_id): return
    
    text = message.text.strip()
    role = check_subscription(user_id)

    if text == "📊 วิเคราะห์หุ้น":
        bot.reply_to(message, "ส่งชื่อหุ้นมาได้เลยครับ (หุ้นไทยอย่าลืมใส่ .BK ต่อท้ายนะ)")
        return
    elif text == "📋 Watchlist ของฉัน":
        handle_watchlist_cmd(message)
        return
    elif text == "💎 สมัคร VIP":
        pay_text = (
            "💎 **อัปเกรดบัญชี (VIP / PRO)**\n"
            "💳 ธนาคารกสิกรไทย: `135-1-34469-1`\n"
            "ชื่อ: นาย เกียรติศักดิ์ วุฒิจันทร์\n\n"
            "⭐ **VIP (199.-/เดือน)**: AI ฟันธง + ข่าวด่วน + Watchlist 10 ตัว\n"
            "👑 **PRO (499.-/เดือน)**: กราฟ Realtime + Watchlist ไม่จำกัด\n"
            "✅ *โอนยอดเงินตามแพ็กเกจ แล้วส่งสลิปมาในแชทนี้ได้เลยครับ*"
        )
        bot.reply_to(message, pay_text, parse_mode="Markdown")
        return
    elif text == "🎁 เติมโค้ด VIP":
        bot.reply_to(message, "🎟 พิมพ์คำสั่ง `/redeem [ตามด้วยโค้ดของคุณ]`", parse_mode="Markdown")
        return
    elif text == "👤 บัญชีของฉัน":
        profile = get_user_profile(user_id)
        if profile:
            _, expiry, usage, reg_date = profile
            watch_count = len(get_user_watch(user_id))
            status_text = "👑 PRO" if role == 'pro' else "💎 VIP" if role == 'vip' else "🆓 Free"
            msg = f"👤 **ID:** `{user_id}`\n🏷 **สถานะ:** {status_text}\n⏰ **หมดอายุ:** {expiry or 'ไม่มี'}\n📋 **Watchlist:** {watch_count} ตัว"
        else:
            msg = "❌ ไม่พบข้อมูล"
        bot.reply_to(message, msg, parse_mode="Markdown")
        return
    elif text == "🌍 สภาวะตลาด":
        load_msg = bot.reply_to(message, "🌍 กำลังดึงข้อมูล...")
        try:
            fg_index = get_fear_and_greed_index()
            indices = {"SET (ไทย)": "^SET.BK", "S&P 500 (สหรัฐ)": "^GSPC", "Bitcoin (คริปโต)": "BTC-USD"}
            market_text = ""
            for name, sym in indices.items():
                data = yf.Ticker(sym).history(period="5d")
                if len(data) >= 2:
                    close_today = data['Close'].iloc[-1]
                    pct_change = ((close_today - data['Close'].iloc[-2]) / data['Close'].iloc[-2]) * 100
                    emoji = "🟢" if pct_change >= 0 else "🔴"
                    market_text += f"• {name}: {close_today:,.2f} ({pct_change:+.2f}%) {emoji}\n"
            msg = f"🌍 **สภาวะตลาด**\n🧭 **Fear & Greed:** {fg_index}\n📊 **ดัชนี:**\n{market_text}"
            bot.edit_message_text(msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
        except: bot.edit_message_text("❌ ดึงข้อมูลล้มเหลว", message.chat.id, load_msg.message_id)
        return
    elif text == "📰 ข่าวด่วนตลาดทุน":
        load_msg = bot.reply_to(message, "📰 กำลังดึงข่าว...")
        try:
            url = "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+การลงทุน&hl=th&gl=TH&ceid=TH:th"
            res = cffi_requests.get(url, impersonate="chrome110", timeout=15)
            soup = BeautifulSoup(res.content, "xml")
            items = soup.find_all("item")[:3]
            news_text = "📰 **Top 3 ข่าวเด่นวันนี้**\n\n"
            for i, item in enumerate(items, 1):
                link_tag = item.find('link')
                link = link_tag.next_sibling.strip() if link_tag and link_tag.next_sibling else ""
                news_text += f"{i}. [{item.title.text}]({link})\n\n"
            bot.edit_message_text(news_text, message.chat.id, load_msg.message_id, parse_mode="Markdown", disable_web_page_preview=True)
        except: bot.edit_message_text("❌ ล้มเหลว", message.chat.id, load_msg.message_id)
        return
    elif text == "🚀 สแกน Watchlist (VIP)":
        if user_id != ADMIN_ID and role == 'free':
            bot.reply_to(message, "🔒 สงวนสิทธิ์เฉพาะ **VIP / PRO**")
            return
        my_list = get_user_watch(user_id)
        if not my_list:
            bot.reply_to(message, "📋 Watchlist ว่างเปล่า")
            return
        scan_msg = bot.reply_to(message, f"🚀 สแกนหุ้น {len(my_list)} ตัว...")
        scan_result = "🚀 **รายงานสแกน**\n\n"
        for sym in my_list:
            try:
                tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                if err or not tech_data: continue
                ema_short = "🟢 ขาขึ้น" if tech_data['ema20'] > tech_data['ema50'] else "🔴 ขาลง"
                cross = "✨ Golden Cross!" if tech_data['ema50'] > tech_data['ema200'] else "ธรรมดา"
                rsi = tech_data['rsi']
                rsi_txt = "🔥 Overbought" if rsi > 70 else "🎯 Oversold" if rsi < 30 else "⚪️ กลาง"
                scan_result += f"📌 **{sym}** ({tech_data['price']:.2f})\n   เทรนด์: {ema_short} | RSI: {rsi_txt}\n"
            except: pass
        bot.edit_message_text(scan_result, message.chat.id, scan_msg.message_id, parse_mode="Markdown")
        return
    elif text == "📚 วิธีอ่านสัญญาณ":
        bot.reply_to(message, "📚 **วิธีอ่านสัญญาณ:**\n- **RSI Overbought 🔴:** ราคาขึ้นแรงเกินไป ระวังโดนเทขาย\n- **RSI Oversold 🟢:** ราคาตกหนักเกินไป อาจมีเด้งกลับ\n- **Golden Cross 🟢:** จุดกลับตัวเป็นขาขึ้น\n- **Death Cross 🔴:** จุดกลับตัวเป็นขาลง", parse_mode="Markdown")
        return
    elif text == "👑 แผงควบคุมแอดมิน":
        if user_id != ADMIN_ID: return
        bot.reply_to(message, "👑 **Admin Menu**\n👉 `/addrole`, `/gencode`, `/broadcast`, `/stats`, `/ban`, `/performance`", parse_mode="Markdown")
        return

    symbol = text.upper()
    if len(symbol) > 10: return

    usage = get_usage(user_id)
    if user_id != ADMIN_ID and role == 'free' and usage >= 10:
        bot.reply_to(message, "🔒 โควต้าฟรีหมดแล้ว กด [💎 สมัคร VIP]")
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
    markup.add(InlineKeyboardButton(f"⭐ เพิ่ม {correct_symbol}", callback_data=f"addwatch_{correct_symbol}"))

    bot.delete_message(message.chat.id, load_msg.message_id)
    
    # 🌟 ระบบส่งข้อความแบบกัน Error (แก้อาการมีแต่รูป ไม่มีตัวหนังสือ)
    if len(report) > 1000:
        bot.send_photo(message.chat.id, chart)
        try:
            # ลองส่งแบบจัดหน้า (Markdown)
            bot.send_message(message.chat.id, report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            # ถ้า AI ใส่สัญลักษณ์แปลกๆ จนพัง ให้ส่งแบบข้อความธรรมดากันเหนียว
            bot.send_message(message.chat.id, report, reply_markup=markup)
    else:
        try:
            bot.send_photo(message.chat.id, chart, caption=report, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            chart.seek(0) # รีเซ็ตไฟล์รูป
            bot.send_photo(message.chat.id, chart, caption=report, reply_markup=markup)

if __name__ == "__main__":
    init_db()
    keep_alive()
    bot.infinity_polling()
