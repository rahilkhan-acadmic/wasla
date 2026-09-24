"""
Real US distress labels, sourced from SEC EDGAR's full-text search.

Key insight: Form 8-K Item 1.03 is SPECIFICALLY reserved for "Bankruptcy or
Receivership" -- a company checking this item is making a structured,
unambiguous disclosure that it has filed for bankruptcy. This is a much
cleaner signal than trying to detect distress from language in a 10-K, and
it's free and public.

Docs: https://www.sec.gov/edgar/search/ (the UI); this module uses the same
full-text search API that UI calls, https://efts.sec.gov/LATEST/search-index

IMPORTANT LIMITATIONS (read before treating this as a finished dataset):
  - EDGAR full-text search only indexes filings from 2001 onward.
  - Item 1.03 filing =/= the company necessarily delisted or fully failed --
    some emerge from Chapter 11 reorganization and continue trading. Treat
    "filed Item 1.03" as "entered financial distress", which is what this
    project is actually trying to predict -- not necessarily "ceased to exist".
  - This needs real internet access to efts.sec.gov / data.sec.gov -- it will
    NOT work in network-sandboxed environments. Run it on your own machine.
  - Respect SEC's rate limits (this module sleeps between requests).
"""

import os
import sys
import time
import json
import requests
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from edgar_client import HEADERS, fetch_financials_for_cik  # noqa: E402
from features import has_complete_financials  # noqa: E402

FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def _search_full_text(query: str, forms: str, start_date: str, end_date: str,
                       from_offset: int = 0) -> dict:
    """One page of EDGAR full-text search results.

    dateRange/startdt/enddt filter by filing date; forms filters by form type.
    """
    params = {
        "q": query,
        "forms": forms,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "from": from_offset,
    }
    resp = requests.get(FULL_TEXT_SEARCH_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def find_bankruptcy_filings(start_date: str, end_date: str, max_results: int = 200) -> list[dict]:
    """Returns a list of {cik, company_name, filing_date, accession_no} for
    every 8-K Item 1.03 (bankruptcy) filing in the given date range.

    EDGAR full-text search doesn't have a direct "item number" filter, so we
    search for the item's own label text within 8-K filings -- this is the
    standard workaround and is what the item actually looks like verbatim in
    every properly-formatted 8-K that checks this box.
    """
    results = []
    offset = 0
    while len(results) < max_results:
        page = _search_full_text(
            query='"Item 1.03" "Bankruptcy or Receivership"',
            forms="8-K",
            start_date=start_date,
            end_date=end_date,
            from_offset=offset,
        )
        hits = page.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            cik_raw = source.get("ciks", [None])[0]
            if cik_raw is None:
                continue
            results.append({
                "cik": int(cik_raw),
                "company_name": source.get("display_names", [""])[0],
                "filing_date": source.get("file_date"),
                "accession_no": hit.get("_id"),
            })

        offset += len(hits)
        time.sleep(0.2)  # stay well under SEC's rate limit
        if len(hits) < 10:  # fewer than a full page -- we've reached the end
            break

    return results[:max_results]


def find_healthy_sample(start_date: str, end_date: str, exclude_ciks: set[int],
                         max_results: int = 200) -> list[dict]:
    """Returns companies that filed a normal annual 10-K in the same window,
    excluding any CIK already flagged as a bankruptcy filer.

    This is the "healthy" comparison class. Sourcing it from EDGAR itself
    (rather than a hand-picked list of well-known large caps) matters for
    survivorship bias: a hardcoded list of "well-known healthy companies"
    implicitly only include survivors, i.e., a leaky proxy for the very
    thing we're trying to predict.
    """
    results = []
    offset = 0
    while len(results) < max_results:
        page = _search_full_text(
            query="",  # any 10-K in the window
            forms="10-K",
            start_date=start_date,
            end_date=end_date,
            from_offset=offset,
        )
        hits = page.get("hits", {}).get("hits", [])
        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})
            cik_raw = source.get("ciks", [None])[0]
            if cik_raw is None:
                continue
            cik = int(cik_raw)
            if cik in exclude_ciks:
                continue
            results.append({
                "cik": cik,
                "company_name": source.get("display_names", [""])[0],
                "filing_date": source.get("file_date"),
            })

        offset += len(hits)
        time.sleep(0.2)
        if len(hits) < 10:
            break

    return results[:max_results]


def build_us_labeled_dataset(start_date: str, end_date: str,
                              n_distressed: int = 30, n_healthy: int = 30,
                              polite_delay: float = 0.2) -> list[dict]:
    """End-to-end: find real bankruptcy events + a healthy sample from the
    same period, pull EACH company's financials AS OF just before its event
    date (or, for healthy companies, as of their filing date), and return
    records in the same schema as data/sample_companies.json.
    """
    print(f"Searching for bankruptcy filings ({start_date} to {end_date})...")
    bankruptcies = find_bankruptcy_filings(start_date, end_date, max_results=n_distressed * 2)
    print(f"  Found {len(bankruptcies)} candidate bankruptcy filings")

    exclude = {b["cik"] for b in bankruptcies}
    print("Searching for a healthy comparison sample...")
    healthy = find_healthy_sample(start_date, end_date, exclude, max_results=n_healthy * 2)
    print(f"  Found {len(healthy)} candidate healthy filers")

    records = []

    for b in bankruptcies[:n_distressed]:
        try:
            fin = fetch_financials_for_cik(b["cik"], polite_delay=polite_delay,
                                            as_of_date=b["filing_date"])
            if not has_complete_financials(fin):
                continue  # no usable data for this CIK -- skip rather than guess
            records.append({
                "ticker": f"US-CIK{b['cik']}",
                "company_name": b["company_name"],
                "market": "US",
                "financials": fin,
                "headlines": [f"{b['company_name']} files for bankruptcy protection."],
                "label_distressed": 1,
                "event_date": b["filing_date"],
                "source": "SEC EDGAR 8-K Item 1.03",
            })
        except Exception as e:
            print(f"  Skipping CIK {b['cik']} ({b['company_name']}): {e}")

    for h in healthy[:n_healthy]:
        try:
            fin = fetch_financials_for_cik(h["cik"], polite_delay=polite_delay,
                                            as_of_date=h["filing_date"])
            if not has_complete_financials(fin):
                continue
            records.append({
                "ticker": f"US-CIK{h['cik']}",
                "company_name": h["company_name"],
                "market": "US",
                "financials": fin,
                "headlines": [],
                "label_distressed": 0,
                "event_date": h["filing_date"],
                "source": "SEC EDGAR 10-K (no bankruptcy filing found)",
            })
        except Exception as e:
            print(f"  Skipping CIK {h['cik']} ({h['company_name']}): {e}")

    return records


MARKET_CODE = "us"
MARKET_LABEL = "United States (SEC EDGAR)"
MARKET_REGION = "Americas"


def add_cli_args(parser) -> None:
    """Registers this market's own CLI arguments onto the shared parser --
    part of the plugin contract, see data/build_dataset.py."""
    group = parser.add_argument_group(f"{MARKET_LABEL} options")
    group.add_argument("--us-start-date", default="2015-01-01")
    group.add_argument("--us-end-date", default=None,
                        help="YYYY-MM-DD; defaults to today, so scheduled/automated "
                             "runs keep picking up newly-filed bankruptcies over time")
    group.add_argument("--us-n-distressed", type=int, default=30)
    group.add_argument("--us-n-healthy", type=int, default=30)


def build(args) -> list[dict]:
    """Plugin entry point -- see data/build_dataset.py's MARKET_REGISTRY."""
    end_date = args.us_end_date or date.today().isoformat()
    return build_us_labeled_dataset(
        start_date=args.us_start_date, end_date=end_date,
        n_distressed=args.us_n_distressed, n_healthy=args.us_n_healthy,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2015-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--n-distressed", type=int, default=30)
    parser.add_argument("--n-healthy", type=int, default=30)
    parser.add_argument("--out", default="us_real_labels.json")
    args = parser.parse_args()

    data = build_us_labeled_dataset(args.start_date, args.end_date,
                                     args.n_distressed, args.n_healthy)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {len(data)} labeled US companies to {args.out}")
