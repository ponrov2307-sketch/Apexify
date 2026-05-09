import time
import hashlib
import math
import difflib
import traceback
from datetime import datetime, timedelta, timezone
import telebot
import requests 
from config import TELEGRAM_TOKEN, ADMIN_ID, GEMINI_API_KEY, gemini_client
from technical_tools import calculate_technical_indicators
import intraday_volume
import psycopg2
from database import (get_all_active_symbols, get_users_watching, init_db, check_subscription,
                      get_connection, log_alert, get_all_active_price_alerts, deactivate_price_alert,
                      auto_downgrade_expired_users, init_new_features_db,
                      should_send_user_notification, mark_digest_sent,
                      reset_daily_free_usage, get_expiring_subscriptions,
                      get_top_watched_symbols, get_all_earnings_subscriptions,
                      mark_user_inactive, get_active_users,
                      get_pending_plans, update_plan_outcome, expire_stale_plans,
                      load_all_alert_states, save_alert_state,
                      is_earnings_notified, mark_earnings_notified)
from bot_utils import safe_send_with_retry
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

import threading as _threading

last_alert_state = {}  # populated from DB ตอน run_alert_loop เริ่ม — ดู _hydrate_alert_state()

# 🛡 sent_pro_news + _rss_cache อ่าน/เขียนจากหลาย thread (Flash + Digest + alert loop)
# กัน race "Set changed during iteration" + cache อ่านขณะเขียน
sent_pro_news = set()
_sent_news_lock = _threading.Lock()
_rss_cache_lock = _threading.Lock()


def _set_alert_state(symbol, kind, new_state):
    """Update in-memory + persist DB. Save เฉพาะตอน state เปลี่ยน — ไม่ flood DB"""
    bucket = last_alert_state.setdefault(symbol, {})
    if bucket.get(kind) != new_state:
        bucket[kind] = new_state
        save_alert_state(symbol, kind, new_state)


def _hydrate_alert_state():
    """โหลด alert state จาก DB → fix bug duplicate alert หลัง restart"""
    try:
        loaded = load_all_alert_states()
        last_alert_state.clear()
        last_alert_state.update(loaded)
        total = sum(len(v) for v in loaded.values())
        print(f"[AlertState] โหลด {total} state จาก DB ({len(loaded)} symbols) — กัน duplicate alert", flush=True)
    except Exception as e:
        print(f"[AlertState] hydrate ล้มเหลว — เริ่มต้นด้วย empty state: {e}", flush=True)


def safe_send(bot_instance, user_id, text, **kwargs):
    """ส่งข้อความอย่างปลอดภัย — wrap safe_send_with_retry ให้ทุก alert path ได้ retry ฟรี
    Backwards-compat: same signature/return value (True/False) เหมือนเดิม
    """
    return safe_send_with_retry(bot_instance, user_id, text, retries=3, **kwargs)


def _is_gemini_overloaded_error(err):
    err_str = str(err)
    return (
        '503' in err_str
        or 'UNAVAILABLE' in err_str
        or 'high demand' in err_str.lower()
        or 'overloaded' in err_str.lower()
    )


def _is_gemini_model_unavailable_error(err):
    err_str = str(err)
    return (
        '404' in err_str
        or 'NOTFOUND' in err_str
        or 'no longer available' in err_str.lower()
        or 'not found' in err_str.lower()
    )


def _gemini_generate_with_retry(prompt, model='gemini-2.5-flash', retries=4, delay=20):
    """เรียก Gemini พร้อม retry + exponential backoff + fallback model
    Retry เมื่อเจอ 503 (overload) หรือ 404 (model deprecated)
    """
    # ใช้โมเดลตระกูล 2.5 ทั้งหมด (2.0-flash ถูก deprecated แล้ว 2026)
    fallback_chain = [model, 'gemini-2.5-flash-lite', 'gemini-2.5-pro']
    last_err = None
    for attempt in range(retries + 1):
        current_model = fallback_chain[min(attempt, len(fallback_chain) - 1)]
        try:
            return client.models.generate_content(model=current_model, contents=prompt)
        except Exception as e:
            last_err = e
            # 404: โมเดลไม่มี → ข้ามไปโมเดลถัดไปทันที (ไม่ต้องรอ)
            if _is_gemini_model_unavailable_error(e):
                if attempt < retries:
                    print(f"[Gemini] 404 {current_model} deprecated/unavailable, try next model", flush=True)
                    continue
            # 503: overload → wait แล้ว retry
            if _is_gemini_overloaded_error(e):
                if attempt < retries:
                    wait = delay * (2 ** attempt)
                    print(f"[Gemini] 503 {current_model} try {attempt+1}/{retries}, wait {wait}s", flush=True)
                    time.sleep(wait)
                    continue
            raise  # error อื่นๆ throw ทันที
    raise last_err

# 🌟 เก็บประวัติข่าวที่เคยส่งไปแล้วเพื่อกันส่งซ้ำ
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
    # 🌟 ยิง Thai quality guard ก่อน trim (กัน AI พิมพ์แปลก)
    try:
        from ai_analyzer import _fix_thai_typos
        compact = _fix_thai_typos(compact)
    except Exception:
        pass
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


def _is_duplicate_news(title, existing_titles, threshold=0.62):
    """Return True if title is too similar to any existing title (difflib ratio)."""
    t = title.lower()
    for ex in existing_titles:
        if difflib.SequenceMatcher(None, t, ex.lower()).ratio() >= threshold:
            return True
    return False


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
        rows = cur.fetchall()
        conn.close()
        with _sent_news_lock:
            for (raw_key,) in rows:
                if raw_key:
                    sent_pro_news.add(raw_key)
            count = len(sent_pro_news)
        print(f"[init] โหลดประวัติ sent_pro_news จาก DB: {count} รายการ")
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
    """Morning macro briefing — batch fetch (1 HTTP) แทน per-asset loop"""
    syms = list(MORNING_MACRO_ASSETS.keys())
    if not syms:
        return ""
    try:
        batch = yf.download(
            syms, period="5d",
            group_by='ticker', progress=False, threads=True,
            auto_adjust=False,
        )
    except Exception as e:
        print(f"[MorningMacro] batch download fail: {e}", flush=True)
        return ""

    lines = []
    for symbol, label in MORNING_MACRO_ASSETS.items():
        try:
            sym_data = batch[symbol] if symbol in batch.columns.get_level_values(0) else batch
            closes = sym_data["Close"].dropna()
            if len(closes) < 2:
                continue
            last_close = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])
            if prev_close <= 0:
                continue
            pct_change = ((last_close - prev_close) / prev_close) * 100
            emoji = "🟢" if pct_change >= 0 else "🔴"
            lines.append(f"{emoji} {label}: {last_close:,.2f} ({pct_change:+.2f}%)")
        except Exception as e:
            print(f"[MorningMacro] {symbol} parse fail: {e}", flush=True)
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

        full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
        safe_send(bot, user_id, full_msg, parse_mode="Markdown", disable_web_page_preview=True)
        time.sleep(0.5)

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
                last_alert_state[symbol] = {'rsi': 'normal', 'cross': 'normal', 'breakout': 'normal', 'gap': 'normal', 'accel': 'normal'}

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
                _set_alert_state(symbol, 'rsi', rsi_condition)
            elif rsi_condition == 'normal':
                _set_alert_state(symbol, 'rsi', 'normal')

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
                _set_alert_state(symbol, 'cross', cross_condition)

            # 🚀 Intraday Breakout — เปลี่ยนจาก daily close เป็น 5m close + volume ยืนยัน
            # เก่า: price (daily) > resistance → จับตอนปลายวัน สาย 5-6 ชม.
            # ใหม่: 5m close ทะลุ daily S/R + vol > 1.5x of 1hr → จับภายใน 5 นาที + กัน false breakout
            breakout_condition = 'normal'
            msg = None
            try:
                br = intraday_volume.detect_breakout_intraday(symbol, resistance, support, vol_confirm_ratio=1.5)
                if br and br.get("direction"):
                    cur_close = br["current_close"]
                    vol_ratio = br["vol_ratio"]
                    level = br.get("breakout_level") or 0
                    candle_time = br.get("candle_time")
                    time_str = (
                        candle_time.strftime("%H:%M")
                        if candle_time is not None and hasattr(candle_time, "strftime")
                        else "ล่าสุด"
                    )
                    if br["direction"] == "up":
                        breakout_condition = 'break_res'
                        msg = (
                            f"🚀 **RESISTANCE BREAKOUT (intraday)** 🚀\n"
                            f"หุ้น **{symbol}** ทะลุแนวต้าน **{level:.2f}** แล้ว!\n"
                            f"แคนเดิล {time_str}: ปิดที่ {cur_close:.2f} · vol {vol_ratio:.1f}x ของ 1 ชม.\n"
                            f"(ราคาปัจจุบัน: {price:.2f})"
                        )
                    else:
                        breakout_condition = 'break_sup'
                        msg = (
                            f"🩸 **SUPPORT BROKEN (intraday)** 🩸\n"
                            f"หุ้น **{symbol}** หลุดแนวรับ **{level:.2f}** ลงมาแล้ว ระวังแรงเทขาย!\n"
                            f"แคนเดิล {time_str}: ปิดที่ {cur_close:.2f} · vol {vol_ratio:.1f}x\n"
                            f"(ราคาปัจจุบัน: {price:.2f})"
                        )
            except Exception as e:
                print(f"⚠️ [BreakoutIntraday] {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)

            if breakout_condition != 'normal' and msg and breakout_condition != last_alert_state[symbol].get('breakout', 'normal'):
                send_alert_to_users(symbol, msg, alert_type="tech")
                log_alert(symbol, f"BREAKOUT_{breakout_condition.upper()}", price)
                _set_alert_state(symbol, 'breakout', breakout_condition)
            elif breakout_condition == 'normal':
                _set_alert_state(symbol, 'breakout', 'normal')

            # 🐳 Intraday Whale Alert — เปลี่ยนจาก daily volume → 5m bar
            # เหตุผล: daily volume สะสมทั้งวัน กว่าจะถึง 3x avg ก็ใกล้ปิดตลาด → alert สาย 5-6 ชม.
            # ใหม่: เทียบ 5m candle ปิดล่าสุดกับ avg ของ 12 candle ผ่านมา (1 ชม.) — detect ภายใน 5-10 นาที
            whale_condition = 'normal'
            msg = None
            try:
                spike = intraday_volume.detect_volume_spike(symbol, threshold=3.0, lookback_bars=12)
                # spike=None = fetch ล้มเหลว / session_open=False = ตลาดปิด → ทั้งคู่ skip
                if spike and spike.get("session_open") and spike.get("spike"):
                    ratio = spike["ratio"]
                    cur_close = spike["current_close"]
                    cur_open = spike["current_open"]
                    candle_time = spike.get("candle_time")
                    time_str = (
                        candle_time.strftime("%H:%M")
                        if candle_time is not None and hasattr(candle_time, "strftime")
                        else "ล่าสุด"
                    )
                    if cur_close >= cur_open:
                        whale_condition = 'buy_spike'
                        msg = (
                            f"🐳 **WHALE ALERT (มีวาฬเข้า!)** 🐳\n"
                            f"หุ้น **{symbol}** วอลุ่ม 5 นาทีพุ่ง **{ratio:.1f}x** ของ 1 ชม. ผ่านมา\n"
                            f"แคนเดิล {time_str}: {cur_open:.2f} → {cur_close:.2f} (เขียว)\n"
                            f"(ราคาปัจจุบัน: {price:.2f})"
                        )
                    else:
                        whale_condition = 'sell_spike'
                        msg = (
                            f"🩸 **WHALE DUMP (วาฬเทขาย!)** 🩸\n"
                            f"หุ้น **{symbol}** วอลุ่ม 5 นาทีพุ่ง **{ratio:.1f}x** ของ 1 ชม. ผ่านมา\n"
                            f"แคนเดิล {time_str}: {cur_open:.2f} → {cur_close:.2f} (แดง)\n"
                            f"(ราคาปัจจุบัน: {price:.2f})"
                        )
            except Exception as e:
                print(f"⚠️ [WhaleIntraday] {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)

            if whale_condition != 'normal' and msg and whale_condition != last_alert_state[symbol].get('whale', 'normal'):
                send_alert_to_users(symbol, msg, alert_type="whale")
                log_alert(symbol, f"WHALE_{whale_condition.upper()}", price)
                _set_alert_state(symbol, 'whale', whale_condition)
            elif whale_condition == 'normal':
                _set_alert_state(symbol, 'whale', 'normal')

            # 📐 Gap Open Alert — ตรวจ gap ใหญ่ตอนเปิดตลาด (เฉพาะ 30 นาทีแรก)
            # detect ทันทีตอนเปิด ไม่ต้องรอราคาวิ่งสะสมทั้งวัน
            gap_condition = 'normal'
            gap_msg = None
            try:
                prev_close = tech_data.get('prev_close')
                gap = intraday_volume.detect_gap_open(symbol, prev_close, threshold_pct=2.0, window_seconds=1800)
                if gap:
                    pct = gap['gap_pct']
                    open_p = gap['open_price']
                    pc = gap['prev_close']
                    if gap['direction'] == 'up':
                        gap_condition = 'gap_up'
                        gap_msg = (
                            f"📐 **GAP UP — เปิดสูงกว่าวานนี้** 📐\n"
                            f"หุ้น **{symbol}** เปิดที่ {open_p:.2f} ({pct:+.2f}%) จากปิดเมื่อวาน {pc:.2f}\n"
                            f"_จับตา momentum ตอนต้นวัน_"
                        )
                    else:
                        gap_condition = 'gap_down'
                        gap_msg = (
                            f"📐 **GAP DOWN — เปิดต่ำกว่าวานนี้** 📐\n"
                            f"หุ้น **{symbol}** เปิดที่ {open_p:.2f} ({pct:+.2f}%) จากปิดเมื่อวาน {pc:.2f}\n"
                            f"_ระวังแรงเทขายต่อ_"
                        )
            except Exception as e:
                print(f"⚠️ [GapOpen] {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)

            if gap_condition != 'normal' and gap_msg and gap_condition != last_alert_state[symbol].get('gap', 'normal'):
                send_alert_to_users(symbol, gap_msg, alert_type="tech")
                log_alert(symbol, f"GAP_{gap_condition.upper()}", price)
                _set_alert_state(symbol, 'gap', gap_condition)
            else:
                # Reset gap state เมื่อพ้นช่วงเปิดตลาด → กันไม่ให้ค้าง state ข้ามวัน
                # (detect_gap_open คืน None ถ้าพ้น 30 นาทีแรก)
                if gap_condition == 'normal' and last_alert_state[symbol].get('gap', 'normal') != 'normal':
                    secs = intraday_volume.time_since_session_open(symbol)
                    if secs is None or secs > 1800:
                        _set_alert_state(symbol, 'gap', 'normal')

            # ⚡ Price Acceleration — ตรวจ momentum spike (>3% ใน 30 นาที + vol confirm)
            # จับ "หุ้นวิ่งเร็ว" ก่อนที่ vol จะถึง 3x (whale threshold)
            accel_condition = 'normal'
            accel_msg = None
            try:
                accel = intraday_volume.detect_price_acceleration(symbol, lookback_bars=6, threshold_pct=3.0, vol_confirm=1.2)
                if accel and accel.get("vol_confirmed"):
                    pct = accel["change_pct"]
                    sp = accel["start_price"]
                    ep = accel["end_price"]
                    vr = accel["vol_ratio"]
                    if accel["direction"] == "up":
                        accel_condition = 'accel_up'
                        accel_msg = (
                            f"⚡ **PRICE ACCELERATION — วิ่งเร็ว** ⚡\n"
                            f"หุ้น **{symbol}** {sp:.2f} → {ep:.2f} ({pct:+.2f}%) ใน 30 นาที\n"
                            f"vol {vr:.1f}x ของช่วงก่อนหน้า · จังหวะ momentum ชัด"
                        )
                    else:
                        accel_condition = 'accel_down'
                        accel_msg = (
                            f"⚡ **PRICE ACCELERATION — เทเร็ว** ⚡\n"
                            f"หุ้น **{symbol}** {sp:.2f} → {ep:.2f} ({pct:+.2f}%) ใน 30 นาที\n"
                            f"vol {vr:.1f}x ของช่วงก่อนหน้า · ระวังต่อขาลง"
                        )
            except Exception as e:
                print(f"⚠️ [PriceAccel] {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)

            if accel_condition != 'normal' and accel_msg and accel_condition != last_alert_state[symbol].get('accel', 'normal'):
                send_alert_to_users(symbol, accel_msg, alert_type="tech")
                log_alert(symbol, f"ACCEL_{accel_condition.upper()}", price)
                _set_alert_state(symbol, 'accel', accel_condition)
            elif accel_condition == 'normal':
                _set_alert_state(symbol, 'accel', 'normal')

            time.sleep(2)
        except Exception as e:
            print(f"❌ [MarketConditions] ล้มเหลวสำหรับ {symbol}: {e}")

# ==========================================
# 🌟 ฟังก์ชันดึงข่าวรวมจากทุกสำนัก
# ==========================================
def get_fresh_global_news():
    """ดึงข่าวรวม — มี Cache 30 นาที ป้องกัน Flash & Digest ดึงซ้ำกัน
    🛡 Locked: rss_cache + sent_pro_news ทั้งคู่ access จากหลาย thread
    """
    now = time.time()
    with _rss_cache_lock:
        cache_ts = _rss_cache["ts"]
        cache_data = list(_rss_cache["data"])  # snapshot สำหรับใช้นอก lock
    if now - cache_ts < _RSS_CACHE_TTL and cache_data:
        with _sent_news_lock:
            sent_snapshot = set(sent_pro_news)
        return [n for n in cache_data if n["title"] not in sent_snapshot]

    urls = [
        # 🇺🇸 ข่าวเมกา / ตลาดโลก (Google News) — ลบ Thai news ออก ตามที่ user ขอ
        "https://news.google.com/rss/search?q=economy+OR+stock+market+OR+gold+OR+crypto+OR+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
        # 📊 Macro / Fed / Rates
        "https://news.google.com/rss/search?q=Federal+Reserve+OR+interest+rates+OR+inflation+OR+GDP+when:1d&hl=en-US&gl=US&ceid=US:en",
        # 🏦 Yahoo Finance market headlines
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
        # 📺 CNBC markets
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        # 📰 MarketWatch top stories
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
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
    with _rss_cache_lock:
        _rss_cache["data"] = balanced_news
        _rss_cache["ts"] = time.time()

    with _sent_news_lock:
        sent_snapshot = set(sent_pro_news)
    return [n for n in balanced_news if n["title"] not in sent_snapshot]

# ==========================================
# 🌟 ระบบส่งข่าวด่วนรายชั่วโมง (Flash News) - [อัปเกรดระบบดักจับ Error]
# ==========================================
def broadcast_hourly_urgent_news(bot_instance, force=False):
    fresh_news = get_fresh_global_news()
    if not fresh_news:
        try:
            bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News System:** ไม่พบข่าวใหม่จากสำนักข่าวเลย (อาจเกิดจาก Network หรือไม่มีข่าวจริงๆ)")
        except Exception as notify_err:
            print(f"[FlashNews] notify-admin failed: {notify_err}", flush=True)
        return
    
    titles_str = "\n".join(
        [f"- [{n.get('source', 'Unknown Source')}] {n['title']}" for n in fresh_news[:MAX_FLASH_HEADLINES]]
    )
    
    prompt = f"""
    คุณคือนักวิเคราะห์การเงินระดับโลก
    นี่คือพาดหัวข่าวล่าสุด:
    {titles_str}

    เลือกข่าวที่ "ด่วนและสำคัญที่สุดในเชิงเศรษฐกิจ" จำนวน 2 ข่าว จากคนละสำนักข่าวถ้าเป็นไปได้
    ถ้าหลายพาดหัวพูดถึงเรื่องเดียวกัน ให้เลือกเพียงข่าวเดียวจากกลุ่มนั้น (ห้ามซ้ำประเด็น)
    (ถ้าข่าวมีความรุนแรงหรือสงคราม ให้สรุปเฉพาะผลกระทบทางเศรษฐกิจเท่านั้น)

    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวที่เลือก",
            "emoji": "emoji 1-2 ตัวที่สื่อทิศทางตลาด เช่น 🔴📉 หรือ 🟢📈 หรือ 🟡⚡️",
            "headline_th": "พาดหัวสั้นๆ เป็นภาษาไทย ไม่เกิน 10 คำ",
            "summary": "สรุปสั้นๆ 1-2 ประโยค รวมผลกระทบต่อตลาดด้วย (ภาษาไทย)"
        }}
    ]
    """
    try:
        ai_check = _gemini_generate_with_retry(prompt)
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
        with _sent_news_lock:
            seen_titles = list(sent_pro_news)
        for item in analysis_list[:2]:
            original_title = _normalize_news_title(
                item.get('original_title') or item.get('title') or item.get('headline') or ''
            )
            emoji = item.get('emoji', '📌')
            headline_th = item.get('headline_th', '') or original_title
            summary = item.get('summary') or item.get('content') or item.get('description') or ''

            if not original_title or not summary:
                continue
            # 🌟 similarity dedup — กรองข่าวคล้ายกัน
            if not force and _is_duplicate_news(original_title, seen_titles):
                continue
            # 🌟 cross-dedup: ใช้ category "news" ร่วมกับ Digest (skip when force=True)
            if not force and not _claim_dispatch_once("news", original_title):
                continue

            summary = _compact_news_text(summary, max_chars=200, max_lines=2)
            sections.append(f"{emoji} *{headline_th}*\n{summary}")
            if not force:
                with _sent_news_lock:
                    sent_pro_news.add(original_title)
                seen_titles.append(original_title)

        if not sections:
            return

        # ป้องกันหน่วยความจำเต็ม
        with _sent_news_lock:
            if len(sent_pro_news) > 500:
                sent_pro_news.clear()

        msg = "⚡️ *Flash News*\n\n" + "\n\n".join(sections)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE role IN ('pro', 'vip')")
        recipients = [str(pro[0]) for pro in cur.fetchall()
                      if check_subscription(pro[0]) in ('pro', 'vip')
                      and should_send_user_notification(pro[0], category="flash_news")]
        conn.close()
        if str(ADMIN_ID) not in recipients:
            recipients.insert(0, str(ADMIN_ID))
        count = 0
        for uid in recipients:
            if safe_send(bot_instance, uid, msg, parse_mode='Markdown'):
                count += 1
            time.sleep(0.5)
        print(f"[FlashNews] ส่งสำเร็จ {count} คน ({len(sections)} ข่าว)")

    except Exception as e:
        # 🌟 3. ดักจับกรณี API พัง หรือโดนบล็อคเนื้อหาความรุนแรง
        tb = traceback.format_exc()
        print(f"❌ [FlashNews] Error:\n{tb}")
        # 🌟 503 Gemini overload — skip เงียบๆ รอบหน้ารันใหม่เอง ไม่ต้องปลุก admin
        if _is_gemini_overloaded_error(e):
            return
        try:
            error_msg = str(e)
            if "Safety" in error_msg or "blocked" in error_msg.lower():
                bot_instance.send_message(ADMIN_ID, "⚠️ **Flash News สะดุด:** AI ปฏิเสธการสรุปข่าวเนื่องจากติดฟิลเตอร์คำรุนแรง (Safety Policy)")
            else:
                bot_instance.send_message(ADMIN_ID, f"⚠️ **Flash News System Error:** {error_msg}\n\n`{tb[-300:]}`", parse_mode="Markdown")
        except Exception as notify_err:
            print(f"[FlashNews] notify-admin failed: {notify_err}", flush=True)

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

    เลือกข่าวเชิงเศรษฐกิจ/การลงทุน ที่ "สำคัญที่สุด" 2 ข่าว จากคนละสำนักข่าวถ้าเป็นไปได้
    ถ้าหลายพาดหัวพูดถึงเรื่องเดียวกัน ให้เลือกเพียงข่าวเดียวจากกลุ่มนั้น (ห้ามซ้ำประเด็น)
    (เน้นเรื่องเศรษฐกิจ หลีกเลี่ยงเนื้อหาความรุนแรง)

    ตอบกลับในรูปแบบ JSON Array เท่านั้น:
    [
        {{
            "original_title": "พาดหัวข่าวต้นฉบับที่เลือก",
            "emoji": "emoji 1-2 ตัวที่สื่อทิศทางตลาด เช่น 🔴📉 หรือ 🟢📈 หรือ 🟡⚡️",
            "headline_th": "พาดหัวสั้นๆ เป็นภาษาไทย ไม่เกิน 10 คำ",
            "summary": "สรุปสั้นๆ 1-2 ประโยค รวมผลกระทบต่อตลาดด้วย (ภาษาไทย)"
        }}
    ]
    """
    try:
        ai_check = _gemini_generate_with_retry(prompt)
        result_text = ai_check.text.strip().replace('```json', '').replace('```', '')
        try:
            analysis_list = json.loads(result_text)
        except json.JSONDecodeError as je:
            print(f"[DigestNews] AI returned non-JSON → silent drop. preview: {result_text[:150]}", flush=True)
            return

        if not isinstance(analysis_list, list):
            print(f"[DigestNews] AI returned {type(analysis_list).__name__} not list → silent drop", flush=True)
            return
        if len(analysis_list) == 0:
            print(f"[DigestNews] AI returned empty list (no headlines worth pushing)", flush=True)
            return

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
        if str(ADMIN_ID) not in [str(u) for u in eligible_users]:
            eligible_users.insert(0, ADMIN_ID)
        if not eligible_users:
            conn.close()
            return
        sent_to_users = set()
        digest_sections = []
        with _sent_news_lock:
            seen_titles = list(sent_pro_news)

        for item in analysis_list[:MAX_DIGEST_ITEMS]:
            original_title = _normalize_news_title(item.get('original_title', ''))
            emoji = item.get('emoji', '📰')
            headline_th = item.get('headline_th', '') or original_title
            summary = item.get('summary', '')

            if original_title and summary:
                # 🌟 similarity dedup — กรองข่าวคล้ายกัน
                if not force and _is_duplicate_news(original_title, seen_titles):
                    continue
                # 🌟 cross-dedup: ใช้ category "news" ร่วมกับ Flash News (skip when force=True)
                if not force and not _claim_dispatch_once("news", original_title):
                    continue
                summary = _compact_news_text(summary, max_chars=200, max_lines=2)
                digest_sections.append(f"{emoji} *{headline_th}*\n{summary}")
                if not force:
                    with _sent_news_lock:
                        sent_pro_news.add(original_title)
                    seen_titles.append(original_title)
        if not digest_sections:
            conn.close()
            return

        msg = "📰 *Apex News Digest*\n\n" + "\n\n".join(digest_sections)

        for uid in eligible_users:
            if safe_send(bot_instance, uid, msg, parse_mode='Markdown'):
                sent_to_users.add(uid)
            time.sleep(0.5)
        for uid in sent_to_users:
            mark_digest_sent(uid)
        conn.close()
    except Exception as e:
        tb = traceback.format_exc()
        print(f"❌ [DigestNews] Error:\n{tb}")
        # 🌟 503 Gemini overload — skip เงียบๆ รอบหน้ารันใหม่เอง ไม่ต้องปลุก admin
        if _is_gemini_overloaded_error(e):
            return
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Digest News Error:** {str(e)[:100]}\n\n`{tb[-300:]}`", parse_mode="Markdown")
        except Exception as notify_err:
            print(f"[DigestNews] notify-admin failed: {notify_err}", flush=True)


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
            safe_send(bot, user_id, msg, parse_mode="Markdown")
            deactivate_price_alert(a_id)
            time.sleep(0.5)
# ==========================================
# 🎙️ ฟีเจอร์ AI Podcast สรุปตลาดตอนเช้า (08:00 น.)
# ==========================================
def get_podcast_market_data():
    """ดึงข้อมูลตลาดสำหรับ podcast เช้า — batch fetch (1 HTTP request) แทน loop N requests"""
    tickers = [
        ('^GSPC',     'S&P 500',     'จุด'),
        ('^IXIC',     'Nasdaq',      'จุด'),
        ('^DJI',      'Dow Jones',   'จุด'),
        ('^SET.BK',   'SET Index',   'จุด'),
        ('BTC-USD',   'Bitcoin',     'ดอลลาร์'),
        ('GC=F',      'ทองคำโลก',    'ดอลลาร์'),
        ('CL=F',      'น้ำมันดิบ',   'ดอลลาร์'),
        ('DX-Y.NYB',  'Dollar Index','จุด'),
        ('^TNX',      'US 10Y Yield','%'),
        ('^VIX',      'VIX',         'จุด'),
    ]

    # 🌟 Batch download: 1 HTTP request → 10 tickers (เร็วกว่า loop เดิม ~5-10x)
    syms = [t[0] for t in tickers]
    try:
        batch = yf.download(
            syms, period='5d',
            group_by='ticker', progress=False, threads=True,
            auto_adjust=False,
        )
    except Exception as e:
        print(f"⚠️ [Podcast] batch download fail: {e}", flush=True)
        return "ข้อมูลตลาดยังไม่พร้อม ตลาดอาจยังไม่เปิดหรือเน็ตมีปัญหา"

    def _extract(sym):
        try:
            # MultiIndex columns เมื่อ multi-symbol; flat ถ้า 1 ตัว
            sym_data = batch[sym] if sym in batch.columns.get_level_values(0) else batch
            closes = sym_data['Close'].dropna()
            if len(closes) < 2:
                return None, None
            prev, curr = float(closes.iloc[-2]), float(closes.iloc[-1])
            if math.isnan(curr) or math.isnan(prev) or prev == 0:
                return None, None
            return curr, (curr - prev) / prev * 100
        except Exception as e:
            print(f"[Podcast] {sym} parse fail: {e}", flush=True)
            return None, None

    date_str = (datetime.utcnow() + timedelta(hours=7)).strftime('%d %b %Y')
    parts = [f"ข้อมูลตลาด ณ วันที่ {date_str}:"]
    for sym, label, unit in tickers:
        price, chg = _extract(sym)
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

def get_stock_spotlight_news(target_count: int = 5):
    """ดึงข่าวรายหุ้น target_count ตัวที่น่าสนใจสำหรับ podcast
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

    # 🌟 yf.Ticker(sym).news ไม่มี built-in timeout — wrap 8s ผ่าน ThreadPoolExecutor
    # กันค้างเป็นนาทีถ้า Yahoo network stall (เคยเจอใน news page เดียวกัน)
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    def _fetch_one_news(sym):
        try:
            return yf.Ticker(sym).news or []
        except Exception:
            return []

    results = []
    with ThreadPoolExecutor(max_workers=1) as ex:
        for sym in candidates:
            if len(results) >= target_count:
                break
            try:
                future = ex.submit(_fetch_one_news, sym)
                news_items = future.result(timeout=8)
                if not news_items:
                    continue
                headline = news_items[0].get('title', '').strip()
                if headline:
                    results.append(f"{sym}: {headline}")
            except FutureTimeout:
                print(f"[Podcast] ข่าว {sym} timeout 8s — ข้าม", flush=True)
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

    ข่าวรายหุ้นสำคัญ (เลือกเล่า 4-5 ตัวที่น่าสนใจที่สุด):
    {stock_news_context}

    ตอบกลับมาเฉพาะบทพูดที่จะอ่านออกอากาศได้ทันที **ความยาว 4-5 นาที** (ประมาณ 700-900 คำไทย)
    ห้ามมีคำอธิบาย ห้ามมี label ห้ามมีวงเล็บ ห้ามมีหัวข้อ ห้ามบอกว่ากำลังจะทำอะไร เริ่มพูดได้เลย

    เนื้อหาที่ต้องครอบคลุมแบบเนียนๆ ลึกขึ้นกว่าเดิม:
    1. ทักทายยามเช้าแบบเป็นกันเอง บอกบรรยากาศตลาดคืนที่ผ่านมาเป็นภาพรวม
    2. ภาพรวมตลาดเชิงลึก: S&P, Nasdaq, Dow, ทอง, น้ำมัน, ดอลลาร์, BTC — เล่าตัวเลข + ความหมาย + driver ที่ทำให้เคลื่อน
    3. มุมมองมหภาค: dollar index, yield curve, fear/greed, sector rotation — เชื่อมโยงเป็นเรื่องเดียวกัน
    4. เจาะข่าวรายหุ้น 4-5 ตัว: เล่าข่าว + วิเคราะห์ implications สำหรับนักลงทุน + เปรียบเทียบกับ peer ถ้ามีข่าวสำคัญ
    5. ความเสี่ยง/โอกาสที่ต้องจับตาวันนี้: catalyst สำคัญ (FOMC, CPI, earnings) ถ้ามี
    6. กลยุทธ์ปฏิบัติ: คนเทรดสั้นกับคนถือยาวควรทำอะไรต่างกัน
    7. ปิดด้วยข้อคิดเชิงจิตวิทยาการลงทุน + กำลังใจ

    ข้อกำหนด:
    - ใช้ภาษาพูดธรรมชาติ น่าฟัง มีพลัง ไม่เวอร์ — เหมือนพี่นักวิเคราะห์เล่าให้น้องฟังขณะขับรถ
    - อธิบายลึกเชิง implications ไม่ใช่แค่อ่านตัวเลข
    - ห้ามใช้ Bullet Point ดอกจัน แฮชแท็ก หัวข้อย่อย วงเล็บ หรือ label ทุกชนิด
    - อ่านตัวเลขแบบกลมๆ ฟังง่าย เช่น "ห้าพันสองร้อยจุด" แทน "5,234.56"
    - **อย่างน้อย 7 ย่อหน้า และ 25-30 ประโยค** เพื่อให้ได้ความยาว 4-5 นาที
    - ใช้คำเชื่อมที่ทำให้เนื้อหาไหลเป็นเรื่องเดียวกัน (เช่น "นอกจากนี้", "ในมุมมองที่ลึกขึ้น", "สำหรับคนที่ถือ...")
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
        cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
        podcast_recipients = [str(row[0]) for row in cur.fetchall()
                              if check_subscription(row[0]) == 'pro'
                              and should_send_user_notification(row[0], category="morning_briefing")]
        cur.close()
        conn.close()
        if str(ADMIN_ID) not in podcast_recipients:
            podcast_recipients.insert(0, str(ADMIN_ID))

        count = 0
        for user_id in podcast_recipients:
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
        except Exception as notify_err:
            print(f"[Podcast] notify-admin failed: {notify_err}", flush=True)

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

_TOP_MOVERS_TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL",
    "PTT.BK", "ADVANC.BK", "KBANK.BK", "AOT.BK", "SCB.BK",
]

def _get_top_movers_section():
    moves = []
    for sym in _TOP_MOVERS_TICKERS:
        try:
            hist = yf.Ticker(sym).history(period='2d')
            if len(hist) >= 2:
                prev = hist['Close'].iloc[-2]
                curr = hist['Close'].iloc[-1]
                if prev > 0:
                    pct = (curr - prev) / prev * 100
                    moves.append((sym, pct))
        except Exception as e:
            print(f"[TopMovers] {sym} fetch failed: {e}", flush=True)
    if not moves:
        return ""
    moves.sort(key=lambda x: x[1], reverse=True)
    gainers = moves[:3]
    losers = moves[-3:]
    g_str = "  ".join(f"{s} {p:+.1f}%" for s, p in gainers)
    l_str = "  ".join(f"{s} {p:+.1f}%" for s, p in reversed(losers))
    return f"🏆 **Gainers:** {g_str}\n📉 **Losers:** {l_str}"

# ==========================================
# 🌟 ฟีเจอร์ Morning Apexify Briefing (08:30 น.)
# ==========================================
def _get_overnight_breaking_section() -> str:
    """Pull HIGH-tier breaking news classified in past 14h (overnight US market window).

    Why 14h: morning briefing fires 08:30 Thai. 14h back covers ~18:30 prev day Thai
    = 11:30 ET prev session — captures pre-market through after-hours macro releases
    (CPI/NFP at 08:30 ET, FOMC at 14:00 ET, etc).
    """
    try:
        from database import get_recent_breaking_news
        items = get_recent_breaking_news(limit=10, importance="HIGH")
    except Exception as e:
        print(f"[MorningBriefing] overnight breaking fetch failed: {e}", flush=True)
        return ""
    if not items:
        return ""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=14)
    fresh = []
    for it in items:
        try:
            ts_str = it.get("classified_at")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                fresh.append(it)
        except Exception:
            continue
    if not fresh:
        return ""
    lines = ["🚨 **ข่าวด่วนเมื่อคืน:**"]
    for n in fresh[:5]:
        summary = n.get("summary_th") or n.get("title", "")[:80]
        lines.append(f"• {summary}")
    return "\n".join(lines) + "\n\n"


def send_morning_briefing(bot_instance, force=False):
    try:
        if not force and not _claim_dispatch_once("morning_briefing", _current_thai_date_str()):
            print("⏭️ [Morning Briefing] ข้ามการส่งซ้ำของวันนี้")
            return
        sp500 = yf.Ticker('^GSPC').history(period='1d')
        btc = yf.Ticker('BTC-USD').history(period='1d')
        gold = yf.Ticker('GC=F').history(period='1d')
        set_hist = yf.Ticker('^SET.BK').history(period='2d')
        usdthb_hist = yf.Ticker('USDTHB=X').history(period='1d')
        
        fresh_news = get_fresh_global_news()
        news_titles = (
            "\n".join([f"- [{n.get('source', 'Unknown Source')}] {n['title']}" for n in fresh_news[:5]])
            if fresh_news else "ไม่มีข่าวเด่น"
        )
        
        if not sp500.empty and not btc.empty:
            sp500_close = sp500['Close'].iloc[-1]
            btc_close = btc['Close'].iloc[-1]
            gold_close = gold['Close'].iloc[-1] if not gold.empty else 0
            # SET Index
            thai_market_section = ""
            try:
                if len(set_hist) >= 2:
                    set_prev = set_hist['Close'].iloc[-2]
                    set_curr = set_hist['Close'].iloc[-1]
                    set_pct = (set_curr - set_prev) / set_prev * 100 if set_prev else 0
                    set_str = f"• SET Index: {set_curr:,.2f} ({set_pct:+.2f}%)\n"
                elif len(set_hist) == 1:
                    set_str = f"• SET Index: {set_hist['Close'].iloc[-1]:,.2f}\n"
                else:
                    set_str = ""
                usdthb_str = f"• USD/THB: {usdthb_hist['Close'].iloc[-1]:.2f}\n" if not usdthb_hist.empty else ""
                if set_str or usdthb_str:
                    thai_market_section = f"🇹🇭 **ตลาดไทย:**\n{set_str}{usdthb_str}\n"
            except Exception as thai_err:
                print(f"[MorningBriefing] Thai market section failed: {thai_err}", flush=True)
            top_movers_text = _get_top_movers_section()
            top_movers_section = f"{top_movers_text}\n\n" if top_movers_text else ""
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

            overnight_breaking_section = _get_overnight_breaking_section()

            msg = (
                f"🌅 **Apexify Morning Briefing** 🌅\n\n"
                f"📊 **สรุปตลาดโลกเมื่อคืน:**\n"
                f"• S&P 500: {sp500_close:,.2f}\n"
                f"• Bitcoin: {btc_close:,.2f}\n"
                f"• ทองคำโลก (Gold): {gold_close:,.2f}\n\n"
                f"{thai_market_section}"
                f"{overnight_breaking_section}"
                f"{macro_assets_section}"
                f"{movers_section}"
                f"{top_movers_section}"
                f"{econ_section}"
                f"🤖 **มุมมอง Apexify วันนี้:**\n{summary}\n\n"
                f"🔥 *ขอให้พอร์ตเขียวๆ ตลอดวันครับ!*\n\n"
                f"{MORNING_BRIEFING_LEGAL_DISCLAIMER}"
            )
            
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE role IN ('vip', 'pro')")
            recipients = [str(pro[0]) for pro in cur.fetchall()
                          if check_subscription(pro[0]) in ('vip', 'pro')
                          and should_send_user_notification(pro[0], category="morning_briefing")]
            cur.close()
            conn.close()
            if str(ADMIN_ID) not in recipients:
                recipients.insert(0, str(ADMIN_ID))

            count = 0
            for uid in recipients:
                if safe_send(bot_instance, uid, msg, parse_mode='Markdown'):
                    count += 1
                time.sleep(0.5)

            if count > 0: print(f"✅ ส่ง Morning Briefing สำเร็จ {count} คน")
    except Exception as e:
        tb = traceback.format_exc()
        print(f"❌ [MorningBriefing] Error:\n{tb}")
        try:
            bot_instance.send_message(ADMIN_ID, f"⚠️ **Morning Briefing Error:** {str(e)[:200]}\n\n`{tb[-300:]}`", parse_mode="Markdown")
        except Exception as notify_err:
            print(f"[MorningBriefing] notify-admin failed: {notify_err}", flush=True)

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
        pro_user_ids = [str(row[0]) for row in cur.fetchall()]
        cur.close()
        conn.close()
        # 🌟 รวม ADMIN_ID ถ้าไม่มีใน list (admin ได้ทุกอย่างที่ PRO ได้)
        if str(ADMIN_ID) not in pro_user_ids:
            pro_user_ids.insert(0, str(ADMIN_ID))
        for uid in pro_user_ids:
            if check_subscription(uid) == 'pro' and should_send_user_notification(uid, category="xd_alert"):
                try:
                    bot.send_message(uid, msg, parse_mode='Markdown')
                    time.sleep(0.5)
                except Exception as e:
                    print(f"[XDAlert] ส่งให้ {uid} ไม่สำเร็จ: {e}")
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
    user_ids = [str(row[0]) for row in cur.fetchall()]
    # 🌟 รวม ADMIN_ID ถ้ามี portfolio (admin ได้ทุก feature)
    cur.execute("SELECT 1 FROM portfolios WHERE user_id=%s LIMIT 1", (str(ADMIN_ID),))
    if cur.fetchone() and str(ADMIN_ID) not in user_ids:
        user_ids.insert(0, str(ADMIN_ID))
    cur.close()
    conn.close()

    count = 0
    for user_id in user_ids:
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
    """แจ้งเตือน VIP/PRO ที่หมดอายุใน 7/3/1 วัน + inline button ต่ออายุ"""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    DAY_WORDS = {7: "7 วัน", 3: "3 วัน", 1: "พรุ่งนี้"}
    URGENCY = {7: "💡", 3: "⚠️", 1: "🚨"}
    for days_left in (7, 3, 1):
        try:
            users = get_expiring_subscriptions(days_left)
        except Exception as e:
            print(f"[expiry_warnings] get_expiring_subscriptions error: {e}")
            continue
        for user_id, role, expiry_date in users:
            role_label = "💎 VIP" if role == "vip" else "👑 PRO"
            day_word = DAY_WORDS[days_left]
            urgency = URGENCY[days_left]
            msg = (
                f"{urgency} **แพ็กเกจของคุณใกล้หมดอายุแล้ว**\n\n"
                f"📦 แพ็กเกจปัจจุบัน: {role_label}\n"
                f"⏰ หมดอายุ: {str(expiry_date)[:10]}\n"
                f"📅 เหลือเวลา: **{day_word}**\n\n"
            )
            if days_left == 1:
                msg += "⚡ **ต่ออายุตอนนี้เลยเพื่อไม่ให้ขาดช่วง** — ไม่งั้นพรุ่งนี้ฟีเจอร์พรีเมียมจะถูกปิดทันที"
            elif days_left == 3:
                msg += "💎 ต่ออายุตอนนี้รับสิทธิ์ใช้งานต่อเนื่อง — ไม่เสียวันที่เหลือของแพ็กเกจปัจจุบัน"
            else:
                msg += "✨ เหลืออีก 7 วัน — ต่ออายุเตรียมไว้ใช้ได้ยาวๆ ต่อเนื่องไม่สะดุด"

            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton(f"💎 ต่ออายุ VIP 79฿", callback_data="menu_vip"),
                InlineKeyboardButton(f"👑 ต่ออายุ PRO 109฿", callback_data="menu_vip"),
            )
            kb.add(InlineKeyboardButton("🎁 ใช้โค้ดส่วนลด", callback_data="menu_code"))

            try:
                bot_instance.send_message(user_id, msg, parse_mode="Markdown", reply_markup=kb)
            except Exception as e:
                print(f"[expiry_warnings] send to {user_id} failed: {e}")
    print(f"[expiry_warnings] ส่งแจ้งเตือนหมดอายุเรียบร้อย (7/3/1 วัน)")

def send_final_hour_warnings(bot_instance):
    """แจ้งเตือนคนที่แพ็กเกจกำลังจะหมดอายุใน 1-2 ชม. ข้างหน้า — peak intent moment
    ก่อน downgrade. Daily 1-day warning ส่งตอนเที่ยงคืน อาจห่างจริงหลายชม. — รอบนี้
    จับโค้งสุดท้ายไม่ให้พลาด.

    Dedup ผ่านตาราง expiry_final_warned (PRIMARY KEY user_id+expiry_at) — fire ครั้ง
    เดียวต่อ subscription period. ถ้า user ต่ออายุแล้ว expiry_at ใหม่ → fire ใหม่ได้.
    """
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    conn = get_connection()
    c = conn.cursor()
    rows = []
    try:
        c.execute("""
            SELECT user_id, role, expiry_date FROM users
            WHERE role IN ('vip', 'pro')
              AND expiry_date IS NOT NULL
              AND expiry_date::timestamptz > NOW()
              AND expiry_date::timestamptz <= NOW() + INTERVAL '2 hours'
        """)
        rows = c.fetchall()
    except Exception as e:
        print(f"[final_hour_warnings] query error: {e}", flush=True)
        conn.close()
        return

    # Pull free_trial_used in a separate light query so we can pick the right copy
    trial_users = set()
    try:
        c.execute("SELECT user_id FROM users WHERE free_trial_used = TRUE")
        trial_users = {row[0] for row in c.fetchall()}
    except Exception as e:
        print(f"[final_hour_warnings] trial flag query error: {e}", flush=True)

    sent = 0
    for user_id, role, expiry in rows:
        # Atomic dedup — INSERT only succeeds for first warning of this expiry
        try:
            c.execute(
                "INSERT INTO expiry_final_warned (user_id, expiry_at) VALUES (%s, %s) "
                "ON CONFLICT (user_id, expiry_at) DO NOTHING",
                (str(user_id), expiry),
            )
            already_warned = c.rowcount == 0
            conn.commit()
        except Exception as e:
            print(f"[final_hour_warnings] dedup error for {user_id}: {e}", flush=True)
            conn.rollback()
            continue
        if already_warned:
            continue

        role_label = "💎 VIP" if role == 'vip' else "👑 PRO"
        expiry_str = str(expiry)[:16] if expiry else "-"
        is_trial = role == 'pro' and user_id in trial_users

        if is_trial:
            # Trial wrap-up — concrete usage stats so the renew decision is informed
            try:
                c.execute(
                    "SELECT COUNT(*) FROM analysis_plans WHERE user_id = %s "
                    "AND issued_at >= %s::timestamptz - INTERVAL '7 days'",
                    (str(user_id), expiry),
                )
                plans_count = c.fetchone()[0] or 0
            except Exception:
                plans_count = 0
            try:
                c.execute(
                    "SELECT COUNT(*) FROM user_price_alerts WHERE user_id = %s AND is_active = 1",
                    (str(user_id),),
                )
                alerts_count = c.fetchone()[0] or 0
            except Exception:
                alerts_count = 0
            try:
                c.execute("SELECT COUNT(*) FROM user_watchlist WHERE user_id = %s", (str(user_id),))
                watch_count = c.fetchone()[0] or 0
            except Exception:
                watch_count = 0

            msg = (
                f"🚨 **PRO Trial เหลือ 1-2 ชม. สุดท้าย**\n\n"
                f"⏰ หมดอายุ: {expiry_str}\n\n"
                f"📊 ตลอด 7 วันที่ผ่านมา คุณใช้:\n"
                f"   • วิเคราะห์ + Plan: **{plans_count}** ครั้ง\n"
                f"   • Price Alerts: **{alerts_count}** รายการ\n"
                f"   • Watchlist: **{watch_count}** หุ้น\n\n"
                f"⚡ ต่อสมัครต่อเลย ใช้ต่อเนื่องไม่ต้องเริ่มใหม่:"
            )
        else:
            msg = (
                f"🚨 **{role_label} ของคุณกำลังจะหมดอายุ!**\n\n"
                f"⏰ หมดภายใน **1-2 ชั่วโมง** ({expiry_str})\n"
                f"_หลังจากนั้นฟีเจอร์พรีเมียมจะถูกปิดทันที_\n\n"
                f"⚡ ต่ออายุตอนนี้เพื่อใช้งานต่อเนื่อง:"
            )

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("💎 ต่ออายุ VIP 79฿", callback_data="menu_vip"),
            InlineKeyboardButton("👑 ต่ออายุ PRO 109฿", callback_data="menu_vip"),
        )
        kb.add(InlineKeyboardButton("🎁 ใช้โค้ดส่วนลด", callback_data="menu_code"))
        try:
            bot_instance.send_message(user_id, msg, parse_mode="Markdown", reply_markup=kb)
            sent += 1
        except Exception as e:
            print(f"[final_hour_warnings] send to {user_id} failed: {e}", flush=True)

    conn.close()
    if sent > 0:
        print(f"[final_hour_warnings] ส่ง {sent} คน — last-hour upsell window", flush=True)


def send_trial_spotlights(bot_instance):
    """Mid-trial DMs — Day 2 (5d remaining): Smart Alerts, Day 5 (2d remaining): AI Plan.
    Day 4 (3d) and Day 6 (1d) are skipped because the existing 7/3/1-day expiry warnings
    already fire on those days. Daily fire at noon Thai time + dedup table → each user
    sees each spotlight once per trial period.
    """
    SPOTLIGHTS = [
        ('day2', 5,
         "🎯 **PRO Trial Day 2 — ลอง Smart Alerts**\n\n"
         "ตั้งให้ AI แจ้งเมื่อหุ้นถึง RSI/MACD/breakout — ไม่ต้องเฝ้าจอ\n\n"
         "ลองพิมพ์: `/setalert AAPL 200`\n"
         "ดูที่ตั้งไว้: `/myalerts`"),
        ('day5', 2,
         "🎯 **PRO Trial Day 5 — ลอง AI Plan เทรด**\n\n"
         "พิมพ์ชื่อหุ้นใด ๆ → รายงานจะมี Entry/TP1/TP2/SL พร้อม + กราฟวาด zone\n\n"
         "ลองพิมพ์: `AAPL` หรือ `NVDA`"),
    ]

    sent_total = 0
    for marker, days_remaining, body in SPOTLIGHTS:
        target_date = (datetime.now() + timedelta(days=days_remaining)).strftime('%Y-%m-%d')
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""
                SELECT u.user_id FROM users u
                LEFT JOIN trial_spotlight_sent t ON t.user_id = u.user_id AND t.day_marker = %s
                WHERE t.user_id IS NULL
                  AND u.role = 'pro'
                  AND u.free_trial_used = TRUE
                  AND u.expiry_date IS NOT NULL
                  AND u.expiry_date::date = %s::date
            """, (marker, target_date))
            users = [row[0] for row in c.fetchall()]
        except Exception as e:
            print(f"[trial_spotlight] {marker} query error: {e}", flush=True)
            conn.close()
            continue

        for user_id in users:
            try:
                c.execute(
                    "INSERT INTO trial_spotlight_sent (user_id, day_marker) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (str(user_id), marker),
                )
                inserted = c.rowcount > 0
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"[trial_spotlight] dedup error: {e}", flush=True)
                continue
            if not inserted:
                continue
            try:
                bot_instance.send_message(user_id, body, parse_mode="Markdown")
                sent_total += 1
            except Exception as e:
                print(f"[trial_spotlight] send to {user_id} failed: {e}", flush=True)

        conn.close()

    if sent_total > 0:
        print(f"[trial_spotlight] ส่ง {sent_total} คน — mid-trial spotlights", flush=True)


def send_winback_dms(bot_instance):
    """Re-engage free users inactive 7/14/30 days. Hooks the open with their
    biggest watchlist mover (last 7d) so it doesn't read like a generic blast."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    from database import get_user_watch
    import yfinance as yf

    MILESTONES = [(7, "7d", "1 อาทิตย์"), (14, "14d", "2 อาทิตย์"), (30, "30d", "1 เดือน")]

    sent_total = 0
    for days, marker, day_word in MILESTONES:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""
                SELECT u.user_id FROM users u
                LEFT JOIN winback_sent w ON w.user_id = u.user_id AND w.milestone = %s
                WHERE w.user_id IS NULL
                  AND u.last_active IS NOT NULL
                  AND u.last_active::timestamptz < NOW() - INTERVAL %s
                  AND COALESCE(u.role, 'free') = 'free'
            """, (marker, f"{days} days"))
            users = [row[0] for row in c.fetchall()]
        except Exception as e:
            print(f"[winback] {marker} query error: {e}", flush=True)
            conn.close()
            continue

        sent = 0
        for user_id in users:
            if str(user_id) == str(ADMIN_ID):
                continue

            # Build personalized hook — biggest absolute mover from their watchlist
            watchlist = get_user_watch(user_id) or []
            hook = ""
            if watchlist:
                perfs = []
                for sym in watchlist[:5]:
                    try:
                        hist = yf.Ticker(sym).history(period='8d')
                        if len(hist) < 2:
                            continue
                        start = hist['Close'].iloc[0]
                        end = hist['Close'].iloc[-1]
                        if not start:
                            continue
                        pct = (end - start) / start * 100
                        perfs.append((sym, pct))
                    except Exception:
                        continue
                if perfs:
                    perfs.sort(key=lambda x: abs(x[1]), reverse=True)
                    sym, pct = perfs[0]
                    sign = '+' if pct >= 0 else ''
                    hook = f"📊 **{sym}** {sign}{pct:.2f}% ใน 7 วันที่ผ่านมา\n\n"

            msg = (
                f"👋 ไม่เจอคุณมา **{day_word}** แล้วครับ\n\n"
                f"{hook}"
                f"💡 พิมพ์ชื่อหุ้นเพื่อกลับมาวิเคราะห์ หรือ `/weekly_recap` ดูสรุปอาทิตย์นี้\n\n"
                f"🆓 Free Trial: 3 ครั้ง/วัน รีเซ็ตเที่ยงคืน 🌙"
            )
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📱 เปิดเมนูหลัก", callback_data="hub_home"))

            # Mark sent atomically
            try:
                c.execute(
                    "INSERT INTO winback_sent (user_id, milestone) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (str(user_id), marker),
                )
                inserted = c.rowcount > 0
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"[winback] dedup error: {e}", flush=True)
                continue
            if not inserted:
                continue

            try:
                bot_instance.send_message(user_id, msg, parse_mode="Markdown", reply_markup=kb)
                sent += 1
            except Exception as e:
                print(f"[winback] send to {user_id} failed: {e}", flush=True)

        conn.close()
        sent_total += sent

    if sent_total > 0:
        print(f"[winback] ส่ง {sent_total} คน — re-engagement", flush=True)


def send_watchlist_daily_summary(bot_instance):
    """ส่งสรุป Watchlist รายวันให้ VIP+/PRO ที่มี watchlist (05:00 Thai time, หลังตลาด US ปิด)"""
    from database import get_user_watch
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM user_watchlist")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    count = 0
    for user_id in users:
        # Tier gate: VIP+/PRO only
        if str(user_id) != str(ADMIN_ID) and check_subscription(user_id) not in ('vip', 'pro'):
            continue
        if not should_send_user_notification(user_id, category="general"):
            continue
        tickers = get_user_watch(user_id)
        if not tickers:
            continue
        rows = []
        for sym in tickers:
            try:
                hist = yf.Ticker(sym).history(period='2d')
                if len(hist) < 2:
                    continue
                prev = hist['Close'].iloc[-2]
                curr = hist['Close'].iloc[-1]
                pct = (curr - prev) / prev * 100 if prev else 0
                tech_data, _, err = calculate_technical_indicators(sym, generate_chart=False)
                rsi = tech_data.get('rsi', 50) if tech_data and not err else 50
                if rsi < 35:
                    signal = "⚠️ Oversold"
                elif rsi > 65:
                    signal = "⚠️ Overbought"
                elif pct > 0:
                    signal = "📈 Uptrend"
                elif pct < 0:
                    signal = "📉 Downtrend"
                else:
                    signal = "➡️ Neutral"
                icon = "🟢" if pct >= 0 else "🔴"
                rows.append(f"{icon} **{sym}** {pct:+.2f}%  RSI: {rsi:.0f}  {signal}")
            except Exception as e:
                print(f"[WatchlistDigest] {sym} fetch failed: {e}", flush=True)
        if not rows:
            continue
        msg = (
            f"📋 **Watchlist สรุปวันนี้** ({len(rows)} รายการ)\n\n"
            + "\n".join(rows)
            + "\n\n_💡 ส่งทุกวัน 05:00 น. หลังตลาด US ปิด_"
        )
        if safe_send(bot_instance, user_id, msg, parse_mode="Markdown"):
            count += 1
        time.sleep(0.3)
    if count > 0:
        print(f"✅ [WatchlistSummary] ส่งสำเร็จ {count} คน", flush=True)


def send_weekly_performance_digest(bot_instance):
    """Digest ประจำสัปดาห์ — ส่ง VIP/PRO ทุกวันศุกร์ 18:00 Thai time
    รวม: Watchlist WoW, Track Record 30d, AI Economic Preview (สัปดาห์หน้า)
    """
    from database import get_user_watch, get_track_record_stats

    # 🌟 1. Global Track Record (ใช้ซ้ำได้ ไม่ต้องคำนวณต่อ user)
    stats_30d = get_track_record_stats(days=30)

    # 🌟 2. AI-generated Economic Preview สัปดาห์หน้า (ถ้าคิวรีล้มเหลว ให้ skip section นี้)
    economic_preview = None
    try:
        eco_prompt = """
        ระบุเหตุการณ์เศรษฐกิจ/ตลาดสหรัฐฯ สำคัญที่จะเกิดใน 7 วันข้างหน้า
        โฟกัส: FOMC, CPI, PPI, NFP, GDP, Fed speech, Earnings week ของบริษัทใหญ่
        ตอบภาษาไทย bullet list 3-5 รายการ ห้ามเกิน 5 บรรทัด
        รูปแบบ: "📅 วันที่ประมาณ — เหตุการณ์ (ผลกระทบคาด)"
        ห้ามใส่ข้อความนำ/ท้าย ตอบเฉพาะ bullets
        """
        eco_resp = _gemini_generate_with_retry(eco_prompt)
        economic_preview = eco_resp.text.strip()[:500]
    except Exception as e:
        print(f"[WeeklyDigest] AI eco preview failed: {e}", flush=True)

    # 🌟 3. ดึง VIP + PRO + admin
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM users WHERE role IN ('vip', 'pro')")
    recipients = [str(row[0]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    if str(ADMIN_ID) not in recipients:
        recipients.insert(0, str(ADMIN_ID))

    count = 0
    for user_id in recipients:
        role = check_subscription(user_id)
        if role not in ('vip', 'pro'):
            continue
        if not should_send_user_notification(user_id, category="general"):
            continue

        # Watchlist WoW (เทียบราคาปิด 5 วันก่อน)
        tickers = []
        try:
            tickers = get_user_watch(user_id) or []
        except Exception:
            pass

        watch_lines = []
        for sym in tickers[:10]:  # จำกัด 10 ตัวแรก
            try:
                hist = yf.Ticker(sym).history(period='7d')
                if len(hist) < 2:
                    continue
                close_now = float(hist['Close'].iloc[-1])
                close_past = float(hist['Close'].iloc[0])
                wow = (close_now - close_past) / close_past * 100 if close_past else 0
                icon = "🟢" if wow >= 0 else "🔴"
                watch_lines.append(f"{icon} `{sym}` {wow:+.2f}%  _${close_now:,.2f}_")
            except Exception:
                continue

        # User's personal Plan outcomes (PRO only, ในสัปดาห์ที่ผ่านมา)
        user_plan_line = ""
        if role == 'pro':
            try:
                u_stats = get_track_record_stats(days=7, user_id=user_id)
                if u_stats["total"] > 0:
                    user_plan_line = (
                        f"\n📊 *Plan ของคุณสัปดาห์นี้:* "
                        f"{u_stats['tp1_hit'] + u_stats['tp2_hit']} hit / "
                        f"{u_stats['sl_hit']} SL / {u_stats['open']} เปิดอยู่\n"
                    )
            except Exception as e:
                print(f"[WeeklyDigest] user plan stats failed for {user_id}: {e}", flush=True)

        # สร้างข้อความ
        tier_badge = "👑 PRO" if role == 'pro' else "💎 VIP"
        msg_parts = [f"📰 **Apexify Weekly Digest** — {tier_badge}\n"]

        if watch_lines:
            msg_parts.append("*📋 Watchlist ของคุณ (WoW):*\n" + "\n".join(watch_lines))
        else:
            msg_parts.append("_📋 ยังไม่มีหุ้นใน Watchlist — เพิ่มได้โดยวิเคราะห์แล้วกด ⭐_")

        if user_plan_line:
            msg_parts.append(user_plan_line)

        # Global track record
        if stats_30d["closed"] > 0:
            msg_parts.append(
                f"\n*🎯 Apexify Track Record 30 วัน:*\n"
                f"  Hit Rate: *{stats_30d['hit_rate_pct']:.1f}%* "
                f"({stats_30d['wins']}/{stats_30d['closed']} Plans hit TP)"
            )

        if economic_preview:
            msg_parts.append(f"\n*📅 สัปดาห์หน้าต้องจับตา:*\n{economic_preview}")

        msg_parts.append("\n_ส่งทุกวันศุกร์ 18:00 | พิมพ์ /track ดูสถิติละเอียด_")

        msg = "\n\n".join(msg_parts)

        if safe_send(bot_instance, user_id, msg, parse_mode='Markdown'):
            count += 1
        time.sleep(0.5)

    print(f"✅ [WeeklyDigest] ส่งสำเร็จ {count} คน", flush=True)


def check_plan_outcomes():
    """ตรวจ Plan ที่ออกให้ PRO user แล้วว่า hit TP1/TP2/SL หรือ expired
    รันวันละครั้งตอนเช้า — ใช้ข้อมูลราคาจาก yfinance เปรียบเทียบย้อนหลัง
    """
    try:
        pending = get_pending_plans(min_age_hours=24, max_age_days=45)
    except Exception as e:
        print(f"[PlanOutcome] get_pending_plans error: {e}", flush=True)
        return
    if not pending:
        try:
            expire_stale_plans(max_age_days=45)
        except Exception as e:
            print(f"[PlanOutcome] expire_stale_plans failed: {e}", flush=True)
        return

    # group by symbol เพื่อลด API call
    symbols = {}
    for row in pending:
        plan_id, symbol, bias, entry_low, entry_high, tp1, tp2, sl, price_at_issue, issued_at = row
        symbols.setdefault(symbol, []).append(row)

    updated = 0
    for symbol, plans in symbols.items():
        try:
            earliest_issued = min(p[9] for p in plans)
            # ดึงข้อมูลราคาตั้งแต่วันที่ออก Plan แรกสุด
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=earliest_issued.date(), interval="1d")
            if hist.empty:
                continue

            for plan in plans:
                plan_id, _, bias, e_low, e_high, tp1, tp2, sl, _, issued_at = plan
                tp1_val = float(tp1) if tp1 is not None else None
                tp2_val = float(tp2) if tp2 is not None else None
                sl_val = float(sl) if sl is not None else None

                # ดึงข้อมูลตั้งแต่วัน issued ของ plan นี้
                plan_hist = hist[hist.index >= issued_at]
                if plan_hist.empty:
                    continue

                highest = float(plan_hist['High'].max())
                lowest = float(plan_hist['Low'].min())

                # หาว่า SL/TP hit ก่อน ใครก่อน (by date)
                sl_hit_date = None
                tp1_hit_date = None
                tp2_hit_date = None

                for date, row_data in plan_hist.iterrows():
                    hi = float(row_data['High'])
                    lo = float(row_data['Low'])
                    if sl_val is not None and lo <= sl_val and sl_hit_date is None:
                        sl_hit_date = date
                    if tp1_val is not None and hi >= tp1_val and tp1_hit_date is None:
                        tp1_hit_date = date
                    if tp2_val is not None and hi >= tp2_val and tp2_hit_date is None:
                        tp2_hit_date = date

                # ตัดสิน outcome ตามลำดับเวลา
                if sl_hit_date and (tp1_hit_date is None or sl_hit_date < tp1_hit_date):
                    update_plan_outcome(plan_id, 'sl_hit', f"SL {sl_val:.2f} hit on {sl_hit_date.strftime('%Y-%m-%d')}")
                    updated += 1
                elif tp2_hit_date:
                    update_plan_outcome(plan_id, 'tp2_hit', f"TP2 {tp2_val:.2f} hit on {tp2_hit_date.strftime('%Y-%m-%d')}")
                    updated += 1
                elif tp1_hit_date:
                    update_plan_outcome(plan_id, 'tp1_hit', f"TP1 {tp1_val:.2f} hit on {tp1_hit_date.strftime('%Y-%m-%d')}")
                    updated += 1
                # else: ยังเปิดอยู่
        except Exception as e:
            print(f"[PlanOutcome] {symbol} error: {e}", flush=True)
            continue

    try:
        expire_stale_plans(max_age_days=45)
    except Exception:
        pass

    if updated > 0:
        print(f"✅ [PlanOutcome] อัปเดต {updated} plans", flush=True)


def check_earnings_calendar(bot_instance):
    """แจ้งเตือน Earnings วันนี้ให้ผู้ใช้ที่สมัครไว้ — เรียกทุกวัน 8:00 น.

    🛡 Dedup: เช็ค earnings_notified table ก่อนส่ง — กันซ้ำตอน bot restart ใกล้ 8 AM
    🌙 Quiet hours: เช็ค should_send_user_notification(uid, 'digest_news')
    """
    try:
        subscriptions = get_all_earnings_subscriptions()  # {symbol: [user_id, ...]}
        if not subscriptions:
            return
        today = datetime.utcnow().date()
        # notified: {user_id: [(symbol, line, target_date), ...]}
        # เก็บ symbol+target_date ไว้ mark dedup ทีละตัวหลังส่งสำเร็จ
        notified = {}
        for symbol, user_ids in subscriptions.items():
            try:
                ticker = yf.Ticker(symbol)
                cal = ticker.calendar
                if cal is None or cal.empty:
                    continue
                if 'Earnings Date' in cal.columns:
                    earn_dates = cal['Earnings Date'].dropna()
                else:
                    continue
                for ed in earn_dates:
                    ed_date = ed.date() if hasattr(ed, 'date') else None
                    if ed_date and (ed_date == today or ed_date == today + timedelta(days=1)):
                        label = "วันนี้" if ed_date == today else "พรุ่งนี้"
                        line = f"📅 **{symbol}** — Earnings {label} ({ed_date.strftime('%d %b')})"
                        for uid in user_ids:
                            # Tier gate: VIP+/PRO only — skip downgraded users
                            if str(uid) != str(ADMIN_ID) and check_subscription(uid) not in ('vip', 'pro'):
                                continue
                            # Dedup: skip ถ้า user ได้ alert symbol นี้ ใน target_date เดียวกันไปแล้ว
                            if is_earnings_notified(uid, symbol, ed_date):
                                continue
                            # Quiet hours: skip ถ้า user ปิด digest_news / อยู่นอก news window
                            if not should_send_user_notification(uid, category="digest_news"):
                                continue
                            notified.setdefault(uid, []).append((symbol, line, ed_date))
                        break
            except Exception as e:
                print(f"[EarningsAlert] {symbol} fetch fail: {e}", flush=True)

        sent_count = 0
        for uid, items in notified.items():
            lines = [it[1] for it in items]
            msg = "🗓 **Earnings Alert วันนี้**\n\n" + "\n".join(lines) + "\n\n_💡 ใช้ /earnings เพื่อจัดการการแจ้งเตือน_"
            if safe_send_with_retry(bot_instance, uid, msg, parse_mode="Markdown"):
                # Mark dedup เฉพาะตอนส่งสำเร็จ — ถ้าส่งล้มเหลว retry รอบหน้า (ดี)
                for sym, _line, target_date in items:
                    mark_earnings_notified(uid, sym, target_date)
                sent_count += 1
            time.sleep(0.2)
        if sent_count:
            print(f"✅ [EarningsAlert] ส่ง {sent_count} users (skipped {len(notified) - sent_count} fail)", flush=True)
    except Exception as e:
        print(f"[EarningsAlert] Error: {e}", flush=True)


def run_alert_loop(bot_instance=None):
    """Main alert loop — started as a daemon Thread from main.py"""
    if bot_instance is None:
        bot_instance = bot

    _init_sent_pro_news()
    _hydrate_alert_state()
    print("🚀 Apexify Alert System (PRO + VIP selected features) is Running...")

    last_hourly_news_time = time.time() - FLASH_NEWS_INTERVAL_SECONDS
    last_global_news_time = time.time() - DIGEST_NEWS_CHECK_INTERVAL_SECONDS
    last_stock_news_check_time = time.time() - STOCK_NEWS_CHECK_INTERVAL_SECONDS
    last_final_hour_warning_time = 0.0
    last_breaking_news_time = 0.0
    BREAKING_NEWS_INTERVAL_SECONDS = 5 * 60  # poll every 5 min (matches loop cadence)
    last_morning_briefing_date = None
    last_xd_check_date = None
    last_podcast_date = None
    last_portfolio_summary_date = None
    last_downgrade_date = None
    last_expiry_warning_date = None
    last_watchlist_summary_date = None
    last_earnings_check_date = None
    last_plan_outcome_date = None
    last_weekly_digest_date = None
    last_engagement_date = None

    while True:
      try:
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

        # 🌟 Track Record — ตรวจ Plan outcome วันละครั้ง ตี 6 (ตลาด US ปิดแล้ว)
        if thai_time.hour == 6 and last_plan_outcome_date != current_date_str:
            check_plan_outcomes()
            last_plan_outcome_date = current_date_str

        if thai_time.hour == 8 and last_earnings_check_date != current_date_str:
            check_earnings_calendar(bot_instance)
            last_earnings_check_date = current_date_str

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

        if thai_time.hour == 5 and last_watchlist_summary_date != current_date_str:
            send_watchlist_daily_summary(bot_instance)
            last_watchlist_summary_date = current_date_str

        # 🌟 Weekly Digest — ศุกร์ 18:00 Thai time (weekday()=4 = Friday)
        if (thai_time.weekday() == 4 and thai_time.hour == 18
                and last_weekly_digest_date != current_date_str):
            send_weekly_performance_digest(bot_instance)
            last_weekly_digest_date = current_date_str

        # 🎯 Engagement loop — once daily at noon Thai time
        # Trial spotlights + win-back DMs share the same fire window so
        # users don't get pinged at random throughout the day.
        if thai_time.hour == 12 and last_engagement_date != current_date_str:
            try:
                send_trial_spotlights(bot_instance)
            except Exception as e:
                print(f"[AlertLoop] send_trial_spotlights failed: {e}", flush=True)
            try:
                send_winback_dms(bot_instance)
            except Exception as e:
                print(f"[AlertLoop] send_winback_dms failed: {e}", flush=True)
            last_engagement_date = current_date_str

        check_market_conditions()
        check_custom_price_alerts()

        # 🚨 Final-hour expiry warning — runs hourly, dedup'd via expiry_final_warned
        if current_time - last_final_hour_warning_time >= 3600:
            try:
                send_final_hour_warnings(bot_instance)
            except Exception as e:
                print(f"[AlertLoop] final_hour_warnings failed: {e}", flush=True)
            last_final_hour_warning_time = current_time

        # 🚨 Breaking News — poll macro RSS, classify HIGH via Gemini, push to PRO
        if current_time - last_breaking_news_time >= BREAKING_NEWS_INTERVAL_SECONDS:
            try:
                from breaking_news import process_breaking_news
                stats = process_breaking_news(bot_instance)
                if stats["high"] > 0 or stats["pushed_users"] > 0:
                    print(f"[BreakingNews] high={stats['high']} pushed={stats['pushed_users']} "
                          f"shortlisted={stats['shortlisted']} dup={stats['skipped_dup']}",
                          flush=True)
            except Exception as e:
                print(f"[BreakingNews] loop error: {e}", flush=True)
            last_breaking_news_time = time.time()

        # 🌟 Resolve due alert outcomes ใน background — ออกจาก hot path ของ admin dashboard
        try:
            from admin_service import resolve_due_alerts_background
            resolve_due_alerts_background()
        except Exception as e:
            print(f"[AlertLoop] resolve_due_alerts_background failed: {e}", flush=True)

      except Exception as e:
        print(f"[AlertLoop] Exception in loop body: {e}", flush=True)

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

