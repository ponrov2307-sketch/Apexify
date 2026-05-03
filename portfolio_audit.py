"""portfolio_audit.py — one-shot AI portfolio audit for new Free users.

Triggered when a Free user adds their 3rd stock (or any stock when their
portfolio already has ≥3) and they haven't received an audit yet. Gives
them a "wow moment" so they understand the value of upgrading to VIP/PRO.

The audit is rule-based + price-driven (no Gemini call) so it's fast and
deterministic — sub-second response when yfinance fast_info is warm.
"""
import yfinance as yf


def _fetch_price(ticker: str) -> float:
    """Quickest possible live read using fast_info.last_price."""
    try:
        fi = yf.Ticker(ticker).fast_info
        p = fi.get('lastPrice') if hasattr(fi, 'get') else getattr(fi, 'last_price', 0)
        return float(p) if p else 0.0
    except Exception:
        return 0.0


def run_free_audit(user_id: str) -> str | None:
    """Build a Thai audit message for the given user. Returns None if the
    portfolio doesn't have enough data to audit (<3 stocks, all prices
    failed to fetch, etc.).
    """
    from database import get_user_portfolio
    portfolio = get_user_portfolio(user_id) or []
    if len(portfolio) < 3:
        return None

    # Compute live values — skip any tickers where price fetch failed
    holdings = []
    for p in portfolio:
        price = _fetch_price(p['ticker'])
        if price <= 0:
            continue
        holdings.append({
            'ticker': p['ticker'],
            'shares': p['shares'],
            'avg_cost': p['avg_cost'],
            'price': price,
            'value': p['shares'] * price,
            'cost': p['shares'] * p['avg_cost'],
        })

    if len(holdings) < 3:
        return None  # not enough live data — don't fire a half-broken audit

    holdings.sort(key=lambda h: h['value'], reverse=True)

    total_value = sum(h['value'] for h in holdings)
    total_cost = sum(h['cost'] for h in holdings)
    pnl_pct = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0.0

    top = holdings[0]
    top_pct = (top['value'] / total_value * 100) if total_value else 0.0

    # Health score — rule of thumb across 3 dimensions
    score = 100
    if top_pct > 40:
        score -= 25
    elif top_pct > 30:
        score -= 15
    elif top_pct > 25:
        score -= 8
    if len(holdings) < 5:
        score -= 12
    if pnl_pct < -15:
        score -= 10
    score = max(20, score)

    # Risk lines
    risks: list[str] = []
    sugs: list[str] = []
    if top_pct > 25:
        risks.append(
            f"• `{top['ticker']}` = {top_pct:.0f}% ของพอร์ต → กระจุกเกิน (แนะนำ <25%)"
        )
        sugs.append(
            f"ลด `{top['ticker']}` เหลือ ~25% — ใช้ `/track {top['ticker']}` เช็คจังหวะขาย"
        )
    if len(holdings) < 5:
        risks.append(
            f"• มีหุ้น {len(holdings)} ตัว → diversification น้อย (แนะนำ ≥5 ตัว)"
        )
        sugs.append(
            "เพิ่มหุ้นต่าง sector — ลอง `VOO`, `SCHD`, `QQQM` (ETF กระจายเสี่ยง)"
        )
    if pnl_pct < -15:
        risks.append(f"• พอร์ตติดลบ {pnl_pct:.1f}% — รอบนี้สั่นใจหน่อยนะครับ")
        sugs.append(
            "ลอง `/compare` ตัวที่ขาดทุน vs ตัว defensive (KO, JNJ) ก่อนตัดสิน cut loss"
        )
    if not risks:
        risks.append("• ไม่พบความเสี่ยงเด่น 👏 พอร์ตคุณกระจายตัวดี")

    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
    pnl_sign = "+" if pnl_pct >= 0 else ""

    # Score color emoji
    if score >= 80:
        score_emoji = "💎"
    elif score >= 65:
        score_emoji = "✨"
    elif score >= 50:
        score_emoji = "⚠️"
    else:
        score_emoji = "🚨"

    lines = [
        "🔍 **Apexify AI ตรวจพอร์ตให้ฟรี — ครั้งแรก!** 🎁",
        "",
        f"💼 พอร์ต {len(holdings)} ตัว · มูลค่ารวม **${total_value:,.0f}**",
        f"{pnl_emoji} P&L: **{pnl_sign}{pnl_pct:.2f}%**",
        f"{score_emoji} Health Score: **{score}/100**",
        "",
        "**⚠️ ความเสี่ยงที่เจอ:**",
        *risks,
    ]
    if sugs:
        lines.append("")
        lines.append("**💡 คำแนะนำ:**")
        for i, s in enumerate(sugs, 1):
            lines.append(f"{i}. {s}")

    lines.extend([
        "",
        "✨ ฟีเจอร์ pro-grade ที่จะช่วยคุณต่อ:",
        "• **Trade Plan** — Entry/TP/SL ตัวเลขจริง _(PRO)_",
        "• **Smart Alerts** — RSI/whale/breakout 24/7 _(PRO)_",
        "• **Daily Pulse** — AI สรุปพอร์ตทุกเช้า _(PRO)_",
        "",
        "🎁 ทดลองฟรี 7 วัน → /freetrial",
    ])

    return "\n".join(lines)
