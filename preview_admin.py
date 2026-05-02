"""
Standalone preview server for admin_dashboard.html.

Serves the template with realistic mock data on http://localhost:5555/admin
NO auth, NO real DB — purely for UI review before deploying to DO.

Run: python preview_admin.py
Stop: Ctrl+C
"""
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template

app = Flask(__name__)


def fake_snapshot():
    now = datetime.now()
    return {
        "admin_id": "1234567890",
        "maintenance": {"enabled": False},
        "system_health": {
            "cpu_usage": 32,
            "ram_total_gb": 1.0,
            "ram_used_gb": 0.62,
            "ram_percent": 62,
            "disk_percent": 18,
            "uptime_hours": 339,
            "uptime_seconds": 339 * 3600,
        },
        "user_stats": {
            "total_users": 187,
            "free_users": 140,
            "vip_users": 30,
            "pro_users": 17,
            "estimated_monthly_revenue": 4220,
        },
        "performance": {
            "win_count": 12,
            "loss_count": 4,
            "pending_count": 3,
            "resolved_count": 16,
            "total_count": 16,
            "sample_size": 19,
            "win_rate": 75.0,
            "average_edge_pct": 2.43,
            "entries": [
                {"symbol": "NVDA", "alert_type": "Breakout", "diff_pct": 4.21, "max_favorable_pct": 5.30, "max_adverse_pct": -1.10, "direction_label": "Bullish", "status": "win", "evaluation_due_at": "2026-05-04 20:00"},
                {"symbol": "AAPL", "alert_type": "Pullback", "diff_pct": 2.15, "max_favorable_pct": 3.40, "max_adverse_pct": -0.80, "direction_label": "Bullish", "status": "win", "evaluation_due_at": "2026-05-04 16:30"},
                {"symbol": "TSLA", "alert_type": "Breakdown", "diff_pct": -2.80, "max_favorable_pct": 1.20, "max_adverse_pct": -3.50, "direction_label": "Bearish", "status": "loss", "evaluation_due_at": "2026-05-03 12:00"},
                {"symbol": "PTT.BK", "alert_type": "Trend", "diff_pct": 1.74, "max_favorable_pct": 2.10, "max_adverse_pct": -0.40, "direction_label": "Bullish", "status": "win", "evaluation_due_at": "2026-05-04 09:30"},
                {"symbol": "GOOGL", "alert_type": "Mean-Revert", "diff_pct": None, "max_favorable_pct": None, "max_adverse_pct": None, "direction_label": "Bullish", "status": "pending", "evaluation_due_at": "2026-05-05 18:00"},
                {"symbol": "MSFT", "alert_type": "Breakout", "diff_pct": 3.50, "max_favorable_pct": 4.10, "max_adverse_pct": -0.50, "direction_label": "Bullish", "status": "win", "evaluation_due_at": "2026-05-03 22:00"},
                {"symbol": "META", "alert_type": "Pullback", "diff_pct": -0.92, "max_favorable_pct": 0.80, "max_adverse_pct": -1.40, "direction_label": "Bullish", "status": "loss", "evaluation_due_at": "2026-05-02 15:00"},
                {"symbol": "AMZN", "alert_type": "Breakout", "diff_pct": None, "max_favorable_pct": None, "max_adverse_pct": None, "direction_label": "Bullish", "status": "pending", "evaluation_due_at": "2026-05-05 21:00"},
            ],
            "breakdown": [
                {"alert_type": "Breakout", "horizon_label": "24h", "win_rate": 78.0, "resolved_count": 9, "average_edge_pct": 3.10},
                {"alert_type": "Pullback", "horizon_label": "8h", "win_rate": 62.5, "resolved_count": 8, "average_edge_pct": 1.80},
                {"alert_type": "Trend", "horizon_label": "24h", "win_rate": 71.4, "resolved_count": 7, "average_edge_pct": 2.20},
                {"alert_type": "Mean-Revert", "horizon_label": "4h", "win_rate": 33.3, "resolved_count": 3, "average_edge_pct": -0.40},
            ],
        },
        "paid_users": [
            {"user_id": "5821334712", "username": "trader_pp", "role": "pro", "expiry_date": "2026-05-23", "is_active": True, "status_label": "Active", "last_active": "2026-05-02 14:32", "bot_status": "active"},
            {"user_id": "8294716033", "username": "investor_kim", "role": "vip", "expiry_date": "2026-05-08", "is_active": True, "status_label": "Active", "last_active": "2026-05-02 09:14", "bot_status": "active"},
            {"user_id": "1023487612", "username": "stocks_th", "role": "vip", "expiry_date": "2026-05-04", "is_active": True, "status_label": "Active", "last_active": "2026-05-01 22:48", "bot_status": "active"},
            {"user_id": "7741209384", "username": "x_trader", "role": "pro", "expiry_date": "2026-06-15", "is_active": True, "status_label": "Active", "last_active": "2026-05-02 11:02", "bot_status": "active"},
            {"user_id": "3498712450", "username": "blocked_test", "role": "vip", "expiry_date": "2026-05-15", "is_active": True, "status_label": "Active", "last_active": "2026-04-20 18:30", "bot_status": "inactive"},
        ],
        "top_watched": {
            "total_watch_entries": 240,
            "unique_symbols": 38,
            "items": [
                {"symbol": "NVDA", "watchers": 47},
                {"symbol": "AAPL", "watchers": 35},
                {"symbol": "TSLA", "watchers": 31},
                {"symbol": "PTT.BK", "watchers": 18},
                {"symbol": "GOOGL", "watchers": 17},
                {"symbol": "MSFT", "watchers": 14},
                {"symbol": "AMZN", "watchers": 12},
                {"symbol": "META", "watchers": 11},
            ],
        },
        "expiring_members": {
            "expiring_3_days": 2,
            "expiring_7_days": 5,
            "revenue_at_risk_7_days": 415,
            "items": [
                {"user_id": "1023487612", "role": "vip", "expiry_date": "2026-05-04", "days_left": 1},
                {"user_id": "8294716033", "role": "vip", "expiry_date": "2026-05-08", "days_left": 5},
                {"user_id": "5471092834", "role": "pro", "expiry_date": "2026-05-09", "days_left": 6},
                {"user_id": "9128374650", "role": "vip", "expiry_date": "2026-05-10", "days_left": 7},
                {"user_id": "2340987651", "role": "vip", "expiry_date": "2026-05-12", "days_left": 9},
            ],
        },
        "price_alerts": {
            "total_alerts": 42,
            "unique_users": 11,
            "items": [
                {"symbol": "NVDA", "alerts": 8},
                {"symbol": "AAPL", "alerts": 6},
                {"symbol": "TSLA", "alerts": 5},
                {"symbol": "PTT.BK", "alerts": 4},
                {"symbol": "GOOGL", "alerts": 3},
                {"symbol": "AMZN", "alerts": 3},
                {"symbol": "META", "alerts": 2},
                {"symbol": "MSFT", "alerts": 2},
            ],
        },
        "notification_settings": {
            "total_settings": 89,
            "notifications_off": 12,
            "custom_windows": 7,
            "distribution": [
                {"label": "1h", "count": 8},
                {"label": "4h", "count": 15},
                {"label": "8h", "count": 32},
                {"label": "24h", "count": 22},
            ],
        },
        "recent_activity": {
            "signups": [
                {"user_id": "9182374650", "username": "thai_trader", "role": "free", "ts": "05-02 14:31"},
                {"user_id": "8472093451", "username": "stock_lover", "role": "free", "ts": "05-02 11:08"},
                {"user_id": "7561034820", "username": "investor_x", "role": "vip", "ts": "05-02 09:42"},
                {"user_id": "6234587190", "username": "freetrial_2026", "role": "free", "ts": "05-01 22:14"},
                {"user_id": "5093487612", "username": "newbie_th", "role": "free", "ts": "05-01 18:05"},
                {"user_id": "4127390485", "username": "long_term", "role": "free", "ts": "05-01 14:50"},
                {"user_id": "3094871625", "username": "swing_trader", "role": "free", "ts": "05-01 09:33"},
                {"user_id": "2084719360", "username": "dividend_fan", "role": "vip", "ts": "04-30 21:18"},
            ],
            "payments": [
                {"ref_no": "20260502TXP9", "user_id": "5821334712", "username": "trader_pp", "role": "pro", "ts": "2026-05-02 12:45"},
                {"ref_no": "20260501NQ74", "user_id": "8294716033", "username": "investor_kim", "role": "vip", "ts": "2026-05-01 19:22"},
                {"ref_no": "20260430HK28", "user_id": "7741209384", "username": "x_trader", "role": "pro", "ts": "2026-04-30 15:08"},
                {"ref_no": "20260429MX13", "user_id": "1023487612", "username": "stocks_th", "role": "vip", "ts": "2026-04-29 11:54"},
                {"ref_no": "20260428BB91", "user_id": "7561034820", "username": "investor_x", "role": "vip", "ts": "2026-04-28 16:30"},
                {"ref_no": "20260425CC07", "user_id": "2084719360", "username": "dividend_fan", "role": "vip", "ts": "2026-04-25 10:12"},
            ],
        },
        "hourly_activity": {
            # Realistic Bangkok-tz activity: low at 02-06, peaks at 09-11 + 19-22
            "hours": [4, 2, 1, 0, 0, 1, 3, 8, 15, 22, 28, 24, 18, 14, 12, 11, 13, 17, 25, 29, 26, 21, 14, 9],
            "max": 29,
            "peak_hour": 19,
            "total_active": 317,
            "window_days": 7,
        },
        "funnel": {
            "total_users": 187,
            "active_30d": 142,
            "active_7d": 87,
            "paying_now": 47,
            "vip_now": 30,
            "pro_now": 17,
            "churned_30d": 3,
            "new_30d": 24,
            "new_7d": 7,
            "conversion_pct": 25.13,
            "active_rate_pct": 75.94,
        },
        "top_commands": {
            "items": [
                {"command": "analyze", "count": 412},
                {"command": "track", "count": 218},
                {"command": "fund", "count": 167},
                {"command": "compare", "count": 141},
                {"command": "ask", "count": 128},
                {"command": "myalerts", "count": 96},
                {"command": "portfolio", "count": 89},
                {"command": "setalert", "count": 73},
                {"command": "freetrial", "count": 64},
                {"command": "earnings", "count": 52},
                {"command": "demo", "count": 47},
                {"command": "account", "count": 39},
            ],
            "total": 1526,
            "window_days": 7,
        },
        "alert_delivery": {
            "totals": {"total": 412, "success": 398, "fail": 14, "batches": 5, "success_rate": 96.6},
            "batches": [
                {"id": 5, "audience": "all", "total": 187, "success": 184, "fail": 3, "success_rate": 98.4, "ts": "05-02 09:00"},
                {"id": 4, "audience": "vip_pro", "total": 47, "success": 47, "fail": 0, "success_rate": 100.0, "ts": "05-01 19:30"},
                {"id": 3, "audience": "all", "total": 184, "success": 178, "fail": 6, "success_rate": 96.7, "ts": "04-30 14:00"},
                {"id": 2, "audience": "pro", "total": 17, "success": 17, "fail": 0, "success_rate": 100.0, "ts": "04-29 11:00"},
                {"id": 1, "audience": "vip_pro", "total": 47, "success": 45, "fail": 2, "success_rate": 95.7, "ts": "04-28 08:00"},
            ],
            "daily": [],
            "window_days": 7,
        },
        "quota_burn": {
            "hit_quota": 12,
            "near_quota": 8,
            "total_free_active": 140,
            "burn_rate_pct": 8.57,
            "quota": 3,
            "top_burners": [
                {"user_id": "9182374650", "username": "thai_trader", "used": 3, "last_active": "05-02 14:31"},
                {"user_id": "8472093451", "username": "stock_lover", "used": 3, "last_active": "05-02 11:08"},
                {"user_id": "6234587190", "username": "freetrial_2026", "used": 3, "last_active": "05-01 22:14"},
                {"user_id": "5093487612", "username": "newbie_th", "used": 3, "last_active": "05-01 18:05"},
                {"user_id": "4127390485", "username": "long_term", "used": 2, "last_active": "05-01 14:50"},
                {"user_id": "3094871625", "username": "swing_trader", "used": 2, "last_active": "05-01 09:33"},
                {"user_id": "1029384756", "username": "casual_user", "used": 2, "last_active": "04-30 21:20"},
                {"user_id": "0987612345", "username": "weekend_only", "used": 1, "last_active": "04-30 15:42"},
            ],
        },
        "win_rate_trend": {
            "daily": [
                {"date": "2026-04-19", "wins": 2, "losses": 1, "total": 3, "win_rate": 66.7},
                {"date": "2026-04-20", "wins": 1, "losses": 2, "total": 3, "win_rate": 33.3},
                {"date": "2026-04-21", "wins": 3, "losses": 0, "total": 3, "win_rate": 100.0},
                {"date": "2026-04-22", "wins": 2, "losses": 2, "total": 4, "win_rate": 50.0},
                {"date": "2026-04-23", "wins": 4, "losses": 1, "total": 5, "win_rate": 80.0},
                {"date": "2026-04-24", "wins": 3, "losses": 1, "total": 4, "win_rate": 75.0},
                {"date": "2026-04-25", "wins": 2, "losses": 0, "total": 2, "win_rate": 100.0},
                {"date": "2026-04-26", "wins": 1, "losses": 1, "total": 2, "win_rate": 50.0},
                {"date": "2026-04-27", "wins": 4, "losses": 2, "total": 6, "win_rate": 66.7},
                {"date": "2026-04-28", "wins": 3, "losses": 0, "total": 3, "win_rate": 100.0},
                {"date": "2026-04-29", "wins": 2, "losses": 1, "total": 3, "win_rate": 66.7},
                {"date": "2026-04-30", "wins": 5, "losses": 1, "total": 6, "win_rate": 83.3},
                {"date": "2026-05-01", "wins": 3, "losses": 2, "total": 5, "win_rate": 60.0},
                {"date": "2026-05-02", "wins": 4, "losses": 1, "total": 5, "win_rate": 80.0},
            ],
            "window_days": 14,
        },
        "generated_at": now,
    }


@app.route("/admin")
def admin():
    return render_template("admin_dashboard.html", **fake_snapshot())


@app.route("/admin/api/stats")
def admin_api_stats():
    today = datetime.now().date()
    growth = [
        {"date": (today - timedelta(days=29 - i)).isoformat(), "count": int(2 + (i * 0.3) + ((i % 5) - 2))}
        for i in range(30)
    ]
    pay = [
        {"date": (today - timedelta(days=29 - i)).isoformat(), "count": int(1 + ((i * 0.15) if i % 3 == 0 else 0))}
        for i in range(30)
    ]
    return jsonify({
        "ok": True,
        "active_users": {"dau": 28, "wau": 87, "mau": 142},
        "user_growth": growth,
        "payment_history": pay,
    })


# Stub endpoints so JS doesn't error if buttons are clicked
@app.route("/admin/actions/<path:_>", methods=["POST", "GET"])
def admin_stub_post(_):
    return jsonify({"ok": False, "error": "preview mode — actions disabled"})


@app.route("/admin/api/user/<user_id>")
def admin_api_user(user_id):
    return jsonify({"ok": True, "user": {
        "user_id": user_id,
        "username": "preview_user",
        "role": "pro",
        "expiry_date": "2026-06-15",
        "status": "active",
        "watchlist_count": 5,
        "portfolio_count": 3,
        "active_alerts": 2,
        "registered_date": "2026-03-01",
        "last_active": "2026-05-02 14:00",
    }})


@app.route("/")
def home():
    return '<a href="/admin" style="font-family:monospace">→ /admin</a>'


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Apexify Admin Dashboard — PREVIEW MODE")
    print("  Open: http://localhost:5555/admin")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=5555, debug=False, use_reloader=False)
