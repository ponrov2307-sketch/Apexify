import yfinance as yf
import pandas as pd
import io
import requests


ALLOWED_MARKET_SUFFIXES = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")


def _load_chart_modules():
    import matplotlib

    # ป้องกัน Error บน Server ที่ไม่มีหน้าจอ และเลื่อนการ import
    # ไปตอนที่ต้องสร้างกราฟจริงเท่านั้น
    matplotlib.use('Agg')

    import mplfinance as mpf

    return mpf

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


def _normalize_market_symbol(symbol):
    clean_symbol = str(symbol or "").strip().upper()
    if "." in clean_symbol and not clean_symbol.endswith(ALLOWED_MARKET_SUFFIXES):
        clean_symbol = clean_symbol.replace(".", "-")
    return clean_symbol


def _safe_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _safe_pct(numerator, denominator):
    if denominator in (None, 0):
        return None
    try:
        return (float(numerator) / float(denominator)) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _compute_poc_price(data, bins=10):
    if data is None or data.empty:
        return None

    recent = data.dropna(subset=['Close', 'Volume']).tail(min(60, len(data)))
    if len(recent) < 5:
        return None

    unique_prices = int(recent['Close'].nunique())
    if unique_prices < 2:
        return _safe_float(recent['Close'].iloc[-1])

    try:
        price_bins = pd.cut(recent['Close'], bins=max(2, min(bins, unique_prices)))
        vol_profile = recent.groupby(price_bins, observed=False)['Volume'].sum()
        if vol_profile.empty:
            return None
        poc_bin = vol_profile.idxmax()
        return _safe_float(poc_bin.mid)
    except Exception:
        return None


def _build_interval_snapshot(data, label):
    if data is None or data.empty or len(data) < 8:
        return {
            'label': label,
            'available': False,
            'history_len': 0 if data is None else int(len(data)),
        }

    calc_data = calculate_indicators(data.copy())
    latest = calc_data.iloc[-1]
    recent = calc_data.tail(min(20, len(calc_data)))
    first_close = _safe_float(recent['Close'].iloc[0]) if not recent.empty else None
    latest_close = _safe_float(latest.get('Close'))
    support = _safe_float(recent['Low'].min()) if 'Low' in recent and not recent.empty else None
    resistance = _safe_float(recent['High'].max()) if 'High' in recent and not recent.empty else None
    poc_price = _compute_poc_price(calc_data)
    avg_volume = None
    if 'Volume' in calc_data and len(calc_data) >= 5:
        avg_volume = _safe_float(calc_data['Volume'].tail(min(20, len(calc_data))).mean())
    latest_volume = _safe_float(latest.get('Volume'))
    volume_ratio = None
    if latest_volume is not None and avg_volume not in (None, 0):
        volume_ratio = latest_volume / avg_volume

    consolidation_pct = None
    if latest_close not in (None, 0) and support is not None and resistance is not None:
        consolidation_pct = ((resistance - support) / latest_close) * 100

    close_vs_ema20_pct = None
    ema20 = _safe_float(latest.get('EMA20'))
    if latest_close not in (None, 0) and ema20 not in (None, 0):
        close_vs_ema20_pct = ((latest_close - ema20) / ema20) * 100

    close_vs_poc_pct = None
    if latest_close not in (None, 0) and poc_price not in (None, 0):
        close_vs_poc_pct = ((latest_close - poc_price) / poc_price) * 100

    bb_upper = _safe_float(latest.get('BB_Upper'))
    bb_lower = _safe_float(latest.get('BB_Lower'))
    obv_trend = "flat"
    if 'OBV' in calc_data and len(calc_data) >= 2:
        recent_obv = calc_data['OBV'].tail(min(5, len(calc_data)))
        first_obv = _safe_float(recent_obv.iloc[0])
        latest_obv = _safe_float(recent_obv.iloc[-1])
        if first_obv is not None and latest_obv is not None:
            if latest_obv > first_obv:
                obv_trend = "up"
            elif latest_obv < first_obv:
                obv_trend = "down"

    return {
        'label': label,
        'available': True,
        'history_len': int(len(calc_data)),
        'price': latest_close,
        'rsi': _safe_float(latest.get('RSI')),
        'macd': _safe_float(latest.get('MACD')),
        'signal': _safe_float(latest.get('Signal_Line')),
        'ema20': ema20,
        'ema50': _safe_float(latest.get('EMA50')),
        'ema200': _safe_float(latest.get('EMA200')),
        'volume': latest_volume,
        'avg_volume': avg_volume,
        'volume_ratio': volume_ratio,
        'support': support,
        'resistance': resistance,
        'poc': poc_price,
        'consolidation_pct': consolidation_pct,
        'close_change_pct': _safe_pct((latest_close - first_close) if latest_close is not None and first_close is not None else None, first_close),
        'close_vs_ema20_pct': close_vs_ema20_pct,
        'close_vs_poc_pct': close_vs_poc_pct,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'obv_trend': obv_trend,
    }


def build_multitimeframe_trade_context(symbol):
    clean_symbol = _normalize_market_symbol(symbol)
    ticker = yf.Ticker(clean_symbol)

    try:
        daily_data = ticker.history(period="1y", interval="1d", auto_adjust=False)
    except Exception:
        daily_data = pd.DataFrame()

    try:
        weekly_data = ticker.history(period="5y", interval="1wk", auto_adjust=False)
    except Exception:
        weekly_data = pd.DataFrame()

    try:
        monthly_data = ticker.history(period="10y", interval="1mo", auto_adjust=False)
    except Exception:
        monthly_data = pd.DataFrame()

    day_snapshot = _build_interval_snapshot(daily_data, 'day')
    week_snapshot = _build_interval_snapshot(weekly_data, 'week')
    month_snapshot = _build_interval_snapshot(monthly_data, 'month')

    daily_rsi = day_snapshot.get('rsi')
    daily_volume_ratio = day_snapshot.get('volume_ratio')
    week_volume_ratio = week_snapshot.get('volume_ratio')
    is_extreme_volatility = (
        (daily_rsi is not None and (daily_rsi > 85 or daily_rsi < 15))
        or (daily_volume_ratio is not None and daily_volume_ratio >= 3.5)
        or (week_volume_ratio is not None and week_volume_ratio >= 3.0)
    )

    return {
        'symbol': clean_symbol,
        'price': day_snapshot.get('price') or week_snapshot.get('price') or month_snapshot.get('price'),
        'day': day_snapshot,
        'week': week_snapshot,
        'month': month_snapshot,
        'is_extreme_volatility': is_extreme_volatility,
    }

def calculate_technical_indicators(symbol, generate_chart=True):
    import time

    for attempt in range(2):
        try:
            clean_symbol = _normalize_market_symbol(symbol)

            # 2. ดึงข้อมูลจริง 1 ปี
            ticker = yf.Ticker(clean_symbol)
            data = ticker.history(period="1y")

            # 🌟 Auto-fallback: ถ้าไม่มี suffix และหา US ไม่เจอ → ลอง .BK (หุ้นไทย)
            if data.empty and "." not in clean_symbol and "-" not in clean_symbol:
                fallback_symbol = f"{clean_symbol}.BK"
                fallback_data = yf.Ticker(fallback_symbol).history(period="1y")
                if not fallback_data.empty:
                    clean_symbol = fallback_symbol
                    data = fallback_data

            if data.empty:
                return None, None, (
                    f"❌ ไม่พบข้อมูลหุ้น '{symbol}'\n\n"
                    f"💡 **คำแนะนำการพิมพ์ชื่อหุ้น:**\n"
                    f"• 🇺🇸 **อเมริกา:** พิมพ์ชื่อตรงๆ (เช่น `AAPL`)\n"
                    f"• 🇹🇭 **ไทย:** ต้องมี `.BK` ต่อท้าย (เช่น `PTT.BK`)\n"
                    f"• 🦘 **ออสเตรเลีย:** ต้องมี `.AX` ต่อท้าย (เช่น `CBA.AX`)\n"
                    f"• 🇬🇧 **ลอนดอน:** ต้องมี `.L` ต่อท้าย (เช่น `HSBA.L`)\n"
                    f"• 🇭🇰 **ฮ่องกง:** ต้องมี `.HK` ต่อท้าย (เช่น `0700.HK`)\n"
                    f"• 🇯🇵 **ญี่ปุ่น:** ต้องมี `.T` ต่อท้าย (เช่น `7203.T`)\n\n"
                    f"ลองตรวจสอบตัวสะกดแล้วพิมพ์ส่งมาใหม่อีกครั้งนะครับ!"
                )
            if len(data) < 20:
                return None, None, (
                    f"⏳ หุ้น '{clean_symbol}' เพิ่ง IPO หรือมีข้อมูลย้อนหลังไม่พอ "
                    f"ระบบต้องใช้ราคาอย่างน้อย 20 วัน ลองหุ้นตัวอื่นดูนะครับ"
                )

            # --- เริ่มคำนวณอินดิเคเตอร์ ---
            data = calculate_indicators(data)
            latest = data.iloc[-1]
            prev = data.iloc[-2]
            
            recent20 = data.tail(20)
            support = float(recent20['Low'].min())
            resistance = float(recent20['High'].max())
            
            # 🌟 [เพิ่มใหม่] คำนวณ Volume Profile (โซนคนติดดอย/กระจุกตัว) จากข้อมูล 60 วันย้อนหลัง
            recent60 = data.tail(60)
            price_bins = pd.cut(recent60['Close'], bins=10)
            vol_profile = recent60.groupby(price_bins, observed=False)['Volume'].sum()
            poc_bin = vol_profile.idxmax() # ช่วงราคาที่มีคนซื้อขายเยอะสุด
            poc_price = poc_bin.mid # ราคาตรงกลางของโซนนั้น
            
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
                'poc_price': float(poc_price), # 🌟 ส่งค่าราคากระจุกตัวไปให้ AI วิเคราะห์
                'obv_trend': "เพิ่มขึ้น 📈" if latest['OBV'] > prev['OBV'] else "ลดลง 📉",
                'fear_greed': get_fear_and_greed_index(),
                'volume': float(latest['Volume']), 
                'avg_volume': float(data['Volume'].rolling(window=20).mean().iloc[-1])
            }

            if generate_chart:
                mpf = _load_chart_modules()
                buf = io.BytesIO()
                
                mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', edge='inherit', wick='inherit', volume='in')
                s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds', gridstyle=':', rc={'font.size': 10})
                
                add_plots = [
                    mpf.make_addplot(data['EMA20'].tail(60), color='#2962ff', width=1.5),
                    mpf.make_addplot(data['EMA50'].tail(60), color='#ff6d00', width=1.5),
                    mpf.make_addplot(data['EMA200'].tail(60), color='#d500f9', width=1.5),
                ]

                # 🌟 อัปเดตหัวกราฟให้บอกสีเส้นใหม่
                chart_title = (
                    f"\\nApexify Pro Chart: {clean_symbol}\\n"
                    f"EMA: 20(Blue) 50(Orange) 200(Purple) | Res(Red) Sup(Green) | POC(Yellow)"
                )

                # 🌟 เพิ่มคำสั่งตีเส้น hlines สำหรับโซนคนติดดอย (สีเหลือง #ffff00)
                mpf.plot(
                    data.tail(60),
                    type='candle',
                    style=s,
                    title=chart_title,
                    volume=True,
                    panel_ratios=(4, 1), 
                    addplot=add_plots,
                    hlines=dict(hlines=[resistance, support, float(poc_price)], colors=['#ff0000', '#00ff00', '#ffff00'], linestyle='-.', linewidths=1.5),
                    savefig=dict(fname=buf, dpi=120, bbox_inches='tight', pad_inches=0.1), 
                    figratio=(16, 9), 
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
            print(f"[TechIndicators] {symbol} failed: {e}", flush=True)
            return None, None, (
                f"⚠️ ดึงข้อมูลหุ้น '{symbol}' ไม่สำเร็จ — เซิร์ฟเวอร์ตลาดอาจจะหนาแน่นชั่วคราว "
                f"ลองส่งใหม่อีกครั้งใน 30 วินาทีนะครับ 🙏"
            )
