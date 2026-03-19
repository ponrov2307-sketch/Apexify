import time
from datetime import datetime, timedelta
import telebot
import requests 
from google import genai
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY
from technical_tools import calculate_technical_indicators
import psycopg2
from database import (get_all_active_symbols, get_users_watching, init_db, check_subscription, 
                      get_connection, log_alert, get_all_active_price_alerts, deactivate_price_alert,
                      auto_downgrade_expired_users, init_new_features_db,
                      should_send_user_notification, mark_digest_sent) # 🌟 เพิ่มชื่อฟังก์ชันนี้ต่อท้ายเข้าไป
import json
import xml.etree.ElementTree as ET 
import yfinance as yf
from curl_cffi import requests as cffi_requests 
import asyncio
import edge_tts
import re
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

last_alert_state = {}
sent_pro_news = set() # 🌟 เก็บประวัติข่าวที่เคยส่งไปแล้วเพื่อกันส่งซ้ำ
sent_stock_news_history = {} 
last_stock_news_sent_at = {}
sent_xd_alerts = set()

FLASH_NEWS_INTERVAL_SECONDS = 3 * 3600
DIGEST_NEWS_CHECK_INTERVAL_SECONDS = 3600
STOCK_NEWS_COOLDOWN_SECONDS = 4 * 3600
MAX_FLASH_HEADLINES = 12
MAX_DIGEST_HEADLINES = 12
MAX_DIGEST_ITEMS = 2


def _compact_news_text(text, max_chars=180, max_lines=2):
    cleaned_lines = []
    for raw_line in str(text or "").replace("\r\n", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip(" -•\t")
        if line:
            cleaned_lines.append(line)

    compact = "\n".join(cleaned_lines[:max_lines]).strip()
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact

    trimmed = compact[: max_chars - 1].rstrip()
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0]
    return f"{trimmed}…"

def send_alert_to_users(symbol, message, alert_type="tech"):
    users = get_users_watching(symbol)
    for user_id in users:
        role = check_subscription(user_id)
        if role != 'pro':
            continue

        category = "flash_news" if alert_type == "news" else "general"
        if not should_send_user_notification(user_id, category=category):
            continue

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
        now = time.time()

        if now - last_stock_news_sent_at.get(symbol, 0) < STOCK_NEWS_COOLDOWN_SECONDS:
            return
        
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
                "reason": "วิเคราะห์ผลกระทบสั้นมาก 1 ประโยค (ภาษาไทย ไม่เกิน 80 ตัวอักษร)"
            }}
            """
            
            ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
            
            try:
                analysis = json.loads(result_text)
                if analysis.get('severity') == 'HIGH':
                    sentiment = analysis.get('sentiment', 'NEUTRAL')
                    reason = _compact_news_text(
                        analysis.get('reason', 'ไม่มีคำอธิบายเพิ่มเติม'),
                        max_chars=100,
                        max_lines=1,
                    )
                    
                    emoji_status = "🚀 เชิงบวก" if sentiment == "BULLISH" else "🩸 เชิงลบ" if sentiment == "BEARISH" else "⚪️ กลางๆ"
                    
                    msg = (
                        f"🗞 **ข่าวด่วน {symbol}**\n"
                        f"📌 {title}\n"
                        f"📊 {emoji_status}\n"
                        f"💡 {reason}\n"
                        f"🔗 [อ่านต่อ]({link})"
                    )
                    
                    send_alert_to_users(symbol, msg, alert_type="news")
                    sent_stock_news_history[symbol].add(title) 
                    last_stock_news_sent_at[symbol] = now
                    
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
            # 🌟 ดึงค่า Volume ที่เราเพิ่งเพิ่มมา
            volume = tech_data.get('volume', 0)
            avg_volume = tech_data.get('avg_volume', 1)    
            
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

            # 🌟 [เพิ่มใหม่] เงื่อนไข Whale Alert (วอลุ่มพุ่ง 3 เท่า)
            whale_condition = 'normal'
            if volume > (avg_volume * 3) and price > tech_data['ema20']: 
                whale_condition = 'buy_spike'
                msg = f"🐳 **WHALE ALERT (มีวาฬเข้า!)** 🐳\nหุ้น **{symbol}** มีวอลุ่มซื้อพุ่งกระฉูดกว่าค่าเฉลี่ย {int(volume/avg_volume * 100)}% จับตาดูให้ดี!\n(ราคาปัจจุบัน: {price:.2f})"
            elif volume > (avg_volume * 3) and price < tech_data['ema20']:
                whale_condition = 'sell_spike'
                msg = f"🩸 **WHALE DUMP (วาฬเทขาย!)** 🩸\nหุ้น **{symbol}** โดนสาดวอลุ่มขายทิ้งหนักกว่าค่าเฉลี่ย {int(volume/avg_volume * 100)}% ระวังแรงฉุด!\n(ราคาปัจจุบัน: {price:.2f})"

            if whale_condition != 'normal' and whale_condition != last_alert_state[symbol].get('whale', 'normal'):
                send_alert_to_users(symbol, msg, alert_type="whale")
                log_alert(symbol, f"WHALE_{whale_condition.upper()}", price) 
                last_alert_state[symbol]['whale'] = whale_condition
            elif whale_condition == 'normal':
                last_alert_state[symbol]['whale'] = 'normal'

            time.sleep(2)
        except Exception: pass

# ==========================================
# 🌟 ฟังก์ชันดึงข่าวรวมจากทุกสำนัก
# ==========================================
def get_fresh_global_news():
    urls = [
        "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+ทองคำ+OR+คริปโต+OR+น้ำมัน+when:1d&hl=th&gl=TH&ceid=TH:th",
        "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+gold+OR+crypto+OR+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://www.investing.com/rss/news_25.rss",
        "https://www.investing.com/rss/news_301.rss",
        "https://www.investing.com/rss/market_overview.rss"
    ]
    news_list = []
    seen_titles = set()
    for url in urls:
        try:
            response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:15]: 
                title_elem = item.find('title')
                link_elem = item.find('link')
                if title_elem is not None:
                    title = title_elem.text.strip()
                    link = link_elem.text.strip() if link_elem is not None else ""
                    if title not in sent_pro_news and title not in seen_titles:
                        news_list.append({"title": title, "link": link})
                        seen_titles.add(title)
        except Exception: pass
    return news_list

# ==========================================
# 🌟 ระบบส่งข่าวด่วนรายชั่วโมง (Flash News) - [อัปเกรดระบบดักจับ Error]
# ==========================================
def broadcast_hourly_urgent_news(bot_instance):
    fresh_news = get_fresh_global_news()
    if not fresh_news: 
        try:
            bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News System:** ไม่พบข่าวใหม่จากสำนักข่าวเลย (อาจเกิดจาก Network หรือไม่มีข่าวจริงๆ)")
        except: pass
        return
    
    titles = [n['title'] for n in fresh_news]
    titles_str = "\n".join([f"- {t}" for t in titles[:MAX_FLASH_HEADLINES]]) # ลดจำนวนลงกัน AI งง
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงินระดับโลก 
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}
    
    เลือกข่าวที่ "ด่วนและสำคัญที่สุดในเชิงเศรษฐกิจ" เพียง 1 ข่าว 
    และสรุปเนื้อข่าวแบบสั้นมาก 1-2 บรรทัด (เป็นภาษาไทย) ห้ามใส่ลิงก์
    (ถ้าข่าวมีความรุนแรงหรือสงคราม ให้สรุปเฉพาะผลกระทบทางเศรษฐกิจเท่านั้น)
    
    ตอบกลับในรูปแบบ JSON เท่านั้น:
    {{
        "original_title": "พาดหัวข่าวที่เลือก",
        "summary": "สรุปเนื้อข่าว 1-2 บรรทัด แบบอ่านจบเร็ว"
    }}
    """
    try:
        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
        
        # 🌟 1. ดักจับกรณี AI ไม่ยอมตอบเป็น JSON
        try:
            analysis = json.loads(result_text)
        except json.JSONDecodeError:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News Error:** AI ไม่ได้ตอบเป็น JSON!\n\n**ข้อความที่ AI ตอบมา:**\n{result_text[:500]}")
            return
        
        # 🌟 2. รองรับ Key หลายรูปแบบ (เผื่อ AI ดื้อเปลี่ยนชื่อ Key เอง)
        title = analysis.get('original_title') or analysis.get('title') or analysis.get('headline') or ''
        summary = analysis.get('summary') or analysis.get('content') or analysis.get('description') or ''
        
        if title and summary:
            summary = _compact_news_text(summary, max_chars=180, max_lines=2)
            msg = f"🚨 **Flash News**\n📌 **{title}**\n📝 {summary}"
            sent_pro_news.add(title)
            
            # ป้องกันหน่วยความจำเต็ม
            if len(sent_pro_news) > 500: sent_pro_news.clear()
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
            count = 0
            for pro in cur.fetchall():
                if check_subscription(pro[0]) == 'pro' and should_send_user_notification(pro[0], category="flash_news"):
                    try:
                        bot_instance.send_message(pro[0], msg, parse_mode='Markdown')
                        count += 1
                        time.sleep(0.5) 
                    except Exception: pass
            conn.close()

        else:
            # 🌟 3. ดักจับกรณี AI ตอบ JSON แต่ข้อมูลแหว่ง/ไม่ครบ
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News Error:** ข้อมูลแหว่ง (Title หรือ Summary หายไป)\n\n**JSON ที่ได้:**\n{result_text}")
            
    except Exception as e:
        # 🌟 4. ดักจับกรณี API พัง หรือโดนบล็อคเนื้อหาความรุนแรง
        try:
            error_msg = str(e)
            if "Safety" in error_msg or "blocked" in error_msg.lower():
                bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News สะดุด:** AI ปฏิเสธการสรุปข่าวเนื่องจากติดฟิลเตอร์คำรุนแรง (Safety Policy)")
            else:
                bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News System Error:** {error_msg}")
        except: pass

# ==========================================
# 🌟 ระบบส่งข่าว 4 ชั่วโมง (Digest News)
# ==========================================
def check_and_broadcast_pro_news(bot_instance):
    fresh_news = get_fresh_global_news()
    if not fresh_news: return
    
    titles = [n['title'] for n in fresh_news]
    titles_str = "\n".join([f"- {t}" for t in titles[:MAX_DIGEST_HEADLINES]])
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงิน 
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}
    
    เลือกข่าวเชิงเศรษฐกิจ/การลงทุน ที่ "สำคัญที่สุด" 2 ข่าว 
    สรุปเนื้อหาแต่ละข่าวแบบสั้น กระชับ ข่าวละ 1-2 บรรทัด (ภาษาไทย)
    (เน้นเรื่องเศรษฐกิจ หลีกเลี่ยงเนื้อหาความรุนแรง)
    
    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวต้นฉบับที่เลือก",
            "summary": "สรุปเนื้อข่าว 1-2 บรรทัด"
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
        pro_users = [row[0] for row in cur.fetchall()]
        cur.close()
        eligible_users = []
        for uid in pro_users:
            if check_subscription(uid) == 'pro' and should_send_user_notification(uid, category="digest_news"):
                eligible_users.append(uid)
        if not eligible_users:
            conn.close()
            return
        sent_to_users = set()
        digest_sections = []

        for item in analysis_list[:MAX_DIGEST_ITEMS]:
            title = item.get('original_title', '')
            summary = item.get('summary', '')
            
            if title and summary:
                summary = _compact_news_text(summary, max_chars=140, max_lines=2)
                digest_sections.append(f"**{len(digest_sections) + 1}. {title}**\n{summary}")
                sent_pro_news.add(title)
        if not digest_sections:
            conn.close()
            return

        msg = "📰 **APEX NEWS DIGEST**\n\n" + "\n\n".join(digest_sections)

        for uid in eligible_users:
            try:
                bot_instance.send_message(uid, msg, parse_mode='Markdown')
                sent_to_users.add(uid)
                time.sleep(0.5)
            except Exception:
                pass
        for uid in sent_to_users:
            mark_digest_sent(uid)
        conn.close()
    except Exception as e:
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Digest News Error:** {str(e)[:100]}...")
        except: pass


# ==========================================
# 🌟 ระบบเช็คตั้งเตือนราคาส่วนตัว
# ==========================================
def clear_web_price_alert(user_id, ticker):
    """รีเซ็ตค่า alert_price กลับเป็น 0 หลังแจ้งเตือนแล้ว"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE portfolios SET alert_price = 0 WHERE user_id = %s AND ticker = %s", (str(user_id), ticker))
        conn.commit()
    except Exception as e:
        pass
    finally:
        cur.close()
        conn.close()

def check_custom_price_alerts():
    """🌟 เช็ค Alert จากตารางเดียว และตัดสิทธิ์คนหมด PRO ทันที"""
    bot_alerts = get_all_active_price_alerts()
    if not bot_alerts: return
    
    current_prices = {}
    for alert in bot_alerts:
        sym = alert[2]
        if sym not in current_prices:
            try:
                tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                if not err and tech_data: current_prices[sym] = tech_data['price']
            except: pass
            
    for alert in bot_alerts:
        a_id, user_id, symbol, target_price, condition = alert
        
        # 🌟 ถ้ายศตกจาก PRO ให้ลบ Alert นั้นทิ้งอัตโนมัติ!
        if check_subscription(user_id) != 'pro':
            deactivate_price_alert(a_id)
            continue

        if not should_send_user_notification(user_id, category="general"):
            continue
            
        if symbol not in current_prices: continue
        curr_price = current_prices[symbol]
        triggered = False
        
        # 🌟 ปรับ Format ให้ตรงกัน (เว็บส่ง > บอทส่ง above)
        cond_normalized = 'above' if condition in ['above', '>'] else 'below'
        
        if cond_normalized == 'above' and curr_price >= target_price:
            triggered, cond_text = True, "ทะลุขึ้นเป้าหมายที่"
        elif cond_normalized == 'below' and curr_price <= target_price:
            triggered, cond_text = True, "ร่วงลงมาแตะที่"
            
        if triggered:
            msg = (f"🎯 **TARGET REACHED!** 🎯\n\n📌 หุ้น **{symbol}** \nราคาได้ **{cond_text} {target_price:,.2f}** แล้ว!\n*(ปัจจุบัน: {curr_price:,.2f})*\n\n👉 ระบบปิดการแจ้งเตือนนี้แล้ว")
            try:
                bot.send_message(user_id, msg, parse_mode="Markdown")
                deactivate_price_alert(a_id)
                time.sleep(0.5)
            except Exception: 
                deactivate_price_alert(a_id)
# ==========================================
# 🎙️ ฟีเจอร์ AI Podcast สรุปตลาดตอนเช้า (08:00 น.)
# ==========================================
def get_podcast_market_data():
    try:
        sp500 = yf.Ticker('^GSPC').history(period='1d')['Close'].iloc[-1]
        btc = yf.Ticker('BTC-USD').history(period='1d')['Close'].iloc[-1]
        gold = yf.Ticker('GC=F').history(period='1d')['Close'].iloc[-1]
        return f"ดัชนี เอสแอนด์พี 500 ปิดที่ {sp500:,.0f} จุด, บิตคอยน์อยู่ที่ {btc:,.0f} ดอลลาร์, และราคาทองคำโลกอยู่ที่ {gold:,.0f} ดอลลาร์"
    except Exception as e:
        return "ตลาดหุ้นอเมริกาและคริปโตมีการทรงตัว"

def generate_podcast_script(market_info):
    prompt = f"""
    คุณคือนักจัดรายการพอดแคสต์การเงินชื่อ Apexify 
    เขียนสคริปต์สั้นๆ ความยาวไม่เกิน 1 นาที สำหรับพูดสรุปตลาดเช้านี้
    ข้อมูล: {market_info}
    ข้อบังคับ: ใช้ภาษาพูดที่เป็นกันเอง สนุกสนาน มีพลัง ไม่ใช้ตัวเลขทศนิยมที่อ่านยาก จบด้วยการให้กำลังใจนักลงทุน
    """
    try:
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return res.text.strip()
    except Exception:
        return "สวัสดีครับนักลงทุน วันนี้ตลาดทรงตัว ขอให้เทรดอย่างระมัดระวังนะครับ"

async def create_and_send_podcast(bot_instance):
    print("🌍 [Podcast] กำลังสร้างสคริปต์และอัดเสียง...")
    market_info = get_podcast_market_data()
    script = generate_podcast_script(market_info)
    
    filename = "apexify_morning.mp3"
    communicate = edge_tts.Communicate(script, "th-TH-PremwadeeNeural") # เสียงพรีมวดี
    await communicate.save(filename)
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
    pro_users = cur.fetchall()
    cur.close()
    conn.close()

    count = 0
    for row in pro_users:
        user_id = row[0]
        if check_subscription(user_id) == 'pro' and should_send_user_notification(user_id, category="morning_briefing"):
            try:
                with open(filename, 'rb') as audio:
                    bot_instance.send_voice(
                        chat_id=user_id,
                        voice=audio,
                        caption="🎧 **Apexify Morning Briefing** 🎙️\nอัปเดตตลาดเช้านี้แบบ Podcast ฟังระหว่างขับรถได้เลยครับ! 🚀",
                        parse_mode="Markdown"
                    )
                count += 1
                await asyncio.sleep(0.5) 
            except Exception: pass
            
    if count > 0: print(f"✅ [Podcast] ส่งเสียงสำเร็จ {count} คน")                
# ==========================================
# ==========================================
# 🌟 ฟีเจอร์ Morning Apexify Briefing (08:30 น.)
# ==========================================
def send_morning_briefing(bot_instance):
    try:
        sp500 = yf.Ticker('^GSPC').history(period='1d')
        btc = yf.Ticker('BTC-USD').history(period='1d')
        gold = yf.Ticker('GC=F').history(period='1d') 
        
        fresh_news = get_fresh_global_news()
        news_titles = "\n".join([f"- {n['title']}" for n in fresh_news[:5]]) if fresh_news else "ไม่มีข่าวเด่น"
        
        if not sp500.empty and not btc.empty:
            sp500_close = sp500['Close'].iloc[-1]
            btc_close = btc['Close'].iloc[-1]
            gold_close = gold['Close'].iloc[-1] if not gold.empty else 0
            
            # 🌟 อัปเดต Prompt ใหม่ บังคับให้สั้นและห้ามทวนคำสั่ง!
            prompt = f"""
            คุณคือนักวิเคราะห์การเงินที่เก่งกาจและเป็นกันเอง 
            จงสรุปแนวโน้มตลาดเช้านี้สั้นๆ แบบฟันธงเพื่อส่งให้เทรดเดอร์ (ความยาวไม่เกิน 4 บรรทัดเท่านั้น!)
            
            ข้อมูลตลาดเมื่อคืน: S&P500={sp500_close:.2f}, Bitcoin={btc_close:.2f}, ทองคำ={gold_close:.2f}
            พาดหัวข่าวสำคัญ:
            {news_titles}
            
            ข้อบังคับเด็ดขาด: 
            1. ห้ามทวนคำสั่งหรือเขียนหัวข้อใดๆ ทั้งสิ้น
            2. ห้ามแยกข้อ 1-2-3 ให้เขียนบรรยายรวดเดียวจบ
            3. พิมพ์มาแค่เนื้อหาสรุป 3-4 บรรทัดจบ พร้อมให้กำลังใจท้ายข้อความ
            """
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
                f"⚠️ **คำเตือน:** การลงทุนมีความเสี่ยง โปรดใช้วิจารณญาณ"
            )
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role IN ('vip', 'pro')")
            pro_users = cur.fetchall()
            
            count = 0
            for pro in pro_users:
                if check_subscription(pro[0]) in ('vip', 'pro') and should_send_user_notification(pro[0], category="morning_briefing"):
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
    upcoming_xds = [] # 🌟 เก็บรวบรวมไว้ส่งทีเดียว
    
    for symbol in active_symbols:
        try:
            allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
            clean_symbol = symbol.replace(".", "-") if "." in symbol and not symbol.endswith(allowed_suffixes) else symbol
            ticker = yf.Ticker(clean_symbol)
            ex_div_date = ticker.info.get('exDividendDate')
            
            if ex_div_date:
                days_until_xd = (ex_div_date - now) / 86400 
                
                # 🌟 เตือนล่วงหน้า 1 สัปดาห์ (7 วัน) ไปเลย
                if 0 < days_until_xd <= 7:
                    alert_key = f"{symbol}_{ex_div_date}"
                    if alert_key not in sent_xd_alerts:
                        xd_dt = datetime.utcfromtimestamp(ex_div_date).strftime('%d/%m/%Y')
                        upcoming_xds.append(f"📌 **{symbol}** ➡️ XD วันที่ {xd_dt} (อีก {int(days_until_xd)} วัน)")
                        sent_xd_alerts.add(alert_key)
        except Exception: pass
        
    # 🌟 ถ้ารวบรวมได้ ค่อยบรอดแคสต์ให้สาย PRO รวดเดียว
    if upcoming_xds:
        msg = "📅 **ปฏิทินเตือนหุ้นปันผล (XD Alert) สัปดาห์นี้** 📅\n\n" + "\n".join(upcoming_xds) + "\n\n👉 สายปันผลเตรียมตัว สายเก็งกำไรระวังราคาเปิดกระโดดลงนะครับ!"
        
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
        pro_users = cur.fetchall()
        for pro in pro_users:
            if check_subscription(pro[0]) == 'pro' and should_send_user_notification(pro[0], category="xd_alert"):
                try:
                    bot.send_message(pro[0], msg, parse_mode='Markdown')
                    time.sleep(0.5)
                except Exception: pass
        cur.close()
        conn.close()
# ==========================================
# 🌟 ฟีเจอร์ใหม่: Daily Portfolio Summary (สรุปพอร์ตตี 5)
# ==========================================
def send_daily_portfolio_summary(bot_instance):
    from database import get_user_portfolio, get_connection # ระวังการ import
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    import yfinance as yf
    import time
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT p.user_id
        FROM portfolios p
        JOIN users u ON u.user_id = p.user_id
        WHERE u.role IN ('vip', 'pro')
    """)
    users_with_port = cur.fetchall()
    cur.close()
    conn.close()
    
    count = 0
    for row in users_with_port:
        user_id = row[0]
        role = check_subscription(user_id)
        if role not in ('vip', 'pro'):
            continue
        if not should_send_user_notification(user_id, category="general"):
            continue
        portfolio = get_user_portfolio(user_id)
        if not portfolio: continue
            
        total_invested = 0
        current_value = 0
        msg = f"🔔 **สรุปพอร์ตลงทุน (Apex Wealth Master)** 🔔\n\n"
        
        for asset in portfolio:
            ticker = asset['ticker']
            shares = asset['shares']
            avg_cost = asset['avg_cost']
            try:
                allowed_suffixes = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")
                clean_ticker = ticker.replace(".", "-") if "." in ticker and not ticker.endswith(allowed_suffixes) else ticker
                live_price = float(yf.Ticker(clean_ticker).fast_info.last_price)
            except Exception:
                live_price = avg_cost
                
            invested = shares * avg_cost
            current = shares * live_price
            profit = current - invested
            profit_pct = (profit / invested * 100) if invested > 0 else 0
            
            total_invested += invested
            current_value += current
            
            icon = "🟢" if profit >= 0 else "🔴"
            msg += f"{icon} **{ticker}** : {profit:,.2f} ({profit_pct:,.2f}%)\n"
            
        total_profit = current_value - total_invested
        total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
        total_icon = "🟢" if total_profit >= 0 else "🔴"
        
        msg += f"\n====================\n"
        msg += f"💰 **มูลค่าพอร์ตรวม:** {current_value:,.2f}\n"
        msg += f"💵 **ต้นทุนรวม:** {total_invested:,.2f}\n"
        msg += f"{total_icon} **กำไร/ขาดทุนรวม:** {total_profit:,.2f} ({total_profit_pct:,.2f}%)\n"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Open Dashboard Login", callback_data="menu_dashboard"))
        
        try:  # 👈 เติมคำว่า try: ตรงบรรทัดนี้ครับ! (ย่อหน้าให้ตรงกับ markup)
            bot_instance.send_message(user_id, msg, parse_mode='Markdown', reply_markup=markup)
            count += 1
            time.sleep(0.5)
        except Exception: pass

            
    if count > 0: print(f"✅ ส่งสรุปพอร์ตสำเร็จ {count} คน")

# 👇 จุดสังเกต: วางไว้เหนือบรรทัดนี้
if __name__ == "__main__":
    init_db()
    try:
        init_new_features_db()
    except Exception as e:
        print("DB Init Error:", e)
    
    # 🧹 [เพิ่มบรรทัดนี้] สั่งให้กวาดล้างทันที 1 ครั้ง ตอนที่เพิ่งกดรันบอทใหม่
    auto_downgrade_expired_users()
    print("🧹 กวาดล้าง DB ทันทีที่เปิดระบบเรียบร้อยแล้ว!")
    
    print("🚀 Apexify Alert System (PRO + VIP selected features) is Running...")
    # 🌟 ตั้งค่าเริ่มต้น
    last_hourly_news_time = time.time() - FLASH_NEWS_INTERVAL_SECONDS
    last_global_news_time = time.time() - DIGEST_NEWS_CHECK_INTERVAL_SECONDS
    last_morning_briefing_date = None
    last_xd_check_date = None
    last_podcast_date = None
    # 🌟 เอาบรรทัดนี้มาแปะตรงนี้ครับ
    last_portfolio_summary_date = None

    last_downgrade_date = None # 🌟 เพิ่มตัวแปรสำหรับเช็ควันที่ปรับยศ
    
    while True:
        current_time = time.time()
        thai_time = datetime.utcnow() + timedelta(hours=7)
        current_date_str = thai_time.strftime("%Y-%m-%d")
        
        # 🧹 [เพิ่มใหม่] สั่งปรับยศคนหมดอายุตอนเที่ยงคืน (ทำแค่วันละ 1 ครั้ง)
        if thai_time.hour == 0 and last_downgrade_date != current_date_str:
            auto_downgrade_expired_users()
            print(f"🧹 [{current_date_str}] Auto-Downgrade: อัปเดต DB ปรับยศคนหมดอายุเรียบร้อย")
            last_downgrade_date = current_date_str
            
        # 🌅 ส่ง Morning Briefing (08:30 น.)
        if thai_time.hour == 8 and thai_time.minute >= 30:
            if last_morning_briefing_date != current_date_str:
                send_morning_briefing(bot)
                last_morning_briefing_date = current_date_str
        # 🎙️ ส่ง AI Podcast สรุปตลาด (08:00 น.)
        if thai_time.hour == 8 and thai_time.minute >= 0 and thai_time.minute < 30:
            if last_podcast_date != current_date_str:
                # 🌟 เนื่องจากฟังก์ชันเสียงเป็น Async ต้องใช้คำสั่งนี้รัน
                asyncio.run(create_and_send_podcast(bot))
                last_podcast_date = current_date_str        
        # 📅 เช็ค XD Alerts
        if last_xd_check_date != current_date_str:
            check_xd_alerts()
            last_xd_check_date = current_date_str
        # 🌟 เอาบล็อกนี้มาแทรกตรงนี้ครับ (เช็คเวลาตี 5)
        if thai_time.hour == 5 and thai_time.minute >= 0:
            if last_portfolio_summary_date != current_date_str:
                send_daily_portfolio_summary(bot)
                last_portfolio_summary_date = current_date_str
        # 🌟 แจ้งเตือนข่าว Flash News ทุก 3 ชั่วโมง
        if current_time - last_hourly_news_time >= FLASH_NEWS_INTERVAL_SECONDS:
            broadcast_hourly_urgent_news(bot)
            last_hourly_news_time = time.time()
        
        # 🌟 ตรวจ Digest News ทุก 1 ชั่วโมง แล้วคัดตามความถี่รายผู้ใช้
        if current_time - last_global_news_time >= DIGEST_NEWS_CHECK_INTERVAL_SECONDS:
            check_and_broadcast_pro_news(bot)
            last_global_news_time = time.time() 
            
        # 🌟 เช็คกราฟเทคนิค & ตั้งเตือนราคา (ทุก 5 นาที)
        check_market_conditions()
        check_custom_price_alerts()
        
        time.sleep(300)

