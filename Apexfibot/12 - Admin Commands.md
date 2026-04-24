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
| `/grant <user_id> <role> <days>` | ให้สิทธิ์ VIP/PRO manually |

## Promo Code

| Command | Description |
|---------|------------|
| `/createcode <code> <days> <max_uses> <vip\|pro>` | สร้างโค้ดใหม่ |
| `/listcodes` | ดูรายการโค้ดทั้งหมด |
| `/deletecode <code>` | ลบโค้ด |

## Force Broadcasts (สำหรับทดสอบ + manual trigger)

| Command | Description |
|---------|------------|
| `/force_news flash` | บรอดแคสต์ Flash News ทันที (1 ข่าวเด่น) |
| `/force_news digest` | บรอดแคสต์ Digest News ทันที (2 ข่าว) |
| `/force_weekly` ⭐ | บรอดแคสต์ Weekly Digest ทันที (ไม่ต้องรอศุกร์) |
| `/mock_alert <symbol> <type>` | จำลอง alert (สำหรับ debug) |

## Admin Dashboard (Web)

| Command | Description |
|---------|------------|
| `/admin_dashboard` | เปิด admin dashboard URL พร้อม auto-login |

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
