---
tags: [performance, accuracy, roadmap, research]
---

# ⚡ Performance & Accuracy Roadmap

> รวม audit ภายใน + research GitHub repos + AI accuracy best practices (2025-2026)
> สร้างจาก agent research 2026-04-25

---

## ✅ DONE — Quick Wins ที่ implement แล้ว (รอบนี้)

### 🚀 Speed
1. **yfinance TTL Cache 90 วิ** (`technical_tools.py`) — `cachetools.TTLCache(400, ttl=90)` + RLock + `_fetch_history_cached` helper → request 2+ instant
2. **Parallelize 3 timeframes** (`build_multitimeframe_trade_context`) — `ThreadPoolExecutor(8 workers)` → 3-9 วิ → 1-3 วิ
3. **Progress messages 3 ขั้น** (`main.py:3045-3082`) — "🔍 ดึงข้อมูล" → "🤖 AI วิเคราะห์" → "🎨 วาดกราฟ"
4. **Pre-warm popular tickers** — 14 tickers (AAPL/MSFT/NVDA/GOOGL/AMZN/META/TSLA/PTT.BK/KBANK.BK/AOT.BK/ADVANC.BK/CPALL.BK/0700.HK/7203.T), cycle 45 วิ
5. **`TeleBot(num_threads=8)`** — handler thread pool 4x ใหญ่ขึ้น → 1 user analyze ไม่ block 100+ คน
6. **DB pool 5-30** (`database.py:396`) — รองรับ 8 bot threads + alert + Flask + pre-warm
7. **OBV vectorized** (`calculate_indicators`) — `cumsum` แทน Python loop, ~50x faster

### 🎯 Accuracy
8. **ATR(14)** เพิ่มใน `calculate_indicators` + ส่งใน multi-timeframe context
9. **ATR-based SL** (`ai_analyzer.py:_build_deterministic_plan`) — Bullish 1.5×ATR, Bearish 2.0×ATR (แม่นกว่า % คงที่)
10. **Min stop distance** — กัน premature stop (Bullish 0.5×ATR, Bearish 0.7×ATR)
11. **Plan validation layer** — ตรวจ TP2>TP1>Entry, SL<Entry consistency + ATR bounds (ไม่เกิน 3×ATR), warnings ใน plan dict

### 📦 Free Libraries Installed
- **diskcache 5.6.3** (Apache-2.0) — persistent cache, drop-in สำหรับ Gemini results
- **finnhub-python 2.4.20** — sentiment + insider data + news (free 60 req/min)
- **aiolimiter 1.2.1** (MIT) — rate limit yfinance/Gemini ใน async migration
- pandas-ta 0.3.14b0 — comment ใน requirements (Python<3.14, install บน DO ได้ปกติ)

**คาดการณ์รวม:** 15-20 วิ → **3-5 วิ** (popular/cached), **5-8 วิ** (cold) + **bot ไม่ block** ระหว่างผู้ใช้คนเดียววิเคราะห์

---

## 🚧 Outstanding Bottlenecks (จาก audit + agent C performance research)

### Big — ควรทำต่อ
1. **`AsyncTeleBot` migration** (effort: 1-2 วัน) — เปลี่ยน `TeleBot` → `telebot.async_telebot.AsyncTeleBot` (mod เดียวกัน, ไม่ต้อง install lib ใหม่) → handler ทั้งหมด `def`→`async def` → bot รับ message ใหม่ระหว่าง analyze
2. **DiskCache สำหรับ Gemini responses** (1-2 ชม) — `diskcache.Cache('/var/cache/apexify')` cache AI report 5 นาที → ลด Gemini API call 50%+ ตอน user ขอหุ้นซ้ำใน window
3. **N+1 queries** ใน `alert_system.py:372,1398` — batch `check_subscription` → ครึ่งวัน
4. **AI prompt caching** (`ai_analyzer.py:607`) — Gemini implicit caching ของ `system_instruction` → 30 นาที

### Medium
5. **RQ + Redis** task queue (3 วัน) — offload analyze ไป worker, bot ตอบ < 100ms ทุกครั้ง
6. **finnhub sentiment** integration — เสริม Gemini context (sentiment score + insider data) → +accuracy
7. AI generate streaming (Gemini รองรับ) — edit message ทันทีที่ token แรกมา
8. Chart DPI 120 → 90 + JPEG q=85 — ลดไฟล์ ส่งเร็ว
9. Defer yfinance import startup — 1-3 วิ overhead

---

## 📊 Phase 2 Roadmap — หลัง quick wins

### A. Accuracy Improvements (จาก agent C — ลำดับลงมือ)

#### Priority 1: Structured JSON output + Chain-of-Thought
- เปลี่ยน Gemini prompt → ใช้ `response_mime_type="application/json"` + schema
- บังคับ schema: `{trend, conviction, entry_low, entry_high, tp1, tp2, sl, reasoning_steps}`
- Few-shot 2-3 examples + CoT step-by-step
- **Impact:** ลด parsing error เป็น 0 + accuracy +15-25% (DK-CoT-JSON 2025)
- **Effort:** 1-2 วัน

#### Priority 2: Output validation layer
- ตรวจ `entry/TP/SL` consistent กับ trend (bullish: TP > Entry > SL)
- TP ไม่เกิน `ATR × 3`, SL ไม่ใกล้ราคาปัจจุบัน < `0.5 × ATR`
- ผิด → reject + retry
- **Impact:** ลด hallucination 35-60%
- **Effort:** 1 วัน

#### Priority 3: ATR-based SL + Position Sizing
- SL = `entry - 1.5 × ATR(14)` แทน % คงที่
- Position size = `(account × 1-2%) / (entry - SL)` แสดงให้ user
- Fractional Kelly 25-50% ใช้ calibrated win rate
- **Impact:** user value สูง, ลด stop hunt
- **Effort:** 1 วัน

#### Priority 4: Outcome logging + calibration
- Log ทุก plan: `(symbol, predicted_trend, conviction, entry, tp, sl, ts)`
- หลัง 7/14/30 วันเช็ค outcome → calibrate Conviction Score (Platt scaling/isotonic regression)
- **Impact:** Conviction Score มีความหมายจริง — 80% conviction ชนะจริง 80%
- **Effort:** 1 สัปดาห์ (เก็บ data ก่อน, model หลัง)

#### Priority 5: VIX/Sector context
- ดึง `^VIX`, `^VIX3M` term structure (VIX inversion = bullish)
- เปรียบเทียบ relative strength vs sector ETF (XLK/XLF/XLE etc.)
- 10Y-2Y yield spread เป็น regime filter
- ใส่เป็น context ใน prompt
- **Impact:** macro signal เพิ่มความแม่น
- **Effort:** 2-3 วัน

#### Priority 6 (PRO only): Self-consistency 3-vote
- เรียก Gemini 3 ครั้ง (temperature 0.3-0.7)
- Majority vote trend + average conviction
- ใช้เฉพาะ conviction > 75 (high stakes) — ประหยัด cost
- **Impact:** lift consistency, reliability
- **Effort:** 2 วัน

---

### B. New Capabilities (จาก agent B — top picks)

#### Tier 1: Drop-in replacements (ทำได้เลย)
| ของเดิม | เปลี่ยนเป็น | ประโยชน์ |
|--------|------------|---------|
| TA-Lib | **pandas-ta** (5.5k ⭐ MIT) | Pure Python, 150+ indicators, ติดตั้งง่ายกว่ามากบน Linux |
| `_analysis_cache` dict | **diskcache** (Apache 2.0) | Persist ผ่าน restart, ใหญ่กว่า in-memory |

#### Tier 2: เสริม signal quality
| Capability | Repo / Lib | License |
|-----------|-----------|---------|
| RSI/MACD divergence | [SpiralDevelopment/RSI-divergence-detector](https://github.com/SpiralDevelopment/RSI-divergence-detector) + [xoopsi/macd-divergence-detector](https://github.com/xoopsi/macd-divergence-detector) | reference code |
| Pattern recognition (H&S, double tops) | [keithorange/PatternPy](https://github.com/keithorange/PatternPy) | MIT |
| Sentiment from news | **Finnhub API** (free 60 req/min) หรือ [ProsusAI/finBERT](https://github.com/ProsusAI/finBERT) (Apache 2.0) | ฟรีทั้งคู่ |
| Backtest AI plans | [kernc/backtesting.py](https://github.com/kernc/backtesting.py) (AGPL) | verify entry/TP/SL ก่อนตอบ user — USP เด่น |

#### Tier 3: Data source diversify (อนาคต)
| Source | Free Tier | License | Use Case |
|--------|-----------|---------|----------|
| **OpenBB Platform** (31k ⭐) | ฟรี 100+ providers | AGPL | Aggregator yfinance+FMP+Polygon — ระวัง license ถ้า bot closed-source |
| **Finnhub** | 60 req/min ฟรีไม่จำกัด | API | Sentiment + insider data — เสริม Gemini context |
| **Twelve Data** | 800 req/วัน | API | หุ้นไทย (SET) ดีกว่า yfinance |

---

## 🎯 แผนที่แนะนำ (ลำดับเหตุการณ์)

### Phase 1 ✅ (ทำแล้ว) — Speed quick wins
- TTL cache + parallelize + progress message + pre-warm

### Phase 2 (1 สัปดาห์) — Accuracy core
1. Structured JSON output + CoT prompt (1-2 วัน)
2. Output validation layer (1 วัน)
3. ATR-based SL + position sizing (1 วัน)
4. AI prompt caching (Gemini implicit caching) (30-60 นาที)

### Phase 3 (1 สัปดาห์) — Data + signals
5. pandas-ta migration (1-2 วัน)
6. Finnhub sentiment integration (1-2 วัน)
7. VIX/sector context (1 วัน)
8. RSI/MACD divergence detection (1 วัน)

### Phase 4 (2 สัปดาห์) — Long-term value
9. Outcome logging + Conviction calibration
10. backtesting.py integration (verify plans)
11. Self-consistency 3-vote (PRO only)
12. Pattern recognition (H&S, double tops)

### Phase 5 (Big refactor) — Scalability
13. Sync→async migration: **AsyncTeleBot** (telebot built-in, ง่ายสุด) หรือ **aiogram 3.x** (full asyncio, MIT, fastest)
14. N+1 query fixes
15. Redis + **RQ** task queue (offload analyze จาก main loop)
16. **PgBouncer** transaction pooling ถ้า scale > 100 concurrent
17. Profiling: **py-spy** (live CPU) + **memray** (memory leak hunt)

## 🛠 Tools ที่ควร install เพิ่ม (ไม่บังคับ)

```bash
# Profiling — เปิดใช้เฉพาะ debug session
pip install py-spy memray

# ถ้าตัดสินใจ migrate aiogram
pip install aiogram asyncpg

# ถ้าตัดสินใจใช้ RQ
pip install rq redis
```

---

## 📚 Sources / References

- [DK-CoT-JSON: Knowledge-Enhanced CoT Strategy 2025](https://link.springer.com/article/10.1007/s10791-025-09573-7)
- [The New Quant — LLMs in Trading 2025 (arxiv)](https://arxiv.org/html/2510.05533v1)
- [P1GPT Multi-Agent Trading +16-31% blue chips (arxiv)](https://arxiv.org/pdf/2510.23032)
- [Hallucination Mitigation Survey (arxiv)](https://arxiv.org/html/2510.24476v1)
- [InvestorBench (ACL 2025)](https://aclanthology.org/2025.acl-long.126.pdf)
- [VIX Term Structure as Trading Signal](https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/)
- [pandas-ta GitHub](https://github.com/twopirllc/pandas-ta)
- [OpenBB Platform GitHub](https://github.com/OpenBB-finance/OpenBB)
- [Finnhub APIs](https://finnhub.io/)
- [Best Free Stock APIs 2026 (DEV)](https://dev.to/nexgendata/best-free-stock-market-apis-and-data-tools-in-2026-a-developers-honest-comparison-1926)

---

## 🎯 Decision rule
> **ถ้า user < 50** → focus ที่ Phase 1+2 (speed + accuracy core) เท่านั้น
> Phase 3+ ทำตอนมี user feedback ว่าฟีเจอร์ไหนต้องการเพิ่ม

#performance #accuracy #roadmap
