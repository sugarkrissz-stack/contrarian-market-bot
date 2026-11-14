"""US Market Open Daily Brief Generator — Macro Pre-Market + Crypto Positioning + Directional Bias."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def generate_directional_outlook(
    macro: dict[str, dict[str, Any]],
    crypto: dict[str, dict[str, Any]],
    fng: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    """Determine a rule-based post-open bias with 2-3 explanatory bullets."""
    fng_val = fng.get("value", 50) if fng else 50
    fng_class = fng.get("classification", "Neutral") if fng else "Neutral"

    es = macro.get("ES=F", {})
    nq = macro.get("NQ=F", {})
    dxy = macro.get("DX-Y.NYB", {})
    tnx = macro.get("^TNX", {})

    es_chg = es.get("change_pct", 0.0)
    nq_chg = nq.get("change_pct", 0.0)
    dxy_chg = dxy.get("change_pct", 0.0)
    tnx_chg = tnx.get("change_pct", 0.0)

    # Aggregate BTC/ETH metrics
    btc_data = crypto.get("BTCUSDT") or crypto.get("BTCUSDC") or {}
    eth_data = crypto.get("ETHUSDT") or crypto.get("ETHUSDC") or {}

    btc_fund = (btc_data.get("funding") or {}).get("annualized_apr", 0.0)
    eth_fund = (eth_data.get("funding") or {}).get("annualized_apr", 0.0)
    btc_oi_delta = (btc_data.get("oi") or {}).get("oi_delta_4h_pct", 0.0)
    eth_oi_delta = (eth_data.get("oi") or {}).get("oi_delta_4h_pct", 0.0)
    btc_retail = (btc_data.get("ratios") or {}).get("retail_ratio", 1.5)
    btc_whale = (btc_data.get("ratios") or {}).get("whale_ratio", 1.0)
    eth_retail = (eth_data.get("ratios") or {}).get("retail_ratio", 1.5)
    eth_whale = (eth_data.get("ratios") or {}).get("whale_ratio", 1.0)

    avg_fund = (btc_fund + eth_fund) / 2.0
    avg_oi_delta = (btc_oi_delta + eth_oi_delta) / 2.0

    bullets: list[str] = []
    bias: str

    # Rule 1: Short-Squeeze Watch
    # Negative funding APR, or basis discount, or retail shorting heavily while whales net long
    if avg_fund < -5.0 or (btc_retail < 1.15 and btc_whale > 1.25) or (eth_fund < -8.0):
        bias = "SHORT-SQUEEZE WATCH"
        bullets.append(
            f"Negative funding persists on major perpetuals (ETH: {eth_fund:+.2f}%, BTC: {btc_fund:+.2f}% APR), "
            "indicating overcrowded short positioning vulnerable to a forced unwind."
        )
        if fng_val <= 25:
            bullets.append(
                f"Extreme Macro Fear ({fng_val} - {fng_class}) suggests panic is priced in; "
                "any pre-market equity stabilization can catalyze a sharp relief impulse."
            )
        else:
            bullets.append(
                f"Retail L/S at {btc_retail:.2f} vs Whale L/S at {btc_whale:.2f} reflects positioning divergence in favor of smart money."
            )
        bullets.append(
            f"Equities pre-market: S&P {es_chg:+.2f}%, NQ {nq_chg:+.2f}%. Watch the 09:30 ET opening tick for short covering volume."
        )

    # Rule 2: Long-Squeeze Watch
    # Extreme positive funding or retail extreme long chasing while OI expands
    elif avg_fund > 18.0 or (btc_retail > 2.60 and avg_oi_delta > 3.0) or (fng_val >= 78 and avg_fund > 12.0):
        bias = "LONG-SQUEEZE WATCH"
        bullets.append(
            f"Funding APR remains elevated at {avg_fund:+.2f}% with retail accounts crowded long "
            f"(BTC: {btc_retail:.2f}, ETH: {eth_retail:.2f}), creating downside cascade vulnerability."
        )
        bullets.append(
            f"Open interest delta ({avg_oi_delta:+.2f}% 4h) shows leverage accumulation into potential resistance."
        )
        bullets.append(
            f"Macro backdrop: DXY {dxy_chg:+.2f}% and 10Y Yields {tnx_chg:+.2f}%. Stalling cash market momentum could trigger cascading liquidations."
        )

    # Rule 3: Bullish Rebound
    # Extreme fear with softening DXY or green futures and stabilizing crypto
    elif (fng_val <= 25 or avg_oi_delta < -2.0) and (es_chg >= -0.10 or dxy_chg <= 0.05):
        bias = "BULLISH REBOUND"
        bullets.append(
            f"Macro sentiment is washed out at {fng_val}/100 ({fng_class}), setting up classic contrarian exhaustion conditions."
        )
        bullets.append(
            f"Futures indicate resilient risk appetite: S&P Futures {es_chg:+.2f}%, Nasdaq {nq_chg:+.2f}%, with DXY stable at {dxy.get('price', 100):.2f}."
        )
        bullets.append(
            f"Recent OI flush ({avg_oi_delta:+.2f}% 4h) cleaned out weak leverage, paving the way for cash-driven opening demand."
        )

    # Rule 4: Bearish Continuation
    else:
        bias = "BEARISH CONTINUATION"
        bullets.append(
            f"Risk-off tone dominating global session: Nasdaq-100 Futures {nq_chg:+.2f}%, S&P {es_chg:+.2f}%, and 10Y Yields {tnx_chg:+.2f}%."
        )
        bullets.append(
            f"Crypto retail accounts remain heavy (BTC: {btc_retail:.2f}, ETH: {eth_retail:.2f}) despite macro headwind, risking further long absorption."
        )
        bullets.append(
            f"Fear & Greed index sits at {fng_val} ({fng_class}) with no clear signs of institutional accumulation yet."
        )

    return bias, bullets[:3]


def build_daily_open_brief(
    macro: dict[str, dict[str, Any]],
    crypto: dict[str, dict[str, Any]],
    fng: dict[str, Any] | None,
) -> str:
    """Construct formatted Markdown message for the US Market Open Brief."""
    now_utc = datetime.now(timezone.utc)
    # Estimate ET time (UTC-5 EST or UTC-4 EDT)
    # We display ET timestamp
    bias, bullets = generate_directional_outlook(macro, crypto, fng)

    lines = [
        "🇺🇸 *US MARKET OPEN BRIEF — 09:30 ET*",
        f"📅 `{now_utc.strftime('%Y-%m-%d')} | Pre-Market Snapshot`",
        "",
        "🌐 *Macro Pre-Market:*",
    ]

    es = macro.get("ES=F")
    if es:
        lines.append(f"  • *S&P 500 Futures (ES):* `{es['price']:,.2f}` (`{es['change_pct']:+.2f}%`)")
    nq = macro.get("NQ=F")
    if nq:
        lines.append(f"  • *Nasdaq-100 Futures (NQ):* `{nq['price']:,.2f}` (`{nq['change_pct']:+.2f}%`)")
    dxy = macro.get("DX-Y.NYB")
    if dxy:
        lines.append(f"  • *US Dollar Index (DXY):* `{dxy['price']:.3f}` (`{dxy['change_pct']:+.2f}%`)")
    tnx = macro.get("^TNX")
    if tnx:
        lines.append(f"  • *10Y Treasury Yield:* `{tnx['price']:.3f}%` (`{tnx['change_pct']:+.2f}%`)")

    lines.append("")
    lines.append("⚡ *Crypto Positioning:*")
    if fng:
        lines.append(f"  • *Fear & Greed Index:* `{fng.get('value')}` ({fng.get('classification', '')})")

    # BTC summary
    btc = crypto.get("BTCUSDT") or crypto.get("BTCUSDC") or {}
    bf = btc.get("funding") or {}
    bo = btc.get("oi") or {}
    br = btc.get("ratios") or {}
    lines.append(
        f"  • *BTC:* `${bf.get('mark_price', 0):,.0f}` | "
        f"APR: `{bf.get('annualized_apr', 0):+.2f}%` | "
        f"4h OI Δ: `{bo.get('oi_delta_4h_pct', 0):+.2f}%` | "
        f"Retail: `{br.get('retail_ratio', 0):.2f}` | Whale: `{br.get('whale_ratio', 0):.2f}`"
    )

    # ETH summary
    eth = crypto.get("ETHUSDT") or crypto.get("ETHUSDC") or {}
    ef = eth.get("funding") or {}
    eo = eth.get("oi") or {}
    er = eth.get("ratios") or {}
    lines.append(
        f"  • *ETH:* `${ef.get('mark_price', 0):,.2f}` | "
        f"APR: `{ef.get('annualized_apr', 0):+.2f}%` | "
        f"4h OI Δ: `{eo.get('oi_delta_4h_pct', 0):+.2f}%` | "
        f"Retail: `{er.get('retail_ratio', 0):.2f}` | Whale: `{er.get('whale_ratio', 0):.2f}`"
    )

    lines.append("")
    lines.append(f"🎯 *Post-Open Directional Outlook:* *{bias}*")
    for b in bullets:
        lines.append(f"  • {b}")

    return "\n".join(lines)
