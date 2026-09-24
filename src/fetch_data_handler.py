"""
Lambda handler that runs data/build_dataset.py's real-data-fetching logic
and writes the result to S3, so the retrain pipeline's TrainAndEvaluate step
reads fresh real data instead of the bundled synthetic dataset -- and so
none of this needs to run from your own laptop anymore.

Scoped to the US market by default for the automated weekly run: it's the
most robust of the four bundled markets (real leakage protection via
as_of_date, no API key required, most thoroughly tested). Widen this later
via the FETCH_MARKETS env var (e.g. "us,india") once you're ready --
two things to know before adding India/UK/China here:
  - UK needs COMPANIES_HOUSE_API_KEY set as a Lambda environment variable
    (or better, AWS Secrets Manager, for a real production setup).
  - China's AKShare hits Chinese data providers (Eastmoney, Sina) whose
    reachability from AWS Lambda's network has not been tested -- verify
    this actually works before relying on it in the automated pipeline.

One genuine plus of running this in AWS rather than on a laptop: Lambda's
outbound internet access does NOT route through a corporate proxy the way
an office laptop might, so the SSL/CA-bundle workaround this project needed
locally simply doesn't apply here.
"""

import os
import sys
import json
import tempfile
import boto3

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SRC_DIR, "..", "data"))
sys.path.insert(0, os.path.join(_SRC_DIR, "..", "data", "sources"))

MODEL_BUCKET = os.environ.get("MODEL_BUCKET")
DATASET_S3_KEY = os.environ.get("DATASET_S3_KEY", "datasets/real_companies.json")
FETCH_MARKETS = [m.strip() for m in os.environ.get("FETCH_MARKETS", "us").split(",") if m.strip()]

REQUIRED_FINANCIAL_FIELDS = [
    "total_assets", "total_liabilities", "current_assets",
    "current_liabilities", "retained_earnings", "ebit", "sales",
]


class _EnvArgs:
    """Stand-in for the argparse.Namespace that data/build_dataset.py's
    market plugins expect -- each market's add_cli_args() would normally
    populate these from the command line; here they come from Lambda
    environment variables instead, with the same defaults."""
    us_start_date = os.environ.get("US_START_DATE", "2015-01-01")
    us_end_date = os.environ.get("US_END_DATE")  # None -> today, see us_edgar_labels.build()
    us_n_distressed = int(os.environ.get("US_N_DISTRESSED", "30"))
    us_n_healthy = int(os.environ.get("US_N_HEALTHY", "30"))

    india_csv = os.path.join(_SRC_DIR, "..", "data", "sources", "india_distress_labels.csv")

    uk_api_key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    uk_n_distressed = int(os.environ.get("UK_N_DISTRESSED", "30"))
    uk_n_healthy = int(os.environ.get("UK_N_HEALTHY", "30"))

    china_n_distressed = int(os.environ.get("CHINA_N_DISTRESSED", "30"))
    china_n_healthy = int(os.environ.get("CHINA_N_HEALTHY", "30"))


def fetch_data_handler(event, context):
    from build_dataset import MARKET_REGISTRY, build as build_records

    markets = [m for m in FETCH_MARKETS if m in MARKET_REGISTRY]
    if not markets:
        raise ValueError(
            f"No valid markets in FETCH_MARKETS={FETCH_MARKETS!r}; "
            f"registered markets: {list(MARKET_REGISTRY.keys())}"
        )

    records = build_records(markets, _EnvArgs())

    usable = [
        r for r in records
        if all(r["financials"].get(f) is not None for f in REQUIRED_FINANCIAL_FIELDS)
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(records, tmp)
        tmp_path = tmp.name

    boto3.client("s3").upload_file(tmp_path, MODEL_BUCKET, DATASET_S3_KEY)

    result = {
        "dataset_s3_key": DATASET_S3_KEY,
        "markets_fetched": markets,
        "total_records": len(records),
        "usable_records": len(usable),
    }
    print(json.dumps(result, indent=2))
    return result
