---
tags: [track-record, feature, pro]
---

# 📊 Track Record System

## เป้าหมาย

แสดงให้ user เห็นว่า AI Plans ของ Apexify "แม่นแค่ไหน" — ทำให้:
- **Free user** เห็น proof ว่าระบบใช้ได้จริง → convert เป็น VIP/PRO
- **PRO user** มั่นใจว่าจ่ายเงินคุ้ม → renew
- **Admin** ดูได้ว่าระบบเก่งขึ้น/แย่ลง over time

## Components

### 1. ตาราง `analysis_plans`

ดู [[06 - Database Schema#11 analysis_plans]]

**Outcome states:**
- `open` — ยังไม่ตัดสิน (เพิ่ง issued)
- `tp1_hit` — ราคาไปถึง TP1
- `tp2_hit` — ราคาไปถึง TP2 (ดีกว่า)
- `sl_hit` — ราคาหลุด SL (fail)
- `expired` — เกิน 45 วันยังไม่มีอะไรเกิด

### 2. Logging (auto)

ใน `main.py` หลัง `generate_apexify_report(role='pro')`:

```python
if role == 'pro' and plan:
    log_analysis_plan(
        user_id=user_id,
        symbol=tech_data['symbol'],
        bias='bullish' if plan['tp1'] > plan['entry_low'] else 'bearish',
        entry_low=plan['entry_low'],
        entry_high=plan['entry_high'],
        tp1=plan['tp1'],
        tp2=plan['tp2'],
        sl=plan['sl'],
        price_at_issue=tech_data['price'],
    )
```

### 3. Outcome Evaluation (`check_plan_outcomes()`)

รัน **ทุกวัน 6:00 น. ไทย** ใน `alert_system.py`:

```
1. ดึง pending plans (อายุ 1 วัน - 45 วัน, outcome='open')
2. Group by symbol — ลด yfinance API calls
3. สำหรับแต่ละ symbol:
   - ดึงราคาประวัติจากวันที่ออก plan แรกสุด
   - สำหรับแต่ละ plan ใน symbol:
     - หา sl_hit_date (low ≤ sl)
     - หา tp1_hit_date (high ≥ tp1)
     - หา tp2_hit_date (high ≥ tp2)
4. ตัดสิน outcome ตาม "เกิดก่อน":
   - ถ้า SL ก่อน TP1 → 'sl_hit'
   - elif TP2 hit → 'tp2_hit'
   - elif TP1 hit → 'tp1_hit'
   - else → คงไว้ 'open'
5. expire_stale_plans() — mark 'expired' สำหรับ > 45 วัน
```

### Outcome Logic นี้สำคัญ

**ทำไม "ตามเวลา" ไม่ใช่แค่ "ราคาถึง"?**
- ถ้า SL hit ก่อน TP1 = ขาดทุนจริง (แม้ภายหลังราคาขึ้นถึง TP1)
- เช็คตามวัน trading day — ใช้ daily high/low ไม่ใช่ intraday

**Edge case:**
- ถ้าทั้ง SL และ TP1 hit ในวันเดียวกัน → เลือก SL (conservative)
- ถ้าวันแรกเลย hit อะไรเลย — เป็นไปได้น้อยเพราะ entry ปกติย่อกว่าราคาปัจจุบัน

### 4. Stats Query (`get_track_record_stats()`)

```python
def get_track_record_stats(days=30, user_id=None):
    # SELECT outcome, COUNT(*) FROM analysis_plans
    # WHERE issued_at > NOW() - INTERVAL 'days days'
    # GROUP BY outcome
    return {
        "total": ...,
        "closed": tp1+tp2+sl+expired,
        "open": ...,
        "tp1_hit": ...,
        "tp2_hit": ...,
        "sl_hit": ...,
        "expired": ...,
        "wins": tp1+tp2,
        "hit_rate_pct": wins/closed*100,
    }
```

## User Interface

### `/track` หรือ `/stats`

แสดงสถิติให้ทุก user ดู (รวม free):

```
📊 Apexify Track Record

30 วันที่ผ่านมา (127 Plans ปิดแล้ว, 38 ยังเปิด)
  ✅ Hit Rate (TP1/TP2): 68.5%
  🎯 TP2 hit: 24 | TP1 hit: 63
  🛑 SL hit: 28 | ⏱ Expired: 12

90 วันที่ผ่านมา (...)

💡 วิธีนับ:
• TP1/TP2 hit = ราคาไปถึงเป้าหมาย (กำไร)
• SL hit = ราคาหลุดจุดตัดขาดทุน
• Expired = เกิน 45 วันไม่มีอะไรเกิด
• ไม่ใช่ผลการลงทุนจริง — คำนวณจาก high/low รายวัน

⚠️ ผลย้อนหลังไม่ใช่การรับประกันผลในอนาคต
```

### Personal stats (ใน Weekly Digest)

PRO user เห็นเฉพาะ Plan ของตัวเอง:
```
📊 Plan ของคุณสัปดาห์นี้: 3 hit / 1 SL / 2 เปิดอยู่
```

## Caveats

- **ขั้นต่ำ 1 วัน** ก่อนเริ่มประเมิน — ราคาอาจยังไม่ขยับพอ
- **45 วัน max** — Plans เก่ากว่านี้ mark expired (ไม่ทำให้สถิติเสีย)
- **ไม่ใช่ backtest จริง** — เพราะไม่ได้ simulate การถือ/ปิดเทรดจริง แค่ดูว่าราคาแตะเป้าไหม
- **ไม่นับ slippage / commission**
- **Holiday days** — ถ้าหุ้นไทยตลาดปิดวันนึง outcome อาจคลาดเคลื่อน 1-2 วัน

## Future improvements (ยังไม่ทำ)

- [ ] Per-symbol leaderboard ("AAPL ของ Apexify hit 75%")
- [ ] Per-bias breakdown (bullish hit% vs bearish hit%)
- [ ] Public landing page โชว์ stats live
- [ ] Email weekly summary

ดูต่อ:
- [[06 - Database Schema]]
- [[08 - Alert System]]
- [[15 - Roadmap]]

#track-record #pro #feature
