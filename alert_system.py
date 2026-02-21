import time
import telebot
import requests 
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators

# 🌟 Import ฟังก์ชันดึง/ปิด การตั้งเตือนราคาจากฐานข้อมูลเพิ่มเข้ามา
from database import (get_all_active_symbols, get_users_watching, init_db, check_subscription, 
                      get_connection, log_alert, get_all_active_price_alerts, deactivate_price_alert)
import json
import xml.etree.ElementTree as ET 
from curl_cffi import requests as cffi_requests 

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
last_news_title = {}
sent_pro_news = set()

def send_alert_to_users(symbol, message, alert_type="tech"):
    users = get_users_watching(symbol)
    for user_id in users:
        role = check_subscription(user_id)
        if role != 'pro': continue
        try:
            full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
            bot.send_message(user_id, full_msg, parse_mode="Markdown", disable_web_page_preview=True)
            time.sleep(0.5) 
        except Exception: pass

def check_hot_news(symbol):
    try:
        is_thai_stock = symbol.endswith('.BK')
        search_term = symbol.replace('.BK', '')
        
        if is_thai_stock:
            url = f"https://news.google.com/rss/search?q={search_term}+หุ้น&hl=th&gl=TH&ceid=TH:th"
        else:
            url = f"https://news.google.com/rss/search?q={search_term}+stock&hl=en-US&gl=US&ceid=US:en"

        response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
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

            prompt = f"""
            วิเคราะห์ผลกระทบต่อหุ้น {symbol} จากพาดหัวข่าวนี้: "{title}"
            ตอบกลับในรูปแบบ JSON เท่านั้น:
            {{
                "sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL",
                "severity": "HIGH" หรือ "MEDIUM" หรือ "LOW",
                "reason": "สรุปผลกระทบต่อนักลงทุนแบบสั้นและกระชับที่สุด (ไม่เกิน 2 บรรทัด) เป็นภาษาไทย"
            }}
            """
            
            ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
            
            try:
                analysis = json.loads(result_text)
                if analysis.get('severity') == 'HIGH':
                    sentiment = analysis.get('sentiment', 'NEUTRAL')
                    reason = analysis.get('reason', 'ไม่มีคำอธิบายเพิ่มเติม')
                    
                    emoji_status = "🚀 BULLISH (เชิงบวก)" if sentiment == "BULLISH" else "🩸 BEARISH (เชิงลบ)" if sentiment == "BEARISH" else "⚪️ NEUTRAL (ปกติ)"
                    
                    msg = (
                        f"🗞 **ข่าว:** {title}\n"
                        f"🤖 **มุมมอง AI:** {emoji_status}\n"
                        f"💡 **วิเคราะห์:** {reason}\n\n"
                        f"🔗 [อ่านข่าวเต็มคลิกที่นี่]({link})"
                    )
                    
                    send_alert_to_users(symbol, msg, alert_type="news")
                    last_news_title[symbol] = title
                    
            except json.JSONDecodeError: pass
    except Exception: pass

def check_market_conditions():
    active_symbols = get_all_active_symbols()
    if not active_symbols: return
    
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
        except Exception: pass

def check_and_broadcast_pro_news(bot_instance):
    news_sources = [
        {"tag": "🇹🇭 **สรุปข่าวเด่นฝั่งไทย (PRO Exclusive)**", "url": "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+ตลาดหลักทรัพย์+OR+การลงทุน+OR+หุ้น&hl=th&gl=TH&ceid=TH:th"},
        {"tag": "🌍 **สรุปข่าวเด่นต่างประเทศ (PRO Exclusive)**", "url": "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+investing&hl=en-US&gl=US&ceid=US:en"}
    ]
    
    for source in news_sources:
        try:
            response = cffi_requests.get(source["url"], impersonate="chrome110", timeout=15)
            root = ET.fromstring(response.content)
            items = root.findall('.//item')[:3] 
            
            combined_msg = f"{source['tag']}\n\n"
            new_news_found = False
            
            for item in items:
                title_elem = item.find('title')
                link_elem = item.find('link')
                if title_elem is None: continue
                title = title_elem.text
                link = link_elem.text if link_elem is not None else ""
                
                if title not in sent_pro_news:
                    prompt = f"""
                    คุณคือนักวิเคราะห์การเงิน 
                    สรุปข่าวนี้ให้กระชับที่สุด: "{title}"
                    เน้นใจความและผลกระทบ (ไม่เกิน 2 บรรทัด) เป็นภาษาไทยเท่านั้น ห้ามยาวเด็ดขาด ห้ามใส่ลิงก์
                    """
                    try:
                        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        summary = ai_check.text.strip()
                        combined_msg += f"📰 [{title}]({link})\n💡 **สรุป:** {summary}\n\n"
                        sent_pro_news.add(title)
                        new_news_found = True
                    except Exception: pass
            
            if new_news_found:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
                pro_users = cur.fetchall()
                
                count = 0
                for pro in pro_users:
                    user_id = pro[0]
                    if check_subscription(user_id) == 'pro':
                        try:
                            bot_instance.send_message(user_id, combined_msg.strip(), parse_mode='Markdown', disable_web_page_preview=True)
                            count += 1
                            time.sleep(0.5) 
                        except Exception: pass
                            
                cur.close()
                conn.close()
                if count > 0: print(f"✅ ส่ง {source['tag']} ให้ PRO สำเร็จ {count} คน")
        except Exception: pass

# ==========================================
# 🌟 ระบบเช็คตั้งเตือนราคาส่วนตัว (Custom Price Alerts)
# ==========================================
def check_custom_price_alerts():
    alerts = get_all_active_price_alerts()
    if not alerts: return
    
    # ดึงรายชื่อหุ้นที่ต้องเช็คราคา (รวมไว้ไม่ให้เช็คซ้ำ)
    symbols_to_check = set([alert[2] for alert in alerts])
    current_prices = {}
    
    for sym in symbols_to_check:
        try:
            # ดึงราคาปัจจุบันโดยไม่เจเนอเรตกราฟ
            tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
            if not err and tech_data:
                current_prices[sym] = tech_data['price']
        except Exception:
            pass
            
    for alert in alerts:
        a_id, user_id, symbol, target_price, condition = alert
        if symbol not in current_prices: continue
        
        curr_price = current_prices[symbol]
        triggered = False
        
        if condition == 'above' and curr_price >= target_price:
            triggered = True
            cond_text = "ทะลุขึ้นเป้าหมายที่"
        elif condition == 'below' and curr_price <= target_price:
            triggered = True
            cond_text = "ร่วงลงมาแตะที่"
            
        if triggered:
            # ตรวจสอบอีกรอบว่าเป็น PRO หรือไม่
            role = check_subscription(user_id)
            if role == 'pro' or str(user_id) == ADMIN_ID:
                msg = (
                    f"🎯 **TARGET REACHED!** 🎯\n\n"
                    f"📌 หุ้น **{symbol}** ที่คุณตั้งเตือนไว้\n"
                    f"ตอนนี้ราคาได้ **{cond_text} {target_price:,.2f}** แล้วครับ!\n"
                    f"*(ราคาปัจจุบัน: {curr_price:,.2f})*\n\n"
                    f"👉 ระบบทำการปิดการแจ้งเตือนรายการนี้แล้ว หากต้องการตั้งใหม่พิมพ์ `/setalert`"
                )
                try:
                    bot.send_message(user_id, msg, parse_mode="Markdown")
                    deactivate_price_alert(a_id) # ปิดการแจ้งเตือนหลังส่งเสร็จ
                    time.sleep(0.5)
                except Exception:
                    pass
            else:
                # ถ้าหมดอายุ PRO แล้ว ให้ปิดการแจ้งเตือนทิ้งไปเลย
                deactivate_price_alert(a_id)

if __name__ == "__main__":
    init_db()
    print("🚀 Apexify Alert System (PRO Exclusive) is Running...")
    
    last_global_news_time = 0
    
    while True:
        current_time = time.time()
        
        # 🌟 เช็คข่าวมัดรวม ทุกๆ 4 ชั่วโมง (14400 วินาที)
        if current_time - last_global_news_time > 14400:
            check_and_broadcast_pro_news(bot)
            last_global_news_time = current_time
            
        # 🌟 เช็คกราฟเทคนิค (ทุก 5 นาที)
        check_market_conditions()
        
        # 🌟 เช็คราคาเป้าหมายส่วนตัว (ทุก 5 นาทีพร้อมกราฟ)
        check_custom_price_alerts()
        
        time.sleep(300)
