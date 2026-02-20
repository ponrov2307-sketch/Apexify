import telebot
import logging
import json
import PIL.Image
import io
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, register_user, check_vip, add_vip, get_usage, increment_usage, add_watch, get_user_watch
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report, analyze_payment_slip

# ตั้งค่า Logging
telebot.logger.setLevel(logging.DEBUG)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- 1. เมนูเริ่มต้น ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 วิเคราะห์หุ้น"), KeyboardButton("📋 Watchlist ของฉัน"), KeyboardButton("💎 สมัคร VIP"))
    
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "พิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อเริ่มใช้งานได้เลย"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

# --- 2. ระบบจัดการคำสั่งพื้นฐาน ---
@bot.message_handler(commands=['addvip'])
def handle_add_vip(message):
    if str(message.chat.id) == ADMIN_ID:
        try:
            args = message.text.split()
            target_user, days = args[1], int(args[2]) if len(args) > 2 else 30
            expiry = add_vip(target_user, days)
            bot.reply_to(message, f"✅ อัปเกรด `{target_user}` เป็น VIP แล้ว\nหมดอายุ: {expiry}")
        except:
            bot.reply_to(message, "❌ รูปแบบ: /addvip [user_id] [days]")

@bot.message_handler(commands=['watchlist'])
def handle_watchlist_cmd(message):
    my_list = get_user_watch(str(message.chat.id))
    msg = "📋 **Watchlist ของคุณ:**\n" + "\n".join([f"• {s}" for s in my_list]) if my_list else "📋 Watchlist ว่างเปล่า"
    bot.reply_to(message, msg, parse_mode="Markdown")

# --- 3. ระบบตรวจสลิปด้วย AI ---
@bot.message_handler(content_types=['photo'])
def handle_payment_slip_check(message):
    user_id = str(message.chat.id)
    if check_vip(user_id):
        bot.reply_to(message, "💎 คุณเป็น VIP อยู่แล้วครับ!")
        return

    progress_msg = bot.reply_to(message, "🧾 AI กำลังตรวจสอบสลิปโอนเงิน...")
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        ai_result = analyze_payment_slip(downloaded_file)
        result = json.loads(ai_result.replace('```json', '').replace('```', ''))
        
        if result.get('is_slip') and result.get('amount', 0) >= 199:
            expiry = add_vip(user_id, 30)
            bot.delete_message(message.chat.id, progress_msg.message_id)
            bot.reply_to(message, f"✅ **ชำระเงินสำเร็จ!**\nอัปเกรดเป็น VIP แล้ว\n⏰ หมดอายุ: {expiry}", parse_mode="Markdown")
            bot.send_message(ADMIN_ID, f"💰 เงินเข้า! User {user_id} โอน {result['amount']} บาท")
        else:
            bot.edit_message_text("❌ สลิปไม่ถูกต้องหรือยอดเงินไม่ครบ 199 บาท", message.chat.id, progress_msg.message_id)
    except:
        bot.edit_message_text("❌ เกิดข้อผิดพลาดในการอ่านสลิป", message.chat.id, progress_msg.message_id)

# --- 4. ปุ่มกดเพิ่ม Watchlist ใต้กราฟ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_'))
def inline_addwatch(call):
    user_id = str(call.message.chat.id)
    symbol = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    
    if user_id != ADMIN_ID and not check_vip(user_id):
        bot.send_message(user_id, "🔒 สิทธิ์นี้สำหรับสมาชิก VIP เท่านั้น")
        return

    if add_watch(user_id, symbol):
        bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** เข้า Watchlist แล้ว")
    else:
        bot.send_message(user_id, f"⚠️ มี **{symbol}** อยู่แล้ว")

# --- 5. ระบบวิเคราะห์หุ้น (Core Logic) ---
@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    text = message.text.strip()

    # จัดการปุ่มเมนู
    if text == "📊 วิเคราะห์หุ้น":
        bot.reply_to(message, "ส่งชื่อหุ้นมาได้เลยครับ (เช่น NVDA)")
        return
    elif text == "📋 Watchlist ของฉัน":
        handle_watchlist_cmd(message)
        return
    elif text == "💎 สมัคร VIP":
        pay_text = (
            "💎 **สมัคร VIP (199.- / 30 วัน)**\n"
            "💳 กสิกรไทย: `135-1-34469-1`\n"
            "ชื่อ: นาย เกียรติศักดิ์ วุฒิจันทร์\n\n"
            "โอนแล้วส่งรูปสลิปมาที่นี่ได้เลย!"
        )
        bot.reply_to(message, pay_text, parse_mode="Markdown")
        return

    # วิเคราะห์หุ้น
    symbol = text.upper()
    if len(symbol) > 10: return

    is_vip = check_vip(user_id)
    usage = get_usage(user_id)
    if user_id != ADMIN_ID and not is_vip and usage >= 10:
        bot.reply_to(message, "🔒 โควต้าฟรีหมดแล้ว กดปุ่ม [💎 สมัคร VIP] เพื่อใช้งานต่อ")
        return

    load_msg = bot.reply_to(message, f"🔍 Apexify กำลังวิเคราะห์ {symbol}...")
    tech_data, chart, err = calculate_technical_indicators(symbol)
    
    if err:
        bot.edit_message_text(err, message.chat.id, load_msg.message_id)
        return

    report = generate_apexify_report(tech_data)
    
    # เพิ่ม Footer ตามสถานะ
    if user_id != ADMIN_ID and not is_vip:
        increment_usage(user_id)
        report += f"\n\n🎁 **Trial:** {usage + 1}/10"
    else:
        report += "\n\n💎 **VIP Member**"

    # สร้างปุ่ม Inline
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"⭐ เพิ่ม {symbol} เข้า Watchlist", callback_data=f"addwatch_{symbol}"))

    bot.delete_message(message.chat.id, load_msg.message_id)
    bot.send_photo(message.chat.id, chart, caption=report, parse_mode="Markdown", reply_markup=markup)

if __name__ == "__main__":
    init_db()
    keep_alive()
    bot.infinity_polling()