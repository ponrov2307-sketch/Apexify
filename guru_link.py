"""ลิงก์ teaser "เซียนถือหุ้นนี้" ต่อท้ายผลวิเคราะห์หุ้น

ดึงจาก public API ของเว็บ (เปิด anonymous แล้ว 11 ก.ค. 2026) — เป็น funnel
พาคนจากบอทไปหน้า /gurus บนเว็บ; ทุกอย่าง best-effort ห้ามทำ analyze ช้า/พัง
"""
import time

import requests

WEB_BASE = "https://apexifyy.up.railway.app"

# cache ต่อ symbol 24 ชม. — 13F เปลี่ยนรายไตรมาส ไม่ต้องยิงซ้ำ
_CACHE: dict = {}
_TTL = 24 * 3600
_CACHE_MAX = 4000


def guru_teaser_line(symbol: str) -> str:
    """คืน "\\n\\n🐋 ..." ถ้ามีเซียนถือหุ้นนี้ / "" ถ้าไม่มีหรือดึงพลาด (ไม่ raise)"""
    sym = (symbol or "").upper().strip()
    if not sym:
        return ""
    now = time.time()
    hit = _CACHE.get(sym)
    if hit and now - hit[0] < _TTL:
        return hit[1]

    line = ""
    try:
        r = requests.get(f"{WEB_BASE}/api/gurus/stock/{sym}", timeout=4)
        holders = (r.json() or {}).get("holders") or []
        if holders:
            # เอาชื่อสั้น (นามสกุลคนดังจำง่ายกว่า เช่น Buffett/Soros) 3 คนแรก
            names = []
            for h in holders[:3]:
                full = (h.get("name") or "").strip()
                if full:
                    names.append(full.split()[-1])
            extra = f" +{len(holders) - 3}" if len(holders) > 3 else ""
            if names:
                line = (
                    f"\n\n🐋 เซียนระดับโลกถือ **{sym}** อยู่ {len(holders)} คน "
                    f"({', '.join(names)}{extra})\n"
                    f"👉 ส่องพอร์ตเต็มฟรี: {WEB_BASE}/gurus"
                )
    except Exception:
        # เว็บล่ม/ช้า → ไม่ต้องมีบรรทัดนี้ วิเคราะห์หลักต้องไม่กระทบ
        line = ""

    if len(_CACHE) > _CACHE_MAX:
        _CACHE.clear()
    _CACHE[sym] = (now, line)
    return line
