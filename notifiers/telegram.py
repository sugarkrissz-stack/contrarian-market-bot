"""Telegram Bot API notifier + local markdown fallback."""

from __future__ import annotations

import html
import logging
import os
import re
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


def _error_text(resp: requests.Response) -> str:
    """Telegram's own explanation for a failed request (the body is lost by raise_for_status)."""
    try:
        return str(resp.json().get("description") or resp.text[:200])
    except ValueError:
        return resp.text[:200]


def _to_plain(text: str, parse_mode: str | None) -> str:
    """Strip markup so a message can be re-sent as plain text."""
    if parse_mode == "HTML":
        return html.unescape(re.sub(r"<[^>]+>", "", text))
    return text.replace("*", "").replace("`", "")


def _post_message(text: str, parse_mode: str | None, timeout: int = 10) -> bool:
    """POST one message to Telegram.  Returns True only if Telegram accepted it.

    Logs Telegram's error text on failure.  If Telegram rejects the markup
    ("can't parse entities"), the message is re-sent once as plain text so an
    alert is never silently lost because of a stray `_`, `*` or `<`.
    """
    token, chat_id = _get_creds()
    if not token or not chat_id:
        log.warning("Telegram credentials missing — message not sent")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        # Don't log str(e): it can contain the request URL, which includes the bot token.
        log.error("Telegram request failed: %s", type(e).__name__)
        return False

    if resp.ok:
        return True

    desc = _error_text(resp)
    log.error("Telegram rejected message (HTTP %s): %s", resp.status_code, desc)
    if resp.status_code == 400 and parse_mode and "parse entities" in desc.lower():
        log.warning("Retrying as plain text")
        return _post_message(_to_plain(text, parse_mode), None, timeout)
    return False


def send_alert(signal: Signal, dry_run: bool = False) -> bool:
    """Send a formatted Telegram alert.  Returns True only if it was delivered."""
    text = _format_signal(signal)

    if dry_run:
        log.info("[DRY-RUN] Would send Telegram alert:\n%s", text)
        return True

    if _post_message(text, "HTML"):
        log.info("Telegram alert sent for %s %s", signal.symbol, signal.direction)
        return True
    return False


def send_test_alert() -> bool:
    """Send a test ping to verify Telegram connectivity."""
    text = "🤖 <b>Contrarian Bot — Test Alert</b>\nBot is online and connected."
    ok = _post_message(text, "HTML")
    if ok:
        log.info("Test alert sent successfully")
    else:
        log.error("Test alert failed")
    return ok


def send_daily_open_brief(brief_text: str, dry_run: bool = False) -> bool:
    """Send guaranteed US Market Open Daily Brief to Telegram or log in dry-run."""
    if dry_run:
        log.info("[DRY-RUN] Would send Daily Open Brief to Telegram:\n%s", brief_text)
        return True

    if _post_message(brief_text, "Markdown", timeout=12):
        log.info("Daily Open Brief sent successfully to Telegram")
        return True
    log.error("Daily Open Brief send failed")
    return False


def _format_signal(signal: Signal) -> str:
    """Build the alert message as Telegram HTML.

    HTML (with html.escape on every dynamic string) is used instead of legacy
    Markdown because signal reasons contain `_` and `<`, which break Markdown
    parsing and made Telegram reject the whole alert with HTTP 400.
    """
    esc = html.escape
    badge = esc(signal.badge or f"[{signal.symbol}]")
    lines = [
        f"⚡ <b>{badge} {esc(signal.direction)}</b>",
        f"Signal Score: <code>{signal.score:.0f}/100</code>",
        "",
    ]

    m = signal.metrics
    if signal.source == "crypto":
        lines.append("📊 <b>Metrics:</b>")
        if m.get("funding_apr") is not None:
            lines.append(f"  Funding APR: <code>{m['funding_apr']:+.2f}%</code>")
        if m.get("basis_pct") is not None:
            lines.append(f"  Basis: <code>{m['basis_pct']:+.4f}%</code>")
        if m.get("retail_ls") is not None:
            lines.append(f"  Retail L/S: <code>{m['retail_ls']:.4f}</code>")
        if m.get("whale_ls") is not None:
            lines.append(f"  Whale L/S: <code>{m['whale_ls']:.4f}</code>")
        if m.get("oi_delta_4h") is not None:
            lines.append(f"  4h OI Δ: <code>{m['oi_delta_4h']:+.2f}%</code>")
        if m.get("fng") is not None:
            lines.append(
                f"  Fear &amp; Greed: <code>{esc(str(m['fng']))}</code> ({esc(str(m.get('fng_class', '')))})"
            )
    elif signal.source == "sec":
        lines.append("📋 <b>SEC Filing:</b>")
        if m.get("txn_code"):
            lines.append(f"  Code: <code>{esc(str(m['txn_code']))}</code>")
        if m.get("shares"):
            lines.append(f"  Shares: <code>{m['shares']:,.0f}</code>")
        if m.get("price"):
            lines.append(f"  Price: <code>${m['price']:,.2f}</code>")
        if m.get("total_value"):
            lines.append(f"  Value: <code>${m['total_value']:,.0f}</code>")
        lines.append(f"  10b5-1: <code>{'Yes' if m.get('is_10b51') else 'No'}</code>")

    lines.append("")
    lines.append(f"💡 <i>{esc(signal.reason)}</i>")
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
