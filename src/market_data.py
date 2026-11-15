"""
NSE market data for the dashboard: the Nifty LargeMidcap 250 constituents and
their latest annual financials, so the Company Score page can offer a ticker
dropdown and auto-fill the form.

Two halves:

  * A weekly snapshot job (`snapshot_handler`, Lambda
    `distress-model-nse-snapshot`) downloads the official constituent list,
    fetches each company's latest annual balance sheet + income statement
    via yfinance, and writes one JSON document to S3.
  * The inference API reads that snapshot (`load_snapshot`, cached in
    memory) to serve GET /companies and GET /companies/{symbol}, and calls
    `live_lookup` for a custom ticker that isn't in the index.

This is display/auto-fill data only. It never feeds training: the retrain
pipeline's datasets are built separately by fetch_data_handler.py, and
nothing here is labelled. Keep it that way -- a ticker list with "current"
financials and no as-of discipline would be a leakage risk in training.

Constituent list sources, tried in order (NSE's sites are undocumented and
sometimes refuse cloud IPs, see CLAUDE.md):
  1. the official CSV on niftyindices.com,
  2. the same CSV on NSE's archive host,
  3. a CSV someone uploaded to s3://<MODEL_BUCKET>/<CONSTITUENTS_SEED_KEY>
     (same columns), for when both sites block AWS.

Environment variables:
    MODEL_BUCKET            S3 bucket for the snapshot (required for S3 paths)
    MARKET_SNAPSHOT_KEY     default market-data/nse-largemidcap250/latest.json
    CONSTITUENTS_SEED_KEY   default market-data/nse-largemidcap250/constituents.csv
    MARKET_SNAPSHOT_PATH    local JSON file to use instead of S3 (dev/tests)
    SNAPSHOT_WORKERS        parallel yfinance fetches in the job (default 6)
"""

import csv
import io
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

INDEX_NAME = "Nifty LargeMidcap 250"

CONSTITUENT_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_niftylargemidcap250list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv",
]
_HTTP_HEADERS = {
    # NSE's hosts reject requests without a browser-like User-Agent.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,text/plain,*/*",
}

DEFAULT_SNAPSHOT_KEY = "market-data/nse-largemidcap250/latest.json"
DEFAULT_SEED_KEY = "market-data/nse-largemidcap250/constituents.csv"

# Same seven fields features.REQUIRED_FINANCIAL_FIELDS needs, plus the two
# optional ones the score form accepts.
REQUIRED_FIELDS = [
    "total_assets", "total_liabilities", "current_assets",
    "current_liabilities", "retained_earnings", "ebit", "sales",
]
OPTIONAL_FIELDS = ["market_value_equity", "book_value_equity"]

# Yahoo-style ticker, optionally with an exchange suffix. Deliberately
# narrow: this string ends up in an outbound request.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}(\.[A-Z]{1,3})?$")


# --------------------------------------------------------------------------
# Constituents
# --------------------------------------------------------------------------

def parse_constituents_csv(text: str) -> list[dict]:
    """Parse NSE's index constituent CSV
    (Company Name, Industry, Symbol, Series, ISIN Code) into
    [{symbol, name, industry, isin}]. Tolerates a BOM and stray whitespace."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    seen = set()
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        symbol = row.get("Symbol", "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append({
            "symbol": symbol,
            "name": row.get("Company Name") or symbol,
            "industry": row.get("Industry") or None,
            "isin": row.get("ISIN Code") or None,
        })
    return out


def fetch_constituents(
    http_get: Optional[Callable[[str], str]] = None,
    seed_reader: Optional[Callable[[], Optional[str]]] = None,
) -> tuple[list[dict], str]:
    """Return (constituents, source_description). Raises RuntimeError if no
    source yields a plausible list."""
    if http_get is None:
        http_get = _http_get_text
    if seed_reader is None:
        seed_reader = _read_seed_from_s3

    errors = []
    for url in CONSTITUENT_URLS:
        try:
            rows = parse_constituents_csv(http_get(url))
            # A real list has ~250 rows; a handful means an error page.
            if len(rows) >= 200:
                return rows, url
            errors.append(f"{url}: only {len(rows)} rows")
        except Exception as e:  # network, HTTP status, parse
            errors.append(f"{url}: {e}")

    try:
        seed = seed_reader()
        if seed:
            rows = parse_constituents_csv(seed)
            if rows:
                return rows, "s3-seed"
            errors.append("s3-seed: no rows")
        else:
            errors.append("s3-seed: not present")
    except Exception as e:
        errors.append(f"s3-seed: {e}")

    raise RuntimeError("Could not load index constituents: " + "; ".join(errors))


def _http_get_text(url: str) -> str:
    import requests
    r = requests.get(url, headers=_HTTP_HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def _read_seed_from_s3() -> Optional[str]:
    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError
    key = os.environ.get("CONSTITUENTS_SEED_KEY", DEFAULT_SEED_KEY)
    try:
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    return obj["Body"].read().decode("utf-8")


# --------------------------------------------------------------------------
# Per-company financials
# --------------------------------------------------------------------------

def _clean_number(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def normalise_record(raw: dict, meta: dict) -> dict:
    """Shape one company's fetched fields into the snapshot/API record."""
    financials = {f: _clean_number(raw.get(f)) for f in REQUIRED_FIELDS + OPTIONAL_FIELDS}
    missing = [f for f in REQUIRED_FIELDS if financials[f] is None]
    rec = {
        **meta,
        "financials": financials,
        "missing": missing,
        "complete": not missing,
    }
    if raw.get("currency_mismatch"):
        rec["note"] = (f"Statements are in {raw.get('currency')}, unlike the share price; "
                       "market value of equity left out so the score uses book value.")
    return rec


def fetch_company(yahoo_ticker: str) -> dict:
    """yfinance -> {fields..., as_of, currency}. Thin wrapper over
    nse_client so the field aliases live in one place."""
    import nse_client
    return nse_client.fetch_financials_with_period(yahoo_ticker, polite_delay=0.2)


def fetch_company_with_name(yahoo_ticker: str) -> dict:
    """As fetch_company, plus the company name -- one extra Yahoo request,
    so only used for custom-ticker lookups (the index CSV already has names)."""
    import nse_client
    return nse_client.fetch_financials_with_period(yahoo_ticker, polite_delay=0.0, with_name=True)


def build_snapshot(
    constituents: list[dict],
    constituents_source: str,
    fetcher: Callable[[str], dict] = fetch_company,
    workers: int = 6,
) -> dict:
    """Fetch every constituent's financials (in parallel) and assemble the
    snapshot document. A failing company is recorded with its error rather
    than failing the whole run."""

    def one(c: dict) -> dict:
        yahoo = f"{c['symbol']}.NS"
        meta = {
            "symbol": c["symbol"],
            "yahoo_ticker": yahoo,
            "name": c["name"],
            "industry": c.get("industry"),
        }
        try:
            raw = fetcher(yahoo)
        except Exception as e:
            rec = normalise_record({}, {**meta, "as_of": None, "currency": None})
            rec["error"] = f"{type(e).__name__}: {e}"[:300]
            return rec
        return normalise_record(raw, {
            **meta,
            "as_of": raw.get("as_of"),
            "currency": raw.get("currency"),
        })

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        companies = list(pool.map(one, constituents))

    companies.sort(key=lambda r: r["symbol"])
    return {
        "index": INDEX_NAME,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "constituents_source": constituents_source,
        "data_source": "Yahoo Finance via yfinance (latest annual statements)",
        "count": len(companies),
        "complete_count": sum(1 for r in companies if r["complete"]),
        "companies": companies,
    }


# --------------------------------------------------------------------------
# Snapshot storage
# --------------------------------------------------------------------------

def save_snapshot(snapshot: dict) -> list[str]:
    """Write latest.json plus a dated copy (history for later trend charts).
    Returns the S3 keys written."""
    import boto3
    bucket = os.environ["MODEL_BUCKET"]
    latest = os.environ.get("MARKET_SNAPSHOT_KEY", DEFAULT_SNAPSHOT_KEY)
    dated = latest.rsplit("/", 1)[0] + f"/history/{snapshot['generated_at'][:10]}.json"
    body = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    s3 = boto3.client("s3")
    for key in (dated, latest):
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return [dated, latest]


_SNAPSHOT_TTL_SECONDS = 3600
_snapshot_cache: dict = {"value": None, "loaded_at": 0.0}
_snapshot_lock = threading.Lock()


def load_snapshot(force: bool = False) -> Optional[dict]:
    """The latest snapshot, or None if the job hasn't produced one yet.
    Cached for an hour per warm Lambda container."""
    with _snapshot_lock:
        fresh = time.time() - _snapshot_cache["loaded_at"] < _SNAPSHOT_TTL_SECONDS
        if not force and fresh and _snapshot_cache["loaded_at"]:
            return _snapshot_cache["value"]
        value = _read_snapshot()
        _snapshot_cache.update(value=value, loaded_at=time.time())
        return value


def _read_snapshot() -> Optional[dict]:
    local = os.environ.get("MARKET_SNAPSHOT_PATH")
    if local:
        if not os.path.exists(local):
            return None
        with open(local) as f:
            return json.load(f)

    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError
    key = os.environ.get("MARKET_SNAPSHOT_KEY", DEFAULT_SNAPSHOT_KEY)
    try:
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "AccessDenied"):
            logger.warning("Market snapshot not available: %s", e)
            return None
        raise
    return json.loads(obj["Body"].read())


def find_company(snapshot: Optional[dict], symbol: str) -> Optional[dict]:
    if not snapshot:
        return None
    s = symbol.upper().removesuffix(".NS")
    return next((c for c in snapshot.get("companies", []) if c["symbol"] == s), None)


# --------------------------------------------------------------------------
# Live lookup for custom tickers
# --------------------------------------------------------------------------

def normalise_ticker(raw: str) -> Optional[str]:
    t = (raw or "").strip().upper()
    return t if _TICKER_RE.match(t) else None


def candidate_yahoo_tickers(ticker: str) -> list[str]:
    """A bare ticker is most likely Indian here, so try NSE, then BSE, then
    as-is (e.g. a US ticker). A suffixed ticker is used exactly."""
    if "." in ticker:
        return [ticker]
    return [f"{ticker}.NS", f"{ticker}.BO", ticker]


_LOOKUP_TTL_SECONDS = 6 * 3600
_lookup_cache: dict[str, tuple[float, Optional[dict]]] = {}
_lookup_pool = ThreadPoolExecutor(max_workers=4)


def live_lookup(
    ticker: str,
    fetcher: Callable[[str], dict] = fetch_company_with_name,
    timeout_seconds: float = 20.0,
) -> Optional[dict]:
    """Fetch a custom ticker's latest annual financials on demand. Returns
    a record (same shape as a snapshot company) when at least one required
    field was found, else None. Results, including misses, are cached."""
    now = time.time()
    hit = _lookup_cache.get(ticker)
    if hit and now - hit[0] < _LOOKUP_TTL_SECONDS:
        return hit[1]

    deadline = now + timeout_seconds
    result = None
    for yahoo in candidate_yahoo_tickers(ticker):
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = _lookup_pool.submit(fetcher, yahoo).result(timeout=remaining)
        except FutureTimeout:
            logger.warning("Lookup timed out for %s", yahoo)
            break
        except Exception as e:
            logger.info("Lookup failed for %s: %s", yahoo, e)
            continue
        rec = normalise_record(raw, {
            "symbol": yahoo.split(".")[0],
            "yahoo_ticker": yahoo,
            "name": raw.get("name") or yahoo,
            "industry": None,
            "as_of": raw.get("as_of"),
            "currency": raw.get("currency"),
        })
        if len(rec["missing"]) < len(REQUIRED_FIELDS):
            result = rec
            break

    _lookup_cache[ticker] = (time.time(), result)
    return result


# --------------------------------------------------------------------------
# Lambda entry point for the weekly job
# --------------------------------------------------------------------------

def snapshot_handler(event, context):
    constituents, source = fetch_constituents()
    workers = int(os.environ.get("SNAPSHOT_WORKERS", "6"))
    snapshot = build_snapshot(constituents, source, workers=workers)
    keys = save_snapshot(snapshot)
    summary = {
        "constituents_source": source,
        "count": snapshot["count"],
        "complete_count": snapshot["complete_count"],
        "errors": sum(1 for c in snapshot["companies"] if c.get("error")),
        "s3_keys": keys,
    }
    logger.info("NSE snapshot written: %s", summary)
    return summary
