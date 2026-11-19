"""Contrarian signal engine — multi-gate anomaly detection, noise filtering, and daily alert capping."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import db

log = logging.getLogger(__name__)


@dataclass
class Signal:
    source: str            # "crypto" | "sec" | "shock"
    symbol: str
    direction: str         # "LONG" | "SHORT" | "INSIDER_BUY" | "INSIDER_SELL" | "LIQUIDATION FLUSH" | "SHOCK DUMP" | "SHOCK PUMP" | "PANIC CAPITULATION"
    score: float           # 0-100
    conditions_met: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    badge: str = ""
    reason: str = ""
    trigger_type: str = "CONTRARIAN"  # "CONTRARIAN" | "SHOCK"


def crowding_label(retail_ratio: float | None) -> str:
    """Explicit label for retail L/S ratio crowding."""
    if retail_ratio is None:
        return "N/A"
    if retail_ratio > 2.6:
        return "Longs Crowded / Squeeze Risk"
    if retail_ratio < 0.75:
        return "Shorts Crowded / Bounce Setup"
    return "Balanced"


# ─── Market Shock / Liquidation Flush Scorer ───


def evaluate_market_shock(
    symbol: str,
    shock_data: dict[str, Any] | None,
    funding: dict[str, Any] | None,
    ratios: dict[str, Any] | None,
    fng: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
) -> Signal | None:
    """Evaluate symbol against independent Market Shock / Liquidation Flush rules.

    Triggers 1-of-1 immediately without waiting for 2-of-3 contrarian confluence.
    Conditions:
      a) Absolute price move >= 3.5% in 1h, >= 4.5% in 4h, OR >= 5.0% in 24h.
      b) Open Interest drops by >= 5.0% over 1h to 4h (liquidation flush).
      c) Panic capitulation combo: Fear & Greed Index < 15 AND 24h price change <= -4.5%.
    """
    if not shock_data:
        return None

    cfg = cfg or {}
    shock_cfg = cfg.get("market_shock", {})

    p1 = shock_data.get("price_chg_1h_pct", 0.0)
    p4 = shock_data.get("price_chg_4h_pct", 0.0)
    p24 = shock_data.get("price_chg_24h_pct", 0.0)

    oi1 = shock_data.get("oi_chg_1h_pct", 0.0)
    oi4 = shock_data.get("oi_chg_4h_pct", 0.0)
    oi_usd1 = shock_data.get("oi_usd_chg_1h_pct", 0.0)
    oi_usd4 = shock_data.get("oi_usd_chg_4h_pct", 0.0)

    fng_val = fng.get("value") if fng else None
    retail_ratio = ratios.get("retail_ratio") if ratios else None
    whale_ratio = ratios.get("whale_ratio") if ratios else None

    # Thresholds
    th_p1 = shock_cfg.get("price_move_1h_pct", 3.5)
    th_p4 = shock_cfg.get("price_move_4h_pct", 4.5)
    th_p24 = shock_cfg.get("price_move_24h_pct", 5.0)
    th_oi = -abs(shock_cfg.get("oi_flush_drop_pct", 5.0))
    th_fg = shock_cfg.get("capitulation_fg_max", 15)
    th_cap_p24 = -abs(shock_cfg.get("capitulation_24h_drop_pct", 4.5))

    reasons: list[str] = []
    conds: list[str] = []

    # Condition a: Absolute price move
    price_shock_hit = False
    if abs(p1) >= th_p1:
        price_shock_hit = True
        conds.append(f"1h_price_shock({p1:+.2f}% vs +/-{th_p1}%)")
        reasons.append(f"1h price move {p1:+.2f}% (|Δ| >= {th_p1}%)")
    if abs(p4) >= th_p4:
        price_shock_hit = True
        conds.append(f"4h_price_shock({p4:+.2f}% vs +/-{th_p4}%)")
        reasons.append(f"4h price move {p4:+.2f}% (|Δ| >= {th_p4}%)")
    if abs(p24) >= th_p24:
        price_shock_hit = True
        conds.append(f"24h_price_shock({p24:+.2f}% vs +/-{th_p24}%)")
        reasons.append(f"24h price move {p24:+.2f}% (|Δ| >= {th_p24}%)")

    # Condition b: OI drops >= 5.0% over 1h to 4h
    oi_drop_hit = False
    worst_oi_drop = min(oi1, oi4, oi_usd1, oi_usd4)
    if oi1 <= th_oi or oi4 <= th_oi or oi_usd1 <= th_oi or oi_usd4 <= th_oi:
        oi_drop_hit = True
        conds.append(f"oi_flush(worst_drop={worst_oi_drop:+.2f}% <= {th_oi:.1f}%)")
        reasons.append(f"Open Interest dropped {worst_oi_drop:+.2f}% (liquidation flush >= {abs(th_oi):.1f}%)")

    # Condition c: Panic capitulation combo (F&G < 15 and 24h drop <= -4.5%)
    cap_hit = False
    if fng_val is not None and fng_val < th_fg and p24 <= th_cap_p24:
        cap_hit = True
        conds.append(f"panic_capitulation(fg={fng_val} < {th_fg}, 24h={p24:+.2f}% <= {th_cap_p24:+.1f}%)")
        reasons.append(f"Panic capitulation: Fear & Greed {fng_val} < {th_fg} and 24h drop {p24:+.2f}%")

    if not (price_shock_hit or oi_drop_hit or cap_hit):
        return None

    # Determine direction
    if cap_hit:
        direction = "PANIC CAPITULATION"
    elif oi_drop_hit:
        direction = "LIQUIDATION FLUSH"
    elif price_shock_hit:
        net_move = p1 if abs(p1) >= th_p1 else (p4 if abs(p4) >= th_p4 else p24)
        direction = "SHOCK DUMP" if net_move < 0 else "SHOCK PUMP"
    else:
        direction = "MARKET SHOCK"

    base_score = 80.0
    if sum([price_shock_hit, oi_drop_hit, cap_hit]) >= 2:
        base_score += 10.0
    if abs(p1) >= 5.0 or abs(p24) >= 8.0 or worst_oi_drop <= -8.0:
        base_score += 10.0
    score = min(100.0, base_score)

    rate = funding.get("funding_rate", 0.0) if funding else 0.0
    apr = funding.get("annualized_apr", 0.0) if funding else 0.0
    mark = funding.get("mark_price") if funding else shock_data.get("curr_price", 0.0)

    metrics = {
        "mark_price": mark,
        "price_chg_1h": p1,
        "price_chg_4h": p4,
        "price_chg_24h": p24,
        "oi_delta_1h": oi1,
        "oi_delta_4h": oi4,
        "funding_rate": rate,
        "funding_apr": apr,
        "retail_ls": retail_ratio,
        "whale_ls": whale_ratio,
        "crowding_label": crowding_label(retail_ratio),
        "fng": fng_val,
        "fng_class": fng.get("classification") if fng else None,
    }

    return Signal(
        source="shock",
        symbol=symbol,
        direction=direction,
        score=score,
        conditions_met=conds,
        metrics=metrics,
        reason="; ".join(reasons),
        trigger_type="SHOCK",
    )


# ─── Daily Cap Check ───


def check_daily_alert_cap(cfg: dict[str, Any] | None = None) -> bool:
    """Check if under the 24-hour alert cap. Returns True if can alert, False if cap reached."""
    cfg = cfg or {}
    max_alerts = cfg.get("max_alerts_per_day")
    if max_alerts is None:
        max_alerts = cfg.get("cooldown", {}).get("max_alerts_per_day", 2)

    current_count = db.count_alerts_last_24h()
    if current_count >= max_alerts:
        log.warning(
            "Hard cap reached: %d/%d alerts recorded in alerts_log over the last 24 hours",
            current_count, max_alerts,
        )
        return False
    return True


# ─── Crypto Contrarian Scorer ───


def score_crypto(
    symbol: str,
    funding: dict[str, Any] | None,
    oi: dict[str, Any] | None,
    ratios: dict[str, Any] | None,
    fng: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
    basis_baseline: float | None = None,
    shock_data: dict[str, Any] | None = None,
) -> Signal | None:
    """Evaluate a single symbol against contrarian long and short gates.

    Requires at least 2 of 3 conditions (A, B, C) to fire.

    Thresholds:
      - Fear & Greed Index: < 20 (Extreme Fear) or > 80 (Extreme Greed)
      - Funding Rate: < -0.00005 (-0.005%) or > 0.00025 (+0.025%)
      - Long/Short Ratio: > 2.60 (Longs Crowded / Squeeze Risk) or < 0.75 (Shorts Crowded / Bounce Setup)
    """
    if not funding:
        return None

    cfg = cfg or {}
    long_cfg = cfg.get("contrarian_long", {})
    short_cfg = cfg.get("contrarian_short", {})
    min_conditions = cfg.get("confluence_min_conditions", 2)

    apr = funding.get("annualized_apr", 0.0)
    funding_rate = funding.get("funding_rate", 0.0)
    basis = funding.get("basis_pct", 0.0)
    raw_basis = basis
    use_baseline = bool(cfg.get("basis_baseline", {}).get("enabled", True))
    basis_usable = True
    if use_baseline:
        if basis_baseline is None:
            basis_usable = False
        else:
            basis = raw_basis - basis_baseline
    retail_ratio = ratios.get("retail_ratio") if ratios else None
    whale_ratio = ratios.get("whale_ratio") if ratios else None
    oi_delta = oi.get("oi_delta_4h_pct", 0.0) if oi else None
    if (oi_delta is None or oi_delta == 0.0) and shock_data and shock_data.get("oi_chg_4h_pct") is not None:
        oi_delta = shock_data.get("oi_chg_4h_pct")
    fng_value = fng.get("value") if fng else None

    metrics = {
        "funding_rate": funding_rate,
        "funding_apr": round(apr, 2),
        "basis_pct": round(raw_basis, 4),
        "basis_baseline": round(basis_baseline, 4) if basis_baseline is not None else None,
        "retail_ls": round(retail_ratio, 4) if retail_ratio else None,
        "whale_ls": round(whale_ratio, 4) if whale_ratio else None,
        "crowding_label": crowding_label(retail_ratio),
        "oi_delta_4h": round(oi_delta, 2) if oi_delta is not None else None,
        "fng": fng_value,
        "fng_class": fng.get("classification") if fng else None,
        "mark_price": funding.get("mark_price"),
    }
    if shock_data:
        metrics["price_chg_1h"] = shock_data.get("price_chg_1h_pct")
        metrics["price_chg_4h"] = shock_data.get("price_chg_4h_pct")
        metrics["price_chg_24h"] = shock_data.get("price_chg_24h_pct")
        metrics["oi_delta_1h"] = shock_data.get("oi_chg_1h_pct")

    # ──────────────────────────────────────────────────────────
    # Contrarian Long (Retail Fear / Short Squeeze Setup)
    # ──────────────────────────────────────────────────────────
    long_conds: list[str] = []
    long_score = 0.0

    # Gate A: Derivatives (Funding Rate < -0.00005 / APR <= -5.48%, Basis discount, OR 4h OI delta <= -3.0%)
    funding_rate_low = long_cfg.get("funding_rate_low", -0.00005)
    funding_apr_low = long_cfg.get("funding_apr_low", -5.475)
    basis_low_pct = long_cfg.get("basis_low_pct", -0.03)
    oi_drop_thresh = abs(long_cfg.get("oi_drop_4h_pct", 3.0))

    if funding_rate < funding_rate_low or apr <= funding_apr_low:
        long_conds.append(
            f"A_funding_discount(rate={funding_rate*100:+.4f}%<{funding_rate_low*100:+.4f}%, apr={apr:+.2f}%)"
        )
        long_score += 35
    elif basis_usable and basis < basis_low_pct:
        if use_baseline:
            long_conds.append(
                f"A_basis_discount({basis:+.4f}pt vs {raw_basis - basis:+.4f}% median, limit {basis_low_pct:.4f}pt)"
            )
        else:
            long_conds.append(f"A_basis_discount({basis:.4f}%<{basis_low_pct:.4f}%)")
        long_score += 20
    if oi_delta is not None and oi_delta <= -oi_drop_thresh:
        long_conds.append(f"A_oi_flush({oi_delta:.2f}%<=-{oi_drop_thresh:.2f}%)")
        long_score += 30

    # Gate B: Retail vs Whale Divergence (Retail < 0.75 [Shorts Crowded / Bounce Setup] OR Whale - Retail >= 0.35)
    retail_ls_max = long_cfg.get("retail_ls_max", 0.75)
    whale_diff_min = long_cfg.get("whale_minus_retail_min", 0.35)

    if retail_ratio is not None:
        if retail_ratio < retail_ls_max:
            long_conds.append(
                f"B_retail_ls_low({retail_ratio:.4f}<{retail_ls_max:.2f}, Shorts Crowded / Bounce Setup)"
            )
            long_score += 35
        elif whale_ratio is not None and (whale_ratio - retail_ratio) >= whale_diff_min:
            long_conds.append(f"B_whale_lead_divergence({whale_ratio - retail_ratio:.2f}>={whale_diff_min:.2f})")
            long_score += 30

    # Gate C: Sentiment (Fear & Greed < 20 Extreme Fear)
    fg_max = long_cfg.get("fg_max", 20)
    if fng_value is not None and fng_value < fg_max:
        long_conds.append(f"C_macro_extreme_fear(fg={fng_value}<{fg_max})")
        long_score += 35

    long_groups = len({c[0] for c in long_conds})

    # ──────────────────────────────────────────────────────────
    # Contrarian Short (Retail Euphoria / Long Trap Setup)
    # ──────────────────────────────────────────────────────────
    short_conds: list[str] = []
    short_score = 0.0

    # Gate A: Derivatives (Funding Rate > 0.00025 / APR >= +27.38%, Basis premium, OR 4h OI delta >= +4.0%)
    funding_rate_high = short_cfg.get("funding_rate_high", 0.00025)
    funding_apr_high = short_cfg.get("funding_apr_high", 27.375)
    basis_high_pct = short_cfg.get("basis_high_pct", 0.08)
    oi_jump_thresh = short_cfg.get("oi_jump_4h_pct", 4.0)

    if funding_rate > funding_rate_high or apr >= funding_apr_high:
        short_conds.append(
            f"A_funding_premium(rate={funding_rate*100:+.4f}%>{funding_rate_high*100:+.4f}%, apr={apr:+.2f}%)"
        )
        short_score += 35
    elif basis_usable and basis > basis_high_pct:
        if use_baseline:
            short_conds.append(
                f"A_basis_premium({basis:+.4f}pt vs {raw_basis - basis:+.4f}% median, limit {basis_high_pct:.4f}pt)"
            )
        else:
            short_conds.append(f"A_basis_premium({basis:.4f}%>{basis_high_pct:.4f}%)")
        short_score += 20
    if oi_delta is not None and oi_delta >= oi_jump_thresh:
        short_conds.append(f"A_oi_expansion({oi_delta:.2f}%>={oi_jump_thresh:.2f}%)")
        short_score += 30

    # Gate B: Retail Chasing (Retail > 2.60 [Longs Crowded / Squeeze Risk] OR Retail - Whale >= 0.80)
    retail_ls_min = short_cfg.get("retail_ls_min", 2.60)
    retail_diff_min = short_cfg.get("retail_minus_whale_min", 0.80)

    if retail_ratio is not None:
        if retail_ratio > retail_ls_min:
            short_conds.append(
                f"B_retail_chasing({retail_ratio:.4f}>{retail_ls_min:.2f}, Longs Crowded / Squeeze Risk)"
            )
            short_score += 35
        elif whale_ratio is not None and (retail_ratio - whale_ratio) >= retail_diff_min:
            short_conds.append(f"B_retail_whale_divergence({retail_ratio - whale_ratio:.2f}>={retail_diff_min:.2f})")
            short_score += 30

    # Gate C: Sentiment (Fear & Greed > 80 Extreme Greed)
    fg_min = short_cfg.get("fg_min", 80)
    if fng_value is not None and fng_value > fg_min:
        short_conds.append(f"C_macro_extreme_greed(fg={fng_value}>{fg_min})")
        short_score += 35

    short_groups = len({c[0] for c in short_conds})

    # ──────────────────────────────────────────────────────────
    # Confluence Gate (At least 2 of 3 conditions required)
    # ──────────────────────────────────────────────────────────
    if long_groups >= min_conditions and long_score >= short_score:
        return Signal(
            source="crypto",
            symbol=symbol,
            direction="LONG",
            score=min(long_score, 100),
            conditions_met=long_conds,
            metrics=metrics,
            reason=f"Contrarian LONG — {long_groups}/3 conditions met: {', '.join(long_conds)}",
            trigger_type="CONTRARIAN",
        )

    if short_groups >= min_conditions:
        return Signal(
            source="crypto",
            symbol=symbol,
            direction="SHORT",
            score=min(short_score, 100),
            conditions_met=short_conds,
            metrics=metrics,
            reason=f"Contrarian SHORT — {short_groups}/3 conditions met: {', '.join(short_conds)}",
            trigger_type="CONTRARIAN",
        )

    log.debug(
        "%s: no confluence (long_groups=%d, short_groups=%d)",
        symbol, long_groups, short_groups,
    )
    return None


# ─── SEC Form 4 Filter ───


def filter_form4(
    filing: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> Signal | None:
    """Apply noise filter to a Form 4 transaction."""
    cfg = cfg or {}
    f4cfg = cfg.get("form4_filter", {})
    suppress = set(f4cfg.get("suppress_codes", ["F", "A", "M"]))
    purchase_min = f4cfg.get("purchase_min_value", 50_000)
    sale_min = f4cfg.get("sale_min_value", 500_000)
    sale_10b51_min = f4cfg.get("sale_10b51_min_value", 2_000_000)

    code = (filing.get("txn_code") or "").upper().strip()
    total = abs(filing.get("total_value") or 0)
    is_10b51 = bool(filing.get("is_10b51"))
    ticker = filing.get("ticker", "?")

    # Suppress noise codes
    if code in suppress:
        log.debug("Form 4 suppressed: code %s for %s", code, ticker)
        return None

    if code == "M":
        return None

    direction: str | None = None

    if code == "P" and total >= purchase_min:
        direction = "INSIDER_BUY"
    elif code == "S":
        if is_10b51 and total >= sale_10b51_min:
            direction = "INSIDER_SELL"
        elif not is_10b51 and total >= sale_min:
            direction = "INSIDER_SELL"

    if not direction:
        log.debug(
            "Form 4 below threshold: %s code=%s val=$%.0f 10b5-1=%s",
            ticker, code, total, is_10b51,
        )
        return None

    score = min(100, total / 10_000)

    return Signal(
        source="sec",
        symbol=ticker,
        direction=direction,
        score=score,
        conditions_met=[f"code_{code}", f"value_${total:,.0f}"],
        metrics={
            "txn_code": code,
            "shares": filing.get("shares"),
            "price": filing.get("price_per_share"),
            "total_value": total,
            "is_10b51": is_10b51,
            "filed_date": filing.get("filed_date"),
            "accession": filing.get("accession_no"),
        },
        reason=(
            f"{'Open-market BUY' if direction == 'INSIDER_BUY' else 'Discretionary SELL'}"
            f" — ${total:,.0f} ({'10b5-1' if is_10b51 else 'non-10b5-1'})"
        ),
    )


# ─── One Signal Per Underlying Asset ───

_QUOTE_SUFFIXES = ("USDT", "USDC")


def base_asset(symbol: str) -> str:
    """BTCUSDT / BTCUSDC -> BTC (the underlying both pairs track)."""
    s = symbol.upper()
    for q in _QUOTE_SUFFIXES:
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def sibling_symbols(symbol: str, cfg: dict[str, Any]) -> list[str]:
    """All configured symbols on the same underlying (always includes `symbol`)."""
    sym_cfg = cfg.get("symbols", {})
    configured = list(sym_cfg.get("primary", [])) + list(sym_cfg.get("secondary", []))
    base = base_asset(symbol)
    sibs = [s for s in configured if base_asset(s) == base]
    if symbol not in sibs:
        sibs.append(symbol)
    return sibs


def dedupe_signals(signals: list[Signal]) -> list[Signal]:
    """Keep one signal per (underlying asset, direction/type): the highest score.

    BTCUSDT and BTCUSDC describe the same market; alerting both used up the daily cap or
    sent duplicate shock alerts. Ties keep the first one in input order. For SEC filings,
    keep the highest-score filing per (ticker, direction).
    """
    best: dict[tuple[str, str], Signal] = {}
    order: list[tuple[str, str]] = []
    for sig in signals:
        if sig.source == "sec":
            key = (sig.symbol, sig.direction)
        else:
            action_key = "SHOCK" if (sig.source == "shock" or sig.trigger_type == "SHOCK") else sig.direction
            key = (base_asset(sig.symbol), action_key)

        if key not in best:
            best[key] = sig
            order.append(key)
        elif sig.score > best[key].score:
            best[key] = sig
    return [best[key] for key in order]


# ─── Cooldown and Hard Cap Check ───


def passes_cooldown(signal: Signal, cfg: dict[str, Any]) -> bool:
    """Return True if signal passes cooldown and cap rules.

    Every alert source shares the rolling 24-hour global cap. Market Shock alerts
    additionally use their separate 3-hour per-symbol cooldown, while standard
    contrarian and SEC alerts use the configured per-symbol cooldown.
    """
    # ── Global cap: shock, crypto, and SEC alerts all consume the same budget ──
    if not check_daily_alert_cap(cfg):
        max_alerts = cfg.get("max_alerts_per_day", 2)
        log.info(
            "Alert suppressed by global 24h cap: %s %s %s (cap=%d)",
            signal.source, signal.symbol, signal.direction, max_alerts,
        )
        return False

    # ── Market Shock Cooldown Check (3h separate cooldown) ──
    if signal.source == "shock" or signal.trigger_type == "SHOCK":
        shock_cfg = cfg.get("market_shock", {})
        hours = shock_cfg.get("cooldown_hours", 3)
        check_symbols = sibling_symbols(signal.symbol, cfg)
        for s in check_symbols:
            if db.check_shock_cooldown(s, cooldown_hours=hours):
                log.info(
                    "Market Shock cooldown suppressed (%dh): %s %s (related to %s)",
                    hours, signal.symbol, signal.direction, s,
                )
                return False
        return True

    # ── Standard Contrarian & SEC: 12h per-symbol cooldown ──
    cd_cfg = cfg.get("cooldown", {})
    hours = cd_cfg.get("hours", 12)
    esc_pct = cd_cfg.get("escalation_pct", 40)

    # For crypto, the cooldown covers every pair on the same underlying, so an alert for
    # BTCUSDT also holds back BTCUSDC (and the other way round).
    check_symbols = sibling_symbols(signal.symbol, cfg) if signal.source == "crypto" else [signal.symbol]
    suppressed = any(
        db.check_cooldown(signal.source, s, signal.direction, hours, esc_pct, signal.score)
        for s in check_symbols
    )
    if suppressed:
        log.info(
            "Cooldown suppressed (12h): %s %s %s (score=%.1f)",
            signal.source, signal.symbol, signal.direction, signal.score,
        )
        return False

    return True
