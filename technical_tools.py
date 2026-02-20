import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import io

def calculate_technical_indicators(symbol):
    try:
        df = yf.download(symbol, period="6mo", interval="1d", progress=False)
        if df.empty:
            return None, None, "❌ ไม่พบข้อมูลหุ้นนี้ในระบบ"

        # 1. Moving Averages
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()

        # 2. RSI (14 days)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 3. MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()

        # 4. Bollinger Bands (20 days)
        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
        df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)

        # 5. Support & Resistance (ย้อนหลัง 20 วัน)
        recent_20 = df.tail(20)
        support = recent_20['Low'].min()
        resistance = recent_20['High'].max()
        
        # 6. OBV (On-Balance Volume)
        df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()

        # ดึงข้อมูลวันล่าสุด
        latest = df.iloc[-1]
        
        tech_data = {
            "symbol": symbol.upper(),
            "price": float(latest['Close']),
            "rsi": float(latest['RSI']),
            "macd": float(latest['MACD']),
            "macd_signal": float(latest['Signal_Line']),
            "ema20": float(latest['EMA20']),
            "ema50": float(latest['EMA50']),
            "ema200": float(latest['EMA200']),
            "bb_upper": float(latest['BB_Upper']),
            "bb_lower": float(latest['BB_Lower']),
            "support": float(support),
            "resistance": float(resistance),
            "obv_trend": "เพิ่มขึ้น" if float(df['OBV'].iloc[-1]) > float(df['OBV'].iloc[-2]) else "ลดลง"
        }

        # --- สร้างกราฟ (Visual Chart) ---
        plt.figure(figsize=(10, 5))
        plt.style.use('dark_background')
        plt.plot(df.index[-60:], df['Close'][-60:], label='Price', color='#00e676', linewidth=2)
        plt.plot(df.index[-60:], df['BB_Upper'][-60:], color='gray', linestyle='--', alpha=0.5)
        plt.plot(df.index[-60:], df['BB_Lower'][-60:], color='gray', linestyle='--', alpha=0.5)
        plt.fill_between(df.index[-60:], df['BB_Lower'][-60:], df['BB_Upper'][-60:], color='gray', alpha=0.1)
        
        plt.axhline(y=support, color='#ff5252', linestyle=':', label=f'Support ({support:.2f})')
        plt.axhline(y=resistance, color='#3b82f6', linestyle=':', label=f'Resistance ({resistance:.2f})')
        
        plt.title(f"Apexify Analysis: {symbol.upper()}", color='white')
        plt.legend(loc='best')
        plt.grid(color='#333', linestyle='--')
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close()

        return tech_data, buf, None

    except Exception as e:
        return None, None, f"❌ Error การดึงข้อมูล: {str(e)}"