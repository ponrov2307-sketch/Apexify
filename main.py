import telebot
import logging
telebot.logger.setLevel(logging.DEBUG)

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, register_user, check_vip, add_vip, get_usage, increment_usage, add_watch, get_user_watch
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report
import json
from ai_analyzer import generate_apexify_report, analyze_payment_slip # <--- import เพิ่ม
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
bot = telebot.TeleBot(TELEGRAM_TOKEN)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    
    # --- สร้างปุ่มเมนูหลักด้านล่าง ---
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = KeyboardButton("📊 วิเคราะห์หุ้น")
    btn2 = KeyboardButton("📋 Watchlist ของฉัน")
    btn3 = KeyboardButton("💎 สมัคร VIP")
    markup.add(btn1, btn2, btn3)
    
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "พิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อเริ่มใช้งานได้เลย"
    )
    # ส่งข้อความพร้อมแนบเมนู (markup) ไปด้วย
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")
@bot.message_handler(commands=['addvip'])
def handle_add_vip(message):
    user_id = str(message.chat.id)
    if user_id == ADMIN_ID:
        try:
            args = message.text.split()
            target_user = args[1]
            days = int(args[2]) if len(args) > 2 else 30
            expiry = add_vip(target_user, days)
            bot.reply_to(message, f"✅ อัปเกรดผู้ใช้ `{target_user}` เป็น VIP เรียบร้อย!\nหมดอายุ: {expiry}", parse_mode="Markdown")
        except:
            bot.reply_to(message, "❌ รูปแบบผิด: /addvip [user_id] [days]")

@bot.message_handler(commands=['addwatch'])
def handle_addwatch(message):
    user_id = str(message.chat.id)
    
    if user_id != ADMIN_ID and not check_vip(user_id):
        bot.reply_to(message, "🔒 สิทธิ์เพิ่ม Watchlist ส่วนตัว เฉพาะ **สมาชิก VIP** เท่านั้น!\n\n💎 ติดต่อแอดมินเพื่อสมัคร VIP")
        return

    try:
        symbol = message.text.split()[1].upper()
        current_list = get_user_watch(user_id)
        if len(current_list) >= 5:
            bot.reply_to(message, "❌ คุณเพิ่มหุ้นเข้า Watchlist เต็มโควต้า 5 ตัวแล้วครับ")
            return

        if add_watch(user_id, symbol):
            bot.reply_to(message, f"✅ เพิ่ม **{symbol}** เข้า Watchlist ของคุณแล้ว! บอทจะแจ้งเตือนทันทีที่มีสัญญานสำคัญ")
        else:
            bot.reply_to(message, f"⚠️ คุณมี **{symbol}** ใน Watchlist อยู่แล้วครับ")
            
    except IndexError:
        bot.reply_to(message, "❌ รูปแบบคำสั่งผิด: โปรดพิมพ์ `/addwatch [ชื่อหุ้น]` เช่น `/addwatch NVDA`")

@bot.message_handler(commands=['watchlist'])
def handle_show_watchlist(message):
    user_id = str(message.chat.id)
    my_list = get_user_watch(user_id)
    if my_list:
        bot.reply_to(message, "📋 **Watchlist ของคุณ:**\n" + "\n".join([f"• {sym}" for sym in my_list]))
    else:
        bot.reply_to(message, "📋 Watchlist ของคุณยังว่างเปล่า พิมพ์ `/addwatch [ชื่อหุ้น]` เพื่อเพิ่มครับ")

@bot.message_handler(func=lambda message: True)
def handle_stock_query(message):
    if message.text.startswith('/'): return 
    
    # --- ดักจับการกดปุ่มจากเมนูหลัก ---
    text = message.text.strip()
    if text == "📊 วิเคราะห์หุ้น":
        bot.reply_to(message, "พิมพ์ชื่อสัญลักษณ์หุ้นที่ต้องการวิเคราะห์มาได้เลยครับ เช่น AAPL, TSLA, PTT.BK")
        return
    elif text == "📋 Watchlist ของฉัน":
        handle_show_watchlist(message) # เรียกใช้ฟังก์ชันเดิมได้เลย
        return
    elif text == "💎 สมัคร VIP":
        bot.reply_to(message, "💎 **อัปเกรดเป็น VIP (199.-/เดือน)**\n\n✅ ใช้ AI วิเคราะห์ไม่จำกัด\n✅ ระบบแจ้งเตือนจุดกลับตัว\n✅ สร้าง Watchlist ส่วนตัวได้ 5 ตัว\n\nพิมพ์ `/vip` เพื่อดูวิธีชำระเงินครับ", parse_mode="Markdown")
        return

    symbol = text.upper()
    
    if len(symbol) > 15 or " " in symbol:
        return

    is_vip = check_vip(str(message.chat.id)) # เช็คสิทธิ์
    # ... (ส่วนโค้ดเช็คโควต้าและคำนวณกราฟ AI ปล่อยไว้เหมือนเดิม) ...

    # --- เลื่อนลงมาล่างสุด ตรงก่อนจะส่งรูปภาพ (bot.send_photo) ให้เพิ่มโค้ดนี้ ---
    
    # สร้างปุ่มกดใต้รูป
    markup = InlineKeyboardMarkup()
    btn_add = InlineKeyboardButton(f"⭐ เพิ่ม {symbol} เข้า Watchlist", callback_data=f"addwatch_{symbol}")
    markup.add(btn_add)

    bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
    # แนบ reply_markup=markup เข้าไปตอนส่งรูปด้วย
    bot.send_photo(message.chat.id, chart_buf, caption=report_text, parse_mode="Markdown", reply_markup=markup)

    is_vip = check_vip(user_id)
    usage_count = get_usage(user_id)
    limit = 10 

    if user_id != ADMIN_ID and not is_vip and usage_count >= limit:
        bot.reply_to(message, f"🔒 **โควต้าทดลองใช้ฟรีของคุณหมดแล้วครับ** ({limit}/{limit})\n\n💎 สมัคร VIP (199.-/เดือน) เพื่อใช้งานต่อไม่จำกัด พร้อมฟีเจอร์ AI ขั้นสูง\n\nสนใจสมัครทักแอดมินเลย!", parse_mode="Markdown")
        return

    msg = bot.reply_to(message, f"🔍 Apexify กำลังวิเคราะห์ {symbol}...")
    
    tech_data, chart_buf, error = calculate_technical_indicators(symbol)
    
    if error:
        bot.edit_message_text(error, chat_id=message.chat.id, message_id=msg.message_id)
        return

    bot.edit_message_text(f"🧠 AI กำลังสรุปข้อมูล {symbol}...", chat_id=message.chat.id, message_id=msg.message_id)
    report_text = generate_apexify_report(tech_data)

    if user_id != ADMIN_ID and not is_vip:
        increment_usage(user_id) 
        current = usage_count + 1
        footer = f"\n\n🎁 **Trial Quota:** {current}/{limit} (สมัคร VIP เพื่อปลดล็อก)"
        report_text += footer
    elif is_vip:
        report_text += "\n\n💎 **Apexify VIP Member**"

    bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
    bot.send_photo(message.chat.id, chart_buf, caption=report_text, parse_mode="Markdown")
@bot.message_handler(content_types=['photo'])
def handle_payment_slip(message):
    user_id = str(message.chat.id)
    
    # ถ้าเป็น VIP อยู่แล้ว ไม่ต้องเช็ค
    if check_vip(user_id):
        bot.reply_to(message, "💎 คุณเป็นสมาชิก VIP อยู่แล้วครับ ขอบคุณที่สนับสนุนเรา!")
        return

    # ถ้าลูกค้าส่งรูปมา ให้สมมติว่าเป็นสลิป
    msg = bot.reply_to(message, "🧾 ได้รับรูปภาพแล้ว... ระบบ AI กำลังตรวจสอบสลิป กรุณารอสักครู่ครับ...")
    
    try:
        # 1. ดาวน์โหลดรูปภาพจาก Telegram
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # 2. ส่งให้ AI ตรวจสอบ
        ai_result_json = analyze_payment_slip(downloaded_file)
        
        if not ai_result_json:
            bot.edit_message_text("❌ ระบบไม่สามารถอ่านรูปภาพได้ โปรดลองใหม่อีกครั้ง หรือส่งให้แอดมินตรวจสอบ", chat_id=message.chat.id, message_id=msg.message_id)
            return

        # 3. แปลงผลลัพธ์
        result = json.loads(ai_result_json)
        
        # 4. ตัดสินใจ
        if result.get('is_slip') and result.get('amount', 0) >= 199:
            # ✅ ผ่าน! เติม VIP ให้เลย
            expiry = add_vip(user_id, days=30)
            success_msg = (
                f"✅ **ตรวจสอบสลิปสำเร็จ!**\n"
                f"💰 ยอดเงิน: {result['amount']} บาท\n"
                f"📅 วันที่: {result.get('date', '-')}\n\n"
                f"🎉 **ยินดีด้วย! คุณได้รับการอัปเกรดเป็น VIP แล้ว**\n"
                f"⏰ หมดอายุ: {expiry}\n\n"
                f"เริ่มใช้งานฟีเจอร์พิเศษได้ทันทีพิมพ์ `/addwatch` เพื่อเฝ้าหุ้นได้เลย!"
            )
            bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
            bot.reply_to(message, success_msg, parse_mode="Markdown")
            
            # แจ้งแอดมินด้วยว่ามีเงินเข้า
            bot.send_message(ADMIN_ID, f"💰 **NEW VIP PAYMENT!**\nUser: {user_id}\nAmount: {result['amount']} THB")
            
        else:
            # ❌ ไม่ผ่าน
            fail_msg = "❌ **รูปภาพนี้ไม่ใช่สลิปโอนเงินที่ถูกต้อง หรือยอดเงินไม่ครบ 199 บาท**\n\nหากมีข้อผิดพลาด กรุณาติดต่อแอดมินโดยตรงครับ"
            bot.edit_message_text(fail_msg, chat_id=message.chat.id, message_id=msg.message_id)
            
    except Exception as e:
        print(f"Error checking slip: {e}")
        bot.edit_message_text("❌ เกิดข้อผิดพลาดในการตรวจสอบ กรุณาส่งสลิปให้แอดมินตรวจสอบแทนครับ", chat_id=message.chat.id, message_id=msg.message_id)
# --- ฟังก์ชันจัดการเมื่อมีคนกดปุ่ม Inline ใต้ข้อความ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_'))
def handle_inline_addwatch(call):
    user_id = str(call.message.chat.id)
    symbol = call.data.split('_')[1] # ตัดเอาชื่อหุ้นออกมาจาก addwatch_NVDA
    
    # 1. ลบสถานะโหลดของปุ่ม (กันปุ่มค้าง)
    bot.answer_callback_query(call.id)
    
    # 2. เช็คสิทธิ์ VIP
    if user_id != ADMIN_ID and not check_vip(user_id):
        bot.send_message(user_id, "🔒 สิทธิ์เพิ่ม Watchlist เฉพาะ **สมาชิก VIP** เท่านั้น!\n💎 กดปุ่ม [สมัคร VIP] ที่เมนูด้านล่างเพื่อปลดล็อกครับ")
        return

    # 3. เพิ่มเข้าฐานข้อมูล
    current_list = get_user_watch(user_id)
    if len(current_list) >= 5:
        bot.send_message(user_id, "❌ คุณเพิ่มหุ้นเข้า Watchlist เต็มโควต้า 5 ตัวแล้วครับ")
        return

    if add_watch(user_id, symbol):
        bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** เข้า Watchlist ของคุณแล้ว! บอทจะแจ้งเตือนทันทีที่มีสัญญานสำคัญ")
    else:
        bot.send_message(user_id, f"⚠️ คุณมี **{symbol}** ใน Watchlist อยู่แล้วครับ")
if __name__ == "__main__":
    init_db()
    keep_alive() 
    print("⚡️ Apexify Bot is running with Freemium Mode...")
    bot.infinity_polling()