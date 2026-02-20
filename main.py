import telebot
import logging
import json
import PIL.Image
import io
import yfinance as yf
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from keep_alive import keep_alive 
from config import TELEGRAM_TOKEN, ADMIN_ID
from database import get_all_users, init_db, register_user, check_vip, add_vip, get_usage, increment_usage, add_watch, get_user_watch, get_user_profile, remove_watch_db
from technical_tools import calculate_technical_indicators, get_fear_and_greed_index
from ai_analyzer import generate_apexify_report, analyze_payment_slip

# ตั้งค่า Logging
telebot.logger.setLevel(logging.DEBUG)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- 1. เมนูเริ่มต้น (อัปเกรดปุ่ม) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = str(message.chat.id)
    register_user(user_id)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("📊 วิเคราะห์หุ้น"), KeyboardButton("📋 Watchlist ของฉัน"))
    markup.add(KeyboardButton("🌍 สภาวะตลาด"), KeyboardButton("👤 บัญชีของฉัน"))
    markup.add(KeyboardButton("📚 วิธีอ่านสัญญาณ"), KeyboardButton("💎 สมัคร VIP"))
    
    welcome_text = (
        "⚡️ ยินดีต้อนรับสู่ **Apexify** ระบบวิเคราะห์หุ้นอัจฉริยะ\n\n"
        "🎁 **คุณได้รับสิทธิ์ทดลองใช้งานฟรี 10 ครั้ง!**\n"
        "เลือกเมนูด้านล่าง หรือพิมพ์ชื่อหุ้น (เช่น AAPL, TSLA, PTT.BK) เพื่อเริ่มใช้งานได้เลย"
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
    user_id = str(message.chat.id)
    my_list = get_user_watch(user_id)
    
    if not my_list:
        bot.reply_to(message, "📋 Watchlist ของคุณว่างเปล่า\nพิมพ์ชื่อหุ้นแล้วกด ⭐ เพิ่มเข้า Watchlist ใต้กราฟได้เลยครับ")
        return
        
    markup = InlineKeyboardMarkup()
    for symbol in my_list:
        markup.add(InlineKeyboardButton(f"❌ ลบ {symbol}", callback_data=f"delwatch_{symbol}"))
        
    msg = "📋 **จัดการ Watchlist ของคุณ:**\n(กดปุ่มด้านล่างเพื่อลบหุ้นที่ไม่ต้องการแจ้งเตือน)"
    bot.reply_to(message, msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message):
    user_id = str(message.chat.id)
    if user_id != ADMIN_ID:
        bot.reply_to(message, "🔒 คำสั่งนี้สำหรับแอดมินเท่านั้นครับ")
        return
        
    msg_text = message.text.replace('/broadcast', '').strip()
    if not msg_text:
        bot.reply_to(message, "❌ รูปแบบคำสั่ง: /broadcast [ข้อความที่ต้องการส่ง]")
        return
        
    users = get_all_users()
    success, fail = 0, 0
    bot.reply_to(message, f"⏳ กำลังส่งข้อความหาผู้ใช้ {len(users)} คน...")
    
    for uid in users:
        try:
            bot.send_message(uid, f"📢 **ประกาศจาก Apexify:**\n\n{msg_text}", parse_mode="Markdown")
            success += 1
        except Exception:
            fail += 1 # นับคนที่บล็อคบอทไปแล้ว
            
    bot.reply_to(message, f"✅ บรอดแคสต์สำเร็จ: {success} คน\n❌ ล้มเหลว/บล็อคบอท: {fail} คน")

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
    except Exception as e:
        # 1. แจ้งลูกค้าแบบนุ่มนวล
        bot.edit_message_text("⚠️ AI ไม่สามารถอ่านสลิปได้ โปรดถ่ายให้ชัดเจนอีกครั้ง หรือติดต่อแอดมินครับ", message.chat.id, progress_msg.message_id)
        
        # 2. ฟ้องแอดมินทันที! พร้อมส่งรูปสลิปใบนั้นให้แอดมินดูด้วย
        error_msg = f"🚨 **บอสครับ! มีปัญหาระบบตรวจสลิป** 🚨\n👤 User ID: `{user_id}`\n❌ Error: {e}"
        bot.send_message(ADMIN_ID, error_msg, parse_mode="Markdown")
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption="สลิปที่มีปัญหาครับ 👇")

# --- 4. ปุ่ม Inline (เพิ่ม/ลบ Watchlist) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('addwatch_') or call.data.startswith('delwatch_'))
def inline_watchlist(call):
    user_id = str(call.message.chat.id)
    action, symbol = call.data.split('_')
    bot.answer_callback_query(call.id)
    
    if action == 'addwatch':
        if user_id != ADMIN_ID and not check_vip(user_id):
            bot.send_message(user_id, "🔒 สิทธิ์นี้สำหรับสมาชิก VIP เท่านั้น")
            return

        if add_watch(user_id, symbol):
            bot.send_message(user_id, f"✅ เพิ่ม **{symbol}** เข้า Watchlist แล้ว")
        else:
            bot.send_message(user_id, f"⚠️ มี **{symbol}** อยู่แล้ว")
            
    elif action == 'delwatch':
        remove_watch_db(user_id, symbol)
        bot.edit_message_text(f"🗑️ ลบ **{symbol}** ออกจาก Watchlist เรียบร้อยแล้ว", chat_id=call.message.chat.id, message_id=call.message.message_id)

# --- 5. ระบบวิเคราะห์หุ้น (Core Logic) ---
@bot.message_handler(func=lambda message: True)
def handle_main(message):
    user_id = str(message.chat.id)
    text = message.text.strip()

    # จัดการ 6 ปุ่มเมนู
    if text == "📊 วิเคราะห์หุ้น":
        bot.reply_to(message, "ส่งชื่อหุ้นมาได้เลยครับ (เช่น NVDA, AAPL, PTT.BK)")
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
        
    elif text == "👤 บัญชีของฉัน":
        profile = get_user_profile(user_id)
        if profile:
            role, expiry, usage = profile
            status_text = "💎 VIP Member" if role == 'vip' else "🆓 Free Trial"
            expiry_text = expiry if expiry else "ไม่มีวันหมดอายุ (Free)"
            quota_text = f"ไม่จำกัด" if role == 'vip' else f"{usage}/10 ครั้ง"
            
            msg = (
                f"👤 **ข้อมูลบัญชีของคุณ**\n\n"
                f"🏷 **สถานะ:** {status_text}\n"
                f"📈 **การใช้งาน:** {quota_text}\n"
                f"⏰ **หมดอายุ:** {expiry_text}\n\n"
                f"*(หากต้องการอัปเกรดสิทธิ์ กดปุ่ม 💎 สมัคร VIP)*"
            )
        else:
            msg = "❌ ไม่พบข้อมูลบัญชีของคุณ พิมพ์ /start เพื่อลงทะเบียนใหม่"
        bot.reply_to(message, msg, parse_mode="Markdown")
        return
        
    elif text == "🌍 สภาวะตลาด":
        load_msg = bot.reply_to(message, "🌍 กำลังดึงข้อมูลสภาวะตลาดโลก...")
        try:
            fg_index = get_fear_and_greed_index()
            
            # ดึงดัชนีหลักโลกและไทยมาประกอบ
            indices = {"SET (ไทย)": "^SET.BK", "S&P 500 (สหรัฐ)": "^GSPC", "Bitcoin (คริปโต)": "BTC-USD"}
            market_text = ""
            
            for name, sym in indices.items():
                data = yf.Ticker(sym).history(period="2d")
                if len(data) >= 2:
                    close_today = data['Close'].iloc[-1]
                    close_yest = data['Close'].iloc[-2]
                    pct_change = ((close_today - close_yest) / close_yest) * 100
                    emoji = "🟢" if pct_change >= 0 else "🔴"
                    market_text += f"• {name}: {close_today:,.2f} ({pct_change:+.2f}%) {emoji}\n"
                else:
                    market_text += f"• {name}: ⚠️ ดึงข้อมูลไม่ได้\n"
            
            msg = (
                f"🌍 **สรุปสภาวะตลาด (Market Overview)**\n\n"
                f"🧭 **Fear & Greed Index:**\n{fg_index}\n\n"
                f"📊 **ดัชนีสำคัญวันนี้:**\n{market_text}"
            )
            bot.edit_message_text(msg, message.chat.id, load_msg.message_id, parse_mode="Markdown")
        except Exception as e:
            bot.edit_message_text(f"❌ ดึงข้อมูลตลาดล้มเหลว: {e}", message.chat.id, load_msg.message_id)
        return
        
    elif text == "📚 วิธีอ่านสัญญาณ":
        tutorial = (
            "📚 **คู่มืออ่านสัญญาณ Apexify เบื้องต้น**\n\n"
            "1️⃣ **RSI (ความร้อนแรง)**\n"
            "• Overbought 🔴: ราคาขึ้นแรงเกินไป ระวังโดนเทขาย\n"
            "• Oversold 🟢: ราคาตกหนักเกินไป อาจมีเด้งกลับ\n\n"
            "2️⃣ **MACD (ทิศทางระยะสั้น)**\n"
            "• สัญญาณบวก 🟢: กราฟมีโอกาสเป็นขาขึ้น\n"
            "• สัญญาณลบ 🔴: กราฟมีโอกาสเป็นขาลง\n\n"
            "3️⃣ **EMA Cross (จุดตัด)**\n"
            "• Golden Cross 🟢: เส้นระยะสั้นตัดขึ้นเส้นระยะยาว (จังหวะซื้อ)\n"
            "• Death Cross 🔴: เส้นระยะสั้นตัดลงเส้นระยะยาว (จังหวะขาย/หนี)\n\n"
            "4️⃣ **Bollinger Bands (กรอบราคา)**\n"
            "• ถ้าราคาหลุดขอบบน: แพงไป ระวังย่อตัว\n"
            "• ถ้าราคาหลุดขอบล่าง: ถูกไป อาจหาจังหวะทยอยเก็บ\n"
        )
        bot.reply_to(message, tutorial, parse_mode="Markdown")
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