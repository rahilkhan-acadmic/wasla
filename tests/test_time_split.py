"""
Tests for train_classifier.py's time-based split (time_split_dataset,
time_split_class_counts, check_time_split_gate) -- the mechanism that lets
the model be evaluated on whether it generalizes to LATER companies instead
of random ones.

These are unit tests on synthetic records (no real financials needed --
the split only looks at ticker/market/event_date/label_distressed), so they
run instantly and don't need network access or moto.

Run from the project root: python tests/test_time_split.py
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "src"))

from train_classifier import (  # noqa: E402
    time_split_dataset, time_split_class_counts, check_time_split_gate,
)


def _rec(ticker, market, event_date, label):
    return {"ticker": ticker, "market": market, "event_date": event_date, "label_distressed": label}


def run_test():
    print("=== 1. No train record is dated later than any test record ===")
    records = [
        _rec("D1", "US", "2015-01-01", 1), _rec("D2", "US", "2016-01-01", 1),
        _rec("D3", "US", "2017-01-01", 1), _rec("H1", "US", "2015-06-01", 0),
        _rec("H2", "US", "2016-06-01", 0), _rec("H3", "US", "2017-06-01", 0),
        _rec("D4", "US", "2023-01-01", 1), _rec("D5", "US", "2023-06-01", 1),
        _rec("H4", "US", "2023-03-01", 0), _rec("H5", "US", "2023-09-01", 0),
    ]
    train, test = time_split_dataset(records, "2020-01-01")
    assert train and test, "expected both sides non-empty for this fixture"
    max_train_date = max(r["event_date"] for r in train)
    min_test_date = min(r["event_date"] for r in test)
    assert max_train_date < min_test_date, (
        f"LEAKAGE: train has a record dated {max_train_date}, "
        f"later than the earliest test record {min_test_date}")
    print(f"PASSED (max train date {max_train_date} < min test date {min_test_date})\n")

    print("=== 2. Undated or non-US records always go to train, never test ===")
    records = [
        _rec("D1", "US", "2015-01-01", 1), _rec("H1", "US", "2015-01-01", 0),
        _rec("D2", "US", "2024-01-01", 1), _rec("H2", "US", "2024-01-01", 0),
        _rec("IG1", "india_gsm", None, 1),             # no event_date at all
        _rec("IG2", "india_gsm", "2023-03-31", 0),      # fake shared placeholder date
        _rec("UK1", "uk", "2024-06-01", 1),             # real-looking date, wrong market
    ]
    train, test = time_split_dataset(records, "2020-01-01")
    test_tickers = {r["ticker"] for r in test}
    train_tickers = {r["ticker"] for r in train}
    assert {"IG1", "IG2", "UK1"} <= train_tickers, "unreliable-dated records must land in train"
    assert not ({"IG1", "IG2", "UK1"} & test_tickers), "unreliable-dated records must never reach test"
    print("PASSED\n")

    print("=== 3. No company appears on both sides (company exclusivity) ===")
    train, test = time_split_dataset(records, "2020-01-01")
    overlap = {r["ticker"] for r in train} & {r["ticker"] for r in test}
    assert not overlap, f"company straddling train/test: {overlap}"
    print("PASSED\n")

    print("=== 4. A later snapshot of an already-trained company is dropped, not reused ===")
    records = [
        _rec("REPEAT", "US", "2016-01-01", 0),   # earliest -> train
        _rec("REPEAT", "US", "2022-01-01", 0),   # pre-cutoff duplicate -> kept in train
        _rec("REPEAT", "US", "2024-01-01", 0),   # post-cutoff duplicate -> must be dropped
        _rec("OTHER", "US", "2024-06-01", 1),
    ]
    train, test = time_split_dataset(records, "2023-01-01")
    repeat_dates_in_train = sorted(r["event_date"] for r in train if r["ticker"] == "REPEAT")
    assert repeat_dates_in_train == ["2016-01-01", "2022-01-01"], repeat_dates_in_train
    assert not any(r["ticker"] == "REPEAT" for r in test), "REPEAT must not appear in test"
    print(f"PASSED (REPEAT kept in train at {repeat_dates_in_train}, dropped its 2024 snapshot)\n")

    print("=== 5. Gate fails loudly when a side has too few unique companies ===")
    thin_records = [
        _rec("D1", "US", "2015-01-01", 1), _rec("H1", "US", "2015-01-01", 0),
        _rec("D2", "US", "2024-01-01", 1),   # only 1 distressed, 0 healthy in test
    ]
    train, test = time_split_dataset(thin_records, "2020-01-01")
    try:
        check_time_split_gate(train, test, min_per_class=5)
    except ValueError as e:
        print(f"PASSED (raised: {e})\n")
    else:
        raise AssertionError("expected the gate to reject a test side with 0 healthy companies")

    print("=== 6. Gate passes on a sufficiently balanced synthetic dataset ===")
    balanced = []
    for i in range(6):
        balanced.append(_rec(f"D_old{i}", "US", "2015-01-01", 1))
        balanced.append(_rec(f"H_old{i}", "US", "2015-01-01", 0))
        balanced.append(_rec(f"D_new{i}", "US", "2024-01-01", 1))
        balanced.append(_rec(f"H_new{i}", "US", "2024-01-01", 0))
    train, test = time_split_dataset(balanced, "2020-01-01")
    counts = check_time_split_gate(train, test, min_per_class=5)
    assert counts["train"][0] >= 5 and counts["train"][1] >= 5
    assert counts["test"][0] >= 5 and counts["test"][1] >= 5
    print(f"PASSED (counts={counts})\n")

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_test()
