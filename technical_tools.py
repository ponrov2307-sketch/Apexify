import matplotlib
matplotlib.use('Agg') # ป้องกัน Error บน Server ที่ไม่มีหน้าจอ
import matplotlib.pyplot as plt
import mplfinance as mpf
import yfinance as yf
import pandas as pd
import io
import requests

def get_fear_and_greed_index():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            score = data['fear_and_greed']['score']
            rating = data['fear_and_greed']['rating'].lower()
            
            rating_map = {
                "extreme fear": "กลัวสุดขีด 🩸", "fear": "กลัว 🔴",
                "neutral": "ปกติ ⚪️", "greed": "โลภ 🟢", "extreme greed": "โลภสุดขีด 🤑"
            }
            return f"{score:.0f}/100 ({rating_map.get(rating, rating.capitalize())})"
    except Exception as e:
        print(f"F&G API Error: {e}")
    return "ไม่สามารถดึงข้อมูลได้"

def calculate_indicators(data):
    # EMA
    data['EMA20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA50'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['EMA200'] = data['Close'].ewm(span=200, adjust=False).mean()
    
    # RSI (14)
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = data['Close'].ewm(span=12, adjust=False).mean()
    ema26 = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = ema12 - ema26
    data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands (20)
    data['BB_Middle'] = data['Close'].rolling(window=20).mean()
    std = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['BB_Middle'] + (2 * std)
    data['BB_Lower'] = data['BB_Middle'] - (2 * std)
    
    # OBV
    obv = [0]
    for i in range(1, len(data.Close)):
        if data.Close.iloc[i] > data.Close.iloc[i-1]:
            obv.append(obv[-1] + data.Volume.iloc[i])
        elif data.Close.iloc[i] < data.Close.iloc[i-1]:
            obv.append(obv[-1] - data.Volume.iloc[i])
        else:
            obv.append(obv[-1])
    data['OBV'] = obv
    
    return data

def calculate_technical_indicators(symbol, generate_chart=True):
    import time
    
    for attempt in range(2):
        try:
            clean_symbol = symbol.strip().upper()
            
            # 1. จัดการหุ้นคลาส B (อเมริกา) (เช่น BRK.B แปลงเป็น BRK-B)
            if "." in clean_symbol and not clean_symbol.endswith(".BK"):
                clean_symbol = clean_symbol.replace(".", "-")
            
            # 2. ดึงข้อมูลจริง 1 ปี
            ticker = yf.Ticker(clean_symbol)
            data = ticker.history(period="1y")

            if data.empty:
                return None, None, (
                    f"❌ ไม่พบข้อมูลหุ้น '{symbol}'\n\n"
                    f"💡 **คำแนะนำ:**\n"
                    f"หากคุณต้องการวิเคราะห์ **หุ้นไทย** จะต้องพิมพ์ `.BK` ต่อท้ายเสมอครับ\n"
                    f"(เช่น `PTT.BK`, `KBANK.BK`, `TRUE.BK`)\n"
                    f"เพื่อป้องกันการดึงข้อมูลผิดพลาดไปซ้ำกับหุ้นต่างประเทศครับ"
                )
            if len(data) < 20:
                return None, None, f"❌ ข้อมูลหุ้น '{clean_symbol}' มีน้อยเกินไป ระบบไม่สามารถคำนวณกราฟได้"

            # --- เริ่มคำนวณอินดิเคเตอร์ ---
            data = calculate_indicators(data)
            latest = data.iloc[-1]
            prev = data.iloc[-2]
            
            recent20 = data.tail(20)
            support = float(recent20['Low'].min())
            resistance = float(recent20['High'].max())
            
            tech_data = {
                'symbol': clean_symbol,
                'price': float(latest['Close']),
                'rsi': float(latest['RSI']),
                'macd': float(latest['MACD']),
                'macd_signal': float(latest['Signal_Line']),
                'ema20': float(latest['EMA20']),
                'ema50': float(latest['EMA50']),
                'ema200': float(latest['EMA200']),
                'bb_upper': float(latest['BB_Upper']),
                'bb_lower': float(latest['BB_Lower']),
                'support': support,
                'resistance': resistance,
                'obv_trend': "เพิ่มขึ้น 📈" if latest['OBV'] > prev['OBV'] else "ลดลง 📉",
                'fear_greed': get_fear_and_greed_index()
            }

            if generate_chart:
                buf = io.BytesIO()
                
                mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', edge='inherit', wick='inherit', volume='in')
                s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds', gridstyle=':', rc={'font.size': 10})
                
                add_plots = [
                    mpf.make_addplot(data['EMA20'].tail(60), color='#2962ff', width=1.5),
                    mpf.make_addplot(data['EMA50'].tail(60), color='#ff6d00', width=1.5),
                    mpf.make_addplot(data['EMA200'].tail(60), color='#d500f9', width=1.5),
                ]

                # 🌟 อัปเดตหัวกราฟให้บอกสีเส้นต่างๆ รวมถึงแนวรับ-แนวต้าน
                chart_title = (
                    f"\\nApexify Pro Chart: {clean_symbol}\\n"
                    f"EMA: 20(Blue) 50(Orange) 200(Purple) | Res(Red) Sup(Green)"
                )

                # 🌟 เพิ่มคำสั่งตีเส้น hlines สำหรับแนวต้าน (สีแดง) และแนวรับ (สีเขียว)
                mpf.plot(
                    data.tail(60),
                    type='candle',
                    style=s,
                    title=chart_title,
                    volume=True,
                    panel_ratios=(4, 1), # แท่งเทียน 80% Volume 20%
                    addplot=add_plots,
                    hlines=dict(hlines=[resistance, support], colors=['#ff0000', '#00ff00'], linestyle='-.', linewidths=1.5),
                    savefig=dict(fname=buf, dpi=120, bbox_inches='tight', pad_inches=0.1), # เพิ่มความคมชัด
                    figratio=(16, 9), # ทำให้กราฟเป็นแนวนอนกว้างขึ้น
                    figscale=1.2,
                    tight_layout=True
                )
                
                buf.seek(0)
                return tech_data, buf, None
            
            else:
                return tech_data, None, None

        except Exception as e:
            if attempt == 0:
                time.sleep(1)
                continue
            return None, None, f"❌ เกิดข้อผิดพลาดในการคำนวณกราฟ: {str(e)}"
