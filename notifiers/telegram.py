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
    try:
        text = _format_signal(signal)
    except Exception as e:
        log.error("Failed to format signal alert: %s", e)
        return False

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
    trigger_type = getattr(signal, "trigger_type", "SHOCK" if signal.source == "shock" else "CONTRARIAN")
    trigger_badge = f"[{trigger_type}]"

    lines = [
        f"⚡ <b>{badge} {trigger_badge} {esc(signal.direction)}</b>",
        f"Signal Score: <code>{signal.score:.0f}/100</code>",
        f"<b>Trigger Type:</b> <code>{trigger_type}</code>",
        "",
    ]

    m = signal.metrics
    if signal.source in ("crypto", "shock"):
        lines.append("📊 <b>Market Dynamics:</b>")
        if m.get("mark_price") is not None:
            lines.append(f"  • Mark Price: <code>${m['mark_price']:,.2f}</code>")

        # 1h / 4h / 24h price %
        p1 = m.get("price_chg_1h")
        p4 = m.get("price_chg_4h")
        p24 = m.get("price_chg_24h")
        price_parts = []
        if p1 is not None:
            price_parts.append(f"1h: <code>{p1:+.2f}%</code>")
        if p4 is not None:
            price_parts.append(f"4h: <code>{p4:+.2f}%</code>")
        if p24 is not None:
            price_parts.append(f"24h: <code>{p24:+.2f}%</code>")
        if price_parts:
            lines.append(f"  • Price Moves: {' | '.join(price_parts)}")

        # 1h-4h OI %
        oi1 = m.get("oi_delta_1h")
        oi4 = m.get("oi_delta_4h")
        oi_parts = []
        if oi1 is not None:
            oi_parts.append(f"1h: <code>{oi1:+.2f}%</code>")
        if oi4 is not None:
            oi_parts.append(f"4h: <code>{oi4:+.2f}%</code>")
        if oi_parts:
            lines.append(f"  • Open Interest Δ: {' | '.join(oi_parts)}")

        # Funding rate (8h rate & APR)
        fr = m.get("funding_rate")
        apr = m.get("funding_apr")
        if fr is not None and apr is not None:
            lines.append(f"  • Funding Rate: <code>{fr*100:+.4f}% ({apr:+.2f}% APR)</code>")
        elif apr is not None:
            lines.append(f"  • Funding APR: <code>{apr:+.2f}%</code>")

        # L/S ratio with crowding direction
        rls = m.get("retail_ls")
        wls = m.get("whale_ls")
        crowd = m.get("crowding_label") or ""
        if rls is not None:
            crowd_str = f" (<b>{esc(crowd)}</b>)" if crowd and crowd != "Balanced" else ""
            lines.append(f"  • Retail L/S: <code>{rls:.4f}</code>{crowd_str}")
        if wls is not None:
            lines.append(f"  • Whale L/S: <code>{wls:.4f}</code>")

        # Fear & Greed index
        if m.get("fng") is not None:
            lines.append(
                f"  • Fear &amp; Greed: <code>{esc(str(m['fng']))}</code> ({esc(str(m.get('fng_class', '')))})"
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
    lines.append(f"💡 <b>Reason:</b> <i>{esc(signal.reason)}</i>")
    return "\n".join(lines)


# ─── Market Snapshot Report ───


def write_market_brief(
    binance_data: dict[str, dict[str, Any]],
    fng: dict[str, Any] | None,
    sec_filings: dict[str, list],
    signals: list[Signal],
    report_path: str = "reports/latest_brief.md",
    data_source: str = "",
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
        lines.append("## Macro Sentiment")
        lines.append(f"- Fear & Greed Index: **{fng['value']}** ({fng['classification']})")
        if fng.get("prev_value") is not None:
            lines.append(f"- Previous: **{fng['prev_value']}** ({fng.get('prev_classification', '')})")
        lines.append("")

    # Perpetual futures table
    lines.append("## Perpetual Futures & Shock Metrics")
    lines.append("")
    if data_source:
        lines.append(f"_Data source this run: {data_source}_")
        lines.append("")
    lines.append(
        "| Symbol | Mark Price | 1h Price Δ | 4h Price Δ | 24h Price Δ | 1h OI Δ | 4h OI Δ | Funding (8h / APR) | Retail L/S (Crowding) | Whale L/S |"
    )
    lines.append(
        "|--------|-----------|------------|------------|-------------|---------|---------|---------------------|-----------------------|-----------|"
    )

    for sym, d in binance_data.items():
        f = d.get("funding") or {}
        o = d.get("oi") or {}
        r = d.get("ratios") or {}
        sh = d.get("shock") or {}

        p1_val = sh.get("price_chg_1h_pct")
        p1_str = f"{p1_val:+.2f}%" if p1_val is not None else "—"
        p4_val = sh.get("price_chg_4h_pct")
        p4_str = f"{p4_val:+.2f}%" if p4_val is not None else "—"
        p24_val = sh.get("price_chg_24h_pct")
        p24_str = f"{p24_val:+.2f}%" if p24_val is not None else "—"

        oi1_val = sh.get("oi_chg_1h_pct")
        oi1_str = f"{oi1_val:+.2f}%" if oi1_val is not None else "—"
        oi4_val = sh.get("oi_chg_4h_pct") if sh.get("oi_chg_4h_pct") is not None else o.get("oi_delta_4h_pct")
        oi4_str = f"{oi4_val:+.2f}%" if oi4_val is not None else "—"

        fr = f.get("funding_rate") or 0.0
        apr = f.get("annualized_apr") or 0.0
        funding_str = f"{fr*100:+.4f}% / {apr:+.2f}%" if fr else f"{apr:+.2f}% APR"

        rls = r.get("retail_ratio")
        wls = r.get("whale_ratio")
        from signals.signal_engine import crowding_label
        crowd = crowding_label(rls) if rls is not None else "N/A"
        if rls is not None:
            rls_str = f"{rls:.4f} ({crowd})" if crowd not in ("Balanced", "N/A") else f"{rls:.4f}"
        else:
            rls_str = "—"
        wls_str = f"{wls:.4f}" if wls is not None else "—"

        mark_px = f.get("mark_price")
        mark_str = f"${mark_px:,.2f}" if mark_px is not None else "—"

        lines.append(
            f"| {sym} "
            f"| {mark_str} "
            f"| {p1_str} "
            f"| {p4_str} "
            f"| {p24_str} "
            f"| {oi1_str} "
            f"| {oi4_str} "
            f"| {funding_str} "
            f"| {rls_str} "
            f"| {wls_str} |"
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
            ttype = getattr(s, "trigger_type", "SHOCK" if s.source == "shock" else "CONTRARIAN")
            lines.append(f"### ⚡ {s.badge} [{ttype}] {s.direction} (Score: {s.score:.0f}/100)")
            lines.append(f"- **Trigger Type:** {ttype}")
            lines.append(f"- **Exact Reason:** {s.reason}")
            m = s.metrics
            if s.source in ("crypto", "shock"):
                p_parts = []
                for k, lbl in [("price_chg_1h", "1h"), ("price_chg_4h", "4h"), ("price_chg_24h", "24h")]:
                    if m.get(k) is not None:
                        p_parts.append(f"{lbl} Δ: {m[k]:+.2f}%")
                if p_parts:
                    lines.append(f"- **Price Moves:** {' | '.join(p_parts)}")
                oi_parts = []
                for k, lbl in [("oi_delta_1h", "1h"), ("oi_delta_4h", "4h")]:
                    if m.get(k) is not None:
                        oi_parts.append(f"{lbl} Δ: {m[k]:+.2f}%")
                if oi_parts:
                    lines.append(f"- **Open Interest Δ:** {' | '.join(oi_parts)}")
                if m.get("funding_rate") is not None and m.get("funding_apr") is not None:
                    lines.append(f"- **Funding Rate:** {m['funding_rate']*100:+.4f}% ({m['funding_apr']:+.2f}% APR)")
                if m.get("retail_ls") is not None:
                    lines.append(f"- **Retail L/S:** {m['retail_ls']:.4f} ({m.get('crowding_label', 'Balanced')})")
                if m.get("fng") is not None:
                    lines.append(f"- **Fear & Greed:** {m['fng']} ({m.get('fng_class', '')})")
            lines.append("")
    else:
        lines.append("_No shock or contrarian signals fired this cycle._")
    lines.append("")

    p.write_text("\n".join(lines), encoding="utf-8")
    log.info("Market brief written → %s", p)
