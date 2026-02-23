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
        psycho_support = price * 0.9  
        
    major_support = support 
    
    # --- 2. แปลงค่าเป็นคำศัพท์ที่ดูเป็นกันเองขึ้น แต่ยังคงความโปร ---
    momentum = "🟢 ขาขึ้น (Bullish)" if price > ema20 else "🔴 ขาลง (Bearish)"
    
    if rsi > 70: rsi_status = "🔴 ตึงไปนิด (Overbought)"
    elif rsi < 30: rsi_status = "🟢 โซนของถูก (Oversold)"
    else: rsi_status = "⚪️ กลางๆ รอดูเชิง (Neutral)"
    
    macd_status = "🟢 มีแรงส่ง (Positive)" if macd_line > signal_line else "🔴 แรงเริ่มแผ่ว (Negative)"
    ema_mid = "🟢 ขาขึ้น" if ema20 > ema50 else "🔴 ขาลง"
    
    if ema50 > ema200 and (ema50/ema200 < 1.03): ema_long = "✨ Golden Cross (เตรียมบิน!)"
    elif ema50 < ema200 and (ema200/ema50 < 1.03): ema_long = "💀 Death Cross (ระวังหลุม!)"
    elif ema50 > ema200: ema_long = "🟢 เทรนด์ขาขึ้นยาวๆ"
    else: ema_long = "🔴 เทรนด์ขาลงยาวๆ"
    
    if "เพิ่ม" in obv_trend or "up" in obv_trend.lower(): obv_status = "📈 มีคนแอบเก็บของ (Inflow)"
    elif "ลด" in obv_trend or "down" in obv_trend.lower(): obv_status = "📉 ระวังแรงรินขาย (Outflow)"
    else: obv_status = "➖ นิ่งๆ ทรงตัว"
    
    # --- 3. UI รูปแบบใหม่: เป็นกันเอง อ่านง่าย ---
    report = f"🤖 **Apexify สแกนหุ้น: {symbol}**\n"
    report += f"🏷 **ราคาล่าสุด:** `{price:,.2f}`\n"
    report += "━" * 15 + "\n"
    
    report += "📊 **[ สุขภาพหุ้นตอนนี้ ]**\n"
    report += f"• 🌊 **เทรนด์หลัก:** {momentum}\n"
    report += f"• 🌡️ **RSI (ความร้อนแรง):** {rsi_status} `({rsi:.2f})`\n"
    report += f"• ⚡ **MACD (โมเมนตัม):** {macd_status}\n"
    report += f"• 💰 **Volume (กระแสเงิน):** {obv_status}\n"
    
    report += "\n🎯 **[ โซนราคาที่ต้องจับตา ]**\n"
    report += f"• 🟢 **แนวรับแรก (ถ้าย่อลงมา):** `{first_support:,.2f}`\n"
    report += f"• 🧠 **แนวรับจิตวิทยา (ตัวเลขกลมๆ):** `{psycho_support:,.2f}`\n"
    report += f"• 🛡️ **แนวรับสำคัญ (หลุดตรงนี้หนี):** `{major_support:,.2f}`\n"
    report += f"• 🔴 **แนวต้าน (จุดวัดใจ):** `{resistance:,.2f}`\n"
    
    if lower_band != 0 and upper_band != 0:
        report += f"• 🟡 **กรอบแกว่งตัว (BB):** `{lower_band:,.2f} - {upper_band:,.2f}`\n"

    # --- 4. ส่วนของ AI Trading Playbook ---
    if role in ['vip', 'pro']:
        report += "\n🧠 **[ แผนการเทรดจาก AI ]**\n"
        if role == 'pro':
            # สั่งให้ AI แบ่งคำแนะนำเป็น 2 ระยะ และใช้คำพูดเป็นกันเอง
            prompt = f"""
            คุณคือ AI ผู้ช่วยเทรดเดอร์ที่เป็นมิตรและเก่งกาจ วิเคราะห์หุ้น {symbol} ที่ราคา {price} 
            ข้อมูล: RSI={rsi:.2f}, MACD={macd_status}, เทรนด์={ema_mid}, ระยะยาว={ema_long}
            แนวรับ {support} แนวต้าน {resistance}
            ให้คำแนะนำด้วยภาษาที่เป็นกันเองเหมือนคุยกับเพื่อนเทรดเดอร์ แยกคำแนะนำเป็น 2 ระยะ:
            1. 🏃‍♂️ สายเล่นสั้น (Short-term): ควรทำยังไง
            2. 🧘‍♂️ สายถือยาว (Long-term): ทรงนี้ควรถือต่อหรือหนี
            (ความยาวรวมไม่เกิน 5 บรรทัด)
            บรรทัดสุดท้ายให้สรุปแบบฟันธงในรูปแบบนี้เท่านั้น: **🎯 สรุปให้เลย: [ซื้อ / ถือ / ขาย] เพราะ [เหตุผลสั้นๆ โดนใจ 1 ประโยค]**
            """
        else:
            prompt = f"""
            คุณคือ AI ผู้ช่วยเทรดเดอร์ที่เป็นมิตร วิเคราะห์หุ้น {symbol} ราคา {price} RSI={rsi:.2f} เทรนด์คือ {ema_mid}
            อธิบายสั้นๆ ด้วยภาษาเป็นกันเอง ว่าทรงนี้น่าเล่นไหม ความยาว 3 บรรทัด
            บรรทัดสุดท้ายให้สรุปแบบฟันธง: **🎯 สรุปให้เลย: [ซื้อ / ถือ / ขาย] เพราะ [เหตุผลสั้นๆ 1 ประโยค]**
            """
            
        try:
            ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report += f"💡 *{ai_response.text.strip()}*"
        except Exception as e:
            report += "💡 *ระบบกำลังคิดหนักเลยครับ ขอเวลาแป๊บ ลองกดใหม่นะ!*"
            
    report += "\n\n⚠️ *ย้ำกันนิด: การลงทุนมีความเสี่ยง ข้อมูลนี้ AI ช่วยสแกนให้เพื่อประกอบการตัดสินใจนะคร้าบ*"
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
