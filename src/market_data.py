"""
Market data for the dashboard: index constituents and their latest annual
financials, so the Company Score page can offer a ticker dropdown and
auto-fill the form, and Market Overview can score a whole index.

Two universes (see UNIVERSES):
  * "nse": Nifty LargeMidcap 250 (the original; Lambda
    `distress-model-nse-snapshot`, one run),
  * "us":  S&P 500 (Lambda `distress-model-us-snapshot`). ~500 companies
    don't fit in one 15-minute Lambda run at the observed yfinance pace
    (~250 in ~12 min), so this job runs as N shards on staggered schedules:
    each writes parts/part-<i>-of-<N>.json, then merges every part present
    into latest.json once all N exist.

Two halves:

  * A weekly snapshot job (`snapshot_handler`) downloads the constituent
    list, fetches each company's latest annual balance sheet + income
    statement via yfinance, and writes one JSON document to S3.
  * The inference API reads that snapshot (`load_snapshot`, cached in
    memory) to serve GET /companies and GET /companies/{symbol}, and calls
    `live_lookup` for a custom ticker that isn't in the index.

This is display/auto-fill data only. It never feeds training: the retrain
pipeline's datasets are built separately by fetch_data_handler.py, and
nothing here is labelled. Keep it that way -- a ticker list with "current"
financials and no as-of discipline would be a leakage risk in training.

Constituent list sources, tried in order:
  NSE (undocumented sites that sometimes refuse cloud IPs, see CLAUDE.md):
    1. the official CSV on niftyindices.com,
    2. the same CSV on NSE's archive host,
  S&P 500 (S&P's own list isn't freely downloadable):
    1. the datasets/s-and-p-500-companies CSV on GitHub (maintained from
       Wikipedia's constituent table),
  then, for either:
    3. a CSV someone uploaded to s3://<MODEL_BUCKET>/<prefix>/constituents.csv
       (same columns as that universe's source), for when the sites block AWS.

Environment variables:
    MODEL_BUCKET            S3 bucket for the snapshot (required for S3 paths)
    MARKET_UNIVERSE         the job's universe when the event names none (default nse)
    MARKET_SNAPSHOT_KEY     NSE only, default market-data/nse-largemidcap250/latest.json
    CONSTITUENTS_SEED_KEY   NSE only, default market-data/nse-largemidcap250/constituents.csv
    MARKET_SNAPSHOT_PATH    local JSON file to use instead of S3 for NSE (dev/tests);
                            MARKET_SNAPSHOT_PATH_US for the S&P 500
    SNAPSHOT_WORKERS        parallel yfinance fetches in the job (default 6)
"""

import csv
import dataclasses
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

SP500_INDEX_NAME = "S&P 500"
SP500_CONSTITUENT_URLS = [
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
]

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


def parse_sp500_csv(text: str) -> list[dict]:
    """Parse the S&P 500 constituent CSV (Symbol, Security, GICS Sector,
    GICS Sub-Industry, ..., CIK) into [{symbol, name, industry, cik}].
    Symbols take Yahoo's form: class shares use a dash (BRK.B -> BRK-B)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    out = []
    seen = set()
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        symbol = row.get("Symbol", "").upper().replace(".", "-")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append({
            "symbol": symbol,
            "name": row.get("Security") or symbol,
            # GICS sector (11 values) rather than sub-industry (~120), so the
            # dashboard's industry filter stays usable.
            "industry": row.get("GICS Sector") or None,
            "cik": row.get("CIK") or None,
        })
    return out


@dataclasses.dataclass(frozen=True)
class Universe:
    id: str
    index: str                   # display name, e.g. "S&P 500"
    short_label: str             # dropdown flag, e.g. "LargeMidcap 250"
    prefix: str                  # S3 prefix for latest.json, history/, parts/, constituents.csv
    constituent_urls: tuple
    parser: Callable[[str], list]
    min_rows: int                # fewer rows than this means an error page, not the list
    yahoo_suffix: str            # appended to a symbol for yfinance (".NS"; "" for US)
    exchange: str
    # Industry labels whose banks/insurers have no current/non-current
    # balance-sheet split (see app._is_financial_balance_sheet).
    financial_industries: frozenset

    @property
    def snapshot_key(self) -> str:
        if self.id == "nse":
            return os.environ.get("MARKET_SNAPSHOT_KEY", DEFAULT_SNAPSHOT_KEY)
        return f"{self.prefix}/latest.json"

    @property
    def seed_key(self) -> str:
        if self.id == "nse":
            return os.environ.get("CONSTITUENTS_SEED_KEY", DEFAULT_SEED_KEY)
        return f"{self.prefix}/constituents.csv"

    @property
    def local_path_env(self) -> str:
        return "MARKET_SNAPSHOT_PATH" if self.id == "nse" else f"MARKET_SNAPSHOT_PATH_{self.id.upper()}"

    def part_key(self, shard: int, shards: int) -> str:
        return f"{self.prefix}/parts/part-{shard}-of-{shards}.json"


UNIVERSES: dict[str, Universe] = {
    "nse": Universe(
        id="nse", index=INDEX_NAME, short_label="LargeMidcap 250",
        prefix="market-data/nse-largemidcap250", constituent_urls=tuple(CONSTITUENT_URLS),
        parser=parse_constituents_csv, min_rows=200, yahoo_suffix=".NS", exchange="NSE",
        financial_industries=frozenset({"Financial Services"}),
    ),
    "us": Universe(
        id="us", index=SP500_INDEX_NAME, short_label="S&P 500",
        prefix="market-data/us-sp500", constituent_urls=tuple(SP500_CONSTITUENT_URLS),
        parser=parse_sp500_csv, min_rows=450, yahoo_suffix="", exchange="NYSE/Nasdaq",
        financial_industries=frozenset({"Financials"}),
    ),
}
DEFAULT_UNIVERSE = "nse"


def get_universe(universe_id: Optional[str]) -> Universe:
    """The named universe; raises KeyError for an unknown id."""
    return UNIVERSES[(universe_id or DEFAULT_UNIVERSE).strip().lower()]


def fetch_constituents(
    http_get: Optional[Callable[[str], str]] = None,
    seed_reader: Optional[Callable[[], Optional[str]]] = None,
    universe: str = DEFAULT_UNIVERSE,
) -> tuple[list[dict], str]:
    """Return (constituents, source_description). Raises RuntimeError if no
    source yields a plausible list."""
    u = get_universe(universe)
    if http_get is None:
        http_get = _http_get_text
    if seed_reader is None:
        seed_reader = lambda: _read_seed_from_s3(u.id)  # noqa: E731

    errors = []
    for url in (CONSTITUENT_URLS if u.id == "nse" else u.constituent_urls):
        try:
            rows = u.parser(http_get(url))
            # A real list has ~250 / ~500 rows; a handful means an error page.
            if len(rows) >= u.min_rows:
                return rows, url
            errors.append(f"{url}: only {len(rows)} rows")
        except Exception as e:  # network, HTTP status, parse
            errors.append(f"{url}: {e}")

    try:
        seed = seed_reader()
        if seed:
            rows = u.parser(seed)
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


def _read_seed_from_s3(universe: str = DEFAULT_UNIVERSE) -> Optional[str]:
    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError
    key = get_universe(universe).seed_key
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
    universe: str = DEFAULT_UNIVERSE,
    deadline: Optional[float] = None,
) -> dict:
    """Fetch every constituent's financials (in parallel) and assemble the
    snapshot document. A failing company is recorded with its error rather
    than failing the whole run. Past `deadline` (epoch seconds) the rest are
    recorded as skipped instead of fetched, so a slow week still writes
    what it has before Lambda's timeout kills the run."""
    u = get_universe(universe)

    def one(c: dict) -> dict:
        yahoo = f"{c['symbol']}{u.yahoo_suffix}"
        meta = {
            "symbol": c["symbol"],
            "yahoo_ticker": yahoo,
            "name": c["name"],
            "industry": c.get("industry"),
        }
        if deadline is not None and time.time() > deadline:
            rec = normalise_record({}, {**meta, "as_of": None, "currency": None})
            rec["error"] = "Skipped: the snapshot job ran out of time this week"
            return rec
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
        "index": u.index,
        "universe": u.id,
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

def save_snapshot(snapshot: dict, universe: Optional[str] = None) -> list[str]:
    """Write latest.json plus a dated copy (history for later trend charts).
    Returns the S3 keys written."""
    import boto3
    u = get_universe(universe or snapshot.get("universe"))
    bucket = os.environ["MODEL_BUCKET"]
    latest = u.snapshot_key
    dated = latest.rsplit("/", 1)[0] + f"/history/{snapshot['generated_at'][:10]}.json"
    body = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
    s3 = boto3.client("s3")
    for key in (dated, latest):
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return [dated, latest]


def _get_json(key: str) -> Optional[dict]:
    """An S3 JSON document from MODEL_BUCKET, or None if it isn't there.
    AccessDenied counts as absent: without s3:ListBucket, S3 reports a
    missing key that way."""
    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket:
        return None
    import boto3
    from botocore.exceptions import ClientError
    try:
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "AccessDenied"):
            logger.warning("s3://%s/%s not available: %s", bucket, key, e)
            return None
        raise
    return json.loads(obj["Body"].read())


def save_part(snapshot: dict, universe: str, shard: int, shards: int) -> str:
    import boto3
    key = get_universe(universe).part_key(shard, shards)
    boto3.client("s3").put_object(
        Bucket=os.environ["MODEL_BUCKET"], Key=key,
        Body=json.dumps(snapshot, separators=(",", ":")).encode("utf-8"), ContentType="application/json")
    return key


def merge_parts(parts: list[dict], universe: str) -> dict:
    """One snapshot from shard parts. A company in two parts (the list
    changed between weeks and one shard failed) keeps its newer record."""
    u = get_universe(universe)
    parts = sorted(parts, key=lambda p: p.get("generated_at") or "")
    by_symbol: dict[str, dict] = {}
    for p in parts:  # oldest first, so newer records overwrite
        for c in p.get("companies", []):
            by_symbol[c["symbol"]] = c
    companies = sorted(by_symbol.values(), key=lambda r: r["symbol"])
    newest = parts[-1]
    return {
        "index": u.index,
        "universe": u.id,
        "generated_at": newest["generated_at"],
        "constituents_source": newest.get("constituents_source"),
        "data_source": newest.get("data_source"),
        "count": len(companies),
        "complete_count": sum(1 for r in companies if r["complete"]),
        "parts": [{"shard": (p.get("shard") or {}).get("index"), "generated_at": p.get("generated_at"),
                   "count": p.get("count")} for p in parts],
        "companies": companies,
    }


def merge_parts_from_s3(universe: str, shards: int) -> Optional[dict]:
    """Merge every part once all `shards` exist (the first week, until the
    last shard has run, there is nothing to merge). Later weeks merge after
    each shard, so latest.json gets fresher shard by shard."""
    u = get_universe(universe)
    parts = [_get_json(u.part_key(i, shards)) for i in range(shards)]
    if any(p is None for p in parts):
        return None
    return merge_parts(parts, u.id)


def shard_constituents(constituents: list[dict], shard: int, shards: int) -> list[dict]:
    """Every shards-th constituent by symbol, so shard sizes differ by at
    most one and a company stays in the same shard while the list is
    unchanged."""
    ordered = sorted(constituents, key=lambda c: c["symbol"])
    return [c for i, c in enumerate(ordered) if i % shards == shard]


_SNAPSHOT_TTL_SECONDS = 3600
# One cache per universe. _snapshot_cache is NSE's, kept as a module name
# because tests reset it directly.
_snapshot_cache: dict = {"value": None, "loaded_at": 0.0}
_snapshot_caches: dict[str, dict] = {
    uid: (_snapshot_cache if uid == "nse" else {"value": None, "loaded_at": 0.0}) for uid in UNIVERSES
}
_snapshot_lock = threading.Lock()


def load_snapshot(force: bool = False, universe: str = DEFAULT_UNIVERSE) -> Optional[dict]:
    """The latest snapshot, or None if the job hasn't produced one yet.
    Cached for an hour per warm Lambda container."""
    u = get_universe(universe)
    cache = _snapshot_caches[u.id]
    with _snapshot_lock:
        fresh = time.time() - cache["loaded_at"] < _SNAPSHOT_TTL_SECONDS
        if not force and fresh and cache["loaded_at"]:
            return cache["value"]
        value = _read_snapshot(u)
        cache.update(value=value, loaded_at=time.time())
        return value


def _read_snapshot(u: Optional[Universe] = None) -> Optional[dict]:
    u = u or get_universe(DEFAULT_UNIVERSE)
    local = os.environ.get(u.local_path_env)
    if local:
        if not os.path.exists(local):
            return None
        with open(local) as f:
            return json.load(f)
    if u.id != "nse" and os.environ.get("MARKET_SNAPSHOT_PATH"):
        return None  # local dev/tests with only an NSE file: don't reach for S3
    return _get_json(u.snapshot_key)


def find_company(snapshot: Optional[dict], symbol: str) -> Optional[dict]:
    if not snapshot:
        return None
    u = get_universe(snapshot.get("universe"))
    s = symbol.upper()
    if u.yahoo_suffix:
        s = s.removesuffix(u.yahoo_suffix)
    else:
        s = s.replace(".", "-")  # BRK.B as typed -> BRK-B as stored
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
# Company search (ticker or name) for the dashboard's ticker box
# --------------------------------------------------------------------------

# Ticker-style matching starts at 3 characters, name matching at 5 -- short
# name fragments ("tat", "ind") would match half the market.
MIN_TICKER_QUERY = 3
MIN_NAME_QUERY = 5
MAX_SEARCH_RESULTS = 15
_QUERY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &.\-']{2,39}$")
_SEARCH_TTL_SECONDS = 6 * 3600
_search_cache: dict[str, tuple[float, list[dict]]] = {}


def normalise_query(raw: str) -> Optional[str]:
    q = " ".join((raw or "").split())
    return q if _QUERY_RE.match(q) else None


def _index_matches(snapshot: Optional[dict], q: str) -> list[dict]:
    return [r for _, _, r in _ranked_index_matches(snapshot, q)]


def _ranked_index_matches(snapshot: Optional[dict], q: str) -> list[tuple]:
    if not snapshot:
        return []
    u = get_universe(snapshot.get("universe"))
    qu = q.upper()
    by_name = len(q) >= MIN_NAME_QUERY
    ranked = []
    for c in snapshot.get("companies", []):
        sym, name = c["symbol"], c["name"].upper()
        if sym == qu:
            rank = 0
        elif sym.startswith(qu):
            rank = 1
        elif by_name and name.startswith(qu):
            rank = 2
        elif qu in sym:
            rank = 3
        elif by_name and qu in name:
            rank = 4
        else:
            continue
        ranked.append((rank, sym, {
            "symbol": sym,
            "yahoo_ticker": c["yahoo_ticker"],
            "name": c["name"],
            "exchange": u.exchange,
            "industry": c.get("industry"),
            "in_index": True,
            "has_financials": bool(c.get("complete")),
            "universe": u.id,
            "index_label": u.short_label,
        }))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return ranked


def _dedupe_key(yahoo_ticker: str) -> str:
    """The same Indian company on NSE (.NS) and BSE (.BO) is one company;
    anything else is identified by its exact Yahoo ticker (so NSE's HAL,
    Hindustan Aeronautics, and NYSE's HAL, Halliburton, both stay)."""
    root, _, suffix = yahoo_ticker.upper().partition(".")
    return f"IN:{root}" if suffix in ("NS", "BO") else yahoo_ticker.upper()


def yahoo_search(q: str) -> list[dict]:
    """Yahoo Finance's own search (ticker or company name). Raw quotes, each
    with symbol, longname/shortname, exchDisp, quoteType; _online_matches
    keeps the equities."""
    import yfinance as yf
    s = yf.Search(q, max_results=10, news_count=0, lists_count=0, include_cb=False,
                  recommended=0, timeout=8, raise_errors=True)
    return list(s.quotes or [])


def _online_matches(q: str, searcher: Callable[[str], list[dict]], timeout_seconds: float) -> list[dict]:
    key = q.lower()
    hit = _search_cache.get(key)
    if hit and time.time() - hit[0] < _SEARCH_TTL_SECONDS:
        return hit[1]
    quotes = _lookup_pool.submit(searcher, q).result(timeout=timeout_seconds)
    qu = q.upper()
    out = []
    for x in quotes:
        # Equities only: Yahoo also returns funds, indices, futures, crypto.
        if x.get("quoteType") != "EQUITY" or not x.get("symbol"):
            continue
        yahoo = str(x["symbol"]).upper()
        root = yahoo.split(".")[0]
        # Below the name threshold only ticker-like matches count, so a
        # 3-letter query doesn't return whatever names Yahoo associates.
        if len(q) < MIN_NAME_QUERY and qu not in root:
            continue
        out.append({
            "symbol": root,
            "yahoo_ticker": yahoo,
            "name": x.get("longname") or x.get("shortname") or yahoo,
            "exchange": x.get("exchDisp") or x.get("exchange"),
            "industry": x.get("industry") or x.get("sectorDisp") or None,
            "in_index": False,
            "has_financials": None,  # unknown until fetched
            "universe": None,
            "index_label": None,
        })
    _search_cache[key] = (time.time(), out)
    return out


def search_companies(
    q: str,
    snapshot,
    searcher: Optional[Callable[[str], list[dict]]] = None,
    timeout_seconds: float = 8.0,
) -> dict:
    """Index constituents first (from the weekly snapshots, instant), then
    Yahoo Finance matches not already listed. `snapshot` is one snapshot or
    a list of them (NSE, S&P 500): index matches are ranked together, NSE
    before the S&P 500 at equal rank. If Yahoo is slow or down the index
    matches are still returned, with online_ok=False."""
    if searcher is None:
        searcher = yahoo_search  # looked up at call time, so tests can patch it
    snapshots = snapshot if isinstance(snapshot, list) else [snapshot]
    ranked = []
    for order, snap in enumerate(snapshots):
        ranked += [(rank, order, sym, r) for rank, sym, r in _ranked_index_matches(snap, q)]
    ranked.sort(key=lambda t: t[:3])
    results = [r for *_, r in ranked]

    online_ok = True
    try:
        online = _online_matches(q, searcher, timeout_seconds)
    except Exception as e:  # timeout, network, Yahoo format change
        logger.warning("Online search failed for %r: %s", q, e)
        online, online_ok = [], False

    seen = {_dedupe_key(r["yahoo_ticker"]) for r in results}
    for r in online:
        # The same company on NSE (.NS) and BSE (.BO) is listed once: NSE first.
        key = _dedupe_key(r["yahoo_ticker"])
        if key in seen:
            continue
        seen.add(key)
        results.append(r)
    return {"query": q, "results": results[:MAX_SEARCH_RESULTS], "online_ok": online_ok}


# --------------------------------------------------------------------------
# Lambda entry point for the weekly job
# --------------------------------------------------------------------------

MAX_SHARDS = 10
# Stop starting fetches this long before Lambda's timeout, leaving time to
# write the part and merge.
_DEADLINE_MARGIN_SECONDS = 90


def snapshot_handler(event, context):
    """Event (all optional): {"universe": "nse"|"us", "shard": i, "shards": N}.
    shards=1 (the default) fetches the whole list and writes latest.json;
    shards>1 fetches every N-th company, writes its part, then merges."""
    event = event if isinstance(event, dict) else {}
    u = get_universe(event.get("universe") or os.environ.get("MARKET_UNIVERSE"))
    shards = int(event.get("shards", 1))
    shard = int(event.get("shard", 0))
    if not (1 <= shards <= MAX_SHARDS and 0 <= shard < shards):
        raise ValueError(f"Bad shard {shard} of {shards}")

    deadline = None
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        deadline = time.time() + context.get_remaining_time_in_millis() / 1000 - _DEADLINE_MARGIN_SECONDS

    constituents, source = fetch_constituents(universe=u.id)
    mine = shard_constituents(constituents, shard, shards) if shards > 1 else constituents
    workers = int(os.environ.get("SNAPSHOT_WORKERS", "6"))
    snapshot = build_snapshot(mine, source, workers=workers, universe=u.id, deadline=deadline)

    if shards == 1:
        keys = save_snapshot(snapshot, u.id)
        merged = None
    else:
        snapshot["shard"] = {"index": shard, "of": shards}
        keys = [save_part(snapshot, u.id, shard, shards)]
        merged = merge_parts_from_s3(u.id, shards)
        if merged:
            keys += save_snapshot(merged, u.id)

    summary = {
        "universe": u.id,
        "shard": f"{shard + 1} of {shards}",
        "constituents_source": source,
        "count": snapshot["count"],
        "complete_count": snapshot["complete_count"],
        "errors": sum(1 for c in snapshot["companies"] if c.get("error")),
        "skipped_for_time": sum(1 for c in snapshot["companies"]
                                if (c.get("error") or "").startswith("Skipped")),
        "merged_count": merged["count"] if merged else None,
        "s3_keys": keys,
    }
    logger.info("%s snapshot written: %s", u.index, summary)
    return summary
