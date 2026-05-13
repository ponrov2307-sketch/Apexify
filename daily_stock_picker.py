"""
daily_stock_picker.py — ทุกเช้า 7:30 ICT DM admin: 3 หุ้นน่าโพสต์วันนี้

User feedback:
  - mix Mag 7 + S&P 500 + story stocks (ไม่ใช่แค่หุ้นใหญ่ๆ)
  - chart image แนบให้ (chart เดียวกับ Apexify วิเคราะห์ปกติ)
  - ข่าว = "ข่าวล่าสุดสดๆ" (≤48h) เพื่อให้ admin เอาไปทำ content คนติดตามได้

Workflow:
  1. Combine 3 pools: Mag 7 + S&P 500 + story stocks (~70 ตัว)
  2. Score by composite (move% + vol + conviction + fresh news + variety)
  3. Pick top 3 with sector diversity (ไม่ซ้ำ category เดียว)
  4. DM ADMIN_ID — text (symbol + reasons + hook + fresh news) + chart image แต่ละ pick
"""

import time
import threading
import random
from datetime import datetime, timedelta, timezone


import config


# ============ Pool — 3 tiers mixed ============

MAG_7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]

# Story stocks — ซิ่ง + สตอรี่ + คนไทยชอบ
STORY_STOCKS = [
    # Space
    "RKLB", "ASTS", "IRDM", "PL",
    # Quantum
    "IONQ", "RGTI", "QBTS", "ARQQ",
    # AI plays
    "PLTR", "AI", "SOUN", "BBAI", "BIG", "NBIS",
    # EV / Auto
    "RIVN", "LCID", "NIO", "XPEV",
    # Crypto-linked
    "COIN", "MSTR", "MARA", "RIOT", "HOOD",
    # Biotech / Genomics
    "RXRX", "RGNX", "EXAS", "SAVA",
    # Meme / Retail
    "GME", "BB", "SOFI", "KOSS",
    # High-beta momentum
    "SMCI", "ARM", "AVGO", "MU", "AMD",
    # Fintech
    "NU", "UPST", "AFRM", "PYPL",
    # Defense AI
    "KTOS", "AVAV",
]

# S&P 500 large/mid cap (subset — variety)
SP500_VARIETY = [
    "NFLX", "DIS", "BA", "JPM", "V", "MA", "WMT", "PG", "JNJ", "UNH",
    "LLY", "XOM", "CVX", "HD", "COST", "ABBV", "MRK", "PFE", "BAC", "CRM",
    "ORCL", "ADBE", "INTC", "QCOM", "T", "VZ", "TMUS", "GS", "MS", "C",
]

# 🆕 2026-05-13 — Small cap day trade favorites
# Customer PP P. feedback: "เทรดรายวันส่วนมากเป็น small cap ค่ะ คละๆกันมาก็ได้"
# หุ้นที่ Thai day trader ติดตามจริงๆ ใน 2025-2026 — % move แรงกว่า mega cap
SMALL_CAP_DAYTRADE = [
    # AI / Software small ($300M-$5B)
    "TEM", "HOLO", "LAES", "GFAI", "SERV", "KSCP",
    # Quantum small (RGTI/QBTS/ARQQ มีแล้วใน STORY_STOCKS)
    "QUBT",
    # Space small (RKLB/ASTS/IRDM/PL มีแล้ว)
    "BKSY", "SPIR",
    # Crypto mining (picks-and-shovels — different vibe จาก COIN/MSTR)
    "BTBT", "BTDR", "CIFR", "IREN", "WULF", "HUT", "CLSK",
    # AI Power / Nuclear (hot 2025-2026)
    "OKLO", "SMR", "LEU",
    # Critical Minerals / Rare earth
    "USAR", "MP",
    # eVTOL / Air mobility
    "ACHR", "JOBY",
    # EV small (RIVN/LCID/NIO/XPEV มีแล้ว)
    "GOEV", "WKHS",
    # Defense / Drone (KTOS/AVAV มีแล้ว)
    "ONDS",
    # Biotech catalyst (RXRX/RGNX/EXAS/SAVA มีแล้ว)
    "NVAX", "VKTX",
    # Political / meme
    "DJT",
    # Fintech small (UPST/AFRM/PYPL มีแล้ว)
    "DAVE",
    # Real estate tech
    "OPEN",
]

# Sector tag — เพื่อ variety enforce (ไม่ pick 3 ตัวจาก sector เดียวกัน)
SECTOR_TAG = {
    # Mag 7
    **{s: "tech_mega" for s in MAG_7},
    # Sector tags for story stocks
    "RKLB": "space", "ASTS": "space", "IRDM": "space", "PL": "space",
    "IONQ": "quantum", "RGTI": "quantum", "QBTS": "quantum", "ARQQ": "quantum",
    "PLTR": "ai", "AI": "ai", "SOUN": "ai", "BBAI": "ai", "BIG": "ai", "NBIS": "ai",
    "RIVN": "ev", "LCID": "ev", "NIO": "ev", "XPEV": "ev",
    "COIN": "crypto", "MSTR": "crypto", "MARA": "crypto", "RIOT": "crypto", "HOOD": "crypto",
    "RXRX": "biotech", "RGNX": "biotech", "EXAS": "biotech", "SAVA": "biotech",
    "GME": "meme", "BB": "meme", "SOFI": "meme", "KOSS": "meme",
    "SMCI": "semi", "ARM": "semi", "AVGO": "semi", "MU": "semi", "AMD": "semi",
    "NU": "fintech", "UPST": "fintech", "AFRM": "fintech", "PYPL": "fintech",
    "KTOS": "defense", "AVAV": "defense",
    # S&P 500 misc
    "NFLX": "tech", "DIS": "media", "BA": "industrial", "JPM": "finance", "V": "finance",
    "MA": "finance", "WMT": "retail", "PG": "consumer", "JNJ": "healthcare", "UNH": "healthcare",
    "LLY": "healthcare", "XOM": "energy", "CVX": "energy", "HD": "retail", "COST": "retail",
    "ABBV": "healthcare", "MRK": "healthcare", "PFE": "healthcare", "BAC": "finance", "CRM": "tech",
    "ORCL": "tech", "ADBE": "tech", "INTC": "semi", "QCOM": "semi",
    "T": "telecom", "VZ": "telecom", "TMUS": "telecom",
    "GS": "finance", "MS": "finance", "C": "finance",
    # 🆕 Small cap tags
    "TEM": "ai", "HOLO": "ai", "LAES": "ai", "GFAI": "ai", "SERV": "ai", "KSCP": "ai",
    "QUBT": "quantum",
    "BKSY": "space", "SPIR": "space",
    "BTBT": "mining", "BTDR": "mining", "CIFR": "mining", "IREN": "mining",
    "WULF": "mining", "HUT": "mining", "CLSK": "mining",
    "OKLO": "power", "SMR": "power", "LEU": "power",
    "USAR": "materials", "MP": "materials",
    "ACHR": "evtol", "JOBY": "evtol",
    "GOEV": "ev", "WKHS": "ev",
    "ONDS": "defense",
    "NVAX": "biotech", "VKTX": "biotech",
    "DJT": "meme",
    "DAVE": "fintech",
    "OPEN": "retech",
}

ALL_POOL = list(set(MAG_7 + STORY_STOCKS + SP500_VARIETY + SMALL_CAP_DAYTRADE))


def _is_small_cap(symbol: str) -> bool:
    """ลูกค้า PP P. feedback: ขอ small cap ด้วย — flag เพื่อใส่ warning ใน DM"""
    return symbol in SMALL_CAP_DAYTRADE


# ============ Suggested hook templates ============
# แยก bullish (positive move) / bearish (negative move) context
HOOK_TEMPLATES_BULL = {
    "tech_mega":  [
        "{sym} {move:+.1f}% วันนี้ — ตลาดเริ่มเทใส่ Mag 7 อีกครั้ง?",
        "{sym} หลังตลาด {move:+.1f}% — เทรนด์ระยะยาวยังเขียวอยู่?",
        "{sym} {move:+.1f}% — earnings/guidance อะไรขับ?",
    ],
    "story":      [
        "{sym} {move:+.1f}% — สตอรี่นี้ตื่นแล้วใช่ไหม?",
        "ทำไม {sym} วิ่ง {move:+.1f}% เมื่อคืน?",
        "{sym} {move:+.1f}% — หุ้นที่ไม่ค่อยมีใครพูดถึงแต่กำลังวิ่ง",
    ],
    "quantum":    [
        "{sym} {move:+.1f}% — Quantum Computing ตื่นจริงหรือ pump?",
        "{sym} วิ่งทะลุแนวต้าน — quantum hype ยังไม่จบ",
    ],
    "space":      [
        "{sym} {move:+.1f}% — Space stocks กลับมามีคนสนใจ",
        "{sym} หุ้นดาวเทียมที่นักลงทุนเริ่มจับตา",
        "{sym} {move:+.1f}% — contract ใหม่/launch มาแล้ว?",
    ],
    "ai":         [
        "{sym} {move:+.1f}% — AI hype play ที่ยังไม่ peak?",
        "{sym} — AI software ที่อาจ underrated",
        "{sym} {move:+.1f}% — picks-and-shovels ของ AI cycle",
    ],
    "ev":         [
        "{sym} {move:+.1f}% — EV recovery หรือ trap?",
        "{sym} {move:+.1f}% — delivery numbers ออกมาแล้วเป็นยังไง?",
    ],
    "crypto":     [
        "{sym} {move:+.1f}% — crypto correlation play",
        "{sym} วิ่งตาม BTC {move:+.1f}%",
        "{sym} {move:+.1f}% — เมื่อ crypto market green",
    ],
    "biotech":    [
        "{sym} {move:+.1f}% — biotech catalyst ที่ห้ามพลาด?",
        "{sym} {move:+.1f}% — FDA/trial readout รออะไร?",
    ],
    "semi":       [
        "{sym} {move:+.1f}% — chip cycle ยังไม่จบ",
        "{sym} {move:+.1f}% — AI demand spillover ลง semi",
    ],
    "fintech":    [
        "{sym} {move:+.1f}% — fintech ที่ Apexify เห็น setup ดี",
        "{sym} {move:+.1f}% — credit cycle + earnings catalyst",
    ],
    # 🆕 Small cap sectors
    "mining":     [
        "{sym} {move:+.1f}% — BTC ขึ้น mining stocks วิ่งตาม",
        "{sym} {move:+.1f}% — picks-and-shovels ของ crypto bull run",
        "{sym} {move:+.1f}% — hash rate + difficulty คุ้มขุดอีกแล้ว?",
    ],
    "power":      [
        "{sym} {move:+.1f}% — AI data center ต้องการพลังงาน nuclear?",
        "{sym} {move:+.1f}% — SMR/Microreactor cycle เริ่ม momentum",
        "{sym} {move:+.1f}% — Trump nuclear push ดันเชื้อเพลิงสะอาด",
    ],
    "evtol":      [
        "{sym} {move:+.1f}% — eVTOL กำลังจะ commercial launch?",
        "{sym} {move:+.1f}% — air mobility ที่ห้าม sleep on",
    ],
    "materials":  [
        "{sym} {move:+.1f}% — rare earth supply chain reshore?",
        "{sym} {move:+.1f}% — critical minerals policy push",
    ],
    "retech":     [
        "{sym} {move:+.1f}% — real estate tech ฟื้นพร้อมดอกเบี้ยลง?",
    ],
    "meme":       [
        "{sym} {move:+.1f}% — retail crowd กลับมา?",
        "{sym} วิ่ง {move:+.1f}% — social sentiment เปลี่ยน",
    ],
    "defense":    [
        "{sym} {move:+.1f}% — defense tech ที่กำลังเร่ง contract",
        "{sym} {move:+.1f}% — drone/AI defense play",
    ],
}

HOOK_TEMPLATES_BEAR = {
    "tech_mega":  [
        "{sym} {move:+.1f}% — Mag 7 เริ่มหายร้อน?",
        "{sym} ร่วง {move:+.1f}% — โอกาส buy the dip?",
        "{sym} {move:+.1f}% — rotation ออกจาก tech?",
    ],
    "story":      [
        "{sym} {move:+.1f}% — สตอรี่จบแล้วหรือยังไม่เริ่ม?",
        "{sym} ลง {move:+.1f}% — มี catalyst negative อะไร?",
        "{sym} {move:+.1f}% — pullback ก่อนวิ่งรอบใหม่?",
    ],
    "quantum":    [
        "{sym} {move:+.1f}% — Quantum hype เริ่มจาง?",
        "{sym} ลงจากแนวต้าน — รอ confirmation",
    ],
    "space":      [
        "{sym} {move:+.1f}% — Space stocks เจอแรงขาย",
        "{sym} ลง {move:+.1f}% — guidance/earnings มีอะไร?",
    ],
    "ai":         [
        "{sym} {move:+.1f}% — AI sector หยุดพัก",
        "{sym} ลงทั้งที่ fundamental ยังดี — โอกาสเข้า?",
    ],
    "ev":         [
        "{sym} {move:+.1f}% — EV cycle ยังไม่ฟื้น",
        "{sym} {move:+.1f}% — demand จีน/EU กระทบ?",
    ],
    "crypto":     [
        "{sym} {move:+.1f}% — crypto sell-off กระทบ",
        "{sym} ร่วง {move:+.1f}% — BTC พังลงด้วย",
    ],
    "biotech":    [
        "{sym} {move:+.1f}% — biotech รอ catalyst ถัดไป",
        "{sym} {move:+.1f}% — trial fail/delay?",
    ],
    "semi":       [
        "{sym} {move:+.1f}% — chip cycle เริ่ม cool down",
        "{sym} {move:+.1f}% — รอ Nvidia/TSMC ขับ",
    ],
    "fintech":    [
        "{sym} {move:+.1f}% — fintech ขายตาม market",
        "{sym} {move:+.1f}% — credit risk concern?",
    ],
    # 🆕 Small cap sectors — bear context
    "mining":     [
        "{sym} {move:+.1f}% — BTC ลง mining stocks ร่วงตาม",
        "{sym} {move:+.1f}% — hash rate ไม่คุ้มขุด",
    ],
    "power":      [
        "{sym} {move:+.1f}% — nuclear hype พักก่อน",
        "{sym} {move:+.1f}% — funding/regulatory ติดขัด?",
    ],
    "evtol":      [
        "{sym} {move:+.1f}% — eVTOL certification ล่าช้า?",
    ],
    "materials":  [
        "{sym} {move:+.1f}% — commodities sell-off",
    ],
    "retech":     [
        "{sym} {move:+.1f}% — real estate ดอกเบี้ยยังเป็นภาระ",
    ],
    "meme":       [
        "{sym} {move:+.1f}% — retail crowd ทิ้ง",
        "{sym} ร่วง {move:+.1f}% — social sentiment เย็น",
    ],
    "defense":    [
        "{sym} {move:+.1f}% — defense rotation ออก",
    ],
}

# Flat move (|move| < 0.1%) — ราคาทรงตัว
HOOK_TEMPLATES_FLAT = {
    "tech_mega":  ["{sym} ทรงตัว — รอ Mag 7 catalyst ตัวต่อไป"],
    "story":      ["{sym} นิ่งวันนี้ — รอ news catalyst"],
    "quantum":    ["{sym} ทรงตัว — quantum hype พักก่อน"],
    "space":      ["{sym} ทรงตัว — รอ contract/launch event"],
    "ai":         ["{sym} ทรงตัว — AI sector consolidate"],
    "ev":         ["{sym} ทรงตัว — รอ delivery data"],
    "crypto":     ["{sym} ทรงตัว — รอ BTC ตัดสินทิศ"],
    "biotech":    ["{sym} ทรงตัว — รอ FDA/trial readout"],
    "semi":       ["{sym} ทรงตัว — chip cycle ดู range-bound"],
    "fintech":    ["{sym} ทรงตัว — รอ earnings/macro signal"],
    # 🆕 Small cap sectors — flat
    "mining":     ["{sym} ทรงตัว — รอ BTC คอนเฟิร์มทิศ"],
    "power":      ["{sym} ทรงตัว — รอ contract/license signal"],
    "evtol":      ["{sym} ทรงตัว — รอ FAA approval news"],
    "materials":  ["{sym} ทรงตัว — รอ policy/supply news"],
    "retech":     ["{sym} ทรงตัว — รอ rate cut signal"],
    "meme":       ["{sym} ทรงตัว — social ไม่ active"],
    "defense":    ["{sym} ทรงตัว — รอ contract award"],
}

# Backward compat — keep HOOK_TEMPLATES name for any external ref
HOOK_TEMPLATES = HOOK_TEMPLATES_BULL


def _truncate_smart(text: str, max_len: int = 100) -> str:
    """ตัด text ที่คำ (whitespace) สุดท้าย — ไม่ตัดกลางคำ"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:!?") + "…"


def _build_hook(symbol: str, move_pct: float, news_headline: str = "") -> str:
    """Pick hook template สำหรับ symbol category — bullish/bearish/flat context-aware"""
    sector = SECTOR_TAG.get(symbol, "story")
    # Map specific sectors → template key (รวม "tech" → tech_mega tone)
    if sector in (
        "space", "quantum", "ai", "ev", "crypto", "biotech", "semi", "fintech",
        # 🆕 Small cap sectors
        "mining", "power", "evtol", "materials", "retech", "meme", "defense",
    ):
        key = sector
    elif sector in ("tech_mega", "tech"):
        key = "tech_mega"
    else:
        key = "story"

    # Pick template pool ตาม move direction
    if abs(move_pct) < 0.1:
        pool = HOOK_TEMPLATES_FLAT
    elif move_pct < 0:
        pool = HOOK_TEMPLATES_BEAR
    else:
        pool = HOOK_TEMPLATES_BULL

    templates = pool.get(key, pool.get("story", HOOK_TEMPLATES_BULL["story"]))
    template = random.choice(templates)
    hook = template.format(sym=symbol, move=move_pct)
    if news_headline:
        hook += f"\n   📰 {_truncate_smart(news_headline, 100)}"
    return hook


def _score_pick(tech_data: dict, news_item: dict = None, symbol: str = "") -> float:
    """Composite score — เน้น 'ซิ่ง + สตอรี่ + bull bias' สำหรับ FB-able content

    🆕 2026-05-13: Small cap-aware (PP P. ขอให้เห็น small cap ใน picks)
    - Relax outlier cap (25% → 35%) เพราะ small cap วิ่ง 25-35% เป็นเรื่องปกติ
    - Pump penalty threshold สูงขึ้น (15% → 22%) สำหรับ small cap
    - Bonus +3 ถ้า small cap มี vol confirm (vol_ratio > 2)
    """
    move_raw = tech_data.get("price_move_pct", 0) or 0
    move_abs = abs(move_raw)
    vol_ratio = tech_data.get("volume_ratio", 1) or 1
    rsi = tech_data.get("rsi", 50) or 50
    is_small = _is_small_cap(symbol) if symbol else False

    # Skip boring (< 1% move) — ไม่ค่อย FB-able
    if move_abs < 1.0:
        return -100   # effective skip

    # Cap outlier — relaxed for small cap (day trader ปกติเห็น 25-35%)
    outlier_cap = 35 if is_small else 25
    if move_abs > outlier_cap:
        return -50

    # Big move = priority
    score = move_abs * 2.0
    # Bull bias — positive moves ทำ content "หุ้นวิ่ง" ขายดีกว่า "หุ้นร่วง"
    if move_raw > 0:
        score += 4
    # Outlier cap soft — small cap threshold สูงกว่า (15% → 22%)
    pump_threshold = 22 if is_small else 15
    if move_abs > pump_threshold:
        score -= 5

    # Vol confirm
    score += min(vol_ratio, 5) * 1.5
    # RSI sweet spot (40-65) = healthy momentum
    if 40 <= rsi <= 65:
        score += 5
    elif rsi > 80 or rsi < 20:
        score -= 5

    # 🆕 Small cap bonus — ดึง small cap ที่มี real breakout (vol confirm) เข้า pick
    # +3 ไม่มากพอจะ dominate mega cap แต่พอให้ small cap มี fair shot
    if is_small and vol_ratio > 2:
        score += 3

    # Fresh news bonus — ข่าวสด = FB engagement สูงกว่า
    if news_item:
        age_h = news_item.get("age_hours", 999)
        if age_h <= 6:
            score += 15
        elif age_h <= 24:
            score += 10
        elif age_h <= 48:
            score += 5
    return score


def _fetch_tech(symbol: str) -> dict:
    """Fetch quick tech snapshot — return dict ที่ scoring + display ใช้ได้"""
    try:
        from technical_tools import calculate_technical_indicators
        td, _, err = calculate_technical_indicators(symbol, generate_chart=False)
        if err or not td:
            return None
        # Add price_move_pct
        try:
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="2d")
            if len(hist) >= 2:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                td["price_move_pct"] = (last - prev) / prev * 100
            else:
                td["price_move_pct"] = 0
        except Exception:
            td["price_move_pct"] = 0
        # 🛡 Volume edge case: ถ้า volume/avg_volume = None / 0 → ratio = 1.0 + log
        # ป้องกัน score คำนวณผิดจาก garbage data
        vol = td.get("volume")
        avg_vol = td.get("avg_volume")
        try:
            vol_f = float(vol) if vol is not None else 0
            avg_f = float(avg_vol) if avg_vol is not None else 0
        except (ValueError, TypeError):
            vol_f, avg_f = 0, 0
        if avg_f > 0 and vol_f > 0:
            td["volume_ratio"] = vol_f / avg_f
        else:
            td["volume_ratio"] = 1.0
            if vol_f == 0 or avg_f == 0:
                print(f"[daily-picker] {symbol} volume data missing/zero — ratio defaulted 1.0", flush=True)
        return td
    except Exception as e:
        print(f"[daily-picker] tech err {symbol}: {e}", flush=True)
        return None


def _fetch_news_for_symbol(symbol: str, max_age_hours: int = 48) -> dict:
    """ดึง news ล่าสุด ≤ max_age_hours — เน้นสด (admin เอาไปทำ content คนติดตามได้)

    รองรับ yfinance news format ทั้ง legacy (providerPublishTime epoch) + ใหม่ (content.pubDate ISO)
    Returns: dict { headline, url, published_at, age_hours } หรือ None ถ้าไม่มีข่าวสด
    """
    try:
        import yfinance as yf
        items = yf.Ticker(symbol).news or []
        if not items:
            return None

        now = datetime.now(timezone.utc)
        parsed = []
        for n in items[:10]:  # scan 10 ล่าสุด แล้วเลือกตัวสดสุด
            content = n.get("content") if isinstance(n.get("content"), dict) else n

            # Parse pub time — รองรับ ISO + epoch
            pub_dt = None
            pub_str = content.get("pubDate") or content.get("displayTime")
            if pub_str:
                try:
                    pub_dt = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
                except Exception:
                    pass
            if pub_dt is None:
                epoch = n.get("providerPublishTime") or content.get("providerPublishTime")
                if epoch:
                    try:
                        pub_dt = datetime.fromtimestamp(float(epoch), tz=timezone.utc)
                    except Exception:
                        pass
            if pub_dt is None:
                continue   # ข่าวไม่มี timestamp = ทิ้ง (ไม่รู้ว่าสดไหม)

            age_hours = (now - pub_dt).total_seconds() / 3600
            if age_hours < 0 or age_hours > max_age_hours:
                continue   # อนาคต/เก่าเกินไป = ทิ้ง

            headline = content.get("title") or n.get("title", "")
            url = ""
            cu = content.get("canonicalUrl")
            if isinstance(cu, dict):
                url = cu.get("url", "") or ""
            url = url or n.get("link", "") or ""

            parsed.append({
                "headline": headline,
                "url": url,
                "published_at": pub_dt,
                "age_hours": age_hours,
            })

        if not parsed:
            return None
        parsed.sort(key=lambda x: x["age_hours"])   # ล่าสุดสุดอันแรก
        return parsed[0]
    except Exception:
        return None


def pick_top_3(pool: list = None) -> list[dict]:
    """Pick 3 stocks with sector diversity

    Returns: list of dict { symbol, tech_data, news, score, sector }
    """
    pool = pool or ALL_POOL
    candidates = []

    # Score ทุก symbol ใน pool (cap 50 ตัวเพื่อเร็ว)
    # 🆕 2026-05-13: ขยายจาก 40 → 50 เพราะ pool ใหญ่ขึ้น (เพิ่ม small cap 30 ตัว)
    sample = random.sample(pool, min(50, len(pool)))
    for sym in sample:
        td = _fetch_tech(sym)
        if td is None:
            continue
        news = _fetch_news_for_symbol(sym)
        score = _score_pick(td, news, symbol=sym)
        candidates.append({
            "symbol": sym,
            "tech_data": td,
            "news": news,
            "score": score,
            "sector": SECTOR_TAG.get(sym, "misc"),
        })
        time.sleep(0.5)   # rate-limit yfinance

    # Filter out boring/outlier (score ≤ 0 = skip — boring move or extreme outlier)
    candidates = [c for c in candidates if c["score"] > 0]

    # Sort by score desc
    candidates.sort(key=lambda x: -x["score"])

    # Pick top 3 with sector variety
    picks = []
    used_sectors = set()
    for c in candidates:
        if c["sector"] in used_sectors:
            continue
        picks.append(c)
        used_sectors.add(c["sector"])
        if len(picks) >= 3:
            break

    # ถ้าได้ < 3 (sector variety strict) → fill ตามคะแนน
    if len(picks) < 3:
        for c in candidates:
            if c not in picks:
                picks.append(c)
                if len(picks) >= 3:
                    break

    return picks[:3]


def _generate_simple_plan(tech_data: dict) -> dict:
    """Rule-based trade plan สำหรับ daily picker chart (ไม่กิน AI token)
    ใช้ S/R + EMA50 + current price + 2.5R target

    Returns plan dict: entry_low, entry_high, tp1, tp2, sl
    """
    if not tech_data:
        return {}
    try:
        current = float(tech_data.get("price") or 0)
        if current <= 0:
            return {}
        support = tech_data.get("support")
        resistance = tech_data.get("resistance")
        ema50 = tech_data.get("ema50")
        support = float(support) if support else None
        resistance = float(resistance) if resistance else None
        ema50 = float(ema50) if ema50 else None

        # Bias: bull ถ้าราคา > EMA50 (uptrend), else bear
        is_bull = ema50 is None or current >= ema50

        # Entry zone: ±1% รอบราคาปัจจุบัน (admin/user adjust ได้)
        entry_low = current * 0.99
        entry_high = current * 1.01

        if is_bull:
            # Bull setup: SL ต่ำกว่า entry, TP1 ที่ resistance, TP2 = 2.5R target
            # SL logic ระบุชัด:
            #   ถ้ามี support < current → SL ใต้ support 1.5% (zone respect)
            #   else → SL ที่ -5% (default conservative loss)
            #   cap: ห้าม SL ห่างเกิน 7% (ไม่ Burn account)
            if support and support < current:
                sl = max(support * 0.985, current * 0.93)
            else:
                sl = current * 0.95
            tp1 = resistance if resistance and resistance > current * 1.01 else current * 1.05
            risk = current - sl
            tp2 = current + max(risk, current * 0.02) * 2.5
        else:
            # Bear setup: SL เหนือ entry, TP1 ที่ support (deeper target), TP2 = 2.5R
            # Bear TP1: ถ้ามี support → ใช้ support (deep target)
            #          else → -10% (deeper than bull's +5% — bear move บ่อยใหญ่กว่า)
            if resistance and resistance > current:
                sl = min(resistance * 1.015, current * 1.07)
            else:
                sl = current * 1.05
            tp1 = support if support and support < current * 0.99 else current * 0.90
            risk = sl - current
            tp2 = current - max(risk, current * 0.02) * 2.5

        return {
            "entry_low": round(entry_low, 2),
            "entry_high": round(entry_high, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "sl": round(sl, 2),
            "bias": "bullish" if is_bull else "bearish",
        }
    except Exception as e:
        print(f"[daily-picker] plan gen err: {e}", flush=True)
        return {}


def _render_chart_image(symbol: str, tech_data: dict = None):
    """Generate chart for symbol — PRO style + Entry/TP/SL annotation (rule-based plan)

    Returns: BytesIO buffer of PNG (สำหรับ bot.send_photo)
    """
    try:
        from technical_tools import generate_pro_annotated_chart
        # Rule-based plan สำหรับ chart annotation (ไม่กิน AI token)
        plan = _generate_simple_plan(tech_data) if tech_data else {}
        chart_buf = generate_pro_annotated_chart(symbol, plan=plan)
        if chart_buf is not None:
            return chart_buf
        # Fallback: ถ้า pro chart fail → ใช้ basic
        from technical_tools import calculate_technical_indicators
        _, basic_buf, _ = calculate_technical_indicators(symbol, generate_chart=True)
        return basic_buf
    except Exception as e:
        print(f"[daily-picker] chart err {symbol}: {e}", flush=True)
        return None


def build_daily_picks_message(picks: list[dict]) -> str:
    """Build DM text — ส่งให้ admin"""
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    rank_emoji = ["🥇", "🥈", "🥉"]
    lines = [
        f"☀️ *Daily Picks — {today.strftime('%d %b %Y')}*",
        "━━━━━━━━━━━━━━",
        "",
    ]
    for i, p in enumerate(picks):
        td = p["tech_data"]
        sym = p["symbol"]
        sector = p["sector"]
        move = td.get("price_move_pct", 0) or 0
        price = td.get("price", 0)
        vol_ratio = td.get("volume_ratio", 1)
        rsi = td.get("rsi", 50)
        news = p.get("news") or {}

        sector_emoji_map = {
            "tech_mega": "🏛️", "space": "🚀", "quantum": "⚛️", "ai": "🤖",
            "ev": "🚗", "crypto": "₿", "biotech": "🧬", "meme": "🎮",
            "semi": "💾", "fintech": "💳", "defense": "🪖",
            "tech": "💻", "media": "🎬", "industrial": "🏭", "finance": "🏦",
            "retail": "🛒", "consumer": "🛍️", "healthcare": "🏥", "energy": "⚡",
            "telecom": "📡", "misc": "📊",
            # 🆕 Small cap sectors
            "mining": "⛏️", "power": "⚛️", "evtol": "🛩️",
            "materials": "💎", "retech": "🏠",
        }
        emoji = sector_emoji_map.get(sector, "📊")

        emo = rank_emoji[i] if i < len(rank_emoji) else "•"
        small_cap_tag = " 🔥small cap" if _is_small_cap(sym) else ""
        lines.append(f"{emo} *{sym}* {emoji} — ${price:.2f} ({move:+.2f}%){small_cap_tag}")
        lines.append(f"   📊 vol {vol_ratio:.1f}x · RSI {rsi:.1f} · {sector}")
        hook = _build_hook(sym, move, news.get("headline", "") if news else "")
        lines.append(f"   💡 _{hook}_")
        if news and news.get("url"):
            age_h = news.get("age_hours") or 0
            if age_h < 1:
                age_str = f"{int(age_h * 60)} นาทีที่แล้ว"
            elif age_h < 24:
                age_str = f"{age_h:.1f} ชม.ที่แล้ว"
            else:
                age_str = f"{age_h/24:.1f} วันที่แล้ว"
            lines.append(f"   🔗 [ข่าวล่าสุด]({news['url'][:120]}) · {age_str}")
        # 🆕 Small cap warning — ลูกค้า PP P. ขอเพิ่ม small cap (2026-05-13)
        # ต้องเตือนเพราะ volatility สูง + liquidity ต่ำกว่า mega cap
        if _is_small_cap(sym):
            lines.append("   ⚠️ _small cap — volatility สูง, ใช้ size เล็ก, ตั้ง SL เคร่ง_")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━",
        "_chart แต่ละตัวส่งมาเป็นภาพแยก (Apexify analysis)_",
        "_เอา hook + ข่าวสด + chart ไปต่อยอด ChatGPT/Gemini สำหรับ FB content_",
    ])
    return "\n".join(lines)


def run_once(bot, dry_run: bool = False):
    """รัน 1 cycle: pick + DM admin"""
    if not config.ADMIN_ID:
        print("[daily-picker] no ADMIN_ID set, skip", flush=True)
        return
    print(f"[daily-picker] running (dry={dry_run})...", flush=True)
    picks = pick_top_3()
    if not picks:
        print("[daily-picker] no candidates found", flush=True)
        if not dry_run:
            try:
                bot.send_message(config.ADMIN_ID, "⚠️ Daily Picker: ไม่เจอ candidate วันนี้ (ตลาดอาจปิด/network err)")
            except Exception:
                pass
        return

    msg = build_daily_picks_message(picks)

    if dry_run:
        print("==== DRY RUN ====")
        print(msg)
        return

    # Send text DM first
    try:
        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"[daily-picker] DM text err: {e}", flush=True)
        # fallback: no markdown
        try:
            bot.send_message(config.ADMIN_ID, msg.replace("*", "").replace("_", ""))
        except Exception:
            pass

    # Send chart image for each pick — chart เดียวกับที่ bot วิเคราะห์ปกติ
    for p in picks:
        try:
            chart = _render_chart_image(p["symbol"], p.get("tech_data"))
            if chart:
                bot.send_photo(config.ADMIN_ID, chart, caption=f"📊 {p['symbol']} chart — Apexify")
                time.sleep(1.5)   # rate-limit Telegram
        except Exception as e:
            print(f"[daily-picker] chart send err {p['symbol']}: {e}", flush=True)


def _today_dispatch_key():
    today = config.thai_today() if hasattr(config, "thai_today") else config.thai_now().date()
    return f"daily_picker:daily:{today.isoformat()}"


def _already_ran_today():
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM dispatch_log WHERE dispatch_key=%s LIMIT 1", (_today_dispatch_key(),))
        return c.fetchone() is not None
    except Exception as e:
        print(f"[daily-picker] _already_ran_today DB err: {e}", flush=True)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _mark_today_done():
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (_today_dispatch_key(), "daily_picker", "admin"),
        )
        conn.commit()
    except Exception as e:
        print(f"[daily-picker] mark err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_daily_picker_cron(bot):
    """Daemon thread — DM admin ทุกเช้า 7:30 ICT"""
    if not config.DAILY_PICKER_ENABLED:
        print("[daily-picker] disabled — thread exiting", flush=True)
        return

    target_h = config.DAILY_PICKER_HOUR_ICT
    target_m = config.DAILY_PICKER_MINUTE_ICT
    print(f"[daily-picker] cron started — daily at {target_h:02d}:{target_m:02d} ICT", flush=True)

    time.sleep(2 * 60)   # warm-up

    while True:
        try:
            now = (datetime.now(timezone.utc) + timedelta(hours=7))
            if now.hour == target_h and now.minute >= target_m and now.minute < target_m + 30:
                if not _already_ran_today():
                    _mark_today_done()
                    run_once(bot)
        except Exception as e:
            print(f"[daily-picker] loop err: {e}", flush=True)
        time.sleep(20 * 60)  # poll ทุก 20 นาที


if __name__ == "__main__":
    # smoke test (DRY)
    import telebot
    if not config.TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        exit(1)
    bot = telebot.TeleBot(config.TELEGRAM_TOKEN)
    run_once(bot, dry_run=True)
