---
tags: [tech, stack]
---

# 🛠️ Tech Stack

## Languages & Runtime
- **Python 3.10+**

## Bot Framework
- **pyTelegramBotAPI** (telebot) — synchronous, event-driven
- Polling mode by default (no webhook)

## Web
- **Flask** — admin dashboard + health check + user web
- รันใน background thread แยกจาก bot

## Database
- **PostgreSQL** (production)
- **SQLite** (dev only — migrate.py แปลงให้)
- **Peewee ORM** (legacy parts) + raw SQL ส่วนใหญ่

## AI
- **Google Gemini** ผ่าน google-genai SDK
- Models: `gemini-2.5-flash` (default), `gemini-2.5-flash-lite`, `gemini-2.5-pro` (fallback chain)
- ใช้ `system_instruction` enable implicit prompt caching

## Data Sources
- **yfinance** — ราคาหุ้น, OHLCV history, fundamentals
- **TA-Lib** — technical indicators (RSI, MACD, EMA, BB)
- **mplfinance** — chart rendering
- **edge-tts** — text-to-speech สำหรับ podcast

## RSS / News
- Google News RSS, Yahoo Finance RSS, Investing.com RSS

## Deploy
- **Digital Ocean** droplet (Linux + systemd)
  > ⚠️ **ไม่ใช่ Railway** — CLAUDE.md อาจระบุ Railway แต่ deploy จริงคือ Digital Ocean
- `git pull && systemctl restart apexify` หลังแก้โค้ด

## Threading Model
- **Main thread** — bot polling
- **Thread 1** — Flask server (`keep_alive`)
- **Thread 2** — `_bg_init` → init DB + alert loop

## Important Env Variables (.env)

| Var | Purpose |
|-----|---------|
| `TELEGRAM_TOKEN` | Bot token จาก @BotFather |
| `ADMIN_ID` | Telegram user ID ของ admin |
| `GEMINI_API_KEY` | Google AI Studio key |
| `DB_*` | PostgreSQL connection |
| `BOT_WEB_BASE_URL` | ถ้ามี → ใช้ webhook mode (ไม่ใช่ polling) |

ดูต่อ:
- [[05 - Files Architecture]]
- [[13 - Deploy]]

#tech #stack
