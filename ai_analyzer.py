import json
import PIL.Image
import io
from google import genai
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_apexify_report(tech_data, role='free'):
    # --- 1. ดึงข้อมูลตัวเลขจากกราฟ (เพิ่มการดักจับ Key ป้องกันค่า 0) ---
    symbol = tech_data.get('symbol', 'UNKNOWN')
    price = tech_data.get('price', 0)
    rsi = tech_data.get('rsi', 50)
    macd_line = tech_data.get('macd_line', 0)
    signal_line = tech_data.get('signal_line', 0)
    ema20 = tech_data.get('ema20', 0)
    ema50 = tech_data.get('ema50', 0)
    ema200 = tech_data.get('ema200', 0)
    
    # 🌟 ดักจับ Key ของ Bollinger Bands เผื่อระบบใช้ชื่ออื่น จะได้ไม่เป็น 0.00
    lower_band = tech_data.get('lower_band', tech_data.get('bb_lower', 0))
    upper_band = tech_data.get('upper_band', tech_data.get('bb_upper', 0))
    
    support = tech_data.get('support', 0)
    resistance = tech_data.get('resistance', 0)
    obv_trend = tech_data.get('obv_trend', 'คงที่')
    
    # --- 2. แปลงค่าเป็นคำศัพท์ที่อ่านง่าย สบายตา และดูโปร ---
    momentum = "🟢 ขาขึ้น (Bullish)" if price > ema20 else "🔴 ขาลง (Bearish)"
    
    if rsi > 70: rsi_status = "🔴 ตึงตัว (Overbought)"
    elif rsi < 30: rsi_status = "🟢 น่าสะสม (Oversold)"
    else: rsi_status = "⚪️ กลางๆ (Neutral)"
    
    macd_status = "🟢 ตัดขึ้น (Positive)" if macd_line > signal_line else "🔴 ตัดลง (Negative)"
    
    ema_mid = "🟢 ขาขึ้น" if ema20 > ema50 else "🔴 ขาลง"
    
    if ema50 > ema200 and (ema50/ema200 < 1.03): ema_long = "✨ Golden Cross (จุดกลับตัว)"
    elif ema50 < ema200 and (ema200/ema50 < 1.03): ema_long = "💀 Death Cross (ระวังเทขาย)"
    elif ema50 > ema200: ema_long = "🟢 ขาขึ้นระยะยาว"
    else: ema_long = "🔴 ขาลงระยะยาว"
    
    if "เพิ่ม" in obv_trend or "up" in obv_trend.lower(): obv_status = "📈 มีแรงซื้อสะสม (Inflow)"
    elif "ลด" in obv_trend or "down" in obv_trend.lower(): obv_status = "📉 มีแรงเทขาย (Outflow)"
    else: obv_status = "➖ ทรงตัว (Static)"
    
    # --- 3. ประกอบร่าง UI รูปแบบใหม่ (Executive Summary Style) ---
    report = f"🎯 **สรุปสภาวะหุ้น: {symbol}**\n"
    report += f"💵 **ราคาปัจจุบัน:** `{price:,.2f}`\n\n"
    
    report += "📊 **[ 1. ตัวชี้วัดโมเมนตัม ]**\n"
    report += f"• 🧭 **แนวโน้มหลัก:** {momentum}\n"
    report += f"• 🔥 **RSI (ความร้อนแรง):** {rsi_status} `({rsi:.2f})`\n"
    report += f"• 🌊 **MACD (ทิศทาง):** {macd_status}\n"
    report += f"• 💰 **OBV (กระแสเงิน):** {obv_status}\n"
    
    # 🌟 แสดง Bollinger Bands แบบปลอดภัย ถ้าหาค่าไม่เจอจริงๆ จะไม่โชว์ 0 ให้ลูกค้างง
    if lower_band != 0 and upper_band != 0:
        report += f"• 🟡 **กรอบราคา (Bollinger):** `{lower_band:,.2f} - {upper_band:,.2f}`\n"
        
    report += "\n📈 **[ 2. สัญญาณเส้นค่าเฉลี่ย (EMA) ]**\n"
    report += f"• **ระยะกลาง (20/50):** {ema_mid}\n"
    report += f"• **ระยะยาว (50/200):** {ema_long}\n\n"
    
    report += "🎯 **[ 3. โซนเฝ้าระวัง (Key Levels) ]**\n"
    report += f"• 🟢 **แนวรับสำคัญ:** `{support:,.2f}`\n"
    report += f"• 🔴 **แนวต้านสำคัญ:** `{resistance:,.2f}`\n"

    # --- 4. ส่วนของ Apexify Analysis เฉพาะลูกค้า VIP / PRO ---
    if role in ['vip', 'pro']:
        report += "\n🧠 **[ 4. มุมมองการลงทุนจาก Apexify ]**\n"
        
        # PRO ได้สิทธิวิเคราะห์ลึกกว่าระดับ VIP
        if role == 'pro':
            prompt = f"""
            คุณคือนักวิเคราะห์เทคนิคระดับ Senior วิเคราะห์หุ้น {symbol} ที่ราคา {price} 
            ข้อมูล: RSI={rsi:.2f}, MACD={macd_status}, เทรนด์ระยะกลาง={ema_mid}, ระยะยาว={ema_long}
            แนวรับ {support} แนวต้าน {resistance}
            วิเคราะห์แนวโน้มเชิงลึก อธิบายเหตุผลประกอบความยาวประมาณ 4-5 บรรทัด (ตอบเป็นภาษาไทย)
            และบรรทัดสุดท้ายให้ฟันธงกลยุทธ์โดยใช้รูปแบบนี้เท่านั้น: **🎯 คำแนะนำ: [ซื้อ (BUY) / ถือ (HOLD) / ขาย (SELL)]** (เลือกอย่างใดอย่างหนึ่งให้ชัดเจน)
            """
        else:
            prompt = f"""
            วิเคราะห์หุ้น {symbol} ราคา {price} RSI={rsi:.2f} เทรนด์คือ {ema_mid}
            อธิบายเหตุผลสั้นๆ ว่าน่าสนใจไหม ความยาวประมาณ 3 บรรทัด (ตอบเป็นภาษาไทย)
            และบรรทัดสุดท้ายให้ฟันธงโดยใช้รูปแบบนี้เท่านั้น: **🎯 คำแนะนำ: [ซื้อ / ถือ / ขาย]** (เลือกอย่างใดอย่างหนึ่งให้ชัดเจน)
            """
            
        try:
            ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report += f"💡 *{ai_response.text.strip()}*"
        except Exception as e:
            report += "💡 *ระบบ Apexify กำลังประมวลผลหนัก กรุณาลองใหม่อีกครั้งครับ*"
            
    # 🌟 เพิ่มคำเตือนการลงทุนไว้ท้ายสุด
    report += "\n\n⚠️ **คำเตือน:** การลงทุนมีความเสี่ยง ข้อมูลนี้เป็นเพียงการวิเคราะห์ทางสถิติและ AI เพื่อประกอบการตัดสินใจ ไม่ใช่การชี้ชวนให้ซื้อหรือขายแต่อย่างใด ผู้ลงทุนควรพิจารณาความเสี่ยงด้วยตนเอง"
            
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
