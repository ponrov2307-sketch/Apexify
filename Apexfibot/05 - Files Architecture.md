---
tags: [architecture, code]
---

# 📁 Files Architecture

## Core Files (อย่าลืมว่าแก้ที่ไหน)

| ไฟล์ | บทบาท | ขนาด |
|------|------|------|
| `main.py` | Bot handlers ทั้งหมด — ทุก command + callback อยู่ที่นี่ | ~6500 lines |
| `database.py` | ORM models + DB operations + migrations | ~1700 lines |
| `alert_system.py` | Background alert loop + scheduler + AI broadcasts | ~1900 lines |
| `ai_analyzer.py` | AI report generation (PRO/VIP/Free) + slip analysis + TL;DR builders | ~1700 lines |
| `technical_tools.py` | yfinance + TA-Lib indicators + chart rendering | ~500 lines |
| `bot_utils.py` | Shared helpers (retry/error/maintenance/company name cache) | ~200 lines |
| `keep_alive.py` | Flask web server + admin dashboard + user web | ~600 lines |
| `config.py` | Env variable loading + thai_now helpers | ~140 lines |
| `send_podcast.py` | Standalone podcast generator (TTS) | ~200 lines |
| `admin_service.py` | Admin dashboard data layer | ~400 lines |
| `migrate.py` | SQLite → PostgreSQL migration helper | ~100 lines |

## Cron / Daemon Files (background threads)

| ไฟล์ | บทบาท | Trigger time | Audience |
|------|------|--------------|----------|
| `daily_stock_picker.py` | DM admin 3 picks + chart + FB hook | 7:30 ICT | Admin |
| `daily_pnl_cron.py` | DM watchlist + P&L recap | 8:00 ICT | VIP+PRO |
| `earnings_prep_cron.py` | DM tomorrow's earnings list | 16:00 ICT | Admin |
| `smart_money_cron.py` | OpenInsider cluster buys | 16:00 ICT | Admin + PRO watchlist |
| `plan_proximity_cron.py` | Warn SL/TP/Entry near (portfolio only) | poll 5 min | PRO |
| `premarket_cron.py` | **NEW 2026-05-13** Gap movers pre-market | 20:30 ICT | VIP+PRO |
| `auto_dm_cron.py` | Activation + win-back DMs | 11:00 ICT | All |
| `breaking_news.py` | 3-layer anti-spam news alerts | poll 5 min | PRO subscribers |
| `intraday_volume.py` | Whale/breakout/gap/acceleration alerts | poll 5 min | PRO |
| `heartbeat_watchdog.py` | Watchdog ping admin if bot dead | cron 5 min | Admin |

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
