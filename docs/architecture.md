# โครงสร้างระบบ Apexify

## ภาพรวม

```
[Telegram Users]
      │
      ▼
[Telegram API]
      │
      ▼
[main.py — Bot Handler]
      │
      ├──► [ai_analyzer.py]     ──► [Google Gemini API]
      ├──► [alert_system.py]    ──► [yfinance / TA]
      ├──► [database.py]        ──► [PostgreSQL / Supabase]
      ├──► [pnl_generator.py]
      └──► [send_podcast.py]    ──► [edge-tts]

[keep_alive.py — Flask Web]
      │
      ├──► [admin_service.py]
      ├──► [dashboard_login.py]
      └──► [/admin dashboard]   ◄── [Admin Browser]
```

## โมดูลหลัก

### main.py — Telegram Bot Core
- จัดการ command handlers ทั้งหมด (`/start`, `/manual`, `/setalert`, ฯลฯ)
- รับ text message และส่งไปวิเคราะห์
- ส่ง broadcast ข่าวและ briefing
- Inline keyboard สำหรับ navigation

### alert_system.py — ระบบแจ้งเตือน
- **Price Alerts** — ตรวจราคาหุ้นทุก N นาที เปรียบเทียบกับ target
- **Smart Alerts (PRO)** — RSI overbought/oversold, Golden/Death Cross
- **Earnings Alerts** — แจ้งก่อนประกาศงบการเงิน
- วิ่งใน background thread แยกจาก bot

### database.py — Database Layer
- ORM ด้วย **Peewee**
- รองรับทั้ง **PostgreSQL** (production) และ **SQLite** (development)
- Models หลัก: `User`, `Watchlist`, `Alert`, `EarningsAlert`
- Auto-create tables ตอน startup

### ai_analyzer.py — AI Analysis
- เรียก **Google Gemini** วิเคราะห์หุ้น
- ดึงข้อมูลราคาจาก yfinance
- คำนวณ Technical Indicators (RSI, MACD, Bollinger Bands)
- สร้างกราฟด้วย mplfinance

### keep_alive.py — Web Service
- **Flask** HTTP server
- Health check endpoint `/`
- Admin Dashboard `/admin`
- Magic-link login `/admin-login-token`
- Telegram Webhook `/webhook/<secret>`

### admin_service.py — Admin Operations
- จัดการ user roles (VIP/PRO)
- ส่ง broadcast messages
- ดู stats และ user info
- Ban/unban users

## การทำงานพร้อมกัน (Concurrency)

```
Main Process
├── Flask Web Thread       (keep_alive.py)
├── Telegram Bot Thread    (main.py — polling/webhook)
└── Alert Loop Thread      (alert_system.py)
```

- ใช้ `threading.Thread` สำหรับ background tasks
- Alert loop รันทุก 60 วินาที
- Morning briefing รันตอน 05:00 น. (APScheduler)

## Database Schema

```sql
users
├── user_id      BIGINT PRIMARY KEY
├── username     TEXT
├── role         TEXT  -- 'free', 'vip', 'pro'
├── status       TEXT  -- 'active', 'banned'
├── registered_date  TIMESTAMP
├── expiry_date  TIMESTAMP  -- null = ไม่มีวันหมดอายุ
└── usage_count  INT   -- นับจำนวนการใช้งาน

watchlists
├── user_id      BIGINT  FK → users
└── symbol       TEXT    -- ชื่อหุ้น เช่น 'AAPL'

alerts (price alerts)
├── id           INT PRIMARY KEY
├── user_id      BIGINT FK → users
├── symbol       TEXT
├── target_price DECIMAL
└── alert_type   TEXT  -- 'above', 'below', 'percent'

earnings_alerts
├── id           INT PRIMARY KEY
├── user_id      BIGINT FK → users
└── symbol       TEXT
```

## ระบบ Role และ Permissions

```
Free  → วิเคราะห์ 3 ครั้ง/วัน, Portfolio พื้นฐาน
VIP   → ไม่จำกัด + Morning Briefing + Podcast + Earnings Alert
PRO   → ทุกฟีเจอร์ VIP + Smart Alerts + /setalert + /earnings
Admin → เข้าถึงทุกฟีเจอร์ + Admin Dashboard
```
