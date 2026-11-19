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
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

import db
from collectors import binance_futures, sentiment, sec_edgar, macro_open, market_shock
from signals.signal_engine import (
    score_crypto, filter_form4, passes_cooldown, dedupe_signals, Signal,
    evaluate_market_shock, attach_shock_context, shock_mode,
)
from notifiers.telegram import send_alert, send_test_alert, send_daily_open_brief, write_market_brief
from engine.daily_brief import build_daily_open_brief

# ─── Logging ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

OPEN_BRIEF_MARKER = Path("reports/open_brief_sent.txt")


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
    if not fng:
        cached_fng = db.latest_fng()
        if cached_fng:
            log.info(
                "sentiment.fetch() returned None — using cached Fear & Greed from DB: %s (%s)",
                cached_fng.get("value"), cached_fng.get("classification"),
            )
            fng = cached_fng

    # ── 2. Collect Perpetual Futures (Binance, OKX fallback) ──
    log.info("━━━ Collecting Perpetual Futures Data ━━━")
    all_symbols = cfg.get("symbols", {}).get("primary", []) + cfg.get("symbols", {}).get("secondary", [])
    usdc_fb = cfg.get("usdc_to_usdt_fallback", {})
    binance_data = binance_futures.collect_all(all_symbols, usdc_fb)
    data_source = binance_futures.data_source()
    log.info("Futures data source this run: %s", data_source)

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

    # ── 4. Score Market Shock & Contrarian Signals ──
    log.info("━━━ Scoring Market Shock & Contrarian Signals ━━━")
    badges = cfg.get("priority_badges", {})
    candidates: list[Signal] = []
    shock_signals: list[Signal] = []
    mode = shock_mode(cfg)

    bl_cfg = cfg.get("basis_baseline", {})
    rb_cfg = cfg.get("retail_baseline", {})
    for sym, data in binance_data.items():
        # Fetch 1H candles & OI history for accurate shock metrics
        shock_data = market_shock.fetch_recent_market_shock_data(sym)
        data["shock"] = shock_data

        # 4a. Market Shock / Liquidation Flush. Context by default; own alert only in mode "alert".
        shock_sig = None
        if mode != "off":
            shock_sig = evaluate_market_shock(
                symbol=sym,
                shock_data=shock_data,
                funding=data.get("funding"),
                ratios=data.get("ratios"),
                fng=fng,
                cfg=cfg,
            )
        if shock_sig:
            shock_sig.badge = resolve_badge(sym, badges)
            shock_signals.append(shock_sig)
            if mode == "alert":
                candidates.append(shock_sig)
            log.info(
                "⚡ SHOCK (%s): %s %s %s (score %.0f) — %s",
                mode, shock_sig.badge, sym, shock_sig.direction, shock_sig.score, shock_sig.reason,
            )

        # 4b. Standard Contrarian Signals (2-of-3 Confluence Rule)
        baseline = db.basis_baseline(
            sym, days=bl_cfg.get("days", 7), min_samples=bl_cfg.get("min_samples", 24)
        )
        retail_base = db.retail_baseline(
            sym, days=rb_cfg.get("days", 7), min_samples=rb_cfg.get("min_samples", 24)
        )
        data["retail_baseline"] = retail_base
        signal = score_crypto(
            symbol=sym,
            funding=data.get("funding"),
            oi=data.get("oi"),
            ratios=data.get("ratios"),
            fng=fng,
            cfg=cfg,
            basis_baseline=baseline,
            shock_data=shock_data,
            retail_baseline=retail_base,
        )
        if signal:
            signal.badge = resolve_badge(sym, badges)
            candidates.append(signal)
            log.info("🔔 CONTRARIAN SIGNAL: %s %s %s (score %.0f)", signal.badge, sym, signal.direction, signal.score)
        else:
            log.info("— %s: no contrarian confluence", sym)

    # ── 5. Score SEC Filings ──
    for ticker, filings in sec_results.items():
        for fl in filings:
            if fl.get("form_type") != "4":
                continue
            signal = filter_form4(fl, cfg)
            if signal:
                signal.badge = badges.get("SEC", "[SEC]")
                candidates.append(signal)

    # ── 6. Notify ──
    # An alert only counts toward the daily cap / cooldown once Telegram has
    # actually accepted it.  Cap and cooldown are re-checked right before each
    # send so alerts already delivered earlier in this run are counted.
    log.info("━━━ Notifications ━━━")
    fired_signals: list[Signal] = []
    # One alert per underlying asset and direction (BTCUSDT + BTCUSDC are the same idea).
    n_before = len(candidates)
    candidates = dedupe_signals(candidates)
    shock_signals = dedupe_signals(shock_signals)
    if len(candidates) < n_before:
        log.info("De-duplicated %d signal(s) on the same underlying asset", n_before - len(candidates))
    enriched = attach_shock_context(candidates, shock_signals)
    if enriched:
        log.info("Attached shock context to %d contrarian alert(s)", enriched)
    # Contrarian / SEC alerts first, then (mode "alert" only) shock alerts, so a chase-the-move
    # shock can never use up the daily budget before a swing setup gets its turn.
    candidates.sort(key=lambda sig: (sig.source == "shock", -sig.score))
    for sig in candidates:
        if not passes_cooldown(sig, cfg):
            log.info("⏳ Cooldown/cap: %s %s %s", sig.source, sig.symbol, sig.direction)
            continue
        if not send_alert(sig, dry_run=dry_run):
            log.error(
                "Alert NOT delivered — not recorded, will retry next run: %s %s %s",
                sig.source, sig.symbol, sig.direction,
            )
            continue
        fired_signals.append(sig)
        if not dry_run:
            db.record_alert(sig.source, sig.symbol, sig.direction, sig.score)
        log.info("🔔 SIGNAL sent: %s %s %s (score %.0f)", sig.badge, sig.symbol, sig.direction, sig.score)

    # ── 7. Write Market Brief ──
    report_path = cfg.get("reports", {}).get("path", "reports/latest_brief.md")
    write_market_brief(
        binance_data, fng, sec_results, fired_signals, report_path, data_source,
        shock_context=[sh for sh in shock_signals if sh not in fired_signals],
    )

    # ── 8. Database Maintenance ──
    db.prune_old_records(days=14)

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
    if not fng:
        cached_fng = db.latest_fng()
        if cached_fng:
            log.info(
                "sentiment.fetch() returned None — using cached Fear & Greed from DB: %s (%s)",
                cached_fng.get("value"), cached_fng.get("classification"),
            )
            fng = cached_fng

    log.info("• Fetching Crypto Futures Positioning...")
    all_symbols = cfg.get("symbols", {}).get("primary", []) + cfg.get("symbols", {}).get("secondary", [])
    usdc_fb = cfg.get("usdc_to_usdt_fallback", {})
    binance_data = binance_futures.collect_all(all_symbols, usdc_fb)

    brief_text = build_daily_open_brief(
        macro_data, binance_data, fng, data_source=binance_futures.data_source()
    )

    log.info("━━━ Dispatching US Market Open Brief ━━━")
    delivered = send_daily_open_brief(brief_text, dry_run=dry_run)

    open_brief_path = Path("reports/latest_open_brief.md")
    open_brief_path.parent.mkdir(parents=True, exist_ok=True)
    open_brief_path.write_text(brief_text, encoding="utf-8")
    log.info("Daily Open Brief saved → %s", open_brief_path)

    # The workflow reads this marker so the brief is sent once per New York day,
    # even when GitHub's scheduler starts the job late.
    if delivered and not dry_run:
        today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        OPEN_BRIEF_MARKER.write_text(today_et + "\n", encoding="utf-8")
        log.info("Open brief marked as sent for %s (ET)", today_et)

    # Database Maintenance
    db.prune_old_records(days=14)
    log.info("✅ US Market Open Brief complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Contrarian Market Intelligence Bot")
    parser.add_argument("--dry-run", action="store_true", help="Collect & score without sending Telegram alerts")
    parser.add_argument("--test-alert", action="store_true", help="Send a test Telegram ping and exit")
    parser.add_argument("--daily-open-brief", action="store_true", help="Generate and send US Market Open Brief (09:30 ET)")
    parser.add_argument("--backtest", action="store_true", help="Event-study backtest with forward returns (see backtest.py)")
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

    if args.backtest:
        import backtest
        backtest.main(cfg)
        return

    if args.daily_open_brief:
        run_daily_open_brief(cfg, dry_run=args.dry_run)
        return

    run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
