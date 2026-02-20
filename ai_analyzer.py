from google import genai
from config import GEMINI_API_KEY
import PIL.Image
import io

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_apexify_report(tech_data, is_vip=False):
    rsi_status = "Overbought 🔴" if tech_data['rsi'] > 70 else "Oversold 🟢" if tech_data['rsi'] < 30 else "กลาง ⚪️"
    macd_status = "สัญญาณบวก 🟢" if tech_data['macd'] > tech_data['macd_signal'] else "สัญญาณลบ 🔴"
    ema_short = "ขาขึ้น 🟢" if tech_data['ema20'] > tech_data['ema50'] else "ขาลง 🔴"
    ema_long = "โกลเด้นครอส 🟢" if tech_data['ema50'] > tech_data['ema200'] else "เดธครอส 🔴" if tech_data['ema50'] < tech_data['ema200'] else "ไซด์เวย์ ⚪️"
    
    if is_vip:
        prompt = f"""
        วิเคราะห์หุ้น {tech_data['symbol']} ในฐานะนักวิเคราะห์การเงินมืออาชีพ ข้อมูลทางเทคนิคมีดังนี้:
        ราคา: {tech_data['price']:.2f}, RSI: {tech_data['rsi']:.2f}, แนวโน้ม MACD: {macd_status}, 
        EMA ระยะสั้น: {ema_short}, EMA ระยะยาว: {ema_long}, 
        กรอบ Bollinger: {tech_data['bb_lower']:.2f} - {tech_data['bb_upper']:.2f}, แนวรับ: {tech_data['support']:.2f}, แนวต้าน: {tech_data['resistance']:.2f}
        สภาวะตลาดรวม (Fear & Greed Index): {tech_data['fear_greed']}
        
        สิทธิพิเศษสำหรับลูกค้าระดับ VIP: ช่วยเขียน 'สรุปภาพรวม' เชิงลึก 3-4 บรรทัด อธิบายพฤติกรรมราคา และตอนท้ายสุดให้ **ฟันธงคำแนะนำ (Actionable Advice)** ชัดเจนว่าควร "ซื้อ (BUY)", "ถือ (HOLD)", หรือ "ขาย (SELL)" พร้อมเหตุผลสั้นๆ โดนๆ อย่างมืออาชีพ
        """
    else:
        prompt = f"""
        วิเคราะห์หุ้น {tech_data['symbol']} ในฐานะนักวิเคราะห์การเงินมืออาชีพ ข้อมูลทางเทคนิคมีดังนี้:
        ราคา: {tech_data['price']:.2f}, RSI: {tech_data['rsi']:.2f}, แนวโน้ม MACD: {macd_status}, 
        EMA ระยะสั้น: {ema_short}, EMA ระยะยาว: {ema_long}, 
        กรอบ Bollinger: {tech_data['bb_lower']:.2f} - {tech_data['bb_upper']:.2f}, แนวรับ: {tech_data['support']:.2f}, แนวต้าน: {tech_data['resistance']:.2f}
        สภาวะตลาดรวม (Fear & Greed Index): {tech_data['fear_greed']}
        
        ช่วยเขียน 'สรุปภาพรวม' สั้นๆ 3-4 บรรทัด อธิบายพฤติกรรมราคาและประเมินว่าสภาวะตลาดปัจจุบันเอื้อต่อการเข้าซื้อหรือควรระวัง โดยใช้ภาษาที่อ่านง่าย ดูเป็นมืออาชีพ ห้ามให้คำแนะนำซื้อขายเด็ดขาด
        """
    
    try:
        ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_text = ai_response.text
    except Exception as e:
        print(f"❌ AI Error: {e}") 
        ai_text = f"AI ชั่วคราวไม่สามารถสรุปข้อมูลได้ โปรดลองใหม่อีกครั้งในอีกสักครู่ครับ 🤖"

    report = f"📊 **{tech_data['symbol']}**\n"
    report += f"🧭 **Market Sentiment:** {tech_data['fear_greed']}\n" 
    report += f"โมเมนตัมราคา: {ema_short}\n"
    report += f"RSI: {rsi_status} | MACD: {macd_status}\n"
    report += f"โบลลิงเจอร์ (20): {tech_data['bb_lower']:.2f} - {tech_data['bb_upper']:.2f} 🟡\n"
    report += f"EMA 20/50 ระยะกลาง: {ema_short}\n"
    report += f"EMA 50/200 ระยะยาว: {ema_long}\n"
    report += f"OBV ล่าสุด: {tech_data['obv_trend']}\n"
    report += f"แนวรับ: {tech_data['support']:.2f} แนวต้าน: {tech_data['resistance']:.2f}\n\n"
    report += f"📝 **สรุปภาพรวม {tech_data['symbol']}:**\n{ai_text}\n\n"
    report += "⚠️ *คำเตือน: การลงทุนมีความเสี่ยง ข้อมูลนี้เป็นเพียงการวิเคราะห์ทางสถิติเพื่อประกอบการตัดสินใจ ไม่ใช่คำแนะนำหรือการการันตีผลกำไร*"

    return report

def analyze_payment_slip(image_bytes):
    try:
        image = PIL.Image.open(io.BytesIO(image_bytes))
        prompt = """
        คุณคือระบบตรวจสอบสลิปธนาคารอัตโนมัติ จงตรวจสอบรูปภาพนี้:
        1. นี่คือรูปสลิปโอนเงินธนาคาร (Bank Transfer Slip) ที่ถูกต้องใช่หรือไม่?
        2. ยอดเงินในสลิปคือเท่าไหร่? (มองหาตัวเลขจำนวนเงิน)
        3. วันที่โอนคือเมื่อไหร่?
        
        ตอบกลับมาในรูปแบบ JSON เท่านั้น ดังนี้:
        {"is_slip": true/false, "amount": 199.00, "date": "DD/MM/YYYY"}
        ถ้าไม่ใช่สลิป ให้ตอบ {"is_slip": false}
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, image]
        )
        text = response.text.strip().replace('```json', '').replace('```', '')
        return text 
    except Exception as e:
        print(f"❌ AI Error: {e}") 
        return '{"is_slip": false}'