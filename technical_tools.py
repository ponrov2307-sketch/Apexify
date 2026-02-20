import matplotlib
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io
import requests # <--- เพิ่ม import requests
matplotlib.use('Agg') # <--- เพิ่ม 2 บรรทัดนี้ก่อน import pyplot
import matplotlib.pyplot as plt 

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
            
            # แปลงสถานะเป็นภาษาไทยและอีโมจิ
            rating_map = {
                "extreme fear": "กลัวสุดขีด 🩸",
                "fear": "กลัว 🔴",
                "neutral": "ปกติ ⚪️",
                "greed": "โลภ 🟢",
                "extreme greed": "โลภสุดขีด 🤑"
            }
            rating_th = rating_map.get(rating, rating.capitalize())
            return f"{score:.0f}/100 ({rating_th})"
    except Exception as e:
        print(f"F&G API Error: {e}")
    return "ไม่สามารถดึงข้อมูลได้"
def calculate_indicators(data):
    # EMA
    data['EMA5'] = data['Close'].ewm(span=5, adjust=False).mean()
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
    
    # OBV (On-Balance Volume)
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

def calculate_technical_indicators(symbol):
    try:
        # ตัดช่องว่างเผื่อพิมพ์ผิด และทำเป็นตัวพิมพ์ใหญ่
        clean_symbol = symbol.strip().upper()
        
        # ใช้วิธีดึงข้อมูลที่เสถียรที่สุด (แก้ปัญหาหาหุ้นไม่เจอ)
        ticker = yf.Ticker(clean_symbol)
        data = ticker.history(period="1y")
        
        if data.empty:
            return None, None, f"❌ ไม่พบข้อมูลหุ้น '{clean_symbol}' ในระบบ โปรดตรวจสอบตัวสะกด (หุ้นไทยอย่าลืมใส่ .BK)"

        # ส่งไปคำนวณอินดิเคเตอร์
        data = calculate_indicators(data)
        
        latest = data.iloc[-1]
        prev = data.iloc[-2]
        
        # ดึงค่าราคาปัจจุบัน
        current_price = float(latest['Close'])
        
        # คำนวณแนวรับ-แนวต้าน (20 วันล่าสุด)
        recent20 = data.tail(20)
        support = float(recent20['Low'].min())
        resistance = float(recent20['High'].max())
        
        obv_trend = "เพิ่มขึ้น 📈" if latest['OBV'] > prev['OBV'] else "ลดลง 📉"
        fg_index = get_fear_and_greed_index()
        # แพ็กข้อมูลส่งกลับไปให้ AI สรุปใน ai_analyzer.py
        tech_data = {
            'symbol': clean_symbol,
            'price': current_price,
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
            'obv_trend': obv_trend,
            'fear_and_greed': fg_index
        }

        # --- วาดกราฟ Apexify Pro ---
        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')
        plot_data = data.tail(90) # แสดกราฟแค่ 3 เดือนย้อนหลังให้ดูง่าย
        plt.plot(plot_data.index, plot_data['Close'], label='Price', color='#00e676', linewidth=2)
        plt.plot(plot_data.index, plot_data['EMA20'], label='EMA20', color='#3b82f6', linestyle='--')
        plt.plot(plot_data.index, plot_data['EMA50'], label='EMA50', color='#ff5252', linestyle='--')
        
        plt.axhline(y=support, color='green', linestyle=':', alpha=0.6, label='Support')
        plt.axhline(y=resistance, color='red', linestyle=':', alpha=0.6, label='Resistance')
        
        plt.title(f"Apexify Intelligence: {clean_symbol}", color='#d4af37', size=16, weight='bold')
        plt.legend(loc='best')
        plt.grid(color='#333', linestyle='--')
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        return tech_data, buf, None

    except Exception as e:
        return None, None, f"❌ เกิดข้อผิดพลาดในการคำนวณ: {str(e)}"