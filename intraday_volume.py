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


def is_market_open(symbol, now_utc=None):
    """เช็คว่าตลาดของ symbol นี้กำลังเปิดอยู่ไหม"""
    market = _resolve_market(symbol)
    tz = ZoneInfo(market["tz"])
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    if now_local.weekday() not in market["weekdays"]:
        return False
    t = now_local.time()
    return market["open"] <= t <= market["close"]


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
