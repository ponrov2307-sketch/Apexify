---
tags: [pricing, payment]
---

# 💰 Pricing & Payment

## ราคา (อัปเดตล่าสุด 2026-04-24)

| Package | รายเดือน | รายปี | ส่วนลดต่อปี |
|---------|---------|------|-----------|
| 💎 VIP | 79฿ | 790฿ | ~17% |
| 👑 PRO | 109฿ | 1,090฿ | ~17% |

> ค่าคงที่อยู่ใน `main.py` constant `FREE_DAILY_QUOTA = 3`

## วิธีชำระเงิน

**บัญชีโอน:**
- กสิกรไทย: `135-1-34469-1` (นาย เกียรติศักดิ์ วุฒิจันทร์)

**Flow:**
1. user เลือกแพ็กเกจ → กด "💎 สมัคร VIP/PRO"
2. ส่ง QR/รายละเอียดบัญชี
3. user โอนเงิน → ส่งสลิปเข้าแชท
4. AI (Gemini Vision) อ่านสลิป → ตรวจยอด → upgrade อัตโนมัติใน 3 วินาที

ดู `analyze_payment_slip` ใน `ai_analyzer.py`

## โปรโมชั่น

### 🆓 Free Trial PRO 7 วัน
- สำหรับ user ใหม่ (ใช้ได้ 1 ครั้ง/บัญชี)
- คำสั่ง: `/freetrial` หรือกดปุ่มในเมนู VIP
- เก็บใน column `users.free_trial_used`

### 🎁 Promo Code (`/redeem`)
- Admin สร้างผ่าน `/gencode <days> <max_uses> <vip|pro>` (ระบบสุ่มชื่อโค้ดให้)
- เก็บในตาราง `promo_codes`
- ระบุ days + max_uses + role_type

### 🤝 Referral Rewards
- ดูรายละเอียด: [[10 - Referral System]]
- Referrer ทุก 3 คน → +10 วัน VIP/PRO
- Referrer ทุก 1 คน (ถ้า free) → +3 quota
- **Referred user (v2 ใหม่!)** → VIP 3 วันฟรีทันที

## หลังหมดอายุ

- **Auto downgrade** ทุกเที่ยงคืน → role กลับเป็น 'free'
- **Renewal reminders** ส่ง 7/3/1 วันก่อนหมด พร้อม inline button ต่ออายุ
- ดู `send_expiry_warnings` ใน `alert_system.py`

#pricing
