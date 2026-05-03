---
tags: [campaign, broadcast, marketing, dashboard, social-media]
---

# 🎯 Dashboard Drive Campaigns

> ดัน user ให้ใช้ Web Dashboard (apexifyy.up.railway.app) เยอะขึ้น
> เพิ่มเติมจาก [[21 - Broadcast Templates]] section "WD1-WD30" ที่อธิบาย feature
> ชุดนี้เน้น **action-oriented** + **multi-channel** — หลัง customer เห็น WD แล้วยังไม่กดเปิด

> **สำคัญ:** Bot + Web = Apexify โปรเจกเดียว — ลูกค้าซื้อ tier เดียวได้ทั้งคู่ ไม่ใช่ 2 product แยก

---

## 📋 ทำไมต้องดัน Dashboard

| ปัญหา | สาเหตุ | แก้ด้วย |
|-------|-------|---------|
| User vIP/PRO ลืมว่ามีเว็บ | บอทใช้สะดวก จนไม่เข้าเว็บ | broadcast เน้น "feature ที่บอททำไม่ได้" |
| Free user ไม่รู้ว่าเข้าเว็บได้ | คิดว่าเว็บ = pay only | hook "ฟรี เข้าได้เลย" |
| ลูกค้าใหม่ไม่รู้ว่ามี | onboarding ไม่ได้สอน | DM/comment template |
| Comeback user lapse 30 วัน+ | ลืมแล้ว | win-back broadcast พ่วง dashboard |

**KPI วัดผลแคมเปญ:**
- Daily active users (DAU) ในเว็บ จาก `bot_command_log` + heartbeat ของ web
- /dashboard command usage ในบอท
- Magic-login token redemption rate

---

# A. 🚀 Telegram Broadcasts — Aggressive Drive (DD1–DD12)

> ใช้แทรกระหว่าง WD series ใน [[21 - Broadcast Templates]]
> เน้น **scarcity + FOMO + ตัวเลข** — ไม่ใช่อธิบาย feature แต่กระตุ้นให้กดทันที

## DD1 — "5 วิ ลองเปิด" (ทุก tier — เน้น instant gratification)

```
⏱ 5 วินาที — เปิด dashboard ครั้งแรก

ไม่ต้องสมัคร · ไม่ต้องตั้งรหัสผ่าน
แค่กด /dashboard ในแชทนี้ → ลิงก์เปิดเว็บ → login auto

ลองเปิดเลย พิมพ์ /dashboard
→ ปิดได้ตลอด ถ้าไม่ใช่สิ่งที่ใช่
```

> Hook: **ลด barrier เหลือ 0** — ปลด objection "ขี้เกียจ" / "ไม่อยากสมัคร"

## DD2 — "ปิด market แล้วไปไหน" (PRO/VIP — habit hook)

```
🌙 ตลาด US ปิดแล้ว — เอาเวลาไปทำอะไร?

แทนที่จะรอเปิดพรุ่งนี้ ลองเข้า dashboard
→ ดูผลพอร์ตวันนี้กับ benchmark
→ Heatmap หุ้นที่กำไรเยอะที่สุด
→ AI Daily Pulse สรุปสั้นๆ ก่อนนอน

apexifyy.up.railway.app
หรือพิมพ์ /dashboard
```

> Hook: **timing** — ส่ง 4-5 ทุ่ม Thai time = หลัง US close

## DD3 — "เห็น 3 หุ้น พร้อมกัน" (objection: บอทดู 1 ตัวเสียเวลา)

```
💡 แทนที่จะพิมพ์ทีละตัวในบอท

เปิด Dashboard → เห็นพอร์ตทั้งหมดพร้อมกันใน 1 หน้า
✅ Heatmap — รู้ทันทีว่าหุ้นไหนทำกำไร/ขาดทุน
✅ Health Score — สถานะพอร์ตโดยรวม
✅ Auto-update — ไม่ต้องพิมพ์อะไร แค่เปิดดู

→ apexifyy.up.railway.app
```

> Hook: **time-saver framing** — บอท = single ticker, web = bird's eye

## DD4 — "อันนี้บอททำไม่ได้" (PRO upsell)

```
🔓 5 อย่างที่บอทไม่มี — แต่เว็บ Dashboard มี

1. 📊 Heatmap พอร์ตเป็นภาพ (เห็นกำไร/ขาดทุนเป็นสี)
2. 🎯 Matchmaker หาหุ้นเข้ากับ style ของคุณ
3. 📈 Benchmark เทียบกับ S&P 500 / SET
4. 💰 Tax Export ยื่นภาษี (.xlsx)
5. 📅 Economic Calendar ตามสีตลาด

ใช้สิทธิ์เดียวกับบอท — ไม่มีค่าใช้จ่ายเพิ่ม
→ /dashboard
```

> Hook: **5 features เด็ดที่ web-exclusive** — ดึง PRO user ที่ใช้เฉพาะบอท

## DD5 — "ลูกค้าจริง 3 คน" (social proof — เปลี่ยนชื่อตามจริง)

```
💬 3 ลูกค้าใช้เว็บแล้วบอกว่า...

🗣 "เปิด heatmap เช้าทุกวัน รู้สถานะพอร์ตใน 5 วิ"
🗣 "Tax Export ตอนยื่นภาษี ประหยัดเวลา 2 ชม."
🗣 "Matchmaker เจอหุ้นใหม่ 3 ตัวที่เข้ากับสไตล์"

เอาบ้างมั้ย?
→ apexifyy.up.railway.app
หรือ /dashboard
```

> Hook: **testimonial** — แทน feature claim. ⚠️ ใช้ quote ลูกค้าจริงเท่านั้น

## DD6 — "วันนี้คุณพลาด" (PROBlem-Aware — for inactive)

```
⏰ วันนี้คุณพลาดอะไรไปบ้าง?

ถ้าไม่ได้เข้า Dashboard:
❌ ไม่เห็น 1 หุ้นในพอร์ตที่กำไร +12% เพิ่มขึ้น (vs เมื่อวาน)
❌ ไม่เห็น Earnings ของ AAPL ที่ประกาศพรุ่งนี้
❌ ไม่เห็น Breaking News ที่อาจกระทบ

ทุกวันที่ไม่เปิด — ก็ปล่อย info สำคัญไป

5 วิเปิดเช็ค → /dashboard
```

> Hook: **loss aversion** — กระตุ้นความรู้สึกว่ากำลังเสียโอกาส

## DD7 — "ลูกค้าใช้เว็บก่อน" (PRO segmented push)

```
👑 PRO member ปกติทำอะไรกับ Dashboard?

📅 เช้า 8:00 — เปิดดู AI Daily Pulse + Morning Briefing
📊 9:30 (ตลาด US เปิด) — เช็ค Heatmap พอร์ตหลัก
🎯 ระหว่างวัน — ดู Earnings + Breaking News บน feed
🌙 ก่อนนอน — Benchmark vs S&P + วางแผน Watchlist

ลอง routine นี้ดู — เริ่มที่ /dashboard
```

> Hook: **prescriptive routine** — บอกวิธีใช้เป็นกิจวัตร ลด decision fatigue

## DD8 — "Free ก็เข้าได้" (Free hook — ลด barrier)

```
🆓 Web Dashboard ฟรี — Free user ก็เข้าได้

ไม่ต้องเป็น VIP/PRO
ไม่มีค่าใช้จ่ายแยก
สิทธิ์ที่มีในบอท = สิทธิ์เดียวกันในเว็บ

แค่กด /dashboard → ลิงก์ → login auto
→ ลองเลย ไม่เสียอะไร
```

> Hook: **lower price objection** — clear ว่า web ≠ paid product แยก

## DD9 — "สิ่งที่ต้องตั้งให้ถูก 1 ครั้ง" (PRO conversion path)

```
📌 ตั้งครั้งเดียว — ใช้ทุกวัน

ใน Dashboard ทำได้ใน 2 นาที:
✅ Watchlist — เพิ่มหุ้นที่ติดตาม (ไม่ต้องพิมพ์ทุกครั้ง)
✅ Health Score — เช็คพอร์ตอัตโนมัติ
✅ Notification — เตือน earnings + price + macro

ทำในบอทก็ได้ แต่เว็บเร็วกว่า + เห็นทั้งหน้า

→ /dashboard
```

> Hook: **setup efficiency** — บอกว่าเว็บ = setup hub

## DD10 — "ดู screenshot ก่อนตัดสิน" (visual hook)

```
👀 ดูก่อนว่าหน้าตา Dashboard เป็นยังไง

→ apexifyy.up.railway.app

ไม่ต้อง login ก็เห็นหน้า login ที่ดูได้
ถูกใจค่อย /dashboard ในแชทเพื่อ login auto
ไม่ถูกใจก็ปิด — ไม่มีอะไรเสีย

ใช้เวลาดู 30 วิ → ตัดสินเอง
```

> Hook: **try-before-commit** — ปลด objection "กลัวลำบาก"

## DD11 — "อาทิตย์นี้พอร์ตเป็นยังไง" (weekly recap habit)

```
📊 อาทิตย์นี้พอร์ตคุณเป็นยังไง?

เปิด Dashboard 1 ครั้ง — เห็นทุกตัวเลข:
✅ P&L 7 วันย้อนหลัง
✅ หุ้นที่ทำกำไรสูงสุด/ขาดทุนสูงสุด
✅ Benchmark vs S&P 500 / SET
✅ Health Score พอร์ตโดยรวม

ใช้เวลาแค่ 2 นาที ทุกศุกร์
→ /dashboard
```

> Hook: **weekly ritual** — ส่งวันศุกร์เย็น = ลูกค้ามีเวลาเช็ค

## DD12 — "ขอเวลา 60 วินาที" (commitment device)

```
⏱ ขอเวลา 60 วินาทีของคุณ

1. กด /dashboard
2. รอ 5 วิ — เปิดเว็บ login auto
3. ดู Heatmap — รู้สถานะพอร์ต
4. ปิด — ใช้ชีวิตต่อ

ถ้าวันนี้คุณยังไม่เคยเปิด — เริ่มที่นี่
ถ้าเคยแล้ว — แวะเช็คอีกครั้ง

→ พิมพ์ /dashboard ตอนนี้
```

> Hook: **micro-commitment** — 60 วิ = ไม่นาน, action ชัด

---

# B. 📘 Facebook Posts (FB-DD1 — FB-DD8)

> โพสบนเพจ Apexify — ใช้รูป screenshot ประกอบ
> Format: **Hook line สั้น → benefit list → CTA → ลิงก์**

## FB-DD1 — Visual Hook + Screenshot

```
💼 พอร์ตหุ้นคุณ เปิดดูใน 5 วิทาง...

[📸 screenshot Dashboard heatmap]

ไม่ต้องเปิดบัญชีบล็อกเกอร์
ไม่ต้องสมัครเว็บใหม่
ไม่ต้องตั้งรหัสผ่าน

ถ้าใช้ Apexify อยู่แล้ว → กดในบอท /dashboard ได้เลย
ลูกค้า Free / VIP / PRO — เข้าได้ทุกคน

→ apexifyy.up.railway.app
🤖 บอท: t.me/apexify_bot

#Apexify #พอร์ตหุ้น #หุ้นไทย #หุ้นเมกา #AI
```

## FB-DD2 — Before/After Comparison

```
🆚 ก่อน vs หลัง ใช้ Dashboard

❌ ก่อน:
- พิมพ์ "/portfolio" ใน Telegram → ดู text ตัวเลข
- พิมพ์ "/pnl" → ดูรูป
- พิมพ์ "/compare A B" → เปรียบเทียบ 2 ตัว

✅ หลัง:
- เปิด Dashboard 1 หน้า → เห็นทุกอย่างพร้อมกัน
- Heatmap, Health Score, Benchmark, Watchlist — ครบจอเดียว
- Auto-refresh ทุก 60 วิ

ทดลองเข้าฟรี → apexifyy.up.railway.app
ใช้สิทธิ์เดียวกับบอท Apexify
```

## FB-DD3 — Pain Point + Solution

```
😩 ปวดหัวกับการตามดูพอร์ตหลายตัว?

ปัญหาที่ทุกคนเจอ:
- 5 หุ้น = 5 ครั้งที่ต้องพิมพ์
- ไม่รู้ว่าตัวไหนกำไร/ขาดทุนสุด
- ลืมว่ามี earnings ของ AAPL พรุ่งนี้

ทางแก้: Apexify Dashboard
- เห็นทั้งพอร์ตเป็นภาพ
- Earnings calendar ในตัว
- Auto-track ทุกการเทรด

🤖 ถ้ายังไม่มีบอท → t.me/apexify_bot
🌐 มีอยู่แล้ว → /dashboard ในแชท
```

## FB-DD4 — Free Hook (catch lurkers)

```
🎁 Apexify Web Dashboard — Free user ก็ใช้ได้!

✅ ดูพอร์ตในรูปแบบ visual
✅ Watchlist 5 ตัว (Free) / 50 ตัว (VIP+)
✅ AI Daily Pulse ทุกเช้า
✅ News feed personalized
✅ ภาษาไทย + dark/light theme

login ครั้งเดียว ใช้ได้ทุกเครื่อง (มือถือ + PC)
ไม่มีค่าใช้จ่ายแยก — ใช้สิทธิ์เดียวกับบอท

ทดลอง: apexifyy.up.railway.app
```

## FB-DD5 — Mobile-First (Gen Z hook)

```
📱 Dashboard ที่ออกแบบมาให้ดูบนมือถือก่อน

PWA — install เป็น app ได้
เปิดเร็ว ไม่ต้องโหลดหน้าใหม่
Dark mode by default
Heatmap ปรับขนาดตามจอ
Swipe ระหว่าง tabs ได้

→ apexifyy.up.railway.app
(เปิดใน Chrome → menu → "Add to Home screen" → เป็น app)

#PWA #Mobile #UI
```

## FB-DD6 — Tax Season Tie-in (กรกฎาคม–มีนาคม)

```
📋 ใกล้ยื่นภาษีแล้ว — Apexify ช่วย Export ให้

PRO members:
✅ Export transactions ทั้งหมดเป็น .xlsx
✅ จัดรูปแบบ ภงด.90 ให้
✅ คำนวณกำไร/ขาดทุนต่อ trade
✅ ลบ duplicate auto

ไม่ต้องเริ่มต้นจาก Excel เปล่า — Dashboard ให้ตั้งต้น
→ apexifyy.up.railway.app/export

ราคา PRO: 109฿/เดือน · 1,090฿/ปี
```

## FB-DD7 — "ทำไมต้องมี" (educational)

```
🤔 ทำไม Apexify ต้องมีทั้งบอท + เว็บ?

🤖 บอท Telegram = quick & alert
- พิมพ์ /track AAPL → ตอบใน 2 วิ
- รับ alert price ทันที
- ไม่ต้องเปิด tab ใหม่

🌐 เว็บ Dashboard = deep & visual
- เห็นพอร์ตทั้งหมดพร้อมกัน
- ตั้งค่าครั้งเดียว ใช้ตลอด
- Tax Export, Heatmap, Benchmark

ทั้งคู่ใช้สิทธิ์เดียวกัน — ลูกค้าซื้อ tier เดียวได้ทั้งคู่

🤖 t.me/apexify_bot
🌐 apexifyy.up.railway.app
```

## FB-DD8 — Live Demo Invite

```
🎬 Demo สด — เปิดวันอาทิตย์ 20:00

ลอง Apexify Dashboard ผ่าน screen share
- Tour ทุกหน้า
- ตอบคำถามสด
- โชว์ feature ที่หลายคนยังไม่รู้

ฟรี 100% · ไม่ขายอะไร
ลงทะเบียน: comment "demo" + ชื่อ Telegram

วันถัดมาจะส่ง broadcast ในบอทเตือน
```

---

# C. 📸 Instagram (IG-DD1 — IG-DD5)

> ใช้รูปจริง / screenshot Dashboard
> Format: **caption สั้น + hashtag เยอะ + emoji**

## IG-DD1 — Heatmap Showcase (carousel post)

**รูป:** Heatmap dashboard screenshot

**Caption:**
```
🎨 พอร์ตเป็นภาพ — ดูใน 5 วิ

แทนที่จะนั่งคำนวณ%
เปิด Apexify Dashboard
→ heatmap เห็นทันที ไหนกำไรไหนขาดทุน

ลิงก์ใน bio 📎
หรือกด /dashboard ในบอท Apexify

#Apexify #หุ้น #พอร์ตหุ้น
#stockportfolio #stocktrading #stockdashboard
#AI #FinTech #SET #NASDAQ
#มือใหม่ลงทุน #หุ้นต่างประเทศ
```

## IG-DD2 — Reels Hook (15-second video)

**Hook (3 วิแรก):**
```
"ถ้าคุณยังพิมพ์ดูทีละหุ้นในบอท คุณกำลังเสียเวลา"
```

**Caption:**
```
⏱ 5 หุ้น = 5 ครั้งพิมพ์ในบอท
⏱ 5 หุ้น = 1 ครั้งเปิด Dashboard

Apexify Web Dashboard — เห็นพอร์ตทั้งหมดในจอเดียว
ลิงก์ใน bio

#timesaver #stocktips #investing
```

## IG-DD3 — Story Highlight (cover)

**รูป:** Logo + "DASHBOARD" text overlay

**Story sequence (5 frames):**
1. "พอร์ตคุณวันนี้ +5.2%" (P&L screenshot)
2. "หุ้นที่ทำกำไรสุด: GOOGL +12.5%" (heatmap zoom)
3. "Earnings พรุ่งนี้: AAPL, NVDA" (calendar screenshot)
4. "Benchmark: ชนะ S&P +2%" (benchmark chart)
5. "เปิดเลย → swipe up หรือกดลิงก์ใน bio"

## IG-DD4 — UGC Repost (ลูกค้าจริง)

**รูป:** ลูกค้า screenshot dashboard (ขออนุญาตก่อน)

**Caption:**
```
✨ ลูกค้าจริง — @username
"เปิด Apexify Dashboard เช้าทุกวัน
รู้สถานะพอร์ตใน 5 วินาที"

ขอบคุณที่แชร์ครับ 🙏
ใครอยากลอง — link bio

#customerstory #Apexify #investing
```

## IG-DD5 — Educational Carousel

**Slide 1:** "5 อย่างที่ Dashboard ทำได้ดีกว่าบอท"
**Slide 2-6:** แต่ละ feature 1 slide
**Slide 7:** "ลิงก์ใน bio → ลองเลย"

**Caption:**
```
💡 บอท Telegram + Web Dashboard = ดีกว่ากันคนละแบบ

บอท: เร็ว · ทันใจ · alert
เว็บ: เห็นภาพ · ครบจอ · setup ครั้งเดียว

ลูกค้า Apexify ใช้ได้ทั้งคู่ — ไม่มีค่าใช้จ่ายเพิ่ม
ลิงก์ใน bio 🔗

#StockMarket #Investing #Thailand
```

---

# D. 🐦 Twitter / X (X-DD1 — X-DD5)

> Format: **280 chars · 1-3 hashtag · ลิงก์ตรง**

## X-DD1 — Single Punchy Line

```
ถ้ายังพิมพ์ /track ทีละตัวในบอท ลองเปิด Dashboard ดู

Heatmap พอร์ตเห็นใน 5 วิ
ลูกค้า Apexify เข้าได้ทุก tier

→ apexifyy.up.railway.app

#Apexify #หุ้น
```

## X-DD2 — Question Hook

```
คุณดูพอร์ตหุ้นในมือถือยังไง?

ถ้ายัง screenshot จากแอปธนาคารทุกวัน — มี Apexify Dashboard ที่ดีกว่า

✅ Auto-update
✅ Heatmap visual
✅ Free login ผ่าน Telegram

→ apexifyy.up.railway.app
```

## X-DD3 — Comparison Tweet

```
Apexify บอท: พิมพ์ /track AAPL → ตอบ
Apexify เว็บ: เปิดเห็นพอร์ตทั้งหมดพร้อมกัน

Same account · Same tier · No extra fee

→ /dashboard ในบอท
```

## X-DD4 — Stat Hook

```
ลูกค้า Apexify ที่ใช้ Dashboard 7 วันต่อกัน:
- ใช้ฟีเจอร์ x3 มากขึ้น
- ตั้ง watchlist เฉลี่ย 12 ตัว (vs 3 ตัวสำหรับ bot-only)
- เห็น earnings ล่วงหน้า x2 บ่อยกว่า

→ /dashboard เพื่อเริ่ม streak
```

## X-DD5 — Reply Magnet

```
RT/QT เพื่อโชว์ heatmap พอร์ตของคุณ 🎨

ใช้ Apexify Dashboard:
1. /dashboard ในบอท
2. screenshot Heatmap
3. tag @apexify_th

จะ retweet ทุกตัวที่ติด hashtag #ApexifyHeatmap
```

---

# E. 💬 LINE OA Broadcast (LINE-DD1 — LINE-DD3)

> ลูกค้าไทยเยอะ — LINE OA = direct touch
> Format: **สั้น · มี emoji · ปุ่ม CTA ไป Telegram bot**

## LINE-DD1 — Headline broadcast

```
🌐 Apexify มีเว็บแล้ว!

ลูกค้าของบอท Apexify ทุก tier
เข้าใช้ Dashboard บนเว็บได้แล้ว

📊 ดูพอร์ตเป็น Heatmap
📈 Benchmark vs S&P/SET
💰 Tax Export (PRO)

[ปุ่ม: เปิด Telegram → /dashboard]
```

## LINE-DD2 — Tutorial broadcast

```
📚 วิธีเข้า Apexify Dashboard ใน 30 วิ

1. เปิดบอท Apexify ใน Telegram
2. พิมพ์ /dashboard
3. กดลิงก์ที่ส่งมา → เปิดเว็บ login auto
4. ใช้งานได้ทันที

ทำครั้งเดียว — ใช้ได้ทุกเครื่อง

[ปุ่ม: เปิดบอท]
```

## LINE-DD3 — FAQ resolver broadcast

```
❓ คำถามที่ลูกค้าถามบ่อยเกี่ยวกับ Dashboard

Q: ฟรีมั้ย?
A: ฟรีสำหรับลูกค้าบอท ไม่มีค่าใช้จ่ายเพิ่ม

Q: ต้องสมัครใหม่มั้ย?
A: ไม่ต้อง login ผ่าน Telegram bot ของ Apexify

Q: Free user ก็ใช้ได้?
A: ใช่ — สิทธิ์ตาม tier ของคุณ

Q: เปิดบนมือถือได้?
A: ได้ — install เป็น PWA app ได้ด้วย

[ปุ่ม: ทดลอง /dashboard]
```

---

# F. 💬 DM Direct-to-Dashboard (DM-DD1 — DM-DD5)

> ใช้ใน Telegram DM, FB Messenger, IG DM
> See also: [[26 - DM Quick Replies]]

## DM-DD1 — Reply: "บอทยุ่งยาก"

```
เข้าใจครับ — งั้นลองเว็บแทน

apexifyy.up.railway.app
- เห็นพอร์ตเป็นภาพ Heatmap
- ตั้ง Watchlist + Alert ครั้งเดียว
- ใช้ login เดียวกับบอท

ดูแล้วถ้าไม่ใช้บอทเลยก็ได้ครับ
ทุกอย่างใช้ในเว็บได้
```

## DM-DD2 — Reply: "ฉันใช้ในมือถืออยู่แล้ว"

```
เว็บ Dashboard ก็เปิดในมือถือได้ครับ — ออกแบบ mobile-first

PWA = install เป็น app ได้ (ไม่ต้องโหลดจาก Play/App Store)
เปิดใน Chrome → menu → "Add to Home screen" → เป็น app เลย

อาจสะดวกกว่าตามดูในบอทบางที — ลองดูครับ
apexifyy.up.railway.app
```

## DM-DD3 — Reply: "PRO มันต่างจากบอทยังไง"

```
PRO ในเว็บ Dashboard ปลดล็อก:

✅ Tax Export — Excel ยื่นภาษีได้เลย
✅ Heatmap พอร์ต — เห็นกำไร/ขาดทุนเป็นสี
✅ Matchmaker — AI หาหุ้นที่เข้ากับสไตล์
✅ Benchmark — เทียบกับ S&P, SET
✅ Health Score — ตรวจสุขภาพพอร์ต

ในบอทมีบางส่วน แต่เห็นเป็นภาพ + ครบในเว็บ
ลองเปิดดูก่อน → /dashboard ในบอท
```

## DM-DD4 — Reply: "ลืมรหัส"

```
ไม่ต้องใช้รหัสผ่านครับ 😊

ทุกครั้งที่จะเข้า Dashboard:
1. พิมพ์ /dashboard ในบอท Apexify
2. กดลิงก์ที่บอทส่งมา (มี token หมดอายุ 5 นาที)
3. login auto ทันที

ปลอดภัย + สะดวก — ไม่ต้องจำอะไรเลย
ลองเลยครับ
```

## DM-DD5 — Reply: "ไม่กล้าใส่ข้อมูล"

```
ข้อมูลพอร์ตของคุณปลอดภัยครับ:

✅ ไม่เชื่อมบัญชีโบรกเกอร์ — คุณ input เอง
✅ Privacy Mask — ซ่อนตัวเลขจริงได้ (โชว์เป็น %)
✅ Soft Delete — ลบแล้วกู้คืนได้ใน 7 วัน
✅ Auto Backup — Supabase enterprise-grade

ลองเข้า read-only ก่อนได้ — ดูฟีเจอร์ก่อน input ข้อมูล
apexifyy.up.railway.app
```

---

# G. 📌 Pinned Message Strategy

> บอทมี pinned message ใน private chat ได้ — ใช้ space นี้คุ้มค่า
> Update ทุก 2 อาทิตย์ตาม campaign

## Pin Variant 1 — Universal Hook

```
📌 Apexify — Bot + Web Dashboard

🤖 ในแชทนี้: พิมพ์ /help ดูคำสั่งทั้งหมด
🌐 Web: apexifyy.up.railway.app
   หรือ /dashboard เพื่อ login auto

สิทธิ์ตาม tier เดียว — ใช้ได้ทั้งบอทและเว็บ
Free / VIP (79฿) / PRO (109฿)
```

## Pin Variant 2 — Feature Highlight (rotate ทุก 2 อาทิตย์)

```
📌 ไฮไลต์อาทิตย์นี้:

📊 Web Dashboard Heatmap
ดูพอร์ตเป็นภาพ ใน 5 วิ — รู้สถานะทันที
→ /dashboard

ลูกค้าทุก tier เข้าได้ ไม่มีค่าใช้จ่ายเพิ่ม
```

## Pin Variant 3 — Onboarding Flow

```
📌 เริ่มต้น Apexify ใน 3 ขั้น

1. /me — สมัครและรับ Free trial 7 วัน VIP
2. /track AAPL — ลองวิเคราะห์หุ้น
3. /dashboard — เปิดเว็บ Dashboard

อ่านคู่มือ: /manual
ปัญหา: /support
```

---

# H. 📅 Campaign Calendar — แนะนำลำดับ 12 อาทิตย์

| สัปดาห์ | ช่อง | Template | เหตุผล |
|--------|------|----------|-------|
| 1 | Telegram | DD1 (5 วิ) | broad reveal — ลด barrier |
| 1 | FB | FB-DD7 (ทำไมต้องมี) | educate ทุกกลุ่ม |
| 2 | Telegram | DD8 (Free hook) | catch lurkers |
| 2 | IG | IG-DD2 (Reels) | viral attempt |
| 3 | Telegram | DD4 (5 web-exclusive) | PRO upsell push |
| 3 | LINE | LINE-DD1 | hit Thai market |
| 4 | Telegram | DD7 (PRO routine) | habit formation |
| 4 | FB | FB-DD3 (pain point) | empathy hook |
| 5 | Telegram | DD3 (3 หุ้นพร้อมกัน) | time-saver framing |
| 5 | X | X-DD2 (question) | engagement |
| 6 | Telegram | DD11 (weekly recap ศุกร์) | ritual creation |
| 6 | IG | IG-DD1 (heatmap carousel) | visual hook |
| 7 | Telegram | DD2 (after market close) | timing-based |
| 7 | FB | FB-DD5 (mobile-first) | Gen Z target |
| 8 | Telegram | DD9 (setup once) | Watchlist push |
| 8 | LINE | LINE-DD3 (FAQ) | resolver |
| 9 | Telegram | DD5 (testimonial) | social proof |
| 9 | IG | IG-DD4 (UGC) | community |
| 10 | Telegram | DD6 (loss aversion) | re-engage lapsed |
| 10 | FB | FB-DD2 (before/after) | clear value |
| 11 | Telegram | DD12 (60 วินาที) | micro-commit |
| 11 | X | X-DD3 (comparison) | clarity |
| 12 | Telegram | DD10 (try first) | low-risk close |
| 12 | All channels | repeat best performer | double-down |

---

# I. 💡 Tips สำหรับ admin

## ก่อนกด /broadcast checklist
- [ ] เปลี่ยน apexifyy.up.railway.app เป็น URL ปัจจุบัน (ถ้าย้าย custom domain)
- [ ] ตรวจ Markdown ไม่ leak (`_test_` กลายเป็น italic)
- [ ] ทดสอบกับ ADMIN_ID ก่อนส่ง mass
- [ ] ตรวจ "ปุ่ม" ที่อ้างใน LINE template = button จริงใน LINE OA flex message

## วัดผลแคมเปญ (track ใน admin dashboard)
- `/dashboard` command count ก่อน vs หลัง broadcast
- Heartbeat web (เพิ่มขึ้นมั้ย)
- /admin/heartbeat metrics ดู unique users

## ห้าม
- ❌ ส่ง 2 broadcast ติดกันใน 24 ชม. (ลูกค้ารำคาญ)
- ❌ pitch ก่อน Free user ใช้บอทอย่างน้อย 3 ครั้ง (early = unsubscribe)
- ❌ promise feature ที่ยังไม่ launch
- ❌ ใช้รูป screenshot ที่มีเลขลูกค้าจริง (ขอผ่าน privacy mask ก่อน)

---

ดูต่อ:
- [[21 - Broadcast Templates]] — WD1-WD30 ตัวเดิม + tutorial T1-T15
- [[22 - Sales Templates Mega Pack]] — 60+ templates หลายช่อง
- [[26 - DM Quick Replies]] — สำหรับตอบลูกค้า direct
- [[30 - Sales Chat Quick Replies]] — sales scenarios

#campaign #broadcast #dashboard #marketing
