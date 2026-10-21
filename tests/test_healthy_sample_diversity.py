"""
Tests the CIK-deduplication fix in us_edgar_labels.find_healthy_sample.

THE BUG THIS PREVENTS
EDGAR's full-text search ranks hits by relevance, not by company diversity.
Querying for the near-universal phrase "annual report" across a multi-year
window returns every one of a few large, frequent filers' past 10-Ks as
separate top-ranked hits -- so an un-deduplicated result list filled up to
`max_results` could be dominated by the SAME handful of companies, each
counted many times, rather than `max_results` distinct companies. This is
exactly what happened in data/real_companies_full.json: requesting a healthy
sample of up to 60 came back as ~20 records spanning only 5 real companies
(Raytheon/UTC/RTX alone contributed 5 of them), which makes a time-based
train/test split impossible -- you can't put 5 unique companies on both
sides of a cutoff from a pool of 5 total.

This test fakes _search_full_text (the only network call find_healthy_sample
makes) with a fixture that reproduces that shape: a few CIKs with many hits
each, spread across multiple pages, plus one excluded CIK.

Run from the project root: python tests/test_healthy_sample_diversity.py
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(_ROOT, "data"))

from sources import us_edgar_labels as m  # noqa: E402


def _hit(cik, name):
    return {"_source": {"ciks": [str(cik)], "display_names": [name]}}


def _page(hits):
    return {"hits": {"hits": hits}}


def _make_fake_search(pages):
    """pages: list of lists-of-hits. Returns a callable matching
    _search_full_text's signature, paginating through `pages` by from_offset,
    then returning an empty page once exhausted."""
    def fake(query, forms, start_date, end_date, from_offset=0):
        page_index = from_offset // 10
        if page_index >= len(pages):
            return _page([])
        return _page(pages[page_index])
    return fake


def test_dedup_collapses_repeat_filers_into_one_entry_each():
    """4 hits for CIK 1 (a frequent filer) + 1 hit for CIK 2 must yield
    exactly 2 results, not 5 -- the core bug fix."""
    pages = [[
        _hit(1, "Frequent Filer Co"), _hit(1, "Frequent Filer Co"),
        _hit(1, "Frequent Filer Co"), _hit(1, "Frequent Filer Co"),
        _hit(2, "Normal Co"),
    ]]
    orig = m._search_full_text
    m._search_full_text = _make_fake_search(pages)
    try:
        results = m.find_healthy_sample("2015-01-01", "2024-01-01", exclude_ciks=set(), max_results=200)
    finally:
        m._search_full_text = orig

    ciks = [r["cik"] for r in results]
    assert ciks == [1, 2], f"expected one entry per distinct CIK, got {ciks}"
    print(f"PASS: 5 hits across 2 CIKs correctly collapsed to {len(results)} results")


def test_dedup_spans_multiple_pages():
    """The same CIK reappearing on a LATER page (not just within one page)
    must still be collapsed -- dedup has to persist across the whole paging
    loop, not reset per page."""
    pages = [
        [_hit(1, "A"), _hit(2, "B"), _hit(3, "C"), _hit(4, "D"), _hit(5, "E"),
         _hit(6, "F"), _hit(7, "G"), _hit(8, "H"), _hit(9, "I"), _hit(10, "J")],
        [_hit(1, "A"), _hit(1, "A"), _hit(11, "K")],  # CIK 1 resurfaces, plus one new company
    ]
    orig = m._search_full_text
    m._search_full_text = _make_fake_search(pages)
    try:
        results = m.find_healthy_sample("2015-01-01", "2024-01-01", exclude_ciks=set(), max_results=200)
    finally:
        m._search_full_text = orig

    ciks = [r["cik"] for r in results]
    assert ciks == list(range(1, 12)), f"expected CIKs 1-11 with no repeats, got {ciks}"
    print(f"PASS: dedup persisted across pages, found {len(results)} distinct companies")


def test_excluded_ciks_are_never_returned():
    """A CIK already flagged as a bankruptcy filer must be skipped even on
    its first occurrence, same as before this fix."""
    pages = [[_hit(1, "Bankrupt Co"), _hit(2, "Healthy Co")]]
    orig = m._search_full_text
    m._search_full_text = _make_fake_search(pages)
    try:
        results = m.find_healthy_sample("2015-01-01", "2024-01-01", exclude_ciks={1}, max_results=200)
    finally:
        m._search_full_text = orig

    assert [r["cik"] for r in results] == [2]
    print("PASS: excluded CIK correctly never appears in the healthy sample")


def test_stops_once_max_results_distinct_companies_found():
    """max_results still bounds the final list -- just now counted in
    distinct companies, not raw hits."""
    pages = [[_hit(i, f"Co{i}") for i in range(1, 11)]]  # 10 distinct companies, one page
    orig = m._search_full_text
    m._search_full_text = _make_fake_search(pages)
    try:
        results = m.find_healthy_sample("2015-01-01", "2024-01-01", exclude_ciks=set(), max_results=3)
    finally:
        m._search_full_text = orig

    assert len(results) == 3, f"expected exactly max_results=3, got {len(results)}"
    print(f"PASS: truncated to max_results ({len(results)}) once enough distinct companies were found")


if __name__ == "__main__":
    test_dedup_collapses_repeat_filers_into_one_entry_each()
    test_dedup_spans_multiple_pages()
    test_excluded_ciks_are_never_returned()
    test_stops_once_max_results_distinct_companies_found()
    print("\nALL HEALTHY-SAMPLE-DIVERSITY TESTS PASSED")
