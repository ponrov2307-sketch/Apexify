import io
import json
import math
import re

import PIL.Image
from google import genai

from config import GEMINI_API_KEY
from technical_tools import build_multitimeframe_trade_context

client = genai.Client(api_key=GEMINI_API_KEY)

DISCLAIMER_TEXT = (
    "⚠️ *คำเตือน: รายงานนี้เป็นการวิเคราะห์อัตโนมัติเพื่อประกอบการตัดสินใจเท่านั้น "
    "ไม่ใช่คำแนะนำการลงทุน ผู้ใช้งานควรตรวจสอบข้อมูลเพิ่มเติมและประเมินความเสี่ยง"
    "ด้วยตนเองก่อนตัดสินใจทุกครั้ง*"
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
    return cleaned


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
    if ratio > 2:
        return f"หน้าเทรดนี้ได้เปรียบค่อนข้างดี เสี่ยง 1 ส่วน แลกโอกาสผลตอบแทนราว {ratio:.2f} ส่วน แต่ยังควรคุมขนาดไม้ให้เหมาะ"
    if ratio < 1.5:
        return f"อัตราผลตอบแทนต่อความเสี่ยงราว {ratio:.2f} ส่วน ยังไม่เด่นมาก จึงควรรอ price action ช่วยยืนยันเพิ่ม"
    return f"อัตราผลตอบแทนต่อความเสี่ยงราว {ratio:.2f} ส่วน ถือว่าใช้งานได้หากโครงสร้างราคาไม่เสีย"


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

    if bias == "bullish":
        entry_anchor = _median([day.get("support"), day.get("poc"), day.get("ema20"), week.get("poc"), current_price]) or current_price
        entry_low = min(entry_anchor * 0.995, current_price)
        entry_high = max(entry_anchor * 1.005, current_price)
        entry_mid = (entry_low + entry_high) / 2
        sl_base = _first_valid(day.get("support"), week.get("support"), day.get("ema50"), entry_low * 0.97)
        sl = min(sl_base * 0.985, entry_mid * 0.985)
        if sl >= entry_mid:
            sl = entry_mid * 0.97

        risk = max(entry_mid - sl, entry_mid * 0.015)
        tp1 = _first_valid(day.get("resistance"), week.get("poc"), entry_mid + risk * 1.2)
        if tp1 <= entry_mid:
            tp1 = entry_mid + risk * 1.2
        tp2 = _first_valid(week.get("resistance"), month.get("poc"), month.get("resistance"), tp1 + risk * 1.2)
        if tp2 <= tp1:
            tp2 = tp1 + max(risk, entry_mid * 0.03)

        rr_ratio = (tp2 - entry_mid) / max(entry_mid - sl, 0.01)
        add_anchor = _median([week.get("support"), day.get("support"), month.get("poc"), entry_mid]) or entry_mid
        add_low = min(add_anchor * 0.99, entry_mid)
        add_high = max(add_anchor * 1.01, entry_mid)
        tp_long = _first_valid(month.get("resistance"), tp2 + risk * 1.3, entry_mid * 1.12)
        if tp_long <= tp2:
            tp_long = tp2 + max(risk, entry_mid * 0.04)
        trailing_stop = max(entry_mid, _first_valid(week.get("support"), day.get("ema20"), entry_mid))
    else:
        entry_anchor = _median([day.get("resistance"), day.get("poc"), day.get("ema20"), week.get("poc"), current_price]) or current_price
        entry_low = min(entry_anchor * 0.995, current_price)
        entry_high = max(entry_anchor * 1.005, current_price)
        entry_mid = (entry_low + entry_high) / 2
        sl_base = _first_valid(day.get("resistance"), week.get("resistance"), day.get("ema50"), entry_high * 1.03)
        sl = max(sl_base * 1.015, entry_mid * 1.015)
        if sl <= entry_mid:
            sl = entry_mid * 1.03

        risk = max(sl - entry_mid, entry_mid * 0.015)
        tp1 = _first_valid(day.get("support"), week.get("poc"), entry_mid - risk * 1.2)
        if tp1 >= entry_mid:
            tp1 = entry_mid - risk * 1.2
        tp2 = _first_valid(week.get("support"), month.get("support"), month.get("poc"), tp1 - risk * 1.2)
        if tp2 >= tp1:
            tp2 = tp1 - max(risk, entry_mid * 0.03)

        rr_ratio = (entry_mid - tp2) / max(sl - entry_mid, 0.01)
        add_anchor = _median([week.get("resistance"), day.get("resistance"), month.get("poc"), entry_mid]) or entry_mid
        add_low = min(add_anchor * 0.99, entry_mid)
        add_high = max(add_anchor * 1.01, entry_mid)
        tp_long = _first_valid(month.get("support"), tp2 - risk * 1.3, entry_mid * 0.88)
        if tp_long >= tp2:
            tp_long = tp2 - max(risk, entry_mid * 0.04)
        trailing_stop = min(entry_mid, _first_valid(week.get("resistance"), day.get("ema20"), entry_mid))

    rr_ratio_value = _safe_optional_float(rr_ratio)
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
                "strategy_name": "เด้งขายตามแนวต้าน Sell on Rally",
                "strategy_line": "โฟกัสรอให้ราคารีบาวด์เข้าเขตต้านแล้วค่อยประเมินแรงขายตามโครงสร้างระยะสั้น",
            },
            "position_plan": {
                "strategy_name": "ถือฝั่งป้องกัน และ ค่อยเพิ่มเมื่อรีบาวด์",
                "strategy_line": "โฟกัสฝั่งป้องกันความเสี่ยง และใช้ภาพสัปดาห์ช่วยคัดจังหวะรีบาวด์ที่อาจต่อไม่ผ่าน",
                "advice": "ใช้ภาพกราฟสัปดาห์ช่วยคุมมุมมองหลัก และอย่าปล่อยให้การรีบาวด์สั้นทำให้เสียวินัยการจัดการความเสี่ยง",
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
    return {
        "trend_radar": {
            "day": {"reason": trends["day"]["fallback_reason"]},
            "week": {"reason": trends["week"]["fallback_reason"]},
            "month": {"reason": trends["month"]["fallback_reason"]},
        },
        "day_plan": strategy_defaults["day_plan"],
        "position_plan": strategy_defaults["position_plan"],
        "ai_insight": _default_ai_insight(context, _choose_dominant_bias(trends)),
    }


def _build_member_prompt(context, trends, defaults, tier):
    def trend_snapshot(label, snapshot):
        if not snapshot.get("available"):
            return f"{label}: ข้อมูลไม่เพียงพอ"
        return (
            f"{label}: price={_format_price(snapshot.get('price'))}, "
            f"RSI={_format_price(snapshot.get('rsi'))}, "
            f"MACD={_format_price(snapshot.get('macd'))}, "
            f"Signal={_format_price(snapshot.get('signal'))}, "
            f"EMA20={_format_price(snapshot.get('ema20'))}, "
            f"EMA50={_format_price(snapshot.get('ema50'))}, "
            f"POC={_format_price(snapshot.get('poc'))}, "
            f"Support={_format_price(snapshot.get('support'))}, "
            f"Resistance={_format_price(snapshot.get('resistance'))}, "
            f"VolumeRatio={_format_price(snapshot.get('volume_ratio'))}, "
            f"ConsolidationPct={_format_price(snapshot.get('consolidation_pct'))}"
        )

    tier_label = "VIP" if tier == "vip" else "PRO"
    return f"""
คุณคือผู้ช่วยนักวิเคราะห์การเงินระดับมืออาชีพของ Apexify
งานของคุณคือเติมข้อความลง JSON เท่านั้น ห้ามเขียน markdown ห้ามเขียนคำอธิบายนอก JSON ห้ามใช้ภาษานำซื้อขายแบบเด็ดขาด

ข้อมูลหุ้น:
symbol={context.get('symbol')}
current_price={_format_price(context.get('price'))}
day_trend_bias={trends['day']['bias']}
week_trend_bias={trends['week']['bias']}
month_trend_bias={trends['month']['bias']}
extreme_volatility={str(bool(context.get('is_extreme_volatility'))).lower()}

รายละเอียดราย timeframe:
{trend_snapshot('DAY', context.get('day', {}))}
{trend_snapshot('WEEK', context.get('week', {}))}
{trend_snapshot('MONTH', context.get('month', {}))}

ค่า default หากข้อมูลไม่พอ:
day_reason_default={defaults['trend_radar']['day']['reason']}
week_reason_default={defaults['trend_radar']['week']['reason']}
month_reason_default={defaults['trend_radar']['month']['reason']}
day_strategy_default={defaults['day_plan']['strategy_name']}
day_line_default={defaults['day_plan']['strategy_line']}
position_strategy_default={defaults['position_plan']['strategy_name']}
position_line_default={defaults['position_plan']['strategy_line']}
position_advice_default={defaults['position_plan']['advice']}
ai_insight_default={defaults['ai_insight']}

ข้อกำหนด:
1. ตอบเป็นภาษาไทยเท่านั้น
2. ต้องเป็นโทนวิเคราะห์เชิงเทคนิคแบบเป็นกลางและระมัดระวัง
3. ห้ามใช้คำแบบ การันตี ซื้อเลย ต้องขายทิ้ง หรือชี้นำแบบเด็ดขาด
4. ถ้าข้อมูล timeframe ไหนไม่พอ ให้ reason ของ timeframe นั้นเป็น "ข้อมูลไม่เพียงพอ"
5. ถ้า bias รวมเป็น bearish ให้ใช้แนวคิด Sell on Rally ในคำอธิบาย
6. ถ้ามี extreme volatility ให้ ai_insight เตือนสั้นๆ ว่า indicator อาจเชื่อถือได้น้อยลง
7. สำหรับ tier={tier_label} ให้กรอกทุกฟิลด์ตาม schema ด้านล่าง แม้บางส่วนจะใช้ค่าใกล้เคียงกับ default

JSON schema ที่ต้องตอบ:
{{
  "trend_radar": {{
    "day": {{"reason": "ข้อความสั้น 1 ประโยค"}},
    "week": {{"reason": "ข้อความสั้น 1 ประโยค"}},
    "month": {{"reason": "ข้อความสั้น 1 ประโยค"}}
  }},
  "day_plan": {{
    "strategy_name": "ชื่อกลยุทธ์สั้นๆ",
    "strategy_line": "คำอธิบายสั้น 1 ประโยค"
  }},
  "position_plan": {{
    "strategy_name": "ชื่อกลยุทธ์สั้นๆ",
    "strategy_line": "คำอธิบายสั้น 1 ประโยค",
    "advice": "คำแนะนำเชิงเทคนิค 1 ประโยค"
  }},
  "ai_insight": "มุมมองพิเศษ 1 ถึง 2 ประโยค"
}}

ตอบเฉพาะ JSON object เท่านั้น
""".strip()


def _request_member_payload(prompt, defaults):
    fallback = json.loads(json.dumps(defaults, ensure_ascii=False))
    prompts = [
        prompt,
        f"{prompt}\n\nย้ำอีกครั้ง: ตอบเฉพาะ JSON object ที่ parse ได้ทันที ห้ามมีข้อความอื่นนอก JSON",
    ]

    for candidate_prompt in prompts:
        try:
            response = client.models.generate_content(model="gemini-2.5-flash", contents=candidate_prompt)
            raw_text = getattr(response, "text", "") or ""
            payload_block = _extract_json_block(raw_text)
            if not payload_block:
                continue
            parsed = json.loads(payload_block)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

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
    payload = _request_member_payload(prompt, defaults)
    analysis = _merge_member_payload(defaults, payload, context)
    return trends, deterministic_plan, analysis


def _entry_note_from_bias(plan_bias, context):
    if plan_bias == "bearish":
        resistance = _format_price(_first_valid(context.get("day", {}).get("resistance"), context.get("week", {}).get("poc")))
        return f"รอราคาเด้งกลับไปทดสอบโซนต้านแถว {resistance} หรือบริเวณ EMA สำคัญก่อนค่อยประเมินแรงขายตาม"
    support = _format_price(_first_valid(context.get("day", {}).get("support"), context.get("week", {}).get("poc")))
    return f"รอราคาย่อลงมาทดสอบโซนรับแถว {support} หรือบริเวณ EMA สำคัญก่อนค่อยประเมินแรงซื้อกลับ"


def _tp1_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "เป็นโซนแนวรับย่อย สามารถทยอยลดน้ำหนักบางส่วนเพื่อล็อกผลลัพธ์ของแผนได้"
    return "เป็นโซนต้านย่อย สามารถแบ่งเก็บบางส่วนเพื่อล็อกผลลัพธ์ของแผนได้"


def _tp2_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "เป็นโซนรับใหญ่ที่อาจมีแรงดีดกลับ จึงเหมาะใช้เป็นเป้าหลักของรอบนี้"
    return "เป็นโซนต้านใหญ่ที่หากผ่านได้จะเปิด upside เพิ่ม จึงเหมาะใช้เป็นเป้าหลักของรอบนี้"


def _stop_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "หากราคาปิดกลับขึ้นเหนือโซนนี้ โครงสร้างขายระยะสั้นจะเริ่มเสียและควรลดความเสี่ยง"
    return "หากราคาปิดหลุดโซนนี้ โครงสร้างระยะสั้นจะเริ่มเสียและควรลดความเสี่ยง"


def _position_add_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "หากเกิดรีบาวด์แรงขึ้นมาเทสต้านใหญ่ อาจใช้เป็นจังหวะเพิ่มน้ำหนักฝั่งป้องกันอย่างระมัดระวัง"
    return "หากตลาดย่อลงมาเทสฐานใหญ่ อาจใช้เป็นจังหวะทยอยสะสมเพิ่มเมื่อโครงสร้างหลักยังไม่เสีย"


def _position_trailing_note_from_bias(plan_bias):
    if plan_bias == "bearish":
        return "แนะนำขยับจุดป้องกันความเสี่ยงลงมาหลังราคาเดินตามทาง เพื่อไม่ให้รีบาวด์กลับมาล้างผลลัพธ์ที่ทำได้"
    return "แนะนำขยับจุดป้องกันความเสี่ยงขึ้นมาบริเวณทุนหรือใกล้แนวรับหลัก เพื่อไม่ให้กำไรที่ได้กลับกลายเป็นขาดทุน"


def _build_member_snapshot(context):
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

    momentum = "🟢 ขาขึ้น Bullish" if price is not None and ema20 is not None and price > ema20 else "🔴 ขาลง Bearish"
    if rsi is None:
        rsi_status = "⚪️ ข้อมูลไม่เพียงพอ"
    elif rsi > 70:
        rsi_status = "🔴 ตึงไปนิด Overbought"
    elif rsi < 30:
        rsi_status = "🟢 โซนของถูก Oversold"
    else:
        rsi_status = "⚪️ กลางๆ รอดูเชิง Neutral"

    if macd is None or signal is None:
        macd_status = "⚪️ ข้อมูลไม่เพียงพอ"
        macd_detail = "N/A"
    else:
        macd_status = "🟢 มีแรงส่ง Positive" if macd > signal else "🔴 แรงเริ่มแผ่ว Negative"
        macd_detail = f"MACD: {macd:.2f} | Signal: {signal:.2f}"

    obv_trend = str(day.get("obv_trend") or "flat").lower()
    if obv_trend == "up":
        volume_status = "📈 มีคนแอบเก็บของ Inflow"
    elif obv_trend == "down":
        volume_status = "📉 ระวังแรงรินขาย Outflow"
    else:
        volume_status = "➖ นิ่งๆ ทรงตัว"

    trend_detail = "N/A"
    if price is not None and ema20 not in (None, 0):
        trend_detail = f"{((price - ema20) / ema20) * 100:+.2f}% vs EMA20"

    volume_detail = "N/A"
    if volume is not None and avg_volume is not None:
        volume_detail = f"Vol: {_format_compact_number(volume)} | Avg20: {_format_compact_number(avg_volume)}"

    lines = [
        f"🤖 *Apexify สแกนหุ้น: {symbol}*",
        f"🏷 *ราคาล่าสุด:* {_format_price(price)}",
        "━━━━━━━━━━━━━━━",
        "*📊 สุขภาพหุ้นตอนนี้*",
        f"• 🌊 *เทรนด์หลัก:* {momentum} ({trend_detail})",
        f"• 🌡️ *RSI (ความร้อนแรง):* {rsi_status} ({_format_price(rsi)})",
        f"• ⚡️ *MACD (โมเมนตัม):* {macd_status} ({macd_detail})",
        f"• 💰 *Volume (กระแสเงิน):* {volume_status} ({volume_detail})",
        "",
        "*🎯 โซนราคาที่ต้องจับตา*",
        f"• 🟢 *แนวรับ:* {_format_price(support)}",
        f"• 🔴 *แนวต้าน (จุดวัดใจ):* {_format_price(resistance)}",
    ]

    if poc is not None:
        lines.append(f"• 🟡 *โซนคนกระจุกตัว (POC):* {_format_price(poc)} (จุดสำคัญ)")
    if bb_lower is not None and bb_upper is not None:
        lines.append(f"• 🟡 *กรอบแกว่งตัว (BB):* {_format_price(bb_lower)} - {_format_price(bb_upper)}")

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
    return "\n".join(
        [
            _build_member_snapshot(context),
            "",
            DISCLAIMER_TEXT,
            "",
            "👑 *AI Trade Setup & Analysis (Exclusive for VIP)* 👑",
            "",
            "*📊 สแกนเทรนด์ 3 ระยะ (Trend Radar):*",
            f"• ⏱️ *ระยะสั้น (Day):* {trends['day']['status_emoji']} {trends['day']['status_text']} : {analysis['trend_radar']['day']['reason']}",
            f"• 📅 *ระยะกลาง (Week):* {trends['week']['status_emoji']} {trends['week']['status_text']} : {analysis['trend_radar']['week']['reason']}",
            f"• 🔭 *ระยะยาว (Month):* {trends['month']['status_emoji']} {trends['month']['status_text']} : {analysis['trend_radar']['month']['reason']}",
            "",
            f"*🧠 AI Insight (มุมมองพิเศษ):* {analysis['ai_insight']}",
        ]
    )


def _render_pro_report(context, trends, deterministic_plan, analysis):
    plan_bias = deterministic_plan.get("bias", "bullish")
    day_plan = deterministic_plan["day_plan"]
    position_plan = deterministic_plan["position_plan"]

    return "\n".join(
        [
            _build_member_snapshot(context),
            "",
            DISCLAIMER_TEXT,
            "",
            "👑 *AI Trade Setup & Analysis (Exclusive for PRO)* 👑",
            "",
            "*📊 สแกนเทรนด์ 3 ระยะ (Trend Radar):*",
            f"• ⏱️ *ระยะสั้น (Day):* {trends['day']['status_emoji']} {trends['day']['status_text']} : {analysis['trend_radar']['day']['reason']}",
            f"• 📅 *ระยะกลาง (Week):* {trends['week']['status_emoji']} {trends['week']['status_text']} : {analysis['trend_radar']['week']['reason']}",
            f"• 🔭 *ระยะยาว (Month):* {trends['month']['status_emoji']} {trends['month']['status_text']} : {analysis['trend_radar']['month']['reason']}",
            "",
            "*🎯 แผนลงมือทำแบ่งตามสไตล์ (Actionable Plan):*",
            "",
            "🏃‍♂️ *1. สายเล่นสั้น (Day / Swing Trade)*",
            f"• 💡 *กลยุทธ์:* \"{analysis['day_plan']['strategy_name']}\" {analysis['day_plan']['strategy_line']}",
            f"• 📍 *จุดเข้า (Entry):* {_format_range(day_plan['entry_low'], day_plan['entry_high'])} ({_entry_note_from_bias(plan_bias, context)})",
            f"• 💰 *เป้าทำกำไร (TP):* แบ่งเก็บ 2 เป้า ➡️ *TP1: {_format_price(day_plan['tp1'])}* ({_tp1_note_from_bias(plan_bias)}) | *TP2: {_format_price(day_plan['tp2'])}* ({_tp2_note_from_bias(plan_bias)})",
            f"• 🛑 *ตัดขาดทุน (SL):* {_format_price(day_plan['sl'])} ({_stop_note_from_bias(plan_bias)})",
            f"• ⚖️ *ความคุ้มค่า (R:R Ratio):* 1 : {day_plan['rr_ratio']} ({day_plan['rr_note']})",
            "",
            "🧘‍♂️ *2. สายถือยาว (Position / Run Trend)*",
            f"• 💡 *กลยุทธ์:* \"{analysis['position_plan']['strategy_name']}\" {analysis['position_plan']['strategy_line']}",
            f"• 📍 *จุดสะสมเพิ่ม (Add):* {_format_range(position_plan['add_low'], position_plan['add_high'])} ({_position_add_note_from_bias(plan_bias)})",
            f"• 💰 *เป้าระยะยาว (TP):* {_format_price(position_plan['tp_long'])}+ ({_tp2_note_from_bias(plan_bias)})",
            f"• 🛑 *จุดล็อคกำไร (Trailing Stop):* {_format_price(position_plan['trailing_stop'])} ({_position_trailing_note_from_bias(plan_bias)})",
            f"• ⚖️ *คำแนะนำ:* {analysis['position_plan']['advice']}",
            "",
            f"*🧠 AI Insight (มุมมองพิเศษ):* {analysis['ai_insight']}",
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

    report += f"\n\n{DISCLAIMER_TEXT}"
    return report


def generate_apexify_report(tech_data, role="free"):
    normalized_role = str(role or "free").lower()
    if normalized_role not in ("vip", "pro"):
        return _generate_free_report(tech_data)

    symbol = tech_data.get("symbol") or tech_data.get("ticker") or "UNKNOWN"
    try:
        context = build_multitimeframe_trade_context(symbol)
    except Exception:
        context = _fallback_context_from_tech_data(tech_data)

    try:
        trends, deterministic_plan, analysis = _build_member_analysis(context, normalized_role)
        if normalized_role == "vip":
            return _render_vip_report(context, trends, analysis)
        return _render_pro_report(context, trends, deterministic_plan, analysis)
    except Exception:
        fallback_context = context or _fallback_context_from_tech_data(tech_data)
        trends = _build_trend_summary(fallback_context)
        deterministic_plan = _build_deterministic_plan(fallback_context, _choose_dominant_bias(trends))
        analysis = _build_member_defaults(fallback_context, trends, deterministic_plan)
        if normalized_role == "vip":
            return _render_vip_report(fallback_context, trends, analysis)
        return _render_pro_report(fallback_context, trends, deterministic_plan, analysis)


def analyze_payment_slip(file_path_or_bytes):
    prompt = """
    ตรวจสอบรูปนี้ว่าเป็นสลิปโอนเงินผ่านแอปธนาคารของไทยหรือไม่
    ตอบกลับในรูปแบบ JSON เท่านั้น ห้ามมีข้อความอื่น:
    {
        "is_slip": true หรือ false,
        "amount": ตัวเลขยอดเงินโอนแบบไม่มีลูกน้ำ (เช่น 499),
        "ref_no": "เลขที่อ้างอิงบนสลิป"
    }
    """
    try:
        if isinstance(file_path_or_bytes, bytes):
            image = PIL.Image.open(io.BytesIO(file_path_or_bytes))
        else:
            image = PIL.Image.open(file_path_or_bytes)

        response = client.models.generate_content(model="gemini-2.5-flash", contents=[image, prompt])
        return response.text
    except Exception:
        return '{"is_slip": false, "amount": 0, "ref_no": ""}'
