"""OKX public v5 collector for recent 1H candles and Open Interest history.

Provides accurate 1h, 4h, 24h price changes (%) and 1h-4h OI changes (%)
without relying on prior SQLite history, plus 30-day pagination for backtesting.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

OKX_BASE = "https://www.okx.com/api/v5"

# Map internal/Binance symbols to liquid OKX perpetual instruments
OKX_SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "BTCUSDC": "BTC-USDT-SWAP",  # OKX USDC perp has no volume/candles; map to USDT swap
    "ETHUSDT": "ETH-USDT-SWAP",
    "ETHUSDC": "ETH-USDT-SWAP",  # map to USDT swap
}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


class OKXCollectorError(Exception):
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, OKXCollectorError)),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _okx_get(endpoint: str, params: dict | None = None, timeout: int = 10) -> Any:
    url = f"{OKX_BASE}{endpoint}"
    resp = _session.get(url, params=params, timeout=timeout)
    if resp.status_code == 429:
        log.warning("OKX rate limit encountered, backing off...")
        raise OKXCollectorError("rate-limited")
    resp.raise_for_status()
    return resp.json()


def get_okx_instrument(symbol: str) -> str:
    """Resolve Binance/standard symbol to OKX perpetual swap instrument."""
    return OKX_SYMBOL_MAP.get(symbol, f"{symbol[:3]}-USDT-SWAP")


def fetch_recent_market_shock_data(symbol: str) -> dict[str, Any] | None:
    """Fetch recent 1H candles (limit 26) and 1H OI history (limit 6) from OKX.

    Computes:
      - curr_price, price_1h, price_4h, price_24h
      - price_chg_1h_pct, price_chg_4h_pct, price_chg_24h_pct
      - oi_now, oi_1h, oi_4h
      - oi_chg_1h_pct, oi_chg_4h_pct
      - oi_usd_now, oi_usd_1h, oi_usd_4h
      - oi_usd_chg_1h_pct, oi_usd_chg_4h_pct
    """
    inst_id = get_okx_instrument(symbol)
    try:
        # 1. Fetch 1H candles (up to 26 bars so 24h lookback is fully covered)
        c_res = _okx_get("/market/candles", {"instId": inst_id, "bar": "1H", "limit": "26"})
        candles = c_res.get("data", [])
    except Exception as e:
        log.error("Failed to fetch OKX candles for %s (%s): %s", symbol, inst_id, e)
        return None

    if not candles:
        log.warning("No candle data returned for %s (%s)", symbol, inst_id)
        return None

    # Candle format: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    curr_price = float(candles[0][4])
    price_1h = float(candles[1][4]) if len(candles) > 1 else curr_price
    price_4h = float(candles[4][4]) if len(candles) > 4 else price_1h

    # 24 hours ago: requires at least 24 bars and ~20+ hours timestamp span
    price_24h = curr_price
    price_chg_24h = 0.0
    if len(candles) >= 24:
        idx_24h = min(24, len(candles) - 1)
        curr_ts = int(candles[0][0])
        past_ts = int(candles[idx_24h][0])
        hours_diff = (curr_ts - past_ts) / (3600 * 1000)
        if hours_diff >= 20:
            price_24h = float(candles[idx_24h][4])
            price_chg_24h = ((curr_price - price_24h) / price_24h * 100) if price_24h else 0.0

    price_chg_1h = ((curr_price - price_1h) / price_1h * 100) if price_1h else 0.0
    price_chg_4h = ((curr_price - price_4h) / price_4h * 100) if price_4h else 0.0

    # 2. Fetch 1H Open Interest History (up to 6 bars)
    oi_chg_1h = 0.0
    oi_chg_4h = 0.0
    oi_usd_chg_1h = 0.0
    oi_usd_chg_4h = 0.0
    oi_now = 0.0
    oi_usd_now = 0.0

    try:
        oi_res = _okx_get(
            "/rubik/stat/contracts/open-interest-history",
            {"instId": inst_id, "period": "1H", "limit": "6"},
        )
        oi_data = oi_res.get("data", [])
        if oi_data:
            # OI format: [ts, oi_contracts, oi_ccy, oi_usd]
            oi_now = float(oi_data[0][1])
            oi_usd_now = float(oi_data[0][3])

            if len(oi_data) > 1:
                oi_1h = float(oi_data[1][1])
                oi_usd_1h = float(oi_data[1][3])
                if oi_1h > 0:
                    oi_chg_1h = (oi_now - oi_1h) / oi_1h * 100
                if oi_usd_1h > 0:
                    oi_usd_chg_1h = (oi_usd_now - oi_usd_1h) / oi_usd_1h * 100

            if len(oi_data) > 4:
                oi_4h = float(oi_data[4][1])
                oi_usd_4h = float(oi_data[4][3])
                if oi_4h > 0:
                    oi_chg_4h = (oi_now - oi_4h) / oi_4h * 100
                if oi_usd_4h > 0:
                    oi_usd_chg_4h = (oi_usd_now - oi_usd_4h) / oi_usd_4h * 100
    except Exception as e:
        log.warning("Failed to fetch OKX OI history for %s (%s): %s", symbol, inst_id, e)

    return {
        "symbol": symbol,
        "inst_id": inst_id,
        "curr_price": curr_price,
        "price_1h": price_1h,
        "price_4h": price_4h,
        "price_24h": price_24h,
        "price_chg_1h_pct": round(price_chg_1h, 2),
        "price_chg_4h_pct": round(price_chg_4h, 2),
        "price_chg_24h_pct": round(price_chg_24h, 2),
        "oi_now": oi_now,
        "oi_usd_now": oi_usd_now,
        "oi_chg_1h_pct": round(oi_chg_1h, 2),
        "oi_chg_4h_pct": round(oi_chg_4h, 2),
        "oi_usd_chg_1h_pct": round(oi_usd_chg_1h, 2),
        "oi_usd_chg_4h_pct": round(oi_usd_chg_4h, 2),
    }


def fetch_30d_history(inst_id: str = "BTC-USDT-SWAP", target_bars: int = 720) -> tuple[list[list], list[list]]:
    """Fetch ~30 days of 1H candles and 1H Open Interest history from OKX using pagination.

    Returns:
        (candles, oi_records) ordered chronologically (oldest first).
    """
    log.info("Fetching 30-day 1H candles for %s...", inst_id)
    candles: list[list] = []
    after_cursor: str | None = None

    while len(candles) < target_bars:
        params = {"instId": inst_id, "bar": "1H", "limit": "300"}
        if after_cursor:
            params["after"] = after_cursor
        res = _okx_get("/market/candles", params)
        batch = res.get("data", [])
        if not batch:
            break
        candles.extend(batch)
        after_cursor = batch[-1][0]
        if len(batch) < 300:
            break
        time.sleep(0.05)

    log.info("Fetched %d 1H candles for %s", len(candles), inst_id)

    log.info("Fetching 30-day 1H Open Interest history for %s...", inst_id)
    oi_records: list[list] = []
    end_cursor: str | None = None

    while len(oi_records) < target_bars:
        params = {"instId": inst_id, "period": "1H", "limit": "100"}
        if end_cursor:
            params["end"] = end_cursor
        res = _okx_get("/rubik/stat/contracts/open-interest-history", params)
        batch = res.get("data", [])
        if not batch:
            break
        oi_records.extend(batch)
        end_cursor = batch[-1][0]
        if len(batch) < 100:
            break
        time.sleep(0.05)

    log.info("Fetched %d OI records for %s", len(oi_records), inst_id)

    # Sort both chronologically (oldest first)
    candles_sorted = sorted(candles, key=lambda c: int(c[0]))
    oi_sorted = sorted(oi_records, key=lambda o: int(o[0]))

    return candles_sorted, oi_sorted
