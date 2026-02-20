import telebot
import logging
telebot.logger.setLevel(logging.DEBUG)

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db, register_user, check_vip, add_vip, get_usage, increment_usage, add_watch, get_user_watch
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report

bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "พิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อเริ่มใช้งานได้เลย\n\n"
        "📌 **คำสั่งสำหรับสมาชิก VIP:**\n"
        "`/addwatch [ชื่อหุ้น]` - เพิ่มหุ้นเข้าลิสต์แจ้งเตือนส่วนตัว\n"
        "`/watchlist` - ดูหุ้นที่คุณกำลังเฝ้าระวังอยู่"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

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
    if message.text.startswith('/'): return # ป้องกันบั๊กเวลาคนพิมพ์คำสั่งแปลกๆ
    
    user_id = str(message.chat.id)
    symbol = message.text.upper().strip()
    
    if len(symbol) > 15 or " " in symbol:
        return

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

if __name__ == "__main__":
    init_db()
    keep_alive() 
    print("⚡️ Apexify Bot is running with Freemium Mode...")
    bot.infinity_polling()