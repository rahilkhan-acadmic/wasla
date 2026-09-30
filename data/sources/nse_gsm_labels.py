"""
India distress labels via NSE's GSM (Graded Surveillance Measure) list --
a genuinely better fit for this project than the manually curated CSV in
india_labels.py, for two reasons:

1. GSM's criteria are objectively about weak fundamentals, published by
   SEBI/NSE itself: net worth <= Rs 10 crore, net fixed assets <= Rs 25
   crore, and PE > 2x the Nifty 500 benchmark (or negative PE). This is
   comparable in spirit to China's ST system or the US's Item 1.03 -- an
   official, criteria-based distress flag, not something inferred -- and
   it's specifically about SMALL, weak companies (this project's actual
   penny-stock focus), unlike india_labels.py's mega-cap examples
   (Jet Airways, Reliance Communications, DHFL).

2. GSM-flagged companies are, by definition, STILL ACTIVELY LISTED AND
   TRADING (under enhanced surveillance, not delisted) -- unlike the mostly
   fully-delisted companies in the manual CSV, which is exactly why only
   2 of 8 of those returned usable yfinance data in practice. GSM companies
   should have far better yfinance coverage.

*** WHAT'S CONFIRMED, AND WHAT ISN'T ***

CONFIRMED via a live browser DevTools capture (2026-09-25): the endpoint is
`https://www.nseindia.com/api/reportGSM`, returning a flat JSON array (not
nested under a "data" key) with real fields `symbol`, `companyName`,
`gsmStage`, `survDesc`, `survCode`. The parsing logic below was tested
directly against that real captured response, correctly extracting fields
and prioritizing IBC-flagged (actual insolvency proceedings) entries above
plain GSM (weak-fundamentals) ones -- confirmed with two genuine IBC cases
in that response (AGS Transact, Ankit Metal & Power) sorting correctly to
the top.

STILL UNCONFIRMED: whether the `requests`-based session-bootstrap approach
below (visit homepage, then call the API) actually succeeds programmatically
against NSE's bot protection. The browser capture succeeded because it's a
real browser with a full session, TLS fingerprint, and any JS challenges
already resolved -- a plain Python `requests` session may still be blocked
even with the correct URL. If `_get_nse_session()` gets rejected, check
`nsepython`'s or `jugaad-data`'s current source for whatever additional
headers/cookie handling they use to get past this.


Healthy comparison companies are reused from india_labels.py's existing CSV
(the large-cap examples that reliably return yfinance data), rather than
inventing a third, even-less-certain "broad NSE universe" endpoint.
"""

import os
import sys
import csv
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from nse_client import fetch_financials_for_ticker  # noqa: E402
from features import has_complete_financials  # noqa: E402

MARKET_CODE = "india_gsm"
MARKET_LABEL = "India GSM-flagged companies (NSE surveillance)"
MARKET_REGION = "Indian Subcontinent"

# NSE requires a session cookie from the homepage before its API endpoints
# respond -- calling the API cold, without this, typically returns a 401/403.
NSE_HOMEPAGE = "https://www.nseindia.com"
NSE_GSM_API = "https://www.nseindia.com/api/reportGSM"  # confirmed via live browser DevTools capture

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/reports/gsm",
}

DEFAULT_HEALTHY_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "india_distress_labels.csv")


def add_cli_args(parser) -> None:
    """Registers this market's own CLI arguments onto the shared parser --
    part of the plugin contract, see data/build_dataset.py."""
    group = parser.add_argument_group(f"{MARKET_LABEL} options")
    group.add_argument("--gsm-n-distressed", type=int, default=20,
                        help="Max number of GSM-flagged companies to fetch financials for")
    group.add_argument("--gsm-healthy-csv", default=DEFAULT_HEALTHY_CSV,
                        help="CSV to pull healthy comparison companies from (reuses india_labels.py's format)")


def _get_nse_session() -> requests.Session:
    """NSE's standard cookie-bootstrap workaround: hit the homepage first so
    the server issues session cookies, then reuse that session for the API
    call. Without this step, the API typically rejects the request outright."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    session.get(NSE_HOMEPAGE, timeout=15)  # response content unused -- only need the cookies it sets
    time.sleep(1)  # give the session a moment before the real request, be polite
    return session


def fetch_gsm_list(max_results: int = 20) -> list[dict]:
    """Returns [{symbol, company_name, stage}, ...] for currently GSM-flagged
    companies, prioritizing companies explicitly flagged under India's
    Insolvency and Bankruptcy Code (IBC) -- an even cleaner distress signal
    than plain GSM (which can also include companies flagged for merely weak
    fundamentals, not necessarily active insolvency proceedings).

    Response shape confirmed via a live browser DevTools capture against
    https://www.nseindia.com/api/reportGSM: a flat JSON array (not nested
    under a "data" key), each entry shaped like:
        {"symbol": "AGSTRA", "companyName": "AGS Transact Technologies Limited",
         "gsmStage": "LXII", "survDesc": "Insolvency and Bankruptcy Code (IBC) -
         Receipt of Disclosure or Recommenced scrip and GSM stage 0", ...}
    """
    session = _get_nse_session()
    resp = session.get(NSE_GSM_API, timeout=15)
    resp.raise_for_status()
    rows = resp.json()  # confirmed: flat array, not nested under "data"

    results = []
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        desc = row.get("survDesc", "")
        results.append({
            "symbol": symbol,
            "company_name": row.get("companyName", symbol),
            "stage": desc or row.get("gsmStage", "GSM"),
            "is_ibc": "IBC" in desc or "Insolvency" in desc,
        })

    # IBC-flagged (actual insolvency proceedings) first -- the strongest,
    # cleanest signal in this list -- then everything else.
    results.sort(key=lambda r: not r["is_ibc"])
    return results[:max_results]


def _load_healthy_from_csv(csv_path: str) -> list[dict]:
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["label_distressed"] == "0"]


def build_india_gsm_dataset(n_distressed: int, healthy_csv: str) -> list[dict]:
    print("Fetching current GSM list from NSE...")
    try:
        gsm_companies = fetch_gsm_list(max_results=n_distressed)
        print(f"  Found {len(gsm_companies)} GSM-flagged companies")
    except Exception as e:
        print(f"  Could not fetch GSM list ({e}). This endpoint is unverified -- "
              f"see this module's docstring for how to find the current one.")
        gsm_companies = []

    healthy_rows = _load_healthy_from_csv(healthy_csv)
    print(f"Using {len(healthy_rows)} healthy comparison companies from {healthy_csv}")

    records = []

    for c in gsm_companies:
        ticker = f"{c['symbol']}.NS"
        try:
            fin = fetch_financials_for_ticker(ticker)
            if not has_complete_financials(fin):
                print(f"  Skipping {ticker}: incomplete financials")
                continue
            records.append({
                "ticker": ticker,
                "company_name": c["company_name"],
                "market": "india_gsm",
                "financials": fin,
                "headlines": [],  # deliberately empty -- see tests/test_no_label_derived_headlines.py
                "label_distressed": 1,
                "event_date": None,
                "source": f"NSE GSM {c['stage']}",
            })
        except Exception as e:
            print(f"  Skipping {ticker}: {e}")

    for row in healthy_rows:
        ticker = row["ticker"]
        try:
            fin = fetch_financials_for_ticker(ticker)
            if not has_complete_financials(fin):
                print(f"  Skipping {ticker}: incomplete financials")
                continue
            records.append({
                "ticker": ticker,
                "company_name": row["company_name"],
                "market": "india_gsm",
                "financials": fin,
                "headlines": [],  # deliberately empty -- see tests/test_no_label_derived_headlines.py
                "label_distressed": 0,
                "event_date": row["event_date"],
                "source": row["source"],
            })
        except Exception as e:
            print(f"  Skipping {ticker}: {e}")

    return records


def build(args) -> list[dict]:
    """Plugin entry point -- see data/build_dataset.py's MARKET_REGISTRY."""
    return build_india_gsm_dataset(
        n_distressed=args.gsm_n_distressed,
        healthy_csv=args.gsm_healthy_csv,
    )
