import time
import telebot
import yfinance as yf
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators

# ตั้งค่า Bot และ AI
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

WATCHLIST = ["BTC-USD", "ETH-USD", "NVDA", "TSLA", "PTT.BK"]

# เก็บสถานะเพื่อกันแจ้งเตือนซ้ำรัวๆ
last_alert_state = {}
last_news_title = {}

def send_alert(symbol, message):
    try:
        full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
        bot.send_message(ADMIN_ID, full_msg, parse_mode="Markdown")
        print(f"✅ Sent alert for {symbol}")
    except Exception as e:
        print(f"❌ Failed to send alert: {e}")

def check_hot_news(symbol):
    """ฟังก์ชันให้ AI สแกนข่าวและประเมินผลกระทบ"""
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        if news:
            latest_news = news[0]
            title = latest_news['title']
            link = latest_news.get('link', '#')

            # ถ้าเป็นข่าวเดิมที่เคยแจ้งเตือนไปแล้วให้ข้าม
            if symbol in last_news_title and last_news_title[symbol] == title:
                return

            # ให้ Gemini วิเคราะห์พาดหัวข่าว
            prompt = f"ในฐานะนักวิเคราะห์ ข่าวนี้ส่งผลกระทบต่อราคาหุ้น {symbol} อย่างมีนัยสำคัญรุนแรงหรือไม่? ตอบแค่ 'YES' หรือ 'NO' เท่านั้น: {title}"
            ai_check = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            
            if "YES" in ai_check.text.upper():
                msg = f"🗞 **BREAKING NEWS!**\n\nหัวข้อ: {title}\n🤖 **AI ประเมิน:** ข่าวนี้อาจส่งผลกระทบแรงต่อราคา!\n🔗 [อ่านข่าวเต็มคลิกที่นี่]({link})"
                send_alert(symbol, msg)
                last_news_title[symbol] = title # จำข่าวนี้ไว้ จะได้ไม่เตือนซ้ำ
    except Exception as e:
        print(f"⚠️ News Error {symbol}: {e}")

def check_market_conditions():
    print(f"🔍 [{time.strftime('%H:%M:%S')}] Scanning market & news...")
    
    for symbol in WATCHLIST:
        try:
            # 1. ให้นักสืบ AI เช็คข่าวด่วนก่อน
            check_hot_news(symbol)

            # 2. ดึงข้อมูลเทคนิค
            tech_data, _, error = calculate_technical_indicators(symbol)
            if error or not tech_data:
                continue

            current_rsi = tech_data['rsi']
            ema50 = tech_data['ema50']
            ema200 = tech_data['ema200']
            price = tech_data['price']
            resistance = tech_data['resistance']
            support = tech_data['support']
            
            if symbol not in last_alert_state:
                last_alert_state[symbol] = {'rsi': 'normal', 'cross': 'normal', 'breakout': 'normal'}

            # --- เช็ค RSI ---
            rsi_condition = 'normal'
            if current_rsi < 30:
                rsi_condition = 'oversold'
                msg = f"🟢 **RSI OVERSOLD ({current_rsi:.2f})**\nราคาร่วงหนัก เข้าเขตขายมากเกินไป อาจมีเด้งรีบาวด์! (ราคา: {price:.2f})"
            elif current_rsi > 75:
                rsi_condition = 'overbought'
                msg = f"🔴 **RSI OVERBOUGHT ({current_rsi:.2f})**\nราคาพุ่งแรง เข้าเขตซื้อมากเกินไป ระวังแรงเทขาย! (ราคา: {price:.2f})"

            if rsi_condition != 'normal' and rsi_condition != last_alert_state[symbol]['rsi']:
                send_alert(symbol, msg)
                last_alert_state[symbol]['rsi'] = rsi_condition
            elif rsi_condition == 'normal':
                last_alert_state[symbol]['rsi'] = 'normal'

            # --- เช็ค Breakout แนวรับ-แนวต้าน (ฟีเจอร์ใหม่) ---
            breakout_condition = 'normal'
            # ถ้าราคาปัจจุบัน ทะลุแนวต้าน 20 วันล่าสุด
            if price > resistance:
                breakout_condition = 'break_res'
                msg = f"🚀 **RESISTANCE BREAKOUT**\nราคาทะลุแนวต้านสำคัญที่ {resistance:.2f} ขึ้นไปได้แล้ว! (ราคาปัจจุบัน: {price:.2f}) จับตาดู Volume!"
            # ถ้าราคาปัจจุบัน หลุดแนวรับ 20 วันล่าสุด
            elif price < support:
                breakout_condition = 'break_sup'
                msg = f"🩸 **SUPPORT BROKEN**\nราคาหลุดแนวรับสำคัญที่ {support:.2f} ลงมาแล้ว! (ราคาปัจจุบัน: {price:.2f}) ระวังแรงเทขาย!"

            if breakout_condition != 'normal' and breakout_condition != last_alert_state[symbol]['breakout']:
                send_alert(symbol, msg)
                last_alert_state[symbol]['breakout'] = breakout_condition
            elif breakout_condition == 'normal':
                last_alert_state[symbol]['breakout'] = 'normal'

            time.sleep(2) # พัก 2 วินาทีกันโดนแบน API

        except Exception as e:
            print(f"⚠️ Error checking {symbol}: {e}")

if __name__ == "__main__":
    print("🚀 Apexify Alert System with News Hunter is Running...")
    send_alert("SYSTEM", "อัปเกรดระบบเสร็จสิ้น: AI News Hunter 🗞 และ Breakout Alert 🚀 พร้อมทำงานครับ!")
    while True:
        check_market_conditions()
        time.sleep(300) # ตรวจสอบทุกๆ 5 นาที