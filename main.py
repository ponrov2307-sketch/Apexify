import telebot
from config import TELEGRAM_TOKEN, ADMIN_ID # <--- อย่าลืมเพิ่ม ADMIN_ID ตรงนี้
from database import init_db, register_user, check_vip, add_vip # <--- import ฟังก์ชันใหม่มาด้วย
from technical_tools import calculate_technical_indicators
from ai_analyzer import generate_apexify_report

bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    bot.reply_to(message, "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\nพิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อดูรายงานได้เลยครับ!", parse_mode="Markdown")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    bot.reply_to(message, "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\nพิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อดูรายงานได้เลยครับ!", parse_mode="Markdown")

# --- เพิ่มคำสั่งลับสำหรับแอดมินในการให้สิทธิ์ VIP ---
@bot.message_handler(commands=['addvip'])
def handle_add_vip(message):
    user_id = str(message.chat.id)
    if user_id == ADMIN_ID: # เช็คว่าเป็นแอดมินของแท้ไหม
        try:
            # รูปแบบคำสั่ง: /addvip [IDลูกค้า] [จำนวนวัน]
            args = message.text.split()
            target_user = args[1]
            days = int(args[2]) if len(args) > 2 else 30
            
            expiry = add_vip(target_user, days)
            bot.reply_to(message, f"✅ อัปเกรดผู้ใช้ `{target_user}` เป็น VIP จำนวน {days} วัน เรียบร้อยแล้ว!\n⏰ หมดอายุ: {expiry}", parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "❌ รูปแบบคำสั่งผิด: โปรดพิมพ์ `/addvip [user_id] [จำนวนวัน]` เช่น `/addvip 123456789 30`", parse_mode="Markdown")

# --- อัปเดตฟังก์ชันเช็คหุ้น ให้ล็อกสิทธิ์ VIP ---
@bot.message_handler(func=lambda message: True)
def handle_stock_query(message):
    user_id = str(message.chat.id)
    symbol = message.text.upper().strip()
    
    # ดักการพิมพ์เล่น
    if len(symbol) > 15 or " " in symbol:
        return
        
    # 🌟 เช็คสิทธิ์ VIP ตรงนี้! (แอดมินใช้ฟรีเสมอ)
    if user_id != ADMIN_ID and not check_vip(user_id):
        bot.reply_to(message, "🔒 ฟีเจอร์นี้สงวนสิทธิ์เฉพาะ **สมาชิก VIP** เท่านั้น!\n\n💎 **อัปเกรดเป็น VIP (199.-/เดือน) เพื่อปลดล็อก:**\n✅ บทวิเคราะห์ AI เชิงลึก\n✅ กราฟ Apexify Pro\n✅ แจ้งเตือนข่าวสาร Real-time\n\nสนใจสมัครทักแอดมินเลยครับ!", parse_mode="Markdown")
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