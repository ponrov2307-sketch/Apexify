---
tags: [architecture, code]
---

# 📁 Files Architecture

## Core Files (อย่าลืมว่าแก้ที่ไหน)

| ไฟล์ | บทบาท | ขนาด |
|------|------|------|
| `main.py` | Bot handlers ทั้งหมด — ทุก command + callback อยู่ที่นี่ | ~2200 lines |
| `database.py` | ORM models + DB operations + migrations | ~1700 lines |
| `alert_system.py` | Background alert loop + scheduler + AI broadcasts | ~1900 lines |
| `ai_analyzer.py` | AI report generation (PRO/VIP/Free) + slip analysis | ~1000 lines |
| `technical_tools.py` | yfinance + TA-Lib indicators + chart rendering | ~500 lines |
| `keep_alive.py` | Flask web server + admin dashboard + user web | ~600 lines |
| `config.py` | Env variable loading | ~80 lines |
| `send_podcast.py` | Standalone podcast generator (TTS) | ~200 lines |
| `admin_service.py` | Admin dashboard data layer | ~400 lines |
| `migrate.py` | SQLite → PostgreSQL migration helper | ~100 lines |

## Templates / Static
- `templates/` — Jinja2 templates สำหรับ Flask
  - `admin_dashboard.html` — admin panel
  - `user_dashboard.html` — user portfolio web
- `apexify-guide.html` — public guide page

## Folders
- `docs/` — markdown docs (architecture.md ฯลฯ)
- `output/` — preview HTML files (admin dashboard mockup)
- `Apexfibot/` — **Obsidian vault นี้เอง**
- `.claude/` — Claude Code settings (gitignored บางส่วน)

## Threading Model

```
main.py __main__:
├── keep_alive() → Flask thread (port 8080)
├── _bg_init() thread:
│   ├── init_db()
│   ├── init_new_features_db()
│   └── run_alert_loop(bot)
└── bot.infinity_polling() (main thread, blocking)
```

## Init Order

1. **Flask** ขึ้นก่อน (1-2 วินาที) — เพื่อให้ health check ผ่าน
2. **DB init** ใน background — ไม่ block
3. **Alert loop** เริ่มหลัง DB
4. **Bot polling** — block main thread

> ⚠️ Railway health check timeout 90 วินาที — ถ้า DB init ช้าจะ fail
> ปัจจุบัน deploy บน Digital Ocean — ไม่มี timeout นี้

## ⚠️ ระวัง

- **ห้าม commit `.env`** — มี secrets จริง
- **Database migrations** ต้องทำ `ALTER TABLE` แบบ isolated (try/except + rollback)
- **Alert system** ใช้ yfinance — ตลาดปิดช่วงกลางคืน/วันหยุด เป็นปกติ

ดูต่อ:
- [[06 - Database Schema]]
- [[08 - Alert System]]

#architecture
