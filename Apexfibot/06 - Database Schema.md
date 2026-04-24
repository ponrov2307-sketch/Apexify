---
tags: [database, schema]
---

# 🗃️ Database Schema (PostgreSQL)

## Overview

ใช้ PostgreSQL ใน production, SQLite ใน dev. โครงสร้าง init แบ่ง 2 ฟังก์ชัน:
- **`init_db()`** — ตารางหลักที่ระบบทำงานไม่ได้ถ้าไม่มี
- **`init_new_features_db()`** — ตารางที่เพิ่มเข้ามาภายหลัง (alerts, portfolios, etc.)

ทั้ง 2 รันใน background thread เพื่อไม่ block Flask startup

## Tables

### 1. `users` — User profile

```sql
CREATE TABLE users (
    user_id           TEXT PRIMARY KEY,        -- Telegram user ID
    status            TEXT,                    -- 'active' / 'inactive'
    registered_date   TEXT,                    -- ISO datetime ตอนสมัคร
    role              TEXT,                    -- 'free' / 'vip' / 'pro' (admin = ID match)
    expiry_date       TEXT,                    -- VIP/PRO หมดอายุเมื่อไหร่
    usage_count       INTEGER DEFAULT 0,       -- count วิเคราะห์ free/วัน (รีเซ็ตเที่ยงคืน)
    username          TEXT DEFAULT 'Unknown',
    free_trial_used   BOOLEAN DEFAULT FALSE,   -- ใช้ /freetrial แล้วหรือยัง
    free_trial_vip_given BOOLEAN DEFAULT FALSE,
    last_active       TIMESTAMP                -- update ทุกครั้งที่ส่ง message
);
```

**Key operations:**
- `check_subscription(user_id)` → return 'pro'/'vip'/'free' (admin → 'pro')
- `register_user(user_id, username)` — INSERT ON CONFLICT UPDATE
- `auto_downgrade_expired_users()` — รันเที่ยงคืน → role='free' ถ้า expired
- `reset_daily_free_usage()` — usage_count = 0 ทุกเที่ยงคืน

---

### 2. `promo_codes` — Promotional codes

```sql
CREATE TABLE promo_codes (
    code          TEXT PRIMARY KEY,
    days          INTEGER,
    max_uses      INTEGER DEFAULT 1,
    current_uses  INTEGER DEFAULT 0,
    used_by       TEXT DEFAULT '',         -- comma-separated user_ids
    role_type     TEXT DEFAULT 'vip'       -- 'vip' or 'pro'
);
```

Use: `add_promo_code(code, days, max_uses, role_type)` + `redeem_code(code, user_id)`

---

### 3. `used_slips` — กันสลิปซ้ำ

```sql
CREATE TABLE used_slips (
    ref_no     TEXT PRIMARY KEY,    -- เลขที่อ้างอิงในสลิป
    user_id    TEXT,
    date_used  TEXT
);
```

---

### 4. `alert_logs` — ประวัติการแจ้งเตือน (วัดความแม่นยำ)

```sql
CREATE TABLE alert_logs (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT,
    symbol          TEXT,
    alert_type      TEXT,
    alert_subtype   TEXT,
    metadata        JSONB,
    triggered_at    TIMESTAMP,
    -- + columns สำหรับ accuracy tracking
);
```

---

### 5. `dispatch_log` — Dedup สำหรับ Flash/Digest/Podcast

```sql
CREATE TABLE dispatch_log (
    dispatch_key  TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    raw_key       TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Use: `_claim_dispatch_once(category, raw_key)` — return False ถ้าเคยส่งแล้ว

---

### 6. `user_price_alerts` — Custom price alerts (PRO)

```sql
CREATE TABLE user_price_alerts (
    id            SERIAL PRIMARY KEY,
    user_id       TEXT,
    symbol        TEXT,
    target_price  REAL,
    condition     TEXT,           -- 'above' or 'below'
    is_active     INTEGER DEFAULT 1
);
```

---

### 7. `referrals` — Referral tracking

```sql
CREATE TABLE referrals (
    id           SERIAL PRIMARY KEY,
    referrer_id  TEXT,
    referred_id  TEXT UNIQUE,     -- 1 user สมัครได้แค่ผ่านลิงก์เดียว
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 8. `user_settings` — Per-user preferences

```sql
CREATE TABLE user_settings (
    user_id                 TEXT PRIMARY KEY,
    notifications_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    timezone                TEXT NOT NULL DEFAULT 'Asia/Bangkok',
    language                TEXT NOT NULL DEFAULT 'th',
    digest_frequency_hours  INTEGER NOT NULL DEFAULT 4,
    news_start_hour         INTEGER NOT NULL DEFAULT 7,
    news_end_hour           INTEGER NOT NULL DEFAULT 22,
    last_digest_sent_at     TIMESTAMPTZ
);
```

---

### 9. `portfolios` — User portfolio holdings

```sql
CREATE TABLE portfolios (
    id           SERIAL PRIMARY KEY,
    user_id      TEXT,
    ticker       TEXT NOT NULL,
    shares       NUMERIC NOT NULL,
    avg_cost     NUMERIC NOT NULL,
    asset_group  TEXT DEFAULT 'ALL',
    alert_price  NUMERIC DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, ticker)
);
```

Limits: free 3, VIP 10, PRO ∞

---

### 10. `earnings_alerts` — Subscribe earnings ของหุ้นไหน

```sql
CREATE TABLE earnings_alerts (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, symbol)
);
```

---

### 11. `analysis_plans` — Track Record (PRO Plan logging) ⭐ ใหม่

```sql
CREATE TABLE analysis_plans (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT,
    symbol          TEXT NOT NULL,
    bias            TEXT NOT NULL,       -- 'bullish' / 'bearish'
    entry_low       NUMERIC,
    entry_high      NUMERIC,
    tp1             NUMERIC,
    tp2             NUMERIC,
    sl              NUMERIC,
    price_at_issue  NUMERIC,
    issued_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    outcome         TEXT DEFAULT 'open', -- open/tp1_hit/tp2_hit/sl_hit/expired
    outcome_at      TIMESTAMP,
    outcome_note    TEXT
);
CREATE INDEX idx_plans_outcome_issued ON analysis_plans(outcome, issued_at);
CREATE INDEX idx_plans_symbol ON analysis_plans(symbol);
```

ดู [[09 - Track Record System]] สำหรับ logic การตรวจ outcome

---

### 12. `watchlists` + `user_watchlist` — Watchlist (legacy + new)

มี 2 ตาราง:
- `watchlists` — legacy
- `user_watchlist` — new structure
- `_merge_legacy_watchlists(c)` — รวม legacy → new ทุก init

```sql
CREATE TABLE user_watchlist (
    user_id   TEXT,
    symbol    TEXT,
    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, symbol)
);
```

Limits: free 3, VIP 10, PRO ∞

---

## Migration Strategy

### `ALTER TABLE` แบบปลอดภัย

```python
for col_ddl in [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS free_trial_used BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP",
]:
    try:
        c.execute(col_ddl)
        conn.commit()
    except Exception:
        conn.rollback()  # ❗ rollback ทุก ALTER ที่ fail แยก ๆ
```

> ⚠️ **เคยมีปัญหา cascade timeout** — ถ้า ALTER ตัวแรก fail แล้ว transaction เน่า ตัวที่เหลือจะ fail หมด ต้อง rollback แยกแต่ละ ALTER (ดู commit `c3e143c`)

---

## Connection Pattern

```python
conn = get_connection()
cur = conn.cursor()
try:
    cur.execute(...)
    conn.commit()
except Exception as e:
    conn.rollback()
finally:
    conn.close()  # ❗ ห้ามลืม
```

**Connection leak เคยเกิด** ใน `init_db` — แก้ด้วย commit `e86da11`

ดูต่อ:
- [[05 - Files Architecture]]
- [[09 - Track Record System]]

#database #schema
