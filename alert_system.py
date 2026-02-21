import time
import telebot
import requests 
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators

# 🌟 Import ระบบฐานข้อมูลทั้งหมด
from database import get_all_active_symbols, get_users_watching, init_db, check_subscription, get_connection, log_alert
import json
import xml.etree.ElementTree as ET # 🌟 ใช้ตัวอ่าน XML ที่เสถียรที่สุด

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
last_news_title = {}
sent_pro_news = set()

# ==========================================
# 🌟 ฟังก์ชันส่งแจ้งเตือน (ส่งให้เฉพาะ PRO)
# ==========================================
def send_alert_to_users(symbol, message, alert_type="tech"):
    """
    alert_type: "tech" (กราฟ RSI/EMA), "news" (ข่าวด่วนรายตัว)
    🌟 สิทธิพิเศษนี้สงวนไว้ให้ระดับ PRO เท่านั้น
    """
    users = get_users_watching(symbol)
    for user_id in users:
        role = check_subscription(user_id)
        
        # 👑 กรองความสำคัญ: ให้เฉพาะระดับ PRO (Platinum) เท่านั้น
        if role != 'pro':
            continue
            
        try:
            full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
            bot.send_message(user_id, full_msg, parse_mode="Markdown")
            print(f"✅ Sent {alert_type} alert for {symbol} to User {user_id} (PRO)")
            time.sleep(0.5) 
        except Exception as e:
            print(f"❌ Failed to send to {user_id}: {e}")

# ==========================================
# 🌟 ระบบสแกนข่าวหุ้นรายตัว (AI แปลและวิเคราะห์ผลกระทบ)
# ==========================================
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

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        if items:
            title_elem = items[0].find('title')
            link_elem = items[0].find('link')
            if title_elem is None: return
            
            title = title_elem.text
            link = link_elem.text if link_elem is not None else f"https://news.google.com/search?q={search_term}"

            if not title: return
            if symbol in last_news_title and last_news_title[symbol] == title: return

            # 🌟 ให้ AI แปลและวิเคราะห์ผลกระทบเป็นภาษาไทย
            prompt = f"""
            ในฐานะนักวิเคราะห์การเงินระดับโลก โปรดอ่านพาดหัวข่าวนี้: "{title}"
            และวิเคราะห์ผลกระทบต่อหุ้น {symbol} โดยตอบกลับในรูปแบบ JSON เท่านั้น ดังนี้:
            {{
                "sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL",
                "severity": "HIGH" หรือ "MEDIUM" หรือ "LOW",
                "reason": "แปลข่าวและอธิบายสั้นๆ 1-2 บรรทัดว่าทำไมข่าวนี้ถึงกระทบต่อราคาหุ้น (ตอบเป็นภาษาไทยเท่านั้น)"
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
                        f"🤖 **AI แปลและวิเคราะห์ด่วน:**\n"
                        f"ทิศทางแนวโน้ม: {emoji_status}\n"
                        f"💡 **เหตุผล:** {reason}\n\n"
                        f"🔗 [อ่านข่าวฉบับเต็มคลิกที่นี่]({link})"
                    )
                    
                    send_alert_to_users(symbol, msg, alert_type="news")
                    last_news_title[symbol] = title
                    
            except json.JSONDecodeError:
                pass

    except Exception as e:
        pass

# ==========================================
# 🌟 ระบบแจ้งเตือนกราฟเทคนิค
# ==========================================
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
                msg = f"🟢 **RSI OVERSOLD ({current_rsi:.2f})**\nราคาร่วงหนัก เข้าเขตขายมากเกินไป อาจมีเด้งรีบาวด์! (ราคาปัจจุบัน: {price:.2f})"
            elif current_rsi > 75:
                rsi_condition = 'overbought'
                msg = f"🔴 **RSI OVERBOUGHT ({current_rsi:.2f})**\nราคาพุ่งแรง เข้าเขตซื้อมากเกินไป ระวังแรงเทขาย! (ราคาปัจจุบัน: {price:.2f})"

            if rsi_condition != 'normal' and rsi_condition != last_alert_state[symbol]['rsi']:
                send_alert_to_users(symbol, msg, alert_type="tech")
                log_alert(symbol, f"RSI_{rsi_condition.upper()}", price) 
                last_alert_state[symbol]['rsi'] = rsi_condition
            elif rsi_condition == 'normal':
                last_alert_state[symbol]['rsi'] = 'normal'

            # --- EMA Cross ---
            cross_condition = 'normal'
            if ema50 > ema200 and (ema50 / ema200) < 1.01:
                cross_condition = 'golden_cross'
                msg = f"✨ **GOLDEN CROSS DETECTED** ✨\nเส้น EMA50 ตัดขึ้นเหนือ EMA200 สัญญาณกลับตัวเป็นขาขึ้นระยะยาว! (ราคาปัจจุบัน: {price:.2f})"
            elif ema50 < ema200 and (ema200 / ema50) < 1.01:
                cross_condition = 'death_cross'
                msg = f"💀 **DEATH CROSS DETECTED** 💀\nเส้น EMA50 ตัดลงต่ำกว่า EMA200 สัญญาณกลับตัวเป็นขาลงระยะยาว! (ราคาปัจจุบัน: {price:.2f})"

            if cross_condition != 'normal' and cross_condition != last_alert_state[symbol]['cross']:
                send_alert_to_users(symbol, msg, alert_type="tech")
                log_alert(symbol, f"EMA_{cross_condition.upper()}", price) 
                last_alert_state[symbol]['cross'] = cross_condition

            # --- Breakout ---
            breakout_condition = 'normal'
            if price > resistance:
                breakout_condition = 'break_res'
                msg = f"🚀 **RESISTANCE BREAKOUT**\nราคาทะลุแนวต้านสำคัญที่ {resistance:.2f} ขึ้นไปได้แล้ว! จับตาดู Volume! (ราคาปัจจุบัน: {price:.2f})"
            elif price < support:
                breakout_condition = 'break_sup'
                msg = f"🩸 **SUPPORT BROKEN**\nราคาหลุดแนวรับสำคัญที่ {support:.2f} ลงมาแล้ว! ระวังแรงเทขาย! (ราคาปัจจุบัน: {price:.2f})"

            if breakout_condition != 'normal' and breakout_condition != last_alert_state[symbol]['breakout']:
                send_alert_to_users(symbol, msg, alert_type="tech")
                log_alert(symbol, f"BREAKOUT_{breakout_condition.upper()}", price) 
                last_alert_state[symbol]['breakout'] = breakout_condition
            elif breakout_condition == 'normal':
                last_alert_state[symbol]['breakout'] = 'normal'

            time.sleep(2)

        except Exception as e:
            pass

# ==========================================
# 🌟 ระบบบรอดแคสต์ข่าวด่วนภาพรวมตลาด (ให้เฉพาะ PRO)
# ==========================================
def check_and_broadcast_pro_news(bot_instance):
    """เช็คข่าวด่วน 2 โซน แล้วให้ AI แปลไทย/สรุป ส่งให้ลูกค้า PRO เท่านั้น"""
    news_sources = [
        {"tag": "🇹🇭 **Thai Market News (PRO Exclusive)** 🇹🇭", "url": "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+ตลาดหลักทรัพย์+OR+การลงทุน+OR+หุ้น&hl=th&gl=TH&ceid=TH:th"},
        {"tag": "🌍 **Global Market News (PRO Exclusive)** 🌍", "url": "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+investing&hl=en-US&gl=US&ceid=US:en"}
    ]
    
    for source in news_sources:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(source["url"], headers=headers, timeout=15)
            root = ET.fromstring(response.content)
            items = root.findall('.//item')[:2] 
            
            for item in items:
                title_elem = item.find('title')
                if title_elem is None: continue
                title = title_elem.text
                
                if title not in sent_pro_news:
                    prompt = f"""
                    คุณคือนักวิเคราะห์ข่าวการเงินระดับเชี่ยวชาญ 
                    นี่คือพาดหัวข่าวเศรษฐกิจและการลงทุนล่าสุด (อาจเป็นภาษาไทยหรืออังกฤษ): "{title}"
                    
                    1. แปลข่าวและสรุปให้สั้น กระชับ จับใจความสำคัญว่ากระทบนักลงทุนอย่างไร (ตอบเป็นภาษาไทยเท่านั้น)
                    2. พิมพ์แค่เนื้อหาข่าวที่สรุปแล้วอย่างเดียว ห้ามใส่ลิงก์
                    """
                    try:
                        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        summary = ai_check.text.strip()
                        news_message = f"{source['tag']}\n\n📰 **พาดหัวข่าว:** {title}\n🤖 **AI แปลและวิเคราะห์:** {summary}"
                        
                        conn = get_connection()
                        cur = conn.cursor()
                        # 👑 ดึงเฉพาะลูกค้า PRO
                        cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
                        pro_users = cur.fetchall()
                        
                        count = 0
                        for pro in pro_users:
                            user_id = pro[0]
                            if check_subscription(user_id) == 'pro':
                                try:
                                    bot_instance.send_message(user_id, news_message, parse_mode='Markdown')
                                    count += 1
                                    time.sleep(0.5) 
                                except Exception:
                                    pass
                                    
                        cur.close()
                        conn.close()
                        if count > 0: print(f"✅ ส่งสรุปข่าว {source['tag']} ให้ PRO สำเร็จ {count} คน")
                        sent_pro_news.add(title)
                        break
                    except Exception as ai_e:
                        pass
        except Exception as e:
            pass

if __name__ == "__main__":
    init_db()
    print("🚀 Apexify Alert System (PRO Exclusive) is Running...")
    while True:
        check_and_broadcast_pro_news(bot)
        check_market_conditions()
        time.sleep(300)
