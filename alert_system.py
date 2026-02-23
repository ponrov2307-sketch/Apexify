import time
from datetime import datetime, timedelta
import telebot
import requests 
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators

from database import (get_all_active_symbols, get_users_watching, init_db, check_subscription, 
                      get_connection, log_alert, get_all_active_price_alerts, deactivate_price_alert)
import json
import xml.etree.ElementTree as ET 
import yfinance as yf
from curl_cffi import requests as cffi_requests 

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
sent_pro_news = set() # 🌟 เก็บประวัติข่าวที่เคยส่งไปแล้วเพื่อกันส่งซ้ำ
sent_stock_news_history = {} 
sent_xd_alerts = set()

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

# ==========================================
# 🌟 ระบบสแกนข่าวหุ้นรายตัว (เฉพาะข่าวด่วนจริงๆ)
# ==========================================
def check_hot_news(symbol):
    try:
        is_thai_stock = symbol.endswith('.BK')
        search_term = symbol.replace('.BK', '')
        
        if is_thai_stock:
            url = f"https://news.google.com/rss/search?q={search_term}+หุ้น+when:1d&hl=th&gl=TH&ceid=TH:th"
        else:
            url = f"https://news.google.com/rss/search?q={search_term}+stock+when:1d&hl=en-US&gl=US&ceid=US:en"

        response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        if items:
            title_elem = items[0].find('title')
            link_elem = items[0].find('link')
            if title_elem is None: return
            
            title = title_elem.text.strip()
            link = link_elem.text if link_elem is not None else f"https://news.google.com/search?q={search_term}"

            if not title: return
            
            if symbol not in sent_stock_news_history:
                sent_stock_news_history[symbol] = set()
            if title in sent_stock_news_history[symbol]:
                return

            prompt = f"""
            วิเคราะห์ผลกระทบต่อหุ้น {symbol} จากพาดหัวข่าวนี้: "{title}"
            ตอบกลับในรูปแบบ JSON เท่านั้น โดยพิจารณาอย่างเข้มงวด:
            {{
                "sentiment": "BULLISH" หรือ "BEARISH" หรือ "NEUTRAL",
                "severity": "HIGH" (เฉพาะข่าวด่วนที่มีผลกระทบรุนแรงต่อราคาหุ้นจริงๆ เท่านั้น นอกนั้นให้ตอบ LOW),
                "reason": "วิเคราะห์ผลกระทบสั้นๆ จับใจความ 1 ประโยค (ภาษาไทย)"
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
                        f"🗞 **ข่าวด่วน:** {title}\n"
                        f"🤖 **มุมมอง Apexify:** {emoji_status}\n"
                        f"💡 **วิเคราะห์:** {reason}\n\n"
                        f"🔗 [อ่านข่าวเต็มคลิกที่นี่]({link})"
                    )
                    
                    send_alert_to_users(symbol, msg, alert_type="news")
                    sent_stock_news_history[symbol].add(title) 
                    
                    if len(sent_stock_news_history[symbol]) > 50:
                        sent_stock_news_history[symbol].clear()
                        
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

# ==========================================
# 🌟 ฟังก์ชันดึงข่าวรวมจากทุกสำนัก (เพื่อส่งให้ AI วิเคราะห์)
# ==========================================
def get_fresh_global_news():
    urls = [
        # 1. แหล่งข่าว Google News (เจาะจง 24 ชม. ล่าสุด)
        "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+ทองคำ+OR+คริปโต+OR+น้ำมัน+when:1d&hl=th&gl=TH&ceid=TH:th",
        "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+gold+OR+crypto+OR+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
        
        # 2. แหล่งข่าวสายตรง Investing.com (ตลาดหุ้น, คริปโต, สินทรัพย์โภคภัณฑ์)
        "https://www.investing.com/rss/news_25.rss",        # ข่าวตลาดหุ้นโลก (Equities)
        "https://www.investing.com/rss/news_301.rss",       # ข่าวคริปโต (Cryptocurrency)
        "https://www.investing.com/rss/market_overview.rss" # ภาพรวมตลาดและเศรษฐกิจ (Market Overview)
    ]
    news_list = []
    for url in urls:
        try:
            # ใช้ curl_cffi พรางตัวเป็น Chrome เพื่อทะลุบล็อกการดึงข่าว
            response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
            root = ET.fromstring(response.content)
            
            # ดึงมาสำนักละ 10-15 ข่าวล่าสุดมากองรวมกันให้ AI คัดอีกที
            for item in root.findall('.//item')[:15]: 
                title_elem = item.find('title')
                link_elem = item.find('link')
                
                if title_elem is not None and link_elem is not None:
                    title = title_elem.text.strip()
                    link = link_elem.text.strip()
                    
                    # คัดเฉพาะข่าวที่ยังไม่เคยส่งให้ลูกค้าระดับ PRO
                    if title not in sent_pro_news:
                        news_list.append({"title": title, "link": link})
        except Exception: 
            pass # ถ้าลิงก์ไหนเว็บล่ม ให้ข้ามไปดึงลิงก์อื่นแทน ระบบจะได้ไม่ค้าง
            
    return news_list

# ==========================================
# 🌟 ระบบส่งข่าวด่วนรายชั่วโมง (Flash News) คัดมา 1 ข่าวที่พีคสุด!
# =======================================def broadcast_hourly_urgent_news(bot_instance):
    fresh_news = get_fresh_global_news()
    if not fresh_news: return
    
    titles = [n['title'] for n in fresh_news]
    titles_str = "\n".join([f"- {t}" for t in titles])
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงินระดับโลก 
    นี่คือพาดหัวข่าวล่าสุดที่ดึงมาจากหลายสำนัก:
    {titles_str}
    
    ให้ประเมินและเลือกข่าวที่ "สำคัญและด่วนที่สุด" เพียง 1 ข่าวเท่านั้น
    และเขียนสรุปเนื้อข่าวสั้นๆ (1-2 บรรทัด) เป็นภาษาไทย
    
    ตอบกลับในรูปแบบ JSON เท่านั้น:
    {{
        "original_title": "พาดหัวข่าวต้นฉบับที่เลือก",
        "summary": "สรุปเนื้อข่าวสั้นๆ"
    }}
    """
    try:
        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
        analysis = json.loads(result_text)
        
        selected_title = analysis.get('original_title', '')
        summary = analysis.get('summary', '')
        
        if selected_title and summary:
            msg = (
                f"🚨 **ข่าวด่วนรอบชั่วโมง** 🚨\n\n"
                f"📌 **{selected_title}**\n\n"
                f"📝 **สรุป:** {summary}"
            )
            
            sent_pro_news.add(selected_title)
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
            pro_users = cur.fetchall()
            
            count = 0
            for pro in pro_users:
                if check_subscription(pro[0]) == 'pro':
                    try:
                        bot_instance.send_message(pro[0], msg, parse_mode='Markdown')
                        count += 1
                        time.sleep(0.5) 
                    except Exception: pass
            cur.close()
            conn.close()
            
            if len(sent_pro_news) > 1000: sent_pro_news.clear()
            if count > 0: print(f"✅ ส่ง Flash News สำเร็จ {count} คน")
            
    except Exception as e:
        print("Hourly News Error:", e)
def get_fresh_global_news():
    urls = [
        "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+ทองคำ+OR+คริปโต+OR+น้ำมัน+when:1d&hl=th&gl=TH&ceid=TH:th",
        "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+gold+OR+crypto+OR+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://www.investing.com/rss/news_25.rss",
        "https://www.investing.com/rss/news_301.rss"
    ]
    news_list = []
    for url in urls:
        try:
            response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:15]: 
                title_elem = item.find('title')
                if title_elem is not None:
                    title = title_elem.text.strip()
                    if title not in sent_pro_news:
                        news_list.append({"title": title})
        except Exception: pass
    return news_list

def broadcast_hourly_urgent_news(bot_instance):
    fresh_news = get_fresh_global_news()
    if not fresh_news: return
    
    titles = [n['title'] for n in fresh_news]
    titles_str = "\n".join([f"- {t}" for t in titles])
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงินระดับโลก 
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}
    
    เลือกข่าวที่ "ด่วนและสำคัญที่สุด" เพียง 1 ข่าว 
    และสรุปเนื้อข่าว 3-4 บรรทัด (เป็นภาษาไทย) ห้ามใส่ลิงก์
    
    ตอบกลับในรูปแบบ JSON เท่านั้น:
    {{
        "original_title": "พาดหัวข่าวที่เลือก",
        "summary": "สรุปเนื้อข่าว 3-4 บรรทัด"
    }}
    """
    try:
        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
        analysis = json.loads(result_text)
        
        title = analysis.get('original_title', '')
        summary = analysis.get('summary', '')
        
        if title and summary:
            msg = f"🚨 **ข่าวด่วนรอบชั่วโมง** 🚨\n\n📌 **{title}**\n\n📝 **สรุป:** {summary}"
            sent_pro_news.add(title)
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
            for pro in cur.fetchall():
                if check_subscription(pro[0]) == 'pro':
                    try:
                        bot_instance.send_message(pro[0], msg, parse_mode='Markdown')
                        time.sleep(0.5) 
                    except Exception: pass
            conn.close()
    except Exception as e:
        print("Hourly News Error:", e)
def check_and_broadcast_pro_news(bot_instance):
    fresh_news = get_fresh_global_news()
    if not fresh_news: return
    
    titles = [n['title'] for n in fresh_news]
    titles_str = "\n".join([f"- {t}" for t in titles])
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงิน 
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}
    
    เลือกข่าวที่ "สำคัญที่สุด" 3 ข่าว 
    สรุปเนื้อหาแต่ละข่าวแบบเจาะลึก 3-4 บรรทัด (ภาษาไทย)
    ห้ามใส่ลิงก์ใดๆ ทั้งสิ้น
    
    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวต้นฉบับที่เลือก",
            "summary": "สรุปเนื้อข่าว 3-4 บรรทัด"
        }}
    ]
    """
    try:
        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
        analysis_list = json.loads(result_text)
        
        if not isinstance(analysis_list, list) or len(analysis_list) == 0: return
            
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
        pro_users = cur.fetchall()
        
        for item in analysis_list:
            title = item.get('original_title', '')
            summary = item.get('summary', '')
            
            if title and summary:
                msg = f"📰 **APEX NEWS:**\n*{title}*\n\n📝 **สรุป:**\n{summary}"
                sent_pro_news.add(title)
                
                for pro in pro_users:
                    if check_subscription(pro[0]) == 'pro':
                        try:
                            bot_instance.send_message(pro[0], msg, parse_mode='Markdown')
                            time.sleep(0.5) 
                        except Exception: pass
        conn.close()
    except Exception as e:
        print("News Broadcast Error:", e)


# ==========================================
# 🌟 ระบบเช็คตั้งเตือนราคาส่วนตัว
# ==========================================
def check_custom_price_alerts():
    alerts = get_all_active_price_alerts()
    if not alerts: return
    
    symbols_to_check = set([alert[2] for alert in alerts])
    current_prices = {}
    
    for sym in symbols_to_check:
        try:
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
            role = check_subscription(user_id)
            if role == 'pro' or str(user_id) == ADMIN_ID:
                msg = (
                    f"🎯 **TARGET REACHED!** 🎯\n\n"
                    f"📌 หุ้น **{symbol}** ที่คุณตั้งเตือนไว้\n"
                    f"ตอนนี้ราคาได้ **{cond_text} {target_price:,.2f}** แล้วครับ!\n"
                    f"*(ราคาปัจจุบัน: {curr_price:,.2f})*\n\n"
                    f"👉 ระบบทำการปิดการแจ้งเตือนรายการนี้แล้ว หากต้องการตั้งใหม่พิมพ์ `/setalert`\n\n"
                    f"⚠️ **คำเตือน:** การลงทุนมีความเสี่ยง ข้อมูลนี้เป็นเพียงการแจ้งเตือนตามสถิติ โปรดพิจารณาก่อนตัดสินใจซื้อขาย"
                )
                try:
                    bot.send_message(user_id, msg, parse_mode="Markdown")
                    deactivate_price_alert(a_id) 
                    time.sleep(0.5)
                except Exception:
                    pass
            else:
                deactivate_price_alert(a_id)

# ==========================================
# 🌟 ฟีเจอร์ใหม่: Morning Apexify Briefing (08:30 น.)
# ==========================================
def send_morning_briefing(bot_instance):
    try:
        sp500 = yf.Ticker('^GSPC').history(period='1d')
        btc = yf.Ticker('BTC-USD').history(period='1d')
        gold = yf.Ticker('GC=F').history(period='1d') 
        
        if not sp500.empty and not btc.empty:
            sp500_close = sp500['Close'].iloc[-1]
            btc_close = btc['Close'].iloc[-1]
            gold_close = gold['Close'].iloc[-1] if not gold.empty else 0
            
            prompt = f"ทำตัวเป็นนักวิเคราะห์ สรุปแนวโน้มตลาดเช้านี้สั้นๆ (อิงจาก S&P500 ปิดที่ {sp500_close:.2f}, Crypto {btc_close:.2f} และทองคำโลก {gold_close:.2f}) ให้กำลังใจนักลงทุน ไม่เกิน 3 บรรทัด"
            ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            summary = ai_check.text.strip()
            
            msg = (
                f"🌅 **Apexify Morning Briefing** 🌅\n\n"
                f"📊 **สรุปตลาดโลกเมื่อคืน:**\n"
                f"• S&P 500: {sp500_close:,.2f}\n"
                f"• Bitcoin: {btc_close:,.2f}\n"
                f"• ทองคำโลก (Gold): {gold_close:,.2f}\n\n"
                f"🤖 **มุมมอง Apexify วันนี้:**\n{summary}\n\n"
                f"🔥 *ขอให้พอร์ตเขียวๆ ตลอดวันครับ!*\n\n"
                f"⚠️ **คำเตือน:** การลงทุนมีความเสี่ยง โปรดใช้วิจารณญาณในการตัดสินใจ"
            )
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
            pro_users = cur.fetchall()
            
            count = 0
            for pro in pro_users:
                if check_subscription(pro[0]) == 'pro':
                    try:
                        bot_instance.send_message(pro[0], msg, parse_mode='Markdown')
                        count += 1
                        time.sleep(0.5)
                    except Exception: pass
                    
            cur.close()
            conn.close()
            if count > 0: print(f"✅ ส่ง Morning Briefing สำเร็จ {count} คน")
    except Exception as e:
        print("Morning Briefing Error:", e)

# ==========================================
# 🌟 ฟีเจอร์ใหม่: Dividend & XD Alerts (เตือนก่อน 3 วัน)
# ==========================================
def check_xd_alerts():
    active_symbols = get_all_active_symbols()
    if not active_symbols: return
    
    now = time.time()
    for symbol in active_symbols:
        try:
            clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(".BK") else symbol
            ticker = yf.Ticker(clean_symbol)
            ex_div_date = ticker.info.get('exDividendDate')
            
            if ex_div_date:
                days_until_xd = (ex_div_date - now) / 86400 
                
                if 0 < days_until_xd <= 3:
                    alert_key = f"{symbol}_{ex_div_date}"
                    if alert_key not in sent_xd_alerts:
                        xd_dt = datetime.utcfromtimestamp(ex_div_date).strftime('%d/%m/%Y')
                        msg = (
                            f"📅 **XD ALERT: {symbol}** 📅\n\n"
                            f"หุ้นตัวนี้กำลังจะขึ้นเครื่องหมาย XD (จ่ายปันผล) ในวันที่ **{xd_dt}**\n"
                            f"*(เหลือเวลาอีกประมาณ {int(days_until_xd)} วัน)*\n\n"
                            f"👉 สายปันผลเตรียมตัว สายเก็งกำไรระวังราคาเปิดกระโดดลงนะครับ!"
                        )
                        send_alert_to_users(symbol, msg, alert_type="xd")
                        sent_xd_alerts.add(alert_key)
        except Exception: pass

if __name__ == "__main__":
    init_db()
    print("🚀 Apexify Alert System (PRO Exclusive) is Running...")
    
    # 🌟 ตั้งเวลาให้ระบบรู้ว่าต้องส่งตอนไหน
    last_hourly_news_time = time.time() - 3600  # พร้อมส่งข่าว 1 ชม. ทันที
    last_global_news_time = time.time() - 14400 # พร้อมส่งข่าว 4 ชม. ทันที
    last_morning_briefing_date = None
    last_xd_check_date = None
    
    while True:
        current_time = time.time()
        thai_time = datetime.utcnow() + timedelta(hours=7)
        current_date_str = thai_time.strftime("%Y-%m-%d")
        
        # 🌅 ส่ง Morning Briefing (เมื่อถึงเวลา 08:30 น. ของทุกวัน)
        if thai_time.hour == 8 and thai_time.minute >= 30:
            if last_morning_briefing_date != current_date_str:
                send_morning_briefing(bot)
                last_morning_briefing_date = current_date_str
                
        # 📅 เช็ค XD Alerts (เช็คแค่วันละ 1 ครั้งพอ ไม่ให้ระบบหนัก)
        if last_xd_check_date != current_date_str:
            check_xd_alerts()
            last_xd_check_date = current_date_str
        
        # 🌟 แจ้งเตือนข่าว 1 ชั่วโมง (Flash News - ข่าวเดียว ไม่มีลิงก์)
        if current_time - last_hourly_news_time >= 3600:
            broadcast_hourly_urgent_news(bot)
            last_hourly_news_time = time.time()
        
        # 🌟 แจ้งเตือนข่าว 4 ชั่วโมง (Digest News - มัดรวม 3 ข่าว มีลิงก์)
        if current_time - last_global_news_time >= 14400:
            check_and_broadcast_pro_news(bot)
            last_global_news_time = time.time() 
            
        # 🌟 เช็คกราฟเทคนิค (ทุก 5 นาที)
        check_market_conditions()
        
        # 🌟 เช็คราคาเป้าหมายส่วนตัว (ทุก 5 นาที)
        check_custom_price_alerts()
        
        time.sleep(300)
