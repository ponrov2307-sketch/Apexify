---
tags: [user-guide, manual, onboarding]
---

# 📖 วิธีใช้งาน Apexify (User Guide)

> คู่มือสำหรับลูกค้า — copy-paste ส่งให้ลูกค้าใหม่ได้
> มี version สั้น (1 หน้า) และ version ละเอียด

---

## 🚀 Quick Start (สั้น 30 วินาที)

```
🚀 เริ่มใช้ Apexify ใน 3 ขั้น:

1️⃣ เปิด t.me/Apexify_Trading_Bot
2️⃣ กด /start
3️⃣ พิมพ์ชื่อหุ้น เช่น AAPL, NVDA, PTT.BK

→ AI ตอบใน 5-10 วินาที พร้อมกราฟ + วิเคราะห์ครบ

🎁 อยากใช้ premium ฟรี? พิมพ์ /freetrial → PRO 7 วันฟรี
```

---

## 📚 Quick Start (ละเอียด)

### ขั้นที่ 1: เปิดบอท

ลิงก์: **t.me/Apexify_Trading_Bot**
หรือ search ใน Telegram: `@Apexify_Trading_Bot`

### ขั้นที่ 2: กด `/start`

จะเห็น welcome message + เมนูหลัก

### ขั้นที่ 3: พิมพ์ชื่อหุ้น

| ประเทศ | รูปแบบ | ตัวอย่าง |
|---|---|---|
| 🇺🇸 US | (ไม่มี suffix) | `AAPL` `NVDA` `TSLA` |
| 🇹🇭 ไทย | `.BK` (หรือไม่ใส่ก็ได้) | `PTT.BK` หรือ `PTT` |
| 🇭🇰 ฮ่องกง | `.HK` | `0700.HK` |
| 🇯🇵 ญี่ปุ่น | `.T` | `7203.T` |
| 🇸🇬 สิงคโปร์ | `.SI` | `D05.SI` |
| ฿ Crypto | `-USD` | `BTC-USD` `ETH-USD` |

### ขั้นที่ 4: รอผลลัพธ์ 5-10 วินาที

จะได้:
- 📊 **Trend Radar** 3 ระยะ (วัน / สัปดาห์ / เดือน)
- 📈 **กราฟเทคนิค** พร้อม indicator (PRO มี Entry/TP/SL)
- 💡 **AI Insight** สรุปเป็นภาษาไทย
- 🔔 **ปุ่มลัด** — ตั้งเตือน, ดู Fundamentals (PRO)

---

## 🎮 16 คำสั่งหลัก

> 💡 พิมพ์ `/` ใน Telegram จะเห็นทั้งหมด — ไม่ต้องจำ

### พื้นฐาน (ทุก tier ใช้ได้)
- `/start` — เริ่มต้น + ดูเมนู
- `/account` (alias `/me`) — สถานะบัญชี + Streak
- `/demo` — ทัวร์ฟีเจอร์
- `/manual` (alias `/help`) — คู่มือใช้งานเต็ม
- `/dashboard` — เปิด Web Dashboard
- `/track` — ดูสถิติ AI Track Record
- `/settings` — ตั้งค่าแจ้งเตือน
- `/contact` — ส่งข้อความถึง admin

### พรีเมียม (VIP/PRO)
- `/fund AAPL` (alias `/fundamentals`) — P/E, EPS, Dividend
- `/earnings AAPL` — วิเคราะห์งบ
- `/ealert AAPL` — แจ้งเตือน Earnings

### PRO เท่านั้น
- `/compare AAPL MSFT` — เปรียบเทียบ 2-3 หุ้น
- `/ask <คำถาม>` — ถาม AI ตรงๆ
- `/setalert AAPL 200` — ตั้งเตือนราคา
- `/myalerts` — ดูเตือนทั้งหมด

### บัญชี
- `/freetrial` — ทดลอง PRO 7 วันฟรี
- `/redeem CODE` — เติม promo code
- `/referral` — ลิงก์ชวนเพื่อน

---

## 💎 Workflow แนะนำ (สำหรับนักลงทุน)

### 🌅 ตอนเช้า (5 นาที)
1. รับ **Morning Briefing** อัตโนมัติ (VIP/PRO) — ส่งทุก 8:00 น.
2. เช็คหุ้นในพอร์ต — พิมพ์ `/portfolio`
3. ถ้ามี alerts ค้าง — กดดูใน `/myalerts`

### 🕐 ระหว่างวัน
- เห็นข่าวอะไรน่าสนใจ → พิมพ์ชื่อหุ้นเช็คเทรนด์
- รอ alerts จากบอท (PRO)
- เปิด Web Dashboard ดู portfolio: **apexifyy.up.railway.app**

### 🌆 ตอนเย็น
- เช็ค Watchlist Summary (อัตโนมัติทุกวัน)
- ทบทวน Plans ที่เปิดอยู่ — `/track` ดู outcome

### 📅 รายสัปดาห์
- รับ **Weekly Digest** วันศุกร์ 18:00 (VIP/PRO)
- ทบทวน Hit Rate ของ AI Plans

---

## 🌐 Web Dashboard (apexifyy.up.railway.app)

> สำหรับลูกค้า PRO/VIP — login ด้วย Telegram

### หน้าหลัก
- **Trade Plan v2** — แต่ละหุ้นในพอร์ตแสดง Position sizing + Catalyst + Volume + Apply Plan ปุ่มเดียว
- **Portfolio Health Score** — สุขภาพพอร์ตรวม
- **Daily AI Pulse** — สรุปพอร์ตวันนี้

### หน้าอื่น
- `/transactions` + `/pnl` — บันทึก + สรุปกำไรขาดทุน (ยื่นภาษีได้)
- `/heatmap` — Heatmap ตลาด + watchlist
- `/news` — AI summarize ข่าวพอร์ต
- `/matchmaker` — AI แนะนำหุ้นตามพอร์ต
- `/earnings` + `/economic-calendar`

---

## 🎁 Promo & Rewards (ของฟรีที่ได้)

### 🆓 Free Trial 7 วัน
- พิมพ์ `/freetrial` ใช้ได้ทันที
- ไม่ต้องผูกบัตร, หลัง 7 วันกลับเป็น Free อัตโนมัติ
- จำกัด 1 ครั้ง/บัญชี

### 🔥 Daily Streak
- ใช้บอทต่อเนื่อง 7 วัน → +1 วัน VIP ฟรี อัตโนมัติ
- ดูสถานะใน `/account`

### 🤝 Referral
- ชวนเพื่อนผ่าน `/referral`
- เพื่อนได้ VIP 3 วันฟรีทันที (ใหม่!)
- คุณได้ +10 วัน VIP/PRO ทุก 3 คน

### 🎁 Promo Code
- มีโค้ดจาก admin → พิมพ์ `/redeem VIP7-XXXXXX`
- เพิ่มวันให้ฟรี (3-30 วัน แล้วแต่โค้ด)

---

## 📊 ตีความผลลัพธ์ของบอท

### Trend Radar
```
📊 Apple Inc. (AAPL)

📈 Trend Radar:
   D: 🟢 ขาขึ้น (Bullish)
   W: 🟢 ขาขึ้น
   M: 🟢 ขาขึ้น

   → ทุก timeframe ตรงกัน = signal แรง
```

### Conviction Score
- **C75-92** = แม่นมาก (เทรนด์ + R:R + signal ชัด)
- **C55-74** = ปกติ (ดูเป็น watchlist)
- **C20-54** = อ่อน (ระวัง)

### Entry / TP / SL (PRO)
```
📍 Entry zone: $182-186  ← ราคาที่ AI แนะนำเข้า
🎯 TP1: $209 (+13.4%)    ← Take Profit ครั้งแรก
🎯 TP2: $225 (+22.0%)    ← Take Profit ครั้งสอง
🛑 SL: $172 (-5.5%)      ← Stop Loss (จุดตัดขาดทุน)
⚖️ R:R: 2.4              ← ความคุ้มเสี่ยง (≥2 = ดี)
```

### R:R Warning
- **R:R ≥ 2** = setup คุ้มเสี่ยง 👍
- **R:R 1-2** = พอใช้ได้
- **R:R < 1** = ⚠️ AI เตือนว่าไม่คุ้ม — ระวัง

---

## ⚠️ Disclaimer สำคัญ

```
🚨 Apexify ไม่ใช่ที่ปรึกษาการลงทุน
- ข้อมูลที่บอทแสดง = ข้อมูลเทคนิค + indicator
- AI Insight = วิเคราะห์ภาพรวม ไม่ใช่คำแนะนำซื้อ-ขาย
- การตัดสินใจสุดท้าย = ของคุณเสมอ
- ตลาดมีความเสี่ยง ผลย้อนหลังไม่รับประกันผลอนาคต

ใช้บอทเป็น "ผู้ช่วย" ไม่ใช่ "กูรู"
```

---

## 🆘 ปัญหาที่อาจเจอ + วิธีแก้

| ปัญหา | สาเหตุ | วิธีแก้ |
|---|---|---|
| บอทไม่ตอบ | App Telegram ค้าง | Restart Telegram |
| พิมพ์หุ้นไม่เจอ | สะกด ticker ผิด | เช็คที่ finance.yahoo.com |
| Free Trial ใช้ไม่ได้ | เคยใช้แล้ว | รอ promo code ใหม่ หรือสมัคร VIP/PRO |
| ส่งสลิปไม่ upgrade | ภาพไม่ชัด | ส่งใหม่ + ทักหา admin |
| ข่าวไม่อัปเดต | ตลาดปิด/วันหยุด | ปกติ — รอวันเปิดตลาด |

---

## 📞 ต้องการความช่วยเหลือ?

- พิมพ์ `/contact` ในบอท → ส่งข้อความตรงถึง admin
- inbox Facebook page: [link]
- รอตอบ: 1-3 ชม. (เฉลี่ย)

---

#user-guide #manual #onboarding
