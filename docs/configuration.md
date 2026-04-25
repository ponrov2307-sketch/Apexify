# การตั้งค่า Environment Variables

ไฟล์ `.env` เป็นศูนย์กลางการตั้งค่าทั้งหมด ห้าม commit ไฟล์นี้ขึ้น git

## ตัวแปรที่จำเป็น (Required)

| ตัวแปร | ตัวอย่าง | คำอธิบาย |
|--------|---------|----------|
| `TELEGRAM_TOKEN` | `1234567890:ABC...` | Token จาก @BotFather |
| `GEMINI_API_KEY` | `AIzaSy...` | Google Gemini API key สำหรับ AI |
| `ADMIN_ID` | `123456789` | Telegram User ID ของ admin (ตัวเลข) |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |

## ตัวแปร Web Dashboard

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
|--------|-----------|----------|
| `DASHBOARD_BASE_URL` | — | URL ของ User Dashboard (Railway) — ใช้สำหรับลิงก์ `/dashboard` magic-login ของ user |
| `BOT_WEB_BASE_URL` | — | URL ของ bot service (Digital Ocean) — ใช้สำหรับ webhook + Admin Dashboard |
| `DASHBOARD_LOGIN_SECRET` | — | Secret สำหรับ sign JWT magic-link token |
| `ADMIN_DASHBOARD_LOGIN_SECRET` | _(ใช้ค่าเดียวกับ LOGIN_SECRET)_ | Secret แยกสำหรับ admin (optional) |
| `DASHBOARD_LOGIN_TOKEN_TTL` | `300` | อายุ token (วินาที) |
| `BOT_DASHBOARD_LOGIN_ENABLED` | `true` | เปิด/ปิดฟีเจอร์ magic-link login |
| `FLASK_SECRET_KEY` | — | Flask session encryption key |

## ตัวแปร Slipok (ตรวจสลิป)

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
|--------|-----------|----------|
| `SLIPOK_BRANCH_ID` | `62954` | Branch ID ของบัญชี Slipok |
| `SLIPOK_API_KEY` | — | API Key จาก slipok.com |
| `SLIPOK_TIMEOUT_SECONDS` | `15` | Timeout การเรียก API (วินาที) |

## ตัวแปรอื่นๆ

| ตัวแปร | คำอธิบาย |
|--------|----------|
| `PROMPTPAY_ID` | เบอร์โทร/เลขบัตรประชาชน สำหรับ QR PromptPay |
| `APEXIFY_PASSWORD` | Password เพิ่มเติม (optional) |

## วิธีสร้าง Secret Keys

```bash
# สร้าง random secret key ด้วย Python
python -c "import secrets; print(secrets.token_hex(32))"
```

## การตั้งค่าบน Railway

1. ไปที่ Railway project → Variables
2. เพิ่มตัวแปรทีละตัว หรือ import จาก `.env` file
3. Railway จะ restart service อัตโนมัติเมื่อบันทึก

## ลำดับความสำคัญของค่า

```
config.py โหลดค่าจาก:
1. Environment variables (Railway/systemd inject)
2. ไฟล์ .env ในโฟลเดอร์โปรเจกต์
3. ค่าเริ่มต้น (default) ถ้ามี
```

## ค่าที่ใช้ Fallback กัน

- `FLASK_SECRET_KEY` → fallback ไปใช้ `ADMIN_DASHBOARD_LOGIN_SECRET` → `DASHBOARD_LOGIN_SECRET`
- `ADMIN_DASHBOARD_LOGIN_SECRET` → fallback ไปใช้ `DASHBOARD_LOGIN_SECRET`
