---
tags: [changelog]
---

# 📝 Recent Changes

> เรียงจากใหม่สุดลงล่าง — เก็บแค่ commits สำคัญ

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
