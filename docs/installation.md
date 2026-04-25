# คู่มือการติดตั้ง Apexify

## ความต้องการของระบบ

- Python 3.10 ขึ้นไป
- PostgreSQL (แนะนำ Supabase) หรือ SQLite สำหรับทดสอบ
- Telegram Bot Token (จาก @BotFather)
- Google Gemini API Key

## ขั้นตอนการติดตั้ง

### 1. เตรียม Telegram Bot

1. เปิด Telegram ค้นหา `@BotFather`
2. พิมพ์ `/newbot` แล้วตั้งชื่อบอท
3. บันทึก **Bot Token** ที่ได้รับ
4. หา Telegram User ID ของตัวเองด้วย `@userinfobot`

### 2. เตรียม Google Gemini API

1. ไปที่ [Google AI Studio](https://aistudio.google.com)
2. สร้าง API Key ใหม่
3. บันทึก **API Key**

### 3. เตรียมฐานข้อมูล (Supabase)

1. สมัคร [Supabase](https://supabase.com) (ฟรี)
2. สร้าง Project ใหม่
3. ไปที่ Settings → Database → Connection string
4. คัดลอก **Connection string (URI)**

### 4. Clone และติดตั้ง

```bash
# Clone โปรเจกต์
git clone <repo-url>
cd "Apexify bot telegram"

# สร้าง virtual environment
python -m venv .venv

# Activate (Linux/Mac)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# ติดตั้ง dependencies
pip install -r requirements.txt
```

### 5. ตั้งค่า Environment Variables

```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env`:

```env
TELEGRAM_TOKEN=your_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_ID=your_telegram_user_id
DATABASE_URL=postgresql://user:password@host:5432/dbname

# Dashboard URL (Railway) — Telegram bot magic-login จะชี้ user ไปที่นี่
DASHBOARD_BASE_URL=https://apexifyy.up.railway.app

# Bot URL (Digital Ocean / wherever bot runs) — ใช้สำหรับ webhook + admin dashboard
# ใช้ http://IP:PORT ถ้ารัน polling, https://domain ถ้ารัน webhook
BOT_WEB_BASE_URL=http://YOUR.DO.IP:8080
DASHBOARD_LOGIN_SECRET=random_secret_string_here
FLASK_SECRET_KEY=another_random_secret_here

# Slipok (ตรวจสลิป)
SLIPOK_BRANCH_ID=your_branch_id
SLIPOK_API_KEY=your_slipok_api_key
```

### 6. รันบอท

```bash
# รัน Telegram Bot
python main.py

# หรือรันทั้งระบบ (Flask + Bot)
python keep_alive.py &
python main.py
```

## การทดสอบ

หลังรันแล้ว เปิด Telegram หาบอทของคุณ:

```
/start          → ทักทายและดูสถานะ
/manual         → ดูคำสั่งทั้งหมด
AAPL            → ทดสอบวิเคราะห์หุ้น Apple
/portfolio      → ดูพอร์ต (ว่างตอนแรก)
```

## ย้ายข้อมูลจาก SQLite → PostgreSQL

ถ้ามีข้อมูลเดิมใน `apexify.db`:

```bash
python migrate.py
```

สคริปต์จะย้าย users และ watchlists ไปยัง PostgreSQL โดยอัตโนมัติ

## ปัญหาที่พบบ่อย

ดูที่ [troubleshooting.md](troubleshooting.md)
