---
tags: [moc, index]
---

# 🤖 Apexify — Documentation Hub

> **Apexify** = Telegram bot วิเคราะห์หุ้นด้วย AI สำหรับนักลงทุนไทย
> Tech: Python + Telegram Bot API + Gemini + yfinance + PostgreSQL

---

## 📚 เอกสารทั้งหมด

### 🎯 เริ่มต้น
- [[01 - Project Overview]] — ภาพรวม Apexify คืออะไร
- [[02 - Tech Stack]] — เทคโนโลยี + dependencies
- [[13 - Deploy]] — วิธี deploy บน Digital Ocean

### 💎 Product / Tier
- [[03 - Tier Comparison]] — ตารางเทียบ Free/VIP/PRO
- [[04 - Pricing]] — ราคา + Free Trial + Promo Code
- [[10 - Referral System]] — ระบบชวนเพื่อน v2

### 🏗️ Architecture
- [[05 - Files Architecture]] — ไฟล์สำคัญ + responsibility
- [[06 - Database Schema]] — ตาราง PostgreSQL ทั้งหมด
- [[07 - AI System]] — Gemini integration + prompts
- [[08 - Alert System]] — Background scheduler + cron
- [[09 - Track Record System]] — ระบบติดตาม Plan outcome

### 🎮 Commands
- [[11 - User Commands]] — คำสั่งสำหรับ user ทั่วไป
- [[12 - Admin Commands]] — คำสั่งเฉพาะ admin
- [[16 - Command Discoverability]] ⭐ — วิธีออกแบบให้ user หาคำสั่งเจอ

### 📝 Strategy & History
- [[14 - Recent Changes]] — Changelog ล่าสุด
- [[15 - Roadmap]] ⭐ — **Strategic plan: Now → Next → Soon → Later → Vision**
- [[25 - Performance and Accuracy Roadmap]] 🆕 — Speed audit + AI accuracy improvements + GitHub libs research

### 🗒️ Daily Logs
- [[2026-05-03]] ⭐ — **Webmaster Section + Commodity Spot + Quality Sweep**
- [[2026-05-01]] — **Trade Plan v2 + News Resilience** (Phase 1 + 2 done)
- [[2026-04-25]]
- [[2026-04-24]]

### 🔧 Recent (2026-05-03)
**ApexifyWebmaster cross-user metrics + commodity spot prices — ดู [[14 - Recent Changes]] section บนสุด**
- Admin dashboard: section "Webmaster" ใหม่ — 8 stats + 4 panels (top tickers/holdings/brokers/currency)
- ทั้ง Bot และ ApexifyWebmaster ใช้ Supabase project เดียวกัน → ดึง cross-user data ตรง psycopg2
- Commodities ใช้ futures (=F) แทน ETF — gold→GC=F, oil→CL=F (ราคา spot จริง $4,629/oz, $101.94/bbl)
- Flash News เป็น US-only (drop Thai RSS, เพิ่ม MarketWatch)
- Audio narration ยาวขึ้น (`audio_script_th` 4-6 ประโยค)
- Critical fix: JS TDZ + SQL TEXT cast — admin dashboard sections เปล่ามาทั้งสัปดาห์

### 🔧 Recent (2026-05-02)
**Admin UI redesign + reliability sweep — ดู [[14 - Recent Changes]]**
- Admin dashboard: dark GitHub → Claude cream → terminal Gruvbox (4 metric + Thai)
- Maintenance toggle ส่ง broadcast user (ทั้ง /maintenance และ admin dashboard)
- Alert state persist (กัน duplicate หลัง restart) — fix issue ลูกค้า PP P. report
- Earnings dedup + Telegram retry + Friendly Thai errors + Quiet hours
- Race condition locks + Gemini 30s timeout

### 💼 Sales & Marketing
- [[17 - Sales Playbook]] — Pitch + Objections + Personas + Templates
- [[18 - Feature Cheat Sheet]] — สรุปขายได้ใน 1 หน้า
- [[19 - Facebook Post Templates]] — 15 templates พร้อมโพสต์
- [[20 - Video Scripts]] — 5 scripts + hooks + production tips
- [[21 - Broadcast Templates]] ⭐ — ข้อความสำเร็จรูปสำหรับ /broadcast
- [[22 - Sales Templates Mega Pack]] 🆕 — FB/IG/Line/X/TikTok/Pantip/LinkedIn/SMS/Email — 60+ templates
- [[23 - DM and Closing Scripts]] 🆕 — Greeting → Discovery → Pitch → Demo → Close → Follow-up
- [[24 - Objection Handling Pack]] 🆕 — รับมือคำถามยาก 40+ scripts ทุกหมวด

### 🎯 Customer Service Quick Reference
- [[26 - DM Quick Replies]] ⭐ — Top 10 คำถามใน DM พร้อม copy-paste
- [[27 - Comment Reply Templates]] ⭐ — ตอบคอมเม้น FB/TikTok/IG ตามอารมณ์
- [[28 - User Guide (How to Use)]] ⭐ — คู่มือใช้งานสำหรับลูกค้า (sharable)
- [[29 - Payment Instructions]] ⭐ — วิธีชำระเงิน + FAQ + ปัญหาที่อาจเจอ
- [[30 - Sales Chat Quick Replies]] 🆕 — เทมเพลตขาย 15 scenarios + objection + closing + cheat sheet

---

## 🔥 Quick Reference

| Topic | Path |
|-------|------|
| Project root | `C:\Users\Kiatt\Desktop\code\APEXIFYYY\Apexify bot telegram` |
| Main code | `main.py` |
| Bot token | `.env` (BOT_TOKEN) |
| Admin ID | `.env` (ADMIN_ID) |
| Deploy target (bot) | Digital Ocean (systemd) |
| **Web Dashboard** | apexifyy.up.railway.app (Next.js + FastAPI on Railway) |
| **Web repo** | `C:\Users\Kiatt\Desktop\code\APEXIFYYY\ApexifyWebmaster` |
| **Web GitHub** | github.com/ponrov2307-sketch/ApexifyWebmaster |
| Pricing VIP | 79฿/เดือน, 790฿/ปี |
| Pricing PRO | 109฿/เดือน, 1,090฿/ปี |
| Free quota | 3 ครั้ง/วัน |
| GitHub (bot) | github.com/ponrov2307-sketch/Apexify |

---

#apexify #moc
