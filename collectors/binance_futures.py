"""Futures data collector — Binance USDS-M Perpetuals with automatic OKX v5 fallback."""

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

OKX_BASE = "https://www.okx.com/api/v5"

# Mapping from Binance symbol to OKX perpetual swap instrument
OKX_SYMBOL_MAP = {
    "BTCUSDT": "BTC-USDT-SWAP",
    "BTCUSDC": "BTC-USDC-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "ETHUSDC": "ETH-USDC-SWAP",
}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

_binance_blocked: bool = os.getenv("BINANCE_FORCE_OKX", "").strip().lower() in ("1", "true", "yes")


class BinanceCollectorError(Exception):
    pass


class BinanceBlockedError(Exception):
    """Raised when Binance returns 451, 403, or geo-restriction."""
    pass


@retry(
    retry=retry_if_exception_type(BinanceCollectorError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _get(url: str, params: dict | None = None, timeout: int = 10) -> Any:
    global _binance_blocked
    if _binance_blocked:
        raise BinanceBlockedError("Binance marked as unavailable; using fallback")

    try:
        resp = _session.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        log.warning("Binance request error on %s: %s", url, e)
        raise BinanceCollectorError(str(e)) from e

    if resp.status_code in (403, 451):
        _binance_blocked = True
        log.warning("Binance returned HTTP %d (geo-restricted/forbidden). Switching to OKX fallback.", resp.status_code)
        raise BinanceBlockedError(f"HTTP {resp.status_code}")

    if resp.status_code == 429:
        log.warning("Binance rate-limited — retrying")
        raise BinanceCollectorError("rate-limited")

    resp.raise_for_status()
    return resp.json()


# ─── OKX Public API v5 Helper ───


def _okx_get(endpoint: str, params: dict | None = None, timeout: int = 10) -> Any:
    url = f"{OKX_BASE}{endpoint}"
    resp = _session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ─── OKX Fallback Collectors ───


def fetch_okx_funding(symbol: str) -> dict[str, Any] | None:
    """Fetch mark price, index price, basis %, and funding APR from OKX public v5."""
    okx_inst = OKX_SYMBOL_MAP.get(symbol, f"{symbol[:3]}-USDT-SWAP")
    ccy = symbol[:3]
    fallback_inst = f"{ccy}-USDT-SWAP"

    # 1. Mark Price
    mark_px = None
    try:
        data = _okx_get("/public/mark-price", {"instType": "SWAP", "instId": okx_inst}).get("data", [])
        if not data and okx_inst != fallback_inst:
            data = _okx_get("/public/mark-price", {"instType": "SWAP", "instId": fallback_inst}).get("data", [])
        if data:
            mark_px = float(data[0]["markPx"])
    except Exception as e:
        log.debug("OKX mark-price %s error: %s", okx_inst, e)

    # 2. Index Price
    idx_px = None
    try:
        idx_id = okx_inst.replace("-SWAP", "")
        data = _okx_get("/market/index-tickers", {"instId": idx_id}).get("data", [])
        if not data:
            data = _okx_get("/market/index-tickers", {"instId": f"{ccy}-USDT"}).get("data", [])
        if data:
            idx_px = float(data[0]["idxPx"])
    except Exception as e:
        log.debug("OKX index-tickers %s error: %s", okx_inst, e)

    # 3. Funding Rate
    rate = 0.0
    next_time = ""
    try:
        data = _okx_get("/public/funding-rate", {"instId": okx_inst}).get("data", [])
        if not data and okx_inst != fallback_inst:
            data = _okx_get("/public/funding-rate", {"instId": fallback_inst}).get("data", [])
        if data:
            rate = float(data[0]["fundingRate"])
            next_time = data[0].get("nextFundingTime", "")
    except Exception as e:
        log.debug("OKX funding-rate %s error: %s", okx_inst, e)

    if mark_px is None and idx_px is None:
        log.error("OKX fallback failed for %s mark/index price", symbol)
        return None

    mark = mark_px if mark_px is not None else (idx_px or 0.0)
    index = idx_px if idx_px is not None else mark
    apr = rate * 3 * 365 * 100
    basis = ((mark - index) / index * 100) if index else 0.0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    row = {
        "ts": ts,
        "symbol": symbol,
        "mark_price": mark,
        "index_price": index,
        "funding_rate": rate,
        "annualized_apr": round(apr, 4),
        "basis_pct": round(basis, 6),
        "next_funding_time": next_time,
    }
    db.insert_funding(row)
    log.info(
        "[OKX] %s (%s)  funding_apr=%.2f%%  basis=%.4f%%  mark=%.2f",
        symbol, okx_inst, apr, basis, mark,
    )
    return row


def fetch_okx_open_interest(symbol: str) -> dict[str, Any] | None:
    """Fetch current OI in USD and compute 4h delta % from OKX public v5."""
    okx_inst = OKX_SYMBOL_MAP.get(symbol, f"{symbol[:3]}-USDT-SWAP")
    ccy = symbol[:3]
    fallback_inst = f"{ccy}-USDT-SWAP"

    # Current OI USD
    oi_usd = 0.0
    try:
        data = _okx_get("/public/open-interest", {"instType": "SWAP", "instId": okx_inst}).get("data", [])
        if not data and okx_inst != fallback_inst:
            data = _okx_get("/public/open-interest", {"instType": "SWAP", "instId": fallback_inst}).get("data", [])
        if data:
            oi_usd = float(data[0]["oiUsd"])
    except Exception as e:
        log.error("OKX open-interest %s error: %s", okx_inst, e)

    # 4h Delta from rubik stats open-interest-volume
    delta_pct = 0.0
    try:
        hist_data = _okx_get("/rubik/stat/contracts/open-interest-volume", {"ccy": ccy, "period": "1H"}).get("data", [])
        if len(hist_data) >= 5:
            # Data is descending by timestamp: data[0] is latest, data[4] is 4 hours ago
            curr_oi = float(hist_data[0][1])
            past_oi = float(hist_data[4][1])
            delta_pct = ((curr_oi - past_oi) / past_oi * 100) if past_oi else 0.0
    except Exception as e:
        log.debug("OKX open-interest-volume %s error: %s", ccy, e)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {
        "ts": ts,
        "symbol": symbol,
        "oi_usd": round(oi_usd, 2),
        "oi_delta_4h_pct": round(delta_pct, 4),
    }
    db.insert_oi(row)
    log.info(
        "[OKX] %s (%s)  OI=$%.0f  4h_delta=%.2f%%",
        symbol, okx_inst, oi_usd, delta_pct,
    )
    return row


def fetch_okx_ratios(symbol: str) -> dict[str, Any] | None:
    """Fetch retail L/S account ratio and top-trader whale L/S position ratio from OKX public v5."""
    okx_inst = OKX_SYMBOL_MAP.get(symbol, f"{symbol[:3]}-USDT-SWAP")
    ccy = symbol[:3]
    fallback_inst = f"{ccy}-USDT-SWAP"

    retail = None
    try:
        data = _okx_get("/rubik/stat/contracts/long-short-account-ratio", {"ccy": ccy, "period": "1H"}).get("data", [])
        if data:
            retail = float(data[0][1])
    except Exception as e:
        log.debug("OKX long-short-account-ratio %s error: %s", ccy, e)

    whale = None
    try:
        data = _okx_get("/rubik/stat/contracts/long-short-position-ratio-contract-top-trader", {"instId": okx_inst, "period": "1H"}).get("data", [])
        if not data and okx_inst != fallback_inst:
            data = _okx_get("/rubik/stat/contracts/long-short-position-ratio-contract-top-trader", {"instId": fallback_inst, "period": "1H"}).get("data", [])
        if data:
            whale = float(data[0][1])
    except Exception as e:
        log.debug("OKX top trader position ratio %s error: %s", okx_inst, e)

    if retail is None and whale is None:
        log.warning("No OKX ratio data for %s", symbol)
        return None

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {
        "ts": ts,
        "symbol": symbol,
        "retail_ratio": round(retail, 4) if retail is not None else None,
        "whale_ratio": round(whale, 4) if whale is not None else None,
    }
    db.insert_ratios(row)
    log.info(
        "[OKX] %s (%s)  retail_L/S=%.4f  whale_L/S=%.4f",
        symbol, okx_inst, retail or 0, whale or 0,
    )
    return row


# ─── Binance Primary Collectors ───


def fetch_premium_index(symbol: str) -> dict[str, Any] | None:
    """Return funding/basis metrics for a single symbol with OKX fallback."""
    global _binance_blocked
    if not _binance_blocked:
        try:
            data = _get(f"{BASE}/fapi/v1/premiumIndex", {"symbol": symbol})
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
        except BinanceBlockedError as e:
            log.warning("Binance blocked (%s); using OKX fallback for %s funding", e, symbol)
        except Exception as e:
            log.warning("Binance premiumIndex %s failed (%s); using OKX fallback", symbol, e)

    return fetch_okx_funding(symbol)


def fetch_open_interest(symbol: str) -> dict[str, Any] | None:
    """Fetch recent OI history and compute 4h delta % with OKX fallback."""
    global _binance_blocked
    if not _binance_blocked:
        try:
            data = _get(
                f"{DATA_BASE}/futures/data/openInterestHist",
                {"symbol": symbol, "period": "1h", "limit": 5},
            )
            if data and len(data) >= 2:
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
        except BinanceBlockedError as e:
            log.warning("Binance blocked (%s); using OKX fallback for %s OI", e, symbol)
        except Exception as e:
            log.warning("Binance openInterest %s failed (%s); using OKX fallback", symbol, e)

    return fetch_okx_open_interest(symbol)


def _fetch_binance_ratio(url: str, symbol: str, params: dict) -> float | None:
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
    """Fetch global-account and top-trader L/S ratios with OKX fallback."""
    global _binance_blocked
    if not _binance_blocked:
        try:
            retail = _fetch_binance_ratio(
                f"{DATA_BASE}/futures/data/globalLongShortAccountRatio", symbol, {}
            )
            whale = _fetch_binance_ratio(
                f"{DATA_BASE}/futures/data/topLongShortPositionRatio", symbol, {}
            )

            used_symbol = symbol
            if (retail is None or whale is None) and fallback_symbol:
                log.info(
                    "Ratio fallback: %s → %s (retail=%s, whale=%s)",
                    symbol, fallback_symbol, retail, whale,
                )
                if retail is None:
                    retail = _fetch_binance_ratio(
                        f"{DATA_BASE}/futures/data/globalLongShortAccountRatio",
                        fallback_symbol, {},
                    )
                if whale is None:
                    whale = _fetch_binance_ratio(
                        f"{DATA_BASE}/futures/data/topLongShortPositionRatio",
                        fallback_symbol, {},
                    )
                used_symbol = f"{symbol}(fb:{fallback_symbol})"

            if retail is not None or whale is not None:
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
                row = {
                    "ts": ts,
                    "symbol": symbol,
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
        except BinanceBlockedError as e:
            log.warning("Binance blocked (%s); using OKX fallback for %s ratios", e, symbol)
        except Exception as e:
            log.warning("Binance ratios %s failed (%s); using OKX fallback", symbol, e)

    return fetch_okx_ratios(symbol)


# ─── Collect all for a symbol list ───


def collect_all(
    symbols: list[str],
    usdc_fallback: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run collectors for every symbol (Binance primary, OKX fallback); return per-symbol dicts."""
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
