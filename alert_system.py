import time
import telebot
import yfinance as yf
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators
from database import get_all_active_symbols, get_users_watching, init_db
import json

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

import json # <--- อย่าลืมเพิ่ม import json ไว้ด้านบนสุดของไฟล์ (ใต้ import time)

def check_hot_news(symbol):
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        if news:
            latest_news = news[0]
            title = latest_news['title']
            link = latest_news.get('link', '#')

            # ถ้าเป็นข่าวเดิมที่เคยแจ้งเตือนไปแล้วให้ข้ามไป
            if symbol in last_news_title and last_news_title[symbol] == title:
                return

            # --- อัปเกรด Prompt ให้ AI วิเคราะห์ทิศทางและความรุนแรง ---
            prompt = f"""
            ในฐานะนักวิเคราะห์การเงินระดับโลก โปรดอ่านพาดหัวข่าวนี้: "{title}"
            และวิเคราะห์ผลกระทบต่อหุ้น {symbol} โดยตอบกลับในรูปแบบ JSON เท่านั้น ดังนี้:
            {{
                "sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL",
                "severity": "HIGH" หรือ "MEDIUM" หรือ "LOW",
                "reason": "คำอธิบายสั้นๆ 1-2 บรรทัดว่าทำไมข่าวนี้ถึงกระทบต่อราคาหุ้น"
            }}
            """
            
            ai_check = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            
            # คลีนข้อมูลและแปลงเป็น JSON
            result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
            
            try:
                analysis = json.loads(result_text)
                
                # ถ้าระดับความรุนแรงเป็น HIGH ให้ยิงแจ้งเตือนทันที
                if analysis.get('severity') == 'HIGH':
                    sentiment = analysis.get('sentiment', 'NEUTRAL')
                    reason = analysis.get('reason', 'ไม่มีคำอธิบายเพิ่มเติม')
                    
                    # เลือก Emoji ให้เข้ากับทิศทางตลาด
                    if sentiment == "BULLISH":
                        emoji_status = "🚀 BULLISH (ข่าวดี/เชิงบวกอย่างมาก)"
                    elif sentiment == "BEARISH":
                        emoji_status = "🩸 BEARISH (ข่าวร้าย/เชิงลบอย่างมาก)"
                    else:
                        emoji_status = "⚪️ NEUTRAL (ส่งผลกระทบแต่ยังไม่แน่ชัด)"
                    
                    msg = (
                        f"🚨 **BREAKING NEWS ALERT!** 🚨\n\n"
                        f"📌 **หุ้น:** #{symbol}\n"
                        f"🗞 **พาดหัวข่าว:** {title}\n\n"
                        f"🤖 **AI สแกนข่าวด่วน:**\n"
                        f"ทิศทางแนวโน้ม: {emoji_status}\n"
                        f"💡 **เหตุผล:** {reason}\n\n"
                        f"🔗 [อ่านข่าวฉบับเต็มคลิกที่นี่]({link})"
                    )
                    
                    # ส่งแจ้งเตือนหาทุกคนที่ตั้ง Watchlist หุ้นตัวนี้ไว้
                    send_alert_to_users(symbol, msg)
                    
                    # บันทึกข่าวนี้ไว้ จะได้ไม่แจ้งเตือนซ้ำ
                    last_news_title[symbol] = title
                    
            except json.JSONDecodeError:
                print(f"❌ JSON Parse Error สำหรับข่าว {symbol}")

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