---
tags: [commands, admin]
---

# 👑 Admin Commands

> ทุกคำสั่งเช็ค `if str(message.chat.id) != ADMIN_ID: return`
> Admin ID set ใน `.env` (ADMIN_ID)
> Admin auto = role 'pro' จาก `check_subscription()` (ดู [[06 - Database Schema]])

## System Control

| Command | Description |
|---------|------------|
| `/maintenance` | toggle maintenance mode (บอทไม่รับ command อื่น) |
| `/system_health` | ดูสถานะ server (memory, threads, DB) |
| `/force_backup` | สั่ง backup database ทันที |

## User Management

| Command | Description |
|---------|------------|
| `/users_pro` | รายชื่อ PRO/VIP users + วันหมดอายุ |
| `/user_history <user_id>` | ดูประวัติ activity ของ user |
| `/addrole <user_id> <vip\|pro> <days>` | ให้สิทธิ์ VIP/PRO manually (เช่น `/addrole 1234 vip 30`) |

## Promo Code

| Command | Description |
|---------|------------|
| `/gencode <days> <max_uses> <vip\|pro>` | สร้างโค้ดอัตโนมัติ (ระบบสุ่มชื่อโค้ดให้ เช่น `VIP7-A1B2C3`) |

> 💡 ดู codes ทั้งหมดได้ผ่าน Admin Web Dashboard (ไม่มี /listcodes)

## Force Broadcasts (สำหรับทดสอบ + manual trigger)

| Command | Description |
|---------|------------|
| `/force_news flash` | บรอดแคสต์ Flash News ทันที (1 ข่าวเด่น) |
| `/force_news digest` | บรอดแคสต์ Digest News ทันที (2 ข่าว) |
| `/force_weekly` ⭐ | บรอดแคสต์ Weekly Digest ทันที (ไม่ต้องรอศุกร์) |
| `/mock_alert <symbol> <type>` | จำลอง alert (สำหรับ debug) |

## Admin Dashboard (Web)

เข้าได้ผ่าน:
- callback `admin_web_dashboard` ในเมนู Admin Master Control
- หรือกดปุ่ม "🌐 เปิด Admin Dashboard" ในเมนู

Dashboard URLs:
- `/admin/login` — login page
- `/admin/users` — user list + manage
- `/admin/stats` — usage statistics
- `/admin/codes` — promo codes management

## Admin Master Control (ปุ่ม inline)

ส่งคำว่า "👑 แผงควบคุมแอดมิน" ในแชท → เปิด menu:
- 🛠 เปิด/ปิด Maintenance
- 💻 สถานะเซิร์ฟเวอร์
- 📊 สถิติผู้ใช้งาน
- 🎯 ผลงานความแม่นยำ (alert accuracy)
- 👑 รายชื่อ PRO/VIP
- 📦 Backup ฐานข้อมูล
- 🌐 เปิด Admin Dashboard
- 📖 คู่มือจัดการสมาชิก & โค้ด
- 📣 คู่มือบรอดแคสต์ & ข่าว

## Hidden — handlers ที่ไม่มี explicit command

| Trigger | Behavior |
|---------|---------|
| ส่งสลิปธนาคาร (รูปภาพ) | AI อ่านสลิป → upgrade user อัตโนมัติ |
| `dispatch_log` cleanup | auto every 24h |

ดูต่อ:
- [[11 - User Commands]]
- [[13 - Deploy]]

#commands #admin
