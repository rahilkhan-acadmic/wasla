"""
Loads data/sources/india_distress_labels.csv and fetches REAL financials for
each ticker via nse_client.py (yfinance), producing records in the same
schema as data/sample_companies.json.

*** READ THIS BEFORE USING THE OUTPUT FOR ANYTHING BEYOND A DEMO ***

1. NO FREE STRUCTURED API FOR INDIAN CORPORATE FAILURES EXISTS.
   IBBI's public registry (ibbi.gov.in) lists real CIRP/insolvency cases,
   but the overwhelming majority are private companies with no NSE/BSE
   ticker -- useless for a pipeline that needs yfinance-fetchable financials.
   The CSV this script reads is a MANUALLY CURATED seed list of real,
   well-documented, publicly-listed companies that underwent insolvency,
   not a comprehensive or programmatically-sourced dataset.

2. THE SEED LIST IS SEVERELY SIZE-BIASED, IN A WAY THAT MATTERS A LOT.
   Every distressed example in the seed CSV is a LARGE, nationally-known
   insolvency (Jet Airways, DHFL, Reliance Communications, etc.) because
   those are the cases well-documented enough to cite with confidence.
   Every healthy example is a mega-cap (Reliance, TCS, HDFC Bank...).
   This project's actual stated focus is PENNY STOCKS -- small, thinly
   traded companies. A model trained on "mega-cap failure vs. mega-cap
   health" will NOT transfer to penny-stock-scale distress detection; the
   failure modes and financial signatures are different at that scale.
   Expand this CSV with genuine small/mid-cap examples (via screener.in,
   moneycontrol.com, or NSE/BSE delisting circulars) before trusting this
   for anything beyond proving the pipeline mechanics work.

3. NO POINT-IN-TIME HISTORICAL FETCH FOR INDIA (unlike edgar_client.py).
   yfinance exposes only ~4 years of annual statements with no as_of_date
   filtering the way SEC EDGAR's dated filings allow. This script pulls
   whatever yfinance currently has for each ticker -- for the distressed
   companies, some may no longer report at all (delisted), giving thin or
   missing data. This is a real, currently-unsolved data-leakage risk that
   us_edgar_labels.py explicitly guards against but this script cannot.

Run from your own machine with internet access (not this sandbox):
    python data/sources/india_labels.py --csv data/sources/india_distress_labels.csv --out india_real_labels.json
"""

import os
import sys
import csv
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from nse_client import fetch_financials_for_ticker, fetch_recent_news_headlines  # noqa: E402
from features import has_complete_financials  # noqa: E402


def load_labels_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def build_india_labeled_dataset(csv_path: str, polite_delay: float = 0.5) -> list[dict]:
    rows = load_labels_csv(csv_path)
    records = []

    for row in rows:
        ticker = row["ticker"]
        label = int(row["label_distressed"])
        print(f"Fetching {ticker} ({row['company_name']})...")

        try:
            fin = fetch_financials_for_ticker(ticker)
            time.sleep(polite_delay)
            missing = [k for k, v in fin.items() if v is None]
            if missing:
                print(f"  Warning: missing fields for {ticker}: {missing}")
            if not has_complete_financials(fin):
                print(f"  Skipping {ticker}: incomplete financials "
                      f"(common for delisted/failed companies on yfinance) -- {missing}")
                continue

            headlines = fetch_recent_news_headlines(ticker) if label == 0 else \
                [f"{row['company_name']}: {row['source']}"]

            records.append({
                "ticker": ticker,
                "company_name": row["company_name"],
                "market": "IN",
                "financials": fin,
                "headlines": headlines,
                "label_distressed": label,
                "event_date": row["event_date"],
                "source": row["source"],
            })
        except Exception as e:
            print(f"  Skipping {ticker}: {e}")

    return records


MARKET_CODE = "india"
MARKET_LABEL = "India (NSE/BSE)"
MARKET_REGION = "Indian Subcontinent"
_DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "india_distress_labels.csv")


def add_cli_args(parser) -> None:
    """Registers this market's own CLI arguments onto the shared parser --
    part of the plugin contract, see data/build_dataset.py."""
    group = parser.add_argument_group(f"{MARKET_LABEL} options")
    group.add_argument("--india-csv", default=_DEFAULT_CSV)


def build(args) -> list[dict]:
    """Plugin entry point -- see data/build_dataset.py's MARKET_REGISTRY."""
    return build_india_labeled_dataset(csv_path=args.india_csv)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=os.path.join(os.path.dirname(__file__), "india_distress_labels.csv"))
    parser.add_argument("--out", default="india_real_labels.json")
    args = parser.parse_args()

    data = build_india_labeled_dataset(args.csv)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {len(data)} labeled India companies to {args.out}")
    print("\nRemember: expand data/sources/india_distress_labels.csv with real "
          "small/mid-cap examples before trusting this beyond a pipeline demo.")
