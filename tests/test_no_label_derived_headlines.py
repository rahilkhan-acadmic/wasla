"""
Guards against label leakage through the news_sentiment feature.

THE PROBLEM THIS PREVENTS
Each record carries a `headlines` list that becomes the `news_sentiment`
feature. Several market plugins used to WRITE those headlines themselves from
the label -- e.g. "<company> files for bankruptcy protection." for a company
selected BECAUSE it filed for bankruptcy, or "<company>: NSE GSM <stage>" for
one selected because NSE flagged it. That isn't news observed independently
of the outcome; it's the label re-typed as text. Meanwhile "healthy" companies
got either nothing or *current* news scraped at build time, which is not news
from before any event either. A model can then learn "the text looks like this
=> distressed" -- a shortcut that inflates every metric and does nothing on a
real, unlabeled company, where no such headline exists.

How much it matters depends on the sentiment scorer (VADER scores the US
template exactly 0.0, FinBERT would score it strongly negative), which is why
it must be closed structurally rather than by hoping the scorer is blind to it.

THE RULE
Until genuine, point-in-time, label-independent headlines are available, NO
plugin may emit any headline text, for either class. The feature stays in the
model's input (so feature dimensions and deployed models remain compatible)
but is a constant 0.0 -- carrying no information, and therefore no leak.

This test runs every registered plugin's real build() code, with only the
network faked, and asserts every record's headlines are empty. A plugin with
no fake registered here FAILS the test -- so a future market can't silently
reintroduce the leak by being added without being checked.

Run from the project root: python tests/test_no_label_derived_headlines.py
"""
import os
import sys
import types
import argparse

import pandas as pd

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "data"))

# The UK plugin's --uk-api-key defaults from this env var at parse time.
os.environ["COMPANIES_HOUSE_API_KEY"] = "test-key"

from build_dataset import MARKET_REGISTRY  # noqa: E402

GOOD = {
    "total_assets": 1e6, "total_liabilities": 4e5, "current_assets": 3e5,
    "current_liabilities": 1e5, "retained_earnings": 2e5, "ebit": 1e5, "sales": 5e5,
}
# What a scraped "recent news" call would plausibly return for a healthy company.
REAL_LOOKING_NEWS = ["Shares rally on strong quarterly earnings."]
NO_SLEEP = types.SimpleNamespace(sleep=lambda s: None)


def _fake_us(m):
    m.find_bankruptcy_filings = lambda start, end, max_results=200: [
        {"cik": 1, "company_name": "Bust Co", "filing_date": "2020-01-01", "accession_no": "a"}]
    m.find_healthy_sample = lambda start, end, exclude, max_results=200: [
        {"cik": 2, "company_name": "Fine Co", "filing_date": "2020-01-01"}]
    m.fetch_financials_for_cik = lambda cik, polite_delay=0.2, as_of_date=None: dict(GOOD)


def _fake_india(m):
    m.fetch_financials_for_ticker = lambda t: dict(GOOD)
    m.fetch_recent_news_headlines = lambda t: list(REAL_LOOKING_NEWS)
    m.time = NO_SLEEP


def _fake_india_gsm(m):
    m.fetch_gsm_list = lambda max_results=20: [
        {"symbol": "AGSTRA", "company_name": "AGS Transact", "stage": "IBC", "is_ibc": True}]
    m.fetch_financials_for_ticker = lambda t: dict(GOOD)
    m.fetch_recent_news_headlines = lambda t: list(REAL_LOOKING_NEWS)


def _fake_china(m):
    m._get_a_share_roster = lambda: pd.DataFrame({
        "代码": ["000001", "000002", "000003", "000004"],
        "名称": ["*ST Bad", "ST Worse", "Good One", "Good Two"],
    })
    m._fetch_financials = lambda code, polite_delay=0.3: dict(GOOD)


def _fake_uk(m):
    m._search_by_status = lambda api_key, status, max_results: [
        {"company_number": "1", "company_name": "X Ltd"}]
    m.time = NO_SLEEP


FAKES = {
    "us": _fake_us, "india": _fake_india, "india_gsm": _fake_india_gsm,
    "china": _fake_china, "uk": _fake_uk,
}


def run_test():
    problems = []

    for code, module in MARKET_REGISTRY.items():
        if code not in FAKES:
            problems.append((code, "no fake network layer registered in this test -- "
                                   "add one, so this plugin is checked for label-derived headlines"))
            print(f"  {code:10s} NOT COVERED")
            continue

        FAKES[code](module)
        parser = argparse.ArgumentParser()
        module.add_cli_args(parser)
        records = module.build(parser.parse_args([]))

        labels = {r["label_distressed"] for r in records}
        assert labels == {0, 1}, (
            f"{code}: fakes must yield BOTH classes or this check is vacuous, got {labels}")

        leaking = sorted({r["headlines"][0] for r in records if r.get("headlines")})
        if leaking:
            problems.append((code, f"emits headline text, e.g. {leaking[0]!r}"))
            print(f"  {code:10s} LEAKS  ({len([r for r in records if r.get('headlines')])} "
                  f"of {len(records)} records carry headlines)")
        else:
            print(f"  {code:10s} ok     ({len(records)} records, none carry headlines)")

    if problems:
        print("\nFAILED: plugins feeding text into the headlines feature:")
        for code, why in problems:
            print(f"  {code}: {why}")
        print("\nHeadlines written from the label (or scraped at build time) let a "
              "model learn the label from the text. Emit headlines=[] until real, "
              "point-in-time, label-independent headlines exist. See this file's docstring.")
        raise AssertionError(f"{len(problems)} plugin(s) emit headline text")

    print(f"\nAll {len(MARKET_REGISTRY)} registered plugins emit no headline text. PASSED")


if __name__ == "__main__":
    run_test()
