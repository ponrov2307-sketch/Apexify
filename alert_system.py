import time
import hashlib
import math
from datetime import datetime, timedelta
import telebot
import requests 
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY, gemini_client
from technical_tools import calculate_technical_indicators
import psycopg2
from database import (get_all_active_symbols, get_users_watching, init_db, check_subscription,
                      get_connection, log_alert, get_all_active_price_alerts, deactivate_price_alert,
                      auto_downgrade_expired_users, init_new_features_db,
                      should_send_user_notification, mark_digest_sent,
                      reset_daily_free_usage, get_expiring_subscriptions,
                      get_top_watched_symbols)
import json
import xml.etree.ElementTree as ET 
import yfinance as yf
from curl_cffi import requests as cffi_requests 
import asyncio
import edge_tts
import re
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = gemini_client

last_alert_state = {}
sent_pro_news = set() # 🌟 เก็บประวัติข่าวที่เคยส่งไปแล้วเพื่อกันส่งซ้ำ
sent_stock_news_history = {}
last_stock_news_sent_at = {}
sent_xd_alerts = set()
_rss_cache = {"data": [], "ts": 0.0}  # 🌟 Cache RSS ร่วมระหว่าง Flash และ Digest

FLASH_NEWS_INTERVAL_SECONDS = 3 * 3600
DIGEST_NEWS_CHECK_INTERVAL_SECONDS = 3600
STOCK_NEWS_COOLDOWN_SECONDS = 2 * 3600
STOCK_NEWS_CHECK_INTERVAL_SECONDS = 30 * 60  # 🌟 เช็คข่าวหุ้นรายตัวทุก 30 นาที
_RSS_CACHE_TTL = 1800  # 30 นาที
MAX_FLASH_HEADLINES = 12
MAX_DIGEST_HEADLINES = 12
MAX_DIGEST_ITEMS = 2
MORNING_MACRO_ASSETS = {
    "SPY": "SPY ETF",
    "QQQ": "QQQ ETF",
    "GC=F": "ทองคำโลก",
    "CL=F": "น้ำมัน WTI",
    "DX-Y.NYB": "Dollar Index",
}
MORNING_MOVER_UNIVERSE = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "META": "Meta",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "AMD": "AMD",
    "NFLX": "Netflix",
    "PLTR": "Palantir",
}
MORNING_BRIEFING_LEGAL_DISCLAIMER = (
    "⚠️ **ข้อจำกัดความรับผิดชอบ:** ข้อมูลนี้จัดทำขึ้นเพื่อวัตถุประสงค์ในการให้ข้อมูลทั่วไปเท่านั้น "
    "ไม่ถือเป็นคำแนะนำการลงทุน การเสนอขาย หรือการชักชวนให้ซื้อหรือขายหลักทรัพย์ "
    "สินทรัพย์ดิจิทัล หรือผลิตภัณฑ์ทางการเงินใด ๆ ผู้ลงทุนควรศึกษาข้อมูลเพิ่มเติม "
    "ประเมินความเสี่ยง และใช้ดุลยพินิจของตนเองก่อนตัดสินใจลงทุน"
)


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


def _normalize_news_title(title):
    raw = str(title or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"\s*-\s*Google News\s*$", "", raw, flags=re.IGNORECASE)
    return raw.strip()


def _normalize_news_source(source):
    raw = str(source or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw or "Unknown Source"


def _extract_news_source(item, title="", link=""):
    source_elem = item.find("source")
    if source_elem is not None and source_elem.text:
        return _normalize_news_source(source_elem.text)

    normalized_title = _normalize_news_title(title)
    if " - " in normalized_title:
        maybe_source = normalized_title.rsplit(" - ", 1)[-1]
        if maybe_source and len(maybe_source) <= 60:
            return _normalize_news_source(maybe_source)

    hostname = urlparse(str(link or "")).netloc.replace("www.", "").strip()
    if hostname:
        return _normalize_news_source(hostname)

    return "Unknown Source"


def _build_dispatch_key(category, raw_key):
    normalized = re.sub(r"\s+", " ", str(raw_key or "").strip().lower())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"{category}:{digest}"


def _claim_dispatch_once(category, raw_key):
    dispatch_key = _build_dispatch_key(category, raw_key)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM dispatch_log WHERE created_at < NOW() - INTERVAL '14 days'")
        cur.execute(
            """
            INSERT INTO dispatch_log (dispatch_key, category, raw_key)
            VALUES (%s, %s, %s)
            ON CONFLICT (dispatch_key) DO NOTHING
            RETURNING dispatch_key
            """,
            (dispatch_key, str(category or "").strip(), str(raw_key or "").strip()),
        )
        claimed = cur.fetchone() is not None
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def _init_sent_pro_news():
    """โหลด raw_key จาก dispatch_log (24 ชม.ที่ผ่านมา) เข้า sent_pro_news
    เพื่อป้องกันส่งข่าวซ้ำหลัง restart"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT raw_key FROM dispatch_log WHERE category = 'news' "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        )
        for (raw_key,) in cur.fetchall():
            if raw_key:
                sent_pro_news.add(raw_key)
        conn.close()
        print(f"[init] โหลดประวัติ sent_pro_news จาก DB: {len(sent_pro_news)} รายการ")
    except Exception as e:
        print(f"[init] _init_sent_pro_news error: {e}")


def _get_morning_market_movers_text():
    try:
        history = yf.download(
            tickers=list(MORNING_MOVER_UNIVERSE.keys()),
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception:
        return ""

    if history is None or getattr(history, "empty", True):
        return ""

    movers = []
    for symbol, display_name in MORNING_MOVER_UNIVERSE.items():
        try:
            symbol_history = history[symbol].dropna()
            if len(symbol_history) < 2:
                continue

            last_close = float(symbol_history["Close"].iloc[-1])
            prev_close = float(symbol_history["Close"].iloc[-2])
            if prev_close <= 0:
                continue

            pct_change = ((last_close - prev_close) / prev_close) * 100
            volume_ratio = 0.0

            if "Volume" in symbol_history.columns:
                last_volume = float(symbol_history["Volume"].iloc[-1] or 0)
                avg_volume = float(symbol_history["Volume"].iloc[:-1].tail(4).mean() or 0)
                if avg_volume > 0:
                    volume_ratio = last_volume / avg_volume

            movers.append(
                {
                    "symbol": symbol,
                    "display_name": display_name,
                    "last_close": last_close,
                    "pct_change": pct_change,
                    "volume_ratio": volume_ratio,
                }
            )
        except Exception:
            continue

    if not movers:
        return ""

    top_gainer = max(movers, key=lambda item: item["pct_change"])
    top_loser = min(movers, key=lambda item: item["pct_change"])

    lines = [
        (
            f"📈 เด่นสุด: {top_gainer['display_name']} ({top_gainer['symbol']}) "
            f"{top_gainer['pct_change']:+.2f}% ปิด {top_gainer['last_close']:,.2f} ดอลลาร์"
        )
    ]

    used_symbols = {top_gainer["symbol"]}
    if top_loser["symbol"] not in used_symbols:
        lines.append(
            (
                f"📉 อ่อนสุด: {top_loser['display_name']} ({top_loser['symbol']}) "
                f"{top_loser['pct_change']:+.2f}% ปิด {top_loser['last_close']:,.2f} ดอลลาร์"
            )
        )
        used_symbols.add(top_loser["symbol"])

    remaining = [item for item in movers if item["symbol"] not in used_symbols]
    if remaining:
        notable = max(remaining, key=lambda item: (item["volume_ratio"], abs(item["pct_change"])))
        if notable["volume_ratio"] >= 1.3 or abs(notable["pct_change"]) >= 4.0:
            if notable["volume_ratio"] >= 1.3:
                tail = f"วอลุ่มสูงกว่าค่าเฉลี่ยราว {notable['volume_ratio']:.1f} เท่า"
            else:
                tail = f"แกว่ง {notable['pct_change']:+.2f}% ในคืนเดียว"
            lines.append(f"👀 น่าจับตา: {notable['display_name']} ({notable['symbol']}) {tail}")

    return "\n".join(lines)


def _get_morning_macro_assets_text():
    lines = []
    for symbol, label in MORNING_MACRO_ASSETS.items():
        try:
            history = yf.Ticker(symbol).history(period="5d")
            if history is None or history.empty or len(history) < 2:
                continue

            last_close = float(history["Close"].iloc[-1])
            prev_close = float(history["Close"].iloc[-2])
            if prev_close <= 0:
                continue

            pct_change = ((last_close - prev_close) / prev_close) * 100
            emoji = "🟢" if pct_change >= 0 else "🔴"
            lines.append(f"{emoji} {label}: {last_close:,.2f} ({pct_change:+.2f}%)")
        except Exception:
            continue

    return "\n".join(lines)


def _current_thai_date_str():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")

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
        except Exception as e:
            print(f"[Alert] ส่งให้ {user_id} ({symbol}) ไม่สำเร็จ: {e}")

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
            pub_date_elem = items[0].find('pubDate')
            if title_elem is None: return

            # 🌟 กรองข่าวเก่ากว่า 6 ชั่วโมงออก
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    pub_dt = parsedate_to_datetime(pub_date_elem.text)
                    age_hours = (datetime.now(pub_dt.tzinfo) - pub_dt).total_seconds() / 3600
                    if age_hours > 6:
                        return
                except Exception:
                    pass  # ถ้า parse วันที่ไม่ได้ให้ผ่านไปก่อน

            title = _normalize_news_title(title_elem.text)
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
                "reason": "อธิบายว่าข่าวนี้กระทบราคาหุ้นอย่างไร และนักลงทุนควรระวังหรือจับตาอะไร 2-3 ประโยค (ภาษาไทย)"
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
                    dispatch_key = f"{symbol}|{title}"
                    if not _claim_dispatch_once("stock_news", dispatch_key):
                        sent_stock_news_history[symbol].add(title)
                        last_stock_news_sent_at[symbol] = now
                        return
                    
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
                        
            except json.JSONDecodeError as e:
                print(f"⚠️ [StockNews] JSON decode ล้มเหลวสำหรับ {symbol}: {e}")
    except Exception as e:
        print(f"❌ [StockNews] check_hot_news ล้มเหลวสำหรับ {symbol}: {e}")

def check_market_conditions():
    active_symbols = get_all_active_symbols()
    if not active_symbols: return

    for symbol in active_symbols:
        try:
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
        except Exception as e:
            print(f"❌ [MarketConditions] ล้มเหลวสำหรับ {symbol}: {e}")

# ==========================================
# 🌟 ฟังก์ชันดึงข่าวรวมจากทุกสำนัก
# ==========================================
def get_fresh_global_news():
    """ดึงข่าวรวม — มี Cache 30 นาที ป้องกัน Flash & Digest ดึงซ้ำกัน"""
    now = time.time()
    if now - _rss_cache["ts"] < _RSS_CACHE_TTL and _rss_cache["data"]:
        # ยังใหม่อยู่ กรอง sent_pro_news ออกแล้วคืนผล
        return [n for n in _rss_cache["data"] if n["title"] not in sent_pro_news]

    urls = [
        # 🇹🇭 ข่าวไทย
        "https://news.google.com/rss/search?q=เศรษฐกิจ+OR+หุ้น+OR+ทองคำ+OR+คริปโต+OR+น้ำมัน+when:1d&hl=th&gl=TH&ceid=TH:th",
        # 🌍 ข่าวโลก (Google News)
        "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+gold+OR+crypto+OR+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
        # 📊 Macro / Fed / Rates
        "https://news.google.com/rss/search?q=Federal+Reserve+OR+interest+rates+OR+inflation+OR+GDP+when:1d&hl=en-US&gl=US&ceid=US:en",
        # 🏦 Yahoo Finance market headlines
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        # 📺 CNBC markets
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ]
    raw_news = []
    seen_titles = set()
    for url in urls:
        try:
            response = cffi_requests.get(url, impersonate="chrome110", timeout=15)
            root = ET.fromstring(response.content)
            for item in root.findall('.//item')[:15]:
                title_elem = item.find('title')
                link_elem = item.find('link')
                if title_elem is not None:
                    title = _normalize_news_title(title_elem.text)
                    link = link_elem.text.strip() if link_elem is not None else ""
                    source = _extract_news_source(item, title=title, link=link)
                    if title and title not in seen_titles:
                        raw_news.append({"title": title, "link": link, "source": source})
                        seen_titles.add(title)
        except Exception as e:
            print(f"⚠️ [GlobalNews] ดึง RSS ล้มเหลวสำหรับ {url}: {e}")

    if not raw_news:
        return []

    source_buckets = {}
    for item in raw_news:
        source_buckets.setdefault(item["source"], []).append(item)

    balanced_news = []
    depth = 0
    while len(balanced_news) < MAX_FLASH_HEADLINES:
        added = False
        for source in source_buckets:
            bucket = source_buckets[source]
            if depth < len(bucket):
                balanced_news.append(bucket[depth])
                added = True
                if len(balanced_news) >= MAX_FLASH_HEADLINES:
                    break
        if not added:
            break
        depth += 1

    # 🌟 อัปเดต cache (เก็บทั้งหมด ยังไม่กรอง sent_pro_news)
    _rss_cache["data"] = balanced_news
    _rss_cache["ts"] = time.time()

    return [n for n in balanced_news if n["title"] not in sent_pro_news]

# ==========================================
# 🌟 ระบบส่งข่าวด่วนรายชั่วโมง (Flash News) - [อัปเกรดระบบดักจับ Error]
# ==========================================
def broadcast_hourly_urgent_news(bot_instance, force=False):
    fresh_news = get_fresh_global_news()
    if not fresh_news:
        try:
            bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News System:** ไม่พบข่าวใหม่จากสำนักข่าวเลย (อาจเกิดจาก Network หรือไม่มีข่าวจริงๆ)")
        except Exception:
            pass
        return
    
    titles_str = "\n".join(
        [f"- [{n.get('source', 'Unknown Source')}] {n['title']}" for n in fresh_news[:MAX_FLASH_HEADLINES]]
    )
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงินระดับโลก
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}

    เลือกข่าวที่ "ด่วนและสำคัญที่สุดในเชิงเศรษฐกิจ" จำนวน 2 ข่าว
    โดยพิจารณาความน่าเชื่อถือของสำนักข่าวด้วย พยายามเลือกจากคนละสำนักข่าว
    (ถ้าข่าวมีความรุนแรงหรือสงคราม ให้สรุปเฉพาะผลกระทบทางเศรษฐกิจเท่านั้น ห้ามใส่ลิงก์)

    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวที่เลือก",
            "summary": "อธิบายว่าเกิดอะไรขึ้นและทำไมถึงสำคัญ 3-4 บรรทัด (ภาษาไทย)",
            "impact": "ผลกระทบต่อตลาดและนักลงทุนโดยตรง 1-2 ประโยค (ภาษาไทย)"
        }}
    ]
    """
    try:
        ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')

        # 🌟 1. ดักจับกรณี AI ไม่ยอมตอบเป็น JSON
        try:
            analysis_list = json.loads(result_text)
            # รองรับกรณี AI ส่งกลับมาเป็น object เดี่ยว (ไม่เป็น array)
            if isinstance(analysis_list, dict):
                analysis_list = [analysis_list]
        except json.JSONDecodeError:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News Error:** AI ไม่ได้ตอบเป็น JSON!\n\n**ข้อความที่ AI ตอบมา:**\n{result_text[:500]}")
            return

        if not isinstance(analysis_list, list) or len(analysis_list) == 0:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News Error:** ข้อมูลแหว่ง\n\n**JSON ที่ได้:**\n{result_text[:300]}")
            return

        # 🌟 2. สร้าง sections สำหรับแต่ละข่าว
        sections = []
        for item in analysis_list[:2]:
            title = _normalize_news_title(
                item.get('original_title') or item.get('title') or item.get('headline') or ''
            )
            summary = item.get('summary') or item.get('content') or item.get('description') or ''
            impact = item.get('impact', '')

            if not title or not summary:
                continue
            # 🌟 cross-dedup: ใช้ category "news" ร่วมกับ Digest (skip when force=True)
            if not force and not _claim_dispatch_once("news", title):
                continue

            summary = _compact_news_text(summary, max_chars=400, max_lines=5)
            impact_text = _compact_news_text(impact, max_chars=150, max_lines=2) if impact else ''
            impact_line = f"\n⚡️ *ผลกระทบ:* {impact_text}" if impact_text else ''
            sections.append(f"📌 *{title}*\n{summary}{impact_line}")
            if not force:
                sent_pro_news.add(title)

        if not sections:
            return

        # ป้องกันหน่วยความจำเต็ม
        if len(sent_pro_news) > 500:
            sent_pro_news.clear()

        msg = "🚨 *Flash News*\n\n" + "\n\n".join(sections)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
        recipients = [str(pro[0]) for pro in cur.fetchall()
                      if check_subscription(pro[0]) == 'pro'
                      and should_send_user_notification(pro[0], category="flash_news")]
        conn.close()
        if force and str(ADMIN_ID) not in recipients:
            recipients.insert(0, str(ADMIN_ID))
        count = 0
        for uid in recipients:
            try:
                bot_instance.send_message(uid, msg, parse_mode='Markdown')
                count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"[FlashNews] ส่งให้ {uid} ไม่สำเร็จ: {e}")
        print(f"[FlashNews] ส่งสำเร็จ {count} คน ({len(sections)} ข่าว)")

    except Exception as e:
        # 🌟 3. ดักจับกรณี API พัง หรือโดนบล็อคเนื้อหาความรุนแรง
        try:
            error_msg = str(e)
            if "Safety" in error_msg or "blocked" in error_msg.lower():
                bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News สะดุด:** AI ปฏิเสธการสรุปข่าวเนื่องจากติดฟิลเตอร์คำรุนแรง (Safety Policy)")
            else:
                bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News System Error:** {error_msg}")
        except Exception:
            pass

# ==========================================
# 🌟 ระบบส่งข่าว 4 ชั่วโมง (Digest News)
# ==========================================
def check_and_broadcast_pro_news(bot_instance, force=False):
    fresh_news = get_fresh_global_news()
    if not fresh_news: return
    
    titles_str = "\n".join(
        [f"- [{n.get('source', 'Unknown Source')}] {n['title']}" for n in fresh_news[:MAX_DIGEST_HEADLINES]]
    )
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงิน
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}

    เลือกข่าวเชิงเศรษฐกิจ/การลงทุน ที่ "สำคัญที่สุด" 2 ข่าว
    พยายามให้มาจากคนละสำนักข่าวถ้าเป็นไปได้
    (เน้นเรื่องเศรษฐกิจ หลีกเลี่ยงเนื้อหาความรุนแรง)

    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวต้นฉบับที่เลือก",
            "summary": "อธิบายว่าเกิดอะไรขึ้นและทำไมสำคัญ 3-4 บรรทัด (ภาษาไทย)",
            "impact": "ผลกระทบต่อตลาดและนักลงทุน 1-2 ประโยค (ภาษาไทย)"
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
        # 🌟 VIP ก็ได้รับ Digest ด้วย
        cur.execute("SELECT user_id FROM users WHERE role IN ('pro', 'vip')")
        eligible_users = []
        for (uid,) in cur.fetchall():
            role = check_subscription(uid)
            if role in ('pro', 'vip') and should_send_user_notification(uid, category="digest_news"):
                eligible_users.append(uid)
        cur.close()
        if force and str(ADMIN_ID) not in [str(u) for u in eligible_users]:
            eligible_users.insert(0, ADMIN_ID)
        if not eligible_users:
            conn.close()
            return
        sent_to_users = set()
        digest_sections = []

        for item in analysis_list[:MAX_DIGEST_ITEMS]:
            title = _normalize_news_title(item.get('original_title', ''))
            summary = item.get('summary', '')

            if title and summary:
                # 🌟 cross-dedup: ใช้ category "news" ร่วมกับ Flash News (skip when force=True)
                if not force and not _claim_dispatch_once("news", title):
                    continue
                summary = _compact_news_text(summary, max_chars=400, max_lines=5)
                impact = _compact_news_text(item.get('impact', ''), max_chars=150, max_lines=2)
                impact_line = f"\n⚡️ *ผลกระทบ:* {impact}" if impact else ''
                digest_sections.append(
                    f"**{len(digest_sections) + 1}. {title}**\n{summary}{impact_line}"
                )
                if not force:
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
            except Exception as e:
                print(f"[Digest] ส่งให้ {uid} ไม่สำเร็จ: {e}")
        for uid in sent_to_users:
            mark_digest_sent(uid)
        conn.close()
    except Exception as e:
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Digest News Error:** {str(e)[:100]}...")
        except Exception:
            pass


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
            except Exception as e:
                print(f"[PriceAlert] ดึงราคา {sym} ไม่สำเร็จ: {e}")
            
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
    def _fetch_with_change(ticker_sym):
        try:
            hist = yf.Ticker(ticker_sym).history(period='5d')['Close']
            if len(hist) < 2:
                return None, None
            prev = hist.iloc[-2]
            curr = hist.iloc[-1]
            if math.isnan(curr) or math.isnan(prev) or prev == 0:
                return None, None
            return float(curr), float((curr - prev) / prev * 100)
        except Exception:
            return None, None

    tickers = [
        ('^GSPC',   'S&P 500',     'จุด'),
        ('^SET.BK', 'SET Index',   'จุด'),
        ('BTC-USD', 'Bitcoin',     'ดอลลาร์'),
        ('GC=F',    'ทองคำโลก',   'ดอลลาร์'),
        ('CL=F',    'น้ำมันดิบ',  'ดอลลาร์'),
    ]

    date_str = (datetime.utcnow() + timedelta(hours=7)).strftime('%d %b %Y')
    parts = [f"ข้อมูลตลาด ณ วันที่ {date_str}:"]
    for sym, label, unit in tickers:
        price, chg = _fetch_with_change(sym)
        if price is None:
            continue
        direction = "ขึ้น" if chg >= 0 else "ลง"
        parts.append(
            f"{label} อยู่ที่ {price:,.0f} {unit} ({direction} {abs(chg):.1f}%)"
        )

    if len(parts) == 1:
        print("⚠️ [Podcast] ดึงข้อมูลตลาดไม่ได้เลย ตลาดอาจยังไม่เปิด")
        return "ข้อมูลตลาดยังไม่พร้อม ตลาดอาจยังไม่เปิดหรือเน็ตมีปัญหา"
    return ' | '.join(parts)

def _clean_podcast_script(text: str) -> str:
    text = text.replace('*', '').replace('#', '')
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    lines = text.splitlines()
    lines = [l for l in lines if not re.match(r'^\s*[^\n]{1,30}:\s*$', l)]
    return '\n'.join(lines).strip()

def get_stock_spotlight_news():
    """ดึงข่าวรายหุ้น 3 ตัวที่น่าสนใจสำหรับ podcast
    ใช้ top-watched symbols ในระบบก่อน (1 query DB) fallback เป็น default pool
    """
    default_pool = [
        'NVDA', 'AAPL', 'TSLA', 'META', 'AMZN', 'MSFT', 'GOOGL',
        'AMD', 'NFLX', 'BABA', 'COIN',
        'PTT.BK', 'AOT.BK', 'ADVANC.BK', 'GULF.BK', 'SCB.BK', 'CPALL.BK',
        'BTC-USD', 'ETH-USD',
    ]
    try:
        top_syms = get_top_watched_symbols(10)
    except Exception:
        top_syms = []

    # top-watched มาก่อน เติม default ถ้ายังไม่ครบ
    candidates = top_syms + [s for s in default_pool if s not in top_syms]

    results = []
    for sym in candidates:
        if len(results) >= 3:
            break
        try:
            news_items = yf.Ticker(sym).news
            if not news_items:
                continue
            headline = news_items[0].get('title', '').strip()
            if headline:
                results.append(f"{sym}: {headline}")
        except Exception as e:
            print(f"[Podcast] ดึงข่าว {sym} ไม่สำเร็จ: {e}")
    return results


def generate_podcast_script(market_info):
    # ข่าวภาพรวมตลาด
    try:
        recent_news = get_fresh_global_news()
        news_context = "\n".join([f"- {n['title']}" for n in recent_news[:5]]) if recent_news else "ไม่มีข่าวล่าสุด"
    except Exception:
        news_context = "ไม่มีข่าวล่าสุด"

    # ข่าวรายหุ้น
    try:
        stock_news = get_stock_spotlight_news()
        stock_news_context = "\n".join([f"- {s}" for s in stock_news]) if stock_news else "ไม่มีข้อมูล"
    except Exception:
        stock_news_context = "ไม่มีข้อมูล"

    prompt = f"""
    คุณคือนักจัดรายการวิทยุการลงทุนชื่อ 'Apex AI' กำลังออกอากาศรายการ 'Apexify Morning Briefing'

    ข้อมูลตลาดวันนี้: {market_info}

    พาดหัวข่าวภาพรวมตลาดล่าสุด:
    {news_context}

    ข่าวรายหุ้นสำคัญ (เลือกเล่า 2-3 ตัวที่น่าสนใจที่สุด):
    {stock_news_context}

    ตอบกลับมาเฉพาะบทพูดที่จะอ่านออกอากาศได้ทันที ความยาวประมาณ 3 ถึง 4 นาที
    ห้ามมีคำอธิบาย ห้ามมี label ห้ามมีวงเล็บ ห้ามมีหัวข้อ ห้ามบอกว่ากำลังจะทำอะไร เริ่มพูดได้เลย

    เนื้อหาที่ต้องครอบคลุมแบบเนียนๆ:
    1. ทักทายยามเช้าแบบเป็นกันเอง
    2. เล่าภาพรวมตลาดพร้อมความหมายของตัวเลข ไม่ใช่แค่บอกตัวเลขเฉยๆ
    3. เจาะข่าวรายหุ้น 2-3 ตัวที่มีข่าวน่าสนใจ อธิบายว่ากระทบนักลงทุนอย่างไร
    4. ปิดด้วยมุมคิดหรือกำลังใจสำหรับนักลงทุน

    ข้อกำหนด:
    - ใช้ภาษาพูดธรรมชาติ น่าฟัง มีพลัง ไม่เวอร์
    - อธิบายเหมือนเล่าให้คนฟังตอนขับรถตอนเช้า
    - ห้ามใช้ Bullet Point ดอกจัน แฮชแท็ก หัวข้อย่อย วงเล็บ หรือ label ทุกชนิด
    - อ่านตัวเลขแบบกลมๆ ฟังง่าย
    - อย่างน้อย 4 ย่อหน้า และ 12 ประโยค
    """
    try:
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return _clean_podcast_script(res.text)
    except Exception as e:
        print(f"❌ [Podcast] generate_podcast_script ล้มเหลว: {e}")
        return (
            "สวัสดีตอนเช้าครับนักลงทุนทุกท่าน เช้านี้ภาพรวมตลาดยังอยู่ในโหมดติดตามทิศทางต่อ "
            "แม้ตัวเลขสำคัญหลายตัวจะยังไม่ได้เหวี่ยงแรงมาก แต่ก็สะท้อนว่าตลาดกำลังเลือกทางกันอยู่ "
            "วันนี้เลยเป็นวันที่ควรโฟกัสกับการคุมจังหวะและวางแผนให้รอบคอบ ขอให้ทุกคนลงทุนอย่างมีสติและเริ่มวันด้วยพลังที่ดีครับ"
        )

async def create_and_send_podcast(bot_instance, force=False):
    try:
        if not force and not _claim_dispatch_once("morning_podcast", _current_thai_date_str()):
            print("⏭️ [Podcast] ข้ามการส่งซ้ำของวันนี้")
            return
        print("🌍 [Podcast] กำลังสร้างสคริปต์และอัดเสียง...")
        market_info = get_podcast_market_data()
        script = generate_podcast_script(market_info)

        filename = "apexify_morning.mp3"
        communicate = edge_tts.Communicate(script, "th-TH-PremwadeeNeural") # เสียงพรีมวดี
        await communicate.save(filename)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE role IN ('pro', 'vip')")
        pro_users = cur.fetchall()
        cur.close()
        conn.close()

        count = 0
        for row in pro_users:
            user_id = row[0]
            if check_subscription(user_id) in ('pro', 'vip') and should_send_user_notification(user_id, category="morning_briefing"):
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
                except Exception as e:
                    print(f"[Podcast] ส่งให้ {user_id} ไม่สำเร็จ: {e}")

        if count > 0:
            print(f"✅ [Podcast] ส่งเสียงสำเร็จ {count} คน")

    except Exception as e:
        print(f"❌ [Podcast] Error: {e}")
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Podcast Error:** สร้าง/ส่ง Podcast ล้มเหลว\n`{str(e)[:200]}`", parse_mode="Markdown")
        except Exception:
            pass

# US Economic Calendar 2026 — อัปเดตทุกต้นปี
ECONOMIC_CALENDAR_2026 = [
    # (date_str, event_name, importance)  importance: 🔴=high 🟡=medium
    ("2026-01-07",  "NFP (ตลาดแรงงาน)",          "🔴"),
    ("2026-01-15",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-01-28",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-01-29",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-02-04",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-02-12",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-02-27",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-03-06",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-03-12",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-03-18",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-03-19",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-03-27",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-04-02",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-04-14",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-04-29",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-04-30",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-05-01",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-05-13",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-05-29",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-06-05",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-06-11",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-06-17",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-06-18",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-06-26",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-07-02",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-07-15",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-07-29",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-07-30",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-08-07",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-08-13",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-08-28",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-09-04",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-09-10",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-09-16",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-09-17",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-09-25",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-10-02",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-10-15",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-10-28",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-10-29",  "FOMC ประกาศดอกเบี้ย",        "🔴"),
    ("2026-11-06",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-11-12",  "CPI (เงินเฟ้อ)",              "🔴"),
    ("2026-11-25",  "PCE (เงินเฟ้อ Fed ชอบ)",     "🟡"),
    ("2026-12-04",  "NFP (ตลาดแรงงาน)",           "🔴"),
    ("2026-12-09",  "FOMC Meeting เริ่ม",          "🔴"),
    ("2026-12-10",  "FOMC ประกาศดอกเบี้ย + CPI",  "🔴"),
]

def _get_upcoming_economic_events(days_ahead=3):
    today = datetime.now().date()
    upcoming = []
    for date_str, event, importance in ECONOMIC_CALENDAR_2026:
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        delta = (event_date - today).days
        if 0 <= delta <= days_ahead:
            if delta == 0:
                label = "วันนี้"
            elif delta == 1:
                label = "พรุ่งนี้"
            else:
                label = f"อีก {delta} วัน"
            upcoming.append(f"{importance} **{event}** ({label})")
    return upcoming

# ==========================================
# ==========================================
# 🌟 ฟีเจอร์ Morning Apexify Briefing (08:30 น.)
# ==========================================
def send_morning_briefing(bot_instance, force=False):
    try:
        if not force and not _claim_dispatch_once("morning_briefing", _current_thai_date_str()):
            print("⏭️ [Morning Briefing] ข้ามการส่งซ้ำของวันนี้")
            return
        sp500 = yf.Ticker('^GSPC').history(period='1d')
        btc = yf.Ticker('BTC-USD').history(period='1d')
        gold = yf.Ticker('GC=F').history(period='1d') 
        
        fresh_news = get_fresh_global_news()
        news_titles = (
            "\n".join([f"- [{n.get('source', 'Unknown Source')}] {n['title']}" for n in fresh_news[:5]])
            if fresh_news else "ไม่มีข่าวเด่น"
        )
        
        if not sp500.empty and not btc.empty:
            sp500_close = sp500['Close'].iloc[-1]
            btc_close = btc['Close'].iloc[-1]
            gold_close = gold['Close'].iloc[-1] if not gold.empty else 0
            movers_text = _get_morning_market_movers_text()
            macro_assets_text = _get_morning_macro_assets_text()
            
            # 🌟 อัปเดต Prompt ใหม่ บังคับให้สั้นและห้ามทวนคำสั่ง!
            prompt = f"""
            คุณคือนักวิเคราะห์การเงินที่เก่งกาจและเป็นกันเอง 
            จงสรุปแนวโน้มตลาดเช้านี้สั้นๆ แบบฟันธงเพื่อส่งให้เทรดเดอร์ (ความยาวไม่เกิน 4 บรรทัดเท่านั้น!)
            
            ข้อมูลตลาดเมื่อคืน: S&P500={sp500_close:.2f}, Bitcoin={btc_close:.2f}, ทองคำ={gold_close:.2f}
            สินทรัพย์มหภาคที่ต้องจับตา:
            {macro_assets_text or "ไม่มีข้อมูล ETF ทองคำ น้ำมัน หรือดอลลาร์เพิ่มจากระบบ"}
            หุ้นที่น่าจับตาเมื่อคืน:
            {movers_text or "ไม่มีข้อมูลเพิ่มจากหุ้นที่ระบบติดตาม"}
            พาดหัวข่าวสำคัญ:
            {news_titles}
            
            ข้อบังคับเด็ดขาด: 
            1. ห้ามทวนคำสั่งหรือเขียนหัวข้อใดๆ ทั้งสิ้น
            2. ห้ามแยกข้อ 1-2-3 ให้เขียนบรรยายรวดเดียวจบ
            3. พิมพ์มาแค่เนื้อหาสรุป 3-4 บรรทัดจบ พร้อมให้กำลังใจท้ายข้อความ
            """
            ai_check = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            summary = ai_check.text.strip()
            movers_section = (
                f"📈 **หุ้นน่าจับตาคืนก่อน:**\n{movers_text}\n\n"
                if movers_text
                else ""
            )
            macro_assets_section = (
                f"🌍 **ETF / ทองคำ / น้ำมัน / ดอลลาร์:**\n{macro_assets_text}\n\n"
                if macro_assets_text
                else ""
            )
            econ_events = _get_upcoming_economic_events(days_ahead=3)
            econ_section = (
                "📅 **เหตุการณ์เศรษฐกิจใกล้นี้:**\n" + "\n".join(f"• {e}" for e in econ_events) + "\n\n"
                if econ_events else ""
            )

            msg = (
                f"🌅 **Apexify Morning Briefing** 🌅\n\n"
                f"📊 **สรุปตลาดโลกเมื่อคืน:**\n"
                f"• S&P 500: {sp500_close:,.2f}\n"
                f"• Bitcoin: {btc_close:,.2f}\n"
                f"• ทองคำโลก (Gold): {gold_close:,.2f}\n\n"
                f"{macro_assets_section}"
                f"{movers_section}"
                f"{econ_section}"
                f"🤖 **มุมมอง Apexify วันนี้:**\n{summary}\n\n"
                f"🔥 *ขอให้พอร์ตเขียวๆ ตลอดวันครับ!*\n\n"
                f"{MORNING_BRIEFING_LEGAL_DISCLAIMER}"
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
                    except Exception as e:
                        print(f"[MorningBriefing] ส่งให้ {pro[0]} ไม่สำเร็จ: {e}")
                    
            cur.close()
            conn.close()
            if count > 0: print(f"✅ ส่ง Morning Briefing สำเร็จ {count} คน")
    except Exception as e:
        print(f"❌ [MorningBriefing] Error: {e}")
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Morning Briefing Error:** {str(e)[:200]}", parse_mode="Markdown")
        except Exception:
            pass

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
        except Exception as e:
            print(f"[XDAlert] ดึงข้อมูล XD ล้มเหลวสำหรับ {symbol}: {e}")

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
                except Exception as e:
                    print(f"[XDAlert] ส่งให้ {pro[0]} ไม่สำเร็จ: {e}")
        cur.close()
        conn.close()
# ==========================================
# 🌟 ฟีเจอร์ใหม่: Daily Portfolio Summary (สรุปพอร์ตตี 5)
# ==========================================
def send_daily_portfolio_summary(bot_instance):
    from database import get_user_portfolio, get_connection # ระวังการ import
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    import yfinance as yf
    
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
        rows = []

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
            rows.append((ticker, shares, avg_cost, live_price, profit, profit_pct))

        total_profit = current_value - total_invested
        total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
        total_icon = "🟢" if total_profit >= 0 else "🔴"

        lines = [f"🔔 <b>สรุปพอร์ตประจำวัน</b>  ({len(rows)} หลักทรัพย์)\n"]
        for t, s, ac, lp, pf, pp in rows:
            icon = "🟢" if pf >= 0 else "🔴"
            sign = "+" if pf >= 0 else ""
            lines.append(
                f"{icon} <b>{t}</b>  {s:,.4g} หุ้น\n"
                f"   ทุน {ac:,.2f}  →  ล่าสุด {lp:,.2f}\n"
                f"   {sign}{pf:,.2f}  ({sign}{pp:.2f}%)\n"
            )
        lines.append(
            f"─────────────────────\n"
            f"💰 <b>มูลค่ารวม:</b> {current_value:,.2f}\n"
            f"💵 <b>ต้นทุนรวม:</b> {total_invested:,.2f}\n"
            f"{total_icon} <b>กำไร/ขาดทุนรวม:</b> {'+' if total_profit >= 0 else ''}{total_profit:,.2f}  ({'+' if total_profit_pct >= 0 else ''}{total_profit_pct:.2f}%)"
        )

        try:
            bot_instance.send_message(user_id, "\n".join(lines), parse_mode='HTML')
            count += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"[PortfolioSummary] ส่งให้ {user_id} ไม่สำเร็จ: {e}")

            
    if count > 0: print(f"✅ ส่งสรุปพอร์ตสำเร็จ {count} คน")

# ==========================================
# 🔔 แจ้งเตือนผู้ใช้ที่แพ็กเกจใกล้หมดอายุ
# ==========================================
def send_expiry_warnings(bot_instance):
    """แจ้งเตือน VIP/PRO ที่หมดอายุใน 3 วัน และ 1 วัน"""
    for days_left in (3, 1):
        try:
            users = get_expiring_subscriptions(days_left)
        except Exception as e:
            print(f"[expiry_warnings] get_expiring_subscriptions error: {e}")
            continue
        for user_id, role, expiry_date in users:
            role_label = "💎 VIP" if role == "vip" else "👑 PRO"
            day_word = "3 วัน" if days_left == 3 else "พรุ่งนี้"
            msg = (
                f"⚠️ **แพ็กเกจของคุณใกล้หมดอายุแล้ว!**\n\n"
                f"📦 แพ็กเกจ: {role_label}\n"
                f"⏰ หมดอายุ: {str(expiry_date)[:10]}\n"
                f"📅 เหลือเวลา: {day_word}\n\n"
                f"กดปุ่ม **💎 บัญชี / VIP** เพื่อต่ออายุและใช้งานต่อเนื่องได้เลยครับ!"
            )
            try:
                bot_instance.send_message(user_id, msg, parse_mode="Markdown")
            except Exception as e:
                print(f"[expiry_warnings] send to {user_id} failed: {e}")
    print(f"[expiry_warnings] ส่งแจ้งเตือนหมดอายุเรียบร้อย")

def run_alert_loop(bot_instance=None):
    """Main alert loop — started as a daemon Thread from main.py"""
    if bot_instance is None:
        bot_instance = bot

    _init_sent_pro_news()
    print("🚀 Apexify Alert System (PRO + VIP selected features) is Running...")

    last_hourly_news_time = time.time() - FLASH_NEWS_INTERVAL_SECONDS
    last_global_news_time = time.time() - DIGEST_NEWS_CHECK_INTERVAL_SECONDS
    last_stock_news_check_time = time.time() - STOCK_NEWS_CHECK_INTERVAL_SECONDS
    last_morning_briefing_date = None
    last_xd_check_date = None
    last_podcast_date = None
    last_portfolio_summary_date = None
    last_downgrade_date = None
    last_expiry_warning_date = None

    while True:
        current_time = time.time()
        thai_time = datetime.utcnow() + timedelta(hours=7)
        current_date_str = thai_time.strftime("%Y-%m-%d")

        if thai_time.hour == 0 and last_downgrade_date != current_date_str:
            auto_downgrade_expired_users()
            print(f"🧹 [{current_date_str}] Auto-Downgrade: อัปเดต DB ปรับยศคนหมดอายุเรียบร้อย")
            reset_daily_free_usage()
            send_expiry_warnings(bot_instance)
            last_downgrade_date = current_date_str
            last_expiry_warning_date = current_date_str

        if thai_time.hour == 8 and thai_time.minute >= 30:
            if last_morning_briefing_date != current_date_str:
                send_morning_briefing(bot_instance)
                last_morning_briefing_date = current_date_str

        if thai_time.hour == 8 and thai_time.minute >= 0 and thai_time.minute < 30:
            if last_podcast_date != current_date_str:
                asyncio.run(create_and_send_podcast(bot_instance))
                last_podcast_date = current_date_str

        if last_xd_check_date != current_date_str:
            check_xd_alerts()
            last_xd_check_date = current_date_str

        if thai_time.hour == 5 and thai_time.minute >= 0:
            if last_portfolio_summary_date != current_date_str:
                send_daily_portfolio_summary(bot_instance)
                last_portfolio_summary_date = current_date_str

        if current_time - last_hourly_news_time >= FLASH_NEWS_INTERVAL_SECONDS:
            broadcast_hourly_urgent_news(bot_instance)
            last_hourly_news_time = time.time()

        if current_time - last_global_news_time >= DIGEST_NEWS_CHECK_INTERVAL_SECONDS:
            check_and_broadcast_pro_news(bot_instance)
            last_global_news_time = time.time()

        if current_time - last_stock_news_check_time >= STOCK_NEWS_CHECK_INTERVAL_SECONDS:
            active_symbols = get_all_active_symbols()
            for symbol in (active_symbols or []):
                try:
                    check_hot_news(symbol)
                except Exception as e:
                    print(f"❌ [StockNewsLoop] {symbol}: {e}")
            last_stock_news_check_time = time.time()
            print(f"[StockNews] เช็คข่าวรายตัวเสร็จแล้ว ({len(active_symbols or [])} symbols)")

        check_market_conditions()
        check_custom_price_alerts()

        time.sleep(300)


if __name__ == "__main__":
    init_db()
    try:
        init_new_features_db()
    except Exception as e:
        print("DB Init Error:", e)

    auto_downgrade_expired_users()
    print("🧹 กวาดล้าง DB ทันทีที่เปิดระบบเรียบร้อยแล้ว!")
    run_alert_loop(bot)

