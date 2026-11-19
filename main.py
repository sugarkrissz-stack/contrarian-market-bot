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
    evaluate_market_shock,
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

    bl_cfg = cfg.get("basis_baseline", {})
    for sym, data in binance_data.items():
        # Fetch 1H candles & OI history for accurate shock metrics
        shock_data = market_shock.fetch_recent_market_shock_data(sym)
        data["shock"] = shock_data

        # 4a. Market Shock / Liquidation Flush (1-of-1 Immediate Rule)
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
            candidates.append(shock_sig)
            log.info(
                "⚡ SHOCK SIGNAL: %s %s %s (score %.0f) — %s",
                shock_sig.badge, sym, shock_sig.direction, shock_sig.score, shock_sig.reason,
            )

        # 4b. Standard Contrarian Signals (2-of-3 Confluence Rule)
        baseline = db.basis_baseline(
            sym, days=bl_cfg.get("days", 7), min_samples=bl_cfg.get("min_samples", 24)
        )
        signal = score_crypto(
            symbol=sym,
            funding=data.get("funding"),
            oi=data.get("oi"),
            ratios=data.get("ratios"),
            fng=fng,
            cfg=cfg,
            basis_baseline=baseline,
            shock_data=shock_data,
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
    if len(candidates) < n_before:
        log.info("De-duplicated %d signal(s) on the same underlying asset", n_before - len(candidates))
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
    write_market_brief(binance_data, fng, sec_results, fired_signals, report_path, data_source)

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


def run_backtest_30d(cfg: dict) -> None:
    """Simulate Market Shock rules over the past 30 days using OKX 1H candles & OI history."""
    import requests
    log.info("━━━ Starting 30-Day Market Shock Backtest (BTC-USDT-SWAP) ━━━")
    candles, oi_records = market_shock.fetch_30d_history(inst_id="BTC-USDT-SWAP", target_bars=720)
    if not candles:
        log.error("Failed to fetch historical candles for backtest")
        return

    # Fetch 30-day Fear & Greed history for condition c
    fng_history: dict[str, int] = {}
    try:
        fng_res = requests.get("https://api.alternative.me/fng/?limit=35", timeout=10).json()
        for item in fng_res.get("data", []):
            dt_str = datetime.fromtimestamp(int(item["timestamp"]), timezone.utc).strftime("%Y-%m-%d")
            fng_history[dt_str] = int(item["value"])
    except Exception as e:
        log.warning("Could not fetch F&G history: %s", e)

    # Index OI by timestamp: ts (int ms) -> (contracts, usd)
    oi_by_ts: dict[int, tuple[float, float]] = {}
    for r in oi_records:
        ts = int(r[0])
        oi_by_ts[ts] = (float(r[1]), float(r[3]))

    shock_cfg = cfg.get("market_shock", {})
    cooldown_hours = shock_cfg.get("cooldown_hours", 3)
    cooldown_ms = cooldown_hours * 3600 * 1000

    th_p1 = shock_cfg.get("price_move_1h_pct", 3.5)
    th_p4 = shock_cfg.get("price_move_4h_pct", 4.5)
    th_p24 = shock_cfg.get("price_move_24h_pct", 5.0)
    th_oi = -abs(shock_cfg.get("oi_flush_drop_pct", 5.0))
    th_fg = shock_cfg.get("capitulation_fg_max", 15)
    th_cap_p24 = -abs(shock_cfg.get("capitulation_24h_drop_pct", 4.5))

    alerts: list[dict[str, Any]] = []
    last_alert_ts = -cooldown_ms

    for i in range(24, len(candles)):
        c_curr = candles[i]
        ts_curr = int(c_curr[0])
        px_curr = float(c_curr[4])

        px_1h = float(candles[i - 1][4])
        px_4h = float(candles[i - 4][4])
        px_24h = float(candles[i - 24][4])

        p1 = ((px_curr - px_1h) / px_1h * 100) if px_1h else 0.0
        p4 = ((px_curr - px_4h) / px_4h * 100) if px_4h else 0.0
        p24 = ((px_curr - px_24h) / px_24h * 100) if px_24h else 0.0

        ts_1h = ts_curr - 3600 * 1000
        ts_4h = ts_curr - 4 * 3600 * 1000
        curr_oi_c, curr_oi_usd = oi_by_ts.get(ts_curr, (0.0, 0.0))
        oi_1h_c, oi_1h_usd = oi_by_ts.get(ts_1h, (0.0, 0.0))
        oi_4h_c, oi_4h_usd = oi_by_ts.get(ts_4h, (0.0, 0.0))

        oi1 = ((curr_oi_c - oi_1h_c) / oi_1h_c * 100) if oi_1h_c > 0 else 0.0
        oi4 = ((curr_oi_c - oi_4h_c) / oi_4h_c * 100) if oi_4h_c > 0 else 0.0
        oi_usd1 = ((curr_oi_usd - oi_1h_usd) / oi_1h_usd * 100) if oi_1h_usd > 0 else 0.0
        oi_usd4 = ((curr_oi_usd - oi_4h_usd) / oi_4h_usd * 100) if oi_4h_usd > 0 else 0.0

        date_str = datetime.fromtimestamp(ts_curr / 1000, timezone.utc).strftime("%Y-%m-%d")
        fng_val = fng_history.get(date_str)

        reasons = []
        if abs(p1) >= th_p1:
            reasons.append(f"1h move {p1:+.2f}% (|Δ|>={th_p1}%)")
        if abs(p4) >= th_p4:
            reasons.append(f"4h move {p4:+.2f}% (|Δ|>={th_p4}%)")
        if abs(p24) >= th_p24:
            reasons.append(f"24h move {p24:+.2f}% (|Δ|>={th_p24}%)")

        worst_oi = min(oi1, oi4, oi_usd1, oi_usd4)
        if oi1 <= th_oi or oi4 <= th_oi or oi_usd1 <= th_oi or oi_usd4 <= th_oi:
            reasons.append(f"OI flush {worst_oi:+.2f}% (<= {th_oi:.1f}%)")

        if fng_val is not None and fng_val < th_fg and p24 <= th_cap_p24:
            reasons.append(f"Capitulation (F&G={fng_val} < {th_fg}, 24h={p24:+.2f}%)")

        if not reasons:
            continue

        # Respect 3-hour cooldown
        if ts_curr - last_alert_ts < cooldown_ms:
            continue

        last_alert_ts = ts_curr
        dt_utc = datetime.fromtimestamp(ts_curr / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        alerts.append({
            "timestamp": dt_utc,
            "price": px_curr,
            "p1": p1,
            "p4": p4,
            "p24": p24,
            "oi1": oi1,
            "oi4": oi4,
            "fng": fng_val if fng_val is not None else "N/A",
            "reason": "; ".join(reasons),
        })

    # Summary table
    print("\n" + "═" * 110)
    print("                      30-DAY MARKET SHOCK & LIQUIDATION FLUSH BACKTEST")
    print(f"                      Instrument: BTC-USDT-SWAP | Total Bars Analyzed: {len(candles)}")
    print(f"                      Rules: |1h|>=3.5%, |4h|>=4.5%, |24h|>=5.0%, OI Drop<=-5.0%, Capitulation")
    print(f"                      Cooldown: 3 Hours")
    print("═" * 110)
    print(f"Total Market Shock Alerts Triggered Over 30 Days: {len(alerts)}\n")

    if alerts:
        print(f"{'Timestamp (UTC)':<18} | {'Price':<9} | {'1h Price':<8} | {'4h Price':<8} | {'24h Price':<9} | {'1h OI Δ':<8} | {'4h OI Δ':<8} | {'F&G':<4} | {'Reason'}")
        print("-" * 110)
        for a in alerts:
            print(
                f"{a['timestamp']:<18} | "
                f"${a['price']:<8,.0f} | "
                f"{a['p1']:>+7.2f}% | "
                f"{a['p4']:>+7.2f}% | "
                f"{a['p24']:>+8.2f}% | "
                f"{a['oi1']:>+7.2f}% | "
                f"{a['oi4']:>+7.2f}% | "
                f"{str(a['fng']):<4} | "
                f"{a['reason']}"
            )
        print("═" * 110 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Contrarian Market Intelligence Bot")
    parser.add_argument("--dry-run", action="store_true", help="Collect & score without sending Telegram alerts")
    parser.add_argument("--test-alert", action="store_true", help="Send a test Telegram ping and exit")
    parser.add_argument("--daily-open-brief", action="store_true", help="Generate and send US Market Open Brief (09:30 ET)")
    parser.add_argument("--backtest-30d", action="store_true", help="Simulate Market Shock rules over past 30 days from OKX")
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

    if args.backtest_30d:
        run_backtest_30d(cfg)
        return

    if args.daily_open_brief:
        run_daily_open_brief(cfg, dry_run=args.dry_run)
        return

    run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
