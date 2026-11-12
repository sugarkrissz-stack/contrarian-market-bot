"""Binance USDS-M Futures data collector — public endpoints, no API key."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

import db

log = logging.getLogger(__name__)

BASE = (os.getenv("BINANCE_FAPI_BASE_URL") or "https://fapi.binance.com").strip().rstrip("/")
DATA_BASE = BASE

_session = requests.Session()


class BinanceCollectorError(Exception):
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, BinanceCollectorError)),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _get(url: str, params: dict | None = None, timeout: int = 12) -> Any:
    resp = _session.get(url, params=params, timeout=timeout)
    if resp.status_code == 429:
        log.warning("Binance rate-limited — retrying")
        raise BinanceCollectorError("rate-limited")
    resp.raise_for_status()
    return resp.json()


# ─── Premium Index (funding & basis) ───


def fetch_premium_index(symbol: str) -> dict[str, Any] | None:
    """Return funding/basis metrics for a single symbol."""
    try:
        data = _get(f"{BASE}/fapi/v1/premiumIndex", {"symbol": symbol})
    except Exception as e:
        log.error("premiumIndex %s: %s", symbol, e)
        return None

    mark = float(data["markPrice"])
    index = float(data["indexPrice"])
    rate = float(data["lastFundingRate"])
    apr = rate * 3 * 365 * 100
    basis = (mark - index) / index * 100 if index else 0.0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    row = {
        "ts": ts,
        "symbol": symbol,
        "mark_price": mark,
        "index_price": index,
        "funding_rate": rate,
        "annualized_apr": round(apr, 4),
        "basis_pct": round(basis, 6),
        "next_funding_time": data.get("nextFundingTime", ""),
    }
    db.insert_funding(row)
    log.info(
        "%s  funding_apr=%.2f%%  basis=%.4f%%  mark=%.2f",
        symbol, apr, basis, mark,
    )
    return row


# ─── Open Interest History ───


def fetch_open_interest(symbol: str) -> dict[str, Any] | None:
    """Fetch recent OI history and compute 4h delta %."""
    try:
        data = _get(
            f"{DATA_BASE}/futures/data/openInterestHist",
            {"symbol": symbol, "period": "1h", "limit": 5},
        )
    except Exception as e:
        log.error("openInterestHist %s: %s", symbol, e)
        return None

    if not data or len(data) < 2:
        log.warning("openInterestHist %s: insufficient data (%d rows)", symbol, len(data) if data else 0)
        return None

    current_oi = float(data[-1]["sumOpenInterestValue"])
    oldest_oi = float(data[0]["sumOpenInterestValue"])
    delta_pct = ((current_oi - oldest_oi) / oldest_oi * 100) if oldest_oi else 0.0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    row = {
        "ts": ts,
        "symbol": symbol,
        "oi_usd": round(current_oi, 2),
        "oi_delta_4h_pct": round(delta_pct, 4),
    }
    db.insert_oi(row)
    log.info(
        "%s  OI=$%.0f  4h_delta=%.2f%%",
        symbol, current_oi, delta_pct,
    )
    return row


# ─── Long/Short Ratios ───


def _fetch_ratio(url: str, symbol: str, params: dict) -> float | None:
    try:
        data = _get(url, {**params, "symbol": symbol, "period": "1h", "limit": 2})
        if data:
            return float(data[-1]["longShortRatio"])
    except Exception as e:
        log.debug("ratio fetch %s %s: %s", url, symbol, e)
    return None


def fetch_ratios(
    symbol: str, fallback_symbol: str | None = None
) -> dict[str, Any] | None:
    """Fetch global-account and top-trader L/S ratios.

    If *symbol* (e.g. BTCUSDC) lacks the ratio endpoint, transparently
    fall back to *fallback_symbol* (e.g. BTCUSDT) for the ratio data.
    """
    retail = _fetch_ratio(
        f"{DATA_BASE}/futures/data/globalLongShortAccountRatio", symbol, {}
    )
    whale = _fetch_ratio(
        f"{DATA_BASE}/futures/data/topLongShortPositionRatio", symbol, {}
    )

    used_symbol = symbol
    if (retail is None or whale is None) and fallback_symbol:
        log.info(
            "Ratio fallback: %s → %s (retail=%s, whale=%s)",
            symbol, fallback_symbol, retail, whale,
        )
        if retail is None:
            retail = _fetch_ratio(
                f"{DATA_BASE}/futures/data/globalLongShortAccountRatio",
                fallback_symbol, {},
            )
        if whale is None:
            whale = _fetch_ratio(
                f"{DATA_BASE}/futures/data/topLongShortPositionRatio",
                fallback_symbol, {},
            )
        used_symbol = f"{symbol}(fb:{fallback_symbol})"

    if retail is None and whale is None:
        log.warning("No ratio data for %s", symbol)
        return None

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {
        "ts": ts,
        "symbol": symbol,          # keyed to original symbol
        "retail_ratio": round(retail, 4) if retail else None,
        "whale_ratio": round(whale, 4) if whale else None,
    }
    db.insert_ratios(row)
    log.info(
        "%s  retail_L/S=%.4f  whale_L/S=%.4f",
        used_symbol,
        retail or 0,
        whale or 0,
    )
    return row


# ─── Collect all for a symbol list ───


def collect_all(
    symbols: list[str],
    usdc_fallback: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run all Binance collectors for every symbol; return per-symbol dicts."""
    results: dict[str, dict[str, Any]] = {}
    fb = usdc_fallback or {}

    for sym in symbols:
        funding = fetch_premium_index(sym)
        oi = fetch_open_interest(sym)
        ratios = fetch_ratios(sym, fb.get(sym))
        results[sym] = {
            "funding": funding,
            "oi": oi,
            "ratios": ratios,
        }
        time.sleep(0.25)  # gentle pacing

    return results
