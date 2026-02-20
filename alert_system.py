import time
import telebot
from config import TELEGRAM_TOKEN, ADMIN_ID
from technical_tools import calculate_technical_indicators

# ตั้งค่าบอทสำหรับส่งข้อความ (ใช้ Token เดียวกันได้)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# รายชื่อหุ้น/เหรียญ ที่ต้องการเฝ้าระวัง
WATCHLIST = ["BTC-USD", "ETH-USD", "NVDA", "TSLA", "PTT.BK", "KBANK.BK"]

# ตัวแปรเก็บสถานะล่าสุดเพื่อป้องกันการแจ้งเตือนซ้ำ (Anti-Spam)
last_alert_state = {} 

def send_alert(symbol, message):
    """ฟังก์ชันส่งข้อความแจ้งเตือนเข้า Telegram แอดมิน"""
    try:
        full_msg = f"🚨 **APEXIFY ALERT: {symbol}** 🚨\n\n{message}"
        bot.send_message(ADMIN_ID, full_msg, parse_mode="Markdown")
        print(f"✅ Sent alert for {symbol}")
    except Exception as e:
        print(f"❌ Failed to send alert: {e}")

def check_market_conditions():
    print(f"🔍 [{time.strftime('%H:%M:%S')}] Scanning market...")
    
    for symbol in WATCHLIST:
        try:
            # ดึงข้อมูลทางเทคนิค (ใช้ฟังก์ชันเดิมที่มีอยู่แล้ว)
            tech_data, _, error = calculate_technical_indicators(symbol)
            
            if error or not tech_data:
                continue

            current_rsi = tech_data['rsi']
            ema50 = tech_data['ema50']
            ema200 = tech_data['ema200']
            price = tech_data['price']
            
            # --- สร้าง Key สำหรับเช็คสถานะ ---
            # ถ้าหุ้นตัวนี้ยังไม่มีในระบบ ให้สร้าง dict ว่างๆ ไว้
            if symbol not in last_alert_state:
                last_alert_state[symbol] = {'rsi': 'normal', 'cross': 'normal'}

            # 1. เช็ค RSI (Oversold / Overbought)
            rsi_condition = 'normal'
            if current_rsi < 30:
                rsi_condition = 'oversold'
                msg = f"🟢 **RSI OVERSOLD ({current_rsi:.2f})**\nราคาร่วงหนัก เข้าเขตขายมากเกินไป อาจมีเด้งรีบาวด์! (ราคา: {price:.2f})"
            elif current_rsi > 75:
                rsi_condition = 'overbought'
                msg = f"🔴 **RSI OVERBOUGHT ({current_rsi:.2f})**\nราคาพุ่งแรง เข้าเขตซื้อมากเกินไป ระวังแรงเทขาย! (ราคา: {price:.2f})"

            # แจ้งเตือนเมื่อสถานะเปลี่ยน (ไม่แจ้งซ้ำถ้ายังค้างสถานะเดิม)
            if rsi_condition != 'normal' and rsi_condition != last_alert_state[symbol]['rsi']:
                send_alert(symbol, msg)
                last_alert_state[symbol]['rsi'] = rsi_condition
            elif rsi_condition == 'normal':
                last_alert_state[symbol]['rsi'] = 'normal' # รีเซ็ตเมื่อกลับมาปกติ

            # 2. เช็ค EMA Cross (Golden Cross / Death Cross)
            cross_condition = 'normal'
            # เช็คว่าเส้น 50 ตัดขึ้นเหนือ 200 (Golden Cross)
            if ema50 > ema200 and (ema50 / ema200) < 1.01: # เช็คว่าเพิ่งตัดกันหมาดๆ (ระยะห่าง < 1%)
                cross_condition = 'golden_cross'
                msg = f"✨ **GOLDEN CROSS DETECTED** ✨\nเส้น EMA50 ตัดขึ้นเหนือ EMA200 สัญญาณกลับตัวเป็นขาขึ้นระยะยาว!"
            # เช็คว่าเส้น 50 ตัดลงต่ำกว่า 200 (Death Cross)
            elif ema50 < ema200 and (ema200 / ema50) < 1.01:
                cross_condition = 'death_cross'
                msg = f"💀 **DEATH CROSS DETECTED** 💀\nเส้น EMA50 ตัดลงต่ำกว่า EMA200 สัญญาณกลับตัวเป็นขาลงระยะยาว!"

            if cross_condition != 'normal' and cross_condition != last_alert_state[symbol]['cross']:
                send_alert(symbol, msg)
                last_alert_state[symbol]['cross'] = cross_condition
            
            time.sleep(1) # พัก 1 วินาทีต่อหุ้น 1 ตัว (กันยิง Request รัวเกิน)

        except Exception as e:
            print(f"⚠️ Error checking {symbol}: {e}")

if __name__ == "__main__":
    print("🚀 Apexify Alert System is Running...")
    send_alert("SYSTEM", "ระบบแจ้งเตือนเริ่มทำงานแล้วครับลูกพี่! 😎")
    
    while True:
        check_market_conditions()
        time.sleep(300) # ตรวจสอบทุกๆ 5 นาที (300 วินาที)