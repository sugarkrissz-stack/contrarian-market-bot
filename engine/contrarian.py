"""Compatibility module — re-exports from signals.signal_engine."""

from signals.signal_engine import (
    Signal,
    score_crypto,
    filter_form4,
    passes_cooldown,
    check_daily_alert_cap,
)

__all__ = [
    "Signal",
    "score_crypto",
    "filter_form4",
    "passes_cooldown",
    "check_daily_alert_cap",
]
