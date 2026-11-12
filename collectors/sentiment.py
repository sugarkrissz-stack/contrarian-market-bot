"""Crypto Fear & Greed Index collector — alternative.me public API."""

from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import db

log = logging.getLogger(__name__)

URL = "https://api.alternative.me/fng/?limit=2"


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def fetch() -> dict[str, Any] | None:
    """Return latest Fear & Greed reading and store to DB."""
    try:
        resp = requests.get(URL, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.error("Fear & Greed fetch failed: %s", e)
        return None

    entries = payload.get("data", [])
    if not entries:
        log.warning("Fear & Greed: empty data")
        return None

    latest = entries[0]
    prev = entries[1] if len(entries) > 1 else None

    row = {
        "ts": latest["timestamp"],
        "value": int(latest["value"]),
        "classification": latest["value_classification"],
    }
    db.insert_fng(row)

    result = {
        "value": row["value"],
        "classification": row["classification"],
        "prev_value": int(prev["value"]) if prev else None,
        "prev_classification": prev["value_classification"] if prev else None,
    }
    log.info(
        "Fear & Greed: %d (%s) — prev %s (%s)",
        result["value"],
        result["classification"],
        result.get("prev_value"),
        result.get("prev_classification"),
    )
    return result
