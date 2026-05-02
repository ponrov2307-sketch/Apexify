import io
import json
import math
import re
import time as _time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from threading import RLock

import PIL.Image
from cachetools import TTLCache

from config import GEMINI_API_KEY, gemini_client
from technical_tools import build_multitimeframe_trade_context

client = gemini_client

# 🛡 Gemini timeout pool — กัน handler thread hang ถ้า Gemini stall
# google-genai ไม่ expose timeout ตรงๆ ใช้ pool + future.result(timeout=) แทน
_gemini_timeout_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gemini-to")
GEMINI_DEFAULT_TIMEOUT_S = 30
GEMINI_IMAGE_TIMEOUT_S = 45  # image analysis ช้ากว่าปกติ


def _gemini_call_with_timeout(timeout_s=GEMINI_DEFAULT_TIMEOUT_S, **kwargs):
    """Wrap client.models.generate_content() ด้วย hard timeout
    Background call ยังทำงานต่อใน pool (ไม่ cancel ได้) แต่ caller หลุด
    """
    fut = _gemini_timeout_pool.submit(client.models.generate_content, **kwargs)
    try:
        return fut.result(timeout=timeout_s)
    except _FutureTimeout:
        raise TimeoutError(f"Gemini API timed out after {timeout_s}s") from None

# 🌟 Cache Gemini responses — key by (symbol, bias, rounded price 1%) เพื่อ hit เมื่อ user ขอหุ้นเดียวซ้ำใน 5 นาที
# ลด Gemini API call 50%+ + ลดเวลา 3-8 วิ → 0 วิ บน cache hit
_ai_response_cache = TTLCache(maxsize=200, ttl=300)
_ai_cache_lock = RLock()


# 🥇 Commodity/crypto descriptions — แสดงใต้ชื่อ symbol ใน header รายงาน
# กัน user งงว่า GC=F/CL=F/HG=F คืออะไร (เป็น futures = ราคาจริงของสินค้า ไม่ใช่ ETF)
_COMMODITY_REPORT_DESC = {
    # 🥇 Futures — ราคา spot จริง (front-month continuous)
    'GC=F':    '🥇 ทองคำ (Gold Futures) — ราคา spot ดอลลาร์/ออนซ์',
    'SI=F':    '⚪ แร่เงิน (Silver Futures) — ราคา spot ดอลลาร์/ออนซ์',
    'CL=F':    '🛢 น้ำมันดิบ WTI (Crude Oil Futures) — ดอลลาร์/บาร์เรล',
    'NG=F':    '💨 ก๊าซธรรมชาติ (Natural Gas Futures) — ดอลลาร์/MMBtu',
    'HG=F':    '🟫 ทองแดง (Copper Futures) — ดอลลาร์/ปอนด์',
    'PL=F':    '🥈 ทองคำขาว (Platinum Futures) — ดอลลาร์/ออนซ์',
    'PA=F':    '⚪ พาลาเดียม (Palladium Futures) — ดอลลาร์/ออนซ์',
    # ETF — เผื่อ user พิมพ์ ticker ตรงๆ (ราคา ETF ไม่ใช่ spot)
    'GLD':     '🥇 ETF ทองคำ (SPDR Gold Trust) — ราคาต่อหุ้น ETF (≠ ราคาทอง spot ใช้ `gold` แทนถ้าอยากเห็นราคาจริง)',
    'SLV':     '⚪ ETF แร่เงิน (iShares Silver Trust) — ราคาต่อหุ้น ETF',
    'USO':     '🛢 ETF น้ำมัน (US Oil Fund) — ราคาต่อหุ้น ETF (≠ ราคา oil spot ใช้ `oil` แทนถ้าอยากเห็นราคาจริง)',
    'UNG':     '💨 ETF ก๊าซธรรมชาติ (US Natural Gas Fund)',
    'CPER':    '🟫 ETF ทองแดง (US Copper Index Fund)',
    'PPLT':    '🥈 ETF ทองคำขาว (Aberdeen Platinum)',
    'PALL':    '⚪ ETF พาลาเดียม (Aberdeen Palladium)',
    # Crypto
    'BTC-USD': '₿ Bitcoin — สกุลเงินดิจิทัลอันดับ 1',
    'ETH-USD': 'Ξ Ethereum — สกุลเงินดิจิทัลอันดับ 2',
}


def _ai_cache_key(symbol, dominant_bias, current_price):
    # round price ลงเหลือ % เพื่อให้ cache hit แม้ราคาขยับเล็กน้อย
    bucket = round(current_price / 100, 0) if current_price else 0
    return (str(symbol or "").upper(), str(dominant_bias or ""), bucket)


def _ai_cache_get(key):
    with _ai_cache_lock:
        return _ai_response_cache.get(key)


def _ai_cache_set(key, value):
    with _ai_cache_lock:
        _ai_response_cache[key] = value

DISCLAIMER_TEXT = (
    "_⚠️ ข้อมูลในรายงานฉบับนี้จัดทำขึ้นเพื่อประกอบการพิจารณาเท่านั้น "
    "มิใช่คำแนะนำการลงทุน การเสนอขาย หรือการชักชวนให้ซื้อขายหลักทรัพย์ใด ๆ "
    "การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลและใช้ดุลยพินิจของตนเองก่อนตัดสินใจลงทุน_"
)

UNSAFE_MARKDOWN_CHARS = r"[_`~>#\\+\\=\\|\\{\\}\\!\\*]"
ABSOLUTE_LANGUAGE_PATTERNS = (
    "ซื้อเลย",
    "ขายเลย",
    "ต้องซื้อ",
    "ต้องขาย",
    "ต้องขายทิ้ง",
    "การันตี",
    "รับประกัน",
    "guaranteed",
    "buy now",
    "must sell",
    "100%",
)


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_optional_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _format_compact_number(value):
    number = _safe_float(value)
    abs_number = abs(number)

    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs_number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs_number >= 1_000:
        return f"{number / 1_000:.2f}K"
    return f"{number:.2f}"


def _polish_ai_playbook(text):
    cleaned_lines = []
    replacements = {
        "ควร รอดู": "ควรรอดู",
        "ควร ถือรอดู": "ควรถือรอดู",
        "เพื่อประกอบการตัดสินใจ": "ก่อนตัดสินใจ",
        "ติดตามแนวโน้มอย่างใกล้ชิด": "ติดตามแนวโน้มต่ออีกหน่อย",
        "ทิศทางส่วนใหญ่ยังเป็น": "ภาพรวมยังเป็น",
        "สัญญาณส่วนใหญ่ยังเป็น": "ภาพรวมยังเป็น",
    }

    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue

        for old, new in replacements.items():
            line = line.replace(old, new)

        line = line.replace(" .", ".").replace(" ,", ",")
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# 🌟 Thai Language Quality Guard — AI มักสร้างคำแปลกๆ แก้ก่อนส่ง user
THAI_TYPO_FIXES = {
    # คำผิดที่ AI ชอบใช้ (พบจริงใน production)
    "เกรงทึ่ง": "แข็งแกร่ง",
    "เกรงทึง": "แข็งแกร่ง",
    "ทดฐาน": "ทดสอบฐาน",
    "ทดฐานใหญ่": "ทดสอบฐานใหญ่",
    "แนวราคา": "แนวโน้มราคา",
    "พักฐาน": "ปรับฐาน",
    "พัคฐาน": "ปรับฐาน",
    "โมเมนตั้ม": "โมเมนตัม",  # บางครั้งใช้ไม้โท
    "เข็งแกร่ง": "แข็งแกร่ง",
    "อย่างมีนัยยะสำคัญ": "อย่างมีนัยสำคัญ",
    "นัยยะ": "นัย",
    "การการ": "การ",  # ซ้ำซ้อน
    "ที่ที่": "ที่",
    "และและ": "และ",
}


def _fix_thai_typos(text):
    """แก้คำผิดที่ AI ชอบพิมพ์ให้ถูก + ลบช่องว่างซ้ำ"""
    if not text:
        return text
    fixed = str(text)
    for bad, good in THAI_TYPO_FIXES.items():
        fixed = fixed.replace(bad, good)
    # ลบช่องว่างระหว่างตัวเลขและ % เช่น "5 %" → "5%"
    fixed = re.sub(r"(\d)\s+%", r"\1%", fixed)
    # ลบซ้ำจุดจุด "..." > 3 จุด
    fixed = re.sub(r"\.{4,}", "...", fixed)
    return fixed


def _clean_ai_text(text, fallback="ข้อมูลไม่เพียงพอ"):
    cleaned = str(text or "").replace("\r\n", " ").replace("\n", " ").strip()
    cleaned = re.sub(UNSAFE_MARKDOWN_CHARS, "", cleaned)
    cleaned = cleaned.replace(">", "").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return fallback

    lowered = cleaned.lower()
    if any(token in lowered for token in ABSOLUTE_LANGUAGE_PATTERNS):
        return fallback
    # 🌟 แก้คำผิดภาษาไทยก่อน return
    return _fix_thai_typos(cleaned)


def _extract_json_block(text):
    raw = str(text or "").strip()
    if not raw:
        return None

    fence_match = re.search(r"\{.*\}", raw, re.S)
    return fence_match.group(0) if fence_match else None


def _status_from_bias(bias):
    if bias == "bullish":
        return "🟢", "ขาขึ้น Bullish"
    if bias == "bearish":
        return "🔴", "ขาลง Bearish"
    return "⚪️", "ทรงตัว Neutral"


def _format_price(value):
    number = _safe_optional_float(value)
    return f"{number:,.2f}" if number is not None else "N/A"


def _format_range(low, high):
    low_value = _safe_optional_float(low)
    high_value = _safe_optional_float(high)
    if low_value is None or high_value is None:
        return "N/A"
    ordered = sorted((low_value, high_value))
    return f"{ordered[0]:,.2f} - {ordered[1]:,.2f}"


def _format_price_with_pct(value, reference_price):
    """แสดงราคาพร้อม % ห่างจากราคาปัจจุบัน เช่น '340.00 (-11.0%)'"""
    number = _safe_optional_float(value)
    ref = _safe_optional_float(reference_price)
    if number is None:
        return "N/A"
    if ref is None or ref == 0:
        return f"{number:,.2f}"
    pct = (number - ref) / ref * 100
    sign = "+" if pct >= 0 else ""
    return f"{number:,.2f} ({sign}{pct:.1f}%)"


def _format_range_with_pct(low, high, reference_price):
    low_value = _safe_optional_float(low)
    high_value = _safe_optional_float(high)
    ref = _safe_optional_float(reference_price)
    if low_value is None or high_value is None:
        return "N/A"
    ordered = sorted((low_value, high_value))
    base = f"{ordered[0]:,.2f} - {ordered[1]:,.2f}"
    if ref is None or ref == 0:
        return base
    mid = (ordered[0] + ordered[1]) / 2
    pct = (mid - ref) / ref * 100
    sign = "+" if pct >= 0 else ""
    return f"{base} ({sign}{pct:.1f}%)"


def _first_valid(*values):
    for value in values:
        numeric = _safe_optional_float(value)
        if numeric is not None and numeric > 0:
            return numeric
    return None


def _median(values):
    numbers = sorted(
        value
        for value in (_safe_optional_float(item) for item in values)
        if value is not None and value > 0
    )
    if not numbers:
        return None
    mid = len(numbers) // 2
    if len(numbers) % 2 == 1:
        return numbers[mid]
    return (numbers[mid - 1] + numbers[mid]) / 2


def _round_price(value):
    number = _safe_optional_float(value)
    if number is None:
        return None
    return round(number, 2)


def _infer_day_trend(snapshot):
    if not snapshot.get("available"):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    price = _safe_optional_float(snapshot.get("price"))
    ema20 = _safe_optional_float(snapshot.get("ema20"))
    ema50 = _safe_optional_float(snapshot.get("ema50"))
    macd = _safe_optional_float(snapshot.get("macd"))
    signal = _safe_optional_float(snapshot.get("signal"))

    if None in (price, ema20, ema50, macd, signal):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    score = 0
    score += 1 if price > ema20 else -1
    score += 1 if ema20 > ema50 else -1
    score += 1 if macd > signal else -1

    if score >= 2:
        return {"bias": "bullish", "fallback_reason": "ราคาอยู่เหนือ EMA20 และ MACD ยังอยู่ฝั่งบวก ทำให้ภาพวันยังเอนบวก"}
    if score <= -2:
        return {"bias": "bearish", "fallback_reason": "ราคาอยู่ใต้ EMA20 และ MACD ยังอ่อนกว่าสัญญาณ ทำให้แรงขายยังคุมเกมระยะสั้น"}
    return {"bias": "neutral", "fallback_reason": "ราคาแกว่งใกล้ EMA20 และ MACD ยังไม่ให้ทิศชัด จึงมองเป็นกลางไปก่อน"}


def _infer_week_trend(snapshot):
    if not snapshot.get("available"):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    price = _safe_optional_float(snapshot.get("price"))
    poc = _safe_optional_float(snapshot.get("poc"))
    ema20 = _safe_optional_float(snapshot.get("ema20"))
    ema50 = _safe_optional_float(snapshot.get("ema50"))
    consolidation_pct = _safe_optional_float(snapshot.get("consolidation_pct"))

    if None in (price, poc, ema20, ema50):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    is_tight_range = consolidation_pct is not None and consolidation_pct <= 8
    if price > poc and ema20 >= ema50:
        if is_tight_range:
            reason = "ราคาเริ่มสะสมเหนือ POC และกรอบพักตัวค่อนข้างแคบ มีโอกาสขยับขึ้นต่อหากแรงซื้อยังอยู่"
        else:
            reason = "ราคายืนเหนือ POC และโครงสร้างสัปดาห์ยังไม่เสีย ทำให้ภาพกลางยังเอนขึ้น"
        return {"bias": "bullish", "fallback_reason": reason}

    if price < poc and ema20 <= ema50:
        if is_tight_range:
            reason = "ราคาสะสมใต้ POC ในกรอบแคบและยังไม่กลับเหนือโซนสำคัญ จึงมีโอกาสกดลงต่อได้"
        else:
            reason = "ราคาอยู่ใต้ POC และโครงสร้างสัปดาห์ยังอ่อน ทำให้ภาพกลางยังเอนลง"
        return {"bias": "bearish", "fallback_reason": reason}

    return {"bias": "neutral", "fallback_reason": "ราคายังแกว่งในกรอบสะสมใกล้ POC และยังไม่มีฝั่งใดชนะชัดในภาพสัปดาห์"}


def _infer_month_trend(snapshot):
    if not snapshot.get("available"):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    price = _safe_optional_float(snapshot.get("price"))
    ema20 = _safe_optional_float(snapshot.get("ema20"))
    ema50 = _safe_optional_float(snapshot.get("ema50"))
    volume_ratio = _safe_optional_float(snapshot.get("volume_ratio"))
    change_pct = _safe_optional_float(snapshot.get("close_change_pct"))

    if None in (price, ema20, ema50):
        return {"bias": "neutral", "fallback_reason": "ข้อมูลไม่เพียงพอ"}

    volume_support = volume_ratio is None or volume_ratio >= 0.8
    if price > ema20 and ema20 >= ema50 and volume_support:
        return {"bias": "bullish", "fallback_reason": "ภาพใหญ่ยังอยู่เหนือเส้นเฉลี่ยหลักและ volume ไม่อ่อนผิดปกติ จึงยังมองเป็นขาขึ้นระยะยาว"}

    if price < ema20 and ema20 <= ema50:
        return {"bias": "bearish", "fallback_reason": "ราคาอยู่ใต้เส้นเฉลี่ยหลักและแรงหนุนยังไม่ฟื้นพอ ทำให้ภาพเดือนยังค่อนข้างอ่อน"}

    if change_pct is not None and abs(change_pct) < 5:
        return {"bias": "neutral", "fallback_reason": "ภาพรายเดือนยังแกว่งกลางกรอบและ volume ยังไม่ยืนยันการเลือกทางชัดเจน"}

    return {"bias": "neutral", "fallback_reason": "ภาพใหญ่ยังไม่ชัดพอจะยืนยันแนวโน้มระยะยาว"}


def _build_trend_summary(context):
    day = _infer_day_trend(context.get("day", {}))
    week = _infer_week_trend(context.get("week", {}))
    month = _infer_month_trend(context.get("month", {}))

    for item in (day, week, month):
        emoji, status_text = _status_from_bias(item["bias"])
        item["status_emoji"] = emoji
        item["status_text"] = status_text

    return {"day": day, "week": week, "month": month}


def _choose_dominant_bias(trends):
    score = 0
    for timeframe in ("day", "week", "month"):
        bias = trends.get(timeframe, {}).get("bias")
        if bias == "bullish":
            score += 1
        elif bias == "bearish":
            score -= 1

    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"

    for timeframe in ("day", "week", "month"):
        bias = trends.get(timeframe, {}).get("bias")
        if bias in ("bullish", "bearish"):
            return bias
    return "neutral"


def _build_rr_note(rr_ratio):
    ratio = _safe_optional_float(rr_ratio)
    if ratio is None:
        return "ข้อมูลไม่เพียงพอ"
    if ratio < 1.0:
        return f"⚠️ {ratio:.2f} — ผลตอบแทนน้อยกว่าความเสี่ยง ควรรอจังหวะที่ดีกว่านี้"
    if ratio < 1.5:
        return f"{ratio:.2f} — พอใช้ได้ แต่ควรรอ price action ยืนยันก่อนเข้า"
    if ratio < 2.0:
        return f"{ratio:.2f} — อยู่ในเกณฑ์ดี เหมาะเข้าเทรดได้"
    return f"✅ {ratio:.2f} — ดีเยี่ยม เสี่ยง 1 ส่วน แลกผลตอบแทน {ratio:.1f} ส่วน"


def _build_deterministic_plan(context, dominant_bias):
    day = context.get("day", {})
    week = context.get("week", {})
    month = context.get("month", {})
    current_price = _first_valid(context.get("price"), day.get("price"), week.get("price"), month.get("price"))

    if current_price is None:
        return {
            "bias": dominant_bias,
            "day_plan": {"entry_low": None, "entry_high": None, "tp1": None, "tp2": None, "sl": None, "rr_ratio": "N/A", "rr_note": "ข้อมูลไม่เพียงพอ"},
            "position_plan": {"add_low": None, "add_high": None, "tp_long": None, "trailing_stop": None},
        }

    bias = "bearish" if dominant_bias == "bearish" else "bullish"

    # 🌟 ATR-based volatility — ใช้ปรับ stop placement ให้สมเหตุสมผลกับ volatility ของหุ้น
    atr_day = _safe_optional_float(day.get("atr"))
    atr_week = _safe_optional_float(week.get("atr"))
    # day ATR ใช้กับ short stop, week ATR backup ถ้า day ใช้ไม่ได้
    atr_for_stop = atr_day if (atr_day and atr_day > 0) else (atr_week / 5.0 if (atr_week and atr_week > 0) else None)

    if bias == "bullish":
        entry_anchor = _median([day.get("support"), day.get("poc"), day.get("ema20"), week.get("poc"), current_price]) or current_price
        # 🌟 Entry range: anchor ± 1% — ไม่ stretch ไปถึงราคาปัจจุบัน (กันช่วงกว้างเกิน)
        entry_low = entry_anchor * 0.99
        entry_high = entry_anchor * 1.01
        # ถ้า anchor สูงกว่าราคาปัจจุบัน (anchor = ราคาปัจจุบัน) ให้ลด entry ลงเล็กน้อย (รอย่อ)
        if entry_low > current_price:
            entry_low = current_price * 0.985
            entry_high = current_price * 0.995
        entry_mid = (entry_low + entry_high) / 2
        sl_base = _first_valid(day.get("support"), week.get("support"), day.get("ema50"), entry_low * 0.97)
        # 🌟 ATR-based SL: SL = entry_mid - 1.5×ATR (ATR ปรับตาม volatility)
        # ถ้า ATR-based SL ลึกกว่า support → ใช้ ATR-based เพราะป้องกัน stop hunt
        atr_sl_candidate = entry_mid - 1.5 * atr_for_stop if atr_for_stop else None
        sl = min(sl_base * 0.985, entry_mid * 0.985)
        if atr_sl_candidate is not None and atr_sl_candidate < sl:
            sl = atr_sl_candidate
        if sl >= entry_mid:
            sl = entry_mid * 0.97
        # 🌟 SL ไม่ควรใกล้ราคาปัจจุบันเกินไป — กัน premature stop
        min_stop_distance = (atr_for_stop * 0.5) if atr_for_stop else (entry_mid * 0.01)
        if (entry_mid - sl) < min_stop_distance:
            sl = entry_mid - min_stop_distance

        risk = max(entry_mid - sl, entry_mid * 0.015)
        tp1 = _first_valid(day.get("resistance"), week.get("poc"), entry_mid + risk * 1.2)
        if tp1 <= entry_mid:
            tp1 = entry_mid + risk * 1.2
        tp2 = _first_valid(week.get("resistance"), month.get("poc"), month.get("resistance"), tp1 + risk * 1.2)
        # 🌟 บังคับ TP2 ต้องห่างจาก TP1 อย่างน้อย 3% ของ entry (กัน TP1≈TP2)
        min_tp_gap = entry_mid * 0.03
        if tp2 <= tp1 + min_tp_gap:
            tp2 = tp1 + max(risk * 1.2, min_tp_gap)

        rr_ratio = (tp2 - entry_mid) / max(entry_mid - sl, 0.01)
        add_anchor = _median([week.get("support"), day.get("support"), month.get("poc"), entry_mid]) or entry_mid
        add_low = min(add_anchor * 0.99, entry_mid)
        add_high = max(add_anchor * 1.01, entry_mid)
        tp_long = _first_valid(month.get("resistance"), tp2 + risk * 1.3, entry_mid * 1.12)
        if tp_long <= tp2:
            tp_long = tp2 + max(risk, entry_mid * 0.04)
        trailing_stop = max(entry_mid, _first_valid(week.get("support"), day.get("ema20"), entry_mid))
    else:
        # Bearish (ซื้อหุ้น): แนวโน้มขาลง — รอซื้อที่แนวรับลึกกว่าปกติ, ขายทำกำไรเมื่อเด้ง
        entry_anchor = _median([day.get("support"), week.get("support"), day.get("ema50"), current_price]) or current_price
        entry_low = min(entry_anchor * 0.97, current_price * 0.95)
        entry_high = min(entry_anchor * 0.99, current_price * 0.98)
        if entry_high <= entry_low:
            entry_high = entry_low * 1.01
        entry_mid = (entry_low + entry_high) / 2
        sl_base = _first_valid(week.get("support"), month.get("support"), entry_low * 0.93)
        # 🌟 ATR-based SL สำหรับ bearish (ใช้ ATR ใหญ่กว่า bullish เพราะ swing trade ระยะยาวกว่า)
        atr_sl_candidate = entry_mid - 2.0 * atr_for_stop if atr_for_stop else None
        sl = min(sl_base * 0.97, entry_mid * 0.93)
        if atr_sl_candidate is not None and atr_sl_candidate < sl:
            sl = atr_sl_candidate
        if sl >= entry_mid:
            sl = entry_mid * 0.93
        min_stop_distance = (atr_for_stop * 0.7) if atr_for_stop else (entry_mid * 0.015)
        if (entry_mid - sl) < min_stop_distance:
            sl = entry_mid - min_stop_distance

        risk = max(entry_mid - sl, entry_mid * 0.02)
        tp1 = _first_valid(day.get("resistance"), day.get("ema20"), entry_mid + risk * 1.2)
        if tp1 <= entry_mid:
            tp1 = entry_mid + risk * 1.2
        tp2 = _first_valid(day.get("resistance"), week.get("poc"), week.get("resistance"), tp1 + risk * 1.0)
        # 🌟 บังคับ TP2 ห่างจาก TP1 อย่างน้อย 3%
        min_tp_gap = entry_mid * 0.03
        if tp2 <= tp1 + min_tp_gap:
            tp2 = tp1 + max(risk * 1.2, min_tp_gap)

        rr_ratio = (tp2 - entry_mid) / max(entry_mid - sl, 0.01)
        add_anchor = _median([week.get("support"), month.get("support"), entry_mid]) or entry_mid
        add_low = min(add_anchor * 0.97, entry_mid * 0.95)
        add_high = min(add_anchor * 0.99, entry_mid * 0.98)
        if add_high <= add_low:
            add_high = add_low * 1.01
        tp_long = _first_valid(month.get("resistance"), week.get("resistance"), tp2 + risk * 1.5)
        if tp_long <= tp2:
            tp_long = tp2 + max(risk, entry_mid * 0.05)
        trailing_stop = max(sl, _first_valid(week.get("support"), entry_mid * 0.95))

    rr_ratio_value = _safe_optional_float(rr_ratio)

    # 🌟 Plan validation layer — ตรวจ consistency + ATR bounds ก่อน return
    # 1. Bullish ต้อง: TP2 > TP1 > entry_high, SL < entry_low
    # 2. TP1 ระยะห่างไม่ควรเกิน 3×ATR (กัน TP เพ้อฝัน)
    # 3. SL ระยะห่างไม่ควรเกิน 3×ATR (กัน SL ลึกเกินจน 1 trade ผิดพอร์ตพังหมด)
    plan_warnings = []
    if bias == "bullish":
        if tp2 <= tp1 or tp1 <= entry_mid or sl >= entry_mid:
            plan_warnings.append("plan_consistency_failed")
    else:
        if tp2 <= tp1 or tp1 <= entry_mid or sl >= entry_mid:
            plan_warnings.append("plan_consistency_failed")
    if atr_for_stop and atr_for_stop > 0:
        if abs(tp1 - entry_mid) > 3.0 * atr_for_stop:
            plan_warnings.append("tp1_too_far_atr")
        if abs(entry_mid - sl) > 3.0 * atr_for_stop:
            plan_warnings.append("sl_too_far_atr")

    return {
        "bias": bias,
        "day_plan": {
            "entry_low": _round_price(entry_low),
            "entry_high": _round_price(entry_high),
            "tp1": _round_price(tp1),
            "tp2": _round_price(tp2),
            "sl": _round_price(sl),
            "rr_ratio": f"{rr_ratio_value:.2f}" if rr_ratio_value is not None else "N/A",
            "rr_note": _build_rr_note(rr_ratio_value),
            "atr": _round_price(atr_for_stop) if atr_for_stop else None,
            "validation_warnings": plan_warnings,
        },
        "position_plan": {
            "add_low": _round_price(add_low),
            "add_high": _round_price(add_high),
            "tp_long": _round_price(tp_long),
            "trailing_stop": _round_price(trailing_stop),
        },
    }


def _default_strategy_payload(deterministic_plan):
    bias = deterministic_plan.get("bias")
    if bias == "bearish":
        return {
            "day_plan": {
                "strategy_name": "รอจังหวะซื้อที่แนวรับลึก",
                "strategy_line": "แนวโน้มยังเป็นขาลง ควรรอราคาลงมาถึงแนวรับสำคัญแล้วค่อยประเมินแรงซื้อกลับก่อนเข้า",
            },
            "position_plan": {
                "strategy_name": "รอดูสถานการณ์ ยังไม่เร่งสะสม",
                "strategy_line": "โครงสร้างยังอ่อน ควรรอสัญญาณกลับตัวที่ชัดเจนก่อนเริ่มทยอยสะสม",
                "advice": "อย่ารีบซื้อช่วงขาลง ให้ราคายืนยันพื้นก่อนแล้วค่อยทยอยเข้าด้วยไซส์เล็ก",
            },
        }
    return {
        "day_plan": {
            "strategy_name": "ย่อซื้อเล่นรอบ Buy on Dip",
            "strategy_line": "โฟกัสรอรับเมื่อราคาย่อลงใกล้โซนรับสำคัญแล้วค่อยดูแรงซื้อกลับก่อนตัดสินใจ",
        },
        "position_plan": {
            "strategy_name": "ถือรันเทรนด์ และ ทยอยสะสม Trend Following",
            "strategy_line": "โฟกัสการถือบนภาพใหญ่และค่อยเติมน้ำหนักเมื่อราคาอ่อนตัวแต่โครงสร้างหลักยังไม่เสีย",
            "advice": "เน้นปล่อยให้กำไรเติบโตตามแนวโน้มหลัก โดยอิงภาพกราฟสัปดาห์มากกว่าความผันผวนรายวัน",
        },
    }


def _default_ai_insight(context, dominant_bias):
    insight_parts = []
    if dominant_bias == "bearish":
        insight_parts.append("ระวังแรงขายทำกำไรจะกลับมากดดันหากราคาเด้งขึ้นแล้วไม่ผ่านแนวต้านหลักในภาพวันและภาพสัปดาห์")
    elif dominant_bias == "bullish":
        insight_parts.append("หากราคายังยืนเหนือโซนรับหลักได้ มีโอกาสเห็นการไต่ระดับต่อแบบค่อยเป็นค่อยไป แต่ควรดูแรงซื้อยืนยันทุกครั้ง")
    else:
        insight_parts.append("ภาพรวมยังอยู่ในช่วงเลือกทาง จึงควรรอให้ราคายืนยันเหนือแนวต้านหรือหลุดแนวรับสำคัญก่อนเพิ่ม conviction")

    if context.get("is_extreme_volatility"):
        insight_parts.append("ช่วงนี้ความผันผวนค่อนข้างสูงหรือมี volume spike เด่น ทำให้ indicator อาจเชื่อถือได้น้อยลงในจังหวะข่าวแรง")

    return " ".join(insight_parts[:2])


def _build_member_defaults(context, trends, deterministic_plan):
    strategy_defaults = _default_strategy_payload(deterministic_plan)
    bias = _choose_dominant_bias(trends)
    day = context.get("day", {})
    support = _format_price(day.get("support"))
    resistance = _format_price(day.get("resistance"))
    if bias == "bearish":
        watch_next_default = f"ราคาเด้งกลับมาทดสอบ {resistance} — ถ้าผ่านไม่ได้ มีสิทธิย่อต่อ"
        confirmation_default = f"ราคายืนเหนือ {resistance} 2-3 วัน + Vol เพิ่ม"
        invalidation_default = f"หลุด {support} พร้อม Vol สูง = แนวโน้มขาลงยังไม่จบ"
    elif bias == "bullish":
        watch_next_default = f"จับตาแนวต้าน {resistance} — ผ่านได้จะเปิด upside ใหม่"
        confirmation_default = f"ปิดเหนือ {resistance} + RSI ไม่หลุด 50"
        invalidation_default = f"หลุดแนวรับ {support} พร้อม Vol สูง = ยกเลิกแผน"
    else:
        watch_next_default = f"รอราคาเลือกทาง — ผ่าน {resistance} หรือหลุด {support}"
        confirmation_default = "รอ price action ยืนยันทิศทางใน 2-3 วัน"
        invalidation_default = "ภาพรวมยังไม่ชัด ยังไม่ควรรีบเข้า"
    return {
        "trend_radar": {
            "day": {"reason": trends["day"]["fallback_reason"]},
            "week": {"reason": trends["week"]["fallback_reason"]},
            "month": {"reason": trends["month"]["fallback_reason"]},
        },
        "day_plan": strategy_defaults["day_plan"],
        "position_plan": strategy_defaults["position_plan"],
        "watch_next": watch_next_default,
        "confirmation_signal": confirmation_default,
        "invalidation": invalidation_default,
        "ai_insight": _default_ai_insight(context, bias),
    }


# 🌟 System Instruction — static content ที่ใช้ซ้ำทุกคำขอ
# Gemini 2.5 จะ cache ส่วนนี้อัตโนมัติ (implicit caching) → ลดค่า API + เร็วขึ้น
_MEMBER_SYSTEM_INSTRUCTION = """
คุณคือนักวิเคราะห์เทคนิคหุ้นของ Apexify — ตอบเป็น JSON object เท่านั้น ห้ามมี markdown หรือข้อความใดนอก JSON

กฎเหล็ก:
- ห้ามชี้นำซื้อขายเด็ดขาด (ห้ามใช้คำ: "ซื้อเลย" "ขายเลย" "การันตี" "รับประกัน" "100%")
- ภาษาไทยสะกดถูกต้อง ห้ามใช้คำแปลก เช่น "เกรงทึ่ง"(→แข็งแกร่ง) "ทดฐาน"(→ทดสอบฐาน) "แนวราคา"(→แนวโน้มราคา) "โมเมนตั้ม"(→โมเมนตัม)
- โทนเป็นกลาง-ระวัง: bearish→แนะรอซื้อที่แนวรับลึก ห้ามรีบเข้า
- extreme volatility→เตือนใน ai_insight เสมอ
- ข้อมูลไม่พอ→ใช้คำว่า "ข้อมูลไม่เพียงพอ"
- ทุกฟิลด์ "สั้น" = ห้ามเกิน 80 ตัวอักษร และต้อง actionable ไม่ใช่ขยายความซ้ำ
- ฟิลด์ watch_next/confirmation_signal/invalidation = ห้ามเกิน 120 ตัวอักษร

Output schema (ตอบเฉพาะ JSON object ตามนี้):
{
  "trend_radar": {
    "day": {"reason": "..."},
    "week": {"reason": "..."},
    "month": {"reason": "..."}
  },
  "day_plan": {"strategy_name": "...", "strategy_line": "..."},
  "position_plan": {"strategy_name": "...", "strategy_line": "...", "advice": "..."},
  "watch_next": "จุด/เงื่อนไขที่ต้องเฝ้าในไม่กี่วันข้างหน้า",
  "confirmation_signal": "เงื่อนไขที่ทำให้ Plan ใช้ได้จริง",
  "invalidation": "เงื่อนไขที่ทำให้ Plan ใช้ไม่ได้ ต้องยกเลิก",
  "ai_insight": "สรุป actionable 1-2 ประโยค ห้ามซ้ำ trend_radar"
}
""".strip()


def _build_member_prompt(context, trends, defaults, tier):
    """Dynamic content per-symbol — prepend to contents (system_instruction มี rules แล้ว)"""
    def trend_snapshot(label, snapshot):
        if not snapshot.get("available"):
            return f"{label}: N/A"
        fp = _format_price
        return (
            f"{label}: P={fp(snapshot.get('price'))} RSI={fp(snapshot.get('rsi'))} "
            f"MACD={fp(snapshot.get('macd'))}/{fp(snapshot.get('signal'))} "
            f"EMA={fp(snapshot.get('ema20'))}/{fp(snapshot.get('ema50'))} "
            f"POC={fp(snapshot.get('poc'))} S={fp(snapshot.get('support'))} R={fp(snapshot.get('resistance'))} "
            f"Vol={fp(snapshot.get('volume_ratio'))} Cons={fp(snapshot.get('consolidation_pct'))}"
        )

    tier_label = "VIP" if tier == "vip" else "PRO"
    return f"""
tier={tier_label} | {context.get('symbol')} @ {_format_price(context.get('price'))} | bias: D={trends['day']['bias']} W={trends['week']['bias']} M={trends['month']['bias']} | extreme_vol={str(bool(context.get('is_extreme_volatility'))).lower()}

{trend_snapshot('D', context.get('day', {}))}
{trend_snapshot('W', context.get('week', {}))}
{trend_snapshot('M', context.get('month', {}))}
""".strip()


def _request_member_payload(prompt, defaults, cache_key=None):
    """เรียก Gemini พร้อม system_instruction (implicit caching) + fallback + in-process cache"""
    # 🌟 In-process cache — key=(symbol,bias,price-bucket), TTL=300s → ตัด 3-8 วิ บน hit
    if cache_key is not None:
        cached = _ai_cache_get(cache_key)
        if cached is not None:
            print(f"[ai-cache] HIT  {cache_key}", flush=True)
            return json.loads(json.dumps(cached, ensure_ascii=False))

    fallback = json.loads(json.dumps(defaults, ensure_ascii=False))
    try:
        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            system_instruction=_MEMBER_SYSTEM_INSTRUCTION,
            temperature=0.3,
            response_mime_type="application/json",
        )
    except ImportError:
        config = None

    prompts = [
        prompt,
        f"{prompt}\n\nย้ำ: ตอบเฉพาะ JSON object ที่ parse ได้ทันที ห้ามมีข้อความอื่น",
    ]

    for candidate_prompt in prompts:
        t0 = _time.time()
        try:
            kwargs = {"model": "gemini-2.5-flash", "contents": candidate_prompt}
            if config is not None:
                kwargs["config"] = config
            response = _gemini_call_with_timeout(timeout_s=GEMINI_DEFAULT_TIMEOUT_S, **kwargs)
            raw_text = getattr(response, "text", "") or ""
            payload_block = _extract_json_block(raw_text)
            if not payload_block:
                continue
            parsed = json.loads(payload_block)
            if isinstance(parsed, dict):
                elapsed = _time.time() - t0
                print(f"[ai-cache] MISS {cache_key} fetched ({elapsed:.2f}s)", flush=True)
                if cache_key is not None:
                    _ai_cache_set(cache_key, parsed)
                return parsed
        except Exception as e:
            # Log retry failure — debug ง่ายขึ้นเวลา Gemini ขัดข้อง
            print(f"[ai-cache] retry fail (key={cache_key}): {type(e).__name__}: {str(e)[:120]}", flush=True)
            continue

    print(f"[ai-cache] all {len(prompts)} retries exhausted (key={cache_key}) → fallback", flush=True)
    return fallback


def _merge_member_payload(defaults, payload, context):
    merged = json.loads(json.dumps(defaults, ensure_ascii=False))
    payload = payload if isinstance(payload, dict) else {}

    trend_payload = payload.get("trend_radar", {}) if isinstance(payload.get("trend_radar"), dict) else {}
    for timeframe in ("day", "week", "month"):
        current_reason = merged["trend_radar"][timeframe]["reason"]
        snapshot = context.get(timeframe, {})
        reason_candidate = None
        if isinstance(trend_payload.get(timeframe), dict):
            reason_candidate = trend_payload[timeframe].get("reason")
        if snapshot.get("available") and current_reason != "ข้อมูลไม่เพียงพอ":
            merged["trend_radar"][timeframe]["reason"] = _clean_ai_text(reason_candidate, current_reason)

    day_payload = payload.get("day_plan", {}) if isinstance(payload.get("day_plan"), dict) else {}
    position_payload = payload.get("position_plan", {}) if isinstance(payload.get("position_plan"), dict) else {}

    merged["day_plan"]["strategy_name"] = _clean_ai_text(day_payload.get("strategy_name"), merged["day_plan"]["strategy_name"])
    merged["day_plan"]["strategy_line"] = _clean_ai_text(day_payload.get("strategy_line"), merged["day_plan"]["strategy_line"])
    merged["position_plan"]["strategy_name"] = _clean_ai_text(position_payload.get("strategy_name"), merged["position_plan"]["strategy_name"])
    merged["position_plan"]["strategy_line"] = _clean_ai_text(position_payload.get("strategy_line"), merged["position_plan"]["strategy_line"])
    merged["position_plan"]["advice"] = _clean_ai_text(position_payload.get("advice"), merged["position_plan"]["advice"])
    merged["watch_next"] = _clean_ai_text(payload.get("watch_next"), merged["watch_next"])
    merged["confirmation_signal"] = _clean_ai_text(payload.get("confirmation_signal"), merged["confirmation_signal"])
    merged["invalidation"] = _clean_ai_text(payload.get("invalidation"), merged["invalidation"])
    merged["ai_insight"] = _clean_ai_text(payload.get("ai_insight"), merged["ai_insight"])

    if context.get("is_extreme_volatility") and "indicator อาจเชื่อถือได้น้อยลง" not in merged["ai_insight"]:
        merged["ai_insight"] = f"{merged['ai_insight']} ช่วงนี้ความผันผวนค่อนข้างสูง จึงควรเผื่อใจว่า indicator อาจเชื่อถือได้น้อยลง"

    return merged


def _build_member_analysis(context, tier):
    trends = _build_trend_summary(context)
    dominant_bias = _choose_dominant_bias(trends)
    deterministic_plan = _build_deterministic_plan(context, dominant_bias)
    defaults = _build_member_defaults(context, trends, deterministic_plan)
    prompt = _build_member_prompt(context, trends, defaults, tier)
    cache_key = _ai_cache_key(context.get("symbol"), dominant_bias, context.get("price"))
    payload = _request_member_payload(prompt, defaults, cache_key=cache_key)
    analysis = _merge_member_payload(defaults, payload, context)
    return trends, deterministic_plan, analysis


def _entry_note_from_bias(plan_bias, context):
    if plan_bias == "bearish":
        support = _format_price(_first_valid(context.get("day", {}).get("support"), context.get("week", {}).get("support")))
        return f"รอซื้อที่แนวรับลึกแถว {support} เมื่อเห็นสัญญาณหยุดลง — ไม่ควรรีบซื้อช่วงขาลง"
    support = _format_price(_first_valid(context.get("day", {}).get("support"), context.get("week", {}).get("poc")))
    return f"เข้าซื้อเมื่อราคาย่อลงมาทดสอบโซนรับแถว {support} แล้วมีแรงซื้อกลับ"


def _tp1_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "ขายบางส่วนเมื่อเด้งขึ้นมาถึงโซนนี้"
    return "แบ่งขายบางส่วนเพื่อล็อกกำไร"


def _tp2_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "เป้าหลัก — โซนต้านที่ราคาอาจเด้งกลับขึ้นไปถึง"
    return "เป้าหลัก — โซนต้านใหญ่ หากผ่านได้จะเปิด upside เพิ่ม"


def _stop_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "ขายตัดขาดทุนหากราคาหลุดโซนนี้ เพราะอาจลงต่อ"
    return "ตัดขาดทุนทันทีหากราคาหลุดโซนนี้"


def _position_add_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "หากราคาลงมาถึงแนวรับใหญ่ อาจทยอยสะสมเพิ่มอย่างระมัดระวัง"
    return "หากราคาย่อลงมาเทสฐานใหญ่ อาจทยอยสะสมเพิ่มได้"


def _position_trailing_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "ขยับ SL ขึ้นตามราคาเมื่อเริ่มฟื้นตัว เพื่อป้องกันขาดทุนเพิ่ม"
    return "ขยับ SL ขึ้นตามราคาเพื่อไม่ให้กำไรกลายเป็นขาดทุน"


def _calculate_conviction_score(context, trends):
    dominant_bias = _choose_dominant_bias(trends)
    day = context.get("day", {})
    score = 50

    weights = {"day": 16, "week": 12, "month": 10}
    for timeframe, weight in weights.items():
        bias = trends.get(timeframe, {}).get("bias", "neutral")
        if dominant_bias == "neutral":
            if bias == "neutral":
                score += max(3, weight // 4)
        else:
            if bias == dominant_bias:
                score += weight
            elif bias == "neutral":
                score += max(2, weight // 5)
            else:
                score -= weight

    rsi = _safe_optional_float(day.get("rsi"))
    if rsi is not None:
        if 45 <= rsi <= 65:
            score += 6
        elif rsi > 85 or rsi < 15:
            score -= 10
        elif rsi > 75 or rsi < 25:
            score -= 6

    volume_ratio = _safe_optional_float(day.get("volume_ratio"))
    if volume_ratio is not None:
        if volume_ratio >= 1.8:
            score += 8
        elif volume_ratio >= 1.2:
            score += 5
        elif volume_ratio < 0.7:
            score -= 5

    price = _safe_optional_float(context.get("price") or day.get("price"))
    ema20 = _safe_optional_float(day.get("ema20"))
    if price is not None and ema20 not in (None, 0):
        if dominant_bias == "bullish" and price > ema20:
            score += 5
        elif dominant_bias == "bearish" and price < ema20:
            score += 5
        elif dominant_bias in ("bullish", "bearish"):
            score -= 4

    score = max(20, min(95, score))
    if score >= 80:
        return score, "สูงมาก", "🔥"
    if score >= 68:
        return score, "ค่อนข้างสูง", "🚀"
    if score >= 55:
        return score, "ปานกลาง", "⚖️"
    return score, "ระวัง", "🛡️"


def _build_trend_badges(trends):
    return "⏱️ Day {day} • 📅 Week {week} • 🔭 Month {month}".format(
        day=trends.get("day", {}).get("status_emoji", "⚪️"),
        week=trends.get("week", {}).get("status_emoji", "⚪️"),
        month=trends.get("month", {}).get("status_emoji", "⚪️"),
    )


def _build_member_snapshot(context, trends, tier):
    day = context.get("day", {})
    symbol = context.get("symbol", "UNKNOWN")
    price = _safe_optional_float(context.get("price") or day.get("price"))
    ema20 = _safe_optional_float(day.get("ema20"))
    rsi = _safe_optional_float(day.get("rsi"))
    macd = _safe_optional_float(day.get("macd"))
    signal = _safe_optional_float(day.get("signal"))
    volume = _safe_optional_float(day.get("volume"))
    avg_volume = _safe_optional_float(day.get("avg_volume"))
    support = _safe_optional_float(day.get("support"))
    resistance = _safe_optional_float(day.get("resistance"))
    poc = _safe_optional_float(day.get("poc"))
    bb_lower = _safe_optional_float(day.get("bb_lower"))
    bb_upper = _safe_optional_float(day.get("bb_upper"))

    momentum = "🟢 ขาขึ้น" if price is not None and ema20 is not None and price > ema20 else "🔴 ขาลง"
    if rsi is None:
        rsi_status = "⚪️ ไม่มีข้อมูล"
    elif rsi > 70:
        rsi_status = "🔴 Overbought — ระวังแรงขายทำกำไร"
    elif rsi < 30:
        rsi_status = "🟢 Oversold — อาจมีแรงดีดกลับ"
    else:
        rsi_status = "⚪️ Neutral"

    if macd is None or signal is None:
        macd_status = "⚪️ ไม่มีข้อมูล"
        macd_detail = ""
    else:
        macd_status = "🟢 โมเมนตัมบวก" if macd > signal else "🔴 แรงส่งอ่อนลง"
        macd_detail = f"({macd:.2f} / {signal:.2f})"

    obv_trend = str(day.get("obv_trend") or "flat").lower()
    if obv_trend == "up":
        volume_status = "📈 เงินไหลเข้า (Inflow)"
    elif obv_trend == "down":
        volume_status = "📉 เงินไหลออก (Outflow)"
    else:
        volume_status = "➖ ทรงตัว"

    trend_detail = ""
    if price is not None and ema20 not in (None, 0):
        trend_detail = f"{((price - ema20) / ema20) * 100:+.2f}% vs EMA20"

    volume_detail = ""
    if volume is not None and avg_volume is not None:
        volume_detail = f"Vol {_format_compact_number(volume)} | Avg {_format_compact_number(avg_volume)}"

    conviction_score, conviction_label, conviction_emoji = _calculate_conviction_score(context, trends)
    tier_badge = "👑 *PRO Report*" if tier == "pro" else "💎 *VIP Report*"

    lines = [
        f"{'━' * 17}",
        f"{tier_badge}",
        f"*🤖 Apexify AI — {symbol}*",
    ]

    # 🥇 Commodity/crypto description — บอกชัดเจนว่า ETF/coin ตัวนี้คืออะไร
    commodity_desc = _COMMODITY_REPORT_DESC.get(symbol)
    if commodity_desc:
        lines.append(f"_{commodity_desc}_")

    lines.extend([
        f"{'━' * 17}",
        f"💵 *ราคา:* {_format_price(price)}",
        f"📡 *Trend:* {_build_trend_badges(trends)}",
        f"🎯 *Conviction:* {conviction_emoji} {conviction_score}/100  _{conviction_label}_",
        "─ ─ ─ ─ ─ ─ ─ ─ ─",
        "*📊 วิเคราะห์สุขภาพหุ้น*",
        f"• 🌊 *Trend:* {momentum}  {trend_detail}",
        f"• 🌡 *RSI {_format_price(rsi)}:* {rsi_status}",
        f"• ⚡️ *MACD:* {macd_status}  {macd_detail}",
        f"• 💧 *Volume:* {volume_status}  {volume_detail}",
        "─ ─ ─ ─ ─ ─ ─ ─ ─",
        "*🗺 โซนราคาสำคัญ*",
        f"• 🟢 *แนวรับ:* {_format_price(support)}",
        f"• 🔴 *แนวต้าน:* {_format_price(resistance)}",
    ])

    if poc is not None:
        lines.append(f"• 🟡 *POC (โซนคนกระจุก):* {_format_price(poc)}")
    if bb_lower is not None and bb_upper is not None:
        lines.append(f"• 🔵 *Bollinger Band:* {_format_price(bb_lower)} — {_format_price(bb_upper)}")

    return "\n".join(lines)


def _fallback_context_from_tech_data(tech_data):
    def pick(*keys):
        for key in keys:
            value = tech_data.get(key)
            if value is not None:
                return value
        return None

    day_snapshot = {
        "available": True,
        "price": pick("price"),
        "rsi": pick("rsi"),
        "macd": pick("macd", "macd_line"),
        "signal": pick("macd_signal", "signal_line"),
        "ema20": pick("ema20"),
        "ema50": pick("ema50"),
        "ema200": pick("ema200"),
        "volume": pick("volume"),
        "avg_volume": pick("avg_volume"),
        "volume_ratio": None,
        "support": pick("support"),
        "resistance": pick("resistance"),
        "poc": pick("poc_price"),
        "bb_lower": pick("lower_band", "bb_lower"),
        "bb_upper": pick("upper_band", "bb_upper"),
        "obv_trend": pick("obv_trend"),
        "consolidation_pct": None,
        "close_change_pct": None,
    }

    return {
        "symbol": tech_data.get("symbol", "UNKNOWN"),
        "price": pick("price"),
        "day": day_snapshot,
        "week": {"available": False},
        "month": {"available": False},
        "is_extreme_volatility": False,
    }


def _render_vip_report(context, trends, analysis):
    """VIP: ภาพรวม + Trend Radar + Watch Next + Insight (ไม่มี entry/TP/SL ตัวเลข — นั่นคือ PRO)"""
    return "\n".join(
        [
            _build_member_snapshot(context, trends, "vip"),
            "",
            "*🔭 AI Trend Radar — 3 ระยะ*",
            f"• ⏱ *วัน:* {trends['day']['status_emoji']} {trends['day']['status_text']} — {analysis['trend_radar']['day']['reason']}",
            f"• 📅 *สัปดาห์:* {trends['week']['status_emoji']} {trends['week']['status_text']} — {analysis['trend_radar']['week']['reason']}",
            f"• 🔭 *เดือน:* {trends['month']['status_emoji']} {trends['month']['status_text']} — {analysis['trend_radar']['month']['reason']}",
            "",
            f"*👀 Watch Next:* {analysis['watch_next']}",
            "",
            f"*🧠 AI Insight:* {analysis['ai_insight']}",
            "",
            "_💎 อัปเกรดเป็น PRO เพื่อดู Entry/TP/SL ตัวเลข + R:R + Smart Alerts_",
            "",
            DISCLAIMER_TEXT,
        ]
    )


def _render_pro_report(context, trends, deterministic_plan, analysis):
    plan_bias = deterministic_plan.get("bias", "bullish")
    day_plan = deterministic_plan["day_plan"]
    position_plan = deterministic_plan["position_plan"]
    bias_label = "⚠️ ขาลง — รอจังหวะ" if plan_bias == "bearish" else "✅ ขาขึ้น — เปิดรับความเสี่ยง"
    current_price = _first_valid(
        context.get("price"),
        context.get("day", {}).get("price"),
    )

    return "\n".join(
        [
            _build_member_snapshot(context, trends, "pro"),
            "",
            "*🔭 AI Trend Radar — 3 ระยะ*",
            f"• ⏱ *วัน:* {trends['day']['status_emoji']} {trends['day']['status_text']} — {analysis['trend_radar']['day']['reason']}",
            f"• 📅 *สัปดาห์:* {trends['week']['status_emoji']} {trends['week']['status_text']} — {analysis['trend_radar']['week']['reason']}",
            f"• 🔭 *เดือน:* {trends['month']['status_emoji']} {trends['month']['status_text']} — {analysis['trend_radar']['month']['reason']}",
            "",
            f"*🎯 Actionable Plan — {bias_label}*",
            "",
            f"*🏃 สายสั้น {'(รอจังหวะ)' if plan_bias == 'bearish' else '(Swing)'} — กรอบ 1-4 สัปดาห์*",
            f"  💡 {analysis['day_plan']['strategy_name']} — {analysis['day_plan']['strategy_line']}",
            f"  📍 *เข้าซื้อ:* {_format_range_with_pct(day_plan['entry_low'], day_plan['entry_high'], current_price)}",
            f"  🎯 *TP1:* {_format_price_with_pct(day_plan['tp1'], current_price)}",
            f"  🎯 *TP2:* {_format_price_with_pct(day_plan['tp2'], current_price)}",
            f"  🛑 *SL:* {_format_price_with_pct(day_plan['sl'], current_price)}",
            f"  ⚖️ *R:R:* {day_plan['rr_note']}",
            "",
            "*🧘 สายยาว (Position) — กรอบ 3-12 เดือน*",
            f"  💡 {analysis['position_plan']['strategy_name']} — {analysis['position_plan']['strategy_line']}",
            f"  📍 *สะสมเพิ่ม:* {_format_range_with_pct(position_plan['add_low'], position_plan['add_high'], current_price)}",
            f"  🎯 *เป้าระยะยาว:* {_format_price_with_pct(position_plan['tp_long'], current_price)}",
            f"  🛡 *Trailing Stop:* {_format_price_with_pct(position_plan['trailing_stop'], current_price)}",
            "",
            "*🧭 เงื่อนไข Plan*",
            f"  ✅ *ยืนยันเข้า:* {analysis['confirmation_signal']}",
            f"  ❌ *ยกเลิก Plan:* {analysis['invalidation']}",
            f"  👀 *Watch Next:* {analysis['watch_next']}",
            "",
            f"*🧠 AI Insight:* {analysis['ai_insight']}",
            "",
            "_💡 Position Sizing: เสี่ยงไม่เกิน 1-2% ของพอร์ตต่อไม้ — คำนวณจาก SL ด้านบน_",
            "",
            DISCLAIMER_TEXT,
        ]
    )


def _generate_free_report(tech_data):
    symbol = tech_data.get("symbol", "UNKNOWN")
    price = _safe_float(tech_data.get("price", 0))
    rsi = _safe_float(tech_data.get("rsi", 50))
    macd_line = _safe_float(tech_data.get("macd", tech_data.get("macd_line", 0)))
    signal_line = _safe_float(tech_data.get("macd_signal", tech_data.get("signal_line", 0)))
    ema20 = _safe_float(tech_data.get("ema20", 0))
    ema50 = _safe_float(tech_data.get("ema50", 0))
    ema200 = _safe_float(tech_data.get("ema200", 0))
    volume = _safe_float(tech_data.get("volume", 0))
    avg_volume = _safe_float(tech_data.get("avg_volume", 0))
    lower_band = _safe_float(tech_data.get("lower_band", tech_data.get("bb_lower", 0)))
    upper_band = _safe_float(tech_data.get("upper_band", tech_data.get("bb_upper", 0)))
    support = _safe_float(tech_data.get("support", 0))
    resistance = _safe_float(tech_data.get("resistance", 0))
    obv_trend = str(tech_data.get("obv_trend", "คงที่"))
    poc_price = _safe_float(tech_data.get("poc_price", 0))

    momentum = "🟢 ขาขึ้น (Bullish)" if price > ema20 else "🔴 ขาลง (Bearish)"

    if rsi > 70:
        rsi_status = "🔴 ตึงไปนิด (Overbought)"
    elif rsi < 30:
        rsi_status = "🟢 โซนของถูก (Oversold)"
    else:
        rsi_status = "⚪️ กลางๆ รอดูเชิง (Neutral)"

    macd_status = "🟢 มีแรงส่ง (Positive)" if macd_line > signal_line else "🔴 แรงเริ่มแผ่ว (Negative)"
    trend_percent = ((price - ema20) / ema20 * 100) if ema20 else 0.0
    trend_detail = f"({trend_percent:+.2f}% vs EMA20)" if ema20 else "(EMA20: N/A)"
    macd_detail = f"(MACD: {macd_line:.2f} | Signal: {signal_line:.2f})"
    volume_detail = f"(Vol: {_format_compact_number(volume)} | Avg20: {_format_compact_number(avg_volume)})"

    obv_trend_lower = obv_trend.lower()
    if "เพิ่ม" in obv_trend or "up" in obv_trend_lower:
        obv_status = "📈 มีคนแอบเก็บของ (Inflow)"
    elif "ลด" in obv_trend or "down" in obv_trend_lower:
        obv_status = "📉 ระวังแรงรินขาย (Outflow)"
    else:
        obv_status = "➖ นิ่งๆ ทรงตัว"

    report = f"🤖 **Apexify สแกนหุ้น: {symbol}**\n"
    report += f"🏷 **ราคาล่าสุด:** `{price:,.2f}`\n"
    report += "━" * 15 + "\n"
    report += "📊 **[ สุขภาพหุ้นตอนนี้ ]**\n"
    report += f"• 🌊 **เทรนด์หลัก:** {momentum} `{trend_detail}`\n"
    report += f"• 🌡️ **RSI (ความร้อนแรง):** {rsi_status} `({rsi:.2f})`\n"
    report += f"• ⚡ **MACD (โมเมนตัม):** {macd_status} `{macd_detail}`\n"
    report += f"• 💰 **Volume (กระแสเงิน):** {obv_status} `{volume_detail}`\n"
    report += "\n🎯 **[ โซนราคาที่ต้องจับตา ]**\n"
    report += f"• 🟢 **แนวรับ:** `{support:,.2f}`\n"
    report += f"• 🔴 **แนวต้าน (จุดวัดใจ):** `{resistance:,.2f}`\n"

    if poc_price > 0:
        report += f"• 🟡 **โซนคนกระจุกตัว (POC):** `{poc_price:,.2f}` *(จุดสำคัญ)*\n"

    if lower_band != 0 and upper_band != 0:
        report += f"• 🟡 **กรอบแกว่งตัว (BB):** `{lower_band:,.2f} - {upper_band:,.2f}`\n"

    report += "\n💎 *อัปเกรด VIP/PRO เพื่อดู:*\n"
    report += "• 📈 กราฟเทคนิคพร้อม EMA + S/R + POC\n"
    report += "• 🔭 AI Trend Radar 3 ระยะ (วัน/สัปดาห์/เดือน)\n"
    report += "• 🎯 Entry/TP/SL ตัวเลขชัด + กราฟแสดง zone (PRO)\n"
    report += "• 🔔 Smart Alerts + ตั้งเตือนราคา (PRO)\n"
    report += f"\n{DISCLAIMER_TEXT}"
    return report


def generate_apexify_report(tech_data, role="free"):
    """คืน (report_text, plan_dict_or_none)
    plan_dict = day_plan ของ deterministic_plan สำหรับ PRO เท่านั้น (ใช้วาดบนกราฟ)
    Free/VIP คืน plan = None
    """
    normalized_role = str(role or "free").lower()
    if normalized_role not in ("vip", "pro"):
        return _generate_free_report(tech_data), None

    symbol = tech_data.get("symbol") or tech_data.get("ticker") or "UNKNOWN"
    try:
        context = build_multitimeframe_trade_context(symbol)
    except Exception:
        context = _fallback_context_from_tech_data(tech_data)

    try:
        trends, deterministic_plan, analysis = _build_member_analysis(context, normalized_role)
        if normalized_role == "vip":
            return _render_vip_report(context, trends, analysis), None
        return _render_pro_report(context, trends, deterministic_plan, analysis), deterministic_plan.get("day_plan")
    except Exception:
        fallback_context = context or _fallback_context_from_tech_data(tech_data)
        trends = _build_trend_summary(fallback_context)
        deterministic_plan = _build_deterministic_plan(fallback_context, _choose_dominant_bias(trends))
        analysis = _build_member_defaults(fallback_context, trends, deterministic_plan)
        if normalized_role == "vip":
            return _render_vip_report(fallback_context, trends, analysis), None
        return _render_pro_report(fallback_context, trends, deterministic_plan, analysis), deterministic_plan.get("day_plan")


def analyze_payment_slip(file_path_or_bytes):
    prompt = """
    ตรวจสอบรูปนี้ว่าเป็นสลิปโอนเงินผ่านแอปธนาคารของไทยหรือไม่
    ตอบกลับในรูปแบบ JSON เท่านั้น ห้ามมีข้อความอื่น:
    {
        "is_slip": true หรือ false,
        "amount": ตัวเลขยอดเงินโอนแบบไม่มีลูกน้ำ (เช่น 109),
        "ref_no": "เลขที่อ้างอิงบนสลิป"
    }
    """
    try:
        if isinstance(file_path_or_bytes, bytes):
            image = PIL.Image.open(io.BytesIO(file_path_or_bytes))
        else:
            image = PIL.Image.open(file_path_or_bytes)

        response = _gemini_call_with_timeout(
            timeout_s=GEMINI_IMAGE_TIMEOUT_S,
            model="gemini-2.5-flash",
            contents=[image, prompt],
        )
        return response.text
    except Exception:
        return '{"is_slip": false, "amount": 0, "ref_no": ""}'
