---
tags: [ux, commands, design]
---

# 🎯 Command Discoverability

## ปัญหา

Apexify มี 13+ คำสั่ง — user ใหม่จำไม่หมด, user เก่าลืม → ไม่ใช้ฟีเจอร์ที่จ่ายเงินไปแล้ว

## Solution (3 ทาง — ทำครบแล้ว)

### 1. 📱 Telegram Commands Menu (native)

เมื่อ user พิมพ์ `/` ใน Telegram → dropdown แสดงคำสั่งทั้งหมดพร้อมคำอธิบาย

**Code** ใน `main.py __main__`:

```python
from telebot.types import BotCommand
bot.set_my_commands([
    BotCommand("start", "เริ่มใช้งาน / ลงทะเบียน"),
    BotCommand("manual", "คู่มือคำสั่งทั้งหมด"),
    BotCommand("track", "สถิติ AI Plans — hit rate ย้อนหลัง"),
    BotCommand("fund", "ข้อมูลพื้นฐาน (P/E, EPS, Dividend) — VIP/PRO"),
    BotCommand("compare", "เปรียบเทียบ 2-3 หุ้น — PRO"),
    BotCommand("earnings", "วิเคราะห์งบการเงินด้วย AI — VIP/PRO"),
    BotCommand("ealert", "แจ้งเตือนวัน Earnings — VIP/PRO"),
    BotCommand("setalert", "ตั้งเตือนราคา — PRO"),
    BotCommand("myalerts", "ดู price alerts ที่ตั้งไว้"),
    BotCommand("freetrial", "ทดลอง PRO 7 วันฟรี"),
    BotCommand("redeem", "เติมโค้ดโปรโมชั่น"),
    BotCommand("settings", "ตั้งค่าการแจ้งเตือน"),
    BotCommand("dashboard", "เปิด Web Dashboard"),
])
```

✅ Run ทุกครั้งตอน startup — ถ้าเพิ่ม command ใหม่ **อย่าลืมแก้ list นี้**

### 2. 🎬 Contextual Quick-Action Buttons

หลังวิเคราะห์หุ้นเสร็จ → ปุ่มต่อเนื่องโผล่ใต้รายงาน user ไม่ต้องจำ `/fund` `/compare`:

```python
if role in ('vip', 'pro'):
    markup.add(
        InlineKeyboardButton(f"📊 Fundamentals", callback_data=f"quick_fund_{correct_symbol}"),
        InlineKeyboardButton(f"📈 งบการเงิน", callback_data=f"quick_earnings_{correct_symbol}"),
    )
if role == 'pro':
    markup.add(
        InlineKeyboardButton(f"⚖️ เปรียบเทียบหุ้นอื่น", callback_data=f"quick_compare_{correct_symbol}"),
        ...
    )
```

**Callback handler**: `quick_action_callbacks()` reuse handle functions เดิม:
- `quick_fund_AAPL` → เรียก `handle_fundamentals()` ด้วย fake message
- `quick_earnings_AAPL` → เรียก `handle_earnings()`
- `quick_compare_AAPL` → prompt ให้พิมพ์ `/compare AAPL <หุ้น2>` ต่อ

### 3. 🗺 Hub Menu จัดหมวด

เดิม: 10 ปุ่มเรียงเต็มหน้า ดูไม่ออกว่ากลุ่มไหน
ใหม่: แบ่ง 4 หมวดด้วยการเรียงแถว:

**วิเคราะห์/ข้อมูล**
- 📅 สรุปวันนี้ | 🌍 ตลาดโลก
- 📰 ข่าวด่วน | 📊 Track Record ⭐

**พอร์ต/Watchlist**
- 📋 Watchlist | 💼 พอร์ตลงทุน

**พรีเมียม**
- 🚀 สแกนหุ้น (VIP) | 🔥 หุ้นเด่น (PRO)
- 🔔 ตั้งเตือนราคา (PRO) | 📈 Earnings Alert ⭐

**ตั้งค่า**
- ⚙️ ตั้งค่าแจ้งเตือน | 🌐 Web Dashboard

พร้อม tip ด้านบน:
> 💡 เคล็ดลับ: พิมพ์ `/` ในแชทเพื่อดูคำสั่งทั้งหมด
> หรือพิมพ์ชื่อหุ้นเลย เช่น AAPL PTT.BK

## Design Principles

1. **Discovery 3 ระดับ:**
   - Global (set_my_commands) — คำสั่งทั้งหมด
   - Contextual (quick buttons) — ที่เกี่ยวกับ symbol ปัจจุบัน
   - Category (hub menu) — แบ่งตามหน้าที่

2. **Progressive disclosure:**
   - Free user เห็น text message
   - VIP user เห็นปุ่ม Fundamentals + Earnings
   - PRO user เห็นปุ่ม Compare + Price Alert เพิ่ม
   → feature ที่ tier ต่ำเห็นแต่กดไม่ได้ = upsell signal

3. **Reuse handlers:**
   - Fake message object + type SimpleNamespace
   - ไม่ต้องเขียน logic ซ้ำระหว่าง `/fund` command กับ callback

## ถ้าเพิ่ม command ใหม่ ต้องทำ 4 อย่าง:

1. ✏️ เขียน `@bot.message_handler(commands=['xxx'])`
2. ✏️ เพิ่มใน `bot.set_my_commands([...])` (main.py __main__)
3. ✏️ อัปเดต `/manual` message
4. ✏️ ถ้าเกี่ยวกับ symbol → เพิ่ม quick button + callback handler
5. ✏️ ถ้าเป็น tier pro/vip feature → เพิ่มใน Hub menu

ดูต่อ:
- [[11 - User Commands]]
- [[12 - Admin Commands]]

#ux #design
