"""
Builds a real, labeled distress dataset -- selectable by market, or combined
across any subset of registered markets.

Usage (run on your own machine with internet access, not a sandbox):
    python data/build_dataset.py --market us
    python data/build_dataset.py --market india
    python data/build_dataset.py --market us,india
    python data/build_dataset.py --market all --out data/real_companies.json

Output schema matches data/sample_companies.json exactly (plus a few extra
provenance fields: market, company_name, event_date, source), so it's a
drop-in replacement anywhere sample_companies.json is currently used.

--- ADDING A NEW MARKET ---
Every market is a plugin: a module in data/sources/ exposing exactly four
things, each demonstrated by us_edgar_labels.py, india_labels.py,
uk_companies_house_labels.py (a deliberately partial example -- read its
docstring), and china_labels.py:

    MARKET_CODE          str, e.g. "us"  -- the --market value that selects it
    MARKET_REGION         str, e.g. "Americas" -- a broad grouping for later
                          aggregate/regional views (dashboard work, not yet
                          built). Injected onto every record automatically
                          by build() below -- individual plugins don't need
                          to add it themselves.
    add_cli_args(parser) adds this market's own CLI arguments to the shared
                          parser (its API key, date range, whatever it needs)
    build(args) -> list[dict]
                          the plugin entry point. Returns records in the
                          shared schema: {ticker, company_name, market,
                          financials: {...7 fields...}, headlines,
                          label_distressed, event_date, source}

Then add ONE line to MARKET_REGISTRY below. That's the whole contract --
build_dataset.py's CLI, merging, and summary logic need no changes.
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import us_edgar_labels, india_labels, uk_companies_house_labels, china_labels

# --- The plugin registry. Adding a market = one line here + its module. ---
MARKET_REGISTRY = {
    us_edgar_labels.MARKET_CODE: us_edgar_labels,
    india_labels.MARKET_CODE: india_labels,
    uk_companies_house_labels.MARKET_CODE: uk_companies_house_labels,
    china_labels.MARKET_CODE: china_labels,
}


def _parse_market_selection(raw: str) -> list[str]:
    if raw == "all":
        return list(MARKET_REGISTRY.keys())
    selected = [m.strip() for m in raw.split(",")]
    unknown = [m for m in selected if m not in MARKET_REGISTRY]
    if unknown:
        raise ValueError(
            f"Unknown market(s): {unknown}. Registered markets: {list(MARKET_REGISTRY.keys())}"
        )
    return selected


def build(markets: list[str], args) -> list[dict]:
    records = []
    for market_code in markets:
        module = MARKET_REGISTRY[market_code]
        label = getattr(module, "MARKET_LABEL", market_code)
        region = getattr(module, "MARKET_REGION", "Unspecified")
        print("=" * 60)
        print(f"Building {label} dataset...")
        print("=" * 60)
        market_records = module.build(args)
        for r in market_records:
            r.setdefault("region", region)  # only fills it in if the plugin didn't already set one
        records.extend(market_records)
    return records


def summarize(records: list[dict]) -> None:
    n_distressed = sum(1 for r in records if r["label_distressed"] == 1)
    n_healthy = len(records) - n_distressed
    n_usable = sum(1 for r in records if r["financials"].get("total_assets") is not None)
    by_market = {}
    by_region = {}
    for r in records:
        by_market[r["market"]] = by_market.get(r["market"], 0) + 1
        region = r.get("region", "Unspecified")
        by_region[region] = by_region.get(region, 0) + 1

    print("\n" + "=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    print(f"Total records:       {len(records)}")
    print(f"  Distressed:         {n_distressed}")
    print(f"  Healthy:            {n_healthy}")
    print(f"  With usable financials: {n_usable} (records without will be "
          f"skipped by train_classifier.py)")
    print("By market:")
    for m, count in by_market.items():
        print(f"  {m}: {count} records")
    print("By region:")
    for region, count in by_region.items():
        print(f"  {region}: {count} records")
    if n_usable < 40:
        print("\nNOTE: fewer than 40 usable records. Fine for proving the")
        print("pipeline works, but real model training benefits from hundreds")
        print("of labeled examples per class -- treat results accordingly.")


if __name__ == "__main__":
    # Two-pass parsing: first just enough to know which markets are selected,
    # so we only register THOSE markets' CLI args (avoids requiring e.g. a UK
    # API key when you only asked for --market us).
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--market", default="all")
    pre_args, _ = pre_parser.parse_known_args()

    try:
        selected_markets = _parse_market_selection(pre_args.market)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--market", default="all",
                         help=f"Comma-separated market codes, or 'all'. Registered: {list(MARKET_REGISTRY.keys())}")
    parser.add_argument("--out", default="data/real_companies.json")
    for market_code in selected_markets:
        MARKET_REGISTRY[market_code].add_cli_args(parser)
    args = parser.parse_args()

    records = build(selected_markets, args)

    with open(args.out, "w") as f:
        json.dump(records, f, indent=2)

    summarize(records)
    print(f"\nWrote {len(records)} records to {args.out}")
    print(f"\nTrain on it with:")
    print(f"  python src/train_classifier.py --data {args.out} --out models/distress_model_real.json")
