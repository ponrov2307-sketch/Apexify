---
tags: [backlog, todo, planning]
updated: 2026-05-13
---

# 📋 To-Build Backlog (สิ่งที่จะทำ + ที่เลือกได้)

> สรุป: รวมทุก feature idea ที่ค้างอยู่ — แยกเป็น "ยืนยันจะทำ" / "รอเลือก" / "ตัดสินใจไม่ทำ"
> ใช้หน้านี้คืนนี้เลือกว่าจะทำอะไรต่อ

> ⚠️ Audit แล้ว 2026-05-13: features ที่มีอยู่จริงในระบบดูที่ [[18 - Feature Cheat Sheet]] (ใหม่กว่าครั้งก่อน) — ของในนี้ = "ยังไม่มี/รอตัดสินใจ" เท่านั้น

---

## ✅ ทำเสร็จ 2026-05-13 (5 features)

### ~~Small Cap Day Trade Coverage~~ ✅ **DONE** (commits 1e165ef + 4b7473c + f0d9970)
- Daily Picks pool 70→110 · Morning Movers 38→60 · Screener 200→225
- Quota logic: try to fill 4 small + 6 large in Screener top 10
- Risk: 🔥small cap tag + warning line
- Trigger: PP P. (paying PRO) feedback

### ~~Pre-Market Movers Cron~~ ✅ **DONE** (commit 32d93bf)
- New `premarket_cron.py`, VIP+PRO, 19:30 ICT daily Mon-Fri (DST · winter 20:30 ICT)
- Hybrid: watchlist matches + top 3 discovery
- Dry-run verified 18:30 ICT

### ~~TL;DR Header~~ ✅ **DONE** (commit 32d93bf)
- All tiers, 1-line summary at top of every analyze
- Free/VIP/PRO each have tailored format

### ~~Glossary in /manual~~ ✅ **DONE** (commit 32d93bf)
- 14 terms in existing `/manual` button (no new command per user constraint)

### ~~Company Name in Parens~~ ✅ **DONE** (commit b6040e7)
- `bot_utils.get_company_short_name()` cached 24h
- Applied 6 places: TL;DR / snapshot / Free header / Pre-Market / Screener / Daily Picks

---

## ✅ ทำเสร็จแล้ว (2026-05-12 เย็น)

### ~~Smart Money Tracker~~ ✅ **DONE** (commit 2560d2d + bb49545)
- ใช้ OpenInsider + per-signal dedup + 14-day fresh filter
- Daily 16:00 ICT cron — admin + PRO watchlist match
- Verified 100 fetched → 19 fresh signals

### ~~E1 Stop-loss Proximity Warning~~ ✅ **DONE** (commit abb6bba + ed14121 + 165db9c)
- Poll 5 นาที, portfolio-only filter, soft DM tone
- SL ±1.5% · TP ±1.0% · Entry ±1.0% · cooldown 1 ชม.

---

## 🟡 รอตัดสินใจ — เลือกได้ตอนต้องการ

### Bot enhancements (ของที่มีอยู่ → ปรับปรุง)

~~**E1. Stop-loss Proximity Warning**~~ ✅ **DONE** (2026-05-12)

**E2. /compare ขยาย 2 → 4 tickers + UX**
- ปัจจุบัน: `/sp500` page รองรับ 2 ticker (stock duel) + bot `/compare` 2 ตัว
- ปัญหา: user บอก "ได้แค่ 2 ตัว ไม่ค่อยโอเค"
- Upgrade: รองรับ 3-4 ticker overlay + table metrics side-by-side
- Effort: ~4 ชม. (frontend chart series + backend support)
- Files: `frontend/src/app/(dashboard)/sp500/page.tsx`, `api/routers/market.py`

### Bot capabilities ใหม่ (ยังไม่มีในระบบ)

~~**B-new1. /feedback command**~~ ✅ **มีแล้ว** — ปุ่ม "ติดต่อแอดมิน" ใน /contact + abnormal slip flow (ลบ 2026-05-12)

**B-new2. Personal Activity Stats**
- /me หรือ /track เพิ่ม "คุณวิเคราะห์ 12 หุ้นสัปดาห์นี้ · TSLA ดูบ่อย 5 ครั้ง"
- จาก Roadmap "Next" ยังไม่ได้ทำ
- Effort: ~2 ชม. (query bot_command_log + format)

**B-new3. Sector Rotation Alert (weekly Mon morning DM)**
- "💰 Money rotating: Healthcare → AI Power week-over-week"
- ใช้ /หุ้นเด่น scan data — aggregate by sector + week-over-week diff
- Effort: ~3 ชม.

**B-new4. Per-symbol Track Record**
- "AAPL ของ Apexify hit 75% ใน 30 วัน"
- จาก Roadmap "Soon" ยังไม่ได้ทำ
- Effort: ~3 ชม. (extend /track query by symbol)

### Web features ใหม่

**W-new1. Push notifications (PWA)**
- ปัจจุบัน: service worker registered แต่ subscribe/send ยังไม่ implement (stub)
- Breaking news HIGH + PRO alert → push แม้ไม่เปิด web
- Effort: ~3 ชม. (Web Push API + backend store + send via VAPID)

**W-new2. Multi-asset support (ETF/Crypto/Forex)**
- ปัจจุบัน: stocks เท่านั้น (ทั้ง bot + web)
- เริ่มจาก ETF (SPY, QQQ) ก่อน
- จาก Roadmap "Soon"
- Effort: ~5 ชม.

---

## 🔴 ตัดสินใจไม่ทำ (User ปฏิเสธ — ห้ามเสนอใหม่)

### 2026-05-12
- ❌ FB OG Card Generator ทาง bot (`/og NVDA` → PNG) — ปฏิเสธ
- ❌ Daily Picker → auto FB draft text/image — ปฏิเสธ
- ❌ Referral code per user (unique link) — ปฏิเสธ
- ❌ Weekly Trade Plan Recap PRO — ปฏิเสธ
- ❌ Browser push notification (W2) — ปฏิเสธรอบนี้ (แต่อยู่ใน W-new1 ปรับเป็น PWA → ตรงๆ ถ้าทำใหม่ค่อยพิจารณา)
- ❌ Watchlist Heatmap public share — ปฏิเสธ
- ❌ AI Chat sidebar ใน web — มีอยู่แล้ว (copilot-fab)
- ❌ PRO+ tier — ปฏิเสธ
- ❌ Annual plan discount — ปฏิเสธ
- ❌ Pay-per-analysis push — ปฏิเสธ
- ❌ Community access (LINE OA private) — ปฏิเสธ
- ❌ Refer-a-friend gamification — ปฏิเสธ
- ❌ Group chat moderator bot — ปฏิเสธ
- ❌ Live trading room weekly — ปฏิเสธ
- ❌ Backtest engine (B3) — ปฏิเสธ
- ❌ /cal command (B4) — ปฏิเสธ (ทำในเว็บแล้ว /economic-calendar)
- ❌ /news SYM (B5) — ปฏิเสธ
- ❌ Telegram Channel auto-broadcast (B6) — ปฏิเสธ
- ❌ Voice command STT (B7) — ปฏิเสธ
- ❌ Public Trader Profile (W6) — ปฏิเสธ
- ❌ Strategy Share + Win Rate (W7) — ปฏิเสธ
- ❌ Risk meter widget (W8) — ปฏิเสธ
- ❌ Custom dashboard widgets (W9) — ปฏิเสธ

### เก่ากว่า (HANDOFF / older)
- ❌ YouTube Shorts Auto Generator (P0 #1 เก่า — User ลบทิ้งโปรเจกต์ 2026-05-XX)
- ❌ FB Infographic Generator (HANDOFF P2 #5) — ตัดสินใจไม่ทำ
- ❌ Cohort Retention Heatmap (HANDOFF P2 #7) — ตัดสินใจไม่ทำ
- ❌ Top-up Paywall enhance (HANDOFF P2 #8) — ตัดสินใจไม่ทำ
- ❌ /setalert Web UI (HANDOFF P2 #9) — ตัดสินใจไม่ทำ

---

## 🟣 Parked (รอเหตุการณ์เฉพาะ)

**P1. Discount Code System** (% off ราคาจริง)
- Schema + flow ออกแบบไว้แล้ว (ดู [[15 - Roadmap]] Soon)
- Trigger: event ใช้จริง (Black Friday, ปีใหม่) **และ** scale > 30 paying
- ปัจจุบัน 13 paying — ใช้ "วันฟรี" promo (`/redeem CODE`) แทนได้

**P2. Phase B feature bets** (3 ตัว, parked memory)
- Thai US Earnings Synthesis (PRO)
- SET Governance Red-Flag
- Cross-broker Portfolio + Tax
- Trigger: scale > 30 paying

**P3. LINE OA version**
- Trigger: > 200 paying + bandwidth ทำได้

---

## 📊 Snapshot สถานะปัจจุบัน

- **Paying:** 13 (ดู metric)
- **Web users 24h:** 27 unique (53 ตลอด 5 วัน)
- **Bot cron ปัจจุบัน:** Daily Picker, Earnings Prep, Daily P&L Recap, Auto-DM, Plan Evaluator, Heartbeat, Breaking News, Alert Loop
- **Recent deploys:** Smart Money "list ในหน้านี้" — backlog only, ยังไม่ build

---

## 🎯 ลำดับแนะนำต่อไป

**Smart Money expansion (ทำคู่ pattern เดียวกัน):**
1. **C2 Analyst Upgrades/Downgrades** (~2 ชม.) — Finnhub free 60/min, PRO watchlist match
2. **C1 Congress Trading** (~3 ชม.) — Pelosi/Tuberville, viral content
3. **C4 52w Breakout Screener** (~1.5 ชม.) — quick win ใช้ yfinance ที่มี

**Polish / Quality:**
4. **B-new2 Personal Activity Stats** (~2 ชม.) — /me แสดง "คุณวิเคราะห์ X หุ้นสัปดาห์นี้"
5. **B-new4 Per-symbol Track Record** (~3 ชม.) — "NVDA ของ Apexify hit 78%"

**Web:**
6. **E2 /compare 2→4 tickers** (~4 ชม.) — แก้ที่ user ทักว่าไม่โอเค

ดู [[33 - New Features Promo Templates]] สำหรับ marketing content ของ features ที่ deploy แล้ว

ดูต่อ: [[14 - Recent Changes]] · [[15 - Roadmap]] · [[18 - Feature Cheat Sheet]]

#backlog #planning
