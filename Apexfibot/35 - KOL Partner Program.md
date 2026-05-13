# 35 - KOL Partner Program

> **สถานะ:** 📝 Design draft — ยังไม่ implement
> **วันที่:** 2026-05-13
> **Trigger ทำเมื่อ:** มีลูกค้าจ่าย > 20 คน หรือ มี KOL ทักมา proactive
> **Effort:** ~1 วัน (web page + admin panel)
> **Origin:** [[34 - User Simulation Insights]] persona P22 "แอดมินเอ๋"

---

## 🎯 ทำไมต้องมี Program นี้

จากการ simulate users — เจอ persona "KOL/Influencer" ที่ใช้ Apexify เป็น **content source** สำหรับทำ TikTok/FB
- ❌ ไม่ใช่ลูกค้าหลัก (convert 23%)
- ✅ แต่เป็น **distribution partner** ที่ทรงพลังที่สุด
- KOL 1 คน reach 5K-50K = ลูกค้าเข้ามาเอง

**ROI:**
- จ่าย KOL 1 คน ฟรี PRO (109/เดือน) = ต้นทุนแทบ 0
- KOL คนเดียวได้ user ใหม่ 5-20 คน/เดือน
- 5 KOL = 25-100 user ใหม่/เดือน

---

## 🏆 Program Structure

### 3 Tiers ตาม followers

| Tier | Followers | Reward |
|------|-----------|--------|
| **Bronze** | 1K-5K | Free 3 เดือน PRO + 20% commission |
| **Silver** | 5K-30K | **Free lifetime PRO** + 30% commission |
| **Gold** | 30K+ | Free lifetime PRO + **50% commission** + custom branding |

**Commission:** จ่ายจากค่าสมัครของ user ที่ใช้ referral link ของ KOL **ตลอด lifetime ของ user** (ไม่ใช่แค่เดือนแรก)

**ตัวอย่าง:**
- Silver KOL แนะนำ 10 user → user จ่ายเดือนละ 109 × 10 = 1,090฿
- KOL ได้ 30% × 1,090 = **327฿/เดือน** (recurring ตลอดเดือนที่ user ยังจ่าย)

---

## ✅ Requirements ที่ KOL ต้องมี

### Bronze (1K-5K)
- ✅ มี account หุ้น/การเงินอย่างน้อย 1 platform (FB, IG, TikTok, X, YT)
- ✅ Content เกี่ยวกับลงทุน/หุ้น/เศรษฐกิจอย่างน้อย 80%
- ✅ Active โพสต์ขั้นต่ำ 2 ครั้ง/สัปดาห์

### Silver (5K-30K)
- ✅ ทุกอย่างของ Bronze
- ✅ Engagement rate > 3% (likes + comments / followers)
- ✅ Audience ส่วนใหญ่เป็น Thai (verify จาก analytics)

### Gold (30K+)
- ✅ ทุกอย่างของ Silver
- ✅ มีอย่างน้อย 1 viral post (>10K views) ในรอบ 3 เดือน
- ✅ ผ่าน interview กับ admin

---

## 🚫 Disqualifiers (ไม่รับ)

- ❌ เคยถูก report scam/pump-and-dump
- ❌ Content เป็น "เซียนหุ้น" สาย hype/garentee
- ❌ Follower fake (เช็คผ่าน HypeAuditor / manual)
- ❌ ขายคอร์สที่ guarantee profit
- ❌ Promote crypto Ponzi / MLM

---

## 🎨 Asset Pack ให้ KOL

KOL ที่ approved จะได้รับ:

### Brand Kit
- 🎨 **Logo** Apexify (full + icon + monochrome)
- 🎨 **Color palette** (Gruvbox warm beige `#BDAE93`)
- 🎨 **Font** Yeseva One + system fonts
- 🎨 **Image templates** (Canva, Figma)

### Content Templates
- 📸 **TikTok script** 30/60 วินาที (5 styles)
- 📸 **FB carousel** template (5 slides)
- 📸 **IG Reel** template (3 styles)
- 📸 **YouTube short** script
- 📸 **Twitter thread** template

### Sample Content (ใช้ได้ทันที)
- 🎬 **30 ตัวอย่าง post** ที่ใช้ Daily Picks
- 🎬 **20 ตัวอย่าง post** Smart Money signal
- 🎬 **10 ตัวอย่าง post** Earnings prep

### Tracking
- 🔗 **Custom referral link** ต่อ KOL
- 📊 **Dashboard** ดู:
  - Clicks
  - Signups
  - Trial activations
  - Paid conversions
  - Commission accrued
  - Commission paid

### Communication
- 💬 **Private LINE/Telegram group** สำหรับ KOL ทุกคน + admin
- 📧 **Monthly newsletter** ส่งฟีเจอร์ใหม่ + content ideas
- 🤝 **1-on-1 onboarding call** สำหรับ Silver+ tier

---

## 📋 Application Flow

### Step 1: KOL Apply (ผ่านหน้า web `/partner`)
ฟอร์ม:
```
ชื่อ-นามสกุล: _______________
ช่องทาง: [FB / IG / TikTok / YT / X / อื่นๆ]
URL: _______________
Followers: _______________
Niche: [หุ้นไทย / หุ้น US / Crypto / ทั่วไป]
ตัวอย่าง 3 post ล่าสุด: _______________
ทำไมอยากร่วม: _______________
Telegram ID (admin จะติดต่อกลับ): _______________
```

### Step 2: Admin Review (1-3 วัน)
- เช็ค followers จริง/ปลอม
- เช็ค content quality
- เช็ค disqualifier list
- ตอบ approved/declined

### Step 3: Onboarding (สำหรับที่ approved)
- ส่ง welcome email + asset pack
- Activate PRO ฟรี
- Generate custom referral link
- เพิ่มเข้า LINE/TG private group
- (Silver+) Schedule 1-on-1 call

### Step 4: Tracking & Payment
- Dashboard อัพเดท real-time
- Commission accrue ทุกเดือน
- จ่ายผ่าน PromptPay/bank transfer ทุกวันที่ 5 ของเดือน
- Min payout 500฿ (carry over ถ้าไม่ถึง)

---

## 📝 Content Rights & Rules

### KOL ทำได้:
- ✅ ใช้ output จาก Apexify (analyze, picks, charts) ทำ content
- ✅ Screenshot บอท + crop ใน video
- ✅ Show ตัวเองใช้บอท on-screen
- ✅ Quote bullet points จาก analyze

### KOL ต้องทำ (attribution):
- ✅ **Tag/Mention** `@Apexify_Trading_Bot` ใน post อย่างน้อย 1 ครั้ง/post
- ✅ ใส่ **referral link** ใน bio/description
- ✅ Disclaimer ว่า "เครื่องมือวิเคราะห์ ไม่ใช่คำแนะนำลงทุน"

### KOL ห้ามทำ:
- ❌ Claim ว่าเป็น "เจ้าของ" หรือ "ทีม Apexify"
- ❌ ขายต่อ/resell การใช้งาน
- ❌ Modify logo Apexify
- ❌ Guarantee profit ใน post
- ❌ ใช้บอท spam ใส่ลิงก์ scam/Ponzi

---

## 💰 Tier Economics (math เผื่อตัดสินใจ)

### สมมติ: เริ่ม 5 KOL ทุก tier

**ต้นทุน/เดือน:**
- 5 × Free PRO = 545฿ (opportunity cost)
- Commission ~30% ของ revenue ที่ generate
- Asset pack: one-time 8 ชม. dev work

**ผลตอบแทน/เดือน (conservative):**
- Bronze (n=2): แต่ละคน 3-5 signup/เดือน, paid 1-2 → revenue 218฿/เดือน (net 174฿ × 2 = 348฿)
- Silver (n=2): แต่ละคน 10-15 signup/เดือน, paid 4-6 → revenue 654฿/เดือน (net 458฿ × 2 = 916฿)
- Gold (n=1): 30-50 signup, paid 12-20 → revenue 1,962฿/เดือน (net 981฿)

**Total: ~2,245฿/เดือน revenue เพิ่ม จาก 5 KOL** (year 1 conservative)

**Year 2 หาก KOL เก่งและขยาย:** scale 3-5x

---

## 🔥 Sample Content KOL ใช้ได้ทันที

### TikTok 30 วิ: "AI ดักหุ้นแทนเรา"
```
[Hook 0-3s] "ติดตาม NVDA, MSTR, COIN พร้อมกัน 24 ชม. — ไหวมั้ย?"
[Problem 3-8s] "เราคนเดียวตามไม่ทันแน่ๆ"
[Solution 8-20s] [show Daily Picks 7:45 + Golden Cross alert]
"Apexify ส่งสัญญาณให้ทุกเช้า 7:45 + เตือนเมื่อมี Golden Cross"
[CTA 20-30s] "Link ใน bio ทดลองฟรี 7 วัน"
```

### FB Carousel: "5 หุ้นที่ Apexify pick วันนี้"
- Slide 1: "หุ้น US ที่ AI คัด วันนี้ 13 พ.ค."
- Slide 2-4: หุ้น 3 ตัวที่ Daily Picker pick + chart
- Slide 5: "Link in bio — Apexify ฟรี 7 วัน"

### YT Short: "ใครซื้อหุ้นนี้ก่อนเรา?"
```
[0-5s] "หุ้น COIN วันนี้วิ่ง +8% — ใครรู้ก่อนเรา?"
[5-15s] "Apexify Smart Money tracker เห็น insider ซื้อ $2M 3 วันก่อน"
[15-25s] [show smart money alert]
[25-30s] "ลอง 7 วันฟรี link bio"
```

---

## 🔧 Technical Implementation (ไว้ทำตอนตั้งใจ)

### Backend
- Table `kol_partners` (id, name, tier, referral_code, telegram_id, status, approved_at)
- Table `kol_clicks` (kol_id, ts, ip_hash, user_agent)
- Table `kol_conversions` (kol_id, user_id, action: signup/trial/paid, ts, revenue)
- Endpoint `GET /api/partner/dashboard` (KOL self-service)
- Endpoint `POST /api/partner/apply` (apply form)

### Frontend
- Page `/partner` — public landing + apply form
- Page `/partner/dashboard` — KOL self-service (auth required)
- Admin page `/admin/partners` — review + approve

### Bot Integration
- Command `/ref [code]` — user enter KOL code → log conversion
- Track conversion via `start_param` ใน Telegram deep link

### Tracking Link Format
```
https://apexify.com/ref/{kol_code}
→ redirects to t.me/Apexify_Trading_Bot?start=ref_{kol_code}
```

---

## 📊 Success Metrics

หลัง launch 3 เดือน วัด:

| Metric | Target |
|--------|--------|
| KOL approved | 5-10 |
| Active KOL (post ≥ 2/week) | 80% |
| Avg conversions per KOL/month | 3-8 |
| KOL-driven revenue / total | 15-25% |
| Cost per acquired customer (CPA) | < 50฿ |

---

## 🚀 Phase Plan

### Phase 1: Soft Launch (เมื่อ trigger ตรง)
- Hand-pick 3 KOL invitation (ไม่เปิด public)
- ทดลอง 1 เดือน — ดู mechanics ทำงานไหม
- Refine

### Phase 2: Public Launch
- เปิดหน้า `/partner` ให้ public apply
- Marketing ผ่าน FB ad → "KOL recruit"
- Target 5-10 KOL approved

### Phase 3: Scale
- เปิด Gold tier interview
- เพิ่ม content templates
- เพิ่ม international (Thai overseas KOL)

---

## ⚠️ Risk & Mitigation

### Risk 1: KOL เอาเครดิตไป claim เป็นของตัวเอง
- **Mitigate:** Content rights clear + attribution required + ตรวจสอบ monthly

### Risk 2: KOL recommend Apexify ตลาดมือใหม่งบน้อย (low LTV)
- **Mitigate:** Brief KOL ให้ target P2 (first jobber) + P5 (intermediate) ใน guideline

### Risk 3: KOL หาย หลังจากได้ free PRO
- **Mitigate:** Bronze tier 3 เดือนก่อน — re-evaluate ค่อย upgrade lifetime
- Silver+ ต้องมี post อย่างน้อย 2/week ไม่งั้น downgrade

### Risk 4: Commission fraud (KOL ใช้ multi-account ตัวเอง claim)
- **Mitigate:** IP/device fingerprint check + admin manual review สำหรับ payment > 1,000฿

---

## 💡 ใช้ไฟล์นี้ยังไง

- **Trigger ทำ:** เมื่อ paying users > 20 หรือ มี KOL ทักมา proactive
- **เริ่มจาก:** Phase 1 soft launch (hand-pick 3 KOL)
- **อย่าทำตอนนี้** ถ้า: lifetime PRO commitment เกิน revenue ที่มี

---

## 🔗 ที่เกี่ยวข้อง

- [[34 - User Simulation Insights]] — origin persona P22
- [[10 - Referral System]] — existing referral (ลูกค้าทั่วไป)
- [[19 - Facebook Post Templates]] — content templates เดิม
- [[31 - Dashboard Drive Campaigns]] — web traffic
