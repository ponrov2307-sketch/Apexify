import telebot
from config import TELEGRAM_TOKEN, ADMIN_ID
# เพิ่ม get_usage และ increment_usage เข้ามา
from database import init_db, register_user, check_vip, add_vip, get_usage, increment_usage 
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report
import logging # <--- เพิ่มบรรทัดนี้
telebot.logger.setLevel(logging.DEBUG)
from config import TELEGRAM_TOKEN, ADMIN_ID
bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    bot.reply_to(message, "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\nพิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อเริ่มใช้งานได้เลย", parse_mode="Markdown")

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

@bot.message_handler(func=lambda message: True)
def handle_stock_query(message):
    user_id = str(message.chat.id)
    symbol = message.text.upper().strip()
    
    if len(symbol) > 15 or " " in symbol:
        return

    # --- เช็คสิทธิ์การใช้งาน (Logic ใหม่) ---
    is_vip = check_vip(user_id)
    usage_count = get_usage(user_id)
    limit = 10 # จำนวนครั้งที่ให้ใช้ฟรี

    # ถ้าไม่ใช่แอดมิน และไม่ใช่ VIP และใช้เกินโควต้าแล้ว -> บล็อก
    if user_id != ADMIN_ID and not is_vip and usage_count >= limit:
        bot.reply_to(message, f"🔒 **โควต้าทดลองใช้ฟรีของคุณหมดแล้วครับ** ({limit}/{limit})\n\n💎 สมัคร VIP (199.-/เดือน) เพื่อใช้งานต่อไม่จำกัด พร้อมฟีเจอร์ AI ขั้นสูง\n\nสนใจสมัครทักแอดมินเลย!", parse_mode="Markdown")
        return

    msg = bot.reply_to(message, f"🔍 Apexify กำลังวิเคราะห์ {symbol}...")
    
    # 1. คำนวณค่าเทคนิค
    tech_data, chart_buf, error = calculate_technical_indicators(symbol)
    
    if error:
        bot.edit_message_text(error, chat_id=message.chat.id, message_id=msg.message_id)
        return

    # 2. สร้างรายงาน AI
    bot.edit_message_text(f"🧠 AI กำลังสรุปข้อมูล {symbol}...", chat_id=message.chat.id, message_id=msg.message_id)
    report_text = generate_apexify_report(tech_data)

    # --- ส่วนแสดงสถานะโควต้าท้ายข้อความ ---
    if user_id != ADMIN_ID and not is_vip:
        increment_usage(user_id) # บวกจำนวนการใช้
        current = usage_count + 1
        footer = f"\n\n🎁 **Trial Quota:** {current}/{limit} (สมัคร VIP เพื่อปลดล็อก)"
        report_text += footer
    elif is_vip:
        report_text += "\n\n💎 **Apexify VIP Member**"

    # 3. ส่งผลลัพธ์
    bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
    bot.send_photo(message.chat.id, chart_buf, caption=report_text, parse_mode="Markdown")

if __name__ == "__main__":
    init_db()
    print("⚡️ Apexify Bot is running with Freemium Mode...")
    bot.infinity_polling()