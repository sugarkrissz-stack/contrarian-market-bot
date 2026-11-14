"""Macro Pre-Market Data Collector — Yahoo Finance Public Chart API (no API keys required)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

log = logging.getLogger(__name__)

MACRO_SYMBOLS = {
    "ES=F": "S&P 500 Futures",
    "NQ=F": "Nasdaq-100 Futures",
    "DX-Y.NYB": "US Dollar Index (DXY)",
    "^TNX": "10Y Treasury Yield",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def fetch_symbol_chart(symbol: str, timeout: int = 10) -> dict[str, Any] | None:
    """Fetch 1h interval / 2d range chart data from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1h", "range": "2d"}
    resp = _session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("chart", {}).get("result")
    if not results:
        log.warning("No chart data returned for %s", symbol)
        return None

    meta = results[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")

    # If regularMarketPrice is missing, try last close from indicators
    if price is None:
        quotes = results[0].get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in quotes.get("close", []) if c is not None]
        if closes:
            price = closes[-1]

    if price is None:
        log.warning("Could not resolve market price for %s", symbol)
        return None

    chg_pct = 0.0
    if prev_close and prev_close > 0:
        chg_pct = ((price - prev_close) / prev_close) * 100.0

    return {
        "symbol": symbol,
        "name": MACRO_SYMBOLS.get(symbol, symbol),
        "price": round(float(price), 3),
        "prev_close": round(float(prev_close), 3) if prev_close else None,
        "change_pct": round(float(chg_pct), 2),
    }


def fetch_macro_open() -> dict[str, dict[str, Any]]:
    """Fetch all macro open assets (ES, NQ, DXY, 10Y Yield)."""
    snapshot: dict[str, dict[str, Any]] = {}
    for sym, name in MACRO_SYMBOLS.items():
        try:
            item = fetch_symbol_chart(sym)
            if item:
                snapshot[sym] = item
                log.info(
                    "Macro: %-10s (%-22s) price=%-9.3f 24h_chg=%+6.2f%%",
                    sym, name, item["price"], item["change_pct"],
                )
            else:
                log.warning("Failed to collect macro data for %s", sym)
        except Exception as e:
            log.warning("Macro fetch exception for %s: %s", sym, e)
    return snapshot
