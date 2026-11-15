"""
Validates dashboard/data/insolvency_cases.json, the hand-curated Insolvency
Watch list. It's edited by hand, so this guards the things that would
silently mislead a reader:

  * every case cites at least one https source;
  * dates are real dates, and an outcome never precedes its admission;
  * the outcome fields agree with each other (an "acquired" case names an
    acquirer, a liquidated one doesn't, an "ongoing" one has no recovery);
  * recovery percentages are plausible and always carry a note;
  * the in_training_labels flags match data/sources/india_distress_labels.csv
    exactly, because the page relies on them to never show a model score for
    a company the model trained on.

Run from the project root: python tests/test_insolvency_data.py
"""
import csv
import json
import os
import re
from datetime import date

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(_ROOT, "dashboard", "data", "insolvency_cases.json")
TRAINING_LABELS = os.path.join(_ROOT, "data", "sources", "india_distress_labels.csv")

OUTCOMES = {"acquired", "liquidated", "ongoing"}
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")  # day optional where only the month is sourced


def _parse(d: str) -> date:
    """YYYY-MM-DD, or YYYY-MM read as the first of the month."""
    assert DATE_RE.match(d), f"bad date format: {d!r}"
    parts = [int(x) for x in d.split("-")]
    return date(parts[0], parts[1], parts[2] if len(parts) == 3 else 1)


def _norm(name: str) -> str:
    n = name.lower().replace("(india)", "").replace("&", "and")
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(ltd|limited|india)\b", " ", n)
    return " ".join(n.split())


with open(DATA) as f:
    DOC = json.load(f)
CASES = DOC["cases"]


def test_document_header():
    for key in ("title", "status_as_of", "method", "training_data_note", "cases"):
        assert DOC.get(key), f"missing top-level {key}"
    _parse(DOC["status_as_of"])
    assert len(CASES) >= 15, "expected a meaningful number of cases"
    print(f"PASS: header present, {len(CASES)} cases, status as of {DOC['status_as_of']}")


def test_ids_unique_and_fields_present():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    required = ["id", "company", "industry", "rbi_first_list", "admitted", "outcome", "outcome_event",
                "outcome_date", "acquirer", "recovery_pct", "recovery_note", "summary",
                "in_training_labels", "sources"]
    for c in CASES:
        missing = [k for k in required if k not in c]
        assert not missing, f"{c.get('id')}: missing {missing}"
        assert c["company"].strip() and c["summary"].strip() and c["outcome_event"].strip(), c["id"]
    print("PASS: unique ids, every field present")


def test_every_case_is_sourced():
    for c in CASES:
        assert c["sources"], f"{c['id']}: no sources"
        for s in c["sources"]:
            assert s["label"].strip(), f"{c['id']}: unlabelled source"
            assert s["url"].startswith("https://"), f"{c['id']}: non-https source {s['url']}"
    print("PASS: every case cites at least one labelled https source")


def test_dates_and_outcome_consistency():
    today = _parse(DOC["status_as_of"])
    for c in CASES:
        admitted = _parse(c["admitted"])
        assert date(2016, 12, 1) <= admitted <= today, f"{c['id']}: admitted {admitted} outside the IBC era"
        assert c["outcome"] in OUTCOMES, f"{c['id']}: unknown outcome {c['outcome']}"

        if c["outcome_date"] is not None:
            od = _parse(c["outcome_date"])
            assert admitted <= od <= today, f"{c['id']}: outcome {od} before admission or in the future"

        if c["outcome"] == "acquired":
            assert c["acquirer"], f"{c['id']}: acquired but no acquirer"
            assert c["outcome_date"], f"{c['id']}: acquired but no outcome date"
        if c["outcome"] == "liquidated":
            assert c["acquirer"] is None, f"{c['id']}: liquidated cases have no acquirer"
            assert c["outcome_date"], f"{c['id']}: liquidated but no date"
        if c["outcome"] == "ongoing":
            assert c["acquirer"] is None and c["recovery_pct"] is None, f"{c['id']}: ongoing case claims a result"
    counts = {o: sum(c["outcome"] == o for c in CASES) for o in sorted(OUTCOMES)}
    print(f"PASS: dates valid and ordered; outcomes consistent {counts}")


def test_recovery_values_are_plausible_and_explained():
    for c in CASES:
        r = c["recovery_pct"]
        if r is None:
            continue
        assert isinstance(r, (int, float)) and 0 < r <= 100, f"{c['id']}: recovery {r}"
        assert c["recovery_note"], f"{c['id']}: a recovery figure needs a note on its basis"
    n = sum(c["recovery_pct"] is not None for c in CASES)
    print(f"PASS: {n} recovery figures, all within 0-100% and annotated")


def test_training_flags_match_training_labels():
    with open(TRAINING_LABELS) as f:
        distressed = {_norm(r["company_name"]) for r in csv.DictReader(f) if r["label_distressed"] == "1"}
    flagged = {_norm(c["company"]) for c in CASES if c["in_training_labels"]}
    unflagged = {_norm(c["company"]) for c in CASES if not c["in_training_labels"]}

    missing_flag = distressed & unflagged
    assert not missing_flag, f"in training labels but not flagged: {missing_flag}"
    wrong_flag = flagged - distressed
    assert not wrong_flag, f"flagged but not in training labels: {wrong_flag}"
    print(f"PASS: in_training_labels matches india_distress_labels.csv ({len(flagged)} companies)")


if __name__ == "__main__":
    test_document_header()
    test_ids_unique_and_fields_present()
    test_every_case_is_sourced()
    test_dates_and_outcome_consistency()
    test_recovery_values_are_plausible_and_explained()
    test_training_flags_match_training_labels()
    print("\nAll insolvency data tests passed.")
