"""Event-study backtest: what did price do AFTER each trigger?

The old 30-day "backtest" only counted how often an alert would have fired, which cannot say
whether the alert was any good.  This module measures outcomes instead, for the setups the bot
relies on, always against an unconditional baseline (what the same trade does on a random day):

  A. Fear & Greed extremes on daily candles (years of history)
       - F&G < 20  -> LONG,  F&G > 80 -> SHORT
       - "setup then trigger": F&G < 20 recently AND price closes above the previous day's high
  B. Market-shock moves on 1H candles (~90 days): is a sharp dump/pump a fade or a continuation?
  C. Funding dislocations (OKX keeps ~3 months of funding history)

For every event set it reports: sample size, win rate, mean/median forward return, typical
adverse excursion (how far price went against the trade first) and how often a stop of
1% / 2% / 3% / 5% would have been hit -- the number that matters for "very small invalidation".

Run:   python backtest.py            (or: python main.py --backtest)
Needs the OKX and alternative.me public APIs (works from GitHub Actions, not from every network).
Output: reports/backtest.md plus stdout.
"""

from __future__ import annotations

import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("backtest")

# A candle is (ts_ms, open, high, low, close)
Candle = tuple[int, float, float, float, float]

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
FUNDING_APR_FACTOR = 3 * 365 * 100  # 8h rate -> APR in percent

THIN_SAMPLE = 20  # below this the numbers are anecdotes, not statistics


# ─────────────────────────── pure statistics ───────────────────────────


def dedupe_events(indices: list[int], min_gap_bars: int) -> list[int]:
    """Keep the first event of each episode; skip events closer than `min_gap_bars` to the last kept."""
    kept: list[int] = []
    for i in sorted(indices):
        if not kept or i - kept[-1] >= min_gap_bars:
            kept.append(i)
    return kept


def trade_outcome(candles: list[Candle], i: int, horizon: int, side: str) -> dict[str, float] | None:
    """Outcome of entering at the close of bar `i` and holding `horizon` bars.

    `side` is "long" or "short".  Returns None if the horizon runs past the data.
    ret / adverse / favorable are in percent, from the trade's point of view.
    """
    if i + horizon >= len(candles):
        return None
    entry = candles[i][4]
    if entry <= 0:
        return None
    window = candles[i + 1 : i + horizon + 1]
    lo = min(c[3] for c in window)
    hi = max(c[2] for c in window)
    exit_px = window[-1][4]
    if side == "long":
        ret = (exit_px / entry - 1) * 100
        adverse = max(0.0, (entry - lo) / entry * 100)
        favorable = max(0.0, (hi - entry) / entry * 100)
    else:
        ret = (1 - exit_px / entry) * 100
        adverse = max(0.0, (hi - entry) / entry * 100)
        favorable = max(0.0, (entry - lo) / entry * 100)
    return {"ret": ret, "adverse": adverse, "favorable": favorable}


def summarize(
    candles: list[Candle],
    indices: list[int],
    horizon: int,
    side: str,
    stops: list[float],
) -> dict[str, Any] | None:
    """Aggregate trade_outcome over many entries. None if no entry has a full horizon."""
    outs = [o for i in indices if (o := trade_outcome(candles, i, horizon, side)) is not None]
    if not outs:
        return None
    rets = [o["ret"] for o in outs]
    adv = [o["adverse"] for o in outs]
    n = len(outs)
    return {
        "n": n,
        "win_pct": 100 * sum(r > 0 for r in rets) / n,
        "mean_ret": statistics.fmean(rets),
        "median_ret": statistics.median(rets),
        "p10_ret": sorted(rets)[int(0.1 * (n - 1))],
        "median_adverse": statistics.median(adv),
        "stop_hit": {s: 100 * sum(a >= s for a in adv) / n for s in stops},
        # winner that never touched the stop: what a tight-stop swing trader actually keeps
        "clean_win": {
            s: 100 * sum(1 for o in outs if o["ret"] > 0 and o["adverse"] < s) / n for s in stops
        },
    }


def structure_stop_stats(
    candles: list[Candle], indices: list[int], horizon: int, side: str = "long"
) -> dict[str, float] | None:
    """Stop placed just beyond the trigger bar's own extreme (low for longs).

    Returns median risk % (entry to that stop), stop-hit %, and the mean R-multiple
    (return / risk) over trades that have a full horizon.
    """
    risks: list[float] = []
    rs: list[float] = []
    hit = 0
    for i in indices:
        o = trade_outcome(candles, i, horizon, side)
        if o is None:
            continue
        entry = candles[i][4]
        stop_px = candles[i][3] if side == "long" else candles[i][2]
        risk = abs(entry - stop_px) / entry * 100
        if risk < 0.05:  # degenerate bar, skip rather than divide by ~0
            continue
        risks.append(risk)
        stopped = o["adverse"] >= risk
        hit += stopped
        rs.append(-1.0 if stopped else o["ret"] / risk)
    if not risks:
        return None
    return {
        "n": len(risks),
        "median_risk": statistics.median(risks),
        "stop_hit_pct": 100 * hit / len(risks),
        "mean_r": statistics.fmean(rs),
    }


# ─────────────────────────── event detection ───────────────────────────


def fng_events(
    candles: list[Candle], fng_by_day: dict[str, int], low: int = 20, high: int = 80
) -> tuple[list[int], list[int]]:
    """Indices of daily bars where Fear & Greed was < low (long) / > high (short)."""
    longs: list[int] = []
    shorts: list[int] = []
    for i, c in enumerate(candles):
        day = datetime.fromtimestamp(c[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
        v = fng_by_day.get(day)
        if v is None:
            continue
        if v < low:
            longs.append(i)
        elif v > high:
            shorts.append(i)
    return longs, shorts


def setup_then_trigger(
    candles: list[Candle], fear_idx: list[int], lookback: int = 5
) -> list[int]:
    """Bars that close above the previous bar's high within `lookback` bars after a fear day."""
    fear = set(fear_idx)
    out: list[int] = []
    for i in range(1, len(candles)):
        if not any((i - k) in fear for k in range(0, lookback + 1)):
            continue
        if candles[i][4] > candles[i - 1][2]:
            out.append(i)
    return out


def shock_events(
    candles: list[Candle],
    th_1h: float = 3.5,
    th_4h: float = 4.5,
    th_24h: float = 5.0,
) -> tuple[list[int], list[int]]:
    """Indices of hourly bars with a sharp price move: (dumps, pumps)."""
    dumps: list[int] = []
    pumps: list[int] = []
    for i in range(24, len(candles)):
        c = candles[i][4]
        p1 = (c / candles[i - 1][4] - 1) * 100
        p4 = (c / candles[i - 4][4] - 1) * 100
        p24 = (c / candles[i - 24][4] - 1) * 100
        move = None
        if abs(p1) >= th_1h:
            move = p1
        elif abs(p4) >= th_4h:
            move = p4
        elif abs(p24) >= th_24h:
            move = p24
        if move is None:
            continue
        (dumps if move < 0 else pumps).append(i)
    return dumps, pumps


def oi_flush_events(
    candles: list[Candle], oi_by_ts: dict[int, float], th_drop: float = 5.0
) -> list[int]:
    """Hourly bars where OI (contracts) fell >= th_drop% over 1h or 4h."""
    out: list[int] = []
    for i in range(4, len(candles)):
        now = oi_by_ts.get(candles[i][0])
        if not now:
            continue
        drops = []
        for back in (1, 4):
            prev = oi_by_ts.get(candles[i - back][0])
            if prev and prev > 0:
                drops.append((now - prev) / prev * 100)
        if drops and min(drops) <= -th_drop:
            out.append(i)
    return out


def funding_events(
    candles: list[Candle],
    funding: list[tuple[int, float]],
    apr_low: float = -8.0,
    apr_high: float = 27.375,
) -> tuple[list[int], list[int]]:
    """Map 8h funding settlements to the hourly bar that closes at settlement time."""
    by_ts = {c[0]: i for i, c in enumerate(candles)}
    longs: list[int] = []
    shorts: list[int] = []
    for ft, rate in funding:
        i = by_ts.get(ft - HOUR_MS)
        if i is None:
            continue
        apr = rate * FUNDING_APR_FACTOR
        if apr <= apr_low:
            longs.append(i)
        elif apr >= apr_high:
            shorts.append(i)
    return longs, shorts


# ─────────────────────────── data fetching ───────────────────────────

GetFn = Callable[[str, dict | None], Any]


def _default_get() -> GetFn:
    from collectors.market_shock import _okx_get

    return lambda endpoint, params=None: _okx_get(endpoint, params)


def fetch_candles(
    inst_id: str, bar: str, bars: int, get: GetFn | None = None, sleep: float = 0.12
) -> list[Candle]:
    """Page backwards through OKX history-candles (100 per request). Confirmed bars, oldest first."""
    get = get or _default_get()
    out: dict[int, Candle] = {}
    after: str | None = None
    while len(out) < bars:
        params: dict[str, str] = {"instId": inst_id, "bar": bar, "limit": "100"}
        if after:
            params["after"] = after
        batch = get("/market/history-candles", params).get("data", [])
        if not batch:
            break
        for r in batch:
            if len(r) > 8 and str(r[8]) != "1":
                continue  # skip the still-forming bar
            out[int(r[0])] = (int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]))
        oldest = min(int(r[0]) for r in batch)
        if after is not None and str(oldest) == after:
            break
        after = str(oldest)
        if len(batch) < 100:
            break
        time.sleep(sleep)
    return [out[k] for k in sorted(out)][-bars:]


def fetch_fng_history(session: Any = None) -> dict[str, int]:
    """Entire Fear & Greed history from alternative.me as {YYYY-MM-DD (UTC): value}."""
    import requests

    sess = session or requests
    data = sess.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=20).json()
    out: dict[str, int] = {}
    for item in data.get("data", []):
        day = datetime.fromtimestamp(int(item["timestamp"]), timezone.utc).strftime("%Y-%m-%d")
        out[day] = int(item["value"])
    return out


def fetch_funding_history(
    inst_id: str, max_records: int = 400, get: GetFn | None = None, sleep: float = 0.12
) -> list[tuple[int, float]]:
    """OKX funding-rate history: [(fundingTime_ms, rate)], oldest first (~3 months available)."""
    get = get or _default_get()
    out: dict[int, float] = {}
    after: str | None = None
    while len(out) < max_records:
        params: dict[str, str] = {"instId": inst_id, "limit": "100"}
        if after:
            params["after"] = after  # records earlier than this fundingTime
        batch = get("/public/funding-rate-history", params).get("data", [])
        if not batch:
            break
        for r in batch:
            out[int(r["fundingTime"])] = float(r["realizedRate"] or r["fundingRate"])
        oldest = min(int(r["fundingTime"]) for r in batch)
        if after is not None and str(oldest) == after:
            break
        after = str(oldest)
        if len(batch) < 100:
            break
        time.sleep(sleep)
    return sorted(out.items())


def fetch_oi_history(
    inst_id: str, bars: int, get: GetFn | None = None, sleep: float = 0.12
) -> dict[int, float]:
    """Best-effort 1H open-interest history in CONTRACTS: {ts_ms: contracts}. {} if unavailable."""
    get = get or _default_get()
    out: dict[int, float] = {}
    end: str | None = None
    try:
        while len(out) < bars:
            params: dict[str, str] = {"instId": inst_id, "period": "1H", "limit": "100"}
            if end:
                params["end"] = end
            batch = get("/rubik/stat/contracts/open-interest-history", params).get("data", [])
            if not batch:
                break
            for r in batch:
                out[int(r[0])] = float(r[1])
            oldest = min(int(r[0]) for r in batch)
            if end is not None and str(oldest) == end:
                break
            end = str(oldest)
            if len(batch) < 100:
                break
            time.sleep(sleep)
    except Exception as exc:  # the endpoint's retention is not guaranteed
        log.warning("OI history unavailable for %s: %s", inst_id, type(exc).__name__)
    return out


# ─────────────────────────── report ───────────────────────────

STOPS_DAILY = [2.0, 3.0, 5.0, 8.0]
STOPS_HOURLY = [1.0, 2.0, 3.0]


def _fmt_row(label: str, s: dict[str, Any] | None, stops: list[float], key_stop: float) -> str:
    if s is None:
        return f"| {label} | 0 | — | — | — | — | " + " | ".join("—" for _ in stops) + " | — |"
    thin = " ⚠thin" if s["n"] < THIN_SAMPLE else ""
    hits = " | ".join(f"{s['stop_hit'][st]:.0f}%" for st in stops)
    return (
        f"| {label} | {s['n']}{thin} | {s['win_pct']:.0f}% | {s['mean_ret']:+.2f}% | "
        f"{s['median_ret']:+.2f}% | {s['median_adverse']:.2f}% | {hits} | "
        f"{s['clean_win'][key_stop]:.0f}% |"
    )


def _table(
    title: str,
    candles: list[Candle],
    events: list[int],
    side: str,
    horizons: list[int],
    unit: str,
    stops: list[float],
    key_stop: float,
    baseline_gap: int,
) -> list[str]:
    head = (
        "| Horizon | n | Win | Mean | Median | Median MAE | "
        + " | ".join(f"Stop {s:g}%" for s in stops)
        + f" | Win w/o {key_stop:g}% stop |"
    )
    sep = "|" + "---|" * (6 + len(stops) + 1)
    lines = [f"**{title}** — {len(events)} episode(s)", "", head, sep]
    all_idx = list(range(0, len(candles), baseline_gap))
    for h in horizons:
        ev = summarize(candles, events, h, side, stops)
        lines.append(_fmt_row(f"{h}{unit} after", ev, stops, key_stop))
        base = summarize(candles, all_idx, h, side, stops)
        lines.append(_fmt_row(f"{h}{unit} random-day baseline", base, stops, key_stop))
    lines.append("")
    return lines


def build_report(parts: list[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = [
        f"# Contrarian event-study backtest — {now}",
        "",
        "Entry = close of the trigger bar. Win = positive return at the horizon (trade's direction). "
        "MAE = median worst move AGAINST the trade before the horizon ends. "
        "`Stop x%` = share of trades whose adverse move reached x% at some point "
        "(daily candles use the daily low/high, so intraday order is unknown). "
        "Each trigger row is followed by a random-day baseline: if the trigger does not beat it, "
        "it is not an edge. Rows with n < 20 are marked thin. Past results, small samples, "
        "no fees or funding costs.",
        "",
    ]
    return "\n".join(head + parts) + "\n"


def run_daily_fng(get: GetFn | None, fng: dict[str, int]) -> list[str]:
    parts: list[str] = ["## A. Fear & Greed extremes (daily, UTC)", ""]
    for name, inst in (("BTC", "BTC-USDT"), ("ETH", "ETH-USDT")):
        try:
            candles = fetch_candles(inst, "1Dutc", 2200, get)
        except Exception as exc:
            parts += [f"### {name}", f"_Could not fetch candles: {type(exc).__name__}_", ""]
            continue
        if len(candles) < 200:
            parts += [f"### {name}", f"_Only {len(candles)} daily candles available._", ""]
            continue
        first = datetime.fromtimestamp(candles[0][0] / 1000, timezone.utc).strftime("%Y-%m-%d")
        parts += [f"### {name} ({len(candles)} daily bars from {first})", ""]
        longs, shorts = fng_events(candles, fng)
        longs_ep = dedupe_events(longs, 7)
        shorts_ep = dedupe_events(shorts, 7)
        horizons = [1, 3, 7, 14, 30]
        parts += _table("LONG when F&G < 20", candles, longs_ep, "long", horizons, "d", STOPS_DAILY, 5.0, 1)
        parts += _table("SHORT when F&G > 80", candles, shorts_ep, "short", horizons, "d", STOPS_DAILY, 5.0, 1)

        trig = dedupe_events(setup_then_trigger(candles, longs, lookback=5), 5)
        parts += _table(
            "LONG setup→trigger (F&G < 20 within 5d, then close > previous day's high)",
            candles, trig, "long", horizons, "d", STOPS_DAILY, 5.0, 1,
        )
        for h in (7, 14):
            st = structure_stop_stats(candles, trig, h, "long")
            if st:
                parts.append(
                    f"Structure stop (below the trigger day's low), {h}d hold: n={st['n']}, "
                    f"median risk {st['median_risk']:.2f}%, stopped out {st['stop_hit_pct']:.0f}%, "
                    f"mean result {st['mean_r']:+.2f}R"
                )
        parts.append("")
    return parts


def run_hourly(get: GetFn | None) -> list[str]:
    parts: list[str] = ["## B. Market-shock moves (1H, ~90 days) — fade or continuation?", ""]
    for name, inst in (("BTC", "BTC-USDT-SWAP"), ("ETH", "ETH-USDT-SWAP")):
        try:
            candles = fetch_candles(inst, "1H", 2200, get)
        except Exception as exc:
            parts += [f"### {name}", f"_Could not fetch candles: {type(exc).__name__}_", ""]
            continue
        if len(candles) < 300:
            parts += [f"### {name}", f"_Only {len(candles)} hourly candles available._", ""]
            continue
        parts += [f"### {name} ({len(candles)} hourly bars)", ""]
        dumps, pumps = shock_events(candles)
        horizons = [1, 4, 12, 24, 72]
        parts += _table("Fade the DUMP (LONG after a sharp drop)", candles, dedupe_events(dumps, 6),
                        "long", horizons, "h", STOPS_HOURLY, 2.0, 1)
        parts += _table("Fade the PUMP (SHORT after a sharp rise)", candles, dedupe_events(pumps, 6),
                        "short", horizons, "h", STOPS_HOURLY, 2.0, 1)
        oi = fetch_oi_history(inst, len(candles), get)
        if len(oi) >= 200:
            flush = dedupe_events(oi_flush_events(candles, oi), 6)
            parts += _table("LONG after a real OI flush (contracts down >= 5%)", candles, flush,
                            "long", horizons, "h", STOPS_HOURLY, 2.0, 1)
        else:
            parts += [f"_OI history not available ({len(oi)} rows): OI-flush rule could not be tested._", ""]
    parts.append(
        "_Reading it: if 'Fade the DUMP' has a negative mean, the dump CONTINUED — "
        "chasing the move would have beaten fading it._\n"
    )
    return parts


def run_funding(get: GetFn | None) -> list[str]:
    parts: list[str] = ["## C. Funding dislocations (1H candles, ~3 months of OKX funding history)", ""]
    for name, inst in (("BTC", "BTC-USDT-SWAP"), ("ETH", "ETH-USDT-SWAP")):
        try:
            candles = fetch_candles(inst, "1H", 2400, get)
            funding = fetch_funding_history(inst, 400, get)
        except Exception as exc:
            parts += [f"### {name}", f"_Could not fetch data: {type(exc).__name__}_", ""]
            continue
        parts += [f"### {name} ({len(funding)} funding settlements)", ""]
        horizons = [4, 12, 24, 72]
        for label, apr_low in (("APR <= -8% (current)", -8.0), ("APR <= -5.475% (Gemini's relaxed rule)", -5.475)):
            longs, _ = funding_events(candles, funding, apr_low=apr_low)
            parts += _table(f"LONG when funding {label}", candles, dedupe_events(longs, 12),
                            "long", horizons, "h", STOPS_HOURLY, 2.0, 1)
        _, shorts = funding_events(candles, funding)
        parts += _table("SHORT when funding APR >= 27.375%", candles, dedupe_events(shorts, 12),
                        "short", horizons, "h", STOPS_HOURLY, 2.0, 1)
    return parts


def main(cfg: dict | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s %(message)s")
    get = _default_get()
    parts: list[str] = []

    try:
        fng = fetch_fng_history()
        log.info("Fear & Greed history: %d days", len(fng))
        parts += run_daily_fng(get, fng)
    except Exception as exc:
        log.error("Section A failed: %s", type(exc).__name__)
        parts += ["## A. Fear & Greed extremes", f"_Failed: {type(exc).__name__}_", ""]

    for fn in (run_hourly, run_funding):
        try:
            parts += fn(get)
        except Exception as exc:
            log.error("%s failed: %s", fn.__name__, type(exc).__name__)
            parts += [f"## {fn.__name__}", f"_Failed: {type(exc).__name__}_", ""]

    report = build_report(parts)
    out = Path("reports/backtest.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    log.info("Backtest written → %s", out)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
