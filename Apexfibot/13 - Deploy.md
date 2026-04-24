---
tags: [deploy, ops]
---

# 🚀 Deployment Guide

## Production Environment

**Platform:** Digital Ocean droplet (ไม่ใช่ Railway แม้ CLAUDE.md เก่าจะระบุ)
**OS:** Linux (Ubuntu)
**Process manager:** systemd
**Service name:** `apexify` (ตัวอย่าง — ตรวจดูจริงบน server)

## Deploy Workflow (มาตรฐาน)

```bash
# 1. SSH เข้า droplet
ssh root@<droplet_ip>

# 2. ไปที่ project folder
cd /path/to/apexify

# 3. Pull code ใหม่
git pull origin main

# 4. (ถ้ามี requirements ใหม่) install
pip install -r requirements.txt

# 5. Restart service
systemctl restart apexify

# 6. ดู logs
journalctl -u apexify -f
```

## Initial Setup (ครั้งแรก)

### 1. Install dependencies
```bash
sudo apt update && sudo apt install -y python3 python3-pip postgresql
pip3 install -r requirements.txt
```

### 2. Setup PostgreSQL
```bash
sudo -u postgres createuser apexify -P
sudo -u postgres createdb apexify_db -O apexify
```

### 3. Create `.env`
```bash
TELEGRAM_TOKEN=...
ADMIN_ID=...
GEMINI_API_KEY=...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=apexify_db
DB_USER=apexify
DB_PASSWORD=...
# Optional:
BOT_WEB_BASE_URL=https://your-domain.com   # → ใช้ webhook mode
```

### 4. systemd service file `/etc/systemd/system/apexify.service`

```ini
[Unit]
Description=Apexify Trading Bot
After=network.target postgresql.service

[Service]
Type=simple
User=apexify
WorkingDirectory=/path/to/apexify
EnvironmentFile=/path/to/apexify/.env
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Enable + start
```bash
systemctl daemon-reload
systemctl enable apexify
systemctl start apexify
systemctl status apexify
```

## Health Check

- Flask listens on port 8080 (or as configured)
- `GET /` should return HTTP 200 within reasonable time
- ใช้สำหรับ monitoring (UptimeRobot, etc.)

## Webhook vs Polling

```python
# main.py
_base = BOT_WEB_BASE_URL.rstrip("/") if BOT_WEB_BASE_URL else ""
if _base and _base.startswith("https://"):
    # → Webhook mode
    bot.set_webhook(url=f"{_base}/webhook/{secret}")
else:
    # → Polling mode (default)
    bot.infinity_polling()
```

**Polling** = simpler, no domain needed — ใช้สำหรับ dev / Digital Ocean droplet ปกติ
**Webhook** = scale ดีกว่า, ต้อง HTTPS — ใช้ถ้ามี Cloudflare/nginx setup

## Common Operations

### ดู logs
```bash
journalctl -u apexify -f --since "1 hour ago"
```

### Restart only (no pull)
```bash
systemctl restart apexify
```

### Stop bot
```bash
systemctl stop apexify
```

### Database backup
```bash
pg_dump apexify_db > backup_$(date +%Y%m%d).sql
```

หรือใช้ admin command `/force_backup` (auto upload ไป cloud — ดู `keep_alive.py`)

### Database migration
- ระบบ auto-migrate ผ่าน `init_db()` + `init_new_features_db()` ตอน startup
- ถ้า ALTER fail → log แต่ไม่ crash (ดู [[06 - Database Schema#Migration Strategy]])

## Troubleshooting

### Bot ไม่ตอบ
1. `systemctl status apexify` — check running
2. `journalctl -u apexify -n 100` — last 100 lines
3. ตรวจ `.env` token ถูกต้องไหม

### Gemini errors มาเยอะ
- 503 = overload (ปกติ — มี retry chain แล้ว)
- 404 = model deprecated → ดู [[07 - AI System#Models Used]]
- 401 = API key หมดอายุ → renew

### Database connection errors
- เช็ค PostgreSQL service: `systemctl status postgresql`
- เช็ค connection string ใน `.env`
- เช็ค firewall: `sudo ufw status`

### High memory usage
- yfinance/matplotlib leak — restart service หาก > 1GB
- consider cron job restart ทุกคืน

ดูต่อ:
- [[02 - Tech Stack]]
- [[14 - Recent Changes]]

#deploy #ops
