"""Contrarian signal engine — multi-gate anomaly detection, noise filtering, and daily alert capping."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import db

log = logging.getLogger(__name__)


@dataclass
class Signal:
    source: str            # "crypto" | "sec"
    symbol: str
    direction: str         # "LONG" | "SHORT" | "INSIDER_BUY" | "INSIDER_SELL"
    score: float           # 0-100
    conditions_met: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    badge: str = ""
    reason: str = ""


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
) -> Signal | None:
    """Evaluate a single symbol against contrarian long and short gates.

    Requires at least 2 of 3 conditions (A, B, C) to fire.

    `basis_baseline` is the symbol's trailing median basis %.  When
    `basis_baseline.enabled` is true in the config (default), the basis thresholds are
    applied to the deviation from that baseline instead of the raw value, because the raw
    basis of a USDT-margined perp sits permanently around -0.05% and would otherwise
    satisfy the "discount" gate on every run.  Without a baseline (thin history) the
    basis arm is skipped rather than guessed.
    """
    if not funding:
        return None

    cfg = cfg or {}
    long_cfg = cfg.get("contrarian_long", {})
    short_cfg = cfg.get("contrarian_short", {})
    min_conditions = cfg.get("confluence_min_conditions", 2)

    apr = funding.get("annualized_apr", 0)
    basis = funding.get("basis_pct", 0)
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
    oi_delta = oi.get("oi_delta_4h_pct", 0) if oi else None
    fng_value = fng.get("value") if fng else None

    metrics = {
        "funding_apr": round(apr, 2),
        "basis_pct": round(raw_basis, 4),
        "basis_baseline": round(basis_baseline, 4) if basis_baseline is not None else None,
        "retail_ls": round(retail_ratio, 4) if retail_ratio else None,
        "whale_ls": round(whale_ratio, 4) if whale_ratio else None,
        "oi_delta_4h": round(oi_delta, 2) if oi_delta is not None else None,
        "fng": fng_value,
        "fng_class": fng.get("classification") if fng else None,
        "mark_price": funding.get("mark_price"),
    }

    # ──────────────────────────────────────────────────────────
    # Contrarian Long (Retail Fear / Short Squeeze Setup)
    # ──────────────────────────────────────────────────────────
    long_conds: list[str] = []
    long_score = 0.0

    # Gate A: Derivatives (Funding APR <= -8.0%, Basis < -0.03%, OR 4h OI delta <= -3.0%)
    funding_apr_low = long_cfg.get("funding_apr_low", -8.0)
    basis_low_pct = long_cfg.get("basis_low_pct", -0.03)
    oi_drop_thresh = abs(long_cfg.get("oi_drop_4h_pct", 3.0))

    if apr <= funding_apr_low:
        long_conds.append(f"A_funding_apr_low({apr:.2f}%<={funding_apr_low:.2f}%)")
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

    # Gate B: Retail vs Whale Divergence (Retail <= 1.10 OR Whale - Retail >= 0.35)
    retail_ls_max = long_cfg.get("retail_ls_max", 1.10)
    whale_diff_min = long_cfg.get("whale_minus_retail_min", 0.35)

    if retail_ratio is not None:
        if retail_ratio <= retail_ls_max:
            long_conds.append(f"B_retail_ls_low({retail_ratio:.2f}<={retail_ls_max:.2f})")
            long_score += 30
        elif whale_ratio is not None and (whale_ratio - retail_ratio) >= whale_diff_min:
            long_conds.append(f"B_whale_lead_divergence({whale_ratio - retail_ratio:.2f}>={whale_diff_min:.2f})")
            long_score += 30

    # Gate C: Sentiment (Fear & Greed <= 20 Extreme Fear)
    fg_max = long_cfg.get("fg_max", 20)
    if fng_value is not None and fng_value <= fg_max:
        long_conds.append(f"C_macro_extreme_fear(fg={fng_value}<={fg_max})")
        long_score += 35

    long_groups = len({c[0] for c in long_conds})

    # ──────────────────────────────────────────────────────────
    # Contrarian Short (Retail Euphoria / Long Trap Setup)
    # ──────────────────────────────────────────────────────────
    short_conds: list[str] = []
    short_score = 0.0

    # Gate A: Derivatives (Funding APR >= +20.0%, Basis > 0.08%, OR 4h OI delta >= +4.0%)
    funding_apr_high = short_cfg.get("funding_apr_high", 20.0)
    basis_high_pct = short_cfg.get("basis_high_pct", 0.08)
    oi_jump_thresh = short_cfg.get("oi_jump_4h_pct", 4.0)

    if apr >= funding_apr_high:
        short_conds.append(f"A_funding_apr_high({apr:.2f}%>={funding_apr_high:.2f}%)")
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

    # Gate B: Retail Chasing (Retail >= 2.40 OR Retail - Whale >= 0.80)
    retail_ls_min = short_cfg.get("retail_ls_min", 2.40)
    retail_diff_min = short_cfg.get("retail_minus_whale_min", 0.80)

    if retail_ratio is not None:
        if retail_ratio >= retail_ls_min:
            short_conds.append(f"B_retail_chasing({retail_ratio:.2f}>={retail_ls_min:.2f})")
            short_score += 30
        elif whale_ratio is not None and (retail_ratio - whale_ratio) >= retail_diff_min:
            short_conds.append(f"B_retail_whale_divergence({retail_ratio - whale_ratio:.2f}>={retail_diff_min:.2f})")
            short_score += 30

    # Gate C: Sentiment (Fear & Greed >= 80 Extreme Greed)
    fg_min = short_cfg.get("fg_min", 80)
    if fng_value is not None and fng_value >= fg_min:
        short_conds.append(f"C_macro_extreme_greed(fg={fng_value}>={fg_min})")
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
    total = filing.get("total_value") or 0
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
    """Keep one crypto signal per (underlying asset, direction): the highest score.

    BTCUSDT and BTCUSDC describe the same market; alerting both used up the daily cap on
    one idea.  Ties keep the first one in the input order.  Non-crypto signals pass through.
    """
    best: dict[tuple[str, str], Signal] = {}
    order: list[Signal | tuple[str, str]] = []
    for sig in signals:
        if sig.source != "crypto":
            order.append(sig)
            continue
        key = (base_asset(sig.symbol), sig.direction)
        if key not in best:
            best[key] = sig
            order.append(key)
        elif sig.score > best[key].score:
            best[key] = sig
    return [best[item] if isinstance(item, tuple) else item for item in order]


# ─── Cooldown and Hard Cap Check ───


def passes_cooldown(signal: Signal, cfg: dict[str, Any]) -> bool:
    """Return True if signal passes the 24h daily cap AND 12h per-symbol cooldown."""
    # Gate 1: Check 24-hour hard cap (max_alerts_per_day)
    if not check_daily_alert_cap(cfg):
        max_alerts = cfg.get("max_alerts_per_day", 2)
        log.info(
            "Alert suppressed by 24h hard cap: %s %s %s (cap=%d)",
            signal.source, signal.symbol, signal.direction, max_alerts,
        )
        return False

    # Gate 2: 12h per-symbol cooldown
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
