"""SQLite database layer — WAL mode, schema bootstrap, and helpers."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

_DB_PATH: str | None = None


def _resolve_path(cfg_path: str = "data/market_intel.db") -> str:
    p = Path(cfg_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def init(cfg_path: str = "data/market_intel.db") -> None:
    """Create tables (if needed) and set WAL journal mode."""
    global _DB_PATH
    _DB_PATH = _resolve_path(cfg_path)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    assert _DB_PATH, "Call db.init() first"
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_funding(row: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO funding
               (ts, symbol, mark_price, index_price, funding_rate,
                annualized_apr, basis_pct, next_funding_time)
               VALUES (:ts,:symbol,:mark_price,:index_price,:funding_rate,
                       :annualized_apr,:basis_pct,:next_funding_time)""",
            row,
        )


def insert_oi(row: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO open_interest
               (ts, symbol, oi_usd, oi_delta_4h_pct)
               VALUES (:ts,:symbol,:oi_usd,:oi_delta_4h_pct)""",
            row,
        )


def insert_ratios(row: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO ls_ratios
               (ts, symbol, retail_ratio, whale_ratio)
               VALUES (:ts,:symbol,:retail_ratio,:whale_ratio)""",
            row,
        )


def insert_fng(row: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO fear_greed
               (ts, value, classification)
               VALUES (:ts,:value,:classification)""",
            row,
        )


def insert_filing(row: dict[str, Any]) -> bool:
    """Insert SEC filing record.  Returns True if newly inserted (not a dup)."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM sec_filings WHERE accession_no = :accession_no",
            row,
        )
        if cur.fetchone():
            return False
        conn.execute(
            """INSERT INTO sec_filings
               (accession_no, cik, ticker, form_type, filed_date,
                primary_doc_url, txn_code, shares, price_per_share,
                total_value, is_10b51)
               VALUES (:accession_no,:cik,:ticker,:form_type,:filed_date,
                       :primary_doc_url,:txn_code,:shares,:price_per_share,
                       :total_value,:is_10b51)""",
            row,
        )
        return True


def check_cooldown(source: str, symbol: str, signal_type: str,
                   cooldown_hours: int, escalation_pct: float,
                   new_score: float) -> bool:
    """Return True if the alert should be SUPPRESSED (still in cooldown)."""
    with _connect() as conn:
        cur = conn.execute(
            """SELECT score, alerted_at FROM alerts_log
               WHERE source=? AND symbol=? AND signal_type=?
               ORDER BY alerted_at DESC LIMIT 1""",
            (source, symbol, signal_type),
        )
        row = cur.fetchone()
        if row is None:
            return False  # no prior alert → allow
        last_score = row["score"]
        # Check time window
        cur2 = conn.execute(
            """SELECT 1 FROM alerts_log
               WHERE source=? AND symbol=? AND signal_type=?
                 AND alerted_at > datetime('now', ?)
               ORDER BY alerted_at DESC LIMIT 1""",
            (source, symbol, signal_type, f"-{cooldown_hours} hours"),
        )
        if cur2.fetchone() is None:
            return False  # outside cooldown window → allow
        # Inside cooldown — allow only if score jumped enough
        if last_score > 0 and new_score >= last_score * (1 + escalation_pct / 100):
            return False
        return True


def record_alert(source: str, symbol: str, signal_type: str, score: float) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO alerts_log (source, symbol, signal_type, score, alerted_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (source, symbol, signal_type, score),
        )


def count_alerts_last_24h() -> int:
    """Return number of alerts logged in the last 24 hours."""
    with _connect() as conn:
        cur = conn.execute(
            """SELECT COUNT(*) FROM alerts_log
               WHERE alerted_at > datetime('now', '-24 hours')"""
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def latest_fng() -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM fear_greed ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None


def latest_funding(symbol: str) -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM funding WHERE symbol=? ORDER BY ts DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def latest_oi(symbol: str) -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM open_interest WHERE symbol=? ORDER BY ts DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def latest_ratios(symbol: str) -> dict[str, Any] | None:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM ls_ratios WHERE symbol=? ORDER BY ts DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─── Schema ───

_SCHEMA = """
CREATE TABLE IF NOT EXISTS funding (
    ts             TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    mark_price     REAL,
    index_price    REAL,
    funding_rate   REAL,
    annualized_apr REAL,
    basis_pct      REAL,
    next_funding_time TEXT,
    PRIMARY KEY (ts, symbol)
);

CREATE TABLE IF NOT EXISTS open_interest (
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    oi_usd          REAL,
    oi_delta_4h_pct REAL,
    PRIMARY KEY (ts, symbol)
);

CREATE TABLE IF NOT EXISTS ls_ratios (
    ts           TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    retail_ratio REAL,
    whale_ratio  REAL,
    PRIMARY KEY (ts, symbol)
);

CREATE TABLE IF NOT EXISTS fear_greed (
    ts              TEXT NOT NULL PRIMARY KEY,
    value           INTEGER,
    classification  TEXT
);

CREATE TABLE IF NOT EXISTS sec_filings (
    accession_no    TEXT PRIMARY KEY,
    cik             TEXT,
    ticker          TEXT,
    form_type       TEXT,
    filed_date      TEXT,
    primary_doc_url TEXT,
    txn_code        TEXT,
    shares          REAL,
    price_per_share REAL,
    total_value     REAL,
    is_10b51        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    score       REAL NOT NULL,
    alerted_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_lookup
    ON alerts_log (source, symbol, signal_type, alerted_at);
"""
