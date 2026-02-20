from google import genai
from config import GEMINI_API_KEY
import PIL.Image
import io

client = genai.Client(api_key=GEMINI_API_KEY)

def generate_apexify_report(tech_data):
    # กำหนดสถานะอินดิเคเตอร์
    rsi_status = "Overbought 🔴" if tech_data['rsi'] > 70 else "Oversold 🟢" if tech_data['rsi'] < 30 else "กลาง ⚪️"
    macd_status = "สัญญาณบวก 🟢" if tech_data['macd'] > tech_data['macd_signal'] else "สัญญาณลบ 🔴"
    ema_short = "ขาขึ้น 🟢" if tech_data['ema20'] > tech_data['ema50'] else "ขาลง 🔴"
    ema_long = "โกลเด้นครอส 🟢" if tech_data['ema50'] > tech_data['ema200'] else "เดธครอส 🔴" if tech_data['ema50'] < tech_data['ema200'] else "ไซด์เวย์ ⚪️"
    
    # ให้ AI สรุปความเห็น (เพิ่ม Fear & Greed เข้าไปใน Prompt)
    prompt = f"""
    วิเคราะห์หุ้น {tech_data['symbol']} ในฐานะนักวิเคราะห์การเงินมืออาชีพ ข้อมูลทางเทคนิคมีดังนี้:
    ราคา: {tech_data['price']:.2f}, RSI: {tech_data['rsi']:.2f}, แนวโน้ม MACD: {macd_status}, 
    EMA ระยะสั้น: {ema_short}, EMA ระยะยาว: {ema_long}, 
    กรอบ Bollinger: {tech_data['bb_lower']:.2f} - {tech_data['bb_upper']:.2f}, แนวรับ: {tech_data['support']:.2f}, แนวต้าน: {tech_data['resistance']:.2f}
    สภาวะตลาดรวม (Fear & Greed Index): {tech_data['fear_greed']}
    
    ช่วยเขียน 'สรุปภาพรวม' สั้นๆ 3-4 บรรทัด อธิบายพฤติกรรมราคาและประเมินว่าสภาวะตลาดปัจจุบันเอื้อต่อการเข้าซื้อหรือควรระวัง โดยใช้ภาษาที่อ่านง่าย ดูเป็นมืออาชีพ
    """
    
    try:
        ai_response = client.models.generate_content(model='gemini-3-flash', contents=prompt)
        ai_text = ai_response.text
    except Exception as e:
        print(f"❌ เจอตัวการแล้ว AI Error: {e}") # พิมพ์ Error ลงในหน้าจอ Terminal
        ai_text = f"AI ไม่สามารถสรุปข้อมูลได้ (สาเหตุ: {str(e)})" # ส่ง Error เข้าไปโชว์ใน Telegram เลยชั่วคราว

    # จัดฟอร์แมตข้อความสไตล์โปรเจกต์
    report = f"📊 **{tech_data['symbol']}**\n"
    report += f"🧭 **Market Sentiment:** {tech_data['fear_greed']}\n" # <--- แสดงผลตรงนี้
    report += f"โมเมนตัมราคา: {ema_short}\n"
    report += f"RSI: {rsi_status} | MACD: {macd_status}\n"
    report += f"โบลลิงเจอร์ (20): {tech_data['bb_lower']:.2f} - {tech_data['bb_upper']:.2f} 🟡\n"
    report += f"EMA 20/50 ระยะกลาง: {ema_short}\n"
    report += f"EMA 50/200 ระยะยาว: {ema_long}\n"
    report += f"OBV ล่าสุด: {tech_data['obv_trend']}\n"
    report += f"แนวรับ: {tech_data['support']:.2f} แนวต้าน: {tech_data['resistance']:.2f}\n\n"
    report += f"📝 **สรุปภาพรวม {tech_data['symbol']}:**\n{ai_text}"

    return report
# ... (ฟังก์ชัน generate_apexify_report เดิมคงไว้) ...

def analyze_payment_slip(image_bytes):
    """ฟังก์ชันส่งรูปสลิปให้ AI ตรวจสอบ"""
    try:
        # แปลงข้อมูล bytes เป็นรูปภาพที่ Gemini อ่านได้
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
            model='Gemini-3 Flash',
            contents=[prompt, image]
        )
        
        # คลีนข้อมูล JSON (เผื่อ AI ตอบติด Backtick มา)
        text = response.text.strip().replace('```json', '').replace('```', '')
        return text # ส่ง String JSON กลับไปให้ main.py แปลงต่อ
        
    except Exception as e:
        # ปริ้น Error ยาวๆ เก็บไว้ดูใน Log ของ Render พอ ไม่ต้องส่งเข้า Telegram
        print(f"❌ AI Error: {e}") 
        
        # ส่งข้อความสั้นๆ กลับไปหาลูกค้า เพื่อป้องกัน Caption ยาวเกิน 1024 ตัวอักษร
        ai_text = "AI ชั่วคราวไม่สามารถสรุปข้อมูลได้ (อาจติดข้อจำกัดการใช้งาน API ฟรี) โปรดลองใหม่อีกครั้งในอีกสักครู่ครับ 🤖"