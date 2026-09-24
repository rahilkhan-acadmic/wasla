"""
Tests the as_of_date cutoff logic in edgar_client.py using a synthetic
companyfacts-shaped fixture (no live EDGAR access needed/possible here).
This is the single most important correctness property for building a real
distress-labeled dataset: financials filed AFTER a company's failure date
must never be visible to a model being trained to predict that failure.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from edgar_client import extract_financials_dict

# Simulates a company that filed three annual 10-Ks: one while healthy
# (2021), one right before its bankruptcy (2022), and one AFTER filing for
# bankruptcy (2023, e.g. a going-concern-qualified final annual report).
FIXTURE = {
    "facts": {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {"form": "10-K", "end": "2020-12-31", "filed": "2021-02-15", "val": 500_000_000},
                        {"form": "10-K", "end": "2021-12-31", "filed": "2022-02-20", "val": 300_000_000},
                        {"form": "10-K", "end": "2022-12-31", "filed": "2023-02-10", "val": 50_000_000},
                    ]
                }
            },
            "Liabilities": {
                "units": {
                    "USD": [
                        {"form": "10-K", "end": "2020-12-31", "filed": "2021-02-15", "val": 200_000_000},
                        {"form": "10-K", "end": "2021-12-31", "filed": "2022-02-20", "val": 280_000_000},
                        {"form": "10-K", "end": "2022-12-31", "filed": "2023-02-10", "val": 400_000_000},
                    ]
                }
            },
        }
    }
}

# Say this company filed for bankruptcy (8-K Item 1.03) on 2022-06-01.
BANKRUPTCY_DATE = "2022-06-01"


def test_no_cutoff_would_leak():
    """Without as_of_date, we'd get the LATEST filing -- which for this
    fixture is the one filed in 2023, AFTER the bankruptcy. This is the bug
    the old code had."""
    result = extract_financials_dict(FIXTURE)  # no as_of_date
    assert result["total_assets"] == 50_000_000, \
        "Sanity check: confirms the old behavior would indeed leak post-failure data"
    print(f"PASS: without as_of_date, total_assets = {result['total_assets']:,} "
          f"(this IS the post-bankruptcy filing -- leakage, as expected without the fix)")


def test_cutoff_prevents_leakage():
    """With as_of_date set to the bankruptcy date, we should get the LAST
    filing that existed BEFORE bankruptcy -- the 2022-02-20 filing, not the
    2023-02-10 one."""
    result = extract_financials_dict(FIXTURE, as_of_date=BANKRUPTCY_DATE)
    assert result["total_assets"] == 300_000_000, \
        f"Expected pre-bankruptcy assets (300M), got {result['total_assets']}"
    assert result["total_liabilities"] == 280_000_000, \
        f"Expected pre-bankruptcy liabilities (280M), got {result['total_liabilities']}"
    print(f"PASS: with as_of_date={BANKRUPTCY_DATE}, total_assets = "
          f"{result['total_assets']:,} (correctly excludes the post-bankruptcy filing)")


def test_cutoff_before_any_filing():
    """An as_of_date before ALL filings should return None, not the earliest
    filing -- there's genuinely no data available at that point in time."""
    result = extract_financials_dict(FIXTURE, as_of_date="2020-01-01")
    assert result["total_assets"] is None, \
        f"Expected None (no filings exist yet), got {result['total_assets']}"
    print("PASS: as_of_date before any filing correctly returns None")


if __name__ == "__main__":
    test_no_cutoff_would_leak()
    test_cutoff_prevents_leakage()
    test_cutoff_before_any_filing()
    print("\nALL LEAKAGE-PREVENTION TESTS PASSED")
