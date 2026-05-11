"""
plan_evaluator_cron.py — Auto /run_outcomes ทุก 6 ชม.

แก้ปัญหา: admin run /run_outcomes มือแค่ 5 ครั้งใน 30 วัน → 365 plans pending ค้าง
ผล: track record (`/track`) stale → trust signal ของ user ลด

Logic core: port มาจาก handle_run_outcomes ใน main.py (entry-filled-first + conservative TP/SL)
แต่ run แบบ silent (ไม่ส่ง progress message) + DM admin สรุปผล
"""

import time
import threading
from datetime import datetime


def evaluate_pending_plans_once():
    """รัน 1 cycle — ตรวจ plans pending + อัปเดต outcome

    Returns: dict {
        "total_plans": int,
        "total_symbols": int,
        "updated": int,
        "yfinance_failed": int,
        "no_hit": int,
        "breakdown": {outcome: count, ...},
        "error": str | None,
    }
    """
    try:
        from database import get_pending_plans, update_plan_outcome, expire_stale_plans, get_connection
        import yfinance as _yf
        from datetime import datetime as _dt2
    except Exception as e:
        return {"error": f"import error: {e}"}

    try:
        pending = get_pending_plans(min_age_hours=24, max_age_days=45)
    except Exception as e:
        return {"error": f"get_pending_plans: {e}"}

    if not pending:
        return {
            "total_plans": 0, "total_symbols": 0, "updated": 0,
            "yfinance_failed": 0, "no_hit": 0, "breakdown": {}, "error": None,
        }

    # Group by symbol
    symbols = {}
    for row in pending:
        symbols.setdefault(row[1], []).append(row)

    total_plans = len(pending)
    total_symbols = len(symbols)
    updated = 0
    yf_failed = 0
    no_hit = 0

    for symbol, plans in symbols.items():
        try:
            earliest_issued = min(p[9] for p in plans)
            ticker = _yf.Ticker(symbol)
            hist = ticker.history(start=earliest_issued.date(), interval="1d")
            if hist.empty:
                yf_failed += 1
                continue

            # strip tz เพื่อให้เปรียบกับ DB issued_at (naive)
            try:
                hist.index = hist.index.tz_localize(None)
            except (TypeError, AttributeError):
                pass

            for plan in plans:
                plan_id, _, bias, e_low, e_high, tp1, tp2, sl, _, issued_at = plan
                tp1_v = float(tp1) if tp1 is not None else None
                tp2_v = float(tp2) if tp2 is not None else None
                sl_v = float(sl) if sl is not None else None
                e_low_v = float(e_low) if e_low is not None else None
                e_high_v = float(e_high) if e_high is not None else None

                if hasattr(issued_at, 'tzinfo') and issued_at.tzinfo is not None:
                    issued_at = issued_at.replace(tzinfo=None)

                plan_hist = hist[hist.index >= issued_at]
                if plan_hist.empty:
                    continue

                # Phase 1: รอ entry fill, Phase 2: ตรวจ TP/SL หลัง fill
                entry_dt = sl_dt = tp1_dt = tp2_dt = None
                for date, row_data in plan_hist.iterrows():
                    hi = float(row_data['High'])
                    lo = float(row_data['Low'])
                    if entry_dt is None:
                        if e_low_v is not None and e_high_v is not None:
                            if lo <= e_high_v and hi >= e_low_v:
                                entry_dt = date
                        if entry_dt is None:
                            continue
                    if sl_v is not None and lo <= sl_v and sl_dt is None:
                        sl_dt = date
                    if tp1_v is not None and hi >= tp1_v and tp1_dt is None:
                        tp1_dt = date
                    if tp2_v is not None and hi >= tp2_v and tp2_dt is None:
                        tp2_dt = date

                # entry-filled-first + conservative outcome
                if entry_dt is None:
                    plan_age = (_dt2.now() - issued_at).days
                    if plan_age >= 14:
                        update_plan_outcome(plan_id, 'no_entry', "Entry never reached")
                        updated += 1
                    else:
                        no_hit += 1
                elif sl_dt and (tp1_dt is None or sl_dt <= tp1_dt):
                    update_plan_outcome(plan_id, 'sl_hit', f"SL {sl_v:.2f}")
                    updated += 1
                elif tp2_dt and (sl_dt is None or tp2_dt < sl_dt):
                    update_plan_outcome(plan_id, 'tp2_hit', f"TP2 {tp2_v:.2f}")
                    updated += 1
                elif tp1_dt and (sl_dt is None or tp1_dt < sl_dt):
                    update_plan_outcome(plan_id, 'tp1_hit', f"TP1 {tp1_v:.2f}")
                    updated += 1
                else:
                    no_hit += 1
        except Exception as e:
            print(f"[plan_eval] {symbol} err: {e}", flush=True)

    try:
        expire_stale_plans(max_age_days=45)
    except Exception:
        pass

    # breakdown
    breakdown = {}
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT outcome, COUNT(*) FROM analysis_plans GROUP BY outcome")
        breakdown = {row[0]: int(row[1]) for row in c.fetchall()}
        c.close()
        conn.close()
    except Exception as e:
        print(f"[plan_eval] breakdown err: {e}", flush=True)

    return {
        "total_plans": total_plans,
        "total_symbols": total_symbols,
        "updated": updated,
        "yfinance_failed": yf_failed,
        "no_hit": no_hit,
        "breakdown": breakdown,
        "error": None,
    }


def run_plan_evaluator_cron(bot):
    """Daemon thread — รัน evaluate_pending_plans_once() ทุก 6 ชม.

    DM ADMIN_ID สรุปผลเฉพาะถ้ามี updated > 0 (ไม่ spam ถ้าไม่มีการเปลี่ยนแปลง)
    """
    import config

    print(f"[plan_eval] cron started — every 6 hours", flush=True)
    time.sleep(120)  # warm-up — รอ DB init เสร็จก่อน

    while True:
        try:
            t_start = time.time()
            result = evaluate_pending_plans_once()
            t_elapsed = time.time() - t_start

            if result.get("error"):
                print(f"[plan_eval] error: {result['error']}", flush=True)
            else:
                updated = result.get("updated", 0)
                total = result.get("total_plans", 0)
                print(
                    f"[plan_eval] cycle done — {updated}/{total} updated "
                    f"(yf_fail={result.get('yfinance_failed', 0)}, "
                    f"no_hit={result.get('no_hit', 0)}) in {t_elapsed:.1f}s",
                    flush=True,
                )

                # DM admin เฉพาะถ้ามี outcome เปลี่ยน (กัน spam)
                if updated > 0 and config.ADMIN_ID:
                    try:
                        breakdown = result.get("breakdown", {})
                        msg = (
                            f"📊 *Plan Evaluator Cron*\n"
                            f"━━━━━━━━━━━━━━\n"
                            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
                            f"✅ Updated: {updated} / {total} plans\n"
                            f"⏳ Still pending: {result.get('no_hit', 0)} no-hit\n"
                            f"📈 Breakdown:\n"
                            f"  • open: {breakdown.get('open', 0)}\n"
                            f"  • tp1\\_hit: {breakdown.get('tp1_hit', 0)}\n"
                            f"  • tp2\\_hit: {breakdown.get('tp2_hit', 0)}\n"
                            f"  • sl\\_hit: {breakdown.get('sl_hit', 0)}\n"
                            f"  • no\\_entry: {breakdown.get('no_entry', 0)}\n"
                            f"  • expired: {breakdown.get('expired', 0)}"
                        )
                        bot.send_message(config.ADMIN_ID, msg, parse_mode="Markdown")
                    except Exception as e:
                        print(f"[plan_eval] admin DM err: {e}", flush=True)
        except Exception as e:
            print(f"[plan_eval] loop err: {e}", flush=True)

        time.sleep(6 * 3600)   # ทุก 6 ชม.


if __name__ == "__main__":
    # smoke test — รัน 1 cycle, ไม่ส่ง DM
    result = evaluate_pending_plans_once()
    import json
    print(json.dumps(result, indent=2, default=str))
