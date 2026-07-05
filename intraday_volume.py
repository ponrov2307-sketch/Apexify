"""Intraday volume spike detection — แทน daily-volume whale check ที่สายเป็นชั่วโมง

ปัญหาของแบบเก่า (alert_system.py:587):
- ใช้ candle "รายวัน" — volume สะสมเรื่อยๆ ทั้งวัน
- กว่าจะถึง 3x avg 20 วัน ก็ใกล้ปิดตลาด → alert สาย 5-6 ชม.

แบบใหม่:
- ใช้ candle 5 นาที (intraday)
- เทียบ candle ล่าสุดกับ avg ของ 12 candle ผ่านมา (1 ชม.)
- detect spike ภายใน 5-10 นาที หลังเกิดจริง

หมายเหตุ:
- yfinance 5m data ย้อนได้ 60 วัน (เพียงพอ)
- รองรับเฉพาะตลาดที่ yfinance ให้ intraday (US/TH/UK/HK/JP/AU)
- ถ้า session ปิด → คืน None (caller ข้าม alert)
"""

from datetime import datetime, time as dtime, timezone
from threading import RLock
from zoneinfo import ZoneInfo

import pandas as pd
from cachetools import TTLCache

try:
    import yfinance as yf
except Exception:
    yf = None


_INTRADAY_CACHE = TTLCache(maxsize=200, ttl=90)  # 90 วิ — ให้สดพอควรแต่ไม่ rate-limit
_CACHE_LOCK = RLock()


# ===== Market session schedule =====
# (timezone, suffix tuple, open_time, close_time, weekdays_open)
# weekday: Monday=0 ... Sunday=6
_MARKETS = [
    # US — NYSE/Nasdaq (handles DST อัตโนมัติผ่าน America/New_York)
    {
        "name": "US",
        "tz": "America/New_York",
        "suffixes": ("",),  # plain ticker = US
        "open": dtime(9, 30),
        "close": dtime(16, 0),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # ไทย SET — split session, รวมเป็น 10:00-16:30 (ไม่เปิด-ปิดต้นเที่ยงเพื่อความง่าย)
    {
        "name": "TH",
        "tz": "Asia/Bangkok",
        "suffixes": (".BK", ".bk"),
        "open": dtime(10, 0),
        "close": dtime(16, 30),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # London
    {
        "name": "UK",
        "tz": "Europe/London",
        "suffixes": (".L", ".l"),
        "open": dtime(8, 0),
        "close": dtime(16, 30),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # Hong Kong
    {
        "name": "HK",
        "tz": "Asia/Hong_Kong",
        "suffixes": (".HK", ".hk"),
        "open": dtime(9, 30),
        "close": dtime(16, 0),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # Tokyo
    {
        "name": "JP",
        "tz": "Asia/Tokyo",
        "suffixes": (".T", ".t"),
        "open": dtime(9, 0),
        "close": dtime(15, 30),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # Sydney
    {
        "name": "AU",
        "tz": "Australia/Sydney",
        "suffixes": (".AX", ".ax"),
        "open": dtime(10, 0),
        "close": dtime(16, 0),
        "weekdays": (0, 1, 2, 3, 4),
    },
    # Crypto — เปิดตลอด
    {
        "name": "CRYPTO",
        "tz": "UTC",
        "suffixes": ("-USD", "-usd"),
        "open": dtime(0, 0),
        "close": dtime(23, 59),
        "weekdays": (0, 1, 2, 3, 4, 5, 6),
    },
]


def _resolve_market(symbol):
    """หา market ของ symbol ตาม suffix; default = US"""
    if not symbol:
        return _MARKETS[0]
    s = symbol.strip()
    for m in _MARKETS:
        for sfx in m["suffixes"]:
            if sfx and s.endswith(sfx):
                return m
    # ไม่ตรง suffix → US
    return _MARKETS[0]


def _is_candle_fresh(symbol, candle_ts):
    """เช็คว่าแท่งเทียนเป็นของ 'วันนี้' จริงในเขตเวลาตลาดนั้นๆ

    กัน stale candle: ตอนตลาดปิด (วันหยุดที่ is_market_open ไม่รู้จัก เพราะเช็คแค่
    weekday+เวลา ไม่มีปฏิทินวันหยุด, หรือ yfinance data lag) yfinance จะคืนแท่งปิดตลาด
    ของวันทำการก่อนหน้ามาแทน — ถ้าไม่เช็ค วันที่ ของแท่งนั้นจะถูกเข้าใจผิดว่าเป็นแท่งสดใหม่
    (ดู detect_gap_open ที่เช็คแบบนี้อยู่แล้ว — ฟังก์ชันนี้ generalize ให้ใช้ร่วมกัน)
    """
    if candle_ts is None:
        return False
    market = _resolve_market(symbol)
    tz = ZoneInfo(market["tz"])
    today_local = datetime.now(timezone.utc).astimezone(tz).date()
    try:
        candle_date = candle_ts.tz_convert(tz).date() if hasattr(candle_ts, "tz_convert") else None
    except Exception:
        candle_date = None
    return candle_date is not None and candle_date == today_local


def is_market_open(symbol, now_utc=None):
    """เช็คว่าตลาดของ symbol นี้กำลังเปิดอยู่ไหม"""
    market = _resolve_market(symbol)
    tz = ZoneInfo(market["tz"])
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    if now_local.weekday() not in market["weekdays"]:
        return False
    t = now_local.time()
    return market["open"] <= t <= market["close"]


def time_since_session_open(symbol, now_utc=None):
    """คืนวินาทีตั้งแต่ session ของ symbol เปิด หรือ None ถ้าตลาดยังไม่เปิด/ปิดแล้ว
    ใช้เช็ค "อยู่ในช่วง 30 นาทีแรก" สำหรับ gap detection
    """
    market = _resolve_market(symbol)
    tz = ZoneInfo(market["tz"])
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    if now_local.weekday() not in market["weekdays"]:
        return None
    t = now_local.time()
    if t < market["open"] or t > market["close"]:
        return None
    open_dt = now_local.replace(
        hour=market["open"].hour,
        minute=market["open"].minute,
        second=0,
        microsecond=0,
    )
    return int((now_local - open_dt).total_seconds())


def _fetch_intraday_5m(symbol):
    """ดึง 5m bars 5 วันล่าสุดผ่าน yf — cached 90 วิ
    คืน DataFrame หรือ None ถ้า fetch ไม่ได้
    """
    if yf is None:
        return None
    key = symbol.strip().upper()
    if not key:
        return None

    with _CACHE_LOCK:
        cached = _INTRADAY_CACHE.get(key)
        if cached is not None:
            return cached.copy()

    try:
        df = yf.Ticker(symbol).history(period="5d", interval="5m", auto_adjust=False)
    except Exception as e:
        print(f"[intraday] yf err {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return None

    if df is None or df.empty:
        return None

    with _CACHE_LOCK:
        _INTRADAY_CACHE[key] = df.copy()
    return df


def detect_volume_spike(symbol, threshold=3.0, lookback_bars=12, min_history=20):
    """ตรวจ intraday volume spike

    Args:
        symbol: ticker
        threshold: spike = current_vol > avg * threshold (default 3x)
        lookback_bars: จำนวน 5m candle ใช้คำนวณ avg (default 12 = 1 ชม.)
        min_history: จำนวน candle ขั้นต่ำใน lookback ก่อนตัดสินใจ

    Returns:
        dict {
            "spike": bool,
            "ratio": float,
            "current_volume": float,
            "avg_volume": float,
            "current_close": float,
            "current_open": float,
            "candle_time": pd.Timestamp,
            "session_open": bool,
            "reason": str,  # ถ้า spike=False อธิบาย
        }
        หรือ None ถ้า fetch ล้มเหลว
    """
    if not is_market_open(symbol):
        return {
            "spike": False, "ratio": 0.0,
            "current_volume": 0.0, "avg_volume": 0.0,
            "current_close": 0.0, "current_open": 0.0,
            "candle_time": None, "session_open": False,
            "reason": "session_closed",
        }

    df = _fetch_intraday_5m(symbol)
    if df is None or df.empty:
        return None

    # 5m bars: ใช้แค่ candle ที่ "ปิดแล้ว" (drop candle สุดท้ายที่อาจเป็น partial)
    # หมายเหตุ: yfinance อาจส่งคืน partial candle ของช่วงเวลาปัจจุบัน — ตัดทิ้งเพื่อกัน false-positive
    if len(df) < min_history + 2:
        return {
            "spike": False, "ratio": 0.0,
            "current_volume": 0.0, "avg_volume": 0.0,
            "current_close": 0.0, "current_open": 0.0,
            "candle_time": None, "session_open": True,
            "reason": "insufficient_history",
        }

    # ถ้า candle ตัวสุดท้ายเป็น partial (เวลาปัจจุบัน) ใช้ตัวก่อนหน้าเป็น "current"
    # ตรวจอย่างหยาบ: candle "เพิ่งเปิด" = volume น้อยมาก / เวลายังไม่ครบ 5m
    completed = df.iloc[:-1]  # ทิ้งแคนเดิลที่อาจ partial (ปลอดภัยสุด)
    if len(completed) < min_history + 1:
        completed = df  # fallback ใช้ทั้งหมดถ้าตัดทิ้งแล้วเหลือน้อย

    current = completed.iloc[-1]

    if not _is_candle_fresh(symbol, current.name if hasattr(current, "name") else None):
        return {
            "spike": False, "ratio": 0.0,
            "current_volume": 0.0, "avg_volume": 0.0,
            "current_close": 0.0, "current_open": 0.0,
            "candle_time": None, "session_open": True,
            "reason": "stale_candle",
        }

    history = completed.iloc[-(lookback_bars + 1):-1]  # candle ก่อนหน้า lookback ตัว
    if len(history) < min_history // 2:
        # lookback ไม่พอ — ลองใช้ทั้งหมดที่มี
        history = completed.iloc[:-1]

    if len(history) == 0:
        return {
            "spike": False, "ratio": 0.0,
            "current_volume": float(current.get("Volume", 0)),
            "avg_volume": 0.0,
            "current_close": float(current.get("Close", 0)),
            "current_open": float(current.get("Open", 0)),
            "candle_time": current.name if hasattr(current, "name") else None,
            "session_open": True,
            "reason": "no_history",
        }

    avg_vol = float(history["Volume"].mean())
    cur_vol = float(current["Volume"])
    ratio = (cur_vol / avg_vol) if avg_vol > 0 else 0.0

    spike = ratio >= threshold and cur_vol > 0 and avg_vol > 0

    return {
        "spike": spike,
        "ratio": ratio,
        "current_volume": cur_vol,
        "avg_volume": avg_vol,
        "current_close": float(current["Close"]),
        "current_open": float(current["Open"]),
        "candle_time": current.name if hasattr(current, "name") else None,
        "session_open": True,
        "reason": "ok",
    }


def detect_breakout_intraday(symbol, daily_resistance, daily_support, vol_confirm_ratio=1.5):
    """ตรวจ breakout ด้วย 5m bar — close ทะลุ daily S/R พร้อม volume ยืนยัน

    เปลี่ยนจาก "daily close > daily resistance" (สาย) เป็น "intraday 5m close > daily resistance"
    เพิ่ม volume confirm เพื่อกัน false breakout ตอน thin liquidity

    Args:
        daily_resistance: max 20-day high (จาก technical_tools.calculate_technical_indicators)
        daily_support: min 20-day low
        vol_confirm_ratio: minimum vol ratio of breakout candle vs prev 12 candles

    Returns: dict {direction: 'up'/'down'/None, ratio, ...} หรือ None ถ้าตลาดปิด/ดึงไม่ได้
    """
    if not is_market_open(symbol):
        return None
    df = _fetch_intraday_5m(symbol)
    if df is None or df.empty or len(df) < 14:
        return None

    completed = df.iloc[:-1] if len(df) > 13 else df
    if len(completed) < 13:
        return None

    current = completed.iloc[-1]

    if not _is_candle_fresh(symbol, current.name if hasattr(current, "name") else None):
        return None

    cur_close = float(current["Close"])
    cur_vol = float(current["Volume"])

    history = completed.iloc[-13:-1]
    history_vol = float(history["Volume"].mean()) if len(history) > 0 else 0.0
    vol_ratio = (cur_vol / history_vol) if history_vol > 0 else 0.0

    direction = None
    breakout_level = None
    if daily_resistance and daily_resistance > 0 and cur_close > daily_resistance:
        direction = "up"
        breakout_level = daily_resistance
    elif daily_support and daily_support > 0 and cur_close < daily_support:
        direction = "down"
        breakout_level = daily_support

    confirmed = direction is not None and vol_ratio >= vol_confirm_ratio

    return {
        "direction": direction if confirmed else None,
        "raw_direction": direction,  # ทะลุแต่ vol ไม่ confirm — บันทึก info
        "vol_confirmed": confirmed,
        "vol_ratio": vol_ratio,
        "current_close": cur_close,
        "current_open": float(current["Open"]),
        "breakout_level": breakout_level,
        "candle_time": current.name if hasattr(current, "name") else None,
        "session_open": True,
    }


def detect_gap_open(symbol, prev_close, threshold_pct=2.0, window_seconds=1800):
    """ตรวจ gap ตอนเปิดตลาด — เฉพาะใน 30 นาทีแรกของ session

    Args:
        prev_close: ราคาปิดเมื่อวาน (จาก daily data)
        threshold_pct: |gap%| ขั้นต่ำที่จะ alert (default 2%)
        window_seconds: alert ได้แค่ใน N วินาทีแรก (default 1800 = 30 min)

    Returns: dict {direction, gap_pct, open_price, prev_close} หรือ None
    """
    if not prev_close or prev_close <= 0:
        return None
    secs = time_since_session_open(symbol)
    if secs is None or secs > window_seconds:
        return None

    df = _fetch_intraday_5m(symbol)
    if df is None or df.empty:
        return None

    market = _resolve_market(symbol)
    tz = ZoneInfo(market["tz"])
    today_local = datetime.now(timezone.utc).astimezone(tz).date()
    try:
        index_dates = df.index.tz_convert(tz).date if hasattr(df.index, "tz_convert") else None
    except Exception:
        index_dates = None
    today_bars = df[index_dates == today_local] if index_dates is not None else df.iloc[-min(6, len(df)):]
    if len(today_bars) == 0:
        return None

    open_bar = today_bars.iloc[0]
    open_price = float(open_bar["Open"])
    if open_price <= 0:
        return None

    gap_pct = (open_price - prev_close) / prev_close * 100
    if abs(gap_pct) < threshold_pct:
        return None

    return {
        "direction": "up" if gap_pct > 0 else "down",
        "gap_pct": gap_pct,
        "open_price": open_price,
        "prev_close": float(prev_close),
        "session_seconds": secs,
    }


def detect_price_acceleration(symbol, lookback_bars=6, threshold_pct=3.0, vol_confirm=1.2):
    """ตรวจ momentum spike — ราคาเคลื่อนเร็วเกินปกติใน 30 นาที (6 candle 5m)

    Args:
        lookback_bars: candle 5m ใช้คำนวณ (default 6 = 30 นาที)
        threshold_pct: |%change| ขั้นต่ำที่จะ alert
        vol_confirm: avg vol ของ window vs avg vol ของ 4x window prior

    Returns: dict {direction, change_pct, ...} หรือ None
    """
    if not is_market_open(symbol):
        return None
    df = _fetch_intraday_5m(symbol)
    if df is None or df.empty or len(df) < lookback_bars + 2:
        return None

    completed = df.iloc[:-1]
    if len(completed) < lookback_bars + 1:
        return None

    window = completed.iloc[-lookback_bars:]
    start_price = float(window.iloc[0]["Open"])
    end_price = float(window.iloc[-1]["Close"])
    if start_price <= 0:
        return None

    change_pct = (end_price - start_price) / start_price * 100
    if abs(change_pct) < threshold_pct:
        return None

    avg_vol_window = float(window["Volume"].mean())
    prior_size = lookback_bars * 4
    if len(completed) >= prior_size + lookback_bars:
        prior_vol = float(completed.iloc[-(prior_size + lookback_bars):-lookback_bars]["Volume"].mean())
    else:
        prior_vol = avg_vol_window
    vol_ratio = (avg_vol_window / prior_vol) if prior_vol > 0 else 1.0

    confirmed = vol_ratio >= vol_confirm

    return {
        "direction": "up" if change_pct > 0 else "down",
        "change_pct": change_pct,
        "start_price": start_price,
        "end_price": end_price,
        "minutes": lookback_bars * 5,
        "vol_ratio": vol_ratio,
        "vol_confirmed": confirmed,
        "session_open": True,
    }
