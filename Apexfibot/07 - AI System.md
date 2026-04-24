---
tags: [ai, gemini, prompts]
---

# 🧠 AI System

## Models Used

### Fallback Chain (ตามลำดับ)
```python
['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro']
```

> ⚠️ **`gemini-2.0-flash` ถูก deprecated** ใน 2026 — ห้ามใส่กลับเข้า chain (ดู commit `1f7daa4`)

### Model selection logic
- **Default**: `gemini-2.5-flash` (เร็ว + ถูก + คุณภาพดี)
- **Fallback 1** (เมื่อ flash overload หรือ deprecated): `gemini-2.5-flash-lite` (เร็วมาก ถูกสุด)
- **Fallback 2** (last resort): `gemini-2.5-pro` (แพง แต่คุณภาพสูงสุด)

## Retry Logic

อยู่ใน `alert_system.py:_gemini_generate_with_retry`:

```python
def _gemini_generate_with_retry(prompt, model='gemini-2.5-flash', retries=4, delay=20):
    fallback_chain = [model, 'gemini-2.5-flash-lite', 'gemini-2.5-pro']
    for attempt in range(retries + 1):
        current_model = fallback_chain[min(attempt, len(fallback_chain) - 1)]
        try:
            return client.models.generate_content(model=current_model, contents=prompt)
        except Exception as e:
            if _is_gemini_model_unavailable_error(e):  # 404
                continue  # ข้ามไปโมเดลถัดไปทันที (ไม่ต้อง wait)
            if _is_gemini_overloaded_error(e):         # 503
                wait = delay * (2 ** attempt)  # 20, 40, 80, 160, 320
                time.sleep(wait)
                continue
            raise  # error อื่นๆ ไม่ retry
```

**Total max wait** = 20+40+80+160+320 = **620 วินาที** (~10 นาที) ก่อนยอมแพ้

## Error Handling

### `_is_gemini_overloaded_error(err)` — 503
- '503' / 'UNAVAILABLE' / 'high demand' / 'overloaded'
- → Retry กับ exponential backoff

### `_is_gemini_model_unavailable_error(err)` — 404
- '404' / 'NOTFOUND' / 'no longer available' / 'not found'
- → ข้ามไปโมเดลถัดไป**ทันที** (ไม่ต้อง wait)

### Silent vs Loud
- **503 ใน Flash/Digest News** → silent skip (admin ไม่ได้รับ alert) — รอบหน้ารันใหม่
- **404 / Safety / JSON parse error** → ส่ง alert ให้ admin
- **Other errors** → ส่ง alert ให้ admin

## Prompt Architecture

### System Instruction (cached implicitly by Gemini 2.5)

อยู่ใน `ai_analyzer.py:_MEMBER_SYSTEM_INSTRUCTION`:

```
คุณคือนักวิเคราะห์เทคนิคหุ้นของ Apexify — ตอบเป็น JSON object เท่านั้น...

กฎเหล็ก:
- ห้ามชี้นำซื้อขายเด็ดขาด
- ภาษาไทยสะกดถูกต้อง ห้ามใช้คำแปลก
- โทนเป็นกลาง-ระวัง bearish→รอซื้อที่แนวรับลึก
- extreme volatility→เตือนใน ai_insight
- ทุกฟิลด์ "สั้น" = ห้ามเกิน 80 ตัวอักษร

Output schema (JSON):
{
  "trend_radar": {...},
  "day_plan": {...},
  "position_plan": {...},
  "watch_next": "...",
  "confirmation_signal": "...",
  "invalidation": "...",
  "ai_insight": "..."
}
```

### Per-call Contents (dynamic data)

```
tier=PRO | NVDA @ 208.63 | bias: D=bullish W=bullish M=neutral | extreme_vol=false

D: P=208.63 RSI=86.80 MACD=6.54/4.58 EMA=192.7/180.5 POC=184.73 S=164.27 R=209.74 Vol=1.2 Cons=4.5
W: P=208.63 RSI=72.1 ...
M: P=208.63 RSI=65.3 ...
```

### Config

```python
config = GenerateContentConfig(
    system_instruction=_MEMBER_SYSTEM_INSTRUCTION,
    temperature=0.3,                       # consistency > creativity
    response_mime_type="application/json", # บังคับ JSON output
)
```

## Free Report (no AI call)

`_generate_free_report()` ไม่เรียก Gemini เลย — สร้างจาก template + tech_data ตรงๆ
- **Why**: ลด API cost + เร็วขึ้น
- มี upsell CTA ในรายงาน

## VIP/PRO Report Flow

```
generate_apexify_report(tech_data, role)
├── normalize role
├── build_multitimeframe_trade_context(symbol)  ← yfinance D/W/M
├── _build_member_analysis(context, tier)
│   ├── _build_trend_summary()
│   ├── _build_deterministic_plan()  ← entry/TP/SL ตัวเลข
│   ├── _build_member_defaults()      ← fallback values
│   ├── _build_member_prompt()
│   ├── _request_member_payload()    ← Gemini call
│   └── _merge_member_payload()      ← รวม AI text + deterministic numbers
└── _render_vip_report() OR _render_pro_report()
    └── return (text, plan_dict_or_none)
```

## Thai Quality Guard

`_fix_thai_typos(text)` แก้คำผิดที่ AI ชอบสร้าง:

| AI พิมพ์ | แก้เป็น |
|---------|--------|
| เกรงทึ่ง | แข็งแกร่ง |
| ทดฐาน | ทดสอบฐาน |
| แนวราคา | แนวโน้มราคา |
| พักฐาน | ปรับฐาน |
| โมเมนตั้ม | โมเมนตัม |
| นัยยะ | นัย |

Apply ใน:
- `_clean_ai_text()` — PRO/VIP report
- `_compact_news_text()` — Flash News + Digest News (import จาก ai_analyzer)

## Other AI Calls

### Slip Analysis (Vision)
`analyze_payment_slip(file_path_or_bytes)` ใน `ai_analyzer.py`:
- Model: `gemini-2.5-flash` (multimodal)
- Input: รูปภาพสลิป
- Output JSON: `{is_slip, amount, ref_no}`

### Flash News (`broadcast_hourly_urgent_news`)
- Prompt: เลือก 1 ข่าวเด่นที่สุดจาก headlines
- Output JSON array of `{original_title, emoji, headline_th, summary}`

### Digest News (`check_and_broadcast_pro_news`)
- Prompt: เลือก 2 ข่าว diverse (คนละสำนัก, คนละประเด็น)
- Output JSON array

### Morning Briefing (`send_morning_briefing`)
- Prompt: สรุปตลาดเมื่อคืน + macro outlook
- Output: ข้อความ Thai 200-400 chars

### Economic Preview (Weekly Digest)
- Prompt: events 7 วันข้างหน้า (FOMC/CPI/NFP/Fed speech)
- Output: bullet list 3-5 รายการ

ดูต่อ:
- [[03 - Tier Comparison]]
- [[08 - Alert System]]

#ai #gemini
