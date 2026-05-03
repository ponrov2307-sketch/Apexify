---
tags: [changelog]
---

# 📝 Recent Changes

> เรียงจากใหม่สุดลงล่าง — เก็บแค่ commits สำคัญ

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
