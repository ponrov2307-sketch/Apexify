from google import genai
from config import GEMINI_API_KEY

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
        ai_response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        ai_text = ai_response.text
    except Exception as e:
        print(f"❌ Gemini API Error: {e}") # <--- เพิ่มบรรทัดนี้เข้าไปครับ
        ai_text = "AI ไม่สามารถสรุปข้อมูลได้ในขณะนี้"
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