"""
Event Watch: what the dashboard's Event Watch section shows.

Combines the event calendar (data/events/macro_events.json) with the
daily-data study (data/events/event_study_results.json, from
src/event_study.py) into, for each event type and index:
  * probable movement   past event-day moves vs ordinary days
  * strategy record     wins / losses of the strategy rule (daily proxy)
  * confidence score    0-100, from visible components (below)
  * volatility note     what India VIX usually does around the event
plus the upcoming events and the latest India VIX close.

Confidence score: a rule with no edge over ordinary days scores 0 however
many events it has; otherwise
    score = 100 x evidence x edge x (0.5 + 0.5 significance) x (0.5 + 0.5 stability)
  evidence      min(trades, 30) / 30           enough past cases?
  edge          (win rate - ordinary-day win rate) / 0.20, clipped to 0..1
  significance  1 at p <= 0.05, 0 at p >= 0.5 (bootstrap vs ordinary days)
  stability     share of the two halves of history (earlier / later) in
                which the win rate beat ordinary days
Labels: < 20 low, < 50 moderate, else high. A research signal from small
samples, not a forecast and not investment advice.
"""

import csv
import datetime
import json
import os
from typing import Optional

import event_study

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EVENTS_PATH = os.path.join(_ROOT, "data", "events", "macro_events.json")
RESULTS_PATH = os.path.join(_ROOT, "data", "events", "event_study_results.json")
PRICES_PATH = os.path.join(_ROOT, "data", "events", "index_daily.csv")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
HORIZON_DAYS = 60
INDEX_NAMES = {"NIFTY50": "Nifty 50", "NIFTYBANK": "Nifty Bank"}

EVENT_INFO = {
    "rbi_mpc": {
        "label": "RBI policy (MPC)",
        "rule": "Follow-through: after the decision, trade the day's direction from the close to the next close.",
        "nse_note": "Decision at 10:00 IST, press conference 12:00, both during NSE hours.",
    },
    "fomc": {
        "label": "US Fed (FOMC)",
        "rule": "Gap and go: if Nifty opens more than 0.5% away after the Fed, trade the gap's direction to the close.",
        "nse_note": "Decision lands at 23:30 / 00:30 IST while NSE is closed; Nifty reacts at the next open.",
    },
    "union_budget": {
        "label": "Union Budget",
        "rule": "Follow-through: after the speech, trade the day's direction from the close to the next close.",
        "nse_note": "Speech from 11:00 IST during a trading session (special session on weekends).",
    },
}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def confidence(trade: dict) -> dict:
    n = trade.get("trades") or 0
    wr, base = trade.get("win_rate"), (trade.get("baseline") or {}).get("win_rate")
    p = trade.get("p_avg_beats_baseline")
    evidence = min(n, 30) / 30
    edge = _clip((wr - base) / 0.20) if wr is not None and base is not None else 0.0
    significance = _clip((0.5 - p) / 0.45) if p is not None else 0.0
    each = trade.get("each") or []
    half = len(each) // 2
    halves = [each[:half], each[half:]] if half else []
    beats = 0
    for h in halves:
        if h and base is not None and sum(1 for t in h if t["return"] > 0) / len(h) > base:
            beats += 1
    stability = beats / 2 if halves else 0.0
    score = round(100 * evidence * edge * (0.5 + 0.5 * significance) * (0.5 + 0.5 * stability))
    label = "low" if score < 20 else "moderate" if score < 50 else "high"
    if wr is not None and base is not None and wr < base - 0.10 and (trade.get("avg_return") or 0) < 0:
        verdict = "Lost money in the past, clearly worse than ordinary days: avoid this rule."
    elif wr is not None and base is not None and wr < base:
        verdict = "No edge: did slightly worse than ordinary days."
    elif score < 20:
        verdict = "No reliable edge in the past data."
    else:
        verdict = "Showed an edge in the past data; small sample, not a guarantee."
    return {"score": score, "label": label, "verdict": verdict,
            "components": {"evidence": round(evidence, 2), "edge": round(edge, 2),
                           "significance": round(significance, 2), "stability": round(stability, 2)}}


def type_card(etype: str, results: dict) -> dict:
    q, trades = results["questions"], results["trades"]
    by_index = {}
    for idx in ("NIFTY50", "NIFTYBANK"):
        size = q["q1_size"].get(idx, {}).get(etype)
        trade = trades.get(idx, {}).get(etype)
        if not size or not trade:
            continue
        by_index[idx] = {
            "name": INDEX_NAMES[idx],
            "movement": {k: size[k] for k in ("n", "abs_ret_p50", "abs_ret_p80", "baseline_abs_ret_p50",
                                              "baseline_abs_ret_p80", "range_p50", "mean_abs_range",
                                              "baseline_mean_abs_range", "up", "down", "each")},
            "record": {k: trade[k] for k in ("trades", "wins", "losses", "win_rate", "avg_return",
                                             "worst", "best", "baseline", "each", "proxy", "cost_per_trade")},
            "confidence": confidence(trade),
        }
    vix = q.get("q5_vix", {}).get(etype)
    return {"type": etype, **EVENT_INFO[etype], "by_index": by_index,
            "vix": {k: vix[k] for k in ("n", "mean_vix_change_on_day", "baseline_mean_vix_change",
                                        "mean_vix_change_3d_before")} if vix else None}


def reaction_session(release: datetime.datetime) -> str:
    """Approximate NSE session the event hits: same day if released before
    the 15:30 IST close, else the next weekday (NSE holidays not modelled)."""
    d = release.astimezone(IST)
    day = d.date() if d.time() < event_study.SESSION_CLOSE else d.date() + datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day.isoformat()


def upcoming(events: list[dict], now: datetime.datetime, horizon_days: int = HORIZON_DAYS) -> list[dict]:
    out = []
    for e in events:
        if e["status"] != "upcoming" or not e.get("release_ist"):
            continue
        rel = datetime.datetime.fromisoformat(e["release_ist"])
        if rel < now - datetime.timedelta(hours=12) or rel > now + datetime.timedelta(days=horizon_days):
            continue
        out.append({"id": e["id"], "type": e["type"], "label": EVENT_INFO[e["type"]]["label"],
                    "date": e["date"], "release_ist": e["release_ist"],
                    "second_stage_ist": e.get("second_stage_ist"),
                    "nse_session": reaction_session(rel),
                    "hours_away": round((rel - now).total_seconds() / 3600, 1),
                    "source": e["source"]["url"]})
    return sorted(out, key=lambda x: x["release_ist"])


def latest_vix(path: str = PRICES_PATH) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    rows = [r for r in csv.DictReader(open(path)) if r["index"] == "INDIAVIX"]
    if not rows:
        return None
    last = max(rows, key=lambda r: r["date"])
    closes = sorted(float(r["close"]) for r in rows)
    pct_rank = sum(1 for c in closes if c <= float(last["close"])) / len(closes)
    return {"date": last["date"], "close": float(last["close"]), "percentile_5y": round(pct_rank, 2)}


_cache: dict = {}


def build(now: Optional[datetime.datetime] = None) -> dict:
    now = now or datetime.datetime.now(IST)
    if "static" not in _cache:
        with open(EVENTS_PATH) as f:
            cal = json.load(f)
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        _cache["static"] = {
            "events": cal["events"],
            "calendar_as_of": cal["as_of"],
            "study_span": results["generated_from"]["span"],
            "cards": {t: type_card(t, results) for t in EVENT_INFO},
            "vix": latest_vix(),
        }
    s = _cache["static"]
    return {"generated_at": now.isoformat(timespec="minutes"),
            "calendar_as_of": s["calendar_as_of"], "study_span": s["study_span"],
            "upcoming": upcoming(s["events"], now), "cards": s["cards"], "latest_vix": s["vix"],
            "disclaimer": "Research from small samples of past events, on daily data. Not investment advice."}
