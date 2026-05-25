import asyncio
import edge_tts
import math
import os
import re
from datetime import datetime
import yfinance as yf
import telebot
from config import TELEGRAM_TOKEN, GEMINI_API_KEY, gemini_client, ADMIN_ID
from database import get_connection, check_subscription

# ⚙️ ตั้งค่า API
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = gemini_client

# ==========================================
# 📊 1. ฟังก์ชันดึงภาพรวมตลาด
# ==========================================
def _fetch_price(ticker_sym):
    """ดึงราคาล่าสุดของ ticker — คืน None ถ้าล้มเหลวหรือได้ NaN"""
    try:
        val = yf.Ticker(ticker_sym).history(period='2d')['Close'].iloc[-1]
        return None if math.isnan(val) else val
    except Exception:
        return None

def get_market_data():
    print("🌍 กำลังดึงข้อมูลตลาดโลก...")
    sp500 = _fetch_price('^GSPC')
    btc   = _fetch_price('BTC-USD')
    gold  = _fetch_price('GC=F')

    date_str = datetime.now().strftime('%d %b %Y')
    parts = [f"ข้อมูล ณ วันที่ {date_str}:"]
    if sp500: parts.append(f"S&P 500 ปิดที่ {sp500:,.0f} จุด")
    if btc:   parts.append(f"Bitcoin อยู่ที่ {btc:,.0f} ดอลลาร์")
    if gold:  parts.append(f"ทองคำโลกอยู่ที่ {gold:,.0f} ดอลลาร์")

    if len(parts) == 1:  # ดึงไม่ได้เลย
        print("⚠️ ดึงข้อมูลตลาดไม่สำเร็จ ตลาดอาจยังไม่เปิด")
        return "ข้อมูลตลาดยังไม่พร้อม ตลาดอาจยังไม่เปิดหรือเน็ตมีปัญหา"
    return ' '.join(parts)

# ==========================================
# 🤖 2. ฟังก์ชันให้ AI เขียนสคริปต์วิทยุ
# ==========================================
def _clean_script(text: str) -> str:
    """ลบ meta-text ที่ AI ใส่มาโดยไม่ควรถูกอ่านออกเสียง เช่น label, วงเล็บ, หัวข้อ"""
    # ลบ * # ออก
    text = text.replace('*', '').replace('#', '')
    # ลบเนื้อหาในวงเล็บทุกชนิด เช่น (เปิดรายการ) [ส่วนที่ 1]
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    # ลบบรรทัดที่ลงท้ายด้วย : (มักเป็น label เช่น "ส่วนที่ 1:" "เนื้อหา:")
    lines = text.splitlines()
    lines = [l for l in lines if not re.match(r'^\s*[^\n]{1,30}:\s*$', l)]
    return '\n'.join(lines).strip()

def generate_script(market_info):
    print("✍️ กำลังให้ AI เขียนบทพูดรายการวิทยุ...")
    prompt = f"""
    คุณคือนักจัดรายการวิทยุการลงทุนชื่อ 'Apex AI' กำลังออกอากาศรายการ 'Apexify Morning Briefing'

    ข้อมูลตลาดวันนี้: {market_info}

    ตอบกลับมาเฉพาะบทพูดที่จะอ่านออกอากาศได้ทันที ความยาวประมาณ 2.5 ถึง 4 นาที
    ห้ามมีคำอธิบาย ห้ามมี label ห้ามมีวงเล็บ ห้ามมีหัวข้อ ห้ามบอกว่ากำลังจะทำอะไร เริ่มพูดได้เลย

    เนื้อหาที่ต้องครอบคลุมแบบเนียนๆ:
    1. ทักทายยามเช้าแบบเป็นกันเอง
    2. เล่าภาพรวมตลาดให้ละเอียดกว่าการบอกตัวเลขเฉยๆ
    3. อธิบายความหมายของตัวเลขต่ออารมณ์ตลาด เงินทุน และสินทรัพย์เสี่ยง
    4. เชื่อมโยงว่าบรรยากาศแบบนี้มีผลกับการลงทุนวันนี้อย่างไร
    5. ปิดด้วยมุมคิดหรือกำลังใจสำหรับนักลงทุน

    ข้อกำหนด:
    - ใช้ภาษาพูดธรรมชาติ น่าฟัง มีพลัง ไม่เวอร์
    - อธิบายตลาดเหมือนเล่าให้คนฟังตอนขับรถตอนเช้า
    - ห้ามใช้ Bullet Point ดอกจัน แฮชแท็ก หัวข้อย่อย วงเล็บ หรือ label ทุกชนิด
    - อ่านตัวเลขแบบกลมๆ ฟังง่าย
    - อย่างน้อย 3 ย่อหน้า และ 10 ประโยค
    """
    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
    try:
        from database import log_gemini_usage
        log_gemini_usage('podcast_short', 'gemini-2.5-flash', response=response)
    except Exception:
        pass
    return _clean_script(response.text)

# ==========================================
# 🎧 3. ฟังก์ชันแปลงข้อความเป็นเสียง (TTS)
# ==========================================
async def create_audio(text: str, filename: str):
    print("🎙️ กำลังบันทึกเสียงเป็นไฟล์ MP3...")
    # 🌟 เลือกเสียงได้: th-TH-NiwatNeural (ชาย) หรือ th-TH-PremwadeeNeural (หญิง)
    voice = "th-TH-NiwatNeural" 
    
    # ปรับความเร็ว +5% ให้ฟีลลิ่งกระฉับกระเฉงสไตล์รายการตอนเช้า
    communicate = edge_tts.Communicate(text, voice, rate="+5%")
    await communicate.save(filename)

# ==========================================
# 🚀 4. รันระบบส่งหาลูกค้า PRO ทั้งหมด
# ==========================================
async def main():
    print("🚀 เริ่มสร้าง Apexify Podcast...")
    market_info = get_market_data()
    
    script = generate_script(market_info)
    print(f"\n📜 สคริปต์ที่ AI เขียน:\n{script}\n")
    
    filename = "apexify_morning.mp3"
    await create_audio(script, filename)
    print("🎧 อัดเสียงสำเร็จ! กำลังเตรียมบรอดแคสต์หาลูกค้า PRO...")

    # ดึงรายชื่อ User จากฐานข้อมูล
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE role = 'pro'")
    user_ids = [str(row[0]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    # 🌟 รวม ADMIN_ID ถ้าไม่มี (admin ได้ทุก feature ของ PRO)
    if ADMIN_ID and str(ADMIN_ID) not in user_ids:
        user_ids.insert(0, str(ADMIN_ID))

    count = 0
    # วนลูปส่งไฟล์เสียง
    for user_id in user_ids:
        # เช็คให้ชัวร์ว่ายังไม่หมดอายุ (admin returns 'pro' เสมอ)
        if check_subscription(user_id) == 'pro':
            try:
                # ต้องเปิดไฟล์อ่านใหม่ทุกครั้งที่ส่ง
                with open(filename, 'rb') as audio:
                    bot.send_voice(
                        chat_id=user_id,
                        voice=audio,
                        caption="🎧 **Apexify Morning Briefing** 🎙️\nอัปเดตตลาดเช้านี้แบบ Podcast ฟังระหว่างขับรถได้เลยครับ! 🚀",
                        parse_mode="Markdown"
                    )
                count += 1
                await asyncio.sleep(0.5) # กันโดนแบนจากการส่งรัว
            except Exception as e:
                print(f"❌ ส่งให้ {user_id} ไม่สำเร็จ: {e}")

    print(f"✅ บรอดแคสต์ Podcast สำเร็จทั้งหมด {count} คน!")
    
    # ลบไฟล์ขยะทิ้ง
    if os.path.exists(filename):
        os.remove(filename)

if __name__ == "__main__":
    asyncio.run(main())
