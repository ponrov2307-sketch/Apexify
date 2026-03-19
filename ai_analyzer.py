import io
import math
import PIL.Image
from google import genai
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

DISCLAIMER_TEXT = (
    "⚠️ *คำเตือน: รายงานนี้เป็นการวิเคราะห์อัตโนมัติเพื่อประกอบการตัดสินใจเท่านั้น "
    "ไม่ใช่คำแนะนำการลงทุน ผู้ใช้งานควรตรวจสอบข้อมูลเพิ่มเติมและประเมินความเสี่ยง"
    "ด้วยตนเองก่อนตัดสินใจทุกครั้ง*"
)


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


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


def generate_apexify_report(tech_data, role='free'):
    # --- 1. ดึงข้อมูลตัวเลขจากกราฟ ---
    symbol = tech_data.get('symbol', 'UNKNOWN')
    price = _safe_float(tech_data.get('price', 0))
    rsi = _safe_float(tech_data.get('rsi', 50))
    macd_line = _safe_float(tech_data.get('macd', tech_data.get('macd_line', 0)))
    signal_line = _safe_float(tech_data.get('macd_signal', tech_data.get('signal_line', 0)))
    ema20 = _safe_float(tech_data.get('ema20', 0))
    ema50 = _safe_float(tech_data.get('ema50', 0))
    ema200 = _safe_float(tech_data.get('ema200', 0))
    volume = _safe_float(tech_data.get('volume', 0))
    avg_volume = _safe_float(tech_data.get('avg_volume', 0))

    lower_band = _safe_float(tech_data.get('lower_band', tech_data.get('bb_lower', 0)))
    upper_band = _safe_float(tech_data.get('upper_band', tech_data.get('bb_upper', 0)))

    support = _safe_float(tech_data.get('support', 0))
    resistance = _safe_float(tech_data.get('resistance', 0))
    obv_trend = str(tech_data.get('obv_trend', 'คงที่'))

    poc_price = _safe_float(tech_data.get('poc_price', 0))  # 🌟 [เพิ่มใหม่] ดึงราคาโซนคนติดดอย

    # --- 2. แปลงค่าเป็นคำศัพท์ที่ดูเป็นกันเองขึ้น แต่ยังคงความโปร ---
    momentum = "🟢 ขาขึ้น (Bullish)" if price > ema20 else "🔴 ขาลง (Bearish)"

    if rsi > 70:
        rsi_status = "🔴 ตึงไปนิด (Overbought)"
    elif rsi < 30:
        rsi_status = "🟢 โซนของถูก (Oversold)"
    else:
        rsi_status = "⚪️ กลางๆ รอดูเชิง (Neutral)"

    macd_status = "🟢 มีแรงส่ง (Positive)" if macd_line > signal_line else "🔴 แรงเริ่มแผ่ว (Negative)"
    ema_mid = "ขาขึ้น" if ema20 > ema50 else "ขาลง"

    if ema50 > ema200 and ema200 > 0 and (ema50 / ema200 < 1.03):
        ema_long = "Golden Cross เริ่มก่อตัว"
    elif ema50 < ema200 and ema50 > 0 and (ema200 / ema50 < 1.03):
        ema_long = "Death Cross เริ่มก่อตัว"
    elif ema50 > ema200:
        ema_long = "แนวโน้มระยะยาวเป็นบวก"
    else:
        ema_long = "แนวโน้มระยะยาวเป็นลบ"

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

    # --- 3. UI รูปแบบใหม่: เป็นกันเอง อ่านง่าย ---
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

    if poc_price > 0:  # 🌟 [เพิ่มใหม่] แสดงโซนคนติดดอย
        report += f"• 🟡 **โซนคนกระจุกตัว (POC):** `{poc_price:,.2f}` *(จุดสำคัญ)*\n"

    if lower_band != 0 and upper_band != 0:
        report += f"• 🟡 **กรอบแกว่งตัว (BB):** `{lower_band:,.2f} - {upper_band:,.2f}`\n"

    # --- 4. ส่วนของ AI Trading Playbook ---
    if role in ['vip', 'pro']:
        report += f"\n{DISCLAIMER_TEXT}\n"
        report += "\n🧠 **[ แผนการเทรดจาก 💎 APEXIFY ]**\n"
        if role == 'pro':
            # 🌟 [เพิ่มใหม่] ส่งค่า POC ให้ AI นำไปประกอบการวิเคราะห์จุดซื้อ/ขาย
            prompt = f"""
            คุณคือ AI ผู้ช่วยวิเคราะห์หุ้นของ Apexify
            วิเคราะห์หุ้น {symbol} ที่ราคา {price:.2f}
            ข้อมูลสำคัญ: RSI={rsi:.2f}, MACD={macd_line:.2f}, Signal={signal_line:.2f},
            เทรนด์ระยะสั้น={ema_mid} ({trend_percent:+.2f}% vs EMA20), เทรนด์ระยะยาว={ema_long},
            แนวรับ={support:.2f}, แนวต้าน={resistance:.2f}, POC={poc_price:.2f},
            กระแสเงิน={obv_status}, Volume ล่าสุด={_format_compact_number(volume)}, Avg20={_format_compact_number(avg_volume)}

            เขียนคำแนะนำภาษาไทยแบบกระชับ เป็นกลาง สุภาพ และอ่านง่าย
            แยกเป็น 2 มุมมอง:
            1. 🏃‍♂️ สายเล่นสั้น: อธิบายว่าควรรอจังหวะ, ถือรอดู, หรือรอสัญญาณยืนยันตรงไหน
            2. 🧘‍♂️ สายถือยาว: อธิบายภาพรวมเชิงแนวโน้มโดยไม่ใช้ภาษาตื่นตระหนก

            ข้อกำหนด:
            - ถ้าสัญญาณยังไม่ไปทางเดียวกันชัดเจน ให้สรุปเป็น "รอดู"
            - หลีกเลี่ยงคำว่า "หนี", "รับมีด", "ขายเลย", "ทุ่ม", หรือถ้อยคำชี้นำแรงเกินจริง
            - ใช้เหตุผลเชิงสังเกต เช่น "สัญญาณยังไม่ชัด", "รอการยืนยัน", "รอดูจังหวะ"
            - ความยาวรวมไม่เกิน 5 บรรทัด
            - บรรทัดสุดท้ายให้ใช้รูปแบบนี้เท่านั้น: **🎯 สรุปให้เลย: [ซื้อ / ถือ / รอดู / ขาย] เพราะ [เหตุผลสั้นๆ 1 ประโยค]**
            """
        else:
            prompt = f"""
            คุณคือ AI ผู้ช่วยวิเคราะห์หุ้นของ Apexify
            วิเคราะห์หุ้น {symbol} ราคา {price:.2f}
            ข้อมูลสำคัญ: RSI={rsi:.2f}, MACD={macd_line:.2f}, Signal={signal_line:.2f},
            เทรนด์ระยะสั้น={ema_mid} ({trend_percent:+.2f}% vs EMA20), แนวรับ={support:.2f}, แนวต้าน={resistance:.2f}

            เขียนภาษาไทยแบบสั้น กระชับ เป็นกลาง และไม่ชี้นำแรงเกินไป ความยาวรวม 3 บรรทัด
            ถ้าสัญญาณไม่ชัดหรือมีทั้งบวกและลบ ให้สรุปเป็น "รอดู"
            หลีกเลี่ยงคำว่า "หนี", "รับมีด", "ขายเลย", หรือถ้อยคำตื่นตระหนก
            บรรทัดสุดท้ายให้ใช้รูปแบบนี้เท่านั้น: **🎯 สรุปให้เลย: [ซื้อ / ถือ / รอดู / ขาย] เพราะ [เหตุผลสั้นๆ 1 ประโยค]**
            """

        try:
            ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report += f"💡 *{ai_response.text.strip()}*"
        except Exception as e:
            report += "💡 *ระบบกำลังคิดหนักเลยครับ ขอเวลาแป๊บ ลองกดใหม่นะ!*"

    else:
        report += f"\n\n{DISCLAIMER_TEXT}"

    return report

def analyze_payment_slip(file_path_or_bytes):
    prompt = '''
    ตรวจสอบรูปนี้ว่าเป็นสลิปโอนเงินผ่านแอปธนาคารของไทยหรือไม่ 
    ตอบกลับในรูปแบบ JSON เท่านั้น ห้ามมีข้อความอื่น:
    {
        "is_slip": true หรือ false,
        "amount": ตัวเลขยอดเงินโอนแบบไม่มีลูกน้ำ (เช่น 499),
        "ref_no": "เลขที่อ้างอิงบนสลิป"
    }
    '''
    try:
        if isinstance(file_path_or_bytes, bytes):
            image = PIL.Image.open(io.BytesIO(file_path_or_bytes))
        else:
            image = PIL.Image.open(file_path_or_bytes)
            
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[image, prompt])
        return response.text
    except Exception as e:
        return '{"is_slip": false, "amount": 0, "ref_no": ""}'
