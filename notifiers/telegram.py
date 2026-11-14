"""Telegram Bot API notifier + local markdown fallback."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from signals.signal_engine import Signal

log = logging.getLogger(__name__)


def _get_creds() -> tuple[str | None, str | None]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def send_alert(signal: Signal, dry_run: bool = False) -> bool:
    """Send a formatted Telegram alert.  Returns True on success."""
    text = _format_signal(signal)

    if dry_run:
        log.info("[DRY-RUN] Would send Telegram alert:\n%s", text)
        return True

    token, chat_id = _get_creds()
    if not token or not chat_id:
        log.warning("Telegram creds missing — alert written to local report only")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Telegram alert sent for %s %s", signal.symbol, signal.direction)
        return True
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


def send_test_alert() -> bool:
    """Send a test ping to verify Telegram connectivity."""
    token, chat_id = _get_creds()
    if not token or not chat_id:
        log.warning("Telegram creds not set — skipping test alert")
        return False

    text = "🤖 *Contrarian Bot — Test Alert*\nBot is online and connected."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Test alert sent successfully")
        return True
    except Exception as e:
        log.error("Test alert failed: %s", e)
        return False


def send_daily_open_brief(brief_text: str, dry_run: bool = False) -> bool:
    """Send guaranteed US Market Open Daily Brief to Telegram or log in dry-run."""
    if dry_run:
        log.info("[DRY-RUN] Would send Daily Open Brief to Telegram:\n%s", brief_text)
        return True

    token, chat_id = _get_creds()
    if not token or not chat_id:
        log.warning("Telegram credentials missing; Daily Open Brief not sent")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": brief_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=12)
        resp.raise_for_status()
        log.info("Daily Open Brief sent successfully to Telegram")
        return True
    except Exception as e:
        log.error("Daily Open Brief send failed: %s", e)
        return False


def _format_signal(signal: Signal) -> str:
    """Build Markdown message for Telegram."""
    badge = signal.badge or f"[{signal.symbol}]"
    lines = [
        f"⚡ *{badge} {signal.direction}*",
        f"Signal Score: `{signal.score:.0f}/100`",
        "",
    ]

    m = signal.metrics
    if signal.source == "crypto":
        lines.append("📊 *Metrics:*")
        if m.get("funding_apr") is not None:
            lines.append(f"  Funding APR: `{m['funding_apr']:+.2f}%`")
        if m.get("basis_pct") is not None:
            lines.append(f"  Basis: `{m['basis_pct']:+.4f}%`")
        if m.get("retail_ls") is not None:
            lines.append(f"  Retail L/S: `{m['retail_ls']:.4f}`")
        if m.get("whale_ls") is not None:
            lines.append(f"  Whale L/S: `{m['whale_ls']:.4f}`")
        if m.get("oi_delta_4h") is not None:
            lines.append(f"  4h OI Δ: `{m['oi_delta_4h']:+.2f}%`")
        if m.get("fng") is not None:
            lines.append(f"  Fear & Greed: `{m['fng']}` ({m.get('fng_class', '')})")
    elif signal.source == "sec":
        lines.append("📋 *SEC Filing:*")
        if m.get("txn_code"):
            lines.append(f"  Code: `{m['txn_code']}`")
        if m.get("shares"):
            lines.append(f"  Shares: `{m['shares']:,.0f}`")
        if m.get("price"):
            lines.append(f"  Price: `${m['price']:,.2f}`")
        if m.get("total_value"):
            lines.append(f"  Value: `${m['total_value']:,.0f}`")
        lines.append(f"  10b5-1: `{'Yes' if m.get('is_10b51') else 'No'}`")

    lines.append("")
    lines.append(f"💡 _{signal.reason}_")
    return "\n".join(lines)


# ─── Market Snapshot Report ───


def write_market_brief(
    binance_data: dict[str, dict[str, Any]],
    fng: dict[str, Any] | None,
    sec_filings: dict[str, list],
    signals: list[Signal],
    report_path: str = "reports/latest_brief.md",
) -> None:
    """Write/overwrite the latest market snapshot markdown."""
    p = Path(report_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Contrarian Market Brief — {now}",
        "",
    ]

    # Fear & Greed
    if fng:
        lines.append(f"## Macro Sentiment")
        lines.append(f"- Fear & Greed Index: **{fng['value']}** ({fng['classification']})")
        if fng.get("prev_value") is not None:
            lines.append(f"- Previous: **{fng['prev_value']}** ({fng.get('prev_classification', '')})")
        lines.append("")

    # Binance futures table
    lines.append("## Binance USDS-M Futures")
    lines.append("")
    lines.append("| Symbol | Mark Price | Funding APR | Basis % | OI (USD) | 4h OI Δ | Retail L/S | Whale L/S |")
    lines.append("|--------|-----------|-------------|---------|----------|---------|------------|-----------|")

    for sym, d in binance_data.items():
        f = d.get("funding") or {}
        o = d.get("oi") or {}
        r = d.get("ratios") or {}
        lines.append(
            f"| {sym} "
            f"| ${f.get('mark_price', 0):,.2f} "
            f"| {f.get('annualized_apr', 0):+.2f}% "
            f"| {f.get('basis_pct', 0):+.4f}% "
            f"| ${o.get('oi_usd', 0):,.0f} "
            f"| {o.get('oi_delta_4h_pct', 0):+.2f}% "
            f"| {r.get('retail_ratio', 0):.4f} "
            f"| {r.get('whale_ratio', 0):.4f} |"
        )
    lines.append("")

    # SEC filings
    total_sec = sum(len(v) for v in sec_filings.values())
    if total_sec > 0:
        lines.append("## SEC Filings (New)")
        lines.append("")
        for ticker, filings in sec_filings.items():
            for fl in filings:
                code = fl.get("txn_code", "—")
                val = fl.get("total_value", 0)
                lines.append(
                    f"- **{ticker}** Form {fl.get('form_type','?')}: "
                    f"Code `{code}` — ${val:,.0f} "
                    f"({'10b5-1' if fl.get('is_10b51') else 'discretionary'})"
                )
        lines.append("")

    # Signals
    lines.append(f"## Alerts Fired: {len(signals)}")
    lines.append("")
    if signals:
        for s in signals:
            lines.append(f"- **{s.badge} {s.direction}** (score {s.score:.0f}) — {s.reason}")
    else:
        lines.append("_No contrarian signals met the confluence gate this cycle._")
    lines.append("")

    p.write_text("\n".join(lines), encoding="utf-8")
    log.info("Market brief written → %s", p)
