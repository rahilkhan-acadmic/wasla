"""
Tests `min_lead_days` and `with_provenance` in edgar_client.extract_financials_dict,
using the same synthetic companyfacts-shaped fixture style as
test_edgar_leakage_prevention.py (no live EDGAR access needed/possible here).

`as_of_date` alone (tested in test_edgar_leakage_prevention.py) only prevents
financials filed AFTER the event from leaking in -- it still hands the model
whatever was MOST RECENTLY filed right up to that date, which is a much easier
problem than genuine forecasting. `min_lead_days` shifts the effective cutoff
earlier, simulating "the model only had data from N days before the event" --
and `with_provenance` records which actual filing ended up being used, so a
record's real lead time can be checked later without re-fetching.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from edgar_client import extract_financials_dict

# Same three-filing shape as test_edgar_leakage_prevention.py: healthy (2021),
# right before bankruptcy (2022), and after bankruptcy (2023). Liabilities is
# deliberately omitted from this fixture so provenance has a "field never
# matched" case to check (ebit/sales/etc. are also absent for the same reason).
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
        }
    }
}

BANKRUPTCY_DATE = "2022-06-01"

# extract_financials_dict always returns every TAG_ALIASES field -- the
# fixture only ever populates total_assets, so every other field is always
# expected to be None.
_ALL_NONE_EXCEPT_ASSETS = {
    "total_assets": None, "total_liabilities": None, "current_assets": None,
    "current_liabilities": None, "retained_earnings": None, "ebit": None, "sales": None,
}


def _expect(total_assets):
    out = dict(_ALL_NONE_EXCEPT_ASSETS)
    out["total_assets"] = total_assets
    return out


def test_min_lead_days_zero_preserves_existing_behavior():
    """min_lead_days=0 (the default) must be a no-op: identical to passing
    just as_of_date, as covered already in test_edgar_leakage_prevention.py."""
    with_zero = extract_financials_dict(FIXTURE, as_of_date=BANKRUPTCY_DATE, min_lead_days=0)
    without_arg = extract_financials_dict(FIXTURE, as_of_date=BANKRUPTCY_DATE)
    assert with_zero == without_arg == _expect(300_000_000), with_zero
    print("PASS: min_lead_days=0 behaves identically to omitting it")


def test_min_lead_days_shifts_cutoff_earlier():
    """min_lead_days=120 moves the effective cutoff to 2022-02-01 (120 days
    before the 2022-06-01 bankruptcy date), which excludes the 2022-02-20
    filing too -- even though that filing is well before the bankruptcy and
    would pass a plain as_of_date check. The model should fall back to the
    2021-02-15 filing (500M), simulating a genuine forecasting gap instead of
    "latest available right up to the event."""
    result = extract_financials_dict(FIXTURE, as_of_date=BANKRUPTCY_DATE, min_lead_days=120)
    assert result["total_assets"] == 500_000_000, \
        f"Expected the older, 2021-02-15 filing (500M) once lead time pushes out the 2022 one, got {result}"
    print(f"PASS: min_lead_days=120 correctly falls back to the older filing ({result['total_assets']:,})")


def test_min_lead_days_without_as_of_date_is_a_noop():
    """Per the docstring, min_lead_days only takes effect when as_of_date is
    also set -- passing it alone must behave exactly like neither being set
    (the latest-ever filing, 50M, same leaky value test_edgar_leakage_prevention
    uses as its "this IS the bug" sanity check)."""
    with_lead_only = extract_financials_dict(FIXTURE, min_lead_days=120)
    with_neither = extract_financials_dict(FIXTURE)
    assert with_lead_only == with_neither == _expect(50_000_000), with_lead_only
    print("PASS: min_lead_days without as_of_date has no effect")


def test_min_lead_days_larger_than_any_lag_returns_none():
    """A lead time longer than any filing's actual lag relative to the event
    must return None, not silently fall back to the as_of_date behavior or
    error -- there's genuinely no data that old."""
    result = extract_financials_dict(FIXTURE, as_of_date=BANKRUPTCY_DATE, min_lead_days=5000)
    assert result["total_assets"] is None, f"Expected None, got {result}"
    print("PASS: min_lead_days longer than any available lag correctly returns None")


def test_provenance_records_the_actual_filing_used():
    """with_provenance=True must return the filed/end dates of the exact
    filing whose value was used -- not just echo back as_of_date/min_lead_days,
    which would be useless for later auditing real lead time."""
    value, provenance = extract_financials_dict(
        FIXTURE, as_of_date=BANKRUPTCY_DATE, with_provenance=True)
    assert value["total_assets"] == 300_000_000
    assert provenance["total_assets"] == {"filed": "2022-02-20", "end": "2021-12-31"}, provenance
    print(f"PASS: provenance correctly identifies the filing actually used: {provenance['total_assets']}")


def test_provenance_tracks_the_lead_time_shift_too():
    """Provenance must reflect whichever filing min_lead_days actually ended
    up selecting (the older, 2021-02-15 one here) -- not the filing that
    would have been picked by as_of_date alone."""
    value, provenance = extract_financials_dict(
        FIXTURE, as_of_date=BANKRUPTCY_DATE, min_lead_days=120, with_provenance=True)
    assert value["total_assets"] == 500_000_000
    assert provenance["total_assets"] == {"filed": "2021-02-15", "end": "2020-12-31"}, provenance
    print(f"PASS: provenance tracks the lead-time-shifted filing too: {provenance['total_assets']}")


def test_provenance_is_none_for_a_field_with_no_matching_tag():
    """total_liabilities has no tag at all in this fixture -- provenance for
    it must be None, not a stale/zero entry, matching value also being None."""
    value, provenance = extract_financials_dict(
        FIXTURE, as_of_date=BANKRUPTCY_DATE, with_provenance=True)
    assert value["total_liabilities"] is None
    assert provenance["total_liabilities"] is None, provenance
    print("PASS: provenance is None for a field with no matching tag, consistent with its None value")


if __name__ == "__main__":
    test_min_lead_days_zero_preserves_existing_behavior()
    test_min_lead_days_shifts_cutoff_earlier()
    test_min_lead_days_without_as_of_date_is_a_noop()
    test_min_lead_days_larger_than_any_lag_returns_none()
    test_provenance_records_the_actual_filing_used()
    test_provenance_tracks_the_lead_time_shift_too()
    test_provenance_is_none_for_a_field_with_no_matching_tag()
    print("\nALL LEAD-TIME TESTS PASSED")
