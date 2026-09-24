"""
Run the full pipeline for a single company: financials + headlines -> features
-> trained model -> distress probability.

Two modes:
  --ticker AAPL          Pulls live financials from SEC EDGAR (needs internet
                          access to sec.gov; will not work in a sandboxed env).
  --demo-ticker SYN027   Looks the company up in the bundled synthetic sample
                          dataset instead, for testing without network access.

Example:
    python src/predict.py --demo-ticker SYN027 --model models/distress_model.json
    python src/predict.py --ticker GME --headlines headlines.txt --model models/distress_model.json
"""

import argparse
import json
import os

import numpy as np
import xgboost as xgb

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_SAMPLE_DATA = os.path.join(_SCRIPT_DIR, "..", "data", "sample_companies.json")

from features import build_feature_row, financials_from_dict, FEATURE_NAMES
from altman_zscore import classify_zone


def load_model(path: str) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier()
    model.load_model(path)
    return model


def predict_from_financials(model, fin_dict: dict, headlines: list[str]):
    fin = financials_from_dict(fin_dict)
    feats = build_feature_row(fin, headlines)
    x = np.array([[feats[name] for name in FEATURE_NAMES]])
    prob_distressed = model.predict_proba(x)[0, 1]
    return prob_distressed, feats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="Real US ticker to fetch live from SEC EDGAR")
    parser.add_argument("--nse-ticker", help="Indian ticker via yfinance, e.g. RELIANCE.NS or TCS.BO")
    parser.add_argument("--demo-ticker", help="Ticker from data/sample_companies.json")
    parser.add_argument("--headlines", help="Path to a text file, one headline per line")
    parser.add_argument("--model", default="models/distress_model.json")
    parser.add_argument("--sample-data", default=_DEFAULT_SAMPLE_DATA,
                         help="Path to sample_companies.json (for --demo-ticker)")
    args = parser.parse_args()

    model = load_model(args.model)
    headlines = []
    if args.headlines:
        with open(args.headlines) as f:
            headlines = [line.strip() for line in f if line.strip()]

    if args.demo_ticker:
        with open(args.sample_data) as f:
            companies = json.load(f)
        match = next((c for c in companies if c["ticker"] == args.demo_ticker), None)
        if match is None:
            raise SystemExit(f"{args.demo_ticker} not found in {args.sample_data}")
        fin_dict = match["financials"]
        headlines = headlines or match["headlines"]
        label = match["label_distressed"]
        print(f"(demo record's ground-truth synthetic label: "
              f"{'DISTRESSED' if label else 'healthy'})")

    elif args.ticker:
        from edgar_client import fetch_financials_for_ticker
        print(f"Fetching live SEC EDGAR data for {args.ticker} ...")
        fin_dict = fetch_financials_for_ticker(args.ticker)
        missing = [k for k, v in fin_dict.items() if v is None]
        if missing:
            print(f"Warning: could not find EDGAR values for: {missing}")
        # Live market value of equity isn't in EDGAR -- plug in a price source
        # yourself (e.g. yfinance) and pass it in for a more accurate Z-Score.
        fin_dict.setdefault("market_value_equity", None)

    elif args.nse_ticker:
        from nse_client import fetch_financials_for_ticker, fetch_recent_news_headlines
        print(f"Fetching live NSE/BSE data for {args.nse_ticker} via yfinance ...")
        fin_dict = fetch_financials_for_ticker(args.nse_ticker)
        missing = [k for k, v in fin_dict.items() if v is None]
        if missing:
            print(f"Warning: could not find values for: {missing} "
                  f"(common for small/micro-caps with thin yfinance coverage)")
        headlines = headlines or fetch_recent_news_headlines(args.nse_ticker)

    else:
        raise SystemExit("Provide --ticker (US/EDGAR), --nse-ticker (India/yfinance), "
                          "or --demo-ticker (offline demo)")

    prob, feats = predict_from_financials(model, fin_dict, headlines)

    print(f"\n=== Distress assessment ===")
    print(f"Model-predicted probability of distress: {prob:.1%}")
    print(f"Altman Z-Score:        {feats['z_score']:.2f}  ({classify_zone(feats['z_score'], 'z')})")
    print(f"Altman Z''-Score:      {feats['z_double_prime']:.2f}  ({classify_zone(feats['z_double_prime'], 'zpp')})")
    print(f"News sentiment (-1..1): {feats['news_sentiment']:+.2f}")
    print(f"Cash burning (EBIT<0):  {'yes' if feats['cash_burn_flag'] else 'no'}")


if __name__ == "__main__":
    main()
