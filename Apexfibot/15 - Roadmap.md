---
tags: [roadmap, planning]
---

# 🗺️ Roadmap

## ✅ Done (เสร็จแล้ว — เรียงตาม sprint)

### Premium Tier Redesign
- [x] Free: text only (no chart) + upsell CTA
- [x] VIP: basic chart + Trend Radar + Watch Next
- [x] PRO: annotated chart + Plan + Conditions + R:R warning

### Track Record (#4)
- [x] `analysis_plans` table + log every PRO plan
- [x] Cron 6:00 → check_plan_outcomes()
- [x] `/track` command แสดง stats 30/90 วัน

### Engagement / Retention
- [x] Inline upsell ตอน quota หมด (3 ปุ่ม + free trial)
- [x] Renewal reminders 7/3/1 วัน + inline buttons
- [x] Free quota 10 → 3 ครั้ง/วัน
- [x] Weekly Digest ศุกร์ 18:00 (#5)
- [x] AI Economic Calendar preview (#6)

### Quality / Performance
- [x] Thai Quality Guard (#8) — แก้ AI typos
- [x] Gemini Prompt Caching (#7) — system_instruction
- [x] Gemini 503 + 404 retry chain
- [x] PRO chart light theme + price labels
- [x] Auto .BK fallback สำหรับหุ้นไทย

### Bug Fixes
- [x] Admin = PRO (critical — alerts ถูก auto-delete)
- [x] Chart `\\n` literal bug
- [x] TP1/TP2 minimum gap enforcement
- [x] Entry range cap (เลิก stretch ไปราคาปัจจุบัน)
- [x] R:R warning เมื่อ < 1.0

### Growth (#9 Referral v2)
- [x] Referred user ได้ VIP 3 วันฟรี (welcome bonus)
- [x] Telegram native share button (`switch_inline_query`)
- [x] อัปเดต menu UI

---

## ⏳ In Progress / Next

(ยังไม่เริ่ม)

---

## 🆕 Sprint 2 (2026-04-24 — เสร็จแล้ว)

### Engagement
- [x] **Daily Streak System** 🔥
  - ครบ 7 วัน → +1 วัน VIP ฟรี (auto)
  - Celebration ที่ 3/7/14/30/50/100
  - แสดงใน /account

### Product Depth
- [x] **/fund** — Fundamentals (VIP/PRO)
  - P/E, PEG, P/B, EPS, Dividend, Market Cap, Beta, 52W
- [x] **/compare A B [C]** — Stock Comparison (PRO)
  - Side-by-side technicals + AI verdict

### UX / Discovery
- [x] **Telegram Commands Menu** (`bot.set_my_commands`)
- [x] **Contextual Quick-Action Buttons** หลังวิเคราะห์
- [x] **Hub menu จัดหมวด 4 กลุ่ม**
- [x] [[16 - Command Discoverability]] — documentation

## 💡 Future Ideas (ตามลำดับความสำคัญ)

### Group A: Engagement & Habit (ดึง user มาทุกวัน)

- [x] ✅ **Daily Streak System** 🔥 (Sprint 2)
- [ ] **Onboarding Tutorial** 📖
  - Interactive 3-step walkthrough สำหรับ new user
  - "ลองพิมพ์ AAPL" → กดปุ่ม → เห็นผล → กด ⭐
  - Effort: Low

- [ ] **Personal Activity Stats** 📊
  - "คุณวิเคราะห์ 12 หุ้นสัปดาห์นี้ | TSLA ดูบ่อย 5 ครั้ง"
  - ใส่ใน /track หรือ command ใหม่
  - Effort: Low

### Group B: Product Depth (เพิ่มเหตุผลสมัคร PRO)

- [x] ✅ **Stock Comparison** `/compare` (Sprint 2)
- [x] ✅ **Fundamentals** `/fund` (Sprint 2)

- [ ] **AI Q&A Follow-up** 💬
  - หลังวิเคราะห์ → ปุ่ม "🤖 ถาม AI เพิ่ม"
  - PRO เท่านั้น (premium chat experience)
  - Effort: Medium

### Group C: Discovery / Marketing

- [ ] **Sector Heatmap รายวัน** 🌡️
  - "🟢 Tech +1.2% | 🔴 Energy -0.8%"
  - ส่งทุกเช้า + คำสั่ง /heatmap
  - Effort: Medium

- [ ] **/share — แชร์รายงานเป็นรูป** 📤
  - สร้างรูปสวยๆ มี logo Apexify
  - โพสต์ Facebook/IG ได้
  - Effort: Medium-High

- [ ] **Backtest Plan** 🔬
  - "ถ้าซื้อตามแผน Apexify 1 ปีก่อน จะได้กำไร X%"
  - Proof of value แบบ historical
  - Effort: High

- [ ] **Public Apexify Telegram Channel** 📢
  - Post highlights ประจำวัน
  - Drive traffic ไป bot
  - Effort: Low (content automation)

### Other

- [ ] **Win-back สำหรับ user หมดอายุ** 💔
  - Day 1-3 หลังหมด → ส่งโค้ดส่วนลด 20-30%

- [ ] **Per-symbol Track Record leaderboard**
  - "AAPL ของ Apexify hit 75% ใน 30 วัน"

- [ ] **Email weekly summary** (สำหรับคนชอบ email)

- [ ] **Insider trading alerts** (เมื่อ CEO ซื้อ/ขาย)

- [ ] **52-week high/low alerts**

---

## 🔮 Long-term Vision

### Year 1 goal
- 1,000 paying subscribers
- Track Record proven > 65% hit rate
- Public mention โดย Thai finance influencer

### Year 2
- iOS/Android native app (สำหรับ user ที่ไม่ใช้ Telegram)
- Multi-language (English market)
- White-label สำหรับ broker partners

ดูต่อ:
- [[14 - Recent Changes]]
- [[01 - Project Overview]]

#roadmap #planning
