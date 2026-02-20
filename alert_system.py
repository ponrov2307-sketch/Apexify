import time
import telebot
import yfinance as yf
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators
from database import get_all_active_symbols, get_users_watching

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
last_news_title = {}

def send_alert_to_users(symbol, message):
    """ส่งข้อความหาทุกคนที่มีหุ้นตัวนี้ในลิสต์"""
    users = get_users_watching(symbol)
    for user_id in users:
        try:
            full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
            bot.send_message(user_id, full_msg, parse_mode="Markdown")
            print(f"✅ Sent alert for {symbol} to User {user_id}")
            time.sleep(0.5) # พักกันสแปม Telegram
        except Exception as e:
            print(f"❌ Failed to send to {user_id}: {e}")

def check_hot_news(symbol):
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        if news:
            latest_news = news[0]
            title = latest_news['title']
            link = latest_news.get('link', '#')

            if symbol in last_news_title and last_news_title[symbol] == title:
                return

            prompt = f"ในฐานะนักวิเคราะห์ ข่าวนี้ส่งผลกระทบต่อราคาหุ้น {symbol} อย่างมีนัยสำคัญรุนแรงหรือไม่? ตอบแค่ 'YES' หรือ 'NO' เท่านั้น: {title}"
            ai_check = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            
            if "YES" in ai_check.text.upper():
                msg = f"🗞 **BREAKING NEWS!**\n\nหัวข้อ: {title}\n🤖 **AI ประเมิน:** ข่าวนี้อาจส่งผลกระทบแรงต่อราคา!\n🔗 [อ่านข่าวเต็มคลิกที่นี่]({link})"
                send_alert_to_users(symbol, msg)
                last_news_title[symbol] = title
    except Exception as e:
        print(f"⚠️ News Error {symbol}: {e}")

def check_market_conditions():
    active_symbols = get_all_active_symbols()
    
    if not active_symbols:
        print(f"[{time.strftime('%H:%M:%S')}] 💤 ไม่มีหุ้นใน Watchlist รอผู้ใช้งานเพิ่มข้อมูล...")
        return

    print(f"🔍 [{time.strftime('%H:%M:%S')}] Scanning {len(active_symbols)} symbols...")
    
    for symbol in active_symbols:
        try:
            check_hot_news(symbol)

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
                send_alert_to_users(symbol, msg)
                last_alert_state[symbol]['rsi'] = rsi_condition
            elif rsi_condition == 'normal':
                last_alert_state[symbol]['rsi'] = 'normal'

            # --- เช็ค EMA Cross ---
            cross_condition = 'normal'
            if ema50 > ema200 and (ema50 / ema200) < 1.01:
                cross_condition = 'golden_cross'
                msg = f"✨ **GOLDEN CROSS DETECTED** ✨\nเส้น EMA50 ตัดขึ้นเหนือ EMA200 สัญญาณกลับตัวเป็นขาขึ้นระยะยาว!"
            elif ema50 < ema200 and (ema200 / ema50) < 1.01:
                cross_condition = 'death_cross'
                msg = f"💀 **DEATH CROSS DETECTED** 💀\nเส้น EMA50 ตัดลงต่ำกว่า EMA200 สัญญาณกลับตัวเป็นขาลงระยะยาว!"

            if cross_condition != 'normal' and cross_condition != last_alert_state[symbol]['cross']:
                send_alert_to_users(symbol, msg)
                last_alert_state[symbol]['cross'] = cross_condition

            # --- เช็ค Breakout ---
            breakout_condition = 'normal'
            if price > resistance:
                breakout_condition = 'break_res'
                msg = f"🚀 **RESISTANCE BREAKOUT**\nราคาทะลุแนวต้านสำคัญที่ {resistance:.2f} ขึ้นไปได้แล้ว! (ราคาปัจจุบัน: {price:.2f}) จับตาดู Volume!"
            elif price < support:
                breakout_condition = 'break_sup'
                msg = f"🩸 **SUPPORT BROKEN**\nราคาหลุดแนวรับสำคัญที่ {support:.2f} ลงมาแล้ว! (ราคาปัจจุบัน: {price:.2f}) ระวังแรงเทขาย!"

            if breakout_condition != 'normal' and breakout_condition != last_alert_state[symbol]['breakout']:
                send_alert_to_users(symbol, msg)
                last_alert_state[symbol]['breakout'] = breakout_condition
            elif breakout_condition == 'normal':
                last_alert_state[symbol]['breakout'] = 'normal'

            time.sleep(2)

        except Exception as e:
            print(f"⚠️ Error checking {symbol}: {e}")

if __name__ == "__main__":
    print("🚀 Apexify Alert System with News Hunter & Personal Watchlist is Running...")
    while True:
        check_market_conditions()
        time.sleep(300) # ตรวจสอบทุกๆ 5 นาที