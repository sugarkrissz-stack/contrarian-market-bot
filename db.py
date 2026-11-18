"""SQLite database layer — WAL mode, schema bootstrap, and helpers."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator

log = logging.getLogger(__name__)

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


def check_shock_cooldown(symbol: str, cooldown_hours: int = 3) -> bool:
    """Return True if a Market Shock alert was already fired for this symbol within `cooldown_hours`."""
    with _connect() as conn:
        cur = conn.execute(
            """SELECT 1 FROM alerts_log
               WHERE source='shock' AND symbol=?
                 AND alerted_at > datetime('now', ?)
               LIMIT 1""",
            (symbol, f"-{cooldown_hours} hours"),
        )
        return cur.fetchone() is not None


def record_alert(source: str, symbol: str, signal_type: str, score: float) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO alerts_log (source, symbol, signal_type, score, alerted_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (source, symbol, signal_type, score),
        )


def count_alerts_last_24h() -> int:
    """Return number of standard contrarian alerts logged in the last 24 hours.

    Excludes Market Shock alerts so shock alerts never burn the daily contrarian cap.
    """
    with _connect() as conn:
        cur = conn.execute(
            """SELECT COUNT(*) FROM alerts_log
               WHERE source != 'shock'
                 AND alerted_at > datetime('now', '-24 hours')"""
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def basis_baseline(symbol: str, days: int = 7, min_samples: int = 24) -> float | None:
    """Median basis % for `symbol` over the last `days` days.

    Perp-vs-index basis has a persistent, symbol-specific offset (e.g. USDT-margined
    contracts sit around -0.05% on OKX nearly all the time), so a fixed threshold on the
    raw value fires permanently.  The median is the symbol's "normal"; signals should
    measure deviation from it.  Returns None when there are fewer than `min_samples`
    rows, so a thin history never produces a baseline-based signal.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT basis_pct FROM funding WHERE symbol=? AND ts >= ? AND basis_pct IS NOT NULL",
            (symbol, cutoff),
        ).fetchall()
    values = sorted(float(r[0]) for r in rows)
    if len(values) < min_samples:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


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


def prune_old_records(days: int = 14) -> dict[str, int]:
    """Delete rows older than `days` days across all timestamped tables.

    Preserves recent alert logs for the 24h cap and recent SEC filing records.
    Runs VACUUM outside any open transaction so the SQLite file physically shrinks on disk.
    """
    assert _DB_PATH, "Call db.init() first"
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat(timespec="seconds")
    cutoff_unix = int(cutoff_dt.timestamp())
    cutoff_date = cutoff_dt.strftime("%Y-%m-%d")
    cutoff_sqlite = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    deleted_counts: dict[str, int] = {}

    with _connect() as conn:
        # 1. funding
        cur = conn.execute("DELETE FROM funding WHERE ts < ?", (cutoff_iso,))
        deleted_counts["funding"] = cur.rowcount

        # 2. open_interest
        cur = conn.execute("DELETE FROM open_interest WHERE ts < ?", (cutoff_iso,))
        deleted_counts["open_interest"] = cur.rowcount

        # 3. ls_ratios
        cur = conn.execute("DELETE FROM ls_ratios WHERE ts < ?", (cutoff_iso,))
        deleted_counts["ls_ratios"] = cur.rowcount

        # 4. fear_greed (UNIX timestamp string or ISO)
        cur = conn.execute(
            """DELETE FROM fear_greed
               WHERE (ts NOT LIKE '%-%' AND CAST(ts AS INTEGER) < ?)
                  OR (ts LIKE '%-%' AND ts < ?)""",
            (cutoff_unix, cutoff_iso),
        )
        deleted_counts["fear_greed"] = cur.rowcount

        # 5. sec_filings (preserves recent filings within `days`)
        cur = conn.execute("DELETE FROM sec_filings WHERE filed_date < ?", (cutoff_date,))
        deleted_counts["sec_filings"] = cur.rowcount

        # 6. alerts_log (preserves >= 24h of alerts for 24h hard cap and cooldowns)
        cur = conn.execute("DELETE FROM alerts_log WHERE alerted_at < ?", (cutoff_sqlite,))
        deleted_counts["alerts_log"] = cur.rowcount

    # Execute VACUUM outside any open transaction to physically shrink the database file
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.isolation_level = None  # Autocommit mode - no open transaction
    try:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    total_deleted = sum(deleted_counts.values())
    log.info(
        "Pruned %d old record(s) (>%dd): %s",
        total_deleted,
        days,
        deleted_counts,
    )
    return deleted_counts


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
