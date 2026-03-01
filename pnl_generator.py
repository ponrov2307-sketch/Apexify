import io
import os
import random
from PIL import Image, ImageDraw, ImageFont

def generate_pnl_card(username, ticker, entry_price, current_price, pnl_font_path='YesevaOne-Regular.ttf'):
    """สร้างภาพ Apexify Alpha Card (PnL) แบบพรีเมียมพร้อมกราฟ Abstract"""
    
    # 📏 1. ตั้งค่าขนาดและการออกแบบ
    width, height = 1200, 750 
    bg_color_top = (8, 18, 32)        
    bg_color_bottom = (0, 0, 0)       
    panel_bg = (15, 25, 40, 200)       
    border_color = (40, 50, 70, 255)  
    text_main = (240, 245, 255)       
    text_sub = (150, 160, 175)        
    
    color_profit = (0, 255, 128)      
    color_loss = (255, 30, 80)        
    
    # 🖼️ 2. สร้างภาพพื้นหลังแบบ Gradient
    img = Image.new('RGB', (width, height), bg_color_bottom)
    draw = ImageDraw.Draw(img)
    
    for y in range(height):
        r = int(bg_color_top[0] + (bg_color_bottom[0] - bg_color_top[0]) * y / height)
        g = int(bg_color_top[1] + (bg_color_bottom[1] - bg_color_top[1]) * y / height)
        b = int(bg_color_top[2] + (bg_color_bottom[2] - bg_color_top[2]) * y / height)
        draw.line((0, y, width, y), fill=(r, g, b))

    # 🔤 3. โหลด Fonts (ใช้ YesevaOne-Regular)
    try:
        if not os.path.exists(pnl_font_path):
            print(f"⚠️ Warning: ไม่พบไฟล์ Font '{pnl_font_path}' บนเซิร์ฟเวอร์ จะใช้ฟอนต์พื้นฐานแทน")
            font_title = font_user = font_ticker = font_pnl = font_label = font_value = ImageFont.load_default()
        else:
            font_title = ImageFont.truetype(pnl_font_path, 35)
            font_user = ImageFont.truetype(pnl_font_path, 40)
            font_ticker = ImageFont.truetype(pnl_font_path, 180) 
            font_pnl = ImageFont.truetype(pnl_font_path, 200)    
            font_label = ImageFont.truetype(pnl_font_path, 30)
            font_value = ImageFont.truetype(pnl_font_path, 60)
    except Exception as e:
        print(f"❌ Font Error: {e}")
        font_title = font_user = font_ticker = font_pnl = font_label = font_value = ImageFont.load_default()

    # 📊 4. คำนวณข้อมูลกำไร/ขาดทุน
    pnl_cash = current_price - entry_price
    pnl_percent = (pnl_cash / entry_price) * 100 if entry_price > 0 else 0
    
    is_profit = pnl_percent >= 0
    status_color = color_profit if is_profit else color_loss
    arrow_char = "▲" if is_profit else "▼"
    
    # ✍️ 5. เริ่มวาดองค์ประกอบหลัก (Layout)
    
    # -- Header Section --
    draw.rectangle([40, 40, 70, 70], fill=status_color)
    draw.text((85, 42), "APEXIFY TRADING AI", fill=text_main, font=font_title)
    draw.text((width - 40, 42), f"USER: {username.upper()}", fill=text_sub, font=font_user, anchor="ra")
    
    # -- Main Body Section (Ticker & PnL) --
    draw.text((width // 2, 210), str(ticker), fill=text_main, font=font_ticker, anchor="mm")
    
    pnl_text = f"{arrow_char} {pnl_percent:+.2f}%"
    draw.text((width // 2, 430), pnl_text, fill=status_color, font=font_pnl, anchor="mm")
    
    # -- Grapth Section (Abstract Sparkline) --
    graph_y_center = 530
    graph_width = 700
    graph_height = 80
    
    points = 15
    data_points = []
    x_step = graph_width / (points - 1)
    base_y = graph_y_center + (graph_height // 2 if not is_profit else -graph_height // 2)
    
    for i in range(points):
        x = (width // 2 - graph_width // 2) + (i * x_step)
        progress = i / (points - 1)
        if is_profit:
            y = base_y + (graph_height) * (1 - progress) - random.uniform(0, 15)
        else:
            y = base_y - (graph_height) * (1 - progress) + random.uniform(0, 15)
        data_points.append((x, y))
        
    draw_img = ImageDraw.Draw(img, "RGBA") 
    for i in range(len(data_points) - 1):
        if i % 2 == 0:
            draw_img.line([data_points[i], data_points[i+1]], fill=status_color + (180,), width=3)

    end_point = data_points[-1]
    r = 8
    draw.ellipse([end_point[0]-r, end_point[1]-r, end_point[0]+r, end_point[1]+r], fill=status_color)
    draw_img.line([(end_point[0], end_point[1] + 10), (end_point[0], graph_y_center + graph_height // 2 + 30)], fill=status_color + (100,), width=2)
    
    # -- Footer Section (Data Panels) --
    panel_y = 610
    panel_height = 100
    panel_w_gap = 20
    panel_w = (width - 80 - (panel_w_gap * 2)) // 3
    
    def draw_data_panel(draw, x, y, w, h, label, value, val_color, font_l, font_v):
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle([x, y, x + w, y + h], radius=15, fill=panel_bg, outline=border_color, width=2)
        img.paste(overlay, (0, 0), overlay)
        
        draw.text((x + 30, y + 20), label, fill=text_sub, font=font_l)
        draw.text((x + 30, y + 50), value, fill=val_color, font=font_v)

    draw_data_panel(draw, 40, panel_y, panel_w, panel_height, "ENTRY PRICE", f"${entry_price:,.2f}", text_main, font_label, font_value)
    draw_data_panel(draw, 40 + panel_w + panel_w_gap, panel_y, panel_w, panel_height, "CURRENT PRICE", f"${current_price:,.2f}", status_color, font_label, font_value)
    draw_data_panel(draw, 40 + (panel_w * 2) + (panel_w_gap * 2), panel_y, panel_w, panel_height, "PnL CASH", f"{pnl_cash:+,.2f}", status_color, font_label, font_value)

    # ⬇️ 6. แปลงรูปภาพเป็น Bytes
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr