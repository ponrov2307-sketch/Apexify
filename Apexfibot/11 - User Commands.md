---
tags: [commands, user]
---

# 🎮 User Commands

> 💡 **เคล็ดลับ:** พิมพ์ `/` ใน Telegram → bot จะแสดง dropdown คำสั่งทั้งหมด
> พร้อมคำอธิบาย ไม่ต้องจำเอง
> ดูรายละเอียด: [[16 - Command Discoverability]]

## Basic

| Command | Description | Tier |
|---------|------------|:---:|
| `/start` | ลงทะเบียน + welcome | All |
| `/start REF_<id>` | สมัครผ่าน referral link → รับ VIP 3 วันฟรี | All |
| `/manual` หรือ `/help` | คู่มือใช้งาน + ปุ่มลัด | All |
| `/settings` | ตั้งค่าการแจ้งเตือน, timezone, ภาษา | All |
| `/dashboard` | เปิด Web Dashboard (auto-login link) | All |

## Stock Analysis (พิมพ์ชื่อหุ้นได้เลย ไม่ต้องมี /)

| Action | Behavior |
|--------|---------|
| พิมพ์ `AAPL` | วิเคราะห์ Apple — text + กราฟ (VIP/PRO) |
| พิมพ์ `PTT.BK` | หุ้นไทย — เติม `.BK` |
| พิมพ์ `PTT` | Auto fallback → ลอง `PTT.BK` ให้อัตโนมัติ |
| พิมพ์ `0700.HK` | หุ้นฮ่องกง |
| พิมพ์ `7203.T` | หุ้นญี่ปุ่น |

**Quota:**
- Free: 3 ครั้ง/วัน (รีเซ็ตเที่ยงคืน)
- VIP/PRO/Admin: ไม่จำกัด

## Watchlist & Portfolio

| Command/Action | Description | Tier |
|---------------|------------|:---:|
| กด ⭐ ใต้รายงาน | เพิ่มเข้า Watchlist | All (Free=3, VIP=10, PRO=∞) |
| `/portfolio` หรือกดปุ่มเมนู | ดูพอร์ต + P&L | All (free=3, VIP=10, PRO=∞) |
| Web dashboard | เพิ่ม/ลบ portfolio entries ได้สะดวก | All |

## Premium Commands

### Earnings

| Command | Description | Tier |
|---------|------------|:---:|
| `/ealert AAPL` | สมัครแจ้งเตือนวัน Earnings | VIP/PRO |
| `/ealert list` | ดูรายการที่สมัครไว้ | VIP/PRO |
| `/ealert remove AAPL` | ยกเลิก | VIP/PRO |
| `/earnings AAPL` | วิเคราะห์งบการเงิน AI | VIP/PRO |
| `/fund AAPL` | P/E, EPS, Dividend, Market Cap, Beta, 52W | VIP/PRO |
| `/compare AAPL MSFT` | เปรียบเทียบ 2-3 หุ้น + AI verdict | PRO |

### Smart Alerts (PRO)

| Command | Description | Tier |
|---------|------------|:---:|
| `/setalert AAPL 200` | ระบุราคาเป้าหมาย | PRO |
| `/setalert AAPL +5%` | เพิ่ม 5% จากราคาปัจจุบัน | PRO |
| `/setalert AAPL -3%` | ลด 3% จากราคาปัจจุบัน | PRO |
| `/myalerts` | ดูรายการ alert ที่ตั้งไว้ | PRO |

## Track Record & Engagement (ทุก tier ดูได้)

| Command | Description |
|---------|------------|
| `/track` หรือ `/trackrecord` | สถิติ AI Plans 30/90 วัน hit rate TP1/TP2 |

ดู [[09 - Track Record System]]

### 🔥 Daily Streak (automatic)
- ใช้งานทุกวันติดต่อกัน → streak +1
- ขาดวัน = reset เป็น 1
- **ครบ 7 วัน → +1 วัน VIP ฟรี** (auto grant)
- ดูสถานะใน `💎 บัญชี / VIP` หรือ callback `hub_home`
- Celebration popup ที่ 3/7/14/30/50/100 วัน

## Account & Subscription

| Command | Description |
|---------|------------|
| `/freetrial` | ทดลอง PRO 7 วันฟรี (1 ครั้ง/บัญชี) |
| `/redeem [โค้ด]` | เติมโค้ดโปรโมชั่น |
| `/account` หรือ `/me` | ดูสถานะบัญชี + Streak + โควต้า |

## Quick Menu (ปุ่ม keyboard)

ปุ่มล่างของ Telegram:
- 📊 **วิเคราะห์หุ้น** — บอกวิธีพิมพ์ชื่อหุ้น
- 📱 **เปิดเมนูหลัก** — Hub ฟีเจอร์ inline
- 💎 **บัญชี / VIP** — สถานะ + สมัคร
- 📖 **คู่มือ /manual** — เปิด help

## Hub Menu (ปุ่ม inline จาก "📱 เปิดเมนูหลัก")

จัดหมวดใหม่ — ดูง่ายขึ้น:

### 📊 วิเคราะห์ / ข้อมูล
- 📅 สรุปวันนี้
- 🌍 ตลาดโลก
- 📰 ข่าวด่วน
- 📊 Track Record ⭐ใหม่

### 💼 พอร์ต / Watchlist
- 📋 Watchlist
- 💼 พอร์ตลงทุน

### 🚀 เครื่องมือพรีเมียม
- 🚀 สแกนหุ้น (VIP)
- 🔥 หุ้นเด่น (PRO)
- 🔔 ตั้งเตือนราคา (PRO)
- 📈 Earnings Alert ⭐ใหม่

### ⚙️ ตั้งค่า
- ⚙️ ตั้งค่าแจ้งเตือน
- 🌐 Web Dashboard

## Contextual Quick-Action Buttons (หลังวิเคราะห์)

หลังพิมพ์ชื่อหุ้น → ปุ่มต่อเนื่องโผล่ใต้รายงาน:

- ⭐ **Watchlist** — เพิ่มเข้า Watchlist
- 📊 **Fundamentals** (VIP/PRO) — ไม่ต้องพิมพ์ /fund
- 📈 **งบการเงิน** (VIP/PRO) — ไม่ต้องพิมพ์ /earnings
- ⚖️ **เปรียบเทียบหุ้นอื่น** (PRO) — prompt ให้พิมพ์ /compare
- 🔔 **ตั้งเตือนราคา** (PRO)
- 💼 **พอร์ต** | 📱 **เมนูหลัก**

ดู [[16 - Command Discoverability]] สำหรับ design philosophy

## Hidden / Advanced

| Command | Behavior |
|---------|---------|
| `/menu_referral` callback | เปิดหน้าชวนเพื่อน + ปุ่มแชร์ |
| `/menu_freetrial` callback | กระตุ้นใช้ free trial |
| `/menu_code` callback | บอกวิธีใช้ /redeem |

ดูต่อ:
- [[12 - Admin Commands]]
- [[10 - Referral System]]

#commands #user
