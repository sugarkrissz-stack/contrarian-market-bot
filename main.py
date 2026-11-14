"""CLI orchestrator for the Contrarian Market Intelligence Bot.

Usage:
    python main.py                  # standard scheduled run
    python main.py --dry-run        # collect live data, evaluate signals, NO Telegram
    python main.py --test-alert     # send a Telegram test ping then exit
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

import db
from collectors import binance_futures, sentiment, sec_edgar, macro_open
from signals.signal_engine import score_crypto, filter_form4, passes_cooldown, Signal
from notifiers.telegram import send_alert, send_test_alert, send_daily_open_brief, write_market_brief
from engine.daily_brief import build_daily_open_brief

# ─── Logging ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_badge(symbol: str, badges: dict[str, str]) -> str:
    if "BTC" in symbol.upper():
        return badges.get("BTC", "[P1 - BTC]")
    if "ETH" in symbol.upper():
        return badges.get("ETH", "[P2 - ETH]")
    return f"[{symbol}]"


def run(cfg: dict, dry_run: bool = False) -> None:
    """Full collection → scoring → notification pipeline."""
    db_path = cfg.get("database", {}).get("path", "data/market_intel.db")
    db.init(db_path)

    # ── 1. Collect Fear & Greed ──
    log.info("━━━ Collecting Fear & Greed ━━━")
    fng = sentiment.fetch()

    # ── 2. Collect Binance Futures ──
    log.info("━━━ Collecting Binance Futures ━━━")
    all_symbols = cfg.get("symbols", {}).get("primary", []) + cfg.get("symbols", {}).get("secondary", [])
    usdc_fb = cfg.get("usdc_to_usdt_fallback", {})
    binance_data = binance_futures.collect_all(all_symbols, usdc_fb)

    # ── 3. Collect SEC EDGAR ──
    log.info("━━━ Collecting SEC EDGAR ━━━")
    ua = os.getenv("SEC_USER_AGENT", "SampleResearchBot/1.0 (contact@example.com)")
    rate_rps = cfg.get("sec_edgar", {}).get("rate_limit_rps", 5)
    lookback_days = cfg.get("sec_edgar", {}).get("lookback_days", 14)
    sec_results: dict[str, list] = {}
    for entry in cfg.get("sec_edgar", {}).get("watchlist", []):
        ticker = entry["ticker"]
        cik = entry["cik"]
        filings = sec_edgar.fetch_filings(cik, ticker, ua, rate_rps, lookback_days)
        sec_results[ticker] = filings
        log.info("SEC %s: %d new filing record(s)", ticker, len(filings))

    # ── 4. Score Crypto Signals ──
    log.info("━━━ Scoring Contrarian Signals ━━━")
    badges = cfg.get("priority_badges", {})
    fired_signals: list[Signal] = []

    for sym, data in binance_data.items():
        signal = score_crypto(
            symbol=sym,
            funding=data.get("funding"),
            oi=data.get("oi"),
            ratios=data.get("ratios"),
            fng=fng,
            cfg=cfg,
        )
        if signal:
            signal.badge = resolve_badge(sym, badges)
            if passes_cooldown(signal, cfg):
                fired_signals.append(signal)
                db.record_alert(signal.source, signal.symbol, signal.direction, signal.score)
                log.info("🔔 SIGNAL: %s %s %s (score %.0f)", signal.badge, sym, signal.direction, signal.score)
            else:
                log.info("⏳ Cooldown: %s %s", sym, signal.direction)
        else:
            log.info("— %s: no confluence", sym)

    # ── 5. Score SEC Filings ──
    for ticker, filings in sec_results.items():
        for fl in filings:
            if fl.get("form_type") != "4":
                continue
            signal = filter_form4(fl, cfg)
            if signal:
                signal.badge = badges.get("SEC", "[SEC]")
                if passes_cooldown(signal, cfg):
                    fired_signals.append(signal)
                    db.record_alert(signal.source, signal.symbol, signal.direction, signal.score)
                    log.info("🔔 SEC SIGNAL: %s %s $%s", ticker, signal.direction, fl.get("total_value", 0))

    # ── 6. Notify ──
    log.info("━━━ Notifications ━━━")
    for sig in fired_signals:
        send_alert(sig, dry_run=dry_run)

    # ── 7. Write Market Brief ──
    report_path = cfg.get("reports", {}).get("path", "reports/latest_brief.md")
    write_market_brief(binance_data, fng, sec_results, fired_signals, report_path)

    log.info(
        "✅ Run complete — %d signal(s) fired, %d symbol(s) scanned, %d SEC ticker(s)",
        len(fired_signals), len(binance_data), len(sec_results),
    )


def run_daily_open_brief(cfg: dict, dry_run: bool = False) -> None:
    """Generate and send guaranteed US Market Open Daily Brief."""
    db_path = cfg.get("database", {}).get("path", "data/market_intel.db")
    db.init(db_path)

    log.info("━━━ Collecting US Market Open Data ━━━")
    log.info("• Fetching Macro Pre-Market Assets...")
    macro_data = macro_open.fetch_macro_open()

    log.info("• Fetching Fear & Greed Index...")
    fng = sentiment.fetch()

    log.info("• Fetching Crypto Futures Positioning...")
    all_symbols = cfg.get("symbols", {}).get("primary", []) + cfg.get("symbols", {}).get("secondary", [])
    usdc_fb = cfg.get("usdc_to_usdt_fallback", {})
    binance_data = binance_futures.collect_all(all_symbols, usdc_fb)

    brief_text = build_daily_open_brief(macro_data, binance_data, fng)

    log.info("━━━ Dispatching US Market Open Brief ━━━")
    send_daily_open_brief(brief_text, dry_run=dry_run)

    open_brief_path = Path("reports/latest_open_brief.md")
    open_brief_path.parent.mkdir(parents=True, exist_ok=True)
    open_brief_path.write_text(brief_text, encoding="utf-8")
    log.info("Daily Open Brief saved → %s", open_brief_path)
    log.info("✅ US Market Open Brief complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Contrarian Market Intelligence Bot")
    parser.add_argument("--dry-run", action="store_true", help="Collect & score without sending Telegram alerts")
    parser.add_argument("--test-alert", action="store_true", help="Send a test Telegram ping and exit")
    parser.add_argument("--daily-open-brief", action="store_true", help="Generate and send US Market Open Brief (09:30 ET)")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    # Load .env
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)

    cfg = load_config(args.config)

    if args.test_alert:
        ok = send_test_alert()
        sys.exit(0 if ok else 1)

    if args.daily_open_brief:
        run_daily_open_brief(cfg, dry_run=args.dry_run)
        return

    run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
