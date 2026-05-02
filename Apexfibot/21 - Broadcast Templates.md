---
tags: [broadcast, templates, admin]
---

# 📢 Broadcast Templates

> ข้อความสำเร็จรูปสำหรับใช้กับ `/broadcast` command
> Copy-paste ได้เลย — แก้แค่วันที่ / โค้ด / ตัวเลขให้ตรงปัจจุบัน

---

## 🛠 วิธีใช้

```
/broadcast <ข้อความ>
```

ส่งหา **active users ทุกคน** (filter `status='active'`)
- รันใน background thread (admin จะได้ progress message)
- ใช้ Markdown ได้
- เว้นบรรทัด ใช้ `\n` (พิมพ์เข้าไปจริงๆ)

⚠️ **ระวัง:**
- ส่งครั้งเดียวจริงจัง — ไม่ rollback ได้
- เก็บ rate limit Telegram (~30 msg/sec)
- ทดสอบกับ admin คนเดียวก่อน (เผื่อ Markdown ผิด)

---

## 🎁 Promo / Free Code

### Template: แจกโค้ด VIP free (กระตุ้น Free user → ลองใช้ premium)

```
🎁 โค้ดพิเศษจาก Apexify วันนี้!

ใช้โค้ด: VIP7-XXXXXX
รับ VIP ฟรี 7 วัน ทันที

วิธีใช้:
พิมพ์ /redeem VIP7-XXXXXX ในแชทนี้

⏰ มีจำนวนจำกัด first-come first-served
จำกัด 1 คน/บัญชี
```

> 💡 ก่อนใช้: `/gencode 7 100 vip` → ได้โค้ดมา → copy ไปใส่ template

### Template: แจกโค้ด PRO 14 วัน (กระตุ้น VIP → upgrade PRO)

```
👑 ลอง PRO 14 วันฟรี!

ใช้โค้ด: PRO14-XXXXXX
ปลดล็อก:
✅ Entry/TP/SL บนกราฟ
✅ /compare เปรียบเทียบหุ้น
✅ /ask ถาม AI
✅ Smart Alerts

พิมพ์ /redeem PRO14-XXXXXX ในแชทนี้
จำกัด 50 คนแรกเท่านั้น
```

---

## 📊 Track Record / Social Proof

### Template: เผย hit rate รายเดือน

```
📊 Apexify Track Record — เดือนนี้

✅ Hit Rate (TP1/TP2): XX.X%
🎯 Plans hit เป้าหมาย: XX จาก XX
🛑 SL hit: X
⏱ Average days to TP1: X วัน

ดูสถิติ live ได้ตลอดเวลา → พิมพ์ /track

⚠️ ข้อมูลย้อนหลังเพื่ออ้างอิง — ผลในอนาคตอาจแตกต่าง
```

### Template: หุ้นที่บอท hit TP สำเร็จ

```
🎯 Plan ที่บอทออก เมื่อ X วันก่อน — hit TP1 แล้ว!

📌 หุ้น: NVDA
📍 Entry: $182-186 (วันที่ X พ.ค.)
🎯 TP1: $209 (hit เมื่อวานนี้!)
📈 +13.4% ในเวลา 18 วัน

อยากได้แผนแบบนี้?
อัปเกรด PRO → /freetrial ทดลองฟรี 7 วัน
```

---

## 🆕 Feature Announcements

### Template: เปิดตัวฟีเจอร์ใหม่

```
🆕 ฟีเจอร์ใหม่: [ชื่อฟีเจอร์]

[คำอธิบายสั้น 1-2 บรรทัด]

วิธีใช้:
[command หรือ instruction]

[ข้อดี/ประโยชน์]

ลองเลย! 🚀
```

### Template: Trade Plan v2 (PRO/VIP — web dashboard) ⭐ 2026-05-01

> สำหรับ broadcast ลูกค้า PRO/VIP เพื่อแจ้งฟีเจอร์ใหม่บน dashboard

**Version A — สั้น (focus actionable):**
```
🚀 Trade Plan v2 — แดชบอร์ดอัปเดต!

แต่ละการ์ดในพอร์ตของคุณตอนนี้บอกชัดขึ้น:

▸ ขายออกกี่ % ที่ TP1, TP2 (position sizing)
🚨 มี earnings ใกล้ๆ ไหม (catalyst alert)
🔥 Volume hot/cold เทียบ 20 วัน
⚠️ หุ้นนี้กี่ % ของพอร์ต — ลดได้ไหม

เด็ดสุด:
🔔 ปุ่ม "ใช้แผนนี้" — กดเดียวตั้ง alerts
ทั้ง TP1, TP2, SL ครบ ไม่ต้องตั้งทีละตัว

เข้าดู: apexifyy.up.railway.app
```

**Version B — ยาว (focus value):**
```
👑 ลูกค้า PRO ใหม่: Trade Plan v2 พร้อมใช้แล้ว!

ก่อนหน้านี้ AI บอกแค่ "TAKE PROFIT" "HOLD"
ตอนนี้บอกครบ:

✅ ขายออกกี่ % ที่ TP1
✅ ขายเพิ่มกี่ % ที่ TP2
✅ มี earnings ใกล้ๆ ระวังไหม
✅ Volume สูงเป็นพิเศษไหม (signal จริงหรือ noise)
✅ หุ้นนี้กระจุกเกินไปไหม
✅ ทำไม AI ให้คะแนนเท่านี้ (กด C-score expand ดูได้)

ฟีเจอร์ที่ลูกค้าขอกันมา:
🔔 ปุ่ม "ใช้แผนนี้" — กดเดียว → ตั้ง 3 alerts
   (TP1, TP2, SL) ครบเลย ไม่ต้องเปิดเมนู alert

ดู apexifyy.up.railway.app

ขอบคุณที่อยู่กับเรา 💚
ทีม Apexify
```

**Version C — สั้นมาก (Telegram message ultra-compact):**
```
🚀 Trade Plan v2 บนเว็บแดชบอร์ด

📊 ใหม่ในการ์ดหุ้น:
• Position sizing (ขายเท่าไหร่)
• Catalyst alert (earnings เร็วๆ นี้)
• Volume hot/cold
• ปุ่ม "ใช้แผน" → ตั้ง alerts ทีเดียว

🔗 apexifyy.up.railway.app
```

### Template: Daily Streak ประกาศ (ครั้งแรก deploy)

```
🔥 ฟีเจอร์ใหม่: Daily Streak System!

ใช้บอททุกวันต่อเนื่อง 7 วัน
→ รับ VIP +1 วันฟรี อัตโนมัติ!

ทำลายสถิติได้ไม่จำกัดครั้ง
ดูสถานะ streak ปัจจุบัน → พิมพ์ /account
หรือกดปุ่ม "💎 บัญชี / VIP" ในเมนู

เริ่มจากวันนี้ พิมพ์ชื่อหุ้น เช่น AAPL ได้เลย 🚀
```

### Template: /track ประกาศ

```
📊 ฟีเจอร์ใหม่: Track Record!

ตอนนี้คุณดูได้แล้ว ว่า AI Plans ของ Apexify
แม่นแค่ไหนใน 30/90 วันที่ผ่านมา

พิมพ์: /track

หลักฐานความน่าเชื่อถือ — โปร่งใส 100%
```

---

## 🎓 Educational / Tips

### Template: Tips การใช้บอท

```
💡 Tip ประจำวัน

รู้ไหม? พิมพ์ "/" ใน Telegram
จะเห็นคำสั่งทั้งหมดของบอทพร้อมคำอธิบาย

ไม่ต้องจำคำสั่งเอง!

ลองพิมพ์ "/" ตอนนี้เลยครับ ⚡
```

### Template: Indicator explainer

```
📚 รู้จัก RSI ใน 30 วินาที

RSI = Relative Strength Index
วัดว่าราคา "ร้อน" หรือ "เย็น"

🔴 > 70 = Overbought (ระวังย่อ)
🟢 < 30 = Oversold (อาจเด้ง)
⚪ 30-70 = Neutral

อยากเช็ค RSI หุ้น?
พิมพ์ชื่อหุ้น เช่น AAPL ในแชทนี้
ระบบจะคำนวณให้ทันที
```

### Template: How to use /ask (PRO)

```
💬 รู้ไหม? PRO user ถาม AI ได้ตรงๆ

พิมพ์: /ask <คำถาม>

ตัวอย่าง:
• /ask ทำไม RSI สูง?
• /ask ควรซื้อหุ้นเทคตอนนี้ไหม?
• /ask อธิบาย MACD ให้หน่อย

AI ตอบภาษาไทย ใช้ context หุ้นที่เพิ่งวิเคราะห์ด้วย
```

---

## 📚 Feature Tutorials (สอนใช้ฟีเจอร์ทีละตัว) ⭐

> ส่งสัปดาห์ละ 1-2 ตัว — เลือกตาม persona ที่ต้องการ activate
> เก็บไว้ rotate ใช้ — feature เดิมส่งซ้ำได้ทุก 2-3 เดือน

---

### T1 — พิมพ์ "/" ดูคำสั่งทั้งหมด (Free)
```
💡 รู้ไหม?

พิมพ์ "/" ใน Telegram แชทบอท
จะเห็นคำสั่งทั้งหมดพร้อมคำอธิบาย

ไม่ต้องจำเอง 16 คำสั่งหลัก
ลองเลย → กด "/" ในแชทตอนนี้ ⚡
```

---

### T2 — วิเคราะห์หุ้นไทย/ต่างประเทศ (Free)
```
🌍 บอทรู้จักหุ้น 10+ ประเทศ

🇺🇸 US: AAPL, NVDA, TSLA
🇹🇭 ไทย: PTT.BK หรือแค่ PTT (auto)
🇭🇰 HK: 0700.HK
🇯🇵 JP: 7203.T
🇰🇷 KR: 005930.KS

พิมพ์ชื่อหุ้น → AI วิเคราะห์ใน 5 วิ
ลองเลย: AAPL หรือ KBANK
```

---

### T3 — /freetrial ทดลอง PRO 7 วันฟรี (Free)
```
🎁 ทดลอง PRO ฟรี 7 วัน

พิมพ์ /freetrial → ปลดล็อกทันที:
✅ Entry / TP / SL ตัวเลขชัด
✅ /compare เปรียบเทียบหุ้น
✅ /ask ถาม AI ตรงๆ
✅ Smart Alerts + Price Alerts

ไม่ต้องผูกบัตร · ไม่หักเงิน
หลัง 7 วันกลับเป็น Free อัตโนมัติ

ลองเลย → /freetrial
```

---

### T4 — /track ดูสถิติ AI (Free)
```
📊 อยากรู้บอทแม่นแค่ไหน?

พิมพ์ /track → เห็นทันที:
✅ Hit Rate (% TP1/TP2 hit)
🛑 SL hit
⏱ เฉลี่ยเวลาถึง TP1
📅 จำนวน Plans เดือนนี้

โปร่งใส 100% — ไม่ขายฝัน
ลอง: /track
```

---

### T5 — /freetrial ครบ → ไม่อยากเสีย (Free → trial)
```
🔥 ใช้ /freetrial ครบ 7 วันแล้วชอบ?

ต่ออายุ PRO เพียง 109฿/เดือน:

หรือ — แต้มฟรีจาก:
🎁 Daily Streak: ใช้ 7 วันต่อ → +1 VIP
🤝 Referral: ชวน 3 คน → +10 วัน VIP
🎫 Promo Code: คอย /redeem ในเพจ FB

ดูสถานะ: /account
สมัครยุติ: /payment
```

---

### T6 — /fund ดู Fundamentals (VIP/PRO)
```
📊 ฟีเจอร์ที่ใช้บ่อยที่สุดของ VIP

พิมพ์ /fund AAPL → เห็นทันที:
💰 P/E ratio
💵 EPS
💎 Dividend Yield
📈 52-week high/low
🎯 Analyst target

ตัดสินใจได้ดีกว่าดูแค่กราฟ
ลอง: /fund NVDA
```

---

### T7 — /compare เปรียบเทียบหุ้น (PRO)
```
⚖️ เลือกระหว่าง 2 หุ้นไม่ถูก?

PRO ใช้ /compare ได้:
/compare AAPL MSFT
/compare PTT.BK BBL.BK CPALL.BK

→ เปรียบเทียบ side-by-side
→ AI Verdict สรุปตัวที่น่าสน
→ ไม่ต้องเปิด 2 แอปพร้อมกัน

ลอง: /compare AAPL GOOGL
```

---

### T8 — /ask ถาม AI ตรงๆ (PRO)
```
💬 มีคำถามเรื่องหุ้น? ถาม AI ได้!

PRO ใช้ /ask ได้ทุกเรื่อง:

/ask P/E ของ AAPL ที่ดีคือเท่าไร
/ask Tesla น่าซื้อตอนนี้ไหม
/ask เริ่มลงทุนหุ้นปันผลควรซื้อตัวไหน

AI ตอบเป็นภาษาไทย — รู้ context พอร์ตคุณด้วย
ลอง: /ask
```

---

### T9 — /setalert ตั้งเตือนราคา (PRO)
```
🔔 เห็นหุ้นน่าสน แต่รอราคาดี?

ตั้ง alert ทิ้งไว้:
/setalert AAPL 200    → เตือนเมื่อแตะ $200
/setalert PTT.BK 35   → เตือนเมื่อแตะ 35 บาท

✅ บอทเช็ค 24/7 อัตโนมัติ
✅ แจ้งทันทีที่ราคาถึง
✅ ไม่ต้องจ้องกราฟทั้งวัน

ดูทั้งหมด: /myalerts
ลบ: /delalert AAPL
```

---

### T10 — /earnings ก่อนประกาศงบ (VIP/PRO)
```
📅 หุ้นจะประกาศงบสัปดาห์นี้ไหม?

VIP/PRO ใช้ /earnings ได้:
/earnings AAPL → ดูวันประกาศ + AI วิเคราะห์ความคาดหวัง

หรือตั้งเตือน earnings:
/ealert AAPL → บอทเตือนล่วงหน้า 2 วันก่อนประกาศ

⚠️ Earnings = ราคาแกว่งแรง
รู้ก่อน เตรียมตัวก่อน
```

---

### T11 — /portfolio บันทึกพอร์ต (Free → PRO)
```
💼 บันทึกพอร์ตในบอทได้

พิมพ์: /add AAPL 10 150
(เพิ่ม 10 หุ้น ต้นทุน $150)

ดูพอร์ต: /portfolio
สร้างการ์ด P&L: /pnl

🎁 ฟรี 3 ตัว · VIP 10 · PRO ไม่จำกัด
ลองเริ่มเลย → /add
```

---

### T12 — /pnl สร้างการ์ดกำไร (Free)
```
🎨 อวดกำไรในเฟซบุ๊ก/ไลน์

พิมพ์ /pnl → ได้ภาพการ์ด P&L สวยงาม:
📊 มูลค่าพอร์ต
💚 กำไร / 🔴 ขาดทุน รวม
📈 Top 3 ตัวที่กำไรเยอะสุด

ภาพพร้อมแชร์ — ไม่ต้องตัด screenshot เอง
ลอง: /pnl
```

---

### T13 — Web Dashboard apexifyy.up.railway.app (PRO/VIP)
```
🌐 Web Dashboard เปิดให้ลูกค้า PRO/VIP

apexifyy.up.railway.app

เห็นได้ครบในจอเดียว:
📊 Trade Plan v2 ทุกหุ้นในพอร์ต
📈 Heatmap ตลาด
💰 P&L Tax Export (ยื่นภาษี)
🔥 AI Daily Pulse
🎯 Matchmaker หาหุ้นใหม่

login ด้วย Telegram → /dashboard
```

---

### T14 — Daily Streak สะสมแต้ม (ทุก tier)
```
🔥 ใช้บอทต่อเนื่อง = ของฟรี

7 วันติด → +1 วัน VIP ฟรีอัตโนมัติ
14 วันติด → +1 อีก
30 วันติด → +1 อีก

ดูสถานะ: /account หรือ /me

แค่พิมพ์ชื่อหุ้นวันละครั้งก็พอ
ทำได้ทุกวัน — ไม่จำกัดครั้ง
```

---

### T15 — Referral ชวนเพื่อน (ทุก tier)
```
🤝 ชวนเพื่อน = ได้ของฟรี

พิมพ์: /referral → ได้ลิงก์ส่วนตัว

ส่งให้เพื่อน → เพื่อนกดสมัคร:
🎁 เพื่อนได้ VIP 3 วันฟรี (ใหม่!)
🎁 คุณได้ +3 quota หรือ +10 วัน VIP/PRO ทุก 3 คน

แชร์ผ่าน Telegram inline button ทันที
```

---

## 🌐 Web Dashboard Push Series (WD1–WD10) ⭐

> ชุดข้อความเฉพาะสำหรับ **ดัน user ไปลองใช้ Web Dashboard** (apexifyy.up.railway.app)
> ส่งสัปดาห์ละ 1 ตัว rotate 10 สัปดาห์ — เน้น angle ต่างกันทุกครั้ง
> Login ใช้ `/dashboard` ในบอท → magic link เปิดเอง ไม่ต้องสมัครใหม่

---

### WD1 — เปิดตัว/Headline (ทุก tier)
```
🌐 Apexify มี Web Dashboard แล้ว!

apexifyy.up.railway.app

ทุกอย่างที่บอททำได้ + อีกเพียบ:
📊 พอร์ต + P&L แบบ real-time
🔥 AI Daily Pulse สรุปตลาดทุกเช้า
📈 Heatmap หุ้นในพอร์ตเป็นภาพ
💰 Tax Export ยื่นภาษีได้

login ครั้งเดียว → พิมพ์ /dashboard
ไม่ต้องสมัครใหม่ ไม่ต้องจำ password
```

---

### WD2 — Tax Export ยื่นภาษี (PRO)
```
💰 ยื่นภาษีปีนี้สบายขึ้น

Web Dashboard มีหน้า P&L Tax Export
สำหรับลูกค้า PRO โดยเฉพาะ:

✅ บันทึกซื้อ-ขายแต่ละครั้ง (manual)
✅ FIFO matching อัตโนมัติ
✅ รวมค่าธรรมเนียม + ภาษี ณ ที่จ่าย
✅ สรุปกำไรขาดทุน THB รายปี
✅ Export CSV format ภ.ง.ด.

→ apexifyy.up.railway.app/pnl
เริ่มบันทึกธุรกรรมก่อน ปลายปีไม่ต้องนั่งคิดเอง

login: /dashboard
```

---

### WD3 — Heatmap พอร์ตเป็นภาพ (VIP/PRO)
```
🔥 ดูพอร์ตทั้งก้อนในวินาทีเดียว

Web Dashboard → tab Heatmap

สี่เขียว = หุ้นที่บวก
สีแดง = หุ้นที่ลบ
ขนาดกล่อง = น้ำหนักในพอร์ต

ไม่ต้องไล่ดูทีละตัวเหมือนใน Telegram
เห็นปุ๊บรู้ปั๊บ ตัวไหนฉุดพอร์ต ตัวไหนพยุง

→ apexifyy.up.railway.app/heatmap
login: /dashboard
```

---

### WD4 — AI Daily Pulse ทุกเช้า (ทุก tier)
```
☀️ ทุกเช้าก่อนเปิดตลาด

Web Dashboard มี AI Daily Pulse:
🤖 Gemini สรุปตลาดเมกาเมื่อคืน
📊 หุ้นเด่น / sector ที่ขยับ
⚠️ ความเสี่ยงที่ต้องระวัง
🎯 Watch list สำหรับวันนี้

อ่านในชาเช้า 1 แก้ว — รู้ทันตลาด
update auto ทุก 30 นาที

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD5 — Share Card อวดพอร์ต (Free → ทุก tier)
```
🎨 อวดพอร์ตให้สวยกว่า screenshot

Web Dashboard → ปุ่ม "Share Card"
สร้างภาพ P&L 1080×1350 (IG portrait):

📸 มูลค่าพอร์ต + กำไร/ขาดทุน
📈 Top 3 ตัวที่ทำเงินเยอะสุด
🎨 ดีไซน์สะอาด ลง story ได้เลย
🔒 มี privacy mask ถ้าไม่อยากโชว์ตัวเลขจริง

โหลดภาพ → ลง FB / IG / Twitter ได้ทันที
→ apexifyy.up.railway.app
```

---

### WD6 — Mobile-Friendly (objection handle)
```
📱 เปิดบนมือถือก็ใช้ได้ครบ

Web Dashboard ออกแบบ mobile-first:
✅ ตารางพอร์ต scroll ลื่น
✅ กราฟแตะซูมได้
✅ ปุ่มใหญ่กดง่าย
✅ ไม่ต้องลงแอป — เปิด browser อย่างเดียว

ทดสอบในมือถือคุณเลย:
apexifyy.up.railway.app

login ด้วย /dashboard ในบอทนี้ → คลิกลิงก์ที่บอทส่งให้ → เข้าได้ทันที
```

---

### WD7 — Free user ก็ใช้ได้ (Free hook)
```
🎁 Free user ก็เข้า Web Dashboard ได้

ฟรีได้:
📊 ดูพอร์ต + P&L
📈 Watchlist + Heatmap
🔥 AI Daily Pulse
📰 ข่าวตลาด
🎯 Matchmaker หาหุ้นใหม่

PRO ปลดล็อกเพิ่ม:
🚨 Breaking News real-time
💰 Tax Export
📅 Earnings Calendar เต็มรูปแบบ

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD8 — Privacy Mask (objection: ไม่อยากโชว์ตัวเลข)
```
🔒 เปิดพอร์ตในที่ทำงาน/ร้านกาแฟได้สบาย

Web Dashboard มี Privacy Toggle:
แตะปุ่ม 👁 → ตัวเลขทั้งหน้าเปลี่ยนเป็น *

$1,672.14 → $*,***.**
850,000 บาท → ***,*** บาท

✅ Layout ไม่เพี้ยน — ตัวเลขถูกปิดทีละหลัก
✅ แตะอีกครั้งเพื่อโชว์
✅ จำสถานะไว้ — เปิดมาครั้งหน้าก็ยังปิดอยู่

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD9 — Matchmaker หาหุ้นใหม่ (VIP/PRO)
```
🎯 อยากซื้อหุ้นใหม่แต่ไม่รู้ตัวไหน?

Web Dashboard → Matchmaker
ตอบ 3 คำถามสั้นๆ:
1️⃣ สาย growth / dividend / value?
2️⃣ ทนความเสี่ยงได้แค่ไหน?
3️⃣ ระยะลงทุน?

→ AI คัดหุ้นจาก 150 ตัว universe สหรัฐ
→ ขึ้นมา 5-10 ตัวที่ match กับสไตล์คุณ
→ คลิกแต่ละตัวดูบทวิเคราะห์เต็ม

ไม่ต้องเดาเอง ไม่ต้อง scroll หาทั้งวัน
→ apexifyy.up.railway.app/matchmaker
```

---

### WD10 — ทำไมต้องใช้ทั้งบอท + Dashboard
```
🔄 บอท + Dashboard ใช้คู่กันได้ผลที่สุด

📱 Telegram bot — ใช้ตอน:
• อยู่นอกบ้าน
• อยากวิเคราะห์ 1 ตัวเร็วๆ
• รับ alert / breaking news

🌐 Web Dashboard — ใช้ตอน:
• เปิดดูพอร์ตรวมเช้า/เย็น
• บันทึกธุรกรรม + ดู P&L
• อยากเห็น Heatmap / Charts ใหญ่
• Export CSV ยื่นภาษี

ข้อมูลเดียวกัน sync ทันที — ไม่ต้องกรอกซ้ำ
→ apexifyy.up.railway.app
```

---

### WD11 — Health Score ตรวจสุขภาพพอร์ต (VIP/PRO)
```
🏥 พอร์ตคุณสุขภาพ "ดี" หรือ "ป่วย"?

Web Dashboard → Portfolio Health Score
ตรวจ 4 มิติพื้นฐาน:
✅ Diversification (≥ 5 ตัวขึ้นไป)
✅ Concentration (Top 3 รวม ≤ 60%)
✅ Sector spread — กระจายธุรกิจไหม
✅ Currency / Country spread

เห็นคะแนนทันที + จุดที่ควร rebalance
ไม่ต้องคิดเอง — ระบบ flag ให้

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD12 — Watchlist Heatmap (ทุก tier)
```
👀 หุ้นใน Watchlist ตัวไหนวิ่งวันนี้?

Web Dashboard → Watchlist Heatmap
✅ Equal-weight grid — ทุกตัวเห็นเท่ากัน
✅ สีแสดง % เปลี่ยนแปลงวันนี้
✅ แดงเข้ม = ลงแรง / เขียวเข้ม = ขึ้นแรง

ไม่ต้องเปิดดูทีละตัวใน Telegram
ปรากฏการณ์ "หุ้นกลุ่มไหน hot" — มองปุ๊บรู้ปั๊บ

→ apexifyy.up.railway.app/heatmap
login: /dashboard
```

---

### WD13 — ข้อมูลปลอดภัย — Auto Backup (ทุก tier)
```
🔒 ข้อมูลพอร์ตคุณ "ไม่หาย"

ทำไมเรื่องนี้สำคัญ:
คู่แข่งบางเจ้าลูกค้าเคยข้อมูลหายตอน login เครื่องใหม่
→ Apexify ออกแบบให้:

✅ เก็บใน Supabase cloud DB
✅ Backup อัตโนมัติทุกวัน
✅ Multi-device sync 100%
✅ ลบผิด — recover ได้ใน 30 วัน
✅ Export CSV เก็บเองได้ทุกเมื่อ
✅ "Last synced HH:MM" โชว์ทุกหน้า

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD14 — Magic Login ครั้งเดียว (objection: ขี้เกียจสมัคร)
```
🔑 ไม่ต้องสมัคร ไม่ต้องจำ password

Web Dashboard ใช้ Magic Login:
1️⃣ พิมพ์ /dashboard ในบอทนี้
2️⃣ บอทส่งลิงก์ — กดเลย
3️⃣ เข้าใช้ได้ทันที

✅ JWT signed — ปลอดภัย
✅ Session 24 ชม. — ไม่ต้องล็อกอินบ่อย
✅ ไม่ต้องตั้ง email + password
✅ ตัวบอทเองคือ "บัญชี" ของคุณ

ลองเลย → /dashboard
```

---

### WD15 — Earnings Calendar (PRO)
```
📅 หุ้นไหนจะประกาศงบสัปดาห์นี้?

Web Dashboard → Earnings Calendar
✅ ปฏิทินรายเดือน / รายสัปดาห์
✅ เน้นหุ้นที่คุณถืออยู่ + watchlist
✅ EPS estimate vs Actual ย้อนหลัง 4Q
✅ AI วิเคราะห์ความคาดหวังก่อนงบ
✅ หลังประกาศ — สรุปทันที beat / miss

PRO ปลดล็อกเต็มรูปแบบ
ไม่งงตอนราคาแกว่งหลังงบประกาศอีก

→ apexifyy.up.railway.app/earnings
login: /dashboard
```

---

### WD16 — Economic Calendar / Macro (PRO)
```
🌍 ข้อมูลเศรษฐกิจสำคัญสัปดาห์นี้

Web Dashboard → Economic Calendar
✅ FED meeting / CPI / PPI / NFP / GDP
✅ อันดับความสำคัญ (🔴🟠🟡)
✅ Forecast vs Actual real-time
✅ เวลาตามเขตเวลาไทย (UTC+7)

🌐 Macro page เพิ่มเติม:
✅ DXY / VIX / 10Y yield
✅ Gold / Oil / BTC

ก่อนเข้าซื้อ — เช็ค macro ก่อน
→ apexifyy.up.railway.app/economic-calendar
login: /dashboard
```

---

### WD17 — Breaking News Banner (PRO)
```
🚨 ข่าวด่วนที่ขยับตลาด — โผล่บน Dashboard ทันที

Web Dashboard มี Breaking News Banner
แถบสีแดงด้านบนเมื่อ HIGH impact:
🔴 Fed rate decision
🔴 CPI / PPI surprise
🔴 GDP shock / Geopolitical event

✅ AI Gemini classify ความสำคัญ
✅ สรุปไทย — อ่าน 10 วิเข้าใจ
✅ Dismiss ได้ทีละข่าว
✅ Sync กับบอท push ใน Telegram

PRO เท่านั้น — สาย active trader ห้ามพลาด
→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD18 — Benchmark พอร์ตชนะ S&P ไหม (VIP/PRO)
```
📈 พอร์ตคุณชนะ S&P 500 จริงไหม?

Web Dashboard → Benchmark
เปรียบเทียบ performance พอร์ตคุณกับ:
✅ S&P 500
✅ NASDAQ
✅ SET Index
✅ Custom benchmark ที่คุณเลือก

📊 กราฟ overlay 1M / 3M / 6M / 1Y / YTD
📊 % return เทียบกัน
📊 Volatility / Max Drawdown

รู้ว่าตัวเองเก่งจริง หรือแค่ตลาดดี
→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD19 — Morning Briefing auto-load (ทุก tier)
```
☕ Briefing ตลาดเช้า — ไม่ต้องกดปุ่ม

Web Dashboard → หน้า Morning
✅ เปิดเข้ามา = generate ให้ทันที
✅ สรุปตลาดเมกาเมื่อคืน
✅ Asia open + ไทย preview
✅ Top movers + sector ที่ขยับ
✅ ความเสี่ยง / catalyst วันนี้

อ่านพร้อมกาแฟ 1 แก้ว = อัปเดตครบ
อัปเดตทุก 30 นาที — ตอนตลาดเปิดยังสด

→ apexifyy.up.railway.app/morning
login: /dashboard
```

---

### WD20 — Tutorial Overlay สอนใช้ (ใหม่กับ Dashboard)
```
🎓 ใหม่กับ Web Dashboard? ไม่งงแน่

ครั้งแรกที่เข้า — มี Tutorial overlay 5 ขั้น:
1️⃣ ตำแหน่งพอร์ตอยู่ไหน
2️⃣ Watchlist เพิ่ม/ลบยังไง
3️⃣ AI Daily Pulse คืออะไร
4️⃣ Heatmap อ่านยังไง
5️⃣ ตั้ง alert จาก Web ได้

✅ 3 นาทีจบ
✅ Skip ได้ทุกขั้นตอน
✅ เปิดซ้ำได้จาก Help menu
✅ Persist — ไม่โผล่ซ้ำหลังจบ

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD21 — Dividend Tracking ปันผล (VIP/PRO)
```
💎 ปันผลปีนี้ได้รวมเท่าไรแล้ว?

Web Dashboard → Dividend Page
✅ รวมปันผลปีนี้ (THB + USD)
✅ Yield on Cost รายตัว
✅ ปฏิทิน ex-div date หุ้นที่ถืออยู่
✅ คาดการณ์ปันผลเดือนหน้า / ปีหน้า
✅ Tax withheld แยก US 15%

นักลงทุนสายปันผล — ติดตามรายเดือนได้ครบ
ไม่ต้องเปิด broker app ทีละเจ้า

→ apexifyy.up.railway.app/dividend
login: /dashboard
```

---

### WD22 — Watchlist Limit Visualizer (Free → upsell)
```
👀 อยากใส่ Watchlist เยอะกว่านี้?

Web Dashboard แสดง limit ชัดเจน:
🆓 Free: 5 ตัว
👑 VIP: 20 ตัว
🚀 PRO: ไม่จำกัด

✅ Visual bar — เห็นเต็มแค่ไหน
✅ ช่องล็อก — บอกว่าเพิ่มได้อีกกี่ตัว
✅ ปุ่ม Upgrade — เห็นราคาทันที

ไม่ต้องลบทิ้งเพื่อใส่ตัวใหม่ทุกครั้ง
→ apexifyy.up.railway.app/watchlist
login: /dashboard
```

---

### WD23 — USD/THB Toggle (เน้นลูกค้าต่างประเทศ + คนเทรดเมกา)
```
💱 ดูพอร์ตเป็น USD หรือ THB ก็ได้

Web Dashboard มี Currency Toggle:
แตะปุ่ม USD ↔ THB:
✅ มูลค่าพอร์ตทั้งก้อน
✅ P&L รวม / รายตัว
✅ ราคาต้นทุน + ราคาตลาด
✅ ทุกตัวเลขแปลงทันที

✅ Live FX rate (USDTHB อัปเดตทุก 30 นาที)
✅ จำสถานะไว้ — ครั้งหน้าเปิดมาก็ตรง

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD24 — Multi-device Sync (ทุก tier)
```
📱💻 มือถือ + คอม sync เห็นเหมือนกันทันที

Web Dashboard เก็บข้อมูลใน cloud (ไม่ใช่ local):
✅ บันทึกบน iPhone — เปิด iPad เห็นทันที
✅ แก้บน MacBook — มือถือ refresh ก็เห็น
✅ ไม่ต้อง export/import ข้ามเครื่อง
✅ "Last synced HH:MM" โชว์ทุกหน้า

ออฟฟิศ + บ้าน + นอกบ้าน — ใช้ได้ทุกที่
→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD25 — Time-saver vs Telegram (objection handle)
```
⏱ ดูพอร์ต 10 ตัวใน Telegram = scroll นาน

Web Dashboard ดูได้ใน 5 วินาที:
📊 ตารางทุกตัวพร้อมกัน
🔥 Heatmap visual ทั้งก้อน
💰 P&L รวม + รายตัว
📈 กราฟใหญ่ — ไม่ใช่ภาพ thumbnail

📱 Telegram = วิเคราะห์ตัวเดียวเร็ว ⚡
🌐 Web = รวมทุกตัวในจอเดียว 🖼

ใช้คู่กันคือถูกที่สุด
→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD26 — Soft Delete กู้คืนได้ (ทุก tier)
```
😱 ลบหุ้นออกจากพอร์ตผิดตัว — ไม่เป็นไร

Web Dashboard ใช้ Soft Delete:
✅ ไม่ลบจริงทันที — ทำเครื่องหมายไว้
✅ Recycle Bin เก็บ 30 วัน
✅ Recover ด้วยปุ่มเดียว — ข้อมูลกลับมาเหมือนเดิม

ทำผิดได้ — แก้กลับได้
ไม่ต้องกลัวลบทับธุรกรรมที่ใช้ยื่นภาษี

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD27 — Payment / Upgrade ในเว็บ (ลูกค้าใหม่)
```
💳 อัปเกรด VIP/PRO ในเว็บ — สะดวกกว่า DM admin

Web Dashboard → Payment Page
✅ การ์ดราคา VIP / PRO เปรียบเทียบชัด
✅ คัดลอกเลขบัญชี / PromptPay ปุ่มเดียว
✅ QR code โหลดง่าย
✅ Upload สลิปยืนยันในหน้าเดียว
✅ Status update ภายใน 5 นาที

นานาชาติ — มี PayPal link ด้วย
ไม่ต้องเปิด LINE คุย admin

→ apexifyy.up.railway.app/payment
login: /dashboard
```

---

### WD28 — News Feed Personalized (VIP/PRO)
```
📰 News Feed ที่เน้นหุ้นของคุณเอง

Web Dashboard → News Page
✅ Filter เฉพาะหุ้นในพอร์ต + watchlist
✅ Sources: Reuters / CNBC / MarketWatch / WSJ
✅ AI summary เป็นไทย
✅ Sentiment tag (Bullish / Bearish / Neutral)
✅ ลิงก์ไปอ่านต้นฉบับได้

ไม่ต้อง scroll ข่าวที่ไม่เกี่ยว
ตื่นเช้าอ่าน 5 ข่าว = อัปเดตหุ้นที่ถือทั้งวัน

→ apexifyy.up.railway.app/news
login: /dashboard
```

---

### WD29 — Add Stock + Auto-log Transaction (PRO)
```
➕ เพิ่มหุ้นเข้าพอร์ต + บันทึกธุรกรรม = ขั้นตอนเดียว

Web Dashboard → ปุ่ม + Add Stock
1️⃣ ค้นหา ticker (autocomplete)
2️⃣ ใส่จำนวน + ราคาต้นทุน
3️⃣ Popup ถาม "บันทึกธุรกรรมด้วยไหม?"
4️⃣ Pre-fill วันนี้ → กด OK เสร็จ

→ Portfolio + Transaction Log update พร้อมกัน
→ ปลายปีกด Export ยื่นภาษีได้เลย
→ ไม่ต้องนั่งรวม Excel เอง

→ apexifyy.up.railway.app
login: /dashboard
```

---

### WD30 — Web Dashboard ฟรี ไม่มีค่าใช้จ่ายแยก (Free hook)
```
🎉 Web Dashboard ฟรี — ไม่มีค่าสมาชิกแยก

ลูกค้า Apexify ทุกคนได้ใช้ทันที:
✅ Free tier — เข้าใช้ฟีเจอร์พื้นฐาน
✅ VIP — ปลดล็อกเพิ่ม (Heatmap, Health, Dividend)
✅ PRO — ครบทุกหน้า + Tax Export

login ด้วย Telegram (ฟรี) — ไม่ต้องสมัครใหม่
สิทธิ์ที่มีในบอท = สิทธิ์เดียวกันใน Web

→ apexifyy.up.railway.app
login: /dashboard
```

---

## 💡 Tips สำหรับ admin

### ลำดับการส่ง (อาทิตย์ละ 1 ตัว)
1. **อาทิตย์ที่ 1**: T1 (พิมพ์ /) — ขั้นพื้นฐาน
2. **อาทิตย์ที่ 2**: T3 (/freetrial) — กระตุ้น Free
3. **อาทิตย์ที่ 3**: T4 (/track) — สร้างความน่าเชื่อถือ
4. **อาทิตย์ที่ 4**: T11 (/portfolio) — engagement
5. **อาทิตย์ที่ 5**: T6 (/fund) — เพิ่ม value VIP
6. **อาทิตย์ที่ 6**: WD1 (เปิดตัว Web Dashboard) — broad reveal
7. **อาทิตย์ที่ 7**: WD4 (AI Daily Pulse) — habit formation ตอนเช้า
8. **อาทิตย์ที่ 8**: WD3 (Heatmap) — visual hook
9. **อาทิตย์ที่ 9**: WD2 (Tax Export) — push PRO conversion
10. **อาทิตย์ที่ 10**: WD5 (Share Card) — encourage UGC
11. ... rotate ต่อไปได้

### Web Dashboard Push — ลำดับแนะนำ (ดัน dashboard 6 อาทิตย์ติด)
1. **WD1** เปิดตัว — รู้ว่ามี
2. **WD30** ฟรีไม่มีค่าใช้จ่ายแยก — ลด barrier
3. **WD14** Login ขั้นตอนเดียว — ลด friction
4. **WD4 หรือ WD19** AI Daily Pulse / Morning — สร้าง habit
5. **WD3 หรือ WD12** Heatmap — visual hook
6. **WD2 หรือ WD9** Tax Export / Matchmaker — push PRO

### Web Dashboard 30 ตัว — จัดหมวดเลือกง่าย

🆕 **Discovery / Headline** — ใช้ครั้งแรกในชุด
- WD1 (เปิดตัวรวม), WD25 (เทียบกับ Telegram = time saver)

🆓 **Free hook / ลด barrier** — กระตุ้น Free user เข้าลอง
- WD7 (Free ก็เข้าได้), WD14 (login ครั้งเดียว), WD30 (ฟรีไม่แยก), WD20 (Tutorial แม้ใหม่)

💰 **PRO Upsell** — เน้นปลดล็อกฟีเจอร์
- WD2 (Tax Export), WD9 (Matchmaker), WD15 (Earnings), WD16 (Macro), WD17 (Breaking News), WD29 (Auto-log Transaction)

📊 **Visual / Engagement** — feature ที่เห็นค่าทันที
- WD3 (Portfolio Heatmap), WD12 (Watchlist Heatmap), WD18 (Benchmark), WD19 (Morning auto), WD21 (Dividend), WD28 (News personalized)

🔐 **Trust / Safety** — ขจัดความกลัว
- WD8 (Privacy Mask), WD13 (Auto Backup), WD26 (Soft Delete recovery)

📱 **Friction killer** — แก้ objection เรื่องการใช้งาน
- WD6 (Mobile-friendly), WD14 (Magic login), WD24 (Multi-device sync)

📈 **Power feature** — สาย active ใช้บ่อย
- WD11 (Health Score), WD22 (Watchlist limit), WD23 (USD/THB), WD27 (Payment in-web)

🎨 **Social / Viral** — กระตุ้นแชร์
- WD5 (Share Card 1080×1350)

🔄 **Combo / Behavior** — สร้าง habit ระยะยาว
- WD4 (AI Daily Pulse), WD10 (Bot+Web combo), WD25 (Time-saver)

### เลือกตาม persona
- **Free user เยอะ** → T1, T2, T3, T11, T12, T14, **WD1, WD5, WD7, WD20, WD30**
- **VIP เยอะ (push ไป PRO)** → T6, T10, T15, **WD2, WD9, WD15, WD16, WD17, WD21**
- **PRO เยอะ (deep retention)** → T7, T8, T9, **WD11, WD18, WD23, WD28, WD29**
- **คน lapse / ไม่เข้านาน** → **WD1, WD4, WD6, WD14, WD19** (ทุกตัว = ลด friction + สร้าง habit)
- **คนสายปันผล** → **WD21, WD13, WD27**
- **คนสาย active trader** → **WD15, WD16, WD17, WD18**
- **ลูกค้าต่างประเทศ** → **WD23, WD27** (USD/THB + PayPal payment)

### ลบลิงก์ก่อนส่ง
ถ้า template มี `/freetrial` หรือ `/track` ในข้อความ — Telegram จะ render เป็นปุ่มกดได้อัตโนมัติ ✅
ไม่ต้องใส่ inline button เพิ่ม

---

## 📅 Market Update / Reminder

### Template: เช้าวันจันทร์ — กระตุ้นเริ่มสัปดาห์

```
🌅 สวัสดีเช้าวันจันทร์!

สัปดาห์นี้มีอะไรน่าจับตา? เช็คได้จาก:
📊 Morning Briefing วันนี้ 8:30 (VIP/PRO)
📰 Flash News ทุก 3 ชม. (PRO)
📅 Weekly Digest ทุกศุกร์ (VIP/PRO)

เริ่มสัปดาห์ด้วย Apexify 🚀
```

### Template: Earnings season ใกล้มา

```
📈 Earnings Season กำลังจะมา!

หุ้นใหญ่ๆ เตรียมประกาศงบในสัปดาห์หน้า:
• AAPL: 30 เม.ย.
• MSFT: 1 พ.ค.
• NVDA: 22 พ.ค.

VIP/PRO: สมัครแจ้งเตือนผ่าน
/ealert AAPL
/ealert MSFT
/ealert NVDA

ระบบแจ้งล่วงหน้า 1 วัน + เช้าวันงบ 📅
```

### Template: ตลาดผันผวน — เตือนระวัง

```
⚡ ตลาดผันผวนสูงวันนี้

VIX สูงผิดปกติ — ระวังการเทรดช่วงนี้

📊 Apexify จะเตือนใน AI Insight ทุกครั้ง
ที่เจอช่วง extreme volatility

PRO: ตรวจ R:R ทุก Plan ก่อนเข้า
ถ้า R:R < 1.5 ควรรอจังหวะดีกว่า
```

---

## 🤝 Referral / Community

### Template: กระตุ้นชวนเพื่อน

```
🤝 ชวนเพื่อนใช้ Apexify — ทั้งคู่ได้รางวัล!

✨ คุณ (คนชวน) ได้:
• ทุก 1 เพื่อน → +3 quota
• ทุก 3 เพื่อน → +10 วัน VIP/PRO!

🎁 เพื่อน ได้:
• VIP 3 วันฟรี ทันที

ดึงลิงก์ชวนเพื่อนของคุณ:
👉 กดเมนู 📱 → 🤝 ชวนเพื่อน
หรือกด /menu_referral
```

### Template: Streak champion

```
🔥 Streak Champion of the Week!

🥇 [ชื่อ user] — 23 วัน
🥈 [ชื่อ user] — 18 วัน
🥉 [ชื่อ user] — 12 วัน

อยากติดอันดับ? ใช้ Apexify ทุกวัน
ครบ 7 วัน รับ VIP +1 วันฟรี
ครบ 30 วัน → Hall of Fame!

เปิดบอทตอนนี้: พิมพ์ชื่อหุ้นใดก็ได้
```

---

## ⚠️ Maintenance / System

### Template: ก่อน Maintenance

```
🔧 แจ้งซ่อมบำรุงระบบ

วันที่: XX/XX/XXXX
เวลา: XX:XX - XX:XX (ประมาณ X ชม.)

ผลกระทบ:
• บอทอาจตอบช้าหรือไม่ตอบช่วงนี้
• Alerts จะส่งหลังระบบกลับมา

ขออภัยในความไม่สะดวก 🙏
ทีม Apexify
```

### Template: หลัง Maintenance

```
✅ ระบบกลับมาปกติแล้ว!

ขอบคุณที่อดทนรอครับ
ตอนนี้ใช้งานได้เต็มรูปแบบเหมือนเดิม

มีฟีเจอร์ใหม่อะไรบ้าง?
👉 พิมพ์ /demo เพื่อดูทัวร์ฟีเจอร์
```

### Template: เตือนปัญหา 3rd party

```
⚠️ แจ้งสถานการณ์: API ของ Yahoo Finance ขัดข้องชั่วคราว

ข้อมูลราคาหุ้นบางตัวอาจไม่อัปเดตช่วงนี้
ระบบกำลังเฝ้าและจะ retry อัตโนมัติทันที

ขออภัยในความไม่สะดวก
จะแจ้งอีกครั้งเมื่อกลับมาปกติ 🙏
```

---

## 💎 Subscription / Upgrade

### Template: VIP early bird (ก่อนขึ้นราคา)

```
💎 ราคาพิเศษ Early Bird!

ก่อนเราขึ้นราคา VIP จาก 79฿ → 99฿
ในเดือนหน้า สมัครตอนนี้ล็อคราคา 79฿/เดือน

⏰ ถึงสิ้นเดือนนี้เท่านั้น

สมัคร → กด 💎 บัญชี / VIP
หรือพิมพ์ /freetrial ลองก่อน 7 วัน
```

### Template: Win-back สำหรับ user ที่หมดอายุ

```
👋 เราคิดถึงคุณ!

แพ็กเกจของคุณหมดไปสักพักแล้ว
มีฟีเจอร์ใหม่หลายอย่างที่คุณยังไม่ได้ลอง:
🆕 Track Record (/track)
🆕 Stock Compare (/compare)
🆕 Daily Streak system

🎁 พิเศษ: ใช้โค้ด WELCOMEBACK14
รับ VIP 14 วันฟรี (จำกัด 100 คนแรก)
```

> 💡 ก่อนใช้: gen โค้ดด้วย `/gencode 14 100 vip` → ได้ชื่อโค้ดจริงมาใส่

---

## 🎉 Celebration / Milestone

### Template: ครบ 100/500/1000 user

```
🎉 ครบ 100 คนแล้ว!

ขอบคุณทุกคนที่ใช้ Apexify

🎁 Special: ใช้โค้ด THANK100
รับ VIP +14 วันฟรี (วันละ 50 คน)

ฉลองด้วยกันครับ 🎊
```

### Template: ครบ 1 ปี Apexify

```
🎂 Happy 1 Year Apexify!

ขอบคุณทุกคนที่ร่วมเดินทางกับเรา
ปีที่ผ่านมา:
✅ XXX paying users
✅ XX% Track Record hit rate
✅ XX features ใหม่

🎁 ของขวัญ: PRO 30 วัน ฟรี!
ใช้โค้ด BIRTHDAY1Y (ใช้ได้ 200 คน)
```

---

## 🚫 ห้ามใช้ใน /broadcast

- ❌ ข้อความขายแบบ aggressive ("ซื้อตอนนี้รวย!")
- ❌ Spam (มากกว่า 1 ครั้ง/สัปดาห์)
- ❌ ข้อความยาวเกิน 4096 ตัวอักษร
- ❌ Markdown ที่ไม่ test ก่อน (เคย break แล้ว)
- ❌ ลิงก์ external ที่ไม่ verify
- ❌ Promo ที่ไม่มี end date

---

## 📊 Best Practices

### Frequency
- **Promo/Free code:** 1-2 ครั้ง/เดือน (พิเศษ + กระตุ้น)
- **Track Record:** 1 ครั้ง/เดือน (เดือนสุดท้าย)
- **Feature announcement:** ทันทีเมื่อ deploy ใหม่
- **Educational:** 2-4 ครั้ง/เดือน (วันธรรมดา)
- **Market update:** ตอนเหตุการณ์สำคัญเท่านั้น
- **Maintenance:** ก่อน-หลังทุกครั้ง

### เวลาส่งที่ดี (Thai time)
- 🌅 **08:00-09:00** — ก่อนตลาดเปิด (engagement สูง)
- 🍽 **12:00-13:00** — พักเที่ยง (อ่านได้นาน)
- 🌆 **18:00-20:00** — หลังเลิกงาน (peak)
- ❌ **00:00-06:00** — กลางคืน (ห้าม)

### Format ที่ engage
1. เปิดด้วย emoji + ขึ้นไปเส้น
2. ประโยคแรกสั้น = ไอเดียใหญ่
3. Bullet points อ่านง่าย
4. CTA ชัดเจน (พิมพ์อะไร / กดอะไร)
5. Markdown bold/italic แต่พอประมาณ

### ก่อนกด /broadcast checklist
- [ ] ส่งทดสอบให้ admin ตัวเองก่อน
- [ ] เช็ค Markdown render ถูก
- [ ] ลิงก์ทั้งหมด work
- [ ] โค้ดที่อ้างถึง — gen แล้วและยัง active
- [ ] เวลาส่งเหมาะสม (ไม่ใช่ตี 3)
- [ ] ข้อความไม่เกิน 4096 ตัวอักษร

---

ดูต่อ:
- [[12 - Admin Commands]]
- [[19 - Facebook Post Templates]]
- [[17 - Sales Playbook]]

#broadcast #templates #admin
