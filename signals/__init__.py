"""Signals package for contrarian market bot."""

from signals.signal_engine import (
    Signal,
    score_crypto,
    filter_form4,
    passes_cooldown,
    check_daily_alert_cap,
    evaluate_market_shock,
    crowding_label,
    dedupe_signals,
)

__all__ = [
    "Signal",
    "score_crypto",
    "filter_form4",
    "passes_cooldown",
    "check_daily_alert_cap",
    "evaluate_market_shock",
    "crowding_label",
    "dedupe_signals",
]
