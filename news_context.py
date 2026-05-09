"""Per-ticker news fetcher for AI grounding.

ใช้กับ ai_analyzer เพื่อใส่ข่าวล่าสุดของหุ้นเข้า Gemini prompt
ทำให้ AI ตอบคำถามแบบ "ทำไม X ลง?" ได้ — ไม่ใช่แค่ดู RSI/MACD

Sources (เรียงลำดับ):
1. yfinance Ticker.news        — US/global stocks, no key
2. Google News RSS (search)    — fallback + Thai stocks (.BK)

Cache: TTLCache 30 นาที/หุ้น (ลด rate-limit hit + เร็วเมื่อถามซ้ำ)
"""

import time
from datetime import datetime
from threading import RLock
from urllib.parse import quote_plus

from cachetools import TTLCache

try:
    import feedparser
except Exception:
    feedparser = None

try:
    import yfinance as yf
except Exception:
    yf = None


_NEWS_CACHE = TTLCache(maxsize=300, ttl=1800)  # 30 นาที
_CACHE_LOCK = RLock()
_FETCH_TIMEOUT_S = 8  # กัน yfinance/feedparser hang


def _parse_iso_unix(iso_str):
    """ISO8601 → unix; คืน 0 ถ้า parse ไม่ได้"""
    if not iso_str:
        return 0
    try:
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp())
    except Exception:
        return 0


def _from_yfinance(symbol):
    """ดึง news ผ่าน yfinance — รองรับทั้ง schema เก่าและใหม่"""
    if yf is None:
        return []
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception as e:
        print(f"[news] yfinance err {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return []

    items = []
    for entry in raw[:12]:
        # schema ใหม่ (>=0.2.40 ประมาณ): {"id": ..., "content": {...}}
        content = entry.get("content") if isinstance(entry, dict) else None
        if isinstance(content, dict):
            title = content.get("title") or ""
            summary = content.get("summary") or content.get("description") or ""
            provider = content.get("provider") or {}
            source = provider.get("displayName") if isinstance(provider, dict) else ""
            pub = _parse_iso_unix(content.get("pubDate") or content.get("displayTime"))
        else:
            # schema เก่า: flat dict
            title = entry.get("title") or ""
            summary = entry.get("summary") or ""
            source = entry.get("publisher") or ""
            pub = int(entry.get("providerPublishTime") or 0)

        title = title.strip()
        if not title:
            continue
        items.append({
            "title": title[:200],
            "summary": (summary or "").strip()[:400],
            "source": (source or "yfinance").strip()[:60],
            "published_unix": pub,
        })
    return items


def _from_google_news_rss(symbol):
    """fallback ผ่าน Google News RSS — ใช้กับหุ้นไทย (.BK) หรือเมื่อ yfinance ว่าง"""
    if feedparser is None:
        return []
    # หุ้นไทย .BK ตัด suffix แล้วเสริม "หุ้น" เพื่อช่วย search
    base = symbol.replace(".BK", "").replace(".bk", "")
    is_thai = symbol.upper().endswith(".BK")
    if is_thai:
        query = f"{base} หุ้น"
        url = (
            f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"&hl=th&gl=TH&ceid=TH:th"
        )
    else:
        query = f"{base} stock"
        url = (
            f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"&hl=en-US&gl=US&ceid=US:en"
        )

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"[news] gnews err {symbol}: {type(e).__name__}: {str(e)[:80]}", flush=True)
        return []

    items = []
    for entry in (getattr(feed, "entries", None) or [])[:12]:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        pub = 0
        if entry.get("published_parsed"):
            try:
                pub = int(time.mktime(entry.published_parsed))
            except Exception:
                pub = 0
        source_obj = entry.get("source")
        source = ""
        if isinstance(source_obj, dict):
            source = source_obj.get("title") or ""
        items.append({
            "title": title[:200],
            "summary": (entry.get("summary") or "").strip()[:400],
            "source": (source or "Google News").strip()[:60],
            "published_unix": pub,
        })
    return items


def fetch_ticker_news(symbol, max_items=5):
    """คืน list[dict] — title/summary/source/published_unix เรียงใหม่สุดก่อน
    ว่าง = ไม่มีข่าว (caller ควร handle gracefully)
    """
    if not symbol or not isinstance(symbol, str):
        return []
    key = symbol.strip().upper()
    if not key:
        return []

    with _CACHE_LOCK:
        cached = _NEWS_CACHE.get(key)
        if cached is not None:
            return cached[:max_items]

    items = _from_yfinance(key)
    if not items:
        items = _from_google_news_rss(key)

    # dedup ตาม title (lowercased) กันข่าวซ้ำจากหลายแหล่ง
    seen = set()
    deduped = []
    for it in items:
        norm = it["title"].lower().strip()
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(it)

    deduped.sort(key=lambda x: x.get("published_unix", 0), reverse=True)
    deduped = deduped[:10]  # cap upstream แต่เก็บใน cache สูงสุด 10

    with _CACHE_LOCK:
        _NEWS_CACHE[key] = deduped
    return deduped[:max_items]


def format_news_for_prompt(items, max_items=5):
    """compact format สำหรับใส่ใน Gemini prompt — ประหยัด token
    ไม่ใส่ summary เพราะ headline พอแล้วและ summary ของ Google News มัก noisy
    """
    if not items:
        return ""
    now = time.time()
    lines = []
    for i, item in enumerate(items[:max_items], 1):
        pub = item.get("published_unix") or 0
        if pub > 0:
            age_h = max(0, (now - pub) / 3600)
            if age_h < 1:
                age = f"{int(age_h * 60)}m"
            elif age_h < 48:
                age = f"{age_h:.0f}h"
            elif age_h < 168:
                age = f"{age_h / 24:.0f}d"
            else:
                age = ">7d"
        else:
            age = "?"
        title = (item.get("title") or "").strip()[:140]
        lines.append(f"{i}. [{age}] {title}")
    return "\n".join(lines)


def format_news_for_display(items, max_items=3):
    """format สำหรับแสดงให้ user เห็น (Telegram MarkdownV1) — สั้นกระชับ"""
    if not items:
        return ""
    now = time.time()
    lines = []
    for item in items[:max_items]:
        pub = item.get("published_unix") or 0
        if pub > 0:
            age_h = max(0, (now - pub) / 3600)
            if age_h < 1:
                age = f"{int(age_h * 60)} นาที"
            elif age_h < 48:
                age = f"{age_h:.0f} ชม."
            else:
                age = f"{age_h / 24:.0f} วัน"
        else:
            age = "ล่าสุด"
        # escape underscore + asterisk ใน title (Telegram Markdown)
        title = (item.get("title") or "").strip()[:120]
        title = title.replace("*", "·").replace("_", " ").replace("`", "'")
        source = (item.get("source") or "").strip()
        source_str = f" — _{source}_" if source else ""
        lines.append(f"  • {title}  `({age})`{source_str}")
    return "\n".join(lines)
