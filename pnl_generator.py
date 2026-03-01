import io
import os
from PIL import Image, ImageDraw, ImageFont

# 🌟 อัปเดตชื่อฟอนต์เป็น YesevaOne-Regular.ttf ตรงนี้ครับ
def generate_pnl_card(username, ticker, entry_price, current_price, pnl_font_path='YesevaOne-Regular.ttf'):
    """สร้างภาพการ์ด PnL แบบ Trading Card ระดับ Pro"""
    
    # 📏 1. ตั้งค่าขนาดและการออกแบบ
    width, height = 1080, 720 
    card_color_top = (10, 25, 47) 
    card_color_bottom = (0, 0, 0) 
    text_color_main = (255, 255, 255) 
    color_profit = (0, 230, 118) 
    color_loss = (255, 23, 68) 
    
    # 🖼️ 2. สร้างภาพพื้นหลังแบบ Gradient
    img = Image.new('RGB', (width, height), card_color_bottom)
    draw = ImageDraw.Draw(img)
    
    for y in range(height):
        r = int(card_color_top[0] + (card_color_bottom[0] - card_color_top[0]) * y / height)
        g = int(card_color_top[1] + (card_color_bottom[1] - card_color_top[1]) * y / height)
        b = int(card_color_top[2] + (card_color_bottom[2] - card_color_top[2]) * y / height)
        draw.line((0, y, width, y), fill=(r, g, b))

    # 🔤 3. โหลด Fonts
    try:
        if not os.path.exists(pnl_font_path):
            print(f"⚠️ Warning: ไม่พบไฟล์ Font '{pnl_font_path}' บนเซิร์ฟเวอร์ จะใช้ฟอนต์พื้นฐานแทน")
            font_main = font_app_title = font_username = font_ticker = font_label = font_price = font_pnl = ImageFont.load_default()
        else:
            # 💡 ถ้าใช้ Yeseva One อาจจะปรับขนาดตัวหนังสือให้ใหญ่ขึ้นนิดนึงได้ เพราะฟอนต์สไตล์นี้ตัวจะแอบเล็ก
            font_main = ImageFont.truetype(pnl_font_path, 40)
            font_app_title = ImageFont.truetype(pnl_font_path, 35)
            font_username = ImageFont.truetype(pnl_font_path, 50)
            font_ticker = ImageFont.truetype(pnl_font_path, 180) 
            font_label = ImageFont.truetype(pnl_font_path, 35)
            font_price = ImageFont.truetype(pnl_font_path, 60)
            font_pnl = ImageFont.truetype(pnl_font_path, 220) 
    except Exception as e:
        print(f"❌ Font Error: {e}")
        font_main = font_app_title = font_username = font_ticker = font_label = font_price = font_pnl = ImageFont.load_default()

    # 📊 4. คำนวณข้อมูลกำไร/ขาดทุน
    pnl_amount = current_price - entry_price
    pnl_percent = (pnl_amount / entry_price) * 100 if entry_price > 0 else 0
    
    is_profit = pnl_percent >= 0
    status_color = color_profit if is_profit else color_loss
    
    # ✍️ 5. เริ่มวาดข้อความ
    draw.text((40, 40), "APEXIFY TRADING AI", fill=(150, 150, 150), font=font_app_title)
    draw.text((width - 40, 40), f"USER: {username.upper()}", fill=text_color_main, font=font_username, anchor="ra")
    
    draw.text((width // 2, 220), str(ticker), fill=text_color_main, font=font_ticker, anchor="mm")
    
    pnl_text = f"{pnl_percent:+.2f}%"
    draw.text((width // 2, 450), pnl_text, fill=status_color, font=font_pnl, anchor="mm")
    
    # Bottom: ราคาเข้าและราคาปัจจุบัน
    box_y = 600
    draw.text((width * 0.25, box_y), "ENTRY PRICE", fill=(180, 180, 180), font=font_label, anchor="mm")
    draw.text((width * 0.25, box_y + 60), f"${entry_price:,.2f}", fill=text_color_main, font=font_price, anchor="mm")
    
    draw.text((width * 0.75, box_y), "CURRENT PRICE", fill=(180, 180, 180), font=font_label, anchor="mm")
    draw.text((width * 0.75, box_y + 60), f"${current_price:,.2f}", fill=status_color, font=font_price, anchor="mm")

    # ⬇️ 6. แปลงรูปภาพเป็น Bytes
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr