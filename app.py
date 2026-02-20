import telebot
from google import genai
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import sqlite3
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# ===========================
# 🔑 ส่วนตั้งค่าระบบ (Apexify)
# ===========================
TELEGRAM_TOKEN = "ใส่_TOKEN_ของคุณ"
GEMINI_API_KEY = "AIzaSyBaX407gKCKTPsfBFTgUbSDbJZldcQf2po"
ADMIN_ID = "ใส่_ID_ของคุณ" 

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# ===========================
# 🗄️ ระบบฐานข้อมูลสมาชิกและรายได้
# ===========================
def init_db():
    conn = sqlite3.connect('apex_master.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS members (user_id TEXT PRIMARY KEY, expiry_date TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, amount REAL, date TEXT)')
    conn.commit()
    conn.close()

def is_vip(user_id):
    if str(user_id) == str(ADMIN_ID): return True
    conn = sqlite3.connect('apex_master.db')
    c = conn.cursor()
    c.execute("SELECT expiry_date FROM members WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        expiry = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        if expiry > datetime.now(): return True
    return False

# ===========================
# 📈 ฟังก์ชันคำนวณ Indicator ระดับ Pro
# ===========================
def calculate_indicators(data):
    # EMA
    data['EMA5'] = data['Close'].ewm(span=5, adjust=False).mean()
    data['EMA20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA50'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['EMA200'] = data['Close'].ewm(span=200, adjust=False).mean()
    
    # RSI (14)
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = data['Close'].ewm(span=12, adjust=False).mean()
    ema26 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = ema12 - ema26
    data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands (20)
    data['BB_Middle'] = data['Close'].rolling(window=20).mean()
    std = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['BB_Middle'] + (2 * std)
    data['BB_Lower'] = data['BB_Middle'] - (2 * std)
    
    # OBV (On-Balance Volume)
    obv = [0]
    for i in range(1, len(data.Close)):
        if data.Close.iloc[i] > data.Close.iloc[i-1]:
            obv.append(obv[-1] + data.Volume.iloc[i])
        elif data.Close.iloc[i] < data.Close.iloc[i-1]:
            obv.append(obv[-1] - data.Volume.iloc[i])
        else:
            obv.append(obv[-1])
    data['OBV'] = obv
    
    return data

# ===========================
# 📊 ฟังก์ชันวิเคราะห์และสร้างรีพอร์ต
# ===========================
def get_advanced_analysis(symbol):
    try:
        # โหลดข้อมูลย้อนหลัง 1 ปีเพื่อความแม่นยำของ EMA200
        data = yf.download(symbol, period="1y", interval="1d", progress=False)
        if data.empty: return None, "ไม่พบข้อมูลหุ้น"

        data = calculate_indicators(data)
        
        # ดึงค่าวันล่าสุด
        latest = data.iloc[-1]
        prev = data.iloc[-2]
        
        current_price = latest['Close'].item() if isinstance(latest['Close'], pd.Series) else latest['Close']
        
        # คำนวณแนวรับ-แนวต้าน (20 วันล่าสุด)
        recent20 = data.tail(20)
        support = recent20['Low'].min().item() if isinstance(recent20['Low'].min(), pd.Series) else recent20['Low'].min()
        resistance = recent20['High'].max().item() if isinstance(recent20['High'].max(), pd.Series) else recent20['High'].max()
        
        # --- แปลงค่าเป็น Status ---
        momentum_txt = "บวก 📈" if current_price > latest['EMA5'] else "ลบ 📉"
        rsi_val = latest['RSI']
        rsi_txt = "ซื้อมากเกินไป 🔴" if rsi_val > 70 else "ขายมากเกินไป 🟢" if rsi_val < 30 else "กลาง ⚪️"
        
        macd_txt = "สัญญาณบวก 🟢" if latest['MACD'] > latest['Signal_Line'] else "สัญญาณลบ 🔴"
        
        ema20_50 = "ขาขึ้น 🟢" if latest['EMA20'] > latest['EMA50'] else "ขาลง 🔴"
        ema50_200 = "โกลเด้นครอส 🟢" if latest['EMA50'] > latest['EMA200'] else "เดธครอส 🔴" if latest['EMA50'] < latest['EMA200'] else "ไซด์เวย์ ⚪️"
        
        obv_txt = "เพิ่มขึ้น 📈" if latest['OBV'] > prev['OBV'] else "ลดลง 📉"
        
        # --- วาดกราฟ Apexify Pro ---
        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')
        plot_data = data.tail(90) # แสดงกราฟแค่ 3 เดือนย้อนหลังให้ดูง่าย
        plt.plot(plot_data.index, plot_data['Close'], label='Price', color='#00e676', linewidth=2)
        plt.plot(plot_data.index, plot_data['EMA20'], label='EMA20', color='#3b82f6', linestyle='--')
        plt.plot(plot_data.index, plot_data['EMA50'], label='EMA50', color='#ff5252', linestyle='--')
        
        plt.axhline(y=support, color='green', linestyle=':', alpha=0.6, label=f'Support')
        plt.axhline(y=resistance, color='red', linestyle=':', alpha=0.6, label=f'Resistance')
        
        plt.title(f"Apexify Intelligence: {symbol.upper()}", color='#d4af37', size=16, weight='bold') # ใช้สีทอง
        plt.legend(loc='best')
        plt.grid(color='#333', linestyle='--')
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        
        # --- เตรียมข้อมูลให้ AI วิเคราะห์ ---
        prompt = (f"วิเคราะห์หุ้น {symbol} สั้นๆ กระชับแบบมืออาชีพ ข้อมูลปัจจุบัน: "
                  f"ราคา {current_price:.2f}, แนวรับ {support:.2f}, แนวต้าน {resistance:.2f}, "
                  f"RSI={rsi_val:.1f}, MACD={macd_txt}, ทิศทางระยะสั้น={momentum_txt}, ระยะกลาง={ema20_50}, ระยะยาว={ema50_200} "
                  f"สรุปมุมมองการลงทุนและแนวโน้มที่อาจเกิดขึ้น")
        
        ai_response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        
        # --- ประกอบร่างข้อความ Report ---
        analysis_text = (
            f"📊 **{symbol.upper()}**\n"
            f"โมเมนตัมราคา: ระยะสั้นเป็น{momentum_txt}\n"
            f"RSI: {rsi_txt} | MACD: {macd_txt}\n"
            f"ราคาเฉลี่ย 5 วัน: `{latest['EMA5']:.2f}`\n"
            f"โบลลิงเจอร์ (20): `{latest['BB_Lower']:.2f} - {latest['BB_Upper']:.2f}`\n"
            f"EMA 20/50 ระยะกลาง: {ema20_50}\n"
            f"EMA 50/200 ระยะยาว: {ema50_200}\n"
            f"OBV ล่าสุด: {obv_txt}\n"
            f"แนวรับ: `{support:.2f}` | แนวต้าน: `{resistance:.2f}`\n\n"
            f"*เพื่อเป็นข้อมูล ไม่ใช่คำแนะนำการลงทุน ระบบอ่านตลาดตามราคาและโวลุ่มจริง*\n\n"
            f"📝 **สรุปภาพรวม {symbol.upper()}:**\n{ai_response.text}"
        )
        
        return buf, analysis_text
    except Exception as e:
        return None, f"Error: {str(e)}"

# ===========================
# 📰 AI News Hunter
# ===========================
def fetch_hot_news():
    watchlist = ["AAPL", "TSLA", "PTT.BK"] 
    for symbol in watchlist:
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            if news:
                latest_news = news[0]
                prompt = f"ข่าวนี้ส่งผลกระทบต่อราคาหุ้น {symbol} อย่างรุนแรงหรือไม่? ตอบแค่ 'YES' หรือ 'NO': {latest_news['title']}"
                check = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                
                if "YES" in check.text.upper():
                    broadcast_msg = (
                        f"⚡️ **[APEXIFY HOT NEWS]** ⚡️\n\n"
                        f"🗞 {latest_news['title']}\n"
                        f"📌 หุ้น: #{symbol}\n"
                        f"🤖 ระบบตรวจพบข่าวสำคัญที่อาจกระทบราคา"
                    )
                    bot.send_message(ADMIN_ID, broadcast_msg)
        except:
            continue

# ===========================
# ⏰ Scheduler
# ===========================
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_hot_news, 'interval', hours=1) 
scheduler.start()

# ===========================
# 🤖 Handlers
# ===========================
@bot.message_handler(func=lambda message: True)
def handle_stock(message):
    user_id = message.chat.id
    if is_vip(user_id):
        symbol = message.text.upper()
        msg = bot.send_message(user_id, f"⚡️ Apexify กำลังประมวลผลอินดิเคเตอร์เชิงลึกสำหรับ {symbol}...")
        chart, analysis = get_advanced_analysis(symbol)
        
        bot.delete_message(chat_id=user_id, message_id=msg.message_id) # ลบข้อความกำลังโหลด
        
        if chart:
            bot.send_photo(user_id, chart, caption=analysis, parse_mode="Markdown")
        else:
            bot.reply_to(message, analysis)
    else:
        bot.reply_to(message, "🔒 สิทธิ์นี้เฉพาะสมาชิก VIP (199.-/เดือน) สนใจสมัครทักแอดมินครับ")

if __name__ == "__main__":
    init_db()
    print("⚡️ Apexify Bot is Online and Ready...")
    bot.infinity_polling()