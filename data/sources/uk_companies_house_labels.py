"""
UK distress labels via Companies House -- the UK's official company registry.

*** THIS IS A DELIBERATELY PARTIAL WORKED EXAMPLE OF THE PLUGIN PATTERN ***
It demonstrates that not every market is equally easy to add. Read the two
halves below before assuming this "just works" like the US module does.

THE LABEL SIDE IS GENUINELY CLEAN AND FREE:
Companies House's API (api.company-information.service.gov.uk) exposes a
`company_status` field with real values including "liquidation",
"administration", "receivership", and "voluntary-arrangement" -- a
structured signal comparable in quality to SEC EDGAR's Item 1.03. A free
API key (instant, no approval wait) is all that's needed:
https://developer.company-information.service.gov.uk/

THE FINANCIALS SIDE IS THE HONEST GAP:
Unlike SEC EDGAR's XBRL company-facts API (which returns tagged financial
figures as plain JSON), Companies House's filed "accounts" are documents
(iXBRL or PDF) attached to a filing, not queryable structured fields via
this API. Extracting total_assets/liabilities/etc. from them requires
parsing iXBRL documents -- a real, separate piece of work (libraries like
`python-xbrl` or `arelle` exist for this) that this module does NOT
implement. `_fetch_financials_stub` below returns all-None financials on
purpose, so records from this module will currently be filtered out by the
same has_complete_financials() check used consistently by every market
module -- this module proves the LABEL half of the plugin contract works,
and marks the financials half as a clearly-flagged TODO rather than faking it.

This is intentional: a market plugin that returns confidently-wrong
financials would be far worse than one that honestly returns nothing yet.
"""

import os
import sys
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

MARKET_CODE = "uk"
MARKET_LABEL = "United Kingdom (Companies House)"
MARKET_REGION = "Europe"

API_BASE = "https://api.company-information.service.gov.uk"
DISTRESS_STATUSES = ["liquidation", "administration", "receivership", "voluntary-arrangement"]


def add_cli_args(parser) -> None:
    """Registers this market's own CLI arguments onto the shared parser --
    part of the plugin contract, see data/build_dataset.py."""
    group = parser.add_argument_group(f"{MARKET_LABEL} options")
    group.add_argument("--uk-api-key", default=os.environ.get("COMPANIES_HOUSE_API_KEY"),
                        help="Free key from developer.company-information.service.gov.uk, "
                             "or set COMPANIES_HOUSE_API_KEY")
    group.add_argument("--uk-n-distressed", type=int, default=30)
    group.add_argument("--uk-n-healthy", type=int, default=30)


def _search_by_status(api_key: str, status: str, max_results: int) -> list[dict]:
    """Companies House's advanced search, filtered by company_status."""
    resp = requests.get(
        f"{API_BASE}/advanced-search/companies",
        params={"company_status": status, "size": min(max_results, 100)},
        auth=(api_key, ""),  # HTTP Basic auth: API key as username, blank password
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def find_distressed_companies(api_key: str, max_results: int = 30) -> list[dict]:
    results = []
    per_status = max(1, max_results // len(DISTRESS_STATUSES))
    for status in DISTRESS_STATUSES:
        items = _search_by_status(api_key, status, per_status)
        for item in items:
            results.append({
                "company_number": item.get("company_number"),
                "company_name": item.get("company_name"),
                "status": status,
            })
        time.sleep(0.3)
    return results[:max_results]


def find_healthy_companies(api_key: str, max_results: int = 30) -> list[dict]:
    items = _search_by_status(api_key, "active", max_results)
    return [{"company_number": i.get("company_number"), "company_name": i.get("company_name"),
              "status": "active"} for i in items]


def _fetch_financials_stub(company_number: str) -> dict:
    """DELIBERATELY UNIMPLEMENTED -- see module docstring. Returns the same
    dict shape as edgar_client.py/nse_client.py so downstream code doesn't
    need to know this market is incomplete, but every value is None until
    someone implements iXBRL parsing of this company's filed accounts."""
    return {
        "total_assets": None, "total_liabilities": None,
        "current_assets": None, "current_liabilities": None,
        "retained_earnings": None, "ebit": None, "sales": None,
    }


def build_uk_labeled_dataset(api_key: str, n_distressed: int = 30, n_healthy: int = 30) -> list[dict]:
    if not api_key:
        raise ValueError(
            "No Companies House API key provided. Get a free one (instant, no "
            "approval wait) at https://developer.company-information.service.gov.uk/ "
            "and pass --uk-api-key or set COMPANIES_HOUSE_API_KEY."
        )

    print("Searching Companies House for distressed companies "
          f"(statuses: {', '.join(DISTRESS_STATUSES)})...")
    distressed = find_distressed_companies(api_key, n_distressed)
    print(f"  Found {len(distressed)} candidates")

    print("Searching for a healthy comparison sample...")
    healthy = find_healthy_companies(api_key, n_healthy)
    print(f"  Found {len(healthy)} candidates")

    records = []
    for c in distressed:
        records.append({
            "ticker": f"UK-{c['company_number']}",
            "company_name": c["company_name"],
            "market": "UK",
            "financials": _fetch_financials_stub(c["company_number"]),
            "headlines": [f"{c['company_name']}: entered {c['status']}"],
            "label_distressed": 1,
            "event_date": None,  # not fetched in this stub -- see docstring
            "source": f"Companies House company_status={c['status']}",
        })
    for c in healthy:
        records.append({
            "ticker": f"UK-{c['company_number']}",
            "company_name": c["company_name"],
            "market": "UK",
            "financials": _fetch_financials_stub(c["company_number"]),
            "headlines": [],
            "label_distressed": 0,
            "event_date": None,
            "source": "Companies House company_status=active",
        })

    print(f"\nNOTE: all {len(records)} UK records have financials=None (see module "
          f"docstring) -- they will be filtered out by build_dataset.py's usual "
          f"'skip if no financials' check until iXBRL parsing is implemented.")
    return records


def build(args) -> list[dict]:
    """Plugin entry point -- see data/build_dataset.py's MARKET_REGISTRY."""
    return build_uk_labeled_dataset(
        api_key=args.uk_api_key,
        n_distressed=args.uk_n_distressed, n_healthy=args.uk_n_healthy,
    )
