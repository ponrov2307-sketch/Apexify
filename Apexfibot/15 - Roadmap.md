---
tags: [roadmap, planning, strategy]
---

# 🗺️ Apexify Roadmap (Strategic Plan)

> วาง 5 ขั้น: **Done → Now → Next → Soon → Later → Vision**
> เป้าหมายหลัก: 1,000 paying subscribers ใน 12 เดือน

---

## ✅ Done — สิ่งที่ทำเสร็จแล้ว

### Sprint 1 (รากฐาน)
- ✅ Premium tier redesign (Free/VIP/PRO ต่างกันชัด)
- ✅ Track Record system (`/track` + cron evaluate)
- ✅ Tier-specific charts (Free=text, VIP=basic, PRO=annotated)
- ✅ Renewal reminders 7/3/1 วัน + inline buttons
- ✅ Quota: 10 → 3/วัน + inline upsell
- ✅ Weekly Digest + AI Economic Calendar
- ✅ Thai Quality Guard + Gemini Prompt Caching
- ✅ Admin = PRO (critical bug fix)
- ✅ Referral v2 (เพื่อนได้ VIP 3 วัน + native share)

### Sprint 2 (engagement + product depth)
- ✅ Daily Streak (+1 วัน VIP/7วัน)
- ✅ /fund — Fundamentals (P/E, EPS, Dividend, ฯลฯ)
- ✅ /compare — Stock Comparison + AI Verdict
- ✅ /ask — AI Q&A (context-aware)
- ✅ /demo — Feature tour
- ✅ Telegram Commands Menu (set_my_commands)
- ✅ Contextual Quick Buttons + Hub menu จัดหมวด

### Sprint 3 (polish + sales kit)
- ✅ Free Trial flow ปลอดภัย (กดซ้ำไม่มีปัญหา)
- ✅ ข้อความเตือนเกลาให้สุภาพ (✨ แทน ⚠️)
- ✅ /manual ขยาย 3x (workflow + FAQ + tips)
- ✅ Obsidian Vault 21 ไฟล์ (technical + sales)

ดูประวัติเต็ม: [[14 - Recent Changes]]

---

## 🎯 Now — ทำตอนนี้ (ก่อน push feature ใหม่)

> ปัจจุบัน: Code stable, sales kit พร้อม
> โฟกัส: **deploy + เริ่มหา user จริง**

### Action Items สัปดาห์นี้
- [ ] **Deploy ล่าสุดบน Digital Ocean** (`git pull && systemctl restart`)
- [ ] **ทดสอบ flow ทั้งหมดด้วยตัวเอง** (เผื่อมี bug)
  - วิเคราะห์ AAPL / PTT.BK
  - กด /freetrial / /freetrial ซ้ำ
  - กด /compare /fund /ask
  - กด /demo / /track
- [ ] **สร้าง welcome promo code** (เช่น `WELCOME2026` แจก VIP 7 วัน)
- [ ] **โพสต์ Facebook ครั้งแรก** (ใช้ template จาก [[19]])
- [ ] **อัด TikTok 1 คลิป** (ใช้ script จาก [[20]])
- [ ] **ทักเพื่อน 5 คนแรก** ให้ลอง /freetrial

### Metrics ที่ต้องเริ่มเก็บ
- Daily active users
- /freetrial conversion (start → analyze ครั้งแรก)
- Trial → Paid conversion (7 วัน)
- Average session length
- Most-used command

---

## 🔜 Next — ทำใน 1-2 สัปดาห์ (Quick Wins)

### Polish (Effort: Low, Impact: Medium)
- [ ] **Onboarding Tutorial** 📖
  - 3-step interactive walkthrough หลัง /start
  - "พิมพ์ AAPL → กด ⭐ → รับ briefing พรุ่งนี้"
  - กัน drop-off ของ user ใหม่

- [ ] **Personal Activity Stats** 📊
  - "คุณวิเคราะห์ 12 หุ้นสัปดาห์นี้ | TSLA ดูบ่อย 5 ครั้ง"
  - แสดงใน /account หรือ /track

- [ ] **Sector Heatmap รายวัน** 🌡️
  - ส่งทุกเช้า: "🟢 Tech +1.2% | 🔴 Energy -0.8%"
  - คำสั่ง /heatmap — ดูได้ทุกเมื่อ
  - Hook ให้ user เปิดบอททุกวัน

### Marketing (Effort: Low, Impact: High)
- [ ] **เริ่มลงคอนเทนต์ตาม [[19]] template**
  - 1 post/วัน บน Facebook
  - 1 reel/วัน บน TikTok
- [ ] **เปิด Public Telegram Channel**
  - Post Track Record รายสัปดาห์
  - Stock pick อัตโนมัติจากบอท
  - Drive traffic → bot
- [ ] **ลง Pantip / กลุ่ม Facebook นักลงทุน**
  - แนะนำตัว + แชร์ free trial
  - ตอบคำถามมือใหม่

### Quality (Effort: Low, Impact: Medium)
- [ ] **เพิ่ม `/feedback` command**
  - User บอก bug/แนะนำได้ตรง → ส่งหา admin
- [ ] **Better error logs**
  - Sentry หรือ self-hosted error tracker
- [ ] **Health monitoring**
  - UptimeRobot ping `/` ทุก 5 นาที

---

## ⏳ Soon — ทำใน 1-3 เดือน (Mid features)

### Product Depth (PRO value)
- [ ] **/share — Export รายงานเป็นรูป** 📤
  - สร้าง image สวยๆ มี logo
  - User โพสต์ FB/IG ได้ → free marketing
  - **Effort: Medium-High** | **Impact: High** (viral)

- [ ] **Backtest Plan** 🔬
  - "ถ้าซื้อตาม Plan Apexify 1 ปีก่อน → กำไร X%"
  - Proof of value แบบ historical
  - **Effort: High** | **Impact: Very High** (trust builder)

- [ ] **Per-symbol Track Record** 📊
  - "AAPL ของ Apexify hit 75% ใน 30 วัน"
  - แสดงใน /track หรือ chart annotation
  - **Effort: Medium** | **Impact: High**

- [ ] **Multi-asset support** (ETF, Crypto, Forex)
  - เริ่มจาก ETF (SPY, QQQ) ก่อน
  - Crypto (BTC-USD) ทีหลัง
  - **Effort: Medium**

### Engagement
- [ ] **Win-back campaign สำหรับ user หมดอายุ**
  - Day 1: "เราคิดถึงคุณ + แจกโค้ด REJOIN30 (VIP 30 วัน)"
  - Day 7: "หุ้นใน watchlist คุณช่วงนี้... ลองดูใหม่"
  - **Effort: Low**

- [ ] **Pro tier "VIP+" exclusive features**
  - Sector rotation alerts
  - Earnings beat predictor
  - Insider trading alerts
  - → upsell PRO ได้
  - **Effort: Medium-High**

### Marketing
- [ ] **Influencer partnership** (1-2 คนแรก)
  - แจกโค้ดเฉพาะ + ส่วนแบ่ง revenue
  - ช่อง: หุ้นไทย, คริปโต, การเงิน
- [ ] **YouTube channel เปิดอย่างเป็นทางการ**
  - 1 video/สัปดาห์ (long-form 5-10 นาที)
  - SEO-optimized titles
- [ ] **Blog/SEO** (apexify.com หรือ medium.com)
  - 4 บทความ/เดือน เน้นคำค้น "วิเคราะห์หุ้น AI"

---

## 🌅 Later — ทำใน 3-6 เดือน (Big Plays)

### Platform Expansion
- [ ] **LINE OA version**
  - LINE = ฐาน user คนไทยใหญ่กว่า Telegram
  - feature เหมือน Telegram bot
  - **Effort: High** | **Impact: Very High**

- [ ] **Web Dashboard เต็มรูปแบบ**
  - User login + พอร์ตเต็ม + alert manager
  - Mobile-responsive
  - ใช้แทน command บางตัว

- [ ] **Discord bot** (สำหรับ trader community)
  - Server-wide alerts
  - VIP role integration

### Product Innovation
- [ ] **AI Portfolio Optimizer** 💼
  - User บอก budget + risk profile
  - AI แนะนำ allocation 5-10 หุ้น
  - **Premium PRO+ feature**

- [ ] **Auto-trade integration** (เชื่อม broker)
  - SETtrade API / Settrade
  - ผูก Plan ของบอท → กดส่งคำสั่งจริงใน 1 click
  - **Effort: Very High** (regulatory + technical)

- [ ] **Voice query** "สวัสดี Apexify วิเคราะห์ AAPL ให้หน่อย"
  - ใช้ STT + TTS (edge-tts มีอยู่)
  - **Effort: Medium** (cool factor สูง)

### Business
- [ ] **B2B partnerships**
  - Broker partner (เสนอ Apexify เป็น value-add)
  - การเงินส่วนบุคคล (SCB Easy, K+ ฯลฯ)
- [ ] **Enterprise tier** (5,000+ บาท/เดือน)
  - Multi-user accounts
  - Custom alerts
  - Priority support

---

## 🔮 Vision — 6-12+ เดือน (Long-term)

### Year 1 Goal (สิ้น 2026)
- 🎯 **1,000 paying subscribers**
- 🎯 Track Record > 65% hit rate (proven public)
- 🎯 Public mention โดย Thai finance influencer
- 🎯 Monthly Recurring Revenue (MRR) ≥ 90,000฿
- 🎯 Churn rate < 10%/เดือน

### Year 2 (2027)
- 📱 iOS/Android native app
- 🌍 Multi-language (English เริ่มก่อน)
- 🤝 White-label สำหรับ broker partners
- 📊 5,000+ subscribers
- 💰 MRR ≥ 500,000฿

### Year 3+ (Vision big)
- 🇸🇬 Singapore/Malaysia expansion
- 🏦 Acquisition target by broker / fintech
- 🌐 Open API สำหรับ developers

---

## 🚨 Risks & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|:---:|:---:|------|
| Gemini API ราคาขึ้น | Med | High | Implement caching แล้ว + monitor cost |
| Telegram ban (rare) | Low | Critical | เตรียม LINE backup + Discord |
| คู่แข่งใหม่ลอกฟีเจอร์ | High | Med | Track Record = moat ที่ลอกยาก |
| ตลาดหมีระยะยาว | Med | High | Diversify (ETF, Crypto, Forex) |
| Compliance issues | Low | High | Disclaimer ชัด + ไม่ชี้นำ |
| User churn จากของดี free อื่นๆ | Med | Med | สร้าง community + streak system |

---

## 🛠 Tech Debt (จัดการเรื่อยๆ)

- [ ] **Tests** — เพิ่ม unit tests สำหรับ critical paths
- [ ] **CI/CD** — auto deploy เมื่อ push (GitHub Actions)
- [ ] **DB backup automation** — daily + offsite
- [ ] **Logs structured** — JSON logs + query tool
- [ ] **Refactor main.py** — ตอนนี้ 2700+ บรรทัด → แตกเป็น modules
- [ ] **Database indexing** — review + optimize slow queries
- [ ] **Rate limiting** — กัน abuse (`/ask` flood)
- [ ] **Session cleanup** — `_user_last_symbol` dict ไม่มี expiry
- [ ] **Image storage** — chart cache แค่ memory → ใช้ Redis

---

## 💰 Pricing Strategy Roadmap

### Phase 1: Land grab (ตอนนี้) — Now
- เน้น Free Trial + Referral แจก
- ราคาเดิม 79/109
- Promo code = แจกวัน VIP

### Phase 2: Establish (Month 3-6)
- ขึ้น VIP เป็น 99 / PRO เป็น 149 (early bird ราคาเก่า)
- เริ่มใช้ Promo Code "ส่วนลด" (ต้องสร้างระบบเพิ่ม)
- เพิ่ม Annual plan discount

### Phase 3: Premium (Month 6-12)
- เพิ่ม "VIP+" tier (159/เดือน)
- Enterprise tier
- White-label pricing

### Phase 4: Optimize (Year 2+)
- A/B test pricing
- Dynamic pricing per region
- Family plan / Group discount

---

## 📊 KPIs ที่ต้องติดตาม

### Product
- DAU / MAU ratio
- Average commands per user/day
- Track Record hit rate (must trend up)

### Growth
- New /start per day
- Free → Trial conversion rate
- Trial → Paid conversion rate
- Referral coefficient

### Revenue
- MRR (Monthly Recurring Revenue)
- ARPU (Average Revenue Per User)
- Churn rate
- LTV (Lifetime Value)

### Marketing
- Cost per acquisition
- Organic traffic growth
- Social engagement rate
- Brand mentions

---

## 🎯 ลำดับงานแนะนำ (Decision Tree)

**ถ้าตอนนี้ user น้อย (< 50):**
→ โฟกัส Marketing + Influencer + Free Trial promo
→ ห้ามทำ feature ใหม่ จนกว่าจะมี feedback จริง

**ถ้า user เริ่มมา (50-200):**
→ ทำ Onboarding Tutorial + Sector Heatmap
→ เริ่ม Track Record marketing
→ ยังไม่ทำ feature ใหญ่

**ถ้า user เยอะ (200-500):**
→ /share + Backtest Plan (proof + viral)
→ ขยายตลาด LINE / Discord
→ Influencer partnership

**ถ้า user เยอะมาก (500+):**
→ Web Dashboard เต็ม
→ ขึ้นราคา + Promo Code ส่วนลด
→ Enterprise tier

---

ดูต่อ:
- [[14 - Recent Changes]] — เกิดอะไรขึ้นล่าสุด
- [[17 - Sales Playbook]] — ขายยังไง
- [[18 - Feature Cheat Sheet]] — สรุปทุกอย่าง
- [[01 - Project Overview]] — เริ่มอ่านที่นี่

#roadmap #planning #strategy
