"""
Tests for src/event_study.py (Event Breakout daily-data study) on synthetic
prices with known answers. No network, no real data needed.

The easy-to-get-wrong part is which trading day an event hits:
  * RBI 10:00 IST and Budget 11:00 IST -> that day's session;
  * FOMC 23:30 IST (US summer) -> the NEXT session;
  * FOMC 00:30 IST next day (US winter) -> that morning's session;
  * a weekend Budget session -> that weekend day, if it traded.

Run from the project root: python tests/test_event_study.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import event_study as es  # noqa: E402


def _rows(dates, closes, opens=None, highs=None, lows=None):
    opens = opens or closes
    return [{"date": d, "open": o, "high": h if highs else max(o, c) * 1.002,
             "low": l if lows else min(o, c) * 0.998, "close": c}
            for d, o, c, h, l in zip(dates, opens, closes, highs or closes, lows or closes)]


def _weekdays(start, n):
    out, d = [], datetime.date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def test_reaction_day_mapping():
    dates = ["2024-11-06", "2024-11-07", "2024-11-08", "2024-11-11",
             "2022-06-15", "2022-06-16", "2025-01-31", "2025-02-01", "2025-02-03"]
    dates.sort()
    ev = lambda rel: {"release_ist": rel, "date": rel[:10]}  # noqa: E731
    pick = lambda rel: dates[es.reaction_index(ev(rel), dates)]  # noqa: E731
    assert pick("2024-11-07T10:00:00+05:30") == "2024-11-07"        # RBI-style, in session
    assert pick("2022-06-15T23:30:00+05:30") == "2022-06-16"        # FOMC, US summer -> next day
    assert pick("2024-11-08T00:30:00+05:30") == "2024-11-08"        # FOMC, US winter -> same morning
    assert pick("2025-02-01T11:00:00+05:30") == "2025-02-01"        # Saturday Budget session
    assert pick("2024-11-07T15:45:00+05:30") == "2024-11-08"        # after the close -> next day
    unscheduled = {"release_ist": None, "date": "2022-06-15"}
    assert dates[es.reaction_index(unscheduled, dates)] == "2022-06-15"
    print("PASS: reaction day: RBI/Budget same day, FOMC 23:30 -> next session, 00:30 -> same morning")


def test_day_metrics_math():
    rows = _rows(["d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9"],
                 closes=[100, 100, 100, 100, 100, 102, 103, 103, 103, 104],
                 opens=[100, 100, 100, 100, 100, 101, 103, 103, 103, 104],
                 highs=[100, 100, 100, 100, 100, 103, 103, 103, 103, 104],
                 lows=[100, 100, 100, 100, 100, 99, 103, 103, 103, 104])
    m = es.day_metrics(rows, 4)
    assert m is not None and m["ret"] == 0
    rows += _rows(["d10"], [104])  # day 5 needs 5 days ahead
    m = es.day_metrics(rows, 5)
    assert abs(m["ret"] - 0.02) < 1e-12 and abs(m["gap"] - 0.01) < 1e-12
    assert abs(m["intraday"] - (102 / 101 - 1)) < 1e-12 and abs(m["range"] - 0.04) < 1e-12
    assert abs(m["next1"] - (103 / 102 - 1)) < 1e-12 and abs(m["next5"] - (104 / 102 - 1)) < 1e-12
    assert es.day_metrics(rows, 3) is None and es.day_metrics(rows, 6) is None  # not enough history/future
    print("PASS: ret / gap / intraday / range / next1 / next5 computed from prev close")


def test_study_detects_bigger_moves_and_gap_and_go():
    # 400 quiet days (+-0.2%); every 20th day an "event" with a 2% gap that
    # keeps going (+1% more intraday). The study must see bigger moves, a
    # gap-and-go rate of 1.0, and exclude event days (+-1) from the baseline.
    dates = _weekdays("2022-01-03", 400)
    closes, opens, events = [], [], []
    price = 1000.0
    for i, d in enumerate(dates):
        if i % 20 == 10:
            o = price * 1.02
            c = o * 1.01
            events.append({"id": f"fomc-{d}", "type": "fomc", "status": "past",
                           "release_ist": f"{d}T00:30:00+05:30", "date": d})
        else:
            o = price
            c = price * (1.002 if i % 2 else 0.998)
        opens.append(o)
        closes.append(c)
        price = c
    prices = {"NIFTY50": _rows(dates, closes, opens)}
    res = es.run(prices, events)
    q1 = res["questions"]["q1_size"]["NIFTY50"]["fomc"]
    assert q1["n"] == len(events) - 1 or q1["n"] == len(events), q1  # last may lack 5 days ahead
    assert q1["ratio_ret"] > 10 and q1["p_ret_bigger"] < 0.01, q1
    q3 = res["questions"]["q3_gap_and_go"]["NIFTY50"]
    assert q3["go_rate"] == 1.0 and q3["n_big_gap"] == q1["n"], q3
    assert q3["baseline_n_big_gap"] == 0, "event days and neighbours must not leak into the baseline"
    print(f"PASS: synthetic events: |ret| {q1['ratio_ret']}x baseline (p={q1['p_ret_bigger']}), "
          f"gap-and-go {q3['go_rate']}, baseline clean")


def test_bootstrap_is_deterministic_and_directional():
    pool = [0.0, 0.0, 0.0, 1.0]
    p1 = es.bootstrap_p(0.9, pool, 5)
    assert p1 == es.bootstrap_p(0.9, pool, 5), "fixed seed -> same answer"
    assert p1 < 0.05 and es.bootstrap_p(0.1, pool, 5) > 0.5
    assert es.bootstrap_p(0.0, pool, 5, upper=False) > 0.2
    print("PASS: bootstrap p-values deterministic and in the right direction")


def test_trade_outcomes_daily_proxies():
    m = lambda **k: {"event": "e", "date": "d", "gap": 0.0, "intraday": 0.0, "ret": 0.0, "next1": 0.0, **k}  # noqa: E731
    ev = [m(gap=0.01, intraday=0.004),    # gap up, kept going: win
          m(gap=-0.008, intraday=0.003),  # gap down, faded: loss
          m(gap=0.002, intraday=0.01)]    # gap < 0.5%: no trade
    t = es.trade_outcomes(ev, [m(gap=0.006, intraday=-0.001)], "gap_and_go")
    assert (t["trades"], t["wins"], t["losses"]) == (2, 1, 1), t
    assert abs(t["each"][0]["return"] - (0.004 - es.COST)) < 1e-4
    assert t["baseline"]["trades"] == 1 and t["proxy"] == "daily"
    ft = es.trade_outcomes([m(ret=0.01, next1=0.002), m(ret=-0.01, next1=0.004), m(ret=0.0, next1=0.05)],
                           [], "follow_through")
    assert (ft["trades"], ft["wins"]) == (2, 1), ft   # flat day -> no trade
    # A tiny gain smaller than the cost is a loss.
    tiny = es.trade_outcomes([m(gap=0.01, intraday=0.0003)], [], "gap_and_go")
    assert tiny["wins"] == 0
    print("PASS: trade outcomes: gap-and-go and follow-through daily proxies, costs, no-trade days")


if __name__ == "__main__":
    test_reaction_day_mapping()
    test_day_metrics_math()
    test_study_detects_bigger_moves_and_gap_and_go()
    test_bootstrap_is_deterministic_and_directional()
    test_trade_outcomes_daily_proxies()
    print("\nAll event study tests passed.")
