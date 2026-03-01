from PIL import Image, ImageDraw, ImageFont
import io

def generate_pnl_card(username: str, ticker: str, entry_price: float, current_price: float) -> io.BytesIO:
    """ฟังก์ชันวาดรูปการ์ด PnL สไตล์กระดานเทรด"""
    
    profit_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    is_profit = profit_pct >= 0
    
    main_color = "#32D74B" if is_profit else "#FF453A"
    sign = "+" if is_profit else ""
    
    width, height = 1080, 1080
    image = Image.new("RGB", (width, height), "#0B0E11")
    draw = ImageDraw.Draw(image)
    
    draw.rectangle([(50, 50), (1030, 1030)], outline="#2B3139", width=4)
    draw.rectangle([(40, 40), (1040, 1040)], outline=main_color, width=2)

    try:
        font_huge = ImageFont.truetype("arialbd.ttf", 200)
        font_title = ImageFont.truetype("arialbd.ttf", 80)
        font_normal = ImageFont.truetype("arial.ttf", 50)
        font_small = ImageFont.truetype("arial.ttf", 40)
    except IOError:
        font_huge = font_title = font_normal = font_small = ImageFont.load_default()

    draw.text((80, 80), "APEXIFY MASTER", fill="#D0FD3E", font=font_normal)
    draw.text((80, 140), "PREMIUM PORTFOLIO", fill="#8B949E", font=font_small)
    draw.text((80, 300), f"{ticker} / USD", fill="#FFFFFF", font=font_title)
    
    position_text = "LONG (SPOT)" if is_profit else "HOLDING"
    draw.text((80, 400), position_text, fill=main_color, font=font_normal)
    draw.text((80, 500), f"{sign}{profit_pct:.2f}%", fill=main_color, font=font_huge)

    draw.text((80, 800), "Entry Price", fill="#8B949E", font=font_normal)
    draw.text((80, 860), f"${entry_price:,.2f}", fill="#FFFFFF", font=font_title)
    draw.text((600, 800), "Current Price", fill="#8B949E", font=font_normal)
    draw.text((600, 860), f"${current_price:,.2f}", fill="#FFFFFF", font=font_title)

    draw.text((80, 1000), f"Trader: @{username}", fill="#D0FD3E", font=font_small)
    draw.text((700, 1000), "Scan to Join Apexify 🚀", fill="#8B949E", font=font_small)

    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr