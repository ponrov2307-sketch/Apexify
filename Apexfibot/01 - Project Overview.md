---
tags: [overview]
---

# 📖 Project Overview

## Apexify คืออะไร

**Apexify** เป็น Telegram bot ที่ใช้ AI (Google Gemini) วิเคราะห์หุ้นแบบเทคนิคให้นักลงทุนไทย รองรับหุ้นทั่วโลก (US, ไทย, ฮ่องกง, ญี่ปุ่น, ออสเตรเลีย, ฯลฯ)

## เป้าหมายหลัก

1. **ลดเวลาวิเคราะห์** — แทนที่จะอ่านกราฟ + indicators เอง user แค่พิมพ์ชื่อหุ้นก็ได้รายงานครบ
2. **ให้ระดับมือใหม่ + มืออาชีพ** — Free user ดูภาพรวมได้, PRO ได้ Plan เทรดสำเร็จรูป (Entry/TP/SL)
3. **ติดตามอัตโนมัติ** — Alert เมื่อราคา/RSI ถึงเกณฑ์, ข่าวด่วน, สรุปประจำวัน

## หลักการสำคัญ

### บอทนี้สำหรับ "ซื้อหุ้น" ไม่ใช่ trading/shorting
- bearish bias = รอจังหวะ**ซื้อ**ที่แนวรับลึก (ไม่ใช่ short)
- TP สูงกว่า Entry เสมอ
- SL ใต้ Entry เสมอ

### ไม่ใช่คำแนะนำการลงทุน
- ทุกรายงานมี disclaimer ชัด
- Track Record (`/track`) แสดงสถิติ hit rate แต่ไม่ใช่การรับประกัน

## ใครคือ user

- **Free** — มือใหม่ ลองใช้ ตัดสินใจสมัครต่อ (3 ครั้ง/วัน)
- **VIP (79฿)** — นักลงทุนทั่วไปที่อยากเห็นภาพรวม + AI Trend Radar
- **PRO (109฿)** — นักลงทุนจริงจัง อยาก Plan เทรดเป็นตัวเลข + alerts
- **Admin** — เจ้าของบอท (ได้ทุกฟีเจอร์ของ PRO + admin dashboard)

## Touchpoints

- **Telegram bot** — main interface
- **Web Dashboard** — Flask app (`keep_alive.py`) สำหรับ admin + user portfolio
- **Background scheduler** — alert/digest/briefing/cron tasks

ดูต่อ:
- [[02 - Tech Stack]]
- [[03 - Tier Comparison]]
- [[05 - Files Architecture]]

#overview
