import yfinance as yf
import pandas as pd
import io
import requests
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from cachetools import TTLCache


ALLOWED_MARKET_SUFFIXES = (".BK", ".AX", ".L", ".HK", ".T", ".DE", ".SI", ".KS", ".KQ", ".TW", ".PA")

_yf_history_cache = TTLCache(maxsize=400, ttl=300)
_yf_cache_lock = RLock()
_yf_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="yfetch")


def _fetch_history_cached(symbol, period="1y", interval="1d", auto_adjust=True):
    import time as _t
    key = (symbol, period, interval, auto_adjust)
    with _yf_cache_lock:
        cached = _yf_history_cache.get(key)
    if cached is not None:
        print(f"[yfcache] HIT  {symbol} {period}/{interval} (cache size={len(_yf_history_cache)})", flush=True)
        return cached.copy()
    t0 = _t.time()
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=auto_adjust)
    except Exception as e:
        print(f"[yfetch] {symbol} {period}/{interval} failed: {e}", flush=True)
        return pd.DataFrame()
    elapsed = _t.time() - t0
    if df is None or df.empty:
        print(f"[yfcache] MISS {symbol} {period}/{interval} EMPTY ({elapsed:.2f}s)", flush=True)
        return pd.DataFrame()
    with _yf_cache_lock:
        _yf_history_cache[key] = df.copy()
    print(f"[yfcache] MISS {symbol} {period}/{interval} fetched ({elapsed:.2f}s, cache size={len(_yf_history_cache)})", flush=True)
    return df


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

    # ATR (14) — Average True Range — สำหรับ stop sizing แบบ volatility-aware
    high_low = data['High'] - data['Low']
    high_close = (data['High'] - data['Close'].shift()).abs()
    low_close = (data['Low'] - data['Close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    data['ATR'] = true_range.rolling(window=14).mean()

    # OBV (vectorized — เร็วกว่า loop เดิม ~50x)
    direction = data['Close'].diff().fillna(0)
    obv_step = data['Volume'].where(direction > 0, -data['Volume'].where(direction < 0, 0))
    data['OBV'] = obv_step.cumsum()

    return data


_COMMODITY_ALIASES = {
    # 🥇 ราคา spot จริง — ใช้ futures (=F suffix) ไม่ใช่ ETF เพราะราคา ETF ต่างจาก spot
    'GOLD': 'GC=F', 'ทอง': 'GC=F', 'ทองคำ': 'GC=F',
    'SILVER': 'SI=F', 'SIV': 'SI=F', 'แร่เงิน': 'SI=F', 'เงิน': 'SI=F',
    'OIL': 'CL=F', 'CRUDE': 'CL=F', 'น้ำมัน': 'CL=F', 'น้ำมันดิบ': 'CL=F',
    'GAS': 'NG=F', 'NATGAS': 'NG=F', 'ก๊าซ': 'NG=F', 'ก๊าซธรรมชาติ': 'NG=F',
    'COPPER': 'HG=F', 'ทองแดง': 'HG=F',
    'PLATINUM': 'PL=F', 'ทองคำขาว': 'PL=F',
    'PALLADIUM': 'PA=F', 'พาลาเดียม': 'PA=F',
    # ETF aliases — ถ้า user พิมพ์ตรงๆ ก็ส่งไปตามนั้น (ราคา ETF ไม่ใช่ spot)
    'GLD': 'GLD', 'SLV': 'SLV', 'USO': 'USO', 'UNG': 'UNG',
    'CPER': 'CPER', 'PPLT': 'PPLT', 'PALL': 'PALL',
    # Crypto — BTC-USD/ETH-USD เป็น spot price อยู่แล้ว
    'BTC': 'BTC-USD', 'BITCOIN': 'BTC-USD', 'บิทคอยน์': 'BTC-USD', 'บิตคอยน์': 'BTC-USD',
    'ETH': 'ETH-USD', 'ETHEREUM': 'ETH-USD',
}


def _normalize_market_symbol(symbol):
    raw = str(symbol or "").strip()
    clean_symbol = raw.upper()
    # 🥇 Commodity/crypto aliases — เช่น "gold" → GLD, "oil" → USO, "btc" → BTC-USD
    if clean_symbol in _COMMODITY_ALIASES:
        return _COMMODITY_ALIASES[clean_symbol]
    if raw in _COMMODITY_ALIASES:  # ภาษาไทย (upper() ไม่กระทบ)
        return _COMMODITY_ALIASES[raw]
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
        'atr': _safe_float(latest.get('ATR')),
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

    fetch_specs = (
        ("1y", "1d"),
        ("5y", "1wk"),
        ("10y", "1mo"),
    )
    futures = [
        _yf_executor.submit(_fetch_history_cached, clean_symbol, period, interval, False)
        for period, interval in fetch_specs
    ]
    daily_data = futures[0].result()
    weekly_data = futures[1].result()
    monthly_data = futures[2].result()

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

            # 2. ดึงข้อมูลจริง 1 ปี (cached + thread-safe)
            data = _fetch_history_cached(clean_symbol, period="1y")

            # 🌟 Auto-fallback: ถ้าไม่มี suffix และหา US ไม่เจอ → ลอง .BK (หุ้นไทย)
            if data.empty and "." not in clean_symbol and "-" not in clean_symbol:
                fallback_symbol = f"{clean_symbol}.BK"
                fallback_data = _fetch_history_cached(fallback_symbol, period="1y")
                if not fallback_data.empty:
                    clean_symbol = fallback_symbol
                    data = fallback_data

            if data.empty:
                return None, None, (
                    f"🔎 ยังไม่พบข้อมูลหุ้น '{symbol}' ในระบบครับ\n\n"
                    f"💡 **ลองตรวจรูปแบบการพิมพ์ดังนี้:**\n"
                    f"• 🇺🇸 **อเมริกา:** พิมพ์ชื่อตรงๆ (เช่น `AAPL`)\n"
                    f"• 🇹🇭 **ไทย:** ต้องมี `.BK` ต่อท้าย (เช่น `PTT.BK`)\n"
                    f"• 🦘 **ออสเตรเลีย:** เติม `.AX` (เช่น `CBA.AX`)\n"
                    f"• 🇬🇧 **ลอนดอน:** เติม `.L` (เช่น `HSBA.L`)\n"
                    f"• 🇭🇰 **ฮ่องกง:** เติม `.HK` (เช่น `0700.HK`)\n"
                    f"• 🇯🇵 **ญี่ปุ่น:** เติม `.T` (เช่น `7203.T`)\n"
                    f"• 🥇 **โลหะ/น้ำมัน:** พิมพ์ `gold` `silver` `oil` `gas` `copper`\n"
                    f"• ₿ **คริปโต:** `btc` `eth`\n\n"
                    f"รบกวนตรวจตัวสะกดแล้วลองพิมพ์ใหม่อีกครั้งนะครับ ✨"
                )
            if len(data) < 20:
                return None, None, (
                    f"⏳ หุ้น '{clean_symbol}' มีข้อมูลย้อนหลังไม่เพียงพอสำหรับการวิเคราะห์\n"
                    f"_(อาจเป็นหุ้นที่เพิ่ง IPO — ระบบต้องใช้ข้อมูลอย่างน้อย 20 วัน)_\n"
                    f"ลองเลือกหุ้นตัวอื่นที่มีประวัติยาวกว่านี้ดูนะครับ"
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
                'atr': float(latest['ATR']) if pd.notna(latest.get('ATR')) else None,
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

                # 🌟 Light theme — match PRO chart palette so the brand feels consistent.
                # Teal/coral candle colors + white background + same EMA + level palette
                # as generate_pro_annotated_chart. PRO still differs by adding the Entry
                # zone shading + TP/SL annotations on top.
                mc = mpf.make_marketcolors(
                    up='#26a69a',        # teal — up bars
                    down='#ef5350',      # coral — down bars
                    edge='inherit',
                    wick={'up': '#26a69a', 'down': '#ef5350'},
                    volume={'up': '#26a69a', 'down': '#ef5350'},
                )
                s = mpf.make_mpf_style(
                    marketcolors=mc,
                    base_mpf_style='yahoo',
                    gridstyle='-',
                    gridcolor='#e0e0e0',
                    facecolor='white',
                    edgecolor='#333333',
                    figcolor='white',
                    rc={'font.size': 10, 'axes.labelcolor': '#333333', 'axes.edgecolor': '#cccccc'},
                )

                add_plots = [
                    mpf.make_addplot(data['EMA20'].tail(60), color='#1e88e5', width=1.5),   # blue — same as PRO
                    mpf.make_addplot(data['EMA50'].tail(60), color='#fb8c00', width=1.5),   # orange — same as PRO
                    mpf.make_addplot(data['EMA200'].tail(60), color='#8e24aa', width=1.5),  # purple — same as PRO
                ]

                chart_title = (
                    f"\nApexify Chart: {clean_symbol}\n"
                    f"EMA: 20(Blue) 50(Orange) 200(Purple) | Res(Red) Sup(Green) | POC(Orange)"
                )

                # Same level colors as PRO chart — darker on white bg for contrast.
                mpf.plot(
                    data.tail(60),
                    type='candle',
                    style=s,
                    title=chart_title,
                    volume=True,
                    panel_ratios=(4, 1),
                    addplot=add_plots,
                    hlines=dict(
                        hlines=[resistance, support, float(poc_price)],
                        colors=['#d32f2f', '#388e3c', '#ff9800'],  # red / green / orange (matches PRO)
                        linestyle=':',
                        linewidths=1.3,
                    ),
                    savefig=dict(fname=buf, dpi=100, bbox_inches='tight', pad_inches=0.1),
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
                f"📡 ข้อมูลหุ้น '{symbol}' ยังไม่พร้อมให้บริการในขณะนี้\n"
                f"_อาจเป็นเพราะตลาดปิด หรือเซิร์ฟเวอร์ข้อมูลกำลังอัปเดต_\n"
                f"รบกวนลองอีกครั้งใน 30 วินาทีนะครับ 🙏"
            )


def generate_pro_annotated_chart(symbol, plan):
    """กราฟ PRO เฉพาะ — Entry zone shaded + เส้น TP1/TP2/SL พร้อม label %
    Auto-scale Y-axis ให้ครอบทุกระดับ + dedupe เส้นซ้ำ (เช่น resistance=tp1)
    plan = dict มี keys: entry_low, entry_high, tp1, tp2, sl
    """
    try:
        clean_symbol = _normalize_market_symbol(symbol)
        data = _fetch_history_cached(clean_symbol, period="1y")

        if data.empty and "." not in clean_symbol and "-" not in clean_symbol:
            fallback_data = _fetch_history_cached(f"{clean_symbol}.BK", period="1y")
            if not fallback_data.empty:
                clean_symbol = f"{clean_symbol}.BK"
                data = fallback_data

        if data.empty or len(data) < 20:
            return None

        data = calculate_indicators(data)
        recent20 = data.tail(20)
        support = float(recent20['Low'].min())
        resistance = float(recent20['High'].max())
        recent60 = data.tail(60)
        price_bins = pd.cut(recent60['Close'], bins=10)
        vol_profile = recent60.groupby(price_bins, observed=False)['Volume'].sum()
        poc_price = float(vol_profile.idxmax().mid)
        current_price = float(recent60['Close'].iloc[-1])

        mpf = _load_chart_modules()
        import matplotlib.pyplot as plt
        buf = io.BytesIO()

        # 🌟 Light theme — พื้นขาว แท่งเขียว/แดง mute (แบบ Bloomberg/TradingView light)
        mc = mpf.make_marketcolors(
            up='#26a69a',        # เขียวเทอร์ควอยซ์ (ขึ้น)
            down='#ef5350',      # แดง coral (ลง)
            edge='inherit',
            wick={'up': '#26a69a', 'down': '#ef5350'},
            volume={'up': '#26a69a', 'down': '#ef5350'},
        )
        s = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style='yahoo',
            gridstyle='-',
            gridcolor='#e0e0e0',
            facecolor='white',
            edgecolor='#333333',
            figcolor='white',
            rc={'font.size': 10, 'axes.labelcolor': '#333333', 'axes.edgecolor': '#cccccc'},
        )

        add_plots = [
            mpf.make_addplot(data['EMA20'].tail(60), color='#1e88e5', width=1.5),   # blue
            mpf.make_addplot(data['EMA50'].tail(60), color='#fb8c00', width=1.5),   # orange
            mpf.make_addplot(data['EMA200'].tail(60), color='#8e24aa', width=1.5),  # purple
        ]

        entry_low = _safe_chart_float(plan.get('entry_low'))
        entry_high = _safe_chart_float(plan.get('entry_high'))
        tp1 = _safe_chart_float(plan.get('tp1'))
        tp2 = _safe_chart_float(plan.get('tp2'))
        sl = _safe_chart_float(plan.get('sl'))

        # 🌟 Dedupe: ถ้า resistance ใกล้ tp1 / support ใกล้ sl → ไม่ต้องวาด
        dedupe_threshold = current_price * 0.005  # 0.5%
        show_resistance = tp1 is None or abs(resistance - tp1) > dedupe_threshold
        show_support = sl is None or abs(support - sl) > dedupe_threshold

        # 🌟 รวม hlines — สีโทนเข้มให้ contrast กับพื้นขาว
        hline_values = []
        hline_colors = []
        hline_styles = []
        if show_resistance:
            hline_values.append(resistance)
            hline_colors.append('#d32f2f')  # แดงซีด — แนวต้าน
            hline_styles.append(':')
        if show_support:
            hline_values.append(support)
            hline_colors.append('#388e3c')  # เขียวซีด — แนวรับ
            hline_styles.append(':')
        # POC — ส้มเด่นบนพื้นขาว
        if entry_low is None or entry_high is None or not (min(entry_low, entry_high) <= poc_price <= max(entry_low, entry_high)):
            hline_values.append(poc_price)
            hline_colors.append('#ff9800')  # ส้ม
            hline_styles.append(':')
        if tp1 is not None:
            hline_values.append(tp1)
            hline_colors.append('#2e7d32')  # เขียวเข้ม
            hline_styles.append('--')
        if tp2 is not None:
            hline_values.append(tp2)
            hline_colors.append('#1b5e20')  # เขียวเข้มกว่า TP1
            hline_styles.append('-')
        if sl is not None:
            hline_values.append(sl)
            hline_colors.append('#c62828')  # แดงเข้ม
            hline_styles.append('-')

        fill_between_dict = None
        if entry_low is not None and entry_high is not None:
            ordered = sorted([entry_low, entry_high])
            fill_between_dict = dict(y1=ordered[0], y2=ordered[1], alpha=0.2, color='#4caf50')

        chart_title = (
            f"\nApexify PRO — {clean_symbol}  |  Entry Zone + TP + SL Plan\n"
            f"EMA: 20(Blue) 50(Orange) 200(Purple)"
        )

        # 🌟 คำนวณ Y-axis range ให้ครอบทุกระดับ + padding
        all_levels = [resistance, support, poc_price]
        for v in (entry_low, entry_high, tp1, tp2, sl):
            if v is not None:
                all_levels.append(v)
        data_min = float(recent60['Low'].min())
        data_max = float(recent60['High'].max())
        y_min = min(min(all_levels), data_min) * 0.96
        y_max = max(max(all_levels), data_max) * 1.04

        plot_kwargs = dict(
            type='candle',
            style=s,
            title=chart_title,
            volume=True,
            panel_ratios=(4, 1),
            addplot=add_plots,
            hlines=dict(hlines=hline_values, colors=hline_colors, linestyle=hline_styles, linewidths=1.3),
            figratio=(16, 9),
            figscale=1.2,
            tight_layout=True,
            ylim=(y_min, y_max),
            returnfig=True,
        )
        if fill_between_dict is not None:
            plot_kwargs['fill_between'] = fill_between_dict

        fig, axes = mpf.plot(recent60, **plot_kwargs)
        ax = axes[0]  # main price panel

        # 🌟 ใส่ label ภายในกราฟด้านซ้าย (กัน clip จาก bbox_inches='tight')
        import matplotlib.transforms as mtransforms
        trans = mtransforms.blended_transform_factory(ax.transAxes, ax.transData)
        x_label = 0.02  # ซ้ายสุดของ axes (2% จากซ้าย)

        def add_label(price, text, fc='#2e7d32'):
            """Label bbox สีเต็ม ตัวหนังสือขาว (contrast สูงบนพื้นขาว)"""
            if price is None:
                return
            pct = (price - current_price) / current_price * 100
            label = f' {text} ${price:,.2f} ({pct:+.1f}%) '
            ax.text(
                x_label, price, label,
                transform=trans,
                color='#ffffff', fontsize=10, fontweight='bold',
                va='center', ha='left',
                bbox=dict(boxstyle='round,pad=0.35', fc=fc, ec=fc, lw=0),
                zorder=10,
            )

        add_label(tp2, '🎯 TP2', fc='#1b5e20')       # เขียวเข้มสุด
        add_label(tp1, '🎯 TP1', fc='#2e7d32')       # เขียวเข้ม
        if entry_low is not None and entry_high is not None:
            entry_mid = (entry_low + entry_high) / 2
            pct = (entry_mid - current_price) / current_price * 100
            ax.text(
                x_label, entry_mid,
                f' 📍 ENTRY ${entry_low:,.2f}–${entry_high:,.2f} ({pct:+.1f}%) ',
                transform=trans,
                color='#ffffff', fontsize=10, fontweight='bold',
                va='center', ha='left',
                bbox=dict(boxstyle='round,pad=0.35', fc='#00796b', ec='#00796b', lw=0),
                zorder=10,
            )
        add_label(sl, '🛑 SL', fc='#c62828')          # แดงเข้ม
        # 🌟 NOW marker — น้ำเงิน
        ax.text(
            x_label, current_price, f' ▶ NOW ${current_price:,.2f} ',
            transform=trans,
            color='#ffffff', fontsize=10, fontweight='bold',
            va='center', ha='left',
            bbox=dict(boxstyle='round,pad=0.35', fc='#1565c0', ec='#1565c0', lw=0),
            zorder=10,
        )

        fig.savefig(buf, dpi=100, bbox_inches='tight', pad_inches=0.15, facecolor='white')
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"[ProChart] {symbol} failed: {e}", flush=True)
        return None


def _safe_chart_float(value):
    try:
        result = float(value)
        if pd.isna(result) or not result:
            return None
        return result
    except (TypeError, ValueError):
        return None
