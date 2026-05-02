---
tags: [referral, growth]
---

# 🤝 Referral System (v2)

## Overview

User ส่งลิงก์ชวนเพื่อน → เพื่อนสมัครผ่านลิงก์ → ทั้งคู่ได้รางวัล

## Rewards Structure

### 🎁 Referrer (คนชวน)

| Action | Reward |
|--------|--------|
| ทุก 1 เพื่อนใหม่ (ถ้า role=free) | -3 จาก usage_count = +3 quota |
| ทุก 3 เพื่อนใหม่ (milestone) | +10 วัน VIP/PRO (auto upgrade ถ้าเป็น free) |
| 6 คน | +20 วัน |
| 9 คน | +30 วัน |
| ... | ทุก 3 เพิ่ม |

### 🎁 Referred user (คนถูกชวน) — v2 ใหม่!

- สมัครผ่านลิงก์ → **VIP 3 วันฟรี** ทันที
- ใช้ INSERT ON CONFLICT — ถ้าเป็น VIP/PRO อยู่แล้ว จะต่อ 3 วัน
- ไม่ทับ PRO (ถ้าเป็น PRO อยู่จะคง role ไว้)

## Flow

### 1. User ขอลิงก์ (กดปุ่ม `🤝 ชวนเพื่อน` ใน Hub menu — callback_data: `menu_referral`)

```python
ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
```

แสดงผ่าน inline message พร้อม:
- Progress bar (🟩 N คน / ⬜ 3-N เหลือ)
- ลิงก์เต็ม (cn copy)
- **ปุ่ม share native ของ Telegram** (`switch_inline_query`)

### 2. เพื่อนกด link → `/start REF_<referrer_id>`

```python
if args[1].startswith('REF_'):
    referrer_id = args[1].replace('REF_', '')
    success, milestone_hit = process_referral(referrer_id, user_id)
```

### 3. `process_referral()` ใน database.py:

```sql
-- 1. ตรวจซ้ำ — ถ้า new user มีอยู่แล้วในระบบ → False (กัน abuse)
SELECT user_id FROM users WHERE user_id = %s;

-- 2. INSERT referral record
INSERT INTO referrals (referrer_id, referred_id) VALUES (...);

-- 3. นับจำนวน referrals ของ referrer
SELECT COUNT(*) FROM referrals WHERE referrer_id = %s;

-- 4. ถ้า milestone (count % 3 == 0):
UPDATE users SET
    role = CASE WHEN role='pro' THEN 'pro' ELSE 'vip' END,
    expiry_date = GREATEST(COALESCE(expiry_date, NOW()), NOW()) + INTERVAL '10 days'
WHERE user_id = %s;

-- 5. ถ้าไม่ใช่ milestone:
UPDATE users SET usage_count = GREATEST(0, usage_count - 3)
WHERE user_id = %s AND role NOT IN ('vip','pro');

-- 6. 🌟 v2: REFERRED user bonus — VIP 3 วัน
INSERT INTO users (user_id, role, expiry_date, registered_date, status)
VALUES (%s, 'vip', NOW() + INTERVAL '3 days', NOW(), 'active')
ON CONFLICT (user_id) DO UPDATE SET
    role = CASE WHEN users.role IN ('vip','pro') THEN users.role ELSE 'vip' END,
    expiry_date = GREATEST(COALESCE(users.expiry_date, NOW()), NOW()) + INTERVAL '3 days';
```

### 4. Notifications ส่งหา referrer

**Milestone hit:**
```
🎉 ยินดีด้วย! Milestone ครบ N คน!
🏆 คุณได้รับ VIP/PRO +10 วัน เรียบร้อยแล้ว!
ชวนต่อทุก 3 คน = VIP/PRO +10 วัน 🚀
```

**Per referral (ไม่ครบ milestone):**
```
🎁 มีเพื่อนสมัครผ่านลิงก์ของคุณแล้ว! (N คน)
อีก X คน รับ VIP/PRO +10 วัน ฟรีครับ 🤝
```

### 5. Notification ส่งหา referred user (ใหม่!)

```
🎁 โบนัสต้อนรับ!
คุณสมัครผ่านลิงก์ชวนเพื่อน
✨ รับ VIP 3 วันฟรี เรียบร้อยแล้ว!

💎 ใช้งานได้เต็มรูปแบบ:
• วิเคราะห์ไม่จำกัด + กราฟเทคนิค
• AI Trend Radar 3 ระยะ
• Morning Briefing + Digest News

ลองพิมพ์ชื่อหุ้นใดๆ เช่น `AAPL` เพื่อเริ่มทดลองเลยครับ!
```

## Anti-abuse

- 1 user สมัครผ่านลิงก์ได้ **1 ครั้งเท่านั้น** — ใช้ `referred_id UNIQUE` constraint
- Self-referral (referrer == referred) → reject
- ถ้า user เคยมีในระบบแล้ว → not eligible (กันสมัครซ้ำลบบัญชีเก่า)

## UX Improvements (v2)

### Telegram native share button
```python
share_text = f"🚀 แนะนำบอทวิเคราะห์หุ้น AI ที่ผมใช้อยู่! สมัครผ่านลิงก์นี้รับ VIP 3 วันฟรีทันที 🎁\n{ref_link}"
share_kb.add(InlineKeyboardButton(
    "📤 แชร์ลิงก์ให้เพื่อน (Telegram)",
    switch_inline_query=share_text,
))
```

`switch_inline_query` เปิดหน้าเลือก chat ของ Telegram → user ส่งข้อความสำเร็จรูปได้ทันที ไม่ต้อง copy-paste

ดูต่อ:
- [[04 - Pricing]]
- [[06 - Database Schema]]

#referral #growth
