# Apexify — Project Context for Claude

## โปรเจกต์คืออะไร

**Apexify** เป็น Telegram Bot สำหรับวิเคราะห์หุ้นด้วย AI พัฒนาด้วย Python ใช้ Google Gemini เป็น AI engine

Deploy บน **Railway.app** (production) หรือ **Linux server** ด้วย systemd

## Stack

- **Language**: Python 3.10+
- **Bot Framework**: python-telegram-bot 22.x
- **Web**: Flask (admin dashboard + health check)
- **Database**: PostgreSQL (production) / SQLite (dev) ด้วย Peewee ORM
- **AI**: Google Gemini API
- **Data**: yfinance, TA-Lib
- **Deploy**: Railway.app

## ไฟล์สำคัญ

| ไฟล์ | หน้าที่ |
|------|--------|
| `main.py` | Bot handlers ทั้งหมด — แก้ไขที่นี่สำหรับ features ใหม่ |
| `database.py` | ORM models + DB operations — ระวังการ migrate |
| `alert_system.py` | Background alert loop — ใช้ threading |
| `config.py` | Environment variables — อย่าเพิ่ม secrets ตรงนี้ |
| `keep_alive.py` | Flask web + Admin Dashboard |

## Architecture Notes

- Bot รัน polling โดยค่าเริ่มต้น (ไม่ใช่ webhook)
- Alert loop รันใน **background thread** แยกต่างหาก
- Flask server รันใน **background thread** แยกต่างหาก
- main.py เริ่มทั้ง Flask + Alert loop ก่อน แล้วค่อยรัน bot
- Database init (`init_db`) รันใน background thread เพื่อไม่ block health check

## User Roles

```
free  → 10 การวิเคราะห์/วัน
vip   → ไม่จำกัด + briefing + podcast (79 บาท/เดือน)
pro   → ทุกอย่าง + smart alerts + setalert + earnings (109 บาท/เดือน)
admin → super user ไม่มีข้อจำกัด
```

## Skills ที่แนะนำสำหรับโปรเจกต์นี้

- `/debug` — ใช้เมื่อมี error จาก logs หรือ bot ล่ม
- `/code-review` — ใช้ก่อน merge หรือ deploy
- `/deploy-checklist` — ใช้ก่อน push ขึ้น Railway
- `/incident-response` — ใช้เมื่อ production มีปัญหา

## สิ่งที่ควรระวัง

- **ห้าม commit `.env`** — มี secrets จริง
- Database migrations ต้องทำ `ALTER TABLE` แบบ isolated (ดู commit history)
- Alert system ใช้ yfinance — ตลาดปิดช่วงวันหยุด/กลางคืน เป็นปกติ
- Railway health check คาดหวัง HTTP 200 จาก `/` ภายใน 90 วินาที
