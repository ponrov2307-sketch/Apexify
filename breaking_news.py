"""Breaking News Alert — fetches US macro news, classifies importance via Gemini,
pushes HIGH-tier only to PRO subscribers via Telegram.

Design:
- Free sources: official RSS (Fed, BLS, Treasury) + Reuters/CNBC/MarketWatch.
- Two-stage filter: keyword pre-filter cuts ~95% noise instantly, then Gemini
  classifies the shortlist into HIGH / MEDIUM / LOW + Thai 1-line summary.
- Dedup via url_hash UNIQUE constraint on breaking_news_log.
- Throttle: max 1 alert per user per 30 min (anti-spam).
- Quiet hours: Thai 02:00-08:00 → bundled into morning briefing instead of push.
- Audio: HIGH alerts also get a short Thai voice clip via edge_tts (same voice
  as morning podcast: th-TH-PremwadeeNeural).
"""

import asyncio
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

try:
    from curl_cffi import requests as cffi_requests
    _USE_CFFI = True
except Exception:
    import requests as cffi_requests  # type: ignore
    _USE_CFFI = False

from config import gemini_client


# ========== Sources ==========
# All free, no registration. Tier-1 official US macro releases + market/company news mix.
_RSS_SOURCES = [
    # Fed press releases — every FOMC + speeches
    ("Fed",        "https://www.federalreserve.gov/feeds/press_all.xml"),
    # BLS — CPI, NFP, jobless claims
    ("BLS",        "https://www.bls.gov/feed/news_release.rss"),
    # Treasury press
    ("Treasury",   "https://home.treasury.gov/rss/press-releases"),
    # Reuters US business via Google News — broaden ครอบคลุม macro + tech + earnings + tariff (กัน war dominance)
    ("Reuters",    "https://news.google.com/rss/search?q=site:reuters.com+(Fed+OR+CPI+OR+jobs+OR+inflation+OR+rate+OR+tech+OR+earnings+OR+tariff+OR+chip+OR+AI)+when:2h&hl=en-US&gl=US&ceid=US:en"),
    # CNBC markets
    ("CNBC",       "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    # CNBC tech (เพิ่มความ diversity ไปทาง company/tech)
    ("CNBC-Tech",  "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    # MarketWatch top stories
    ("MarketWatch","http://feeds.marketwatch.com/marketwatch/topstories/"),
    # WSJ markets main
    ("WSJ",        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    # Yahoo Finance top stories (company news heavy — earnings, M&A, guidance)
    ("Yahoo",      "https://finance.yahoo.com/news/rssindex"),
    # Investing.com news (broad market news)
    ("Investing",  "https://www.investing.com/rss/news.rss"),
    # Seeking Alpha breaking (analyst calls, company news)
    ("SeekingAlpha","https://seekingalpha.com/market_currents.xml"),
]

# ========== Keyword pre-filter ==========
# Tier 1: high-confidence breaking — almost always market-moving.
# Notes:
# - Macro releases (CPI/NFP/FOMC) + true emergencies (recession/default/OPEC tariff)
# - **WAR keywords moved to T2** — Gemini contextual judgment ดีกว่า
#   (Russia/Ukraine + Israel/Iran news cycle ครอบคลุม headlines ทุกวัน — T1 auto-include
#    ทำให้ข่าวอื่นถูก crowd out. Gemini ตัดสินใจว่า war headline ไหน new/breaking)
# - **Company news (mega cap moves, earnings, guidance, M&A, IPO) ดึงขึ้น T1**
_TIER1_KEYWORDS = re.compile(
    r"\b("
    # Macro releases (high-conviction market movers)
    r"CPI|core CPI|PPI|PCE|core PCE|"
    r"non[- ]?farm|nonfarm|NFP|jobs report|payrolls?|"
    r"FOMC|"
    r"Fed [a-z ]*?(?:cuts?|hikes?|raises?|lowers?|holds?)|"
    r"rate (?:cuts?|hikes?|decision)|interest rate (?:cuts?|hikes?|decision)|"
    r"GDP (?:growth|grew|contracted|expansion|fell|dropped)|"
    r"gross domestic product|"
    # True emergencies (specific scenarios — not generic war)
    r"recession|default|debt ceiling|government shutdown|"
    r"OPEC[+]? (?:cuts?|production)|"
    r"trade war|tariff (?:announced|imposed|raised)|"
    r"market crash|stocks? crash|"
    r"Powell|"
    # Company-specific big news — drives single-ticker moves
    r"guidance (?:raised|cut|slashed)|earnings (?:beat|miss|crushed)|"
    r"stock split|share buyback|dividend (?:raised|cut|suspended)|"
    r"acquisition (?:announced|deal)|merger (?:announced)|"
    r"IPO (?:filed|priced)|spin[- ]?off|"
    r"Tesla (?:recalls?|production cut)|Apple (?:recalls?|launches?)|"
    r"Boeing (?:grounded|crash|halts?)|"
    # Mega cap individual movers
    r"(?:NVDA|Nvidia) (?:surges?|plunges?|crashes?|beats?)|"
    r"(?:TSLA|Tesla) (?:surges?|plunges?|crashes?)|"
    r"(?:AAPL|Apple) (?:surges?|plunges?)"
    r")\b",
    re.IGNORECASE,
)

# Tier 2: candidates — Gemini decides if HIGH/MEDIUM/LOW
# Includes contextual war news (Gemini judges if new/escalation/already-priced-in)
_TIER2_KEYWORDS = re.compile(
    r"\b("
    # Macro 2nd tier
    r"inflation|deflation|stagflation|"
    r"jobless|unemployment|labor market|"
    r"retail sales|consumer confidence|consumer sentiment|"
    r"housing starts|building permits|home sales|"
    r"ISM|PMI|manufacturing|services index|"
    r"dollar (?:strengthens?|weakens?|surges?|plunges?)|"
    r"yield (?:curve|spike|drop)|treasury (?:auction|yield)|"
    r"oil (?:surges?|plunges?|spikes?)|"
    r"gold (?:surges?|plunges?|spikes?)|"
    r"S&P 500|Nasdaq|Dow Jones|"
    r"earnings (?:beat|miss|surprise)|guidance (?:cut|raised)|"
    # War / geopolitical (Gemini decides if breaking/escalation)
    r"war|invasion|attack|missile|strike|conflict|"
    r"sanctions?|embargo|"
    r"emergency|crisis|"
    # AI / Tech / Semi — story stocks ส่วนใหญ่อยู่กลุ่มนี้
    r"AI chip|semiconductor|chip (?:demand|shortage|export)|"
    r"GPU|datacenter|cloud computing|"
    r"ChatGPT|OpenAI|Anthropic|Google DeepMind|"
    r"iPhone|MacBook|Tesla|EV (?:sales|demand)|"
    # International macro
    r"China (?:GDP|exports|stimulus|tariff)|"
    r"yuan|yen|BoJ|Bank of Japan|ECB|European Central Bank|"
    r"oil prices?|crude oil|natural gas|"
    # Crypto (high-beta correlation)
    r"Bitcoin|BTC|Ethereum|crypto (?:rally|crash)"
    r")\b",
    re.IGNORECASE,
)


# ========== Helpers ==========

def _hash_url(link: str, title: str) -> str:
    """Stable dedup key — prefer URL but fall back to title (some RSS lack canonical link)."""
    key = link.strip() if link else title.strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _http_get(url: str, timeout: int = 10):
    if _USE_CFFI:
        return cffi_requests.get(url, impersonate="chrome110", timeout=timeout)
    return cffi_requests.get(url, timeout=timeout, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ApexifyBot/1.0)",
    })


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Return list of {title, link, pubDate} — works for RSS 2.0 + Atom."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    # RSS 2.0
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or ""
        if title:
            items.append({"title": title, "link": link, "pubDate": pub})
    # Atom (Treasury uses Atom)
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.iterfind(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            title = (title_el.text or "").strip() if title_el is not None else ""
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            if title:
                items.append({"title": title, "link": link, "pubDate": ""})
    return items


def fetch_news_candidates(per_source_limit: int = 10) -> list[dict]:
    """Pull recent items from all sources. Each item: {title, link, source}."""
    out: list[dict] = []
    seen_titles: set[str] = set()
    for source_name, url in _RSS_SOURCES:
        try:
            resp = _http_get(url, timeout=12)
            if resp.status_code != 200:
                continue
            for it in _parse_rss(resp.content)[:per_source_limit]:
                t = it["title"]
                if t in seen_titles:
                    continue
                seen_titles.add(t)
                out.append({
                    "title": t,
                    "link": it["link"],
                    "source": source_name,
                })
        except Exception as e:
            print(f"[BreakingNews] fetch {source_name} failed: {e}", flush=True)
    return out


def keyword_tier(title: str) -> str | None:
    """Returns 'T1' (auto-shortlist), 'T2' (Gemini candidate), or None (skip)."""
    if _TIER1_KEYWORDS.search(title):
        return "T1"
    if _TIER2_KEYWORDS.search(title):
        return "T2"
    return None


# ========== Gemini classify ==========

_CLASSIFY_PROMPT = """คุณเป็นนักวิเคราะห์ข่าวการเงิน US ตอบเป็น JSON เท่านั้น ห้ามใส่ข้อความอื่น

ข่าว: "{title}"
แหล่ง: {source}

ประเมินว่าข่าวนี้น่าจะกระทบ S&P 500 หรือ Nasdaq มากแค่ไหนใน 1 ชั่วโมงหลังเผยแพร่:
- HIGH: ข่าวด่วน/ตัวเลขเศรษฐกิจสำคัญ คาดเคลื่อน >0.5% เช่น CPI, NFP, FOMC, ภาวะสงคราม, OPEC cut, ลดอัตราดอกเบี้ยเซอไพรส์
- MEDIUM: ข่าวสำคัญรองลง คาด 0.2-0.5% เช่น คำสัมภาษณ์ Fed, retail sales, ISM
- LOW: ข่าวทั่วไปไม่น่าทำให้ตลาดเคลื่อนแรง

หากข่าวเฉพาะบริษัท (เช่น Boeing 777 grounded, Apple recalls, Tesla recall) ระบุ ticker ของบริษัทนั้นใน "tickers"
หากเป็นข่าวมหภาค/ตลาด/นโยบาย (CPI, FOMC, war, OPEC) ที่กระทบทั้งตลาด → "tickers": [] (แสดงว่ากระทบวงกว้าง)

ตอบ JSON:
{{"importance": "HIGH|MEDIUM|LOW", "summary_th": "สรุปไทย 80 ตัวอักษรกระชับ (สำหรับข้อความ Telegram)", "reasoning": "เหตุผลภาษาไทย 1 ประโยค", "audio_script_th": "บท narration ภาษาไทย 4-6 ประโยค (~250-400 ตัวอักษร) สำหรับเสียง อธิบายข่าว+เหตุผล+ผลกระทบที่อาจเกิด+คำแนะนำเตรียมตัวสำหรับนักลงทุน เขียนเป็นประโยคต่อเนื่อง อ่านลื่น ห้ามใช้ bullet", "tickers": []}}"""


_GEMINI_FALLBACK_CHAIN = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro")


def _gemini_classify_with_retry(prompt: str, retries: int = 2):
    """Try the fallback chain with backoff on 503/overload errors."""
    last_err = None
    for model in _GEMINI_FALLBACK_CHAIN:
        for attempt in range(retries + 1):
            try:
                resp = gemini_client.models.generate_content(model=model, contents=prompt)
                return resp
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                # Overloaded → wait then retry; other errors → break to next model
                if "503" in msg or "unavailable" in msg or "overloaded" in msg or "high demand" in msg:
                    if attempt < retries:
                        time.sleep(2 ** attempt)  # 1s, 2s
                        continue
                break
    raise last_err if last_err else RuntimeError("Gemini classify failed")


def gemini_classify_breaking(item: dict) -> dict | None:
    """Classify one news item. Returns enriched dict.

    Output adds: importance ('HIGH'|'MEDIUM'|'LOW'), summary_th, reasoning.

    Strategy:
      - Real classify via Gemini (retry on overload; try fallback models).
      - On total failure: downgrade T1 keyword match to MEDIUM (not HIGH) —
        Fed admin press releases often hit T1 keywords but aren't market-movers.
        Only Gemini's contextual judgment can confirm true breaking.
    """
    if not gemini_client:
        return {
            **item,
            "importance": "MEDIUM" if keyword_tier(item["title"]) else "LOW",
            "summary_th": item["title"][:80],
            "reasoning": "Gemini unavailable — keyword fallback (downgraded)",
            "tickers": [],
        }

    prompt = _CLASSIFY_PROMPT.format(title=item["title"], source=item["source"])
    try:
        resp = _gemini_classify_with_retry(prompt)
        text = (resp.text or "").strip()
        # Strip markdown fences if any
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        importance = str(data.get("importance", "LOW")).upper()
        if importance not in ("HIGH", "MEDIUM", "LOW"):
            importance = "LOW"
        # Normalize tickers list
        raw_tickers = data.get("tickers") or []
        if isinstance(raw_tickers, str):
            raw_tickers = [raw_tickers]
        tickers = [str(t).upper().strip() for t in raw_tickers if str(t).strip()][:10]
        return {
            **item,
            "importance": importance,
            "summary_th": str(data.get("summary_th", item["title"]))[:200],
            "reasoning": str(data.get("reasoning", ""))[:300],
            "audio_script_th": str(data.get("audio_script_th", ""))[:600],
            "tickers": tickers,
        }
    except Exception as e:
        print(f"[BreakingNews] Gemini classify failed (all retries): {e}", flush=True)
        # Fallback: T1 keyword (CPI/NFP/FOMC) → HIGH (don't miss real breaking news)
        # T2 keyword → MEDIUM. ไม่มี keyword → LOW
        # เปลี่ยนจากเดิมที่ T1 → MEDIUM (เสี่ยงพลาด FOMC/CPI ตอน Gemini down)
        tier = keyword_tier(item["title"])
        if tier == "T1":
            importance = "HIGH"
            reasoning = "Gemini error — T1 keyword (CPI/FOMC/NFP) auto-HIGH"
        elif tier == "T2":
            importance = "MEDIUM"
            reasoning = "Gemini error — T2 keyword fallback"
        else:
            importance = "LOW"
            reasoning = "Gemini error — no keyword match"
        return {
            **item,
            "importance": importance,
            "summary_th": item["title"][:80],
            "reasoning": reasoning,
            "tickers": [],
        }


# ========== Thai TTS (Edge TTS) ==========

_TTS_VOICE = "th-TH-PremwadeeNeural"  # Same voice as morning podcast


def _build_audio_script(record: dict) -> str:
    """Build a natural-sounding Thai script from the news record.

    Prefer audio_script_th (narration 4-6 sentences from Gemini) — fallback to
    summary_th + reasoning if missing (older records / Gemini fallback path).
    """
    narration = (record.get("audio_script_th") or "").strip()
    if narration:
        return f"ข่าวด่วนตลาดสหรัฐ. {narration}"
    # Fallback for legacy records without audio_script_th
    summary = (record.get("summary_th") or record.get("title") or "").strip()
    reasoning = (record.get("reasoning") or "").strip()
    parts = ["ข่าวด่วนตลาดสหรัฐ", summary]
    if reasoning:
        parts.append(reasoning)
    return ". ".join(p for p in parts if p)


async def _tts_save(text: str, out_path: str) -> bool:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, _TTS_VOICE)
        await communicate.save(out_path)
        return True
    except Exception as e:
        print(f"[BreakingNews] edge_tts failed: {e}", flush=True)
        return False


def generate_audio_for_breaking(record: dict) -> str | None:
    """Sync wrapper. Returns path to saved mp3 or None."""
    text = _build_audio_script(record)
    if not text:
        return None
    safe_id = (record.get("url_hash") or "tmp")[:16]
    out_path = f"breaking_{safe_id}.mp3"
    try:
        ok = asyncio.run(_tts_save(text, out_path))
    except Exception as e:
        print(f"[BreakingNews] TTS run failed: {e}", flush=True)
        return None
    if ok and os.path.exists(out_path):
        return out_path
    return None


# ========== Format for Telegram ==========

def format_breaking_message(record: dict) -> str:
    """Build Markdown message for Telegram push."""
    icon = "🚨" if record["importance"] == "HIGH" else "📰"
    lines = [
        f"{icon} **ข่าวด่วนตลาด US**",
        "",
        f"📌 {record['summary_th']}",
        "",
        f"💡 _{record.get('reasoning', '')}_" if record.get("reasoning") else "",
        f"📰 {record['title']}",
        f"🔗 [อ่านต่อ]({record['link']})" if record.get("link") else "",
        f"_แหล่ง: {record['source']}_",
    ]
    return "\n".join(l for l in lines if l)


# ========== Main entry — called from alert_system loop ==========

# Quiet hours (Thai): bundle alerts here into morning digest instead of push
_QUIET_HOUR_START = 2   # 02:00 Thai
_QUIET_HOUR_END = 8     # 08:00 Thai

# Throttle per user — minimum gap between push to same subscriber (in seconds)
_PER_USER_THROTTLE_SEC = 60 * 60  # 60 min (เพิ่มจาก 30 → 60 เพราะ event day เช่น CPI/FOMC spam ได้)

# Topic dedup — ถ้าข่าวใหม่ similar กับที่เพิ่งส่ง → skip
_TOPIC_SIMILARITY_THRESHOLD = 0.45   # Jaccard token overlap ≥ 45% = ถือเป็น topic เดียวกัน
_TOPIC_DEDUP_WINDOW_SEC = 6 * 60 * 60   # 6 ชม. window
_MAX_PER_TOPIC_PER_DAY = 2   # ส่งสูงสุด 2 ครั้ง/topic/วัน (เช่น CPI report ส่งแค่ 2 อันแรก)

# In-memory state — primary access (fast)
# Backed by dispatch_log table — persisted across restarts (no spam after deploy)
_user_last_sent_at: dict = {}                  # uid → unix ts
_recent_topics: list[tuple[float, set]] = []   # (timestamp, token_set) recent titles
_daily_topic_count: dict = {}                  # date_str → {topic_key: count}
_hydrated_from_db: bool = False                # one-shot DB load on first cycle


def _title_tokens(title: str) -> set:
    """Normalize title to lowercased set of meaningful tokens"""
    import re as _re
    # ตัด non-alphanumeric เป็น space
    cleaned = _re.sub(r"[^a-zA-Z0-9\s]", " ", title.lower())
    tokens = cleaned.split()
    # ตัด stop words ที่ไม่มี discriminative power
    _STOP = {"the", "a", "an", "in", "on", "of", "to", "for", "is", "are", "was", "were",
             "and", "or", "but", "as", "at", "by", "from", "with", "us", "u", "s"}
    return {t for t in tokens if len(t) >= 2 and t not in _STOP}


def _title_topic_key(tokens: set) -> str:
    """ดึง keyword สำคัญสุดจาก title สำหรับ daily count

    Priority: macro release > company > generic
    """
    macro_keys = {"cpi", "ppi", "pce", "nfp", "fomc", "fed", "powell", "gdp",
                   "jobless", "inflation", "recession", "ism", "pmi"}
    geo_keys = {"iran", "russia", "ukraine", "china", "israel", "war", "missile",
                 "tariff", "sanction", "opec"}
    for k in macro_keys:
        if k in tokens:
            return f"macro:{k}"
    for k in geo_keys:
        if k in tokens:
            return f"geo:{k}"
    # fallback: use top 3 tokens as topic
    return "other:" + "_".join(sorted(tokens)[:3])


def _jaccard_similarity(a: set, b: set) -> float:
    """Jaccard index — |A∩B| / |A∪B|"""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _prune_recent_topics(now_ts: float):
    """ลบ topic ที่เก่ากว่า window"""
    global _recent_topics
    cutoff = now_ts - _TOPIC_DEDUP_WINDOW_SEC
    _recent_topics = [(ts, toks) for ts, toks in _recent_topics if ts > cutoff]


def _is_topic_duplicate(title: str, now_ts: float) -> bool:
    """เช็คว่า title นี้คล้ายกับที่ส่งไปแล้วใน 6 ชม.ที่ผ่านมาหรือไม่"""
    new_tokens = _title_tokens(title)
    if not new_tokens:
        return False
    _prune_recent_topics(now_ts)
    for _ts, old_tokens in _recent_topics:
        if _jaccard_similarity(new_tokens, old_tokens) >= _TOPIC_SIMILARITY_THRESHOLD:
            return True
    return False


def _topic_daily_count_exceeded(title: str, now_dt: datetime) -> bool:
    """เช็คว่า topic นี้ถึงโควต้าวันนี้แล้วหรือไม่ (max 2/topic/day)"""
    tokens = _title_tokens(title)
    if not tokens:
        return False
    topic_key = _title_topic_key(tokens)
    date_str = now_dt.date().isoformat()
    day_counts = _daily_topic_count.setdefault(date_str, {})
    return day_counts.get(topic_key, 0) >= _MAX_PER_TOPIC_PER_DAY


def _mark_topic_sent(title: str, now_ts: float, now_dt: datetime):
    """บันทึก topic ที่ส่งไปแล้ว + persist ลง DB (กัน daily-cap reset on restart)"""
    tokens = _title_tokens(title)
    if not tokens:
        return
    _recent_topics.append((now_ts, tokens))
    topic_key = _title_topic_key(tokens)
    date_str = now_dt.date().isoformat()
    day_counts = _daily_topic_count.setdefault(date_str, {})
    day_counts[topic_key] = day_counts.get(topic_key, 0) + 1
    # cleanup old dates (keep last 2 days)
    if len(_daily_topic_count) > 3:
        oldest = min(_daily_topic_count.keys())
        if oldest != date_str:
            _daily_topic_count.pop(oldest, None)
    # 🆕 Persist to dispatch_log — hydration uses COUNT(*) per topic per day
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (f"news_topic:{date_str}:{topic_key}:{int(now_ts)}", "breaking_news_topic", topic_key),
        )
        conn.commit()
    except Exception as e:
        print(f"[BreakingNews] persist topic_sent err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _can_send_to_user(uid: str, now_ts: float) -> bool:
    """เช็ค per-user throttle (60 นาที)"""
    last = _user_last_sent_at.get(str(uid), 0)
    return (now_ts - last) >= _PER_USER_THROTTLE_SEC


def _mark_user_sent(uid: str, now_ts: float):
    """Mark user as just-sent + persist to DB (survives restart)"""
    _user_last_sent_at[str(uid)] = now_ts
    # 🆕 Persist to dispatch_log — one row per send (used for hydration)
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        # Unique key: news_user:{uid}:{ts_int} — never collide
        c.execute(
            "INSERT INTO dispatch_log (dispatch_key, category, raw_key) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (f"news_user:{uid}:{int(now_ts)}", "breaking_news_user", str(uid)),
        )
        conn.commit()
    except Exception as e:
        print(f"[BreakingNews] persist user_sent err uid={uid}: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _hydrate_state_from_db():
    """Load past throttle/topic-count state from dispatch_log — call once on startup
    Avoids spam-on-restart: user got alert 30 min ago + bot restarted → still throttle works
    Avoids daily-cap reset: CPI sent 2x today + restart → cap stays 2 (no 3rd alert)
    """
    global _hydrated_from_db
    if _hydrated_from_db:
        return
    try:
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()

        # Load per-user throttle — latest news_user entry per user in past 6h
        c.execute(
            """
            SELECT DISTINCT ON (raw_key) raw_key, EXTRACT(EPOCH FROM created_at)
            FROM dispatch_log
            WHERE category = 'breaking_news_user'
              AND created_at > NOW() - INTERVAL '6 hours'
            ORDER BY raw_key, created_at DESC
            """
        )
        for raw_key, ts in c.fetchall():
            if raw_key:
                _user_last_sent_at[str(raw_key)] = float(ts)

        # Load today's per-topic count (for daily cap enforcement)
        c.execute(
            """
            SELECT raw_key, COUNT(*) AS cnt
            FROM dispatch_log
            WHERE category = 'breaking_news_topic'
              AND created_at::date = (NOW() AT TIME ZONE 'Asia/Bangkok')::date
            GROUP BY raw_key
            """
        )
        today_dt = datetime.utcnow() + timedelta(hours=7)
        today_key = today_dt.date().isoformat()
        _daily_topic_count.setdefault(today_key, {})
        for topic_key, cnt in c.fetchall():
            if topic_key:
                _daily_topic_count[today_key][topic_key] = int(cnt)

        print(f"[BreakingNews] hydrated state from DB: "
              f"{len(_user_last_sent_at)} users throttled · "
              f"{len(_daily_topic_count.get(today_key, {}))} topics today", flush=True)
    except Exception as e:
        print(f"[BreakingNews] hydrate err: {e}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        _hydrated_from_db = True   # set even on error → avoid re-trying forever


def is_quiet_hour(now: datetime | None = None) -> bool:
    """Thai 02:00-08:00 = quiet (no real-time push, bundle into morning briefing)."""
    if now is None:
        now = datetime.utcnow() + timedelta(hours=7)
    return _QUIET_HOUR_START <= now.hour < _QUIET_HOUR_END


def process_breaking_news(bot_instance, *, dry_run: bool = False) -> dict:
    """One poll cycle. Returns stats dict.

    Steps:
      1. Fetch RSS candidates
      2. Keyword pre-filter (drop ~95%)
      3. Dedup against breaking_news_log
      4. Gemini classify shortlist
      5. Insert into breaking_news_log
      6. If importance=HIGH and not quiet hour → push to subscribers
    """
    from database import (
        get_breaking_news_subscribers,
        is_breaking_news_seen,
        log_breaking_news,
        mark_breaking_news_sent,
    )

    stats = {"fetched": 0, "shortlisted": 0, "classified": 0,
             "high": 0, "pushed_users": 0, "skipped_dup": 0, "skipped_quiet": False,
             "skipped_topic_dup": 0, "skipped_topic_cap": 0, "skipped_user_throttle": 0}

    # 🆕 Hydrate throttle/topic state from DB on first cycle (one-shot)
    _hydrate_state_from_db()

    candidates = fetch_news_candidates()
    stats["fetched"] = len(candidates)
    if not candidates:
        return stats

    # Pre-filter + dedup
    shortlist = []
    for item in candidates:
        if keyword_tier(item["title"]) is None:
            continue
        item["url_hash"] = _hash_url(item["link"], item["title"])
        if is_breaking_news_seen(item["url_hash"]):
            stats["skipped_dup"] += 1
            continue
        shortlist.append(item)
    stats["shortlisted"] = len(shortlist)

    if not shortlist:
        return stats

    # Cap classify to prevent Gemini quota burn during news storms
    shortlist = shortlist[:8]

    quiet = is_quiet_hour()
    stats["skipped_quiet"] = quiet
    subscribers: list[str] = [] if quiet else get_breaking_news_subscribers()

    for item in shortlist:
        record = gemini_classify_breaking(item)
        if record is None:
            continue
        stats["classified"] += 1

        # Persist (also acts as a final dedup guarantee via UNIQUE constraint)
        try:
            news_id = log_breaking_news(
                url_hash=record["url_hash"],
                source=record["source"],
                title=record["title"],
                link=record.get("link", ""),
                summary_th=record.get("summary_th", ""),
                importance=record["importance"],
                reasoning=record.get("reasoning", ""),
            )
        except Exception as e:
            print(f"[BreakingNews] log insert failed: {e}", flush=True)
            continue
        if news_id is None:
            continue

        if record["importance"] != "HIGH":
            continue
        stats["high"] += 1

        if dry_run or quiet or not subscribers:
            continue

        # 🆕 Topic dedup — ถ้าข่าวนี้คล้ายเรื่องที่เพิ่งส่งใน 6 ชม. → skip
        _now_ts = time.time()
        _now_dt = datetime.utcnow() + timedelta(hours=7)
        if _is_topic_duplicate(record["title"], _now_ts):
            print(f"[BreakingNews] skipped topic dup: {record['title'][:60]}", flush=True)
            stats["skipped_topic_dup"] += 1
            continue

        # 🆕 Per-topic daily cap — เรื่องเดียวกัน max 2/วัน (กัน CPI/FOMC spam)
        if _topic_daily_count_exceeded(record["title"], _now_dt):
            print(f"[BreakingNews] skipped topic daily cap: {record['title'][:60]}", flush=True)
            stats["skipped_topic_cap"] += 1
            continue

        msg = format_breaking_message(record)

        # Personalization: macro news → broadcast all; company-specific → only
        # send to subscribers whose portfolio/watchlist intersects the tickers.
        target_subs = subscribers
        record_tickers = set(record.get("tickers", []))
        if record_tickers:
            from database import get_user_portfolio, get_user_watch
            target_subs = []
            for uid in subscribers:
                try:
                    held = {p["ticker"].upper() for p in (get_user_portfolio(uid) or [])}
                    watched = {w.upper() for w in (get_user_watch(uid) or [])}
                except Exception:
                    held, watched = set(), set()
                if record_tickers & (held | watched):
                    target_subs.append(uid)
            print(f"[BreakingNews] ticker-specific {sorted(record_tickers)} → "
                  f"{len(target_subs)}/{len(subscribers)} subs match", flush=True)

        if not target_subs:
            continue

        # Generate Thai voice clip once per news (reused for all subscribers)
        audio_path = generate_audio_for_breaking(record)

        sent_count = 0
        for uid in target_subs:
            # 🆕 Per-user throttle 60 นาที — กันข่าว spam หลายเรื่อง/ชม.
            if not _can_send_to_user(uid, _now_ts):
                stats["skipped_user_throttle"] += 1
                continue
            try:
                bot_instance.send_message(uid, msg, parse_mode="Markdown",
                                          disable_web_page_preview=False)
                sent_count += 1
                _mark_user_sent(uid, _now_ts)
                # Voice follows text — best-effort
                if audio_path:
                    try:
                        with open(audio_path, "rb") as f:
                            bot_instance.send_voice(chat_id=uid, voice=f,
                                                     caption="🎧 ฟังสรุปข่าว")
                    except Exception as e:
                        print(f"[BreakingNews] voice to {uid} failed: {e}", flush=True)
                # Soft throttle so Telegram doesn't 429 us
                time.sleep(0.05)
            except Exception as e:
                print(f"[BreakingNews] push to {uid} failed: {e}", flush=True)

        # บันทึก topic ที่ส่งสำเร็จไปแล้ว (ใช้ใน dedup รอบหน้า)
        if sent_count > 0:
            _mark_topic_sent(record["title"], _now_ts, _now_dt)

        # Cleanup audio file after push round
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass

        if sent_count > 0:
            try:
                mark_breaking_news_sent(news_id, sent_count)
            except Exception:
                pass
        stats["pushed_users"] += sent_count

    return stats
