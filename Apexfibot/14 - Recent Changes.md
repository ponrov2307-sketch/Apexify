---
tags: [changelog]
---

# 📝 Recent Changes

> เรียงจากใหม่สุดลงล่าง — เก็บแค่ commits สำคัญ

## 2026-05-13 (เย็น) — Pre-Market + TL;DR + Glossary + Company Name (5 features)

### 🔔 Pre-Market Movers Cron (NEW · VIP+PRO · 20:30 ICT)
- ไฟล์ใหม่ `premarket_cron.py` (~250 บรรทัด)
- Time: 20:30 ICT (= 06:30 ET — 1 ชม. ก่อน US เปิด)
- Universe: ~80 tickers (Morning Movers + small cap)
- Filter: gap ≥3%, premarket vol ≥10K
- Hybrid format: 📌 watchlist match + 🌐 top 3 discovery
- Parallel scan ThreadPoolExecutor (12 workers)
- dispatch_log dedup per user/day
- Skip weekends + market holidays
- Config: PREMARKET_ENABLED/HOUR_ICT/MINUTE_ICT/MIN_GAP_PCT
- **Dry-run verified:** 74/75 tickers OK · 6 movers · 15 users processing

### ⚡ TL;DR Header (NEW · ทุก tier)
- บรรทัดแรกของทุก analyze message
- Free: `AAPL (Apple) $220 · แนวรับ · แนวต้าน`
- VIP: `NVDA (NVIDIA) $478 · 🟢 ขาขึ้น 3/3 ระยะ · Confidence 75%`
- PRO: `BUY EOSE (Eos Energy Enterprises) $8.10 · TP $9.25 · SL $5.78`
- 3 helpers: `_build_tldr_free/vip/pro` ใน `ai_analyzer.py`
- Live verified ผ่าน EOSE PRO analysis

### 📖 Glossary in /manual (NEW · ทุก tier · no new command)
- 14 คำศัพท์ใน existing `/manual`:
  - RSI · MACD · Golden Cross · Death Cross · EMA20/50/200
  - Support/Resistance · SL/TP · R:R Ratio · Bollinger Bands · POC
  - Conviction Score · Volume Ratio · Pre-Market/After-Hours
  - Cluster Buy · Gap Up/Down
- ใส่ก่อน "📞 ติดต่อ" — workflow ไม่ขัด

### 🏢 Company Name in Parens (NEW · ทุก ticker display)
- Helper `get_company_short_name()` ใน `bot_utils.py`
- Cache 24h, cleans suffixes (", Inc.", " Corporation" etc.), truncate ≤22 chars
- Apply 5 places:
  - TL;DR (Free/VIP/PRO)
  - Snapshot header (VIP/PRO)
  - Free report header
  - Pre-Market Movers DM
  - Screener top 10
  - Daily Picks admin DM
- Test results: AAPL→"Apple", NVDA→"NVIDIA", EOSE→"Eos Energy Enterprises"

### 📋 Tier Permissions Audit + Doc Update
- `03 - Tier Comparison.md` — sectioned restructure (Analysis/Alerts/Content/Trust)
- Added rows: Smart Money · Plan Proximity · Pre-Market · Glossary · TL;DR · Breaking News · Screener PRO
- `18 - Feature Cheat Sheet.md` — master table + Recent features section
- Admin-only features noted: Daily Stock Picker DM · Earnings Prep DM

### Commits (4 in evening session)
- `32d93bf` — feat: 3 customer-driven features (Pre-Market + TL;DR + Glossary + Tier docs)
- `b6040e7` — feat(display): add company name in parens to all ticker mentions

---

## 2026-05-13 (บ่าย) — Small Cap Day Trade Coverage (PP P. request)

### 🔥 Small Cap Universe Expansion
**Trigger:** ลูกค้า PP P. (paying PRO) feedback 15:06: *"อยากให้เห็นหุ้นเล็กๆด้วยค่ะเพราะคนเทรดรายวันส่วนมากเป็น small cap"*

### Files affected
- `daily_stock_picker.py` (Daily Picks 7:45 ICT)
- `alert_system.py` (Morning Movers 8:00 ICT)
- `smart_money_cron.py` — ✅ already OK ($5 min keeps small caps)

### What shipped

**Daily Picks pool: 70 → 110 tickers (+31 small cap)**
- AI small: TEM, HOLO, LAES, GFAI, SERV, KSCP
- Quantum: QUBT (เพิ่มจาก RGTI/QBTS/ARQQ เดิม)
- Space small: BKSY, SPIR
- Crypto mining: BTBT, BTDR, CIFR, IREN, WULF, HUT, CLSK
- AI Power / Nuclear: OKLO, SMR, LEU
- Materials: USAR, MP
- eVTOL: ACHR, JOBY
- EV small: GOEV, WKHS
- Defense: ONDS
- Biotech: NVAX, VKTX
- Political/meme: DJT
- Fintech small: DAVE
- Real estate tech: OPEN

**Morning Movers: 38 → 60 tickers (+22 small cap)** สำหรับ briefing 8:00

**🔥 Screener (PRO `hub_screener`): 200 → 225 tickers (+25 small cap)** — ลูกค้า PP P. clarified ตัวนี้คือที่ขอจริงๆ
- `SCREENER_SMALL_CAP_SET` (48 tickers): IONQ/RGTI/QBTS/ARQQ/BBAI/SOUN/NBIS/RKLB/ASTS/IRDM/PL/RXRX/EXAS/SAVA/AI/CLSK/CIFR/TEM/ALAB/CRWV/OKLO/SMR/LEU/BTBT/BTDR/IREN/WULF/HUT/ACHR/JOBY/HOLO/LAES/GFAI/SERV/KSCP/QUBT/BKSY/SPIR/USAR/MP/DJT/DAVE/ONDS/OPEN/NVAX/VKTX/GOEV/WKHS
- `SMALL_CAP_TOP_LIMIT = 4` — รับประกัน ≥ 6 mega/large cap ใน top 10 (ป้องกัน small cap ครองกระดาน)
- Rebalance: เรียง score → ดึง 10 แต่ skip small cap ถ้าเกิน limit
- Tag `🔥small cap` หลังราคา
- Subtitle "mega + small cap คละกัน · small cap N/4 ตัว"
- Footer warning เฉพาะตอนมี small cap จริง
- Scan time: 200 → 225 ตัว = +12.5% (~8s → ~9s) ไม่กระทบ UX

**New sector taxonomy + hooks:**
- 6 sectors ใหม่: `mining` ⛏️ · `power` ⚛️ · `evtol` 🛩️ · `materials` 💎 · `retech` 🏠 · `meme` (enhanced) · `defense` (enhanced)
- Hook templates BULL/BEAR/FLAT ครบ 7 sectors ใหม่
- ตัวอย่าง: "BTC ขึ้น mining stocks วิ่งตาม" · "Trump nuclear push ดันเชื้อเพลิงสะอาด" · "eVTOL กำลังจะ commercial launch?"

**Scoring relaxed for small cap:**
- Outlier cap: 25% → **35%** (small caps วิ่ง 25-35% เป็นเรื่องปกติ)
- Pump penalty threshold: 15% → **22%**
- Bonus **+3 score** ถ้า small cap มี `vol_ratio > 2` (real breakout, ไม่ใช่ random noise)

**Visual differentiation:**
- DM tag `🔥small cap` ติดข้าง ticker
- Warning line: `⚠️ small cap — volatility สูง, ใช้ size เล็ก, ตั้ง SL เคร่ง`
- Mega cap ไม่มี warning → mix ยังคงอยู่ ("คละๆกัน" per request)

**Sample size:** 40 → 50 (pool โต 70 → 110)

### Test verified (dry run)
- ✅ OKLO ⚛️ — sector "power" + nuclear hook + 🔥small cap tag + warning
- ✅ BTBT ⛏️ — sector "mining" + BTC correlation hook + warning
- ✅ NVDA 🏛️ — mega cap, no warning, ปกติ (mix retained)

### Marketing implication
Confirms persona P13 "น้องโจ" (momentum trader) + P14 "พี่บิ๊ก" (options buyer) — pay segment ที่เน้น volatile catalyst plays. Daily Picks ตอนนี้ครอบคลุม Mag 7 → small cap day trade ในข้อความเดียว

---

## 2026-05-12 (เย็น) — Smart Money + Proximity Warning + News Anti-Spam + Brand Polish

### 🐳 Smart Money Tracker (NEW cron 16:00 ICT)
- ใหม่ `smart_money_cron.py` — daemon thread daily 16:00 ICT
- Source: **OpenInsider.com** latest-cluster-buys + SEC EDGAR Form 4 (T+2 day filing, 100% reliable)
- Filter chain:
  - Value ≥ $500K
  - Price ≥ $5 (skip penny)
  - Trade ≤ 14 วันที่ผ่านมา (fresh only, กัน signal เก่า 1-2 เดือน)
  - Skip "Blank Checks" / "Petroleum & Petroleum Products" industries
- Classify signals: 🐳 Mega Buy (≥$5M) · 🔥 Cluster x4+ · 📈 Cluster x3 · 💎 Big Buy · 📊 Notable
- Admin DM: top 8 by value
- PRO DM: เฉพาะ ticker ที่อยู่ใน user's watchlist (premium signal)
- **Per-signal dedup**: `smart_money_admin:{ticker}:{trade_date}` + `smart_money_pro:{ticker}:{trade_date}:{user_id}` → ไม่ส่ง cluster เดิมซ้ำ
- ทดสอบ 12 พ.ค.: 100 fetch → 61 quality → 19 fresh — top includes PSUS $70M (7 insiders), AHCO $24M, PLSE $13M (1 วันก่อน)

### ⚠️ Plan Proximity Warning (NEW poll 5 min)
- ใหม่ `plan_proximity_cron.py` — เตือน PRO ก่อนราคาใกล้ SL/TP/Entry zone
- **Scope:** เฉพาะหุ้นที่ user **ถือจริงในพอร์ต** (`shares > 0`) — ไม่ใช่ทุก scan
  - JOIN analysis_plans × portfolios → user ที่ scan แต่ไม่ซื้อ ไม่โดน spam
- Thresholds: SL ±1.5% · TP1/TP2 ±1.0% · Entry zone ±1.0%
- Direction validation: BULL → SL warn เฉพาะตอนยังไม่ทะลุ SL · BEAR → reverse
- Cooldown: 1 ชม./plan/level (in-memory)
- Price cache 2 min/symbol (ลด yfinance calls)
- DM tone: soft, ให้ option (ขายตามแผน · ถือยาว · adjust · DCA · re-analyze) — ไม่บังคับ
- DM แสดง position + P&L%

### 🚨 News Anti-Spam 3-Layer
**Problem วันนี้:** CPI day → 12+ alerts ใน 3 ชม. ทั้งเรื่อง CPI/Iran (ซ้ำซ้อน)

**Fix:**
- **Layer 1: Per-user throttle 60 min** (was declared 30 min แต่ไม่ใช้)
- **Layer 2: Topic dedup Jaccard ≥ 45%** ใน 6 ชม. window
- **Layer 3: Per-topic daily cap 2/วัน**
  - Topic keys: `macro:cpi/ppi/fed/...` · `geo:iran/china/war/...`
- ทดสอบกับ 12 ข่าวจริงวันนี้: **12 → 5** (-58%)

### 🏷 Brand Polish — "AI" → "Apexify" (Option B)
- 10+ user-facing strings ใน main.py: pronoun "AI = ตัวบอท" → "Apexify"
- proximity DM: "แจ้งให้รู้ ไม่บังคับ" → "เป็นแนวทางให้คุณพิจารณา"
- Heading: "ทำไมเตือน?" → "เหตุผลที่แจ้งเตือน"
- เก็บไว้ตามเดิม: feature names (AI Trend Radar / AI Verdict / AI plans) · tech disclosure (Google Gemini AI) · brand "Apexify Trading AI" · marketing docs (FB/TikTok templates คงเดิม)

---

## 2026-05-12 — Cron Engine + News Diversify + Funnel Fix + Tutorial Tracking

### Bot cron + automation (6 features ใหม่)
- ☀️ **Daily Stock Picker** — daily 7:30 ICT DM admin 3 หุ้น + chart + suggested FB hook
  - Pool: Mag 7 + S&P 500 + 30 story stocks + 23 hot movers (~200 ตัว)
  - Composite score: momentum + volume + RSI + fresh news bonus (≤6h = +15)
- 🌅 **Daily P&L Recap PRO** — daily 8:00 ICT DM PRO sliders watchlist + news ≤24h
- 📅 **Earnings Prep** — daily 16:00 ICT DM admin 1 วันก่อน earnings (~50 ticker pool)
- 📬 **Auto-DM Cron** — daily 11:00 ICT activation + win-back (50/day, 30-day cooldown)
- 📊 **Plan Evaluator** — auto /run_outcomes ทุก 6 ชม. (เคยรอ admin manual 5/30 วัน)
- 💓 **Heartbeat watchdog** — write `/tmp/apexify_heartbeat.txt` every 60s + cron */5 min DM admin ถ้า stale

### News diversify (less war dominance)
- War keywords (`war/missile/attack/invasion`) ลงเป็น T2 (Gemini decides)
- Company news (Tesla recall, Nvidia surge, earnings beat) เลื่อนขึ้น T1
- เพิ่ม 4 RSS sources: CNBC-Tech, Yahoo Finance, Investing.com, Seeking Alpha
- Reuters Google News query กว้างขึ้น (+ tech, earnings, tariff, chip, AI, 2h window)
- Tier 2 ใหม่: AI chip, semi, ChatGPT/OpenAI, iPhone, China/yuan/yen, Bitcoin

### Dashboard CTA funnel fix
- `quota_exceeded` → /payment?tier=vip (เดิม / → CTR 0%) — high-intent moment
- `analysis_result` label specific "🔔 ติดตาม {SYM} ในเว็บ" (เดิม generic)
- Funnel data จาก dashboard_events table guided fix

### Audit + admin tools
- 📜 **subscription_history table** + log_subscription_event() helper
  - track: paid/redeem/admin_grant/tier_reward/expire/abnormal_slip
- 🔍 **/user_log {uid}** — timeline ของ subscription changes
- 📊 **/dm_stats** — auto-DM conversion stats
- 🆔 **Slip auto-detect role** — payment slip มา → upgrade ตรง tier ทันที + audit log
- 🚨 **Abnormal slip handling** — log to history + better err message (package list + admin contact)

### Critical fixes
- **PRO→VIP downgrade bug fixed** (commit 54b15bc):
  - Customer Neil + Nattanon ที่ paid PRO แล้ว redeem SILVER code = ถูก downgrade VIP
  - Root cause: `add_subscription` UPDATE role โดยตรงไม่เช็ค hierarchy
  - Fix: เพิ่ม `_ROLE_RANK` + guard + stacking ตลอดถ้า current_expiry > now
  - Restored ทั้ง 2 customers
- **Markdown bug ใน /manual** — `user_id` ใน italic block ตัด parse → ส่งเงียบ
  - Fix: escape `\_id` + `_safe_send_part()` fallback to plain text

### /หุ้นเด่น expansion + scoring boost
- Pool: 150 → ~200 tickers (เพิ่ม 30 story + 23 hot movers)
- Momentum bonus: close_vs_ema20 ±5% = +80, ±3% = +40
- Volume bonus: vol 3x = +50, 1.8x = +25
- ผลลัพธ์: ไม่ซ้ำ blue-chip ตลอด — story stocks ติด top 10 ตอน momentum วิ่ง

### Alert system tune
- Mon/Tue 20:30-21:00 ICT "chaos hour" — threshold สูงขึ้นชั่วคราว
- Whipsaw block — 45-min cooldown ทิศทางตรงข้าม
- Whale alert: ต้องมี price confirmation (move ≥ 0.3%) ก่อน — กัน vol-but-no-move noise

### Web tutorial tracking
- 4 new events: `tutorial_started` / `tutorial_step_viewed` / `tutorial_completed` / `tutorial_skipped`
- Fix latent bug: onClick={dismiss} ส่ง MouseEvent (truthy) เป็น `completed` arg → กลับลำการตัดสินใจ
  - Arrow wrappers ทุกที่ + dismiss(completed: boolean)

### Web visible updates
- 🌡️ **Heatmap redesign jumpquant-style** (`/heatmap`) — S&P 500 cleaner look + correlation matrix
- 🏆 **Track Record card** ย้ายไป /analytics (placement) + Conservative methodology disclaimer
- 🎟️ **Redeem code form ใน dashboard** — สวยขึ้น (compact mode)
- 🥇 **Tier Badge progress pill** — แสดงแม้ยังไม่ได้ badge (เห็น progress)
- 🔁 **Tier threshold sync bot ↔ web** — Bronze 3/Silver 15/Gold 50/Diamond 21
- 🔧 **API: /api/me/* router** — mirror conversion features ของ bot ลงเว็บ

### Bot UX polish
- 🔥 **/track Recent Wins** — แสดง top wins (dedup + cap outlier >100% = filter false data)
- 🎯 **/setalert guided form** — 3 popular tickers picker + step-by-step (UX ดีขึ้นจาก raw text)
- 📱 **Dashboard CTA push ใน 7 commands** — `/del /edit /watch /unwatch /delalert /compare /portfolio` error responses มีปุ่ม Dashboard
- 🐳 **Whale message clarity** — "vol 5 นาที X.Xx · ราคา +Y.YY%" (เดิม cryptic)
- 💰 **Top-up 20฿ copy** — ปรับ pitch ให้ low-stake mention "10 ครั้ง = 2฿/ครั้ง"
- 🎁 **/freetrial CTA button** ใน /start tutorial (CTR เพิ่มจากเดิมที่ user ไม่เห็น command)

---

## 2026-05-10 ⭐⭐⭐ MEGA SPRINT — 7 Conversion Levers + Web Mirror + Track Record Fix

> Daily log: [[2026-05-10]] (full breakdown — 27 bot commits + 8 web commits)

### Conversion Stack (push 7 levers ตามที่ user ขอ)
- **News Grounding** — Gemini เห็นข่าวรายหุ้นก่อนวิเคราะห์
- **Apexify Confidence Score** — 0-100% deterministic
- **Smart Paywall** — preview ของ ticker + flash + social proof + track record + redeem field
- **Top-up 20฿/10 ครั้ง** — pay-per-use pay-as-you-go
- **Annual marketing** — "ฟรี 2 เดือน · ประหยัด 158/218฿"
- **Flash Discount 30 min** — auto-trigger เมื่อ free โดน paywall
- **Code-based discount** — admin /gencode pct% + window — user redeem opens window
- **Chart preview 3 ครั้ง** — free user wow moment + last-shot urgency
- **Tier Badges** Bronze/Silver/Gold/Diamond — auto-grant codes + DM celebration
- **Sunk cost / Anchoring / Scarcity** — text in /me + menu_vip
- **3 cron DMs** — daily reset (7:00) / streak loss (18:00) / lapsed trial (14:00)

### Intraday Alerts (whale latency 5-6 ชม. → 5-10 นาที)
- Whale (5m bar 3x avg) · Breakout intraday · Gap Open (>2% in 30m) · Price Acceleration (>3% in 30m)
- Module ใหม่ `intraday_volume.py` + market session 7 ตลาด

### Chart Vision + Personal Memory + Earnings Revamp
- Chart Vision: VIP/PRO ส่ง chart screenshot → Gemini Vision อ่าน
- Personal Memory: bot จำ holdings/watchlist → personalize prompt + render
- Earnings: ดึง Revenue/YoY/history + inject news + structured verdict 0-10

### Track Record (Backtest Proof) — เจอ critical bugs + fix
- **`1c806ba`** SQL `INTERVAL '%s hours'` syntax — silent fail 2+ สัปดาห์
- **`25025ed`** TZ-aware (US/Eastern) vs naive (DB) datetime — TypeError บน 118 symbols
- **`b6c75e5`** Same-day TP/SL → optimistic → fix conservative (`<=`)
- **`7b629ab`** ⭐ Entry-not-filled → false TP1 hit (98% เวอร์มาจากนี่)
  - Fix 2-phase: Phase 1 wait entry fill / Phase 2 TP/SL after fill
  - เพิ่ม `no_entry` outcome (≥14 วันยังไม่ฟิลล์ → mark)
- /track + Web TrackRecordCard แสดง realistic Hit Rate excluding no_entry

### Admin Tools (sprint นี้)
- /whoami /plansdebug /userdebug /reset_quota /backfill_analyses /run_outcomes /reset_outcomes
- /gencode extended (days mode + discount % mode + custom name)

### Web Dashboard Mirror (ApexifyWebmaster)
- `/api/me/*` 5 endpoints (profile, track-record, redeem, discount-state, notifications)
- Tier Badge (header pill) · Track Record Card (analytics) · Redeem form (payment, premium UI)

### Commits ใน bot (เรียง chronological)
```
5de6f9c news grounding
e0ef67a whale intraday
03baa0a confidence + Apexify rebrand
94afb74 smart paywall
30d8cc9 breakout/gap/accel intraday
7c0dc18 top-up + annual
4306fd4 chart vision + memory
9f11e97 tutorial chart leak
1349804 chart preview 3x
a18e8b9 compact news + cleanup
f0d147c earnings + flash + social
36580b4 payment_type tracking
793ce8f code-based discount
8d8b56b backtest proof track record
e566309 7 conversion levers (badges/sunk/anchor/scarcity/3 DMs)
588d643 admin counts toward tier + plansdebug
11b1338 ลด threshold + backfill_analyses
5f1f55b ACK non-admin + whoami
331f614 admin skip code (DM spam)
8e63d6f userdebug + reset_quota + Diamond 14→21
4ffe17a admin guide updated
1c806ba SQL bug ⭐ track record critical
b249b63 verbose run_outcomes
25025ed TZ + markdown
b6c75e5 conservative outcome
9df52ed bundle: H1+M1+M3
7b629ab entry-filled-first ⭐ root cause 98% เวอร์
```

### Commits ใน web (ApexifyWebmaster)
```
61acc87 /api/me/* router
acc0a40 tier badge + track record + redeem
8415dbe progress pill compact
7bb1b74 + 2c226a8 thresholds sync
9d72dc6 conservative disclaimer
54c097a no_entry support
69f9779 ย้าย Track Record ลงล่าง + Redeem premium UI
```

---

## 2026-05-03 (Webmaster Dashboard Section + Commodity Spot + Quality Fixes)

> Daily note: [[2026-05-03]]

### `f26b8c9` — Webmaster section ขยายเต็มสูบ ⭐⭐⭐
**User บอก iteration แรกดึงข้อมูลน้อย → ขยายเป็น 8 stats + 4 cross-user panels**

**8 stat cards (2 rows):**
- Row 1: Total txn · Growth WoW % · Active 7d/30d · Buy/Sell ratio
- Row 2: Proof% · Storage bytes · Realized P&L · Dividends

**4 panels:**
- Top 8 traded tickers (lime/cyan)
- Top 8 cross-user holdings จาก `portfolios` (magenta/amber)
- Top 5 brokers (NULL/empty → "Manual")
- Currency split USD/THB bar (amber)

ทุก query try/except → fail-soft, missing table = 0 ไม่ break section

### `a064685` — Webmaster section iteration 1 ⭐⭐
**Bot และ ApexifyWebmaster ใช้ Supabase project เดียว** → admin dashboard ดึง cross-user data ตรงผ่าน psycopg2 (ไม่ต้องผ่าน API)

- Panel ใหม่ระหว่าง "สัดส่วนระดับสมาชิก" และ "heatmap รายชั่วโมง"
- 4 stat cards: Total txn / Active 7d / Proof% / Dividends
- Top-5 most-traded tickers (gradient bar)
- `get_webmaster_metrics_snapshot()` ใน admin_service.py — single connection, fail-soft (returns `available=false` ถ้า migrations ยังไม่ run)
- Added to parallel ThreadPool ใน `get_admin_dashboard_snapshot()` ไม่กระทบ cold-load

### `e4fecd1` — Critical bugfixes admin dashboard ⭐⭐
**2 บั๊กไม่เกี่ยวกันทำหน้าเปล่า**

**JS Temporal Dead Zone**
- `const TC` + `chartOpts` ประกาศที่ line 1635 แต่ใช้ที่ 1539 (`renderWinRateTrend`)
- Hoisting ไม่ช่วย const → `ReferenceError: Cannot access TC before initialization`
- Throw ที่ไหน script จุดนั้นหยุด → heatmap, 30-day charts, win rate trend ทั้งหมดเปล่า
- Fix: ย้าย TC + chartOpts ขึ้นไปก่อน renderWinRateTrend

**SQL string vs timestamp**
- `users.expiry_date` schema เป็น TEXT
- Funnel query เขียน `expiry_date > NOW()` → string compare → paying_now/vip_now/pro_now = 0
- Fix: cast `expiry_date::timestamp > NOW()` ทั้ง active paying + churned-30d

### `20d92d1` — Commodities ใช้ futures (=F) ⭐
**User บอก "GLD $420 ไม่ใช่ราคาทองจริง"** — ETF tracking ≠ spot

- gold/ทอง → **GC=F** ($/oz, ~$4,629)
- silver → SI=F ($/oz)
- oil/น้ำมัน → **CL=F** ($/barrel, ~$101.94)
- gas → NG=F ($/MMBtu)
- copper, platinum, palladium → HG=F / PL=F / PA=F
- ETF ticker ที่ user พิมพ์เอง resolve เป็น ETF + warning ใน description ว่า "ใช้ `gold`/`oil` ถ้าอยากเห็นราคาจริง"

### `6134730` — 3 quality fixes
1. **Commodity/crypto description line** — GLD/SLV/USO/BTC-USD ฯลฯ แสดง "🥇 ETF ทองคำ — เคลื่อนไหวตามราคาทองโลก" ใต้ ticker
2. **Flash News drop Thai source** — เน้น US markets, เพิ่ม MarketWatch
3. **Audio narration ยาวขึ้น** — Gemini produce field `audio_script_th` (4-6 ประโยค, 250-400 chars) แยกจาก `summary_th` (Telegram 80 ตัว) → clip เสียงอธิบายเต็ม

### `cb86261` — 3 quality fixes (earnings/compare/alert)
- earnings nan handling
- /compare deeper metrics
- alert retry hardening

### `03d234d` — Commodity friendly aliases (rolled into 20d92d1)
- กฤษ/เงิน/น้ำมัน/btc → mapping (later changed to futures)

---

## 2026-05-02 → 05-03 (Admin UI Overhaul + Reliability Sweep)

### `6616be8` — Maintenance broadcast parity
- /maintenance ในบอท ส่งข้อความหา user ทุกคนเหมือน admin dashboard
- ย้าย `broadcast_maintenance_notice()` ไป `bot_utils.py` (single source)
- ทั้ง 2 จุดใช้ helper เดียวกัน ส่ง "ปิดปรับปรุง" / "กลับมาใช้งานได้แล้ว"

### `aa69683` — Thread locks + Gemini timeout + maintenance broadcast feature ⭐
**Race conditions fixed**
- `_sent_news_lock` กัน "Set changed during iteration" บน sent_pro_news
- `_rss_cache_lock` กัน read-during-write
- ใช้ snapshot pattern (อ่านนอก lock หลัง copy)

**Gemini timeout** — `_gemini_call_with_timeout()` ใน ai_analyzer.py
- ThreadPoolExecutor + future.result(timeout=30s) — กัน handler hang
- Image analysis 45s

**Maintenance broadcast** — admin dashboard ปุ่ม toggle ส่ง broadcast ทุกคนใน background

### `369fa24` — Audit polish #5/#6
- ai_analyzer retry loop: log retry failure + final exhaustion
- Digest news 3 silent paths now log reason (`bad JSON / non-list / empty list`)
- yfinance N+1 batch: get_podcast_market_data + _get_morning_macro_assets_text
  - Loop 10 ticker.history() → single yf.download(syms, threads=True) ~5-10x faster

### `473e757` — 4 polish fixes ⭐⭐
- **Earnings dedup**: new table `earnings_notified(user_id, symbol, notify_date)` — กัน 7:59 → 8:00 restart ส่งซ้ำ
- **Telegram retry**: new `bot_utils.py` `safe_send_with_retry()` — handle 429/timeout/5xx, auto-mark inactive on 403
- **Friendly Thai errors**: 18 sites in main.py — แทน `f"❌ Error: {e}"` ด้วย `friendly_error("...")` + log raw server-side
- **Quiet hours earnings**: เช็ค `should_send_user_notification('digest_news')` ก่อนส่ง 8 AM earnings

### `b6e738a` — Persist alert state ⭐ (fix duplicate alerts after restart)
- Customer PP P. รายงาน RSI/EMA/Breakout/Whale alert ส่งซ้ำหลัง restart
- Root cause: `last_alert_state` เป็น in-memory dict reset เป็น {} ทุก restart
- Fix: new table `alert_state(symbol, kind, state)`
- `_set_alert_state()` save เฉพาะตอน state เปลี่ยน
- `_hydrate_alert_state()` โหลดจาก DB ตอน startup

### `5d98ab4` — Admin dashboard expand monitoring + Thai + softer palette ⭐⭐⭐
**4 features ใหม่**
- Win rate trend chart (rolling 7d + daily overlay จาก alert_logs)
- Top commands table (`bot_command_log` + listener ใน main.py)
- Alert delivery rate (`broadcast_log` + auto-log จาก /admin/broadcast)
- Free quota burn (count free users at 3/3 + top burners list)

**Backend**: 7 new admin_service functions (recent_activity, hourly, funnel, top_commands, alert_delivery, quota_burn, win_rate_trend) — ทั้งหมด parallel ใน thread pool

**Thai translation**: ทั้งหน้า (sidebar, topbar, banners, stats, modals, JS messages)

**Palette softened**: Gruvbox warm beige `#BDAE93` แทน `#D4D4D4` แสบตา · accents desaturated · CRT scanlines เบาลง

### `43fa0dd` — Admin dashboard Claude design + 30 broadcasts (พื้นฐานก่อน redesign เป็น terminal)
- เริ่มต้น: redesign จาก dark GitHub → Claude warm cream (Source Serif + coral)
- ภายหลังเปลี่ยนเป็น Terminal UI ตาม customer feedback ("พื้นหลังขาวแสบตา")
- เพิ่ม 20 Web Dashboard broadcasts (WD11–WD30) ใน [[21 - Broadcast Templates]]

---

## 2026-05-01 (Trade Plan v2 + News Resilience)

> ดู daily note: [[2026-05-01]]

### `a811065` — News: Gemini fallback chain + stale-cache-on-overload ⭐
- **Root cause** — gemini-2.5-flash 503 บ่อยช่วง US market open
- เพิ่ม fallback chain: `flash → flash-lite → pro` (เดิมมีแค่ flash)
- Stale-cache-on-overload — ถ้า fetch fail แต่มี cache ≤4 ชม. ใช้ cache แทน error
- Error message สุภาพขึ้น (ไม่ dump 503 stack trace ให้ user เห็น)

### `57411f1` — News: per-ticker timeout + 30-min cache
- `yfinance.Ticker.news` ครอบ 8s timeout (เคยค้างหลายนาที)
- `portfolio_news` ครอบ 25s asyncio timeout per ticker
- Summary cache 30 นาที per ticker — refresh = instant

### `08fbb9f` — Hotfix: NameError concurrent not defined
- `_build_portfolio_context` ใช้ `concurrent.futures.ThreadPoolExecutor` โดยไม่ import
- แก้โดย import inline match pattern กับ `_fetch_earnings`

### `f4c4c91` — Trade Plan v2 (Phase 1 + 2) ⭐⭐
**Phase 1 — Actionable**
- Reasons แปลเป็นไทย ผ่าน i18n keys
- Position sizing line (`▸ ขายออก 33% ที่ TP1 · อีก 50% ที่ TP2`)
- Concentration warning — badge ถ้าหุ้น ≥25% (warn) / ≥40% (danger)
- Apply Plan wizard — กดเดียวตั้ง 3 alerts (TP1/TP2/SL) + USD currency-safe

**Phase 2 — Insight Badges**
- Catalyst detector — เตือน earnings ใน ≤14 วัน
- Volume confirmation — surge/high/thin badge เทียบกับ 20-day avg
- Confidence breakdown — กด C-score → expand factors (Trend, Action, R:R)

**Backend ใหม่:**
- `batch_get_volume_pulse()` — batch volume vs 20d avg
- `/api/market/portfolio-context` — earnings + volume parallel, cache 10min

ดู [[2026-05-01]] สำหรับรายละเอียด

---

## 2026-04-24 (Sprint Day)

### `f17c462` — Command Discoverability ⭐
- `bot.set_my_commands()` ตอน startup → Telegram dropdown เมื่อพิมพ์ `/`
- Contextual quick-action buttons หลังวิเคราะห์:
  - VIP/PRO: 📊 Fundamentals + 📈 งบการเงิน
  - PRO: ⚖️ เปรียบเทียบ
- Hub menu จัดหมวดใหม่ 4 กลุ่ม
- เพิ่ม tip: "พิมพ์ / เพื่อดูคำสั่ง"
- ดู [[16 - Command Discoverability]]

### `e44eaf4` — Daily Streak + Fundamentals + Compare
- 🔥 Daily Streak: ครบ 7 วัน = +1 วัน VIP ฟรี
- 📊 `/fund <symbol>` — P/E, EPS, Dividend, 52W (VIP/PRO)
- ⚖️ `/compare A B [C]` — side-by-side + AI verdict (PRO)
- ดู [[15 - Roadmap]] section Done

### `88dd65e` — Referral v2
- New user สมัครผ่านลิงก์ → VIP 3 วันฟรีทันที (ใหม่!)
- Telegram native share button (`switch_inline_query`)
- ปรับข้อความ menu_referral ให้ชัด

ดู [[10 - Referral System]]

### `d3fa065` — Thai Quality Guard + Prompt Caching
- เพิ่ม `THAI_TYPO_FIXES` dict — แก้ "เกรงทึ่ง"→"แข็งแกร่ง", "ทดฐาน"→"ทดสอบฐาน" ฯลฯ
- ใช้ใน PRO report + Flash/Digest News
- แยก static rules → `system_instruction` (Gemini 2.5 implicit cache)
- เพิ่ม `temperature=0.3` + `response_mime_type=application/json`

ดู [[07 - AI System]]

### `b57491a` — Weekly Digest + Economic Calendar
- ทุกวันศุกร์ 18:00 ส่ง VIP/PRO:
  - Watchlist WoW
  - Personal Plan outcomes (PRO)
  - Track Record 30 วัน (global)
  - AI Economic Preview สัปดาห์หน้า
- Admin command `/force_weekly` ทดสอบได้

ดู [[08 - Alert System]]

### `e5f187f` — PRO Chart redesign
- Light theme: พื้นขาว + แท่ง teal/coral mute
- Labels แสดงราคาจริง: `🎯 TP1 $11.61 (+11.9%)` (เดิมแสดงแค่ %)
- ENTRY แสดงเป็น range: `📍 ENTRY $9.99–$10.20 (-2.7%)`
- bbox สีเต็ม + ตัวอักษรขาว (contrast สูง)

### `1f7daa4` — Track Record System ⭐
- New table `analysis_plans`
- Auto-log ทุก PRO Plan
- Cron 6:00 น. → `check_plan_outcomes()` ตรวจ TP1/TP2/SL hit
- Command `/track` แสดงสถิติ
- **Bugfix**: Gemini 2.0-flash deprecated → ใช้ 2.5 family ทั้งหมด

ดู [[09 - Track Record System]]

### `36473ae` — Free quota + Inline Upsell + Renewal v2
- Free quota: 10 → 3 ครั้ง/วัน
- ใช้ constant `FREE_DAILY_QUOTA = 3`
- Quota-hit message มี inline buttons (สมัคร VIP/PRO/free trial/code)
- Renewal reminders: 7/3/1 วัน + escalation icons + inline buttons

### `a5d76bc` — PRO chart labels improvement
- ย้าย labels เข้ากราฟ (กัน clip)
- ใช้ `blended_transform` + ขนาดใหญ่ขึ้น 11pt
- เพิ่ม emoji + bbox border หนา

### `bbbbfc2` — send_podcast admin fix
- เพิ่ม ADMIN_ID injection ใน standalone broadcast

### `bdca3cb` — Chart improvements + Admin = PRO ⭐
- **Critical bugfix**: `check_subscription()` return 'pro' สำหรับ admin
  - เคย: admin's price alerts ถูก auto-deactivate ทุกครั้ง!
- Chart auto-scale Y-axis (TP2 outside chart fixed)
- เพิ่ม labels TP1/TP2/SL พร้อม % ที่ขอบ
- Dedupe เส้นซ้ำ (resistance ≈ TP1)

### `7031f20` — Tier-specific charts
- Free: ไม่มีกราฟ + upsell CTA
- VIP: กราฟ basic
- PRO: กราฟ annotated เฉพาะ + Entry zone/TP/SL marks

### `daf676f` — Premium VIP/PRO redesign
- Tier split ชัดเจน
- เพิ่ม Watch Next + Confirmation/Invalidation + Time Horizon
- Position Sizing tip

### `763ee65` — Analyze flow harden + .BK fallback
- พิมพ์ `PTT` → ลอง `PTT.BK` อัตโนมัติ
- Wrap `generate_apexify_report` กัน Gemini crash
- Friendly error message แทน raw exception

### `a57eebd` — Gemini 503 retry hardening
- Retry 4 ครั้ง + exponential backoff (20→320s)
- Fallback model chain
- 503 Flash/Digest news → silent skip (ไม่รบกวน admin)

## Earlier (ก่อน sprint)

### `1d15495` — Analysis report redesign
- โครงสร้างใหม่ของ PRO/VIP report

### `9ee67ee` — Bearish plan = ซื้อหุ้น (ไม่ใช่ short)
- หลักการ: บอทนี้สำหรับซื้อหุ้น
- bearish bias → รอจังหวะซื้อที่แนวรับลึก, TP > Entry

### `92a3e76` — Pricing update
- VIP=79/790, PRO=109/1090

### `c3e143c` — Migration cascade fix
- ALTER TABLE แยก try/except ป้องกัน cascade timeout

ดูต่อ:
- [[15 - Roadmap]]

#changelog
