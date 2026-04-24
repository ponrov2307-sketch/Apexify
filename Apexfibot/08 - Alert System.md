---
tags: [alerts, scheduler, cron]
---

# ⏰ Alert System

## Architecture

`alert_system.py` มี main loop `run_alert_loop(bot_instance)` — รันใน background thread จาก `main.py`

```python
# main.py __main__:
threading.Thread(target=_bg_init, daemon=True).start()
# _bg_init() → init_db() → init_new_features_db() → run_alert_loop(bot)
```

## Loop Pattern

```python
while True:
    try:
        thai_time = datetime.utcnow() + timedelta(hours=7)
        current_date_str = thai_time.strftime("%Y-%m-%d")

        # ... เช็คเวลา/วัน + กันรันซ้ำด้วย last_X_date ...

    except Exception as e:
        print(f"[AlertLoop] Exception: {e}", flush=True)

    time.sleep(300)  # 5 นาที
```

ทุก 5 นาทีเช็คเงื่อนไข — ใช้ `last_X_date` กันรันซ้ำในวันเดียวกัน

---

## 📅 Cron Schedule (Thai Time UTC+7)

| เวลา | Function | กลุ่มผู้รับ |
|-----|---------|----------|
| 00:00 | `auto_downgrade_expired_users()` | (system — role→free ถ้า expired) |
| 00:00 | `reset_daily_free_usage()` | (system — usage_count=0) |
| 00:00 | `send_expiry_warnings()` | VIP/PRO ใกล้หมด 7/3/1 วัน |
| 05:00 | `send_watchlist_daily_summary()` | ทุก user ที่มี watchlist |
| **06:00** ⭐ | `check_plan_outcomes()` | (system — Track Record) |
| 08:00 | `check_earnings_calendar()` | user ที่ subscribe earnings |
| 08:30 | `send_morning_briefing()` | VIP/PRO/admin |
| 21:00 | `send_daily_portfolio_summary()` | VIP/PRO ที่มี portfolio |
| 21:00 | `check_xd_alerts()` | PRO + admin |
| ทุก 3 ชม. | `broadcast_hourly_urgent_news()` (Flash) | PRO + admin |
| ทุก 1 ชม. | `check_and_broadcast_pro_news()` (Digest) | VIP/PRO + admin |
| ทุก 30 นาที | `check_hot_news()` ต่อ symbol | PRO ที่ watch หุ้นนั้น |
| ทุก 5 นาที | `check_market_conditions()` | PRO ที่ watch (RSI/Hammer/MACD/Whale) |
| ทุก 5 นาที | `check_custom_price_alerts()` | PRO ที่ตั้ง price alert |
| **ศุกร์ 18:00** ⭐ | `send_weekly_performance_digest()` | VIP/PRO + admin |

---

## Major Functions

### `broadcast_hourly_urgent_news(bot, force=False)` — Flash News
- ดึง RSS news หลายแหล่ง → AI เลือก 1 ข่าวเด่น
- ส่งให้ PRO + admin
- Cooldown 3 ชม. (`FLASH_NEWS_INTERVAL_SECONDS`)
- 503 → silent skip
- Safety/JSON error → admin alert

### `check_and_broadcast_pro_news(bot, force=False)` — Digest News
- เลือก 2 ข่าวจากคนละสำนัก
- ส่งให้ VIP + PRO + admin
- Cooldown 1 ชม.
- มี dedup ผ่าน `_is_duplicate_news()` + `dispatch_log`

### `send_morning_briefing(bot)` — เช้า 8:30
- Macro snapshot (SPY, QQQ, GC=F, CL=F, DX-Y.NYB)
- Top movers (AAPL, MSFT, NVDA, TSLA, ...)
- AI สรุป — ส่ง VIP/PRO/admin
- มี podcast version (`send_morning_briefing_with_podcast`)

### `send_watchlist_daily_summary(bot)` — เช้า 5:00
- ทุก user ที่มี watchlist (ไม่จำกัด tier)
- เช็ค RSI, % change, signal
- เป็น engagement hook สำหรับ free user ด้วย

### `send_daily_portfolio_summary(bot)` — เย็น 21:00
- VIP/PRO + admin ที่มี portfolio entries
- คำนวณ P&L, % change
- ส่งสรุปยอดรวมพอร์ต

### `check_market_conditions()` — ทุก 5 นาที
- เช็ค active symbols (PRO watchlist) → RSI overbought/oversold
- Hammer pattern, MACD cross, Whale (volume spike)
- ส่งผ่าน `send_alert_to_users()` (filter role='pro' ด้วย check_subscription)

### `check_custom_price_alerts()` — ทุก 5 นาที
- ดึงทุก active alert จาก `user_price_alerts`
- ถ้า role ไม่ใช่ PRO อีกต่อไป → deactivate alert (กันใช้ฟรี)
- ส่งแจ้งเตือนเมื่อราคาถึง

### `check_xd_alerts()` — เย็น 21:00
- เช็คหุ้นไทยที่จะ XD (ขึ้นเครื่องหมาย dividend) ใน 7 วัน
- ส่งให้ PRO + admin

### `check_earnings_calendar(bot)` — เช้า 8:00
- ดู user earnings subscriptions (ตาราง `earnings_alerts`)
- เช็คว่ามี earnings วันนี้/พรุ่งนี้ไหม
- ส่งแจ้งเตือนรวม

### `check_plan_outcomes()` ⭐ — เช้า 6:00
ดูรายละเอียด: [[09 - Track Record System]]

### `send_weekly_performance_digest(bot)` ⭐ — ศุกร์ 18:00
- VIP/PRO + admin
- รวม:
  - Watchlist WoW (Week-over-Week %) — top 10
  - Personal Plan stats สัปดาห์นี้ (PRO only)
  - Global Track Record 30 วัน (hit rate %)
  - AI Economic Preview สัปดาห์หน้า

### `send_expiry_warnings(bot)` — เที่ยงคืน
- แจ้ง 7/3/1 วันก่อนหมดอายุ
- มี inline button ต่ออายุทันที + escalation icon (💡→⚠️→🚨)
- คนละข้อความตาม urgency

---

## Admin Force Commands (สำหรับทดสอบ)

| Command | Trigger function |
|---------|-----------------|
| `/force_news flash` | `broadcast_hourly_urgent_news(force=True)` |
| `/force_news digest` | `check_and_broadcast_pro_news(force=True)` |
| `/force_weekly` ⭐ | `send_weekly_performance_digest()` |
| `/mock_alert <symbol> <type>` | จำลอง alert ทดสอบ |

---

## ⚠️ Pitfalls

### Holiday/After-hours
- yfinance ส่ง empty data ในวันหยุด — ทุก function handle gracefully
- บอทพยายามเช็คตอนกลางคืนอยู่ดี — เป็นเรื่องปกติ ไม่ต้อง alert

### Connection Leaks
- เคยมีปัญหา leak ใน `init_db` (ดู commit `e86da11`)
- ทุก `get_connection()` ต้องมี `conn.close()` ใน finally

### Cascade Migration Failure
- `ALTER TABLE` หลายตัวใน 1 transaction → ถ้าตัวแรก fail ตัวต่อๆไป fail หมด
- แก้ด้วย try/except + rollback แยกแต่ละ ALTER (ดู commit `c3e143c`)

### Gemini Overload (503)
- ทุก news function ต้อง silent skip ถ้าเป็น 503 (กันรบกวน admin)
- ใช้ `_is_gemini_overloaded_error(e)` check
- ดู [[07 - AI System#Error Handling]]

### Loop never sleeps too long
- `time.sleep(300)` หลังแต่ละ iteration (5 นาที)
- ถ้าใส่ logic ใหม่ที่ใช้เวลานาน → ต้อง async/thread แยก

ดูต่อ:
- [[09 - Track Record System]]
- [[07 - AI System]]

#alerts #scheduler
