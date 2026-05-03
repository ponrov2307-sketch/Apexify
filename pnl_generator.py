import io
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

def generate_pnl_card(username, ticker, entry_price, current_price, pnl_font_path='YesevaOne-Regular.ttf'):
    """สร้างภาพ Apexify Viral Card (PnL) สวยงาม ดึงดูดคนใช้งาน"""
    
    # 📏 1. ตั้งค่าขนาด 1080x1080 (Square Format เหมาะแก่การแชร์สุดๆ)
    width, height = 1080, 1080 
    
    # พาเลตต์สีสไตล์ Premium Cyber
    bg_color = (10, 14, 23)           # สีน้ำเงินดำลึก (Deep Space)
    grid_color = (25, 35, 55, 100)    # สีตารางกริด
    panel_bg = (20, 30, 45, 220)      # สีกล่องข้อมูลแบบกระจก (Glassmorphism)
    border_color = (50, 65, 90, 255)  
    text_main = (255, 255, 255)       
    text_sub = (138, 153, 181)        
    
    # 📊 คำนวณ PnL
    pnl_cash = current_price - entry_price
    pnl_percent = (pnl_cash / entry_price) * 100 if entry_price > 0 else 0
    is_profit = pnl_percent >= 0
    
    color_neon = (0, 255, 136) if is_profit else (255, 42, 95) # เขียวนีออน / แดงนีออน
    arrow_char = "▲" if is_profit else "▼"
    
    # 🖼️ 2. สร้างเลเยอร์พื้นหลัง
    img = Image.new('RGBA', (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # วาดตารางกริด (Trading Grid Background)
    grid_spacing = 60
    for x in range(0, width, grid_spacing):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, grid_spacing):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # วาดวงกลมเรืองแสง (Glow Effect) ไว้หลังข้อความ
    glow_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    center_glow = (width // 2, 450)
    glow_draw.ellipse(
        [center_glow[0]-300, center_glow[1]-300, center_glow[0]+300, center_glow[1]+300], 
        fill=color_neon + (20,) # โปร่งแสงมากๆ
    )
    # เบลอแสงให้ฟุ้ง
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=80))
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img) # ดึง draw กลับมาวาดต่อบนภาพที่รวมแสงแล้ว

    # 🔤 3. โหลด Fonts (YesevaOne-Regular)
    try:
        if not os.path.exists(pnl_font_path):
            print(f"⚠️ Warning: ไม่พบ {pnl_font_path} จะใช้ฟอนต์พื้นฐานแทน")
            font_title = font_user = font_ticker = font_pnl = font_label = font_value = font_cta = ImageFont.load_default()
        else:
            font_title = ImageFont.truetype(pnl_font_path, 45)
            font_user = ImageFont.truetype(pnl_font_path, 35)
            font_ticker = ImageFont.truetype(pnl_font_path, 150) 
            font_pnl = ImageFont.truetype(pnl_font_path, 220)    
            font_label = ImageFont.truetype(pnl_font_path, 28)
            font_value = ImageFont.truetype(pnl_font_path, 55)
            font_cta = ImageFont.truetype(pnl_font_path, 30)
    except Exception as e:
        font_title = font_user = font_ticker = font_pnl = font_label = font_value = font_cta = ImageFont.load_default()

    # ✍️ 4. Layout: Header & Title
    # โลโก้เพชรแบบง่ายๆ
    draw.polygon([(80, 50), (100, 80), (80, 110), (60, 80)], fill=color_neon)
    draw.text((120, 60), "APEXIFY TRADING AI", fill=text_main, font=font_title)
    
    # ป้ายแบนเนอร์ User ด้านขวาบน
    draw.rounded_rectangle([width - 350, 50, width - 50, 110], radius=15, fill=panel_bg, outline=color_neon, width=2)
    draw.text((width - 200, 80), f"@{username[:12]}", fill=text_main, font=font_user, anchor="mm")
    
    # ✍️ 5. Center Data (Ticker & Percentage)
    draw.text((width // 2, 280), f"{ticker} / USD", fill=text_main, font=font_ticker, anchor="mm")
    
    pnl_text = f"{arrow_char} {pnl_percent:+.2f}%"
    # วาด Drop Shadow ให้เปอร์เซ็นต์
    draw.text((width // 2 + 5, 500 + 5), pnl_text, fill=(0,0,0,150), font=font_pnl, anchor="mm")
    draw.text((width // 2, 500), pnl_text, fill=color_neon, font=font_pnl, anchor="mm")
    
    # 📈 6. กราฟ Area Chart สุดเท่
    graph_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(graph_layer)
    
    graph_y_base = 650
    graph_w = 800
    graph_h = 100
    points = 20
    x_step = graph_w / (points - 1)
    
    # สร้างจุดสุ่ม
    data_points = []
    for i in range(points):
        x = (width // 2 - graph_w // 2) + (i * x_step)
        progress = i / (points - 1)
        if is_profit: y = graph_y_base + (graph_h) * (1 - progress) - random.uniform(0, 20)
        else: y = graph_y_base - (graph_h) * (1 - progress) + random.uniform(0, 20)
        data_points.append((x, y))
        
    # วาดสีพื้นกราฟแบบโปร่งแสง (Area Chart)
    area_points = [(data_points[0][0], graph_y_base + 150)] + data_points + [(data_points[-1][0], graph_y_base + 150)]
    g_draw.polygon(area_points, fill=color_neon + (30,))
    
    # วาดเส้นกราฟเรืองแสง
    g_draw.line(data_points, fill=color_neon, width=6)
    
    # จุดปลายกราฟ
    end_pt = data_points[-1]
    g_draw.ellipse([end_pt[0]-10, end_pt[1]-10, end_pt[0]+10, end_pt[1]+10], fill=text_main, outline=color_neon, width=4)
    g_draw.line([(end_pt[0], end_pt[1]), (end_pt[0], graph_y_base + 150)], fill=color_neon + (150,), width=2)
    
    img = Image.alpha_composite(img, graph_layer)
    draw = ImageDraw.Draw(img)

    # 🗂️ 7. แผงข้อมูลด้านล่าง (Glassmorphism Panels)
    panel_y = 800
    panel_h = 130
    panel_w = 280
    spacing = 40
    start_x = (width - (panel_w * 3 + spacing * 2)) // 2
    
    def draw_panel(x, y, w, h, label, value, v_color):
        # กล่องหลัง
        draw.rounded_rectangle([x, y, x + w, y + h], radius=20, fill=panel_bg, outline=border_color, width=2)
        # ข้อมูล
        draw.text((x + w//2, y + 40), label, fill=text_sub, font=font_label, anchor="mm")
        draw.text((x + w//2, y + 90), value, fill=v_color, font=font_value, anchor="mm")

    draw_panel(start_x, panel_y, panel_w, panel_h, "ENTRY PRICE", f"${entry_price:,.2f}", text_main)
    draw_panel(start_x + panel_w + spacing, panel_y, panel_w, panel_h, "CURRENT PRICE", f"${current_price:,.2f}", color_neon)
    draw_panel(start_x + (panel_w + spacing) * 2, panel_y, panel_w, panel_h, "PnL CASH", f"{pnl_cash:+,.2f}", color_neon)

    # 🚀 8. Call to Action (ตัวดึงคนเข้ามาใช้บอท)
    cta_bg = [0, height - 70, width, height]
    draw.rectangle(cta_bg, fill=color_neon)
    draw.text((width // 2, height - 35), "⚡ GENERATED BY APEXIFY AI • START YOUR JOURNEY TODAY ⚡", fill=(0,0,0), font=font_cta, anchor="mm")

    # ⬇️ 9. แปลงภาพเป็น RGB แล้วบันทึก
    img = img.convert("RGB")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    return img_byte_arr


def generate_portfolio_pnl_card(
    username: str,
    holdings: list,            # [{ticker, shares, avg_cost, price, value, pnl, pnl_pct}, ...]
    total_value: float,
    total_cost: float,
    thb_value: float | None = None,
    pnl_font_path: str = 'YesevaOne-Regular.ttf',
):
    """Apexify viral card สำหรับทั้งพอร์ต — แสดงทุกหุ้นในการ์ดเดียว

    Layout 1080×1350 (Story-friendly portrait):
      • Header: APEXIFY logo + @username
      • Hero: total portfolio value + overall P&L %
      • Holdings list: top 8 tickers sorted by P&L %
      • Footer panels: total cost / total P&L / # stocks
      • CTA strip
    """
    width, height = 1080, 1350

    # สีโทนเดียวกับ generate_pnl_card — Premium Cyber
    bg_color = (10, 14, 23)
    grid_color = (25, 35, 55, 100)
    panel_bg = (20, 30, 45, 220)
    border_color = (50, 65, 90, 255)
    text_main = (255, 255, 255)
    text_sub = (138, 153, 181)

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    is_profit = total_pnl_pct >= 0
    color_neon = (0, 255, 136) if is_profit else (255, 42, 95)
    color_red = (255, 42, 95)
    arrow_char = "▲" if is_profit else "▼"

    img = Image.new('RGBA', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Grid background
    grid_spacing = 60
    for x in range(0, width, grid_spacing):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, grid_spacing):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)

    # Glow behind hero
    glow_layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.ellipse([240, 250, 840, 850], fill=color_neon + (18,))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=80))
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img)

    # Fonts
    try:
        if not os.path.exists(pnl_font_path):
            f_title = f_user = f_hero_label = f_hero_val = f_pct = f_row = f_panel_l = f_panel_v = f_cta = ImageFont.load_default()
        else:
            f_title = ImageFont.truetype(pnl_font_path, 38)
            f_user = ImageFont.truetype(pnl_font_path, 28)
            f_hero_label = ImageFont.truetype(pnl_font_path, 26)
            f_hero_val = ImageFont.truetype(pnl_font_path, 110)
            f_pct = ImageFont.truetype(pnl_font_path, 80)
            f_row = ImageFont.truetype(pnl_font_path, 38)
            f_panel_l = ImageFont.truetype(pnl_font_path, 22)
            f_panel_v = ImageFont.truetype(pnl_font_path, 42)
            f_cta = ImageFont.truetype(pnl_font_path, 28)
    except Exception:
        f_title = f_user = f_hero_label = f_hero_val = f_pct = f_row = f_panel_l = f_panel_v = f_cta = ImageFont.load_default()

    # Header
    draw.polygon([(80, 50), (100, 80), (80, 110), (60, 80)], fill=color_neon)
    draw.text((120, 60), "APEXIFY · MY PORTFOLIO", fill=text_main, font=f_title)

    # User badge
    safe_user = (username or "Trader")[:14]
    draw.rounded_rectangle([width - 350, 50, width - 50, 105], radius=15, fill=panel_bg, outline=color_neon, width=2)
    draw.text((width - 200, 78), f"@{safe_user}", fill=text_main, font=f_user, anchor="mm")

    # Hero — total value
    draw.text((width // 2, 200), "TOTAL PORTFOLIO VALUE", fill=text_sub, font=f_hero_label, anchor="mm")
    draw.text((width // 2, 290), f"${total_value:,.2f}", fill=text_main, font=f_hero_val, anchor="mm")

    pnl_text = f"{arrow_char} {total_pnl_pct:+.2f}%"
    # Drop shadow
    draw.text((width // 2 + 4, 412), pnl_text, fill=(0, 0, 0, 150), font=f_pct, anchor="mm")
    draw.text((width // 2, 408), pnl_text, fill=color_neon, font=f_pct, anchor="mm")

    # Sort holdings by pnl_pct desc, take top 8
    sorted_holdings = sorted(holdings, key=lambda h: h.get('pnl_pct', 0), reverse=True)[:8]

    # Holdings list panel
    list_x = 80
    list_y = 500
    list_w = width - 160
    row_h = 70
    list_h = row_h * len(sorted_holdings) + 20

    draw.rounded_rectangle(
        [list_x, list_y, list_x + list_w, list_y + list_h],
        radius=24, fill=panel_bg, outline=border_color, width=2,
    )

    for i, h in enumerate(sorted_holdings):
        ry = list_y + 20 + i * row_h
        h_pnl_pct = h.get('pnl_pct', 0)
        h_pnl = h.get('pnl', 0)
        ticker = str(h.get('ticker', '???'))[:8]
        h_color = color_neon if h_pnl_pct >= 0 else color_red

        # Left: ticker
        draw.text((list_x + 32, ry + row_h // 2), ticker, fill=text_main, font=f_row, anchor="lm")

        # Right: pct + cash
        pct_str = f"{h_pnl_pct:+.2f}%"
        cash_str = f"({h_pnl:+,.0f})"
        draw.text((list_x + list_w - 32, ry + row_h // 2), pct_str, fill=h_color, font=f_row, anchor="rm")
        draw.text((list_x + list_w - 200, ry + row_h // 2), cash_str, fill=text_sub, font=f_panel_l, anchor="rm")

        # Subtle row divider
        if i < len(sorted_holdings) - 1:
            draw.line(
                [(list_x + 32, ry + row_h - 4), (list_x + list_w - 32, ry + row_h - 4)],
                fill=(40, 50, 70, 180), width=1,
            )

    # Footer panels — Cost / P&L / # stocks
    footer_y = list_y + list_h + 30
    panel_h = 110
    panel_w = 280
    spacing = 40
    start_x = (width - (panel_w * 3 + spacing * 2)) // 2

    def draw_panel(x, y, label, value, v_color):
        draw.rounded_rectangle([x, y, x + panel_w, y + panel_h], radius=20, fill=panel_bg, outline=border_color, width=2)
        draw.text((x + panel_w // 2, y + 32), label, fill=text_sub, font=f_panel_l, anchor="mm")
        draw.text((x + panel_w // 2, y + 75), value, fill=v_color, font=f_panel_v, anchor="mm")

    draw_panel(start_x, footer_y, "TOTAL COST", f"${total_cost:,.0f}", text_main)
    pnl_str = f"{total_pnl:+,.0f}"
    draw_panel(start_x + panel_w + spacing, footer_y, "TOTAL P&L", pnl_str, color_neon)
    draw_panel(start_x + (panel_w + spacing) * 2, footer_y, "STOCKS", str(len(holdings)), text_main)

    # THB strip (optional)
    if thb_value and thb_value > 0:
        thb_y = footer_y + panel_h + 24
        draw.rounded_rectangle([list_x, thb_y, list_x + list_w, thb_y + 56], radius=14, fill=panel_bg, outline=border_color, width=1)
        thb_text = f"≈ ฿{thb_value:,.0f} · {len(holdings)} หุ้นในพอร์ต"
        draw.text((width // 2, thb_y + 28), thb_text, fill=(252, 213, 53), font=f_panel_l, anchor="mm")

    # CTA strip
    cta_bg = [0, height - 70, width, height]
    draw.rectangle(cta_bg, fill=color_neon)
    draw.text((width // 2, height - 35), "⚡ APEXIFY AI · START YOUR JOURNEY → t.me/Apexify_Trading_Bot ⚡",
              fill=(0, 0, 0), font=f_cta, anchor="mm")

    img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format='PNG')
    out.seek(0)
    return out