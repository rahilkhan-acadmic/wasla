"""
Validates data/events/macro_events.json, the hand-curated calendar of
scheduled macro events (RBI MPC, FOMC, Union Budget) behind the Event
Breakout study (doc/event-breakout-strategy.md).

Hand-edited data goes wrong quietly: a typo'd date, a rate that doesn't
follow from the previous one, an FOMC time that ignores US daylight saving.
This test catches those before they skew a backtest.

Run from the project root: python tests/test_macro_events.py
"""
import datetime
import json
import os
from zoneinfo import ZoneInfo

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(_ROOT, "data", "events", "macro_events.json")

IST = ZoneInfo("Asia/Kolkata")
ET = ZoneInfo("America/New_York")
TYPES = {"rbi_mpc", "fomc", "union_budget"}
QUALITIES = {"official", "press", "consolidated"}


def load():
    with open(PATH) as f:
        return json.load(f)


def test_structure_ids_order_and_sources():
    doc = load()
    events = doc["events"]
    as_of = doc["as_of"]
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids)), "duplicate event ids"
    assert [e["date"] for e in events] == sorted(e["date"] for e in events), "events must be in date order"
    for e in events:
        assert e["type"] in TYPES, e
        assert e["id"] == f"{ {'rbi_mpc': 'rbi', 'fomc': 'fomc', 'union_budget': 'budget'}[e['type']] }-{e['date']}", e["id"]
        datetime.date.fromisoformat(e["date"])
        assert e["status"] == ("past" if e["date"] <= as_of else "upcoming"), e["id"]
        assert e["source"]["url"].startswith("https://"), e["id"]
        assert e["source"]["quality"] in QUALITIES, e["id"]
        if e["surprise"] is not None:
            # A surprise flag must say why and cite where it came from.
            assert isinstance(e["surprise"]["flag"], bool) and e["surprise"]["basis"], e["id"]
            assert e["surprise"]["source"].startswith("https://"), e["id"]
        if e["release_ist"]:
            t = datetime.datetime.fromisoformat(e["release_ist"])
            assert t.utcoffset() == datetime.timedelta(hours=5, minutes=30), e["id"]
    print(f"PASS: {len(events)} events: unique ids, date order, status vs as_of {as_of}, sourced")


def _check_rate_path(events, start_rate, label):
    rate = start_rate
    for e in events:
        d = e["decision"]
        if e["status"] == "upcoming":
            assert d is None, f"{e['id']}: an upcoming event can't have a decision"
            continue
        assert d is not None, f"{e['id']}: past {label} decision missing"
        rate = round(rate + d["change_bps"] / 100, 2)
        assert d["new_rate"] == rate, f"{e['id']}: new_rate {d['new_rate']} != previous + change = {rate}"
    return rate


def test_rbi_decisions_follow_on_from_each_other():
    rbi = [e for e in load()["events"] if e["type"] == "rbi_mpc"]
    final = _check_rate_path(rbi, 4.00, "RBI")  # repo was 4.00% from May 2020
    by_id = {e["id"]: e for e in rbi}
    # Anchor points from the sources: peak 6.50% (Feb 2023), 5.25% after Dec 2025,
    # 5.50% after the Oct 2026 hike.
    assert by_id["rbi-2023-02-08"]["decision"]["new_rate"] == 6.50
    assert by_id["rbi-2025-12-05"]["decision"]["new_rate"] == 5.25
    assert by_id["rbi-2026-10-07"]["decision"]["new_rate"] == 5.50 == final
    for e in rbi:
        wd = datetime.date.fromisoformat(e["date"]).weekday()
        assert wd < 5, f"{e['id']}: RBI decision on a weekend"
        if e["scheduled"]:
            assert e["release_ist"].endswith("T10:00:00+05:30") and e["second_stage_ist"].endswith("T12:00:00+05:30")
    unscheduled = [e["id"] for e in rbi if not e["scheduled"]]
    assert unscheduled == ["rbi-2022-05-04"], unscheduled
    print(f"PASS: {len(rbi)} RBI decisions; repo path 4.00% -> {final}% adds up; one off-cycle meeting")


def test_fomc_times_are_dst_aware_and_path_adds_up():
    fomc = [e for e in load()["events"] if e["type"] == "fomc"]
    final = _check_rate_path(fomc, 0.25, "FOMC")  # 0-0.25% from March 2020
    assert final == 4.00, final
    years = {}
    for e in fomc:
        years[e["date"][:4]] = years.get(e["date"][:4], 0) + 1
        d = datetime.date.fromisoformat(e["date"])
        if e["id"] != "fomc-2024-11-07":  # Thursday, US election week
            assert d.weekday() == 2, f"{e['id']}: FOMC decisions are on Wednesdays"
        et = datetime.datetime.combine(d, datetime.time(14, 0), tzinfo=ET)
        assert datetime.datetime.fromisoformat(e["release_et"]) == et, e["id"]
        assert datetime.datetime.fromisoformat(e["release_ist"]) == et.astimezone(IST), e["id"]
        assert e["nse_open_at_release"] is False
    assert all(n == 8 for n in years.values()), years  # 8 scheduled meetings a year
    by_id = {e["id"]: e for e in fomc}
    # Summer (EDT) -> 23:30 IST same day; winter (EST) -> 00:30 IST next day.
    assert by_id["fomc-2022-06-15"]["release_ist"] == "2022-06-15T23:30:00+05:30"
    assert by_id["fomc-2024-11-07"]["release_ist"] == "2024-11-08T00:30:00+05:30"
    print(f"PASS: {len(fomc)} FOMC decisions, 8 a year, DST-aware IST times; upper bound 0.25% -> {final}%")


def test_budgets():
    budgets = [e for e in load()["events"] if e["type"] == "union_budget"]
    dates = [e["date"] for e in budgets]
    assert dates == ["2021-02-01", "2022-02-01", "2023-02-01", "2024-02-01", "2024-07-23", "2025-02-01", "2026-02-01"]
    kinds = {e["date"]: e["kind"] for e in budgets}
    assert kinds["2024-02-01"] == "interim" and kinds["2024-07-23"] == "full"
    special = [e["date"] for e in budgets if e["special_session"]]
    assert special == ["2025-02-01", "2026-02-01"], special  # Saturday 2025, Sunday 2026
    print("PASS: 7 Union Budgets (incl. 2024 interim + full), weekend special sessions flagged")


if __name__ == "__main__":
    test_structure_ids_order_and_sources()
    test_rbi_decisions_follow_on_from_each_other()
    test_fomc_times_are_dst_aware_and_path_adds_up()
    test_budgets()
    print("\nAll macro event calendar tests passed.")
