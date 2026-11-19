"""SEC EDGAR collector — Form 4 & 13F-HR parser with rate limiting and lookback cutoff."""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

import db

log = logging.getLogger(__name__)

_session = requests.Session()
_last_request_ts: float = 0.0


def _set_user_agent(ua: str) -> None:
    _session.headers["User-Agent"] = ua
    _session.headers["Accept-Encoding"] = "gzip, deflate"


def _rate_limit(max_rps: int = 5) -> None:
    """Enforce <= max_rps requests per second."""
    global _last_request_ts
    gap = 1.0 / max_rps
    now = time.monotonic()
    wait = gap - (now - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _get(url: str, rate_rps: int = 5) -> requests.Response:
    _rate_limit(rate_rps)
    resp = _session.get(url, timeout=15)
    resp.raise_for_status()
    return resp


# ─── Submissions index ───


def fetch_filings(
    cik: str,
    ticker: str,
    user_agent: str,
    rate_rps: int = 5,
    lookback_days: int = 14,
) -> list[dict[str, Any]]:
    """Fetch recent Form 4 and 13F-HR filings within lookback_days for a CIK, store new ones."""
    _set_user_agent(user_agent)
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        resp = _get(url, rate_rps)
        data = resp.json()
    except Exception as e:
        log.error("EDGAR submissions %s (%s): %s", ticker, cik, e)
        return []

    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        log.warning("No recent filings for %s", ticker)
        return []

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    new_filings: list[dict[str, Any]] = []
    now_date = datetime.now(timezone.utc).date()
    cutoff_date = (now_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    for i, form_type in enumerate(forms):
        if i >= len(accessions) or i >= len(dates):
            break

        filed_date = dates[i] if i < len(dates) else ""
        if filed_date:
            try:
                f_date = datetime.strptime(filed_date, "%Y-%m-%d").date()
                if (now_date - f_date).days > lookback_days:
                    continue
            except ValueError:
                if filed_date < cutoff_date:
                    continue

        if form_type not in ("4", "13F-HR"):
            continue

        accession_no = accessions[i]
        primary_doc = primary_docs[i] if i < len(primary_docs) else ""

        accession_nodashes = accession_no.replace("-", "")
        cik_int = str(int(cik))
        raw_doc_filename = primary_doc.split("/")[-1] if primary_doc else ""

        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{accession_nodashes}/{primary_doc}"
        )
        raw_doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_int}/{accession_nodashes}/{raw_doc_filename}"
        )

        base_row = {
            "accession_no": accession_no,
            "cik": cik,
            "ticker": ticker,
            "form_type": form_type,
            "filed_date": filed_date,
            "primary_doc_url": doc_url,
            "txn_code": None,
            "shares": None,
            "price_per_share": None,
            "total_value": None,
            "is_10b51": 0,
        }

        if form_type == "4" and raw_doc_filename.endswith(".xml"):
            parsed = _parse_form4_xml(raw_doc_url, rate_rps)
            if parsed:
                for idx, txn in enumerate(parsed):
                    row = {**base_row, **txn}
                    row["accession_no"] = f"{accession_no}_{txn.get('txn_code','X')}_{idx}"
                    if db.insert_filing(row):
                        new_filings.append(row)
                        log.info(
                            "SEC %s Form 4: %s %s shares @ $%s (10b5-1=%s)",
                            ticker, txn.get("txn_code"), txn.get("shares"),
                            txn.get("price_per_share"), txn.get("is_10b51"),
                        )
                continue

        if db.insert_filing(base_row):
            new_filings.append(base_row)
            log.info("SEC %s %s filed %s", ticker, form_type, filed_date)

    return new_filings


# ─── Form 4 XML Parser ───


def _parse_form4_xml(url: str, rate_rps: int = 5) -> list[dict[str, Any]]:
    """Download and parse a Form 4 XML filing for transactions."""
    try:
        resp = _get(url, rate_rps)
        text = resp.text
    except Exception as e:
        log.warning("Could not fetch Form 4 XML %s: %s", url, e)
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.warning("XML parse error %s: %s", url, e)
        return []

    # Map footnote IDs -> lowercased text
    footnote_map: dict[str, str] = {}
    affirmative_flag = 0
    for el in root.iter():
        tag = _local_tag(el)
        if tag == "footnote" and el.get("id"):
            footnote_map[el.get("id")] = (el.text or "").strip().lower()
        elif tag == "affirmative10b51Flag":
            val = (el.text or "").strip().lower()
            if val in ("1", "true", "y"):
                affirmative_flag = 1

    transactions: list[dict[str, Any]] = []

    for txn_el in _find_all_transactions(root):
        code_el = _find_child(txn_el, "transactionCoding")
        code = ""
        if code_el is not None:
            tc = _find_child(code_el, "transactionCode")
            code = tc.text.strip() if tc is not None and tc.text else ""

        amounts_el = _find_child(txn_el, "transactionAmounts")
        shares = 0.0
        price = 0.0
        if amounts_el is not None:
            sh_el = _find_child(amounts_el, "transactionShares")
            if sh_el is not None:
                val_el = _find_child(sh_el, "value")
                if val_el is not None and val_el.text:
                    try:
                        shares = float(val_el.text)
                    except ValueError:
                        pass
            pr_el = _find_child(amounts_el, "transactionPricePerShare")
            if pr_el is not None:
                val_el = _find_child(pr_el, "value")
                if val_el is not None and val_el.text:
                    try:
                        price = float(val_el.text)
                    except ValueError:
                        pass

        # Detect 10b5-1 indicators
        is_10b51 = affirmative_flag
        for ref in txn_el.iter():
            if _local_tag(ref) == "footnoteId":
                fid = ref.get("id")
                ftext = footnote_map.get(fid, "")
                if "10b5-1" in ftext or "10b5" in ftext or "rule 10b" in ftext:
                    is_10b51 = 1
                    break

        if not is_10b51:
            full_text = ET.tostring(txn_el, encoding="unicode", method="text").lower()
            if "10b5-1" in full_text or "10b5" in full_text or "rule 10b" in full_text:
                is_10b51 = 1

        transactions.append({
            "txn_code": code,
            "shares": shares,
            "price_per_share": price,
            "total_value": round(shares * price, 2),
            "is_10b51": is_10b51,
        })

    return transactions


def _find_all_transactions(root: ET.Element) -> list[ET.Element]:
    """Find all transaction elements regardless of namespace."""
    results = []
    for el in root.iter():
        tag = _local_tag(el)
        if tag in (
            "nonDerivativeTransaction",
            "derivativeTransaction",
        ):
            results.append(el)
    return results


def _find_child(parent: ET.Element, local_name: str) -> ET.Element | None:
    for child in parent:
        if _local_tag(child) == local_name:
            return child
    return None


def _local_tag(el: ET.Element) -> str:
    tag = el.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag
