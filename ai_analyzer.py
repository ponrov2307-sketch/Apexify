import json
import PIL.Image
import io
from google import genai
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_apexify_report(tech_data, role='free'):
    # --- 1. ดึงข้อมูลตัวเลขจากกราฟ ---
    symbol = tech_data.get('symbol', 'UNKNOWN')
    price = tech_data.get('price', 0)
    rsi = tech_data.get('rsi', 50)
    macd_line = tech_data.get('macd_line', 0)
    signal_line = tech_data.get('signal_line', 0)
    ema20 = tech_data.get('ema20', 0)
    ema50 = tech_data.get('ema50', 0)
    ema200 = tech_data.get('ema200', 0)
    
    lower_band = tech_data.get('lower_band', tech_data.get('bb_lower', 0))
    upper_band = tech_data.get('upper_band', tech_data.get('bb_upper', 0))
    
    support = tech_data.get('support', 0)
    resistance = tech_data.get('resistance', 0)
    obv_trend = tech_data.get('obv_trend', 'คงที่')
    
    # --- คำนวณแนวรับใหม่ 3 ระดับ ---
    first_support = ema20 if (ema20 > 0 and ema20 < price) else (price * 0.985)
    
    if price >= 100:
        psycho_support = (int(price) // 10) * 10
    elif price >= 10:
        psycho_support = (int(price) // 5) * 5
    elif price >= 1:
        psycho_support = int(price)
    else:
        psycho_support = price * 0.9  # สำหรับเหรียญหรือหุ้นราคาต่ำ
        
    major_support = support # จุดต่ำสุดในรอบ 20 วัน
    
    # --- 2. แปลงค่าเป็นคำศัพท์สไตล์ Hedge Fund ---
    momentum = "🟢 ขาขึ้น (Bullish)" if price > ema20 else "🔴 ขาลง (Bearish)"
    
    if rsi > 70: rsi_status = "🔴 Overbought (ระวังโดนเท)"
    elif rsi < 30: rsi_status = "🟢 Oversold (โซนน่าเก็บ)"
    else: rsi_status = "⚪️ Neutral (รอดูท่าที)"
    
    macd_status = "🟢 Positive (มีแรงส่ง)" if macd_line > signal_line else "🔴 Negative (แรงส่งแผ่ว)"
    ema_mid = "🟢 ขาขึ้น" if ema20 > ema50 else "🔴 ขาลง"
    
    if ema50 > ema200 and (ema50/ema200 < 1.03): ema_long = "✨ Golden Cross (เตรียมบิน)"
    elif ema50 < ema200 and (ema200/ema50 < 1.03): ema_long = "💀 Death Cross (ระวังหลุม)"
    elif ema50 > ema200: ema_long = "🟢 ขาขึ้นระยะยาว"
    else: ema_long = "🔴 ขาลงระยะยาว"
    
    if "เพิ่ม" in obv_trend or "up" in obv_trend.lower(): obv_status = "📈 Smart Money ไหลเข้า"
    elif "ลด" in obv_trend or "down" in obv_trend.lower(): obv_status = "📉 มีแรงรินขายออก"
    else: obv_status = "➖ ทรงตัว"
    
    # --- 3. UI รูปแบบใหม่: APEXIFY TERMINAL ---
    report = f"💎 **APEXIFY TERMINAL: {symbol}**\n"
    report += f"🏷 **Price:** `{price:,.2f}`\n"
    report += "━" * 15 + "\n"
    
    report += "📊 **[ X-Ray โมเมนตัม ]**\n"
    report += f"• 🌊 **Trend:** {momentum}\n"
    report += f"• 🌡️ **RSI:** {rsi_status} `({rsi:.2f})`\n"
    report += f"• ⚡ **MACD:** {macd_status}\n"
    report += f"• 💰 **Volume:** {obv_status}\n"
    
    report += "\n🎯 **[ Action Zones ]**\n"
    report += f"• 🟢 **แนวรับแรก:** `{first_support:,.2f}`\n"
    report += f"• 🧠 **แนวรับจิตวิทยา:** `{psycho_support:,.2f}`\n"
    report += f"• 🛡️ **แนวรับสำคัญ:** `{major_support:,.2f}`\n"
    report += f"• 🔴 **แนวต้าน (Resistance):** `{resistance:,.2f}`\n"
    
    if lower_band != 0 and upper_band != 0:
        report += f"• 🟡 **กรอบแกว่งตัว (BB):** `{lower_band:,.2f} - {upper_band:,.2f}`\n"

    # --- 4. ส่วนของ AI Trading Playbook ---
    if role in ['vip', 'pro']:
        report += "\n🧠 **[ AI Trading Playbook ]**\n"
        if role == 'pro':
            prompt = f"""
            คุณคือนักวิเคราะห์เทคนิคระดับ Hedge Fund วิเคราะห์หุ้น {symbol} ที่ราคา {price} 
            ข้อมูล: RSI={rsi:.2f}, MACD={macd_status}, เทรนด์={ema_mid}, ระยะยาว={ema_long}
            แนวรับ {support} แนวต้าน {resistance}
            วิเคราะห์พฤติกรรมราคาเชิงลึก เขียนกลยุทธ์การเทรด (Trading Playbook) ความยาว 4-5 บรรทัด (ภาษาไทย)
            บรรทัดสุดท้ายให้ฟันธงกลยุทธ์รูปแบบนี้เท่านั้น: **🎯 Action: [BUY / HOLD / SELL] เพราะ [ระบุเหตุผลสั้นๆ 1 ประโยค]**
            """
        else:
            prompt = f"""
            วิเคราะห์หุ้น {symbol} ราคา {price} RSI={rsi:.2f} เทรนด์คือ {ema_mid}
            อธิบายเหตุผลสั้นๆ ว่าน่าสนใจไหม ความยาว 3 บรรทัด (ภาษาไทย)
            บรรทัดสุดท้ายฟันธง: **🎯 Action: [BUY / HOLD / SELL] เพราะ [ระบุเหตุผลสั้นๆ 1 ประโยค]**
            """
            
        try:
            ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report += f"💡 *{ai_response.text.strip()}*"
        except Exception as e:
            report += "💡 *ระบบกำลังประมวลผลหนาแน่น กรุณาลองใหม่อีกครั้ง*"
            
    report += "\n\n⚠️ *คำเตือน: ข้อมูลเพื่อประกอบการตัดสินใจ ไม่ใช่การชี้ชวนลงทุน*"
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
