"""
Minimal SEC EDGAR client.

SEC EDGAR's XBRL "company facts" API gives you structured financial statement
data (assets, liabilities, revenue, etc.) for any public filer -- for free,
no API key required. This is the best free source of ground-truth fundamentals
for penny stocks and small caps, since most other financial data APIs either
don't cover micro-caps or charge for that tier.

Docs: https://www.sec.gov/edgar/sec-api-documentation

IMPORTANT:
  - SEC requires a descriptive User-Agent header identifying you/your app,
    or requests will be rejected. Set EDGAR_USER_AGENT below or via env var.
  - This module needs outbound internet access to www.sec.gov / data.sec.gov.
    It will NOT work in network-sandboxed environments -- run it on your own
    machine or server where that's reachable.
  - Respect SEC's rate limits (max ~10 requests/second, be conservative).
"""

import os
import time
import requests
from typing import Optional

EDGAR_USER_AGENT = os.environ.get(
    "EDGAR_USER_AGENT", "FinanceDistressResearch you@example.com"
)
HEADERS = {"User-Agent": EDGAR_USER_AGENT}

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json"

# US-GAAP XBRL tags we need to build Financials -- companies vary slightly in
# which tags they use, so a few common aliases are listed per concept.
TAG_ALIASES = {
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "ebit": ["OperatingIncomeLoss"],
    "sales": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
}


def _get_ticker_to_cik_map() -> dict:
    resp = requests.get(TICKER_MAP_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # data is like {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    return {v["ticker"].upper(): v["cik_str"] for v in data.values()}


def get_cik_for_ticker(ticker: str, ticker_map: Optional[dict] = None) -> int:
    ticker_map = ticker_map or _get_ticker_to_cik_map()
    cik = ticker_map.get(ticker.upper())
    if cik is None:
        raise ValueError(f"Ticker {ticker!r} not found in SEC ticker map")
    return cik


def _latest_annual_value(facts_for_tag: dict, as_of_date: Optional[str] = None,
                          min_filing_lag_days: int = 0) -> Optional[float]:
    """Pull the most recent 10-K (annual, form='10-K') value for a US-GAAP tag.

    `as_of_date` (YYYY-MM-DD) is critical for building a leakage-free distress
    dataset: without it, this returns the company's LATEST EVER filing, which
    for a company that later failed would include financials filed AFTER the
    failure event -- silently teaching the model to "predict" distress using
    information that didn't exist yet at prediction time. When set, only
    filings with a `filed` date on or before `as_of_date` are considered.
    """
    best = None
    for unit_values in facts_for_tag.get("units", {}).values():
        for entry in unit_values:
            if entry.get("form") != "10-K":
                continue
            filed = entry.get("filed")
            if as_of_date is not None and filed is not None and filed > as_of_date:
                continue
            if best is None or entry["end"] > best["end"]:
                best = entry
    return best["val"] if best else None


def get_company_facts(cik: int) -> dict:
    url = COMPANY_FACTS_URL.format(cik=cik)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def extract_financials_dict(raw_facts: dict, as_of_date: Optional[str] = None) -> dict:
    """Map raw EDGAR companyfacts JSON down to the fields Financials needs.

    Pass `as_of_date` (YYYY-MM-DD) when building historical/labeled training
    data, so only filings that existed as of that date are used -- see
    `_latest_annual_value` docstring for why this matters.

    Returns a plain dict (not yet a Financials object) since market value of
    equity has to be supplied separately from a price source (EDGAR doesn't
    have live share prices).
    """
    us_gaap = raw_facts.get("facts", {}).get("us-gaap", {})
    out = {}
    for field, tags in TAG_ALIASES.items():
        value = None
        for tag in tags:
            if tag in us_gaap:
                value = _latest_annual_value(us_gaap[tag], as_of_date=as_of_date)
                if value is not None:
                    break
        out[field] = value
    return out


def fetch_financials_for_ticker(ticker: str, ticker_map: Optional[dict] = None,
                                 polite_delay: float = 0.15,
                                 as_of_date: Optional[str] = None) -> dict:
    """End-to-end: ticker -> CIK -> company facts -> extracted financial fields.

    `polite_delay` sleeps briefly between requests to stay well under SEC's
    rate limit when calling this in a loop over many tickers. Pass
    `as_of_date` for historical/labeled data -- see extract_financials_dict.
    """
    cik = get_cik_for_ticker(ticker, ticker_map)
    time.sleep(polite_delay)
    raw = get_company_facts(cik)
    return extract_financials_dict(raw, as_of_date=as_of_date)


def fetch_financials_for_cik(cik: int, polite_delay: float = 0.15,
                              as_of_date: Optional[str] = None) -> dict:
    """Same as fetch_financials_for_ticker, but starting from a CIK directly --
    useful when the data came from EDGAR full-text search, which returns CIKs,
    not tickers (some filers, especially distressed/delisted ones, may have no
    current ticker at all)."""
    time.sleep(polite_delay)
    raw = get_company_facts(cik)
    return extract_financials_dict(raw, as_of_date=as_of_date)


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) != 2:
        print("Usage: python edgar_client.py TICKER")
        sys.exit(1)

    ticker = sys.argv[1]
    fields = fetch_financials_for_ticker(ticker)
    print(json.dumps(fields, indent=2))
