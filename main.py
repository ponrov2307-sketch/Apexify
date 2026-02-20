import telebot
from config import TELEGRAM_TOKEN
from database import init_db, register_user
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report

# สร้างออบเจกต์บอท
bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    bot.reply_to(message, "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\nพิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อดูรายงานได้เลยครับ!", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_stock_query(message):
    symbol = message.text.upper().strip()
    
    # ป้องกันคนพิมพ์ข้อความทั่วไป
    if len(symbol) > 15 or " " in symbol:
        bot.reply_to(message, "กรุณาพิมพ์สัญลักษณ์หุ้นที่ถูกต้อง เช่น NVDA หรือ CPALL.BK")
        return

    msg = bot.reply_to(message, f"🔍 Apexify กำลังดึงข้อมูลและคำนวณอินดิเคเตอร์ให้ {symbol}...")
    
    # 1. คำนวณค่าเทคนิคและวาดกราฟ
    tech_data, chart_buf, error = calculate_technical_indicators(symbol)
    
    if error:
        bot.edit_message_text(error, chat_id=message.chat.id, message_id=msg.message_id)
        return

    # 2. สร้างรายงานด้วย AI
    bot.edit_message_text(f"🧠 กำลังให้ AI ประมวลผลสรุปภาพรวม {symbol}...", chat_id=message.chat.id, message_id=msg.message_id)
    report_text = generate_apexify_report(tech_data)
    
    # 3. ส่งผลลัพธ์พร้อมรูปภาพ
    bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
    bot.send_photo(message.chat.id, chart_buf, caption=report_text, parse_mode="Markdown")

if __name__ == "__main__":
    init_db()
    print("⚡️ Apexify Bot is running module mode...")
    bot.infinity_polling()