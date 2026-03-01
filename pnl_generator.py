import io
import os
from PIL import Image, ImageDraw, ImageFont

def generate_pnl_card(username, ticker, entry_price, current_price, pnl_font_path='RobotoBold.ttf'):
    """สร้างภาพการ์ด PnL แบบ Trading Card ระดับ Pro"""
    
    # 📏 ตั้งค่าขนาดและการออกแบบ
    width, height = 1080, 720 # ขนาดแบบ Instagram Post
    card_color_top = (10, 25, 47) # สีน้ำเงินเข้มที่สุด (Deep Navy)
    card_color_bottom = (0, 0, 0) # สีดำ
    text_color_main = (255, 255, 255) # สีขาว
    color_profit = (0, 230, 118) # สีเขียวนีออน (Profit)
    color_loss = (255, 23, 68) # สีแดงสว่าง (Loss)
    
    # 🖼️ 1. สร้างภาพพื้นหลังแบบ Gradient
    img = Image.new('RGB', (width, height), card_color_bottom)
    draw = ImageDraw.Draw(img)
    
    # วาด Gradient ง่ายๆ (ไล่สีจากบนลงล่าง)
    for y in range(height // 2):
        r = int(card_color_top[0] + (card_color_bottom[0] - card_color_top[0]) * y / (height // 2))
        g = int(card_color_top[1] + (card_color_bottom[1] - card_color_top[1]) * y / (height // 2))
        b = int(card_color_top[2] + (card_color_bottom[2] - card_color_top[2]) * y / (height // 2))
        draw.line((0, y, width, y), fill=(r, g, b))

    # 🔤 2. โหลด Fonts (พร้อมระบบป้องกัน)
    default_font_size = 40
    try:
        if not os.path.exists(pnl_font_path):
            print(f"⚠️ Warning: ไม่พบไฟล์ Font {pnl_font_path} จะใช้ Font พื้นฐานแทน (ภาพอาจไม่สวย)")
            font_main = ImageFont.load_default()
            font_ticker = ImageFont.load_default()
            font_pnl = ImageFont.load_default()
        else:
            font_main = ImageFont.truetype(pnl_font_path, 40)
            font_app_title = ImageFont.truetype(pnl_font_path, 30)
            font_username = ImageFont.truetype(pnl_font_path, 45)
            font_ticker = ImageFont.truetype(pnl_font_path, 180) # หุ้นตัวใหญ่ๆ
            font_label = ImageFont.truetype(pnl_font_path, 35)
            font_price = ImageFont.truetype(pnl_font_path, 60)
            font_pnl = ImageFont.truetype(pnl_font_path, 220) # เปอร์เซ็นต์ใหญ่สุดๆ
    except Exception as e:
        print(f"❌ Font Error: {e}")
        font_main = font_ticker = font_pnl = ImageFont.load_default()

    # 📊 3. คำนวณข้อมูล
    pnl_amount = current_price - entry_price
    pnl_percent = (pnl_amount / entry_price) * 100
    
    is_profit = pnl_percent >= 0
    status_color = color_profit if is_profit else color_loss
    status_arrow = "⬆️" if is_profit else "⬇️"
    
    # ✍️ 4. เริ่มวาดองค์ประกอบต่างๆ
    
    # Header: ชื่อแอปและ User
    draw.text((40, 40), "APEXIFY TRADING AI", fill=(150, 150, 150), font=font_app_title)
    draw.text((width - 40, 40), f"USER: {username.upper()}", fill=text_color_main, font=font_username, anchor="ra")
    
    # Center 1: ชื่อหุ้น (Ticker)
    draw.text((width // 2, 220), ticker, fill=text_color_main, font=font_ticker, anchor="mm")
    
    # Center 2: เปอร์เซ็นต์ PnL (ใหญ่ที่สุด)
    pnl_text = f"{pnl_percent:+.2f}%"
    draw.text((width // 2, 450), pnl_text, fill=status_color, font=font_pnl, anchor="mm")
    
    # สัญลักษณ์ลูกศร
    draw.text((width // 2 + draw.textlength(pnl_text, font=font_pnl) // 2 + 50, 450), status_arrow, fill=status_color, font=font_main, anchor="mm")

    # Bottom: ราคาเข้าและราคาปัจจุบัน
    box_y = 600
    # ฝั่งซ้าย: ราคาเข้า (ENTRY)
    draw.text((width * 0.25, box_y), "ENTRY PRICE", fill=(180, 180, 180), font=font_label, anchor="mm")
    draw.text((width * 0.25, box_y + 60), f"${entry_price:,.2f}", fill=text_color_main, font=font_price, anchor="mm")
    
    # ฝั่งขวา: ราคาปัจจุบัน (CURRENT)
    draw.text((width * 0.75, box_y), "CURRENT PRICE", fill=(180, 180, 180), font=font_label, anchor="mm")
    draw.text((width * 0.75, box_y + 60), f"${current_price:,.2f}", fill=status_color, font=font_price, anchor="mm")

    # ⬇️ 5. แปลงรูปภาพเป็น Bytes เพื่อส่งผ่าน Telegram
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr