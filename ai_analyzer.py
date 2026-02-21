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
    lower_band = tech_data.get('lower_band', 0)
    upper_band = tech_data.get('upper_band', 0)
    support = tech_data.get('support', 0)
    resistance = tech_data.get('resistance', 0)
    obv_trend = tech_data.get('obv_trend', 'คงที่')
    
    # --- 2. แปลงค่าเป็นคำศัพท์สไตล์ Quant Matrix ---
    momentum = "🟢 BULLISH (ขาขึ้น)" if price > ema20 else "🔴 BEARISH (ขาลง)"
    
    if rsi > 70: rsi_status = "🔴 OVERBOUGHT"
    elif rsi < 30: rsi_status = "🟢 OVERSOLD"
    else: rsi_status = "⚪️ NEUTRAL"
    
    macd_status = "🟢 BULLISH" if macd_line > signal_line else "🔴 BEARISH"
    
    ema_mid = "🟢 UPTREND" if ema20 > ema50 else "🔴 DOWNTREND"
    
    if ema50 > ema200 and (ema50/ema200 < 1.03): ema_long = "✨ GOLDEN CROSS"
    elif ema50 < ema200 and (ema200/ema50 < 1.03): ema_long = "💀 DEATH CROSS"
    elif ema50 > ema200: ema_long = "🟢 UPTREND"
    else: ema_long = "🔴 DOWNTREND"
    
    if "เพิ่ม" in obv_trend or "up" in obv_trend.lower(): obv_icon = "📈 INFLOW (เงินเข้า)"
    elif "ลด" in obv_trend or "down" in obv_trend.lower(): obv_icon = "📉 OUTFLOW (เงินออก)"
    else: obv_icon = "➖ STATIC (ทรงตัว)"
    
    # --- 3. ประกอบร่าง UI รูปแบบใหม่ (Apexify Signature Style) ---
    report = f"📌 **{symbol}** | Price: `{price:,.2f}`\n\n"
    
    report += "== [ 🤖 **APEX QUANT ENGINE** ] ==\n"
    report += f"|> 🚀 **Momentum** : `[ {momentum} ]`\n\n"
    
    report += "-- 📊 **CORE MATRIX** --\n"
    report += f"» **RSI** (ความร้อนแรง): `[ {rsi_status} ]` ({rsi:.2f})\n"
    report += f"» **MACD** (ทิศทาง)    : `[ {macd_status} ]`\n"
    report += f"» **OBV** (กระแสเงิน)   : `[ {obv_icon} ]`\n"
    report += f"» **Band** (กรอบราคา) : `[ 🟡 {lower_band:,.2f} ⟷ {upper_band:,.2f} ]`\n\n"
    
    report += "-- 📈 **TREND RADAR** --\n"
    report += f"» **M-Trend** (EMA 20/50) : `[ {ema_mid} ]`\n"
    report += f"» **L-Trend** (EMA 50/200): `[ {ema_long} ]`\n\n"
    
    report += "-- 🎯 **BATTLE ZONES** --\n"
    report += f"🛡️ **ฐานรับ (Support)** : `{support:,.2f}`\n"
    report += f"⚔️ **ต้านทาน (Resist)** : `{resistance:,.2f}`\n"

    # --- 4. ส่วนของ AI Analysis เฉพาะลูกค้า VIP / PRO ---
    if role in ['vip', 'pro']:
        report += "\n🧠 **Apexify AI Analysis:**\n"
        
        # PRO ได้สิทธิวิเคราะห์ลึกกว่าระดับ VIP
        if role == 'pro':
            prompt = f"""
            คุณคือนักวิเคราะห์เทคนิคระดับ Senior วิเคราะห์หุ้น {symbol} ที่ราคา {price} 
            ข้อมูล: RSI={rsi:.2f}, MACD={macd_status}, เทรนด์ระยะกลาง={ema_mid}, ระยะยาว={ema_long}
            แนวรับ {support} แนวต้าน {resistance}
            ฟันธงกลยุทธ์ (Buy/Hold/Sell) พร้อมเหตุผลแบบเฉียบขาดและแม่นยำ ไม่เกิน 3 บรรทัด (ตอบเป็นภาษาไทย)
            """
        else:
            prompt = f"""
            วิเคราะห์หุ้น {symbol} ราคา {price} RSI={rsi:.2f} เทรนด์คือ {ema_mid}
            ให้คำแนะนำสั้นๆ ว่าน่าสนใจไหม (Buy/Hold/Sell) ไม่เกิน 2 บรรทัด (ตอบเป็นภาษาไทย)
            """
            
        try:
            ai_response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report += f"*{ai_response.text.strip()}*"
        except Exception as e:
            report += "*ระบบสมองกล AI กำลังประมวลผลหนัก กรุณาลองใหม่อีกครั้งครับ*"
            
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
