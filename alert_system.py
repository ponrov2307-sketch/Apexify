import time
import telebot
import requests 
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators
# 🌟 Import ระบบเช็กบทบาทลูกค้า (Role) 
from database import get_all_active_symbols, get_users_watching, init_db, check_subscription, get_connection
import json

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
last_news_title = {}
sent_vip_news = set()

# 🌟 ฟังก์ชันส่งแจ้งเตือน ที่ฉลาดพอจะกรองระดับลูกค้า VIP / PRO
def send_alert_to_users(symbol, message, alert_type="tech"):
    """
    alert_type: 
    - "tech" (กราฟ RSI/EMA) ส่งให้ PRO เท่านั้น
    - "news" (ข่าวด่วน) ส่งให้ทั้ง VIP และ PRO
    """
    users = get_users_watching(symbol)
    for user_id in users:
        role = check_subscription(user_id)
        
        # 👑 กรองความสำคัญ: Technical Alert ให้เฉพาะระดับ PRO
        if alert_type == "tech" and role != 'pro':
            continue
            
        # 💎 กรองความสำคัญ: News Alert ให้ VIP และ PRO
        if alert_type == "news" and role not in ['vip', 'pro']:
            continue
            
        try:
            full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
            bot.send_message(user_id, full_msg, parse_mode="Markdown")
            print(f"✅ Sent {alert_type} alert for {symbol} to User {user_id} ({role.upper()})")
            time.sleep(0.5) 
        except Exception as e:
            print(f"❌ Failed to send to {user_id}: {e}")

def check_hot_news(symbol):
    try:
        is_thai_stock = symbol.endswith('.BK')
        search_term = symbol.replace('.BK', '')
        
        if is_thai_stock:
            url = f"https://news.google.com/rss/search?q={search_term}+หุ้น&hl=th&gl=TH&ceid=TH:th"
            news_type = "พาดหัวข่าวไทย"
        else:
            url = f"https://news.google.com/rss/search?q={search_term}+stock&hl=en-US&gl=US&ceid=US:en"
            news_type = "พาดหัวข่าว Global"

        response = cffi_requests.get(url, impersonate="chrome110", timeout=10)
        soup = BeautifulSoup(response.content, "xml")
        
        items = soup.find_all("item")
        if items:
            title = items[0].title.text
            link_tag = items[0].find('link')
            link = link_tag.next_sibling.strip() if link_tag and link_tag.next_sibling else f"https://news.google.com/search?q={search_term}"

            if not title: return
            if symbol in last_news_title and last_news_title[symbol] == title: return

            prompt = f"""
            ในฐานะนักวิเคราะห์การเงินระดับโลก โปรดอ่านพาดหัวข่าวนี้: "{title}"
            และวิเคราะห์ผลกระทบต่อหุ้น {symbol} โดยตอบกลับในรูปแบบ JSON เท่านั้น ดังนี้:
            {{
                "sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL",
                "severity": "HIGH" หรือ "MEDIUM" หรือ "LOW",
                "reason": "คำอธิบายสั้นๆ 1-2 บรรทัดว่าทำไมข่าวนี้ถึงกระทบต่อราคาหุ้น (ตอบเป็นภาษาไทย)"
            }}
            """
            
            ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
            
            try:
                analysis = json.loads(result_text)
                if analysis.get('severity') == 'HIGH':
                    sentiment = analysis.get('sentiment', 'NEUTRAL')
                    reason = analysis.get('reason', 'ไม่มีคำอธิบายเพิ่มเติม')
                    
                    emoji_status = "🚀 BULLISH" if sentiment == "BULLISH" else "🩸 BEARISH" if sentiment == "BEARISH" else "⚪️ NEUTRAL"
                    
                    msg = (
                        f"📌 **หุ้น:** #{symbol}\n"
                        f"🗞 **{news_type}:** {title}\n\n"
                        f"🤖 **AI สแกนข่าวด่วน:**\n"
                        f"ทิศทางแนวโน้ม: {emoji_status}\n"
                        f"💡 **เหตุผล:** {reason}\n\n"
                        f"🔗 [อ่านข่าวฉบับเต็มคลิกที่นี่]({link})"
                    )
                    
                    # 🌟 ส่งแบบ "news" (VIP และ PRO ได้รับ)
                    send_alert_to_users(symbol, msg, alert_type="news")
                    last_news_title[symbol] = title
                    
            except json.JSONDecodeError:
                pass

    except Exception as e:
        print(f"⚠️ News Error {symbol}: {e}")

def check_market_conditions():
    active_symbols = get_all_active_symbols()
    if not active_symbols:
        print(f"[{time.strftime('%H:%M:%S')}] 💤 ไม่มีหุ้นใน Watchlist...")
        return

    print(f"🔍 [{time.strftime('%H:%M:%S')}] Scanning {len(active_symbols)} symbols...")
    
    for symbol in active_symbols:
        try:
            check_hot_news(symbol)

            tech_data, _, error = calculate_technical_indicators(symbol, generate_chart=False)
            if error or not tech_data: continue

            current_rsi = tech_data['rsi']
            ema50 = tech_data['ema50']
            ema200 = tech_data['ema200']
            price = tech_data['price']
            resistance = tech_data['resistance']
            support = tech_data['support']
            
            if symbol not in last_alert_state:
                last_alert_state[symbol] = {'rsi': 'normal', 'cross': 'normal', 'breakout': 'normal'}

            # --- RSI ---
            rsi_condition = 'normal'
            if current_rsi < 30:
                rsi_condition = 'oversold'
                msg = f"🟢 **RSI OVERSOLD ({current_rsi:.2f})**\nราคาร่วงหนัก เข้าเขตขายมากเกินไป อาจมีเด้งรีบาวด์! (ราคา: {price:.2f})"
            elif current_rsi > 75:
                rsi_condition = 'overbought'
                msg = f"🔴 **RSI OVERBOUGHT ({current_rsi:.2f})**\nราคาพุ่งแรง เข้าเขตซื้อมากเกินไป ระวังแรงเทขาย! (ราคา: {price:.2f})"

            if rsi_condition != 'normal' and rsi_condition != last_alert_state[symbol]['rsi']:
                # 🌟 ส่งแบบ "tech" (PRO ได้รับเท่านั้น)
                send_alert_to_users(symbol, msg, alert_type="tech")
                last_alert_state[symbol]['rsi'] = rsi_condition
            elif rsi_condition == 'normal':
                last_alert_state[symbol]['rsi'] = 'normal'

            # --- EMA Cross ---
            cross_condition = 'normal'
            if ema50 > ema200 and (ema50 / ema200) < 1.01:
                cross_condition = 'golden_cross'
                msg = f"✨ **GOLDEN CROSS DETECTED** ✨\nเส้น EMA50 ตัดขึ้นเหนือ EMA200 สัญญาณกลับตัวเป็นขาขึ้นระยะยาว!"
            elif ema50 < ema200 and (ema200 / ema50) < 1.01:
                cross_condition = 'death_cross'
                msg = f"💀 **DEATH CROSS DETECTED** 💀\nเส้น EMA50 ตัดลงต่ำกว่า EMA200 สัญญาณกลับตัวเป็นขาลงระยะยาว!"

            if cross_condition != 'normal' and cross_condition != last_alert_state[symbol]['cross']:
                send_alert_to_users(symbol, msg, alert_type="tech")
                last_alert_state[symbol]['cross'] = cross_condition

            # --- Breakout ---
            breakout_condition = 'normal'
            if price > resistance:
                breakout_condition = 'break_res'
                msg = f"🚀 **RESISTANCE BREAKOUT**\nราคาทะลุแนวต้านสำคัญที่ {resistance:.2f} ขึ้นไปได้แล้ว! จับตาดู Volume!"
            elif price < support:
                breakout_condition = 'break_sup'
                msg = f"🩸 **SUPPORT BROKEN**\nราคาหลุดแนวรับสำคัญที่ {support:.2f} ลงมาแล้ว! ระวังแรงเทขาย!"

            if breakout_condition != 'normal' and breakout_condition != last_alert_state[symbol]['breakout']:
                send_alert_to_users(symbol, msg, alert_type="tech")
                last_alert_state[symbol]['breakout'] = breakout_condition
            elif breakout_condition == 'normal':
                last_alert_state[symbol]['breakout'] = 'normal'

            time.sleep(2)

        except Exception as e:
            pass

def check_and_broadcast_vip_news(bot_instance):
    """เช็คข่าวด่วน 2 โซน แล้วส่งให้ลูกค้า VIP และ PRO"""
    news_sources = [
        {"tag": "🇹🇭 **Thai Market News (VIP)** 🇹🇭", "url": "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+ตลาดหลักทรัพย์+OR+การลงทุน+OR+หุ้น&hl=th&gl=TH&ceid=TH:th"},
        {"tag": "🌍 **Global Market News (VIP)** 🌍", "url": "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+investing&hl=en-US&gl=US&ceid=US:en"}
    ]
    
    for source in news_sources:
        try:
            response = cffi_requests.get(source["url"], impersonate="chrome110", timeout=15)
            soup = BeautifulSoup(response.content, "xml")
            items = soup.find_all("item")[:2] 
            
            for item in items:
                title = item.title.text
                if title not in sent_vip_news:
                    prompt = f"""
                    คุณคือนักวิเคราะห์ข่าวการเงินระดับเชี่ยวชาญ 
                    นี่คือพาดหัวข่าวเศรษฐกิจและการลงทุนล่าสุด: "{title}"
                    
                    1. สรุปข่าวนี้ให้สั้น กระชับ จับใจความสำคัญว่ากระทบนักลงทุนอย่างไร 
                    2. พิมพ์แค่เนื้อหาข่าวที่สรุปแล้วอย่างเดียว ห้ามใส่ลิงก์
                    3. ตอบเป็นภาษาไทยเท่านั้น
                    """
                    try:
                        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        summary = ai_check.text.strip()
                        news_message = f"{source['tag']}\n\n{summary}"
                        
                        # 🌟 ดึงลูกค้าที่เป็น VIP และ PRO ทั้งหมด
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("SELECT user_id FROM users WHERE role IN ('vip', 'pro')")
                        vip_users = cur.fetchall()
                        
                        count = 0
                        for vip in vip_users:
                            user_id = vip[0]
                            # รีเช็กวันหมดอายุอีกครั้ง
                            if check_subscription(user_id) in ['vip', 'pro']:
                                try:
                                    bot_instance.send_message(user_id, news_message, parse_mode='Markdown')
                                    count += 1
                                    time.sleep(0.5) 
                                except Exception:
                                    pass
                                    
                        cur.close()
                        conn.close()
                        if count > 0: print(f"✅ ส่งสรุปข่าว {source['tag']} ให้ VIP/PRO สำเร็จ {count} คน: {title}")
                        sent_vip_news.add(title)
                        break
                    except Exception as ai_e:
                        pass
        except Exception as e:
            pass

if __name__ == "__main__":
    init_db()
    print("🚀 Apexify Alert System (PRO & VIP) is Running...")
    while True:
        check_and_broadcast_vip_news(bot)
        check_market_conditions()
        time.sleep(300) 
