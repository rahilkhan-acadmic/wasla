"""
Guards the India training labels (data/sources/india_distress_labels.csv)
and the training-path financials fetch (src/nse_client.py), after four real
errors were found in 2026-11:

  * ESSARSHIPPING.BO was labelled as Essar Steel's insolvency -- a different
    company's ticker, so the model learned Essar Steel's label against Essar
    Shipping's financials. (Essar Steel India delisted in 2015; yfinance has
    no usable financials for it, so the row was removed rather than re-pointed.)
  * Videocon, DHFL and RCom had event dates that weren't the NCLT admission
    date their own `source` column claimed.
  * Infosys's training record mixed an INR market cap with USD statements,
    giving an Altman market-value ratio of ~700 (peers 1.6-17).

The date check ties every "NCLT CIRP admission" row to the independently
sourced admission date in dashboard/data/insolvency_cases.json, so the two
can't drift apart again.

Run from the project root: python tests/test_india_training_labels.py
"""
import csv
import json
import os
import re
import sys
from datetime import date

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

LABELS = os.path.join(_ROOT, "data", "sources", "india_distress_labels.csv")
CASES = os.path.join(_ROOT, "dashboard", "data", "insolvency_cases.json")

with open(LABELS, newline="") as f:
    ROWS = list(csv.DictReader(f))
with open(CASES) as f:
    CASE_LIST = json.load(f)["cases"]


def _norm(name: str) -> str:
    n = name.lower().replace("(india)", "").replace("&", "and")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(ltd|limited|india)\b", " ", n)
    return " ".join(n.split())


def test_rows_are_well_formed():
    tickers = [r["ticker"] for r in ROWS]
    assert len(tickers) == len(set(tickers)), "duplicate tickers"
    for r in ROWS:
        assert re.match(r"^[A-Z0-9&\-]+\.(NS|BO)$", r["ticker"]), r["ticker"]
        assert r["label_distressed"] in ("0", "1"), r
        y, m, d = (int(x) for x in r["event_date"].split("-"))
        date(y, m, d)  # raises on an impossible date
        assert r["company_name"].strip() and r["source"].strip(), r
    print(f"PASS: {len(ROWS)} rows, unique .NS/.BO tickers, valid labels and dates")


def test_no_ticker_points_at_a_different_company():
    # The ticker's root should plausibly belong to the named company. This
    # catches the Essar Shipping / Essar Steel class of mix-up without a
    # network lookup: every word in the ticker root that is itself a company
    # word (STEEL, SHIPPING, POWER, ...) must appear in the company name.
    industry_words = {"STEEL", "SHIPPING", "POWER", "CAPITAL", "INFRA", "TEXT", "CEMENT", "AIRWAYS"}
    for r in ROWS:
        root = r["ticker"].split(".")[0]
        name = r["company_name"].upper()
        for w in industry_words:
            if w in root:
                stem = {"TEXT": "TEXTILE", "INFRA": "INFRA"}.get(w, w)
                if w == "TEXT":
                    # Alok Industries' BSE code is ALOKTEXT -- a historical
                    # name, allowed explicitly rather than by weakening the rule.
                    continue
                assert stem in name, f"{r['ticker']} looks like a {w.lower()} company, not {r['company_name']}"
    assert not any(r["ticker"].startswith("ESSARSHIPPING") for r in ROWS)
    print("PASS: no ticker names a different kind of company (Essar Shipping row removed)")


def test_admission_dates_match_sourced_insolvency_cases():
    by_name = {_norm(c["company"]): c for c in CASE_LIST}
    checked = 0
    for r in ROWS:
        if r["label_distressed"] != "1" or r["source"] != "NCLT CIRP admission":
            continue
        case = by_name.get(_norm(r["company_name"]))
        assert case, f"{r['company_name']}: no sourced case in insolvency_cases.json to check against"
        assert case["admitted"] == r["event_date"], (
            f"{r['ticker']}: event_date {r['event_date']} but the sourced NCLT admission is {case['admitted']}")
        checked += 1
    assert checked >= 5, checked
    print(f"PASS: {checked} 'NCLT CIRP admission' dates match the sourced Insolvency Watch dates")


def test_training_fetch_drops_market_cap_in_a_different_currency():
    import pandas as pd
    import nse_client
    from features import build_feature_row, financials_from_dict

    col = pd.Timestamp("2026-03-31")
    bs = pd.DataFrame({col: [16_446e6, 6_606e6, 10_912e6, 5_516e6, 13_459e6]},
                      index=["Total Assets", "Total Liabilities Net Minority Interest",
                             "Current Assets", "Current Liabilities", "Retained Earnings"])
    inc = pd.DataFrame({col: [4_553e6, 20_158e6]}, index=["EBIT", "Total Revenue"])

    def ticker_class(financial_currency):
        class FakeTicker:
            def __init__(self, t):
                self.balance_sheet, self.income_stmt = bs, inc
                self.fast_info = {"marketCap": 4_674_539e6, "currency": "INR"}  # INR market cap
                self.info = {"financialCurrency": financial_currency}
        return FakeTicker

    real = nse_client.yf.Ticker
    try:
        nse_client.yf.Ticker = ticker_class("USD")  # Infosys: USD statements
        usd = nse_client.fetch_financials_for_ticker("INFY.NS", polite_delay=0)
        nse_client.yf.Ticker = ticker_class("INR")  # ordinary Indian company
        inr = nse_client.fetch_financials_for_ticker("TCS.NS", polite_delay=0)
    finally:
        nse_client.yf.Ticker = real

    assert usd["market_value_equity"] is None, usd
    assert inr["market_value_equity"] == 4_674_539e6, inr
    # Output shape is unchanged: it must still build a Financials object.
    expected = {"total_assets", "total_liabilities", "current_assets", "current_liabilities",
                "retained_earnings", "ebit", "sales", "market_value_equity", "book_value_equity"}
    assert set(usd) == expected and set(inr) == expected, set(usd) ^ expected

    z_usd = build_feature_row(financials_from_dict(usd))["z_score"]
    z_inr_mix = build_feature_row(financials_from_dict({**usd, "market_value_equity": 4_674_539e6}))["z_score"]
    assert z_usd < 10 < z_inr_mix, (z_usd, z_inr_mix)
    print(f"PASS: training fetch drops a mismatched-currency market cap (Z {z_inr_mix:.0f} -> {z_usd:.1f})")


if __name__ == "__main__":
    test_rows_are_well_formed()
    test_no_ticker_points_at_a_different_company()
    test_admission_dates_match_sourced_insolvency_cases()
    test_training_fetch_drops_market_cap_in_a_different_currency()
    print("\nAll India training-label tests passed.")
