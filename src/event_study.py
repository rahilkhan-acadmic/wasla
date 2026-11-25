"""
Daily-data event study for the Event Breakout section
(doc/event-breakout-strategy.md, validation plan step 2).

How did Nifty 50, Nifty Bank and India VIX behave on the trading day each
scheduled macro event hit them, compared with ordinary days? Inputs:
  data/events/macro_events.json   the event calendar (release times in IST)
  data/events/index_daily.csv     NSE daily OHLC (data/events/fetch_index_history.py)

Questions (each a function below, all on daily data only):
  Q1 size        are |close-to-close| moves and intraday ranges bigger?
  Q2 follow      does the event day's direction continue next day / 5 days?
  Q3 gap_and_go  FOMC -> Nifty: when the next open gaps > 0.5%, does the
                 rest of the day follow the gap or fade it?
  Q4 budget      Budget day: big range, small close?
  Q5 vix         India VIX into and out of events (volatility crush?)

Each event-day statistic is compared with a baseline of ordinary trading
days (excluding every event reaction day and the day either side). With
only ~6-8 events a year, "how unusual is this" is answered by a bootstrap:
draw the same number of baseline days many times and see how often the
baseline is as extreme. Small samples: read results as descriptive.

Usage: python src/event_study.py   (writes data/events/event_study_results.json)
"""

import csv
import datetime
import json
import math
import os
import random
from typing import Optional

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EVENTS_PATH = os.path.join(_ROOT, "data", "events", "macro_events.json")
PRICES_PATH = os.path.join(_ROOT, "data", "events", "index_daily.csv")
RESULTS_PATH = os.path.join(_ROOT, "data", "events", "event_study_results.json")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
SESSION_CLOSE = datetime.time(15, 30)
GAP_THRESHOLD = 0.005  # 0.5%, the FOMC -> Nifty "gap and go" rule
BOOTSTRAP_REPS = 5000
SEED = 20261125


# --------------------------------------------------------------------- data

def load_prices(path: str = PRICES_PATH) -> dict[str, list[dict]]:
    """{index: [{date, open, high, low, close}, ...]} sorted by date."""
    out: dict[str, list[dict]] = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            out.setdefault(r["index"], []).append({
                "date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"])})
    for rows in out.values():
        rows.sort(key=lambda r: r["date"])
    return out


def load_events(path: str = EVENTS_PATH) -> list[dict]:
    with open(path) as f:
        return [e for e in json.load(f)["events"] if e["status"] == "past"]


def release_time(event: dict) -> datetime.datetime:
    if event.get("release_ist"):
        return datetime.datetime.fromisoformat(event["release_ist"])
    # Unscheduled RBI meeting (2022-05-04): time not verified; it fell
    # inside the trading session either way, so map it to that day.
    return datetime.datetime.fromisoformat(event["date"] + "T12:00:00+05:30")


def reaction_index(event: dict, dates: list[str]) -> Optional[int]:
    """Index of the first trading day whose session close (15:30 IST) comes
    after the release: RBI 10:00 and Budget 11:00 -> that day; FOMC 23:30 IST
    -> next session; FOMC 00:30 IST (US winter) -> that morning's session."""
    rel = release_time(event)
    for i, d in enumerate(dates):
        close = datetime.datetime.combine(datetime.date.fromisoformat(d), SESSION_CLOSE, tzinfo=IST)
        if close > rel:
            return i
    return None


def day_metrics(rows: list[dict], i: int) -> Optional[dict]:
    """Daily reaction metrics for trading day i (needs day i-4 and i+5)."""
    if i < 4 or i + 5 >= len(rows):
        return None
    prev, d = rows[i - 1]["close"], rows[i]
    return {
        "date": d["date"],
        "ret": d["close"] / prev - 1,                       # close to close
        "gap": d["open"] / prev - 1,                        # overnight
        "intraday": d["close"] / d["open"] - 1,             # open to close
        "range": (d["high"] - d["low"]) / prev,             # high-low
        "next1": rows[i + 1]["close"] / d["close"] - 1,
        "next5": rows[i + 5]["close"] / d["close"] - 1,
        "pre3": prev / rows[i - 4]["close"] - 1,            # 3 days into the event
    }


# ---------------------------------------------------------------- helpers

def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_p(observed: float, pool: list[float], k: int, reps: int = BOOTSTRAP_REPS,
                seed: int = SEED, upper: bool = True) -> float:
    """Share of random size-k draws (with replacement) from the baseline pool
    whose mean is at least (upper) / at most (lower) the observed mean."""
    if not pool or k == 0:
        return float("nan")
    rng = random.Random(seed)
    hits = 0
    for _ in range(reps):
        m = sum(rng.choice(pool) for _ in range(k)) / k
        hits += (m >= observed) if upper else (m <= observed)
    return hits / reps


def same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def r4(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 4)


# ------------------------------------------------------------------ study

def build_days(prices: dict[str, list[dict]], events: list[dict]):
    """Per index: event reaction metrics by type, and baseline metrics."""
    out = {}
    for index, rows in prices.items():
        dates = [r["date"] for r in rows]
        reaction = {}  # date -> list of event types hitting it
        by_type: dict[str, list[dict]] = {}
        for e in events:
            i = reaction_index(e, dates)
            if i is None:
                continue
            m = day_metrics(rows, i)
            if m is None:
                continue
            m = {**m, "event": e["id"]}
            by_type.setdefault(e["type"], []).append(m)
            reaction.setdefault(i, []).append(e["type"])
        near = {j for i in reaction for j in (i - 1, i, i + 1)}
        baseline = [m for i in range(len(rows)) if i not in near and (m := day_metrics(rows, i))]
        out[index] = {"events": by_type, "baseline": baseline}
    return out


def q1_size(ev, base):
    res = {"n": len(ev)}
    for key in ("ret", "range"):
        obs = mean(abs(m[key]) for m in ev)
        pool = [abs(m[key]) for m in base]
        res[f"mean_abs_{key}"] = r4(obs)
        res[f"baseline_mean_abs_{key}"] = r4(mean(pool))
        res[f"ratio_{key}"] = r4(obs / mean(pool)) if pool else None
        res[f"p_{key}_bigger"] = r4(bootstrap_p(obs, pool, len(ev)))
    return res


def q2_follow(ev, base):
    res = {"n": len(ev)}
    for key in ("next1", "next5"):
        rate = mean(1.0 if same_sign(m["ret"], m[key]) else 0.0 for m in ev)
        pool = [1.0 if same_sign(m["ret"], m[key]) else 0.0 for m in base]
        res[f"continue_{key}"] = r4(rate)
        res[f"baseline_continue_{key}"] = r4(mean(pool))
    return res


def q3_gap_and_go(ev, base, threshold=GAP_THRESHOLD):
    def tally(ms):
        big = [m for m in ms if abs(m["gap"]) > threshold]
        go = sum(1 for m in big if same_sign(m["gap"], m["intraday"]))
        return big, go
    big, go = tally(ev)
    bbig, bgo = tally(base)
    return {"n_events": len(ev), "n_big_gap": len(big), "gap_and_go": go, "gap_fade": len(big) - go,
            "go_rate": r4(go / len(big)) if big else None,
            "baseline_n_big_gap": len(bbig), "baseline_go_rate": r4(bgo / len(bbig)) if bbig else None,
            "events": [{"event": m["event"], "gap": r4(m["gap"]), "intraday": r4(m["intraday"])} for m in big]}


def q4_budget(ev, base):
    ratio = lambda ms: mean(abs(m["ret"]) for m in ms) / mean(m["range"] for m in ms) if ms else None  # noqa: E731
    return {"n": len(ev), "mean_range": r4(mean(m["range"] for m in ev)),
            "mean_abs_close": r4(mean(abs(m["ret"]) for m in ev)),
            "close_to_range": r4(ratio(ev)), "baseline_close_to_range": r4(ratio(base)),
            "days": [{"event": m["event"], "ret": r4(m["ret"]), "range": r4(m["range"]),
                      "next5": r4(m["next5"])} for m in ev]}


def q5_vix(ev, base):
    obs_day, obs_pre = mean(m["ret"] for m in ev), mean(m["pre3"] for m in ev)
    return {"n": len(ev),
            "mean_vix_change_on_day": r4(obs_day), "baseline_mean_vix_change": r4(mean(m["ret"] for m in base)),
            "p_falls_on_day": r4(bootstrap_p(obs_day, [m["ret"] for m in base], len(ev), upper=False)),
            "mean_vix_change_3d_before": r4(obs_pre), "baseline_mean_vix_3d": r4(mean(m["pre3"] for m in base)),
            "p_rises_before": r4(bootstrap_p(obs_pre, [m["pre3"] for m in base], len(ev)))}


def run(prices=None, events=None) -> dict:
    prices = prices if prices is not None else load_prices()
    events = events if events is not None else load_events()
    days = build_days(prices, events)
    results = {"generated_from": {"events": len(events),
                                  "price_days": {k: len(v) for k, v in prices.items()},
                                  "span": [min(r[0]["date"] for r in prices.values()),
                                           max(r[-1]["date"] for r in prices.values())]},
               "questions": {}}
    q = results["questions"]
    for index in ("NIFTY50", "NIFTYBANK"):
        if index not in days:
            continue
        d = days[index]
        for etype, ev in sorted(d["events"].items()):
            q.setdefault("q1_size", {}).setdefault(index, {})[etype] = q1_size(ev, d["baseline"])
            q.setdefault("q2_follow", {}).setdefault(index, {})[etype] = q2_follow(ev, d["baseline"])
        if "fomc" in d["events"]:
            q.setdefault("q3_gap_and_go", {})[index] = q3_gap_and_go(d["events"]["fomc"], d["baseline"])
        if "union_budget" in d["events"]:
            q.setdefault("q4_budget", {})[index] = q4_budget(d["events"]["union_budget"], d["baseline"])
    if "INDIAVIX" in days:
        d = days["INDIAVIX"]
        q["q5_vix"] = {etype: q5_vix(ev, d["baseline"]) for etype, ev in sorted(d["events"].items())}
    return results


def main():
    res = run()
    with open(RESULTS_PATH, "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res["generated_from"]))
    for name, block in res["questions"].items():
        print(f"\n== {name} ==")
        print(json.dumps(block, indent=1)[:4000])


if __name__ == "__main__":
    main()
