import asyncio
import edge_tts
import os
import yfinance as yf
import telebot
from google import genai
from config import TELEGRAM_TOKEN, GEMINI_API_KEY
from database import get_connection, check_subscription

# ⚙️ ตั้งค่า API 
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 📊 1. ฟังก์ชันดึงภาพรวมตลาด
# ==========================================
def get_market_data():
    print("🌍 กำลังดึงข้อมูลตลาดโลก...")
    try:
        sp500 = yf.Ticker('^GSPC').history(period='1d')['Close'].iloc[-1]
        btc = yf.Ticker('BTC-USD').history(period='1d')['Close'].iloc[-1]
        gold = yf.Ticker('GC=F').history(period='1d')['Close'].iloc[-1]
        return f"ดัชนี เอสแอนด์พี 500 ปิดที่ {sp500:,.0f} จุด, บิตคอยน์อยู่ที่ {btc:,.0f} ดอลลาร์, และราคาทองคำโลกอยู่ที่ {gold:,.0f} ดอลลาร์"
    except Exception as e:
        print(f"ดึงข้อมูลตลาดล้มเหลว: {e}")
        return "ตลาดหุ้นอเมริกาและคริปโตมีการทรงตัว"

# ==========================================
# 🤖 2. ฟังก์ชันให้ AI เขียนสคริปต์วิทยุ
# ==========================================
def generate_script(market_info):
    print("✍️ กำลังให้ AI เขียนสคริปต์รายการวิทยุ...")
    prompt = f"""
    คุณคือนักจัดรายการวิทยุการลงทุนที่ชื่อ 'Apex AI'
    กำลังจัดรายการ 'Apexify Morning Briefing' สรุปตลาดเช้านี้
    
    ข้อมูลตลาดวันนี้: {market_info}
    
    ข้อกำหนด:
    1. ความยาวประมาณ 1-2 นาที (อ่านออกเสียงแบบสบายๆ)
    2. ใช้ภาษาพูดที่เป็นธรรมชาติ มีน้ำเสียงตื่นเต้น น่าฟัง เป็นมืออาชีพแต่เข้าถึงง่าย
    3. ห้ามใช้สัญลักษณ์พิเศษ ห้ามมีเครื่องหมายดอกจัน (*) ห้ามมี Bullet Point เด็ดขาด
    4. ให้อ่านตัวเลขกลมๆ เพื่อให้ฟังง่าย
    5. มีการกล่าวทักทายยามเช้า และทิ้งท้ายรายการด้วยคำคมการลงทุน
    """
    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
    return response.text.replace('*', '').replace('#', '')

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
    pro_users = cur.fetchall()
    cur.close()
    conn.close()

    count = 0
    # วนลูปส่งไฟล์เสียง
    for row in pro_users:
        user_id = row[0]
        # เช็คให้ชัวร์ว่ายังไม่หมดอายุ
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