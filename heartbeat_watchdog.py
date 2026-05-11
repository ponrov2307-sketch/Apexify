"""
heartbeat_watchdog.py — Standalone watchdog ที่ DM admin ถ้า bot down

ทำงาน:
  1. bot main process เขียน timestamp ไป /tmp/apexify_heartbeat.txt ทุก 60s
     (ดู _heartbeat_loop ใน main.py)
  2. watchdog script นี้รัน standalone (cron ทุก 5 นาที):
     - อ่าน heartbeat file
     - ถ้า stale > 5 นาที (= bot ตาย/แฮง) → DM admin
     - กัน spam ด้วย cooldown 30 นาที/alert

Setup (DO server):
  crontab -e
  เพิ่ม: */5 * * * * /usr/bin/python3 /root/Apexify/heartbeat_watchdog.py

Verify:
  python3 heartbeat_watchdog.py --dry-run
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import config

HEARTBEAT_FILE = Path("/tmp/apexify_heartbeat.txt")
LAST_ALERT_FILE = Path("/tmp/apexify_watchdog_last_alert.txt")
STALE_THRESHOLD_SEC = 5 * 60       # bot ตาย > 5 นาที → alert
ALERT_COOLDOWN_SEC = 30 * 60       # ห้าม alert ซ้ำใน 30 นาที


def _read_heartbeat() -> float:
    """Return timestamp (epoch sec) ของ last heartbeat. -1 ถ้าไม่มีไฟล์"""
    if not HEARTBEAT_FILE.exists():
        return -1.0
    try:
        return float(HEARTBEAT_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return -1.0


def _last_alert_time() -> float:
    """อ่าน time ของ alert ล่าสุด — กัน spam"""
    if not LAST_ALERT_FILE.exists():
        return 0.0
    try:
        return float(LAST_ALERT_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0.0


def _mark_alert_sent():
    LAST_ALERT_FILE.write_text(str(time.time()), encoding="utf-8")


def _send_admin_alert(message: str, dry_run: bool = False):
    if dry_run:
        print(f"[DRY] would send: {message}", flush=True)
        return
    if not config.TELEGRAM_TOKEN or not config.ADMIN_ID:
        print("⚠️  TELEGRAM_TOKEN or ADMIN_ID missing — cannot alert", flush=True)
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": config.ADMIN_ID,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Alert sent: {message[:60]}", flush=True)
            _mark_alert_sent()
        else:
            print(f"❌ Alert failed: {resp.status_code} {resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"❌ Alert exception: {e}", flush=True)


def check_once(dry_run: bool = False) -> dict:
    """รัน 1 cycle — เช็ค heartbeat + DM admin ถ้า stale

    Returns: dict { status, last_heartbeat_age_sec, alerted, message }
    """
    now = time.time()
    last_hb = _read_heartbeat()
    age = now - last_hb if last_hb > 0 else -1

    if last_hb < 0:
        msg = "🚨 *Apexify bot — no heartbeat file*\nbot อาจไม่ start หรือ heartbeat thread crash"
        status = "no_file"
    elif age > STALE_THRESHOLD_SEC:
        from datetime import timedelta
        last_dt = datetime.fromtimestamp(last_hb, tz=timezone.utc) + timedelta(hours=7)
        msg = (
            f"🚨 *Apexify bot DOWN — heartbeat stale*\n"
            f"━━━━━━━━━━━━━━\n"
            f"⏱ last heartbeat: {last_dt:%Y-%m-%d %H:%M:%S} ICT\n"
            f"💀 ค้าง: {int(age / 60)} นาที (threshold {STALE_THRESHOLD_SEC // 60} นาที)\n\n"
            f"check ด่วน:\n"
            f"  `systemctl status apexify`\n"
            f"  `journalctl -u apexify --since '15 min ago' --no-pager | tail -50`"
        )
        status = "stale"
    else:
        return {"status": "healthy", "last_heartbeat_age_sec": age, "alerted": False, "message": None}

    # cooldown check
    last_alert = _last_alert_time()
    if (now - last_alert) < ALERT_COOLDOWN_SEC and not dry_run:
        return {"status": status, "last_heartbeat_age_sec": age, "alerted": False, "message": "cooldown"}

    _send_admin_alert(msg, dry_run=dry_run)
    return {"status": status, "last_heartbeat_age_sec": age, "alerted": True, "message": msg}


def main():
    dry_run = "--dry-run" in sys.argv
    result = check_once(dry_run=dry_run)
    print(f"watchdog: status={result['status']} age={result.get('last_heartbeat_age_sec', -1):.0f}s alerted={result['alerted']}", flush=True)


if __name__ == "__main__":
    main()
